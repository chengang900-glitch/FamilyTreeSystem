"""家谱基础与核心业务：成员、婚姻、亲子、分支、家谱成员名单"""
from collections import defaultdict

import io

from flask import Blueprint, g, jsonify, request, send_file

from server.common import ApiError, now_str
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, dates, privacy, valid
from server.service.permission import (
    assert_in_family, current_user, require_family, require_login,
)

bp = Blueprint('family', __name__, url_prefix='/api/families')

WRITE_ROLE = 'admin'

PERSON_FIELDS = ('generation', 'name', 'courtesy_name', 'art_name', 'type', 'birth_date',
                 'birth_place', 'death_date', 'bury_address', 'record', 'notes', 'branch_id',
                 'is_private') + valid.CONTACT_FIELDS


def _paged(rows, total, page, size):
    return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size}


def _assert_no_cycle(family_id, parent_id, child_id):
    """登记 parent→child 前做环检测：若 child 已是 parent 的祖先则拒绝"""
    parent_id, child_id = int(parent_id), int(child_id)
    if parent_id == child_id:
        raise ApiError('父母与子女不能是同一人')
    children = defaultdict(list)
    for r in query('SELECT parent_id, child_id FROM parentchild WHERE family_id=?', (family_id,)):
        children[int(r['parent_id'])].append(int(r['child_id']))
    stack, seen = [child_id], set()
    while stack:
        cur = stack.pop()
        if cur == parent_id:
            raise ApiError('该关系会形成亲属环路，请检查世系方向')
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, []))


def _assert_branch_no_cycle(family_id, bid, parent_id):
    """把 bid 的上级设为 parent_id 前，沿上级链检查是否回到 bid。"""
    if parent_id is None:
        return
    bid, cur = int(bid), int(parent_id)
    seen = set()
    while cur:
        if cur == bid:
            raise ApiError('分支层级不能形成环，请检查上级分支')
        if cur in seen:
            raise ApiError('分支层级数据已存在环，请先修复上级分支')
        seen.add(cur)
        row = query_one('SELECT parent_id FROM branch WHERE id=? AND family_id=?',
                        (cur, family_id))
        if row is None:
            break
        cur = row['parent_id']


def _assert_unique_marriage(family_id, s1, s2, exclude_id=None):
    sql = ('SELECT id FROM marriage WHERE family_id=? AND'
           ' ((spouse1_id=? AND spouse2_id=?) OR (spouse1_id=? AND spouse2_id=?))')
    args = [family_id, s1, s2, s2, s1]
    if exclude_id:
        sql += ' AND id<>?'
        args.append(exclude_id)
    if query_one(sql, args):
        raise ApiError('这两位成员之间已存在婚姻记录')


def _assert_marriage_order(family_id, spouse1_id, order, exclude_id=0):
    if query_one('SELECT id FROM marriage WHERE family_id=? AND spouse1_id=? AND marriage_order=? AND id<>?',
                 (family_id, spouse1_id, order, exclude_id)):
        raise ApiError('成员 A 的本段次序已使用，请选择其他次序')


def _assert_persons_in_family(family_id, ids):
    """批量归属前先校验所有成员都属于本谱，避免「先清空再逐个写回」留下半成品"""
    if not ids:
        return
    marks = ','.join(['?'] * len(ids))
    rows = query(f'SELECT id FROM person WHERE family_id=? AND id IN ({marks})',
                 [family_id] + list(ids))
    found = {r['id'] for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ApiError(f'成员不存在或不属于本家谱：{missing[:5]}')


# ---------------- 家谱基础 ----------------
@bp.get('')
@require_login
def family_list():
    from server.service.permission import visible_families
    rows = visible_families(current_user())
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.get('/<int:family_id>')
@require_login
@require_family('member')
def family_detail(family_id):
    row = query_one('SELECT * FROM family WHERE id=?', (family_id,))
    return jsonify({'code': 0, 'msg': 'ok', 'data': dict(row)})


@bp.put('/<int:family_id>')
@require_login
@require_family(WRITE_ROLE)
def family_update(family_id):
    data = request.get_json(silent=True) or {}
    current = query_one('SELECT * FROM family WHERE id=?', (family_id,))
    allowed = ('surname', 'hall_name', 'generation_chars', 'origin_place', 'compiler', 'description')
    fields, args = [], []
    for key in allowed:
        if key in data:
            fields.append(f'{key}=?')
            args.append(data[key])
    if 'generation_frozen' in data:
        fields.append('generation_frozen=?')
        args.append(1 if data['generation_frozen'] else 0)
    if 'visibility' in data:
        fields.append('visibility=?')
        args.append(valid.to_int(data['visibility'], 'visibility', minimum=0, maximum=1))
    if fields:
        fields.append('updated_at=?')
        args.append(now_str())
        args.append(family_id)
        execute(f'UPDATE family SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_family', 'family', family_id,
              audit.change(current, data, allowed + ('generation_frozen', 'visibility')))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.get('/<int:family_id>/stats')
@require_login
@require_family('member')
def family_stats(family_id):
    def c(table):
        return query_one(f'SELECT COUNT(*) c FROM {table} WHERE family_id=?', (family_id,))['c']
    return jsonify({'code': 0, 'msg': 'ok', 'data': {
        'persons': c('person'), 'marriages': c('marriage'), 'parentchild': c('parentchild'),
        'events': c('event'), 'resources': c('resource'), 'branches': c('branch'),
    }})


# ---------------- 家谱成员名单（账号层面） ----------------
@bp.get('/<int:family_id>/members')
@require_login
@require_family('member')
def member_list(family_id):
    rows = query('SELECT u.id, u.username, u.real_name, u.phone, fm.role, fm.granted_at'
                 ' FROM family_members fm JOIN users u ON u.id=fm.user_id'
                 ' WHERE fm.family_id=? ORDER BY fm.role, u.id', (family_id,))
    # 最小权限：普通成员看不到他人手机号
    show_phone = getattr(g, 'family_role', None) == 'admin' or current_user()['is_superuser']
    out = []
    for r in rows:
        item = dict(r)
        if not show_phone:
            item.pop('phone', None)
        out.append(item)
    return jsonify({'code': 0, 'msg': 'ok', 'data': out})


@bp.post('/<int:family_id>/members')
@require_login
@require_family(WRITE_ROLE)
def member_add(family_id):
    me = current_user()
    data = request.get_json(silent=True) or {}
    uid = valid.to_int(data.get('user_id'), 'user_id', minimum=1, required=True)
    role = data.get('role') or 'member'
    if role not in ('admin', 'member'):
        raise ApiError('角色取值不合法')
    if role == 'admin' and not me['is_superuser']:
        raise ApiError('仅超级管理员可指派家谱管理员', code=403)
    if query_one('SELECT id FROM users WHERE id=?', (uid,)) is None:
        raise ApiError('用户不存在', code=404)
    if query_one('SELECT id FROM family_members WHERE family_id=? AND user_id=?', (family_id, uid)):
        raise ApiError('该用户已在此家谱中')
    execute('INSERT INTO family_members (family_id, user_id, role, granted_by, granted_at)'
            ' VALUES (?,?,?,?,?)',
            (family_id, uid, role, me['id'], now_str()))
    audit.log(me['id'], family_id, 'grant_role', 'user', uid, role)
    return jsonify({'code': 0, 'msg': '已加入家谱', 'data': None})


@bp.delete('/<int:family_id>/members/<int:uid>')
@require_login
@require_family(WRITE_ROLE)
def member_remove(family_id, uid):
    me = current_user()
    row = query_one('SELECT role FROM family_members WHERE family_id=? AND user_id=?', (family_id, uid))
    if row is None:
        raise ApiError('该用户不在此家谱中', code=404)
    # 与权限矩阵保持一致：授/撤家谱管理员仅超管可做，家谱管理员只能移除普通用户
    if row['role'] == 'admin' and not me['is_superuser']:
        raise ApiError('仅超级管理员可移除家谱管理员', code=403)
    if row['role'] == 'admin':
        admins = query('SELECT id FROM family_members WHERE family_id=? AND role="admin"', (family_id,))
        if len(admins) <= 1:
            raise ApiError('至少需要保留一名家谱管理员')
    execute('DELETE FROM family_members WHERE family_id=? AND user_id=?', (family_id, uid))
    audit.log(me['id'], family_id, 'revoke_member', 'user', uid)
    return jsonify({'code': 0, 'msg': '已移出家谱', 'data': None})


@bp.get('/<int:family_id>/members/search')
@require_login
@require_family(WRITE_ROLE)
def member_search(family_id):
    """搜索可加入本谱的用户（排除已在谱内；仅家谱管理员可用）。

    隐私约束：家谱管理员不应能枚举全站账号/手机号。非超管只允许精确匹配
    账号或姓名，且只返回加入家谱所需的最小字段。
    """
    me = current_user()
    kw = (request.args.get('keyword') or '').strip()
    if not kw:
        return jsonify({'code': 0, 'msg': 'ok', 'data': []})
    if me['is_superuser']:
        sql = ('SELECT id, username, real_name FROM users'
               ' WHERE (username LIKE ? OR real_name LIKE ?)'
               ' AND id NOT IN (SELECT user_id FROM family_members WHERE family_id=?)'
               ' LIMIT 20')
        args = [f'%{kw}%', f'%{kw}%', family_id]
    else:
        sql = ('SELECT id, username, real_name FROM users'
               ' WHERE (username=? OR real_name=?)'
               ' AND id NOT IN (SELECT user_id FROM family_members WHERE family_id=?)'
               ' LIMIT 20')
        args = [kw, kw, family_id]
    rows = query(sql, args)
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


# ---------------- 本谱操作日志 ----------------
@bp.get('/<int:family_id>/logs')
@require_login
@require_family('admin')
def family_logs(family_id):
    limit = valid.to_int(request.args.get('limit'), 'limit', 200, minimum=1, maximum=1000)
    rows = query(
        'SELECT l.*, u.username FROM operation_log l LEFT JOIN users u ON u.id=l.user_id'
        ' WHERE l.family_id=? ORDER BY l.id DESC LIMIT ?', (family_id, limit))
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.get('/<int:family_id>/logs/export')
@require_login
@require_family('admin')
def family_logs_export(family_id):
    limit = valid.to_int(request.args.get('limit'), 'limit', 10000, minimum=1, maximum=10000)
    rows = query(
        'SELECT l.*, u.username FROM operation_log l LEFT JOIN users u ON u.id=l.user_id'
        ' WHERE l.family_id=? ORDER BY l.id DESC LIMIT ?', (family_id, limit))
    return send_file(io.BytesIO(audit.export_csv(rows)), mimetype='text/csv',
                     as_attachment=True, download_name=f'family_{family_id}_logs.csv')


# ---------------- 成员 ----------------
@bp.get('/<int:family_id>/persons')
@require_login
@require_family('member')
def person_list(family_id):
    page, size = valid.page_args()
    kw = (request.args.get('keyword') or '').strip()
    gen = valid.query_int('generation', minimum=1)
    ptype = valid.query_int('type', minimum=1, maximum=8)
    types = None
    if 'types' in request.args:
        types = [valid.to_int(value, 'types', minimum=1, maximum=8)
                 for value in request.args['types'].split(',')]
        if not types or any(value is None for value in types):
            raise ApiError('成员类型筛选不合法')
    branch = valid.query_int('branch_id', minimum=1)
    where, args = ['p.family_id=?'], [family_id]
    if kw:
        where.append('(p.name LIKE ? OR p.courtesy_name LIKE ? OR p.art_name LIKE ?)')
        args += [f'%{kw}%'] * 3
    if gen is not None:
        where.append('p.generation=?')
        args.append(gen)
    if ptype is not None:
        where.append('p.type=?')
        args.append(ptype)
    if types is not None:
        where.append('p.type IN (' + ','.join('?' for _ in types) + ')')
        args.extend(types)
    if branch is not None:
        where.append('p.branch_id=?')
        args.append(branch)
    cond = ' AND '.join(where)
    total = query_one(f'SELECT COUNT(*) c FROM person p WHERE {cond}', args)['c']
    rows = query(f'SELECT p.*, b.name AS branch_name FROM person p'
                 f' LEFT JOIN branch b ON b.id=p.branch_id WHERE {cond}'
                 f' ORDER BY p.generation, p.id LIMIT ? OFFSET ?',
                 args + [size, (page - 1) * size])
    data = _paged(rows, total, page, size)
    data['items'] = [privacy.mask_person(r) for r in rows]
    return jsonify({'code': 0, 'msg': 'ok', 'data': data})


@bp.get('/<int:family_id>/persons/<int:pid>')
@require_login
@require_family('member')
def person_detail(family_id, pid):
    row = query_one('SELECT p.*, b.name AS branch_name FROM person p'
                    ' LEFT JOIN branch b ON b.id=p.branch_id'
                    ' WHERE p.id=? AND p.family_id=?', (pid, family_id))
    if row is None:
        raise ApiError('成员不存在', code=404)
    return jsonify({'code': 0, 'msg': 'ok', 'data': privacy.mask_person(row)})


@bp.post('/<int:family_id>/persons')
@require_login
@require_family(WRITE_ROLE)
def person_create(family_id):
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        raise ApiError('请输入姓名')
    gen = valid.to_int(data.get('generation'), 'generation', minimum=1, maximum=999)
    if gen is None:
        raise ApiError('世代需为正整数')
    ptype = valid.to_int(data.get('type'), 'type', 1, minimum=1, maximum=8)
    valid.check_date_order(data.get('birth_date'), data.get('death_date'), '逝世日期')
    branch_id = valid.to_optional_id(data.get('branch_id'), 'branch_id')
    if branch_id is not None:
        assert_in_family('branch', branch_id, family_id)
    ts = now_str()
    cols = ['family_id'] + list(PERSON_FIELDS) + ['created_at', 'updated_at']
    contact = valid.contacts(data)
    vals = [family_id, gen, name, data.get('courtesy_name'), data.get('art_name'), ptype,
            data.get('birth_date'), data.get('birth_place'), data.get('death_date'),
            data.get('bury_address'), data.get('record'), data.get('notes'), branch_id,
            1 if data.get('is_private') else 0] + [contact.get(k) for k in valid.CONTACT_FIELDS] + [ts, ts]
    date_values = dates.values(data, dates.DATE_FIELDS['person'])
    for key, value in date_values.items():
        if key not in cols:
            cols.append(key)
            vals.append(value)
    pid = execute(f'INSERT INTO person ({",".join(cols)}) VALUES ({",".join(["?"] * len(cols))})', vals)
    audit.log(current_user()['id'], family_id, 'create_person', 'person', pid, name)
    return jsonify({'code': 0, 'msg': '成员已添加', 'data': {'id': pid}})


@bp.put('/<int:family_id>/persons/<int:pid>')
@require_login
@require_family(WRITE_ROLE)
def person_update(family_id, pid):
    assert_in_family('person', pid, family_id)
    current = query_one('SELECT * FROM person WHERE id=?', (pid,))
    data = request.get_json(silent=True) or {}
    valid.check_date_order(data.get('birth_date', current['birth_date']),
                           data.get('death_date', current['death_date']), '逝世日期')
    fields, args = [], []

    def put(key, value):
        fields.append(f'{key}=?')
        args.append(value)

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            raise ApiError('姓名不能为空')
        put('name', name)
    if 'generation' in data:
        put('generation', valid.to_int(data.get('generation'), 'generation', minimum=1, maximum=999))
    if 'type' in data:
        put('type', valid.to_int(data.get('type'), 'type', minimum=1, maximum=8))
    if 'branch_id' in data:
        branch_id = valid.to_optional_id(data.get('branch_id'), 'branch_id')
        if branch_id is not None:
            assert_in_family('branch', branch_id, family_id)
        put('branch_id', branch_id)
    if 'is_private' in data:
        put('is_private', 1 if data.get('is_private') else 0)
    for key in ('courtesy_name', 'art_name', 'birth_date', 'birth_place', 'death_date',
                'bury_address', 'record', 'notes'):
        if key in data:
            put(key, data[key])
    for key, value in valid.contacts(data).items():
        put(key, value)
    for key, value in dates.values(data, dates.DATE_FIELDS['person'], current=current).items():
        if key not in dates.DATE_FIELDS['person']:
            put(key, value)
    if not fields:
        raise ApiError('没有需要更新的字段')
    fields.append('updated_at=?')
    args += [now_str(), pid]
    execute(f'UPDATE person SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_person', 'person', pid,
              audit.change(current, data, PERSON_FIELDS))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/persons/<int:pid>')
@require_login
@require_family(WRITE_ROLE)
def person_delete(family_id, pid):
    assert_in_family('person', pid, family_id)
    rel = query_one('SELECT COUNT(*) c FROM parentchild WHERE family_id=? AND (parent_id=? OR child_id=?)',
                    (family_id, pid, pid))
    if rel['c'] > 0:
        raise ApiError('该成员存在亲子关系，请先删除相关亲子记录')
    mar = query_one('SELECT COUNT(*) c FROM marriage WHERE family_id=? AND (spouse1_id=? OR spouse2_id=?)',
                    (family_id, pid, pid))
    if mar['c'] > 0:
        raise ApiError('该成员存在婚姻记录，请先删除相关婚姻记录')
    with transaction():
        # 从属关联随主体清理，避免留下孤儿行（旧库无外键时尤其重要）
        execute('DELETE FROM eventperson WHERE person_id=? AND family_id=?', (pid, family_id))
        execute('DELETE FROM resource_relation WHERE entity_type="person" AND entity_id=?'
                ' AND family_id=?', (pid, family_id))
        execute('DELETE FROM person WHERE id=?', (pid,))
    audit.log(current_user()['id'], family_id, 'delete_person', 'person', pid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


# ---------------- 婚姻 ----------------
@bp.get('/<int:family_id>/marriages')
@require_login
@require_family('member')
def marriage_list(family_id):
    kw = (request.args.get('keyword') or '').strip()
    where, args = ['m.family_id=?'], [family_id]
    if kw:
        where.append('(p1.name LIKE ? OR p2.name LIKE ?)')
        args += [f'%{kw}%', f'%{kw}%']
    cond = ' AND '.join(where)
    base = (' FROM marriage m JOIN person p1 ON p1.id=m.spouse1_id'
            ' JOIN person p2 ON p2.id=m.spouse2_id WHERE ')
    if valid.paged_request():
        page, size = valid.page_args()
        total = query_one(f'SELECT COUNT(*) c{base}{cond}', args)['c']
        rows = query(f'SELECT m.*, p1.name AS spouse1_name, p2.name AS spouse2_name'
                     f'{base}{cond} ORDER BY m.id DESC LIMIT ? OFFSET ?',
                     args + [size, (page - 1) * size])
        return jsonify({'code': 0, 'msg': 'ok', 'data': _paged(rows, total, page, size)})
    rows = query(f'SELECT m.*, p1.name AS spouse1_name, p2.name AS spouse2_name'
                 f'{base}{cond} ORDER BY m.id DESC', args)
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.post('/<int:family_id>/marriages')
@require_login
@require_family(WRITE_ROLE)
def marriage_create(family_id):
    data = request.get_json(silent=True) or {}
    s1 = valid.to_int(data.get('spouse1_id'), 'spouse1_id', minimum=1)
    s2 = valid.to_int(data.get('spouse2_id'), 'spouse2_id', minimum=1)
    if not s1 or not s2:
        raise ApiError('请选择配偶双方')
    if s1 == s2:
        raise ApiError('配偶不能为同一人')
    for pid in (s1, s2):
        assert_in_family('person', pid, family_id)
    _assert_unique_marriage(family_id, s1, s2)
    order = valid.to_int(data.get('marriage_order'), 'marriage_order', 1, minimum=1)
    _assert_marriage_order(family_id, s1, order)
    date_values = dates.values(data, dates.DATE_FIELDS['marriage'])
    valid.check_date_order(data.get('marriage_date'), data.get('divorce_date'), '离婚日期')
    ts = now_str()
    mid = execute(
        'INSERT INTO marriage (family_id, spouse1_id, spouse2_id, marriage_order, marriage_date,'
        ' divorce_date, marriage_place, description, notes, created_at, updated_at)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (family_id, s1, s2, order,
         data.get('marriage_date'), data.get('divorce_date'), data.get('marriage_place'),
         data.get('description'), data.get('notes'), ts, ts))
    for key, value in date_values.items():
        if key not in dates.DATE_FIELDS['marriage']:
            execute(f'UPDATE marriage SET {key}=? WHERE id=?', (value, mid))
    audit.log(current_user()['id'], family_id, 'create_marriage', 'marriage', mid)
    return jsonify({'code': 0, 'msg': '婚姻已登记', 'data': {'id': mid}})


@bp.put('/<int:family_id>/marriages/<int:mid>')
@require_login
@require_family(WRITE_ROLE)
def marriage_update(family_id, mid):
    assert_in_family('marriage', mid, family_id)
    data = request.get_json(silent=True) or {}
    current = query_one('SELECT * FROM marriage WHERE id=?', (mid,))
    s1 = valid.to_int(data.get('spouse1_id'), 'spouse1_id', current['spouse1_id'], minimum=1) \
        if 'spouse1_id' in data else current['spouse1_id']
    s2 = valid.to_int(data.get('spouse2_id'), 'spouse2_id', current['spouse2_id'], minimum=1) \
        if 'spouse2_id' in data else current['spouse2_id']
    if s1 == s2:
        raise ApiError('配偶不能为同一人')
    for pid in (s1, s2):
        assert_in_family('person', pid, family_id)
    _assert_unique_marriage(family_id, s1, s2, exclude_id=mid)
    order = valid.to_int(data.get('marriage_order', current['marriage_order']), 'marriage_order', minimum=1)
    _assert_marriage_order(family_id, s1, order, mid)
    marriage_date = data.get('marriage_date', current['marriage_date'])
    divorce_date = data.get('divorce_date', current['divorce_date'])
    valid.check_date_order(marriage_date, divorce_date, '离婚日期')
    fields, args = [], []
    for key in ('spouse1_id', 'spouse2_id', 'marriage_order', 'marriage_date', 'divorce_date',
                'marriage_place', 'description', 'notes'):
        if key in data:
            fields.append(f'{key}=?')
            if key == 'marriage_order':
                args.append(valid.to_int(data[key], key, minimum=1))
            else:
                args.append(data[key])
    if not fields:
        raise ApiError('没有需要更新的字段')
    for key, value in dates.values(data, dates.DATE_FIELDS['marriage'], current=current).items():
        if key not in dates.DATE_FIELDS['marriage']:
            fields.append(f'{key}=?')
            args.append(value)
    fields.append('updated_at=?')
    args += [now_str(), mid]
    execute(f'UPDATE marriage SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_marriage', 'marriage', mid,
              audit.change(current, data, ('spouse1_id', 'spouse2_id', 'marriage_order',
                                           'marriage_date', 'divorce_date', 'marriage_place',
                                           'description', 'notes')))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/marriages/<int:mid>')
@require_login
@require_family(WRITE_ROLE)
def marriage_delete(family_id, mid):
    assert_in_family('marriage', mid, family_id)
    with transaction():
        # resource_relation 是多态关联，没有数据库外键，必须显式清理
        execute('DELETE FROM resource_relation WHERE entity_type="marriage" AND entity_id=?'
                ' AND family_id=?', (mid, family_id))
        execute('DELETE FROM marriage WHERE id=?', (mid,))
    audit.log(current_user()['id'], family_id, 'delete_marriage', 'marriage', mid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


# ---------------- 亲子 ----------------
@bp.get('/<int:family_id>/parentchild')
@require_login
@require_family('member')
def pc_list(family_id):
    kw = (request.args.get('keyword') or '').strip()
    where, args = ['pc.family_id=?'], [family_id]
    if kw:
        where.append('(p1.name LIKE ? OR p2.name LIKE ?)')
        args += [f'%{kw}%', f'%{kw}%']
    cond = ' AND '.join(where)
    base = (' FROM parentchild pc JOIN person p1 ON p1.id=pc.parent_id'
            ' JOIN person p2 ON p2.id=pc.child_id WHERE ')
    # 先按父母分组，再排子女生日；必须在分页前排序，人工排行不影响列表顺序。
    # ISO 值保留原有年/月/日精度，未能规范化的日期统一放在组末。
    order = (' ORDER BY p1.generation, pc.parent_id,'
             " NULLIF(p2.birth_date_iso,'') IS NULL, p2.birth_date_iso, pc.child_id, pc.id")
    if valid.paged_request():
        page, size = valid.page_args()
        total = query_one(f'SELECT COUNT(*) c{base}{cond}', args)['c']
        rows = query(f'SELECT pc.*, p1.name AS parent_name, p1.type AS parent_type, p2.name AS child_name'
                     f'{base}{cond}{order} LIMIT ? OFFSET ?',
                     args + [size, (page - 1) * size])
        return jsonify({'code': 0, 'msg': 'ok', 'data': _paged(rows, total, page, size)})
    rows = query(f'SELECT pc.*, p1.name AS parent_name, p1.type AS parent_type, p2.name AS child_name'
                 f'{base}{cond}{order}', args)
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


def _child_order(value):
    if value is None or value == '':
        return None
    return valid.to_int(value, '子女排行', minimum=1, maximum=9999)


def _assert_child_order(family_id, parent, order, exclude_id=0):
    if order is not None and query_one(
            'SELECT id FROM parentchild WHERE family_id=? AND parent_id=? AND child_order=? AND id<>?',
            (family_id, parent, order, exclude_id)):
        raise ApiError('该父/母名下的子女排行已使用，男女统一排行；请核对或留空')


@bp.post('/<int:family_id>/parentchild')
@require_login
@require_family(WRITE_ROLE)
def pc_create(family_id):
    """支持一次登记多名子女"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ApiError('请求体需为对象')
    if 'children' in data:
        return _pc_create_family(family_id, data)
    parent_id = valid.to_int(data.get('parent_id'), 'parent_id', minimum=1)
    if data.get('child_ids') is not None:
        child_ids = valid.to_id_list(data.get('child_ids'), 'child_ids')
    else:
        single = valid.to_int(data.get('child_id'), 'child_id', minimum=1)
        child_ids = [single] if single else []
    if not parent_id or not child_ids:
        raise ApiError('请选择父母与子女')
    ptype = valid.to_int(data.get('type'), 'type', 1, minimum=1, maximum=7)
    assert_in_family('person', parent_id, family_id)
    ts = now_str()
    count = 0
    with transaction():
        for cid in child_ids:
            if int(cid) == int(parent_id):
                continue
            assert_in_family('person', cid, family_id)
            _assert_no_cycle(family_id, parent_id, cid)
            exists = query_one(
                'SELECT id FROM parentchild WHERE family_id=? AND parent_id=? AND child_id=?',
                (family_id, parent_id, cid))
            if exists:
                continue
            order = _child_order(data.get('child_order'))
            _assert_child_order(family_id, parent_id, order)
            execute('INSERT INTO parentchild (family_id, parent_id, child_id, type, child_order, description,'
                    ' notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                    (family_id, parent_id, cid, ptype, order, data.get('description'),
                     data.get('notes'), ts, ts))
            count += 1
    audit.log(current_user()['id'], family_id, 'create_parentchild', 'parentchild', parent_id,
              f'{count} 条')
    return jsonify({'code': 0, 'msg': f'已登记 {count} 条亲子关系', 'data': {'count': count}})


def _pc_create_family(family_id, data):
    """父母与逐个子女的关系在单个事务中保存；兼容旧单父母接口。"""
    father = valid.to_optional_id(data.get('father_id'), 'father_id')
    mother = valid.to_optional_id(data.get('mother_id'), 'mother_id')
    if not father and not mother:
        raise ApiError('请至少选择父亲或母亲一方')
    if father and father == mother:
        raise ApiError('父亲与母亲不能是同一人')
    children = data.get('children')
    if not isinstance(children, list) or not children or len(children) > 500:
        raise ApiError('请选择 1–500 名子女')
    entries, seen, orders = [], set(), {}
    for row in children:
        if not isinstance(row, dict):
            raise ApiError('子女资料必须为对象')
        child = valid.to_int(row.get('child_id'), 'child_id', minimum=1)
        if not child or child in seen or child in (father, mother):
            raise ApiError('子女不能重复或与父母为同一人')
        seen.add(child)
        if 'child_order' in row:
            orders[child] = _child_order(row['child_order'])
        for parent, field in ((father, 'father_type'), (mother, 'mother_type')):
            if parent:
                kind = valid.to_int(row.get(field), field, 1, minimum=1, maximum=7)
                entries.append((parent, child, kind))
    for pid in set([p for p, _, _ in entries] + list(seen)):
        assert_in_family('person', pid, family_id)
    ts, count = now_str(), 0
    with transaction():
        for parent, allowed, title in ((father, (1, 4, 5, 7), '父亲'), (mother, (2, 3, 6, 8), '母亲')):
            if parent:
                person = query_one('SELECT type FROM person WHERE id=? AND family_id=?', (parent, family_id))
                if not person or person['type'] not in allowed:
                    choices = '宗男、姻婿、外孙或其他（男）' if title == '父亲' else '宗女、姻媳、外孙女或其他（女）'
                    raise ApiError(f'{title}只能选择{choices}，请检查成员类型')
        for parent, child, kind in entries:
            _assert_no_cycle(family_id, parent, child)
            old = query_one('SELECT * FROM parentchild WHERE family_id=? AND parent_id=? AND child_id=?',
                            (family_id, parent, child))
            order = orders.get(child, old['child_order'] if old else None)
            _assert_child_order(family_id, parent, order, old['id'] if old else 0)
            if old:
                if old['type'] != kind or old['child_order'] != order:
                    execute('UPDATE parentchild SET type=?,child_order=?,updated_at=? WHERE id=?', (kind, order, ts, old['id']))
                    audit.log(current_user()['id'], family_id, 'update_parentchild', 'parentchild', old['id'],
                              audit.change(old, {'type': kind, 'child_order': order}, ('type', 'child_order')))
                    count += 1
                continue
            pid = execute('INSERT INTO parentchild (family_id,parent_id,child_id,type,child_order,description,created_at,updated_at)'
                          ' VALUES (?,?,?,?,?,?,?,?)',
                          (family_id, parent, child, kind, order, data.get('description'), ts, ts))
            audit.log(current_user()['id'], family_id, 'create_parentchild', 'parentchild', pid)
            count += 1
    return jsonify({'code': 0, 'msg': f'已保存 {count} 条亲子关系', 'data': {'count': count}})


@bp.put('/<int:family_id>/parentchild/<int:pcid>')
@require_login
@require_family(WRITE_ROLE)
def pc_update(family_id, pcid):
    assert_in_family('parentchild', pcid, family_id)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ApiError('请求体需为对象')
    current = query_one('SELECT * FROM parentchild WHERE id=?', (pcid,))
    parent_id = valid.to_int(data.get('parent_id'), 'parent_id', current['parent_id'], minimum=1) \
        if 'parent_id' in data else current['parent_id']
    child_id = valid.to_int(data.get('child_id'), 'child_id', current['child_id'], minimum=1) \
        if 'child_id' in data else current['child_id']
    assert_in_family('person', parent_id, family_id)
    assert_in_family('person', child_id, family_id)
    role = data.get('parent_role')
    if role is not None:
        if role not in ('father', 'mother'):
            raise ApiError('父母身份不合法')
        parent = query_one('SELECT type FROM person WHERE id=? AND family_id=?', (parent_id, family_id))
        allowed = (1, 4, 5, 7) if role == 'father' else (2, 3, 6, 8)
        if parent['type'] not in allowed:
            raise ApiError('所选父/母与成员类型不符')
    if query_one('SELECT id FROM parentchild WHERE family_id=? AND parent_id=? AND child_id=? AND id<>?',
                 (family_id, parent_id, child_id, pcid)):
        raise ApiError('这条亲子关系已存在，请直接编辑原记录')
    order = _child_order(data.get('child_order', current['child_order']))
    _assert_child_order(family_id, parent_id, order, pcid)
    # 环检测时排除自身这条边
    children = defaultdict(list)
    for r in query('SELECT id, parent_id, child_id FROM parentchild WHERE family_id=?',
                   (family_id,)):
        if r['id'] == pcid:
            continue
        children[int(r['parent_id'])].append(int(r['child_id']))
    if int(parent_id) == int(child_id):
        raise ApiError('父母与子女不能是同一人')
    stack, seen = [int(child_id)], set()
    while stack:
        cur = stack.pop()
        if cur == int(parent_id):
            raise ApiError('该关系会形成亲属环路，请检查世系方向')
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, []))

    fields, args = [], []
    for key in ('parent_id', 'child_id', 'type', 'child_order', 'description', 'notes'):
        if key in data:
            fields.append(f'{key}=?')
            if key == 'type':
                args.append(valid.to_int(data[key], 'type', minimum=1, maximum=7))
            elif key == 'child_order':
                args.append(order)
            elif key.endswith('_id'):
                args.append(valid.to_int(data[key], key, minimum=1))
            else:
                args.append(data[key])
    if fields:
        fields.append('updated_at=?')
        args += [now_str(), pcid]
        execute(f'UPDATE parentchild SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_parentchild', 'parentchild', pcid,
              audit.change(current, data, ('parent_id', 'child_id', 'type',
                                           'description', 'child_order', 'notes')))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/parentchild/<int:pcid>')
@require_login
@require_family(WRITE_ROLE)
def pc_delete(family_id, pcid):
    assert_in_family('parentchild', pcid, family_id)
    with transaction():
        execute('DELETE FROM resource_relation WHERE entity_type="parentchild" AND entity_id=?'
                ' AND family_id=?', (pcid, family_id))
        execute('DELETE FROM parentchild WHERE id=?', (pcid,))
    audit.log(current_user()['id'], family_id, 'delete_parentchild', 'parentchild', pcid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


# ---------------- 分支 ----------------
@bp.get('/<int:family_id>/branches')
@require_login
@require_family('member')
def branch_list(family_id):
    kw = (request.args.get('keyword') or '').strip()
    where, args = ['b.family_id=?'], [family_id]
    if kw:
        where.append('b.name LIKE ?')
        args.append(f'%{kw}%')
    cond = ' AND '.join(where)
    from_where = ' FROM branch b WHERE '
    select = ('SELECT b.*, (SELECT COUNT(*) FROM person p WHERE p.branch_id=b.id) AS person_count'
              + from_where)
    all_rows = request.args.get('all') in ('1', 'true', 'True')
    if valid.paged_request() and not all_rows:
        page, size = valid.page_args()
        total = query_one(f'SELECT COUNT(*) c{from_where}{cond}', args)['c']
        rows = query(f'{select}{cond} ORDER BY b.id LIMIT ? OFFSET ?',
                     args + [size, (page - 1) * size])
        return jsonify({'code': 0, 'msg': 'ok', 'data': _paged(rows, total, page, size)})
    rows = query(f'{select}{cond} ORDER BY b.id', args)
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.post('/<int:family_id>/branches')
@require_login
@require_family(WRITE_ROLE)
def branch_create(family_id):
    data = request.get_json(silent=True) or {}
    if not (data.get('name') or '').strip():
        raise ApiError('请输入分支名称')
    parent_id = valid.to_optional_id(data.get('parent_id'), 'parent_id')
    if parent_id is not None:
        assert_in_family('branch', parent_id, family_id)
    fam = query_one('SELECT generation_chars, generation_frozen, hall_name FROM family WHERE id=?',
                    (family_id,))
    ts = now_str()
    person_ids = valid.to_id_list(data.get('person_ids'), 'person_ids')
    _assert_persons_in_family(family_id, person_ids)
    with transaction():
        bid = execute(
            'INSERT INTO branch (family_id, parent_id, name, origin_place, establish_time,'
            ' description, hall_name, generation_chars, direction, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (family_id, parent_id, data.get('name'), data.get('origin_place'),
             data.get('establish_time'), data.get('description'),
             data.get('hall_name') or (fam['hall_name'] if fam and fam['generation_frozen'] else None),
             data.get('generation_chars')
             or (fam['generation_chars'] if fam and fam['generation_frozen'] else None),
             data.get('direction'), ts, ts))
        for pid in person_ids:
            execute('UPDATE person SET branch_id=?, updated_at=? WHERE id=? AND family_id=?',
                    (bid, ts, pid, family_id))
    audit.log(current_user()['id'], family_id, 'create_branch', 'branch', bid, data.get('name'))
    return jsonify({'code': 0, 'msg': '分支已创建', 'data': {'id': bid}})


@bp.put('/<int:family_id>/branches/<int:bid>')
@require_login
@require_family(WRITE_ROLE)
def branch_update(family_id, bid):
    assert_in_family('branch', bid, family_id)
    current = query_one('SELECT * FROM branch WHERE id=?', (bid,))
    data = request.get_json(silent=True) or {}
    fields, args = [], []
    for key in ('parent_id', 'name', 'origin_place', 'establish_time', 'description',
                'hall_name', 'generation_chars', 'direction'):
        if key in data:
            if key == 'parent_id':
                parent_id = valid.to_optional_id(data[key], 'parent_id')
                if parent_id is not None:
                    assert_in_family('branch', parent_id, family_id)
                    _assert_branch_no_cycle(family_id, bid, parent_id)
                fields.append('parent_id=?')
                args.append(parent_id)
                continue
            fields.append(f'{key}=?')
            args.append(data[key])
    person_ids = valid.to_id_list(data.get('person_ids'), 'person_ids') \
        if 'person_ids' in data else None
    add_ids = valid.to_id_list(data.get('add_ids'), 'add_ids') if 'add_ids' in data else []
    remove_ids = valid.to_id_list(data.get('remove_ids'), 'remove_ids') \
        if 'remove_ids' in data else []
    if person_ids is not None and (add_ids or remove_ids):
        raise ApiError('person_ids 与 add_ids/remove_ids 不能同时使用')
    if set(add_ids) & set(remove_ids):
        raise ApiError('同一成员不能同时加入和移出分支')
    if person_ids is not None:
        # 先校验全部成员归属，再进事务改数据：不会出现「清空后写回失败」的半成品
        _assert_persons_in_family(family_id, person_ids)
    if add_ids:
        _assert_persons_in_family(family_id, add_ids)
    with transaction():
        if fields:
            fields.append('updated_at=?')
            args += [now_str(), bid]
            execute(f'UPDATE branch SET {",".join(fields)} WHERE id=?', args)
        if person_ids is not None:
            ts = now_str()
            execute('UPDATE person SET branch_id=NULL, updated_at=? WHERE branch_id=? AND family_id=?',
                    (ts, bid, family_id))
            for pid in person_ids:
                execute('UPDATE person SET branch_id=?, updated_at=? WHERE id=? AND family_id=?',
                        (bid, ts, pid, family_id))
        else:
            ts = now_str()
            for pid in remove_ids:
                execute('UPDATE person SET branch_id=NULL, updated_at=?'
                        ' WHERE id=? AND family_id=? AND branch_id=?',
                        (ts, pid, family_id, bid))
            for pid in add_ids:
                execute('UPDATE person SET branch_id=?, updated_at=? WHERE id=? AND family_id=?',
                        (bid, ts, pid, family_id))
    audit.log(current_user()['id'], family_id, 'update_branch', 'branch', bid,
              audit.change(current, data, ('parent_id', 'name', 'origin_place', 'establish_time',
                                           'description', 'hall_name', 'generation_chars',
                                           'direction')))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/branches/<int:bid>')
@require_login
@require_family(WRITE_ROLE)
def branch_delete(family_id, bid):
    assert_in_family('branch', bid, family_id)
    with transaction():
        execute('UPDATE person SET branch_id=NULL WHERE branch_id=? AND family_id=?', (bid, family_id))
        execute('UPDATE event SET branch_id=NULL WHERE branch_id=? AND family_id=?', (bid, family_id))
        execute('UPDATE branch SET parent_id=NULL WHERE parent_id=? AND family_id=?', (bid, family_id))
        execute('DELETE FROM resource_relation WHERE entity_type="branch" AND entity_id=?'
                ' AND family_id=?', (bid, family_id))
        execute('DELETE FROM branch WHERE id=?', (bid,))
    audit.log(current_user()['id'], family_id, 'delete_branch', 'branch', bid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


@bp.post('/<int:family_id>/branches/<int:bid>/members')
@require_login
@require_family(WRITE_ROLE)
def branch_assign_members(family_id, bid):
    """批量归入 / 移出分支"""
    assert_in_family('branch', bid, family_id)
    data = request.get_json(silent=True) or {}
    ts = now_str()
    add_ids = valid.to_id_list(data.get('add_ids'), 'add_ids')
    remove_ids = valid.to_id_list(data.get('remove_ids'), 'remove_ids')
    _assert_persons_in_family(family_id, add_ids)
    with transaction():
        for pid in add_ids:
            execute('UPDATE person SET branch_id=?, updated_at=? WHERE id=? AND family_id=?',
                    (bid, ts, pid, family_id))
        for pid in remove_ids:
            execute('UPDATE person SET branch_id=NULL, updated_at=? WHERE id=? AND family_id=?'
                    ' AND branch_id=?', (ts, pid, family_id, bid))
    audit.log(current_user()['id'], family_id, 'assign_branch_members', 'branch', bid)
    return jsonify({'code': 0, 'msg': '成员归属已更新', 'data': None})
