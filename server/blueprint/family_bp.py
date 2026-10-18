"""家谱基础与核心业务：成员、婚姻、亲子、分支、家谱成员名单"""
from collections import defaultdict

from flask import Blueprint, g, jsonify, request

from server.common import ApiError, now_str
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, privacy, valid
from server.service.permission import (
    assert_in_family, current_user, require_family, require_login,
)

bp = Blueprint('family', __name__, url_prefix='/api/families')

WRITE_ROLE = 'admin'

PERSON_FIELDS = ('generation', 'name', 'courtesy_name', 'art_name', 'type', 'birth_date',
                 'birth_place', 'death_date', 'bury_address', 'record', 'notes', 'branch_id',
                 'is_private')


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


def _assert_unique_marriage(family_id, s1, s2, exclude_id=None):
    sql = ('SELECT id FROM marriage WHERE family_id=? AND'
           ' ((spouse1_id=? AND spouse2_id=?) OR (spouse1_id=? AND spouse2_id=?))')
    args = [family_id, s1, s2, s2, s1]
    if exclude_id:
        sql += ' AND id<>?'
        args.append(exclude_id)
    if query_one(sql, args):
        raise ApiError('这两位成员之间已存在婚姻记录')


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
    audit.log(current_user()['id'], family_id, 'update_family', 'family', family_id)
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
    row = query_one('SELECT role FROM family_members WHERE family_id=? AND user_id=?', (family_id, uid))
    if row and row['role'] == 'admin':
        admins = query('SELECT id FROM family_members WHERE family_id=? AND role="admin"', (family_id,))
        if len(admins) <= 1:
            raise ApiError('至少需要保留一名家谱管理员')
    execute('DELETE FROM family_members WHERE family_id=? AND user_id=?', (family_id, uid))
    audit.log(current_user()['id'], family_id, 'revoke_member', 'user', uid)
    return jsonify({'code': 0, 'msg': '已移出家谱', 'data': None})


@bp.get('/<int:family_id>/members/search')
@require_login
@require_family(WRITE_ROLE)
def member_search(family_id):
    """搜索可加入本谱的用户（排除已在谱内；仅家谱管理员可用）"""
    kw = (request.args.get('keyword') or '').strip()
    if not kw:
        return jsonify({'code': 0, 'msg': 'ok', 'data': []})
    rows = query('SELECT id, username, real_name, phone FROM users'
                 ' WHERE (username LIKE ? OR real_name LIKE ? OR phone LIKE ?)'
                 ' AND id NOT IN (SELECT user_id FROM family_members WHERE family_id=?) LIMIT 20',
                 (f'%{kw}%', f'%{kw}%', f'%{kw}%', family_id))
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


# ---------------- 成员 ----------------
@bp.get('/<int:family_id>/persons')
@require_login
@require_family('member')
def person_list(family_id):
    page, size = valid.page_args()
    kw = (request.args.get('keyword') or '').strip()
    gen = valid.query_int('generation', minimum=1)
    ptype = valid.query_int('type', minimum=1, maximum=6)
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
    ptype = valid.to_int(data.get('type'), 'type', 1, minimum=1, maximum=6)
    branch_id = valid.to_optional_id(data.get('branch_id'), 'branch_id')
    if branch_id is not None:
        assert_in_family('branch', branch_id, family_id)
    ts = now_str()
    cols = ['family_id'] + list(PERSON_FIELDS) + ['created_at', 'updated_at']
    vals = [family_id, gen, name, data.get('courtesy_name'), data.get('art_name'), ptype,
            data.get('birth_date'), data.get('birth_place'), data.get('death_date'),
            data.get('bury_address'), data.get('record'), data.get('notes'), branch_id,
            1 if data.get('is_private') else 0, ts, ts]
    pid = execute(f'INSERT INTO person ({",".join(cols)}) VALUES ({",".join(["?"] * len(cols))})', vals)
    audit.log(current_user()['id'], family_id, 'create_person', 'person', pid, name)
    return jsonify({'code': 0, 'msg': '成员已添加', 'data': {'id': pid}})


@bp.put('/<int:family_id>/persons/<int:pid>')
@require_login
@require_family(WRITE_ROLE)
def person_update(family_id, pid):
    assert_in_family('person', pid, family_id)
    data = request.get_json(silent=True) or {}
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
        put('type', valid.to_int(data.get('type'), 'type', minimum=1, maximum=6))
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
    if not fields:
        raise ApiError('没有需要更新的字段')
    fields.append('updated_at=?')
    args += [now_str(), pid]
    execute(f'UPDATE person SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_person', 'person', pid, data.get('name'))
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
    rows = query('SELECT m.*, p1.name AS spouse1_name, p2.name AS spouse2_name'
                 ' FROM marriage m JOIN person p1 ON p1.id=m.spouse1_id'
                 ' JOIN person p2 ON p2.id=m.spouse2_id'
                 ' WHERE m.family_id=? ORDER BY m.id DESC', (family_id,))
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
    ts = now_str()
    mid = execute(
        'INSERT INTO marriage (family_id, spouse1_id, spouse2_id, marriage_order, marriage_date,'
        ' divorce_date, marriage_place, description, notes, created_at, updated_at)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (family_id, s1, s2, valid.to_int(data.get('marriage_order'), 'marriage_order', 1, minimum=1),
         data.get('marriage_date'), data.get('divorce_date'), data.get('marriage_place'),
         data.get('description'), data.get('notes'), ts, ts))
    audit.log(current_user()['id'], family_id, 'create_marriage', 'marriage', mid)
    return jsonify({'code': 0, 'msg': '婚姻已登记', 'data': {'id': mid}})


@bp.put('/<int:family_id>/marriages/<int:mid>')
@require_login
@require_family(WRITE_ROLE)
def marriage_update(family_id, mid):
    assert_in_family('marriage', mid, family_id)
    data = request.get_json(silent=True) or {}
    current = query_one('SELECT spouse1_id, spouse2_id FROM marriage WHERE id=?', (mid,))
    s1 = valid.to_int(data.get('spouse1_id'), 'spouse1_id', current['spouse1_id'], minimum=1) \
        if 'spouse1_id' in data else current['spouse1_id']
    s2 = valid.to_int(data.get('spouse2_id'), 'spouse2_id', current['spouse2_id'], minimum=1) \
        if 'spouse2_id' in data else current['spouse2_id']
    if s1 == s2:
        raise ApiError('配偶不能为同一人')
    for pid in (s1, s2):
        assert_in_family('person', pid, family_id)
    _assert_unique_marriage(family_id, s1, s2, exclude_id=mid)
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
    fields.append('updated_at=?')
    args += [now_str(), mid]
    execute(f'UPDATE marriage SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_marriage', 'marriage', mid)
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/marriages/<int:mid>')
@require_login
@require_family(WRITE_ROLE)
def marriage_delete(family_id, mid):
    assert_in_family('marriage', mid, family_id)
    execute('DELETE FROM marriage WHERE id=?', (mid,))
    audit.log(current_user()['id'], family_id, 'delete_marriage', 'marriage', mid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


# ---------------- 亲子 ----------------
@bp.get('/<int:family_id>/parentchild')
@require_login
@require_family('member')
def pc_list(family_id):
    rows = query('SELECT pc.*, p1.name AS parent_name, p2.name AS child_name'
                 ' FROM parentchild pc JOIN person p1 ON p1.id=pc.parent_id'
                 ' JOIN person p2 ON p2.id=pc.child_id'
                 ' WHERE pc.family_id=? ORDER BY pc.id DESC', (family_id,))
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.post('/<int:family_id>/parentchild')
@require_login
@require_family(WRITE_ROLE)
def pc_create(family_id):
    """支持一次登记多名子女"""
    data = request.get_json(silent=True) or {}
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
            execute('INSERT INTO parentchild (family_id, parent_id, child_id, type, description,'
                    ' notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)',
                    (family_id, parent_id, cid, ptype, data.get('description'),
                     data.get('notes'), ts, ts))
            count += 1
    audit.log(current_user()['id'], family_id, 'create_parentchild', 'parentchild', parent_id,
              f'{count} 条')
    return jsonify({'code': 0, 'msg': f'已登记 {count} 条亲子关系', 'data': {'count': count}})


@bp.put('/<int:family_id>/parentchild/<int:pcid>')
@require_login
@require_family(WRITE_ROLE)
def pc_update(family_id, pcid):
    assert_in_family('parentchild', pcid, family_id)
    data = request.get_json(silent=True) or {}
    current = query_one('SELECT parent_id, child_id FROM parentchild WHERE id=?', (pcid,))
    parent_id = valid.to_int(data.get('parent_id'), 'parent_id', current['parent_id'], minimum=1) \
        if 'parent_id' in data else current['parent_id']
    child_id = valid.to_int(data.get('child_id'), 'child_id', current['child_id'], minimum=1) \
        if 'child_id' in data else current['child_id']
    assert_in_family('person', parent_id, family_id)
    assert_in_family('person', child_id, family_id)
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
    for key in ('parent_id', 'child_id', 'type', 'description', 'notes'):
        if key in data:
            fields.append(f'{key}=?')
            if key == 'type':
                args.append(valid.to_int(data[key], 'type', minimum=1, maximum=7))
            elif key.endswith('_id'):
                args.append(valid.to_int(data[key], key, minimum=1))
            else:
                args.append(data[key])
    if fields:
        fields.append('updated_at=?')
        args += [now_str(), pcid]
        execute(f'UPDATE parentchild SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_parentchild', 'parentchild', pcid)
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/parentchild/<int:pcid>')
@require_login
@require_family(WRITE_ROLE)
def pc_delete(family_id, pcid):
    assert_in_family('parentchild', pcid, family_id)
    execute('DELETE FROM parentchild WHERE id=?', (pcid,))
    audit.log(current_user()['id'], family_id, 'delete_parentchild', 'parentchild', pcid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


# ---------------- 分支 ----------------
@bp.get('/<int:family_id>/branches')
@require_login
@require_family('member')
def branch_list(family_id):
    rows = query('SELECT b.*, (SELECT COUNT(*) FROM person p WHERE p.branch_id=b.id) AS person_count'
                 ' FROM branch b WHERE b.family_id=? ORDER BY b.id', (family_id,))
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
    data = request.get_json(silent=True) or {}
    fields, args = [], []
    for key in ('parent_id', 'name', 'origin_place', 'establish_time', 'description',
                'hall_name', 'generation_chars', 'direction'):
        if key in data:
            if key == 'parent_id':
                parent_id = valid.to_optional_id(data[key], 'parent_id')
                if parent_id is not None:
                    assert_in_family('branch', parent_id, family_id)
                    if parent_id == bid:
                        raise ApiError('上级分支不能是自己')
                fields.append('parent_id=?')
                args.append(parent_id)
                continue
            fields.append(f'{key}=?')
            args.append(data[key])
    person_ids = valid.to_id_list(data.get('person_ids'), 'person_ids') \
        if 'person_ids' in data else None
    if person_ids is not None:
        # 先校验全部成员归属，再进事务改数据：不会出现「清空后写回失败」的半成品
        _assert_persons_in_family(family_id, person_ids)
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
    audit.log(current_user()['id'], family_id, 'update_branch', 'branch', bid)
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
