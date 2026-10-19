"""族谱付印：PDF / Word 三步导出"""
import io
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, send_file

from server.common import ApiError
from server.db.conn import query, query_one
from server.service import audit, privacy, valid
from server.service.permission import current_user, require_family, require_login
from server.service.printutil import PAPER_MM, render_pdf, render_docx


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return default


def _body():
    """统一校验付印入参，避免字符串/对象落到排版代码触发 500。"""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError('请求体需为 JSON 对象')
    mode = body.get('mode', 'lineage')
    if mode not in ('lineage', 'person'):
        raise ApiError('付印模式不合法')
    paper = body.get('paper', 'A4')
    if not isinstance(paper, str) or paper.upper() not in PAPER_MM:
        raise ApiError('纸张参数不合法')
    paper = paper.upper()
    template = body.get('template', 'original')
    if not isinstance(template, str) or template not in ('original', 'traditional', 'european', 'compilation'):
        raise ApiError('付印模板不合法')
    generations = valid.to_int(body.get('generations'), 'generations', default=0)
    root_id = valid.to_int(body.get('root_id'), 'root_id', minimum=1) \
        if body.get('root_id') is not None else None
    if body.get('compiler') is not None and not isinstance(body['compiler'], str):
        raise ApiError('修辑者署名必须为文本')
    return {
        **body, 'mode': mode, 'paper': paper, 'template': template, 'generations': generations, 'root_id': root_id,
        'add_cover': _bool(body.get('add_cover'), True),
        'include_spouse': _bool(body.get('include_spouse'), False),
        'include_children': _bool(body.get('include_children'), False),
    }

bp = Blueprint('print', __name__, url_prefix='/api/families')


def _load(family_id, root_id, mode, generations):
    fam = query_one('SELECT * FROM family WHERE id=?', (family_id,))
    persons = query('SELECT * FROM person WHERE family_id=? ORDER BY generation, id', (family_id,))
    # 其他（男/女）可登记及显示，但不进入任何族谱付印正文或亲属附注。
    excluded = {p['id'] for p in persons if p['type'] in (7, 8)}
    if mode == 'person' and root_id in excluded:
        raise ApiError('其他类型成员不纳入族谱付印，请选择本谱成员')
    persons = [p for p in persons if p['id'] not in excluded]
    # 付印与详情页共用脱敏规则，普通成员不能借导出 PDF/Word 绕过隐私设置
    pmap = {p['id']: privacy.mask_person(p) for p in persons}
    children = {}
    for r in query('SELECT parent_id, child_id FROM parentchild WHERE family_id=?', (family_id,)):
        children.setdefault(r['parent_id'], []).append(r['child_id'])
    spouses = {}
    for m in query('SELECT spouse1_id, spouse2_id FROM marriage WHERE family_id=?', (family_id,)):
        spouses.setdefault(m['spouse1_id'], []).append(m['spouse2_id'])
        spouses.setdefault(m['spouse2_id'], []).append(m['spouse1_id'])

    if mode == 'person' and root_id:
        if root_id not in pmap:
            raise ApiError('主人物不存在或不属于本家谱')
        keep = set()
        stack = [root_id]
        while stack:
            pid = stack.pop()
            if pid in keep or pid not in pmap:
                continue
            keep.add(pid)
            stack.extend(children.get(pid, []))
        items = [pmap[i] for i in sorted(keep, key=lambda x: (pmap[x]['generation'], x))]
    else:
        items = [pmap[p['id']] for p in persons]
    if mode == 'person' and not root_id:
        raise ApiError('请选择主人物')
    if generations and generations > 0:
        base = pmap[root_id]['generation'] if mode == 'person' else min((p['generation'] for p in items), default=1)
        items = [p for p in items if p['generation'] < base + generations]
    return fam, items, pmap, children, spouses


def _lines(fam, items, pmap, children, spouses, opts):
    out = []
    parents = {}
    if opts.get('template', 'original') != 'original':
        for parent, kids in children.items():
            for child in kids:
                parents.setdefault(child, []).append(parent)
    by_gen = {}
    for p in items:
        by_gen.setdefault(p['generation'], []).append(p)
    for gen in sorted(by_gen):
        out.append(('h', f"第 {gen} 世"))
        for p in by_gen[gen]:
            name = p['name']
            extra = ' '.join(x for x in (p['courtesy_name'] and f"字{p['courtesy_name']}",
                                         p['art_name'] and f"号{p['art_name']}") if x)
            out.append(('p', f"{name}{('　' + extra) if extra else ''}"))
            known_parents = [pmap[pid]['name'] for pid in parents.get(p['id'], []) if pid in pmap]
            if known_parents:
                out.append(('s', '父母：' + '、'.join(known_parents)))
            born = p['birth_date'] or '生年不详'
            dead = p['death_date'] or '在世'
            out.append(('s', f"{born} — {dead}"))
            if p['birth_place']:
                out.append(('s', f"生于：{p['birth_place']}"))
            for field, label in (('address', '住址'), ('phone', '手机号'), ('company', '单位/公司'), ('position', '职位')):
                if p.get(field):
                    out.append(('s', f'{label}：{p[field]}'))
            if p['bury_address']:
                out.append(('s', f"葬：{p['bury_address']}"))
            if opts.get('include_spouse'):
                for sid in spouses.get(p['id'], []):
                    sp = pmap.get(sid)
                    if sp:
                        label = '妻' if sp['type'] in (2, 3, 6) else '夫'
                        out.append(('s', f"{label}：{sp['name']}"
                                    f"{('（' + sp['birth_date'] + '）') if sp['birth_date'] else ''}"))
                        if sp['record']:
                            out.append(('s', sp['record']))
            if opts.get('include_children'):
                for label, kinds in (('子', (1, 4, 5)), ('女', (2, 3, 6))):
                    kids = [pmap[c]['name'] for c in children.get(p['id'], []) if c in pmap and pmap[c]['type'] in kinds]
                    if kids:
                        out.append(('s', label + '：' + '、'.join(kids)))
            if p['record']:
                out.append(('s', p['record']))
            out.append(('gap', ''))
    return out


@bp.post('/<int:family_id>/print/estimate')
@require_login
@require_family('member')
def estimate(family_id):
    body = _body()
    fam, items, pmap, children, spouses = _load(
        family_id, body.get('root_id'), body.get('mode', 'lineage'), body.get('generations'))
    content = _lines(fam, items, pmap, children, spouses, body)
    _, pages = render_pdf(fam, content, body)
    return jsonify({'code': 0, 'msg': 'ok',
                    'data': {'persons': len(items), 'pages': pages}})


@bp.post('/<int:family_id>/print/pdf')
@require_login
@require_family('member')
def print_pdf(family_id):
    body = _body()
    fam, items, pmap, children, spouses = _load(
        family_id, body.get('root_id'), body.get('mode', 'lineage'), body.get('generations'))
    now = datetime.now(timezone(timedelta(hours=8)))
    blob, _ = render_pdf(fam, _lines(fam, items, pmap, children, spouses, body), body)
    buf = io.BytesIO(blob)
    audit.log(current_user()['id'], family_id, 'print_pdf', 'family', family_id)
    stamp = now.strftime('%Y%m%d')
    return send_file(buf, as_attachment=True,
                     download_name=f'{(fam["name"] if fam else "族谱")}_{stamp}.pdf',
                     mimetype='application/pdf')


@bp.post('/<int:family_id>/print/docx')
@require_login
@require_family('member')
def print_docx(family_id):
    body = _body()
    if body['template'] not in ('original', 'compilation'):
        raise ApiError('所选模板仅支持 PDF 导出，请选择 PDF')
    fam, items, pmap, children, spouses = _load(
        family_id, body.get('root_id'), body.get('mode', 'lineage'), body.get('generations'))
    now = datetime.now(timezone(timedelta(hours=8)))
    buf = io.BytesIO(render_docx(fam, _lines(fam, items, pmap, children, spouses, body), body))
    audit.log(current_user()['id'], family_id, 'print_docx', 'family', family_id)
    return send_file(buf, as_attachment=True,
                     download_name=f'{(fam["name"] if fam else "族谱")}_{now.strftime("%Y%m%d")}.docx',
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
