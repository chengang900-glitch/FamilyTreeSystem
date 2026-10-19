"""数据交换：导出 JSON / CSV / GEDCOM，导入 JSON / GEDCOM / ZIP

导入采用「旧 ID → 新 ID 重映射」：源数据里的 id 一律丢弃，关系表按映射表改写后再入库，
因此「导出 → 导入」可以闭环使用（同一份数据既可导入新谱，也可重复导入）。
ZIP 包内的 resources/ 原件会解出并存回上传目录。
"""
import csv
import io
import json
import tempfile
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from server.common import ApiError, now_str
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, dates, privacy, settings, valid
from server.service.filepath import safe_upload_path
from server.service.permission import current_user, require_family, require_login

bp = Blueprint('io', __name__, url_prefix='/api/families')

MODULES = ['family', 'branches', 'persons', 'marriages', 'parentchild', 'events',
           'eventpersons', 'resources', 'resource_relations']

# ZIP 导入资源限制：防止 zip bomb 把内存/磁盘打满
MAX_ZIP_FILES = 10000
MAX_ZIP_UNCOMPRESSED = 1024 * 1024 * 1024


def _load_json_payload(blob):
    try:
        data = json.loads(blob.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ApiError('JSON 数据包解析失败')
    if not isinstance(data, dict):
        raise ApiError('JSON 根节点需为对象')
    return data


def _check_zip(z):
    infos = z.infolist()
    if len(infos) > MAX_ZIP_FILES:
        raise ApiError(f'压缩包文件数超过 {MAX_ZIP_FILES} 个上限')
    total = sum(max(i.file_size, 0) for i in infos)
    if total > MAX_ZIP_UNCOMPRESSED:
        raise ApiError('压缩包解压后体积过大，已拒绝导入')
    return infos


def _collect(family_id, modules):
    data = {}
    if 'family' in modules:
        data['family'] = dict(query_one('SELECT * FROM family WHERE id=?', (family_id,)))
    for key, table in (('branches', 'branch'), ('persons', 'person'), ('marriages', 'marriage'),
                       ('parentchild', 'parentchild'), ('events', 'event'),
                       ('eventpersons', 'eventperson'), ('resources', 'resource'),
                       ('resource_relations', 'resource_relation')):
        if key in modules:
            rows = [dict(r) for r in query(f'SELECT * FROM {table} WHERE family_id=?'
                                           f' ORDER BY id', (family_id,))]
            if key == 'persons':
                # 导出与详情页使用同一套脱敏规则，普通成员不能借导出绕过隐私设置
                rows = [privacy.mask_person(r) for r in rows]
            data[key] = rows
    data['meta'] = {'exported_at': now_str(), 'version': '1.0',
                    'source': '家谱管理系统 Web 版'}
    return data


def _csv_safe(value):
    """防 CSV 公式注入：Excel 会把 = + - @ 开头的单元格当公式执行。"""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


def _csv_bytes(rows):
    buf = io.StringIO()
    if not rows:
        return b''
    safe_rows = [{k: _csv_safe(v) for k, v in row.items()} for row in rows]
    writer = csv.DictWriter(buf, fieldnames=list(safe_rows[0].keys()))
    writer.writeheader()
    writer.writerows(safe_rows)
    return buf.getvalue().encode('utf-8-sig')


def _gedcom(data):
    from server.service.gedcom import dumps
    return dumps(data)


@bp.get('/<int:family_id>/export')
@require_login
@require_family('member')
def export_data(family_id):
    fmt = (request.args.get('format') or 'json').lower()
    include_res = request.args.get('include_resources') in ('1', 'true', 'True')
    from flask import g
    privileged = getattr(g, 'family_role', None) == 'admin' or bool(current_user()['is_superuser'])
    if include_res and not privileged \
            and not settings.get_bool('export.member_include_resources', False):
        include_res = False
    modules = request.args.get('modules')
    mods = modules.split(',') if modules else MODULES

    data = _collect(family_id, mods)
    fam = data.get('family') or query_one('SELECT * FROM family WHERE id=?', (family_id,))
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    base = f'{fam["name"]}_export_{stamp}'

    if fmt == 'json' and not include_res:
        buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
        return send_file(buf, as_attachment=True, download_name=f'{base}.json',
                         mimetype='application/json')

    mem = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, mode='w+b')
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        if fmt == 'json':
            z.writestr('data.json', json.dumps(data, ensure_ascii=False, indent=2))
        elif fmt == 'zup':
            manifest = {
                'format': 'zup',
                'version': '1.0',
                'app': '家谱管理系统',
                'exported_at': now_str(),
                'family': {'name': fam['name'], 'slug': fam['slug']},
                'modules': [m for m in MODULES if m in data],
            }
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr('data.json', json.dumps(data, ensure_ascii=False, indent=2))
        elif fmt == 'csv':
            for key in ('persons', 'marriages', 'parentchild', 'events', 'eventpersons',
                        'branches', 'resources', 'resource_relations'):
                if key in data:
                    z.writestr(f'{key}.csv', _csv_bytes(data[key]))
            z.writestr('family.csv', _csv_bytes([data['family']] if 'family' in data else []))
        elif fmt == 'gedcom':
            z.writestr(f'{base}.ged', _gedcom(data))
        else:
            raise ApiError('不支持的导出格式')
        if include_res:
            for r in data.get('resources', []):
                try:
                    p = safe_upload_path(r['storage_path'], must_exist=True)
                except ApiError:
                    continue
                z.write(p, f'resources/{r["fid"]}_{r["name"]}{p.suffix}')
    mem.seek(0)
    audit.log(current_user()['id'], family_id, 'export', 'family', family_id, fmt)
    suffix = 'zup' if fmt == 'zup' else 'zip'
    return send_file(mem, as_attachment=True, download_name=f'{base}.{suffix}',
                     mimetype='application/zip')


# ---------------- 导入 ----------------
def _parse_gedcom(text):
    from server.service.gedcom import loads
    return loads(text)


def _gedcom_generations(persons, fams):
    """按家谱结构推算世代：无父母者=1 世，子女=父母最大世代+1"""
    parents_of = defaultdict(set)
    children_of = defaultdict(set)
    for family in fams.values():
        members = family['members']
        husb = next((v for t, v in members if t == 'husb'), None)
        wife = next((v for t, v in members if t == 'wife'), None)
        for tag, child in members:
            if tag != 'chil' or not child:
                continue
            for parent in (husb, wife):
                if parent:
                    parents_of[child].add(parent)
                    children_of[parent].add(child)
    gen = {}
    queue = deque()
    for p in persons:
        if p['id'] not in parents_of:
            gen[p['id']] = 1
            queue.append(p['id'])
    guard = len(persons) * 2 + 10
    while queue and guard > 0:
        guard -= 1
        cur = queue.popleft()
        for child in children_of.get(cur, ()):
            candidate = gen[cur] + 1
            if gen.get(child, 0) < candidate:
                gen[child] = candidate
                queue.append(child)
    # 环路中的人物无法定层，兜底为 1 世
    return {p['id']: gen.get(p['id'], 1) for p in persons}


def _clamp(value, low, high, default):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(num, low), high)


def _as_text(value):
    """导入包里的文本字段只接受字符串，避免 dict/list 落到 sqlite3 触发 500。"""
    return value if isinstance(value, str) else None


def _ref(value):
    """导入包中的旧 ID 只接受 int/str，避免不可哈希对象进入映射表。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)) and value != '':
        return value
    return None


def _rows(data, key):
    value = data.get(key) or []
    if not isinstance(value, list):
        raise ApiError(f'导入数据字段 {key} 需为数组')
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(f'导入数据字段 {key} 中存在非对象行')
    return value


def _assert_parentchild_acyclic(family_id):
    """导入结束后统一校验亲子关系不存在环。"""
    graph = defaultdict(list)
    for r in query('SELECT parent_id, child_id FROM parentchild WHERE family_id=?', (family_id,)):
        graph[int(r['parent_id'])].append(int(r['child_id']))
    color = {}
    for start in list(graph):
        if color.get(start, 0):
            continue
        color[start] = 1
        stack = [(start, iter(graph.get(start, ())))]
        while stack:
            node, it = stack[-1]
            try:
                nxt = next(it)
            except StopIteration:
                color[node] = 2
                stack.pop()
                continue
            state = color.get(nxt, 0)
            if state == 1:
                raise ApiError('导入数据存在亲属环路，请检查亲子关系')
            if state == 0:
                color[nxt] = 1
                stack.append((nxt, iter(graph.get(nxt, ()))))


def _assert_branch_acyclic(family_id):
    rows = query('SELECT id, parent_id FROM branch WHERE family_id=?', (family_id,))
    parents = {int(r['id']): (int(r['parent_id']) if r['parent_id'] is not None else None)
               for r in rows}
    for start in parents:
        seen = set()
        cur = start
        while cur is not None:
            if cur in seen:
                raise ApiError('导入数据存在分支层级环路，请检查上级分支')
            seen.add(cur)
            cur = parents.get(cur)


def _assert_import_acyclic(family_id):
    _assert_parentchild_acyclic(family_id)
    _assert_branch_acyclic(family_id)


def _clear_family_data(family_id):
    """覆盖导入/恢复前清空本谱业务数据；顺序满足外键 RESTRICT。"""
    for table in ('eventperson', 'resource_relation', 'marriage', 'parentchild',
                  'person', 'event', 'branch', 'resource'):
        execute(f'DELETE FROM {table} WHERE family_id=?', (family_id,))


def _cleanup_old_files(paths):
    """备份/恢复成功提交后删除旧资源文件；只处理上传目录内的安全路径。"""
    for rel in paths:
        try:
            path = safe_upload_path(rel)
        except ApiError:
            continue
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


@bp.get('/<int:family_id>/backup')
@require_login
@require_family('admin')
def family_backup(family_id):
    """家谱级备份：数据 + manifest + 资源原件，可用于本谱恢复或迁移。"""
    fam = query_one('SELECT name, slug FROM family WHERE id=?', (family_id,))
    if fam is None:
        raise ApiError('家谱不存在', code=404)
    data = _collect(family_id, MODULES)
    manifest = {
        'format': 'fts-family-backup',
        'version': '1.0',
        'app': '家谱管理系统',
        'exported_at': now_str(),
        'family': {'name': fam['name'], 'slug': fam['slug']},
    }
    mem = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, mode='w+b')
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr('data.json', json.dumps(data, ensure_ascii=False, indent=2))
        for r in data.get('resources', []):
            try:
                p = safe_upload_path(r['storage_path'], must_exist=True)
            except ApiError:
                continue
            z.write(p, f'resources/{r["fid"]}_{r["name"]}{p.suffix}')
    mem.seek(0)
    audit.log(current_user()['id'], family_id, 'backup_family', 'family', family_id)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    return send_file(mem, as_attachment=True,
                     download_name=f'{fam["name"]}_backup_{stamp}.zip',
                     mimetype='application/zip')


@bp.post('/<int:family_id>/restore')
@require_login
@require_family('admin')
def family_restore(family_id):
    """用家谱级备份 ZIP 覆盖恢复本谱数据。要求 manifest 标记为 fts-family-backup。"""
    file = request.files.get('file')
    if file is None:
        raise ApiError('请选择备份文件')
    if not (file.filename or '').lower().endswith('.zip'):
        raise ApiError('仅支持家谱备份 ZIP')
    try:
        with zipfile.ZipFile(io.BytesIO(file.read())) as z:
            infos = _check_zip(z)
            names = [i.filename for i in infos if not i.is_dir()]
            if 'manifest.json' not in names or 'data.json' not in names:
                raise ApiError('备份包缺少 manifest.json 或 data.json')
            manifest = _load_json_payload(z.read('manifest.json'))
            if manifest.get('format') != 'fts-family-backup':
                raise ApiError('备份包格式不匹配')
            data = _load_json_payload(z.read('data.json'))
            resource_files = _zip_resources(z, infos)
    except zipfile.BadZipFile:
        raise ApiError('备份 ZIP 已损坏')
    ts = now_str()
    old_files = [r['storage_path'] for r in
                 query('SELECT storage_path FROM resource WHERE family_id=?', (family_id,))]
    with transaction():
        _clear_family_data(family_id)
        fam_data = data.get('family') if isinstance(data.get('family'), dict) else {}
        allowed = ('name', 'surname', 'hall_name', 'generation_chars', 'origin_place',
                   'compiler', 'description')
        fields, args = [], []
        for key in allowed:
            if key in fam_data:
                fields.append(f'{key}=?')
                args.append(_as_text(fam_data.get(key)))
        if isinstance(fam_data.get('generation_frozen'), (bool, int)):
            fields.append('generation_frozen=?')
            args.append(1 if fam_data['generation_frozen'] else 0)
        if isinstance(fam_data.get('visibility'), (bool, int, str)):
            try:
                visibility = int(fam_data['visibility'])
            except (TypeError, ValueError):
                visibility = 0
            fields.append('visibility=?')
            args.append(min(max(visibility, 0), 1))
        if fields:
            fields.append('updated_at=?')
            args += [ts, family_id]
            execute(f'UPDATE family SET {",".join(fields)} WHERE id=?', args)
        stats = _apply_json(family_id, data, ts, resource_files)
    _cleanup_old_files(old_files)
    audit.log(current_user()['id'], family_id, 'restore_family', 'family', family_id,
              f'{file.filename}（{", ".join(f"{k}={v}" for k, v in stats.items())}）')
    return jsonify({'code': 0, 'msg': '恢复完成', 'data': stats})


@bp.post('/<int:family_id>/import')
@require_login
@require_family('admin')
def import_data(family_id):
    file = request.files.get('file')
    if file is None:
        raise ApiError('请选择要导入的文件')
    strategy = (request.form.get('strategy')
                or settings.get_str('storage.default_strategy', 'append')).lower()
    if strategy not in ('append', 'overwrite'):
        raise ApiError('导入策略取值不合法')
    name = (file.filename or '').lower()
    ts = now_str()
    stats = {}
    include_metadata = request.form.get('include_metadata', '').lower() in ('1', 'true')
    data = None
    old_files = []
    if strategy == 'overwrite':
        # 先记下旧资源文件，数据库提交成功后再清理，失败回滚时原件仍在
        old_files = [r['storage_path'] for r in
                     query('SELECT storage_path FROM resource WHERE family_id=?', (family_id,))]

    with transaction():
        if strategy == 'overwrite':
            _clear_family_data(family_id)

        if name.endswith('.zip') or name.endswith('.zup'):
            import zipfile as zf
            mem = io.BytesIO(file.read())
            try:
                with zf.ZipFile(mem) as z:
                    infos = _check_zip(z)
                    names = [i.filename for i in infos if not i.is_dir()]
                    json_name = ('data.json' if 'data.json' in names else
                                 next((n for n in names if n.endswith('.json')
                                       and Path(n).name != 'manifest.json'), None))
                    ged_name = next((n for n in names if n.lower().endswith('.ged')), None)
                    if json_name:
                        data = _load_json_payload(z.read(json_name))
                        if include_metadata:
                            _import_metadata(family_id, data, ts)
                        stats = _apply_json(family_id, data, ts, _zip_resources(z, infos))
                    elif ged_name:
                        stats = _apply_gedcom(
                            family_id, z.read(ged_name).decode('utf-8', 'ignore'), ts)
                    else:
                        raise ApiError('压缩包中未找到 data.json 或 .ged 文件')
            except zf.BadZipFile:
                raise ApiError('ZIP 数据包已损坏')
        elif name.endswith('.json'):
            data = _load_json_payload(file.read())
            if include_metadata:
                _import_metadata(family_id, data, ts)
            stats = _apply_json(family_id, data, ts)
        elif name.endswith('.ged'):
            stats = _apply_gedcom(family_id, file.read().decode('utf-8', 'ignore'), ts)
        else:
            raise ApiError('仅支持 JSON / GEDCOM / ZIP 数据包')

    # 覆盖导入成功提交后再删旧文件
    _cleanup_old_files(old_files)

    audit.log(current_user()['id'], family_id, 'import', 'family', family_id,
              f'{file.filename}（{", ".join(f"{k}={v}" for k, v in stats.items())}）')
    total = {t: query_one(f'SELECT COUNT(*) c FROM {t} WHERE family_id=?', (family_id,))['c']
             for t in ('person', 'marriage', 'parentchild', 'event', 'resource', 'branch')}
    total['imported'] = stats
    return jsonify({'code': 0, 'msg': '导入完成', 'data': total})


def _zip_resources(z, infos=None):
    """解出 ZIP 内的 resources/ 原件：{源 fid: (文件名, 字节)}"""
    out = {}
    for info in (infos if infos is not None else z.infolist()):
        if not info.filename.startswith('resources/') or info.is_dir():
            continue
        base = Path(info.filename).name
        if '_' not in base:
            continue
        fid = base.split('_', 1)[0]
        out[fid] = (base, z.read(info))
    return out


def _import_metadata(family_id, data, ts):
    """仅在用户勾选后应用业务资料；不导入 slug、权限、状态及用户 ID。"""
    fam = data.get('family')
    if not isinstance(fam, dict):
        return
    fields, args = [], []
    for key in ('name', 'surname', 'hall_name', 'generation_chars', 'origin_place', 'compiler', 'description'):
        if key not in fam:
            continue
        value = fam[key]
        if value is not None and not isinstance(value, str):
            raise ApiError(f'项目资料 {key} 必须为文本')
        if key == 'name' and (not value or not value.strip()):
            raise ApiError('项目名称不能为空')
        fields.append(f'{key}=?')
        args.append(value)
    if 'generation_frozen' in fam:
        value = fam['generation_frozen']
        if value not in (0, 1, False, True):
            raise ApiError('冻结字辈取值不合法')
        fields.append('generation_frozen=?')
        args.append(int(value))
    if fields:
        execute(f'UPDATE family SET {",".join(fields)},updated_at=? WHERE id=?', args + [ts, family_id])


def _apply_json(family_id, data, ts, resource_files=None):
    """按旧 ID → 新 ID 重映射写入，返回各表实际入库行数。

    安全约定：资源路径一律由本服务重新生成；绝不信任导入包里的 storage_path。
    """
    if not isinstance(data, dict):
        raise ApiError('导入数据格式不合法')
    resource_files = resource_files or {}
    maps = {k: {} for k in ('branch', 'person', 'event', 'resource', 'marriage', 'parentchild')}
    stats = defaultdict(int)

    def insert(table, cols, vals):
        cur = execute(f'INSERT INTO {table} ({",".join(cols)})'
                      f' VALUES ({",".join(["?"] * len(cols))})', vals)
        return cur

    fam = query_one('SELECT slug FROM family WHERE id=?', (family_id,))
    slug = fam['slug'] if fam else f'f{family_id}'
    try:
        target_dir = safe_upload_path(slug)
    except ApiError:
        raise ApiError('家谱存储目录异常，已拒绝导入')

    # 1) 分支：先建（父子关系第二遍补，避免顺序依赖）
    pending_parents = []
    for b in _rows(data, 'branches'):
        old = _ref(b.get('id'))
        name = (_as_text(b.get('name')) or '').strip() or '未命名分支'
        bid = insert('branch',
                     ['family_id', 'parent_id', 'name', 'origin_place', 'establish_time',
                      'description', 'hall_name', 'generation_chars', 'direction',
                      'created_at', 'updated_at'],
                     [family_id, None, name, _as_text(b.get('origin_place')),
                      _as_text(b.get('establish_time')), _as_text(b.get('description')),
                      _as_text(b.get('hall_name')), _as_text(b.get('generation_chars')),
                      _as_text(b.get('direction')), ts, ts])
        if old is not None:
            maps['branch'][old] = bid
        pending_parents.append((bid, _ref(b.get('parent_id'))))
        stats['branch'] += 1
    for bid, old_parent in pending_parents:
        new_parent = maps['branch'].get(old_parent)
        if new_parent and new_parent != bid:
            execute('UPDATE branch SET parent_id=? WHERE id=?', (new_parent, bid))

    # 2) 人物
    for p in _rows(data, 'persons'):
        old = _ref(p.get('id'))
        pid = insert('person',
                     ['family_id', 'generation', 'name', 'courtesy_name', 'art_name', 'type',
                      'birth_date', 'birth_place', 'death_date', 'bury_address', 'record',
                      'notes', 'branch_id', 'is_private'] + list(valid.CONTACT_FIELDS) + ['created_at', 'updated_at'],
                     [family_id, _clamp(p.get('generation'), 1, 999, 1),
                      (_as_text(p.get('name')) or '').strip() or '未命名',
                      _as_text(p.get('courtesy_name')), _as_text(p.get('art_name')),
                      _clamp(p.get('type'), 1, 8, 1), _as_text(p.get('birth_date')),
                      _as_text(p.get('birth_place')), _as_text(p.get('death_date')),
                      _as_text(p.get('bury_address')), _as_text(p.get('record')),
                      _as_text(p.get('notes')),
                      maps['branch'].get(_ref(p.get('branch_id'))),
                      1 if p.get('is_private') else 0] + [_as_text(p.get(k)) for k in valid.CONTACT_FIELDS] + [ts, ts])
        if old is not None:
            maps['person'][old] = pid
        stats['person'] += 1

    # 3) 事件
    for e in _rows(data, 'events'):
        old = _ref(e.get('id'))
        eid = insert('event',
                     ['family_id', 'name', 'time', 'place', 'type', 'description', 'notes',
                      'branch_id', 'created_at', 'updated_at'],
                     [family_id, (_as_text(e.get('name')) or '').strip() or '未命名事件',
                      _as_text(e.get('time')) or '', _as_text(e.get('place')),
                      _clamp(e.get('type'), 1, 2, 1), _as_text(e.get('description')),
                      _as_text(e.get('notes')),
                      maps['branch'].get(_ref(e.get('branch_id'))), ts, ts])
        if old is not None:
            maps['event'][old] = eid
        stats['event'] += 1

    # 4) 婚姻（配偶必须都在本次导入中，否则跳过并计入 skipped）
    skipped = 0
    for m in _rows(data, 'marriages'):
        s1 = maps['person'].get(_ref(m.get('spouse1_id')))
        s2 = maps['person'].get(_ref(m.get('spouse2_id')))
        if not s1 or not s2 or s1 == s2:
            skipped += 1
            continue
        if query_one('SELECT id FROM marriage WHERE family_id=? AND'
                     ' ((spouse1_id=? AND spouse2_id=?) OR (spouse1_id=? AND spouse2_id=?))',
                     (family_id, s1, s2, s2, s1)):
            stats['skipped_duplicate'] += 1
            continue
        mid = insert('marriage',
                     ['family_id', 'spouse1_id', 'spouse2_id', 'marriage_order', 'marriage_date',
                      'divorce_date', 'marriage_place', 'description', 'notes',
                      'created_at', 'updated_at'],
                     [family_id, s1, s2, _clamp(m.get('marriage_order'), 1, 99, 1),
                      _as_text(m.get('marriage_date')), _as_text(m.get('divorce_date')),
                      _as_text(m.get('marriage_place')), _as_text(m.get('description')),
                      _as_text(m.get('notes')), ts, ts])
        old = _ref(m.get('id'))
        if old is not None:
            maps['marriage'][old] = mid
        stats['marriage'] += 1

    # 5) 亲子
    for pc in _rows(data, 'parentchild'):
        parent = maps['person'].get(_ref(pc.get('parent_id')))
        child = maps['person'].get(_ref(pc.get('child_id')))
        if not parent or not child or parent == child:
            skipped += 1
            continue
        if query_one('SELECT id FROM parentchild WHERE family_id=? AND parent_id=? AND child_id=?',
                     (family_id, parent, child)):
            stats['skipped_duplicate'] += 1
            continue
        pcid = insert('parentchild',
                      ['family_id', 'parent_id', 'child_id', 'type', 'child_order', 'description', 'notes',
                       'created_at', 'updated_at'],
                      [family_id, parent, child, _clamp(pc.get('type'), 1, 7, 1),
                       valid.to_int(pc.get('child_order'), 'child_order', minimum=1, maximum=9999),
                       _as_text(pc.get('description')), _as_text(pc.get('notes')), ts, ts])
        old = _ref(pc.get('id'))
        if old is not None:
            maps['parentchild'][old] = pcid
        stats['parentchild'] += 1

    # 6) 事件参与人
    for ep in _rows(data, 'eventpersons'):
        eid = maps['event'].get(_ref(ep.get('event_id')))
        pid = maps['person'].get(_ref(ep.get('person_id')))
        if not eid or not pid:
            skipped += 1
            continue
        if query_one('SELECT id FROM eventperson WHERE event_id=? AND person_id=?', (eid, pid)):
            continue
        insert('eventperson',
               ['family_id', 'event_id', 'person_id', 'role', 'description', 'notes',
                'created_at', 'updated_at'],
               [family_id, eid, pid, _as_text(ep.get('role')), _as_text(ep.get('description')),
                _as_text(ep.get('notes')), ts, ts])
        stats['eventperson'] += 1

    # 7) 文献资源：重新生成 fid 与存储路径；ZIP 内原件写回上传目录
    for r in _rows(data, 'resources'):
        old = _ref(r.get('id'))
        old_fid = r.get('fid') if isinstance(r.get('fid'), str) else None
        new_fid = uuid.uuid4().hex
        name = (_as_text(r.get('name')) or '').strip() or '未命名文献'
        stored = ''
        file_size = 0
        payload = resource_files.get(old_fid) if old_fid else None
        if payload:
            fname, blob = payload
            safe = secure_filename(fname) or f'{new_fid}.bin'
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / f'{new_fid}_{safe}'
            dest.write_bytes(blob)
            stored = f'{slug}/{dest.name}'
            file_size = len(blob)
        rid = insert('resource',
                     ['family_id', 'name', 'fid', 'type', 'storage_path', 'file_size',
                      'mime_type', 'description', 'notes', 'created_at', 'updated_at'],
                     [family_id, name, new_fid, _clamp(r.get('type'), 1, 7, 1), stored,
                      file_size, _as_text(r.get('mime_type')), _as_text(r.get('description')),
                      _as_text(r.get('notes')), ts, ts])
        if old is not None:
            maps['resource'][old] = rid
        stats['resource'] += 1

    # 8) 资源关联
    for rel in _rows(data, 'resource_relations'):
        rid = maps['resource'].get(_ref(rel.get('resource_id')))
        etype = rel.get('entity_type') if isinstance(rel.get('entity_type'), str) else None
        eid = maps.get(etype, {}).get(_ref(rel.get('entity_id'))) if etype else None
        if not rid or not eid:
            skipped += 1
            continue
        if query_one('SELECT id FROM resource_relation WHERE resource_id=? AND entity_type=?'
                     ' AND entity_id=?', (rid, etype, eid)):
            continue
        insert('resource_relation',
               ['family_id', 'resource_id', 'entity_type', 'entity_id', 'notes',
                'created_at', 'updated_at'],
               [family_id, rid, etype, eid, _as_text(rel.get('notes')), ts, ts])
        stats['resource_relation'] += 1

    _assert_import_acyclic(family_id)
    dates.sync_family(family_id)
    stats['skipped'] = skipped
    return dict(stats)

def _apply_gedcom(family_id, text, ts):
    persons, fams = _parse_gedcom(text)
    source_ids = [p.get('id') for p in persons]
    if any(not pid for pid in source_ids) or len(set(source_ids)) != len(source_ids):
        raise ApiError('GEDCOM 人物编号缺失或重复')
    gens = _gedcom_generations(persons, fams)
    for p in persons:
        p['generation'] = p.get('generation') or gens.get(p['id'], 1)
    stats = defaultdict(int, _apply_json(family_id, {'persons': persons}, ts))
    imported = query('SELECT id FROM person WHERE family_id=? ORDER BY id DESC LIMIT ?',
                     (family_id, len(persons))) if persons else []
    idmap = dict(zip((p['id'] for p in persons), reversed([r['id'] for r in imported])))
    person_map = {p['id']: p for p in persons}
    for family_key, family in fams.items():
        members = family['members']
        husb = next((v for t, v in members if t == 'husb'), None)
        wife = next((v for t, v in members if t == 'wife'), None)
        m = family['marriage']
        if m.get('spouse1_source') == wife:
            husb, wife = wife, husb
        if husb and wife and husb in idmap and wife in idmap and idmap[husb] != idmap[wife]:
            s1, s2 = idmap[husb], idmap[wife]
            exists = query_one(
                'SELECT id FROM marriage WHERE family_id=? AND'
                ' ((spouse1_id=? AND spouse2_id=?) OR (spouse1_id=? AND spouse2_id=?))',
                (family_id, s1, s2, s2, s1))
            if not exists:
                order = _clamp(m.get('marriage_order'), 1, 999, 1)
                if not m.get('order_explicit'):
                    order = query_one('SELECT COALESCE(MAX(marriage_order),0)+1 n FROM marriage WHERE family_id=? AND spouse1_id=?',
                                      (family_id, s1))['n']
                execute('INSERT INTO marriage (family_id,spouse1_id,spouse2_id,marriage_order,'
                        'marriage_date,divorce_date,marriage_place,description,notes,created_at,updated_at)'
                        ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (family_id, s1, s2, order,
                         m.get('marriage_date'), m.get('divorce_date'), m.get('marriage_place'),
                         m.get('description'), m.get('notes'), ts, ts))
                stats['marriage'] += 1
        for t, v in members:
            if t == 'chil' and v in idmap:
                for parent in (husb, wife):
                    if parent and parent in idmap and idmap[parent] != idmap[v]:
                        if query_one('SELECT id FROM parentchild WHERE family_id=?'
                                     ' AND parent_id=? AND child_id=?',
                                     (family_id, idmap[parent], idmap[v])):
                            continue
                        pedi = person_map[v].get('_pedi', {})
                        adopted = pedi.get(family_key) in ('adopted', 'foster')
                        kind = _clamp(family['types'].get(v, {}).get(parent), 1, 7, 3 if adopted else 1)
                        order = valid.to_int(family.get('orders', {}).get(v, {}).get(parent), 'child_order', minimum=1, maximum=9999)
                        execute('INSERT INTO parentchild (family_id,parent_id,child_id,type,child_order,created_at,updated_at)'
                                ' VALUES (?,?,?,?,?,?,?)',
                                (family_id, idmap[parent], idmap[v], kind, order, ts, ts))
                        stats['parentchild'] += 1
    _assert_import_acyclic(family_id)
    dates.sync_family(family_id)
    return dict(stats)
