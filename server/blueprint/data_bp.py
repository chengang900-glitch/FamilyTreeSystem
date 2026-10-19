"""事件、文献资源、资源关联与鉴权下载"""
import os
import uuid

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from server.common import ApiError, now_str
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, dates, settings, valid
from server.service.filepath import safe_upload_path, upload_root
from server.service.permission import (
    assert_in_family, current_user, require_family, require_login,
)

bp = Blueprint('data', __name__, url_prefix='/api/families')

ALLOWED_EXT = {
    'pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tif', 'tiff',
    'mp4', 'mov', 'mp3', 'wav', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip',
}
MIME_MAP = {
    'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
    'gif': 'image/gif', 'webp': 'image/webp', 'mp4': 'video/mp4', 'mp3': 'audio/mpeg',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def _upload_dir(family_id):
    slug = query_one('SELECT slug FROM family WHERE id=?', (family_id,))['slug']
    # slug 也来自数据库，统一走安全路径校验，防止历史脏数据逃逸上传根目录
    path = safe_upload_path(slug)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------- 事件 ----------------
@bp.get('/<int:family_id>/relation-targets')
@require_login
@require_family('member')
def relation_targets(family_id):
    """文献关联对象统一分页搜索，只返回本谱 ID 与可公开姓名。"""
    kind = request.args.get('entity_type')
    sources = {
        'person': ('person t', "t.name || '（第' || t.generation || '世）'"),
        'branch': ('branch t', 't.name'),
        'event': ('event t', 't.name'),
        'marriage': ('marriage t JOIN person p1 ON p1.id=t.spouse1_id JOIN person p2 ON p2.id=t.spouse2_id',
                     "p1.name || ' & ' || p2.name"),
        'parentchild': ('parentchild t JOIN person p1 ON p1.id=t.parent_id JOIN person p2 ON p2.id=t.child_id',
                        "p1.name || ' → ' || p2.name"),
    }
    if kind not in sources:
        raise ApiError('关联实体类型不合法')
    source, label = sources[kind]
    page, size = valid.page_args()
    args = [family_id]
    where = 't.family_id=?'
    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        where += f' AND ({label}) LIKE ?'
        args.append(f'%{keyword}%')
    total = query_one(f'SELECT COUNT(*) c FROM {source} WHERE {where}', args)['c']
    rows = query(f'SELECT t.id,({label}) AS label FROM {source} WHERE {where}'
                 ' ORDER BY t.id LIMIT ? OFFSET ?', args + [size, (page - 1) * size])
    return jsonify({'code': 0, 'msg': 'ok', 'data': {
        'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size}})


@bp.get('/<int:family_id>/events')
@require_login
@require_family('member')
def event_list(family_id):
    kw = (request.args.get('keyword') or '').strip()
    where, args = ['e.family_id=?'], [family_id]
    if kw:
        where.append('(e.name LIKE ? OR e.place LIKE ?)')
        args += [f'%{kw}%', f'%{kw}%']
    cond = ' AND '.join(where)
    base = (' FROM event e LEFT JOIN branch b ON b.id=e.branch_id WHERE ')
    if valid.paged_request():
        page, size = valid.page_args()
        total = query_one(f'SELECT COUNT(*) c{base}{cond}', args)['c']
        rows = query(f'SELECT e.*, b.name AS branch_name,'
                     ' (SELECT COUNT(*) FROM eventperson ep WHERE ep.event_id=e.id) AS person_count'
                     f'{base}{cond} ORDER BY e.time DESC, e.id DESC LIMIT ? OFFSET ?',
                     args + [size, (page - 1) * size])
        return jsonify({'code': 0, 'msg': 'ok', 'data': {
            'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size}})
    rows = query(f'SELECT e.*, b.name AS branch_name,'
                 ' (SELECT COUNT(*) FROM eventperson ep WHERE ep.event_id=e.id) AS person_count'
                 f'{base}{cond} ORDER BY e.time DESC, e.id DESC', args)
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.post('/<int:family_id>/events')
@require_login
@require_family('admin')
def event_create(family_id):
    data = request.get_json(silent=True) or {}
    if not (data.get('name') or '').strip():
        raise ApiError('请输入事件名称')
    if not (data.get('time') or '').strip():
        raise ApiError('请输入事件时间')
    date_values = dates.values(data, dates.DATE_FIELDS['event'])
    branch_id = valid.to_optional_id(data.get('branch_id'), 'branch_id')
    if branch_id is not None:
        assert_in_family('branch', branch_id, family_id)
    ts = now_str()
    eid = execute(
        'INSERT INTO event (family_id, name, time, place, type, description, notes, branch_id,'
        ' created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (family_id, data['name'], data['time'], data.get('place'),
         valid.to_int(data.get('type'), 'type', 1, minimum=1, maximum=2),
         data.get('description'), data.get('notes'), branch_id, ts, ts))
    audit.log(current_user()['id'], family_id, 'create_event', 'event', eid, data['name'])
    execute('UPDATE event SET time_iso=?,time_precision=? WHERE id=?',
            (date_values.get('time_iso'), date_values.get('time_precision'), eid))
    return jsonify({'code': 0, 'msg': '事件已添加', 'data': {'id': eid}})


@bp.put('/<int:family_id>/events/<int:eid>')
@require_login
@require_family('admin')
def event_update(family_id, eid):
    assert_in_family('event', eid, family_id)
    current = query_one('SELECT * FROM event WHERE id=?', (eid,))
    data = request.get_json(silent=True) or {}
    fields, args = [], []
    for key in ('name', 'time', 'place', 'description', 'notes'):
        if key in data:
            fields.append(f'{key}=?')
            args.append(data[key])
    if 'type' in data:
        fields.append('type=?')
        args.append(valid.to_int(data['type'], 'type', minimum=1, maximum=2))
    if 'branch_id' in data:
        branch_id = valid.to_optional_id(data['branch_id'], 'branch_id')
        if branch_id is not None:
            assert_in_family('branch', branch_id, family_id)
        fields.append('branch_id=?')
        args.append(branch_id)
    if fields:
        for key, value in dates.values(data, dates.DATE_FIELDS['event'], current=current).items():
            if key != 'time':
                fields.append(f'{key}=?')
                args.append(value)
        fields.append('updated_at=?')
        args += [now_str(), eid]
        execute(f'UPDATE event SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_event', 'event', eid,
              audit.change(current, data, ('name', 'time', 'place', 'type',
                                           'description', 'notes', 'branch_id')))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/events/<int:eid>')
@require_login
@require_family('admin')
def event_delete(family_id, eid):
    assert_in_family('event', eid, family_id)
    with transaction():
        execute('DELETE FROM eventperson WHERE event_id=? AND family_id=?', (eid, family_id))
        execute('DELETE FROM resource_relation WHERE entity_type="event" AND entity_id=?'
                ' AND family_id=?', (eid, family_id))
        execute('DELETE FROM event WHERE id=?', (eid,))
    audit.log(current_user()['id'], family_id, 'delete_event', 'event', eid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})


@bp.get('/<int:family_id>/events/<int:eid>/persons')
@require_login
@require_family('member')
def event_persons(family_id, eid):
    assert_in_family('event', eid, family_id)
    rows = query('SELECT ep.*, p.name, p.generation FROM eventperson ep'
                 ' JOIN person p ON p.id=ep.person_id'
                 ' WHERE ep.event_id=? AND ep.family_id=? ORDER BY ep.id', (eid, family_id))
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.post('/<int:family_id>/events/<int:eid>/persons')
@require_login
@require_family('admin')
def event_person_add(family_id, eid):
    assert_in_family('event', eid, family_id)
    data = request.get_json(silent=True) or {}
    pid = valid.to_int(data.get('person_id'), 'person_id', minimum=1, required=True)
    assert_in_family('person', pid, family_id)
    if query_one('SELECT id FROM eventperson WHERE event_id=? AND person_id=?', (eid, pid)):
        raise ApiError('该成员已在参与人列表中')
    execute('INSERT INTO eventperson (family_id, event_id, person_id, role, description, notes,'
            ' created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)',
            (family_id, eid, pid, data.get('role'), data.get('description'),
             data.get('notes'), now_str(), now_str()))
    audit.log(current_user()['id'], family_id, 'event_add_person', 'event', eid, str(pid))
    return jsonify({'code': 0, 'msg': '参与人已添加', 'data': None})


@bp.delete('/<int:family_id>/events/<int:eid>/persons/<int:epid>')
@require_login
@require_family('admin')
def event_person_remove(family_id, eid, epid):
    assert_in_family('event', eid, family_id)
    execute('DELETE FROM eventperson WHERE id=? AND event_id=? AND family_id=?',
            (epid, eid, family_id))
    audit.log(current_user()['id'], family_id, 'event_remove_person', 'event', eid, str(epid))
    return jsonify({'code': 0, 'msg': '已移除', 'data': None})


# ---------------- 文献资源 ----------------
@bp.get('/<int:family_id>/resources')
@require_login
@require_family('member')
def resource_list(family_id):
    kw = (request.args.get('keyword') or '').strip()
    rtype = valid.query_int('type', minimum=1, maximum=7)
    where, args = ['family_id=?'], [family_id]
    if kw:
        where.append('name LIKE ?')
        args.append(f'%{kw}%')
    if rtype is not None:
        where.append('type=?')
        args.append(rtype)
    cond = ' AND '.join(where)
    if valid.paged_request():
        page, size = valid.page_args()
        total = query_one(f'SELECT COUNT(*) c FROM resource WHERE {cond}', args)['c']
        rows = query(f'SELECT * FROM resource WHERE {cond} ORDER BY id DESC LIMIT ? OFFSET ?',
                     args + [size, (page - 1) * size])
        return jsonify({'code': 0, 'msg': 'ok', 'data': {
            'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size}})
    rows = query(f'SELECT * FROM resource WHERE {cond} ORDER BY id DESC', args)
    return jsonify({'code': 0, 'msg': 'ok', 'data': [dict(r) for r in rows]})


@bp.post('/<int:family_id>/resources')
@require_login
@require_family('admin')
def resource_upload(family_id):
    file = request.files.get('file')
    if file is None or not file.filename:
        raise ApiError('请选择要上传的文件')
    ext = (file.filename.rsplit('.', 1)[-1] or '').lower()
    if ext not in ALLOWED_EXT:
        raise ApiError(f'不支持的文件类型：{ext}')
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    max_mb = settings.get_int('storage.upload_max_mb', 200)
    if size > max_mb * 1024 * 1024:
        raise ApiError(f'文件超过 {max_mb}MB 上限')
    name = (request.form.get('name') or '').strip() or file.filename
    rtype = valid.to_int(request.form.get('type'), 'type', 1, minimum=1, maximum=7)
    fid = uuid.uuid4().hex
    safe = secure_filename(file.filename) or f'{fid}.{ext}'
    stored = f'{fid}_{safe}'
    target = _upload_dir(family_id) / stored
    file.save(str(target))
    rel = target.relative_to(upload_root()).as_posix()
    try:
        rid = execute(
            'INSERT INTO resource (family_id, name, fid, type, storage_path, file_size, mime_type,'
            ' description, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (family_id, name, fid, rtype, rel, size, MIME_MAP.get(ext, file.mimetype),
             request.form.get('description'), request.form.get('notes'), now_str(), now_str()))
    except Exception:
        # 数据库写入失败时不要留下孤儿文件
        try:
            target.unlink()
        except OSError:
            pass
        raise
    audit.log(current_user()['id'], family_id, 'upload_resource', 'resource', rid, name)
    return jsonify({'code': 0, 'msg': '资源已入库', 'data': {'id': rid, 'fid': fid}})


@bp.put('/<int:family_id>/resources/<int:rid>')
@require_login
@require_family('admin')
def resource_update(family_id, rid):
    row = query_one('SELECT * FROM resource WHERE id=?', (rid,))
    if row is None or row['family_id'] != family_id:
        raise ApiError('资源不存在', code=404)
    data = request.get_json(silent=True) or {}
    fields, args = [], []
    for key in ('name', 'description', 'notes'):
        if key in data:
            fields.append(f'{key}=?')
            args.append(data[key])
    if 'type' in data:
        fields.append('type=?')
        args.append(valid.to_int(data['type'], 'type', minimum=1, maximum=7))
    if fields:
        fields.append('updated_at=?')
        args += [now_str(), rid]
        execute(f'UPDATE resource SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_resource', 'resource', rid,
              audit.change(row, data, ('name', 'type', 'description', 'notes')))
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/resources/<int:rid>')
@require_login
@require_family('admin')
def resource_delete(family_id, rid):
    row = query_one('SELECT * FROM resource WHERE id=?', (rid,))
    if row is None or row['family_id'] != family_id:
        raise ApiError('资源不存在', code=404)
    # 只有位于上传目录内的路径才允许删文件；非法路径仅删除数据库记录
    try:
        path = safe_upload_path(row['storage_path'])
    except ApiError:
        path = None
    with transaction():
        execute('DELETE FROM resource_relation WHERE resource_id=? AND family_id=?', (rid, family_id))
        execute('DELETE FROM resource WHERE id=?', (rid,))
    # 数据库记录提交成功后再删文件，避免事务回滚后文件已丢失
    if path is not None and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    audit.log(current_user()['id'], family_id, 'delete_resource', 'resource', rid)
    return jsonify({'code': 0, 'msg': '已删除', 'data': None})

@bp.get('/<int:family_id>/resources/<int:rid>/relations')
@require_login
@require_family('member')
def resource_relations(family_id, rid):
    rows = query('SELECT * FROM resource_relation WHERE resource_id=? AND family_id=?',
                 (rid, family_id))
    out = []
    for r in rows:
        item = dict(r)
        table = {'person': 'person', 'marriage': 'marriage', 'parentchild': 'parentchild',
                 'event': 'event', 'branch': 'branch'}.get(r['entity_type'])
        if table:
            row = query_one(f'SELECT * FROM {table} WHERE id=? AND family_id=?',
                            (r['entity_id'], family_id))
            if row:
                item['entity_name'] = row['name'] if 'name' in row.keys() else f"#{r['entity_id']}"
        out.append(item)
    return jsonify({'code': 0, 'msg': 'ok', 'data': out})


@bp.post('/<int:family_id>/resources/<int:rid>/relations')
@require_login
@require_family('admin')
def resource_relation_add(family_id, rid):
    row = query_one('SELECT id FROM resource WHERE id=? AND family_id=?', (rid, family_id))
    if row is None:
        raise ApiError('资源不存在', code=404)
    data = request.get_json(silent=True) or {}
    etype = data.get('entity_type')
    eid = valid.to_int(data.get('entity_id'), 'entity_id', minimum=1, required=True)
    if etype not in ('person', 'marriage', 'parentchild', 'event', 'branch'):
        raise ApiError('实体类型不合法')
    target = query_one(f'SELECT id FROM {etype} WHERE id=? AND family_id=?', (eid, family_id))
    if target is None:
        raise ApiError('关联对象不存在或不属于本家谱', code=404)
    if query_one('SELECT id FROM resource_relation WHERE resource_id=? AND entity_type=?'
                 ' AND entity_id=?', (rid, etype, eid)):
        raise ApiError('已存在该关联')
    execute('INSERT INTO resource_relation (family_id, resource_id, entity_type, entity_id,'
            ' notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?)',
            (family_id, rid, etype, eid, data.get('notes'), now_str(), now_str()))
    return jsonify({'code': 0, 'msg': '关联已添加', 'data': None})


@bp.delete('/<int:family_id>/resources/<int:rid>/relations/<int:relid>')
@require_login
@require_family('admin')
def resource_relation_del(family_id, rid, relid):
    execute('DELETE FROM resource_relation WHERE id=? AND resource_id=? AND family_id=?',
            (relid, rid, family_id))
    audit.log(current_user()['id'], family_id, 'delete_resource_relation', 'resource', rid,
              str(relid))
    return jsonify({'code': 0, 'msg': '关联已移除', 'data': None})


# ---------------- 鉴权下载 ----------------
@bp.get('/<int:family_id>/files/<int:rid>')
@require_login
@require_family('member')
def file_download(family_id, rid):
    row = query_one('SELECT * FROM resource WHERE id=? AND family_id=?', (rid, family_id))
    if row is None:
        raise ApiError('资源不存在', code=404)
    path = safe_upload_path(row['storage_path'], must_exist=True)
    ext = path.suffix.lstrip('.')
    inline = request.args.get('inline') in ('1', 'true', 'True')
    return send_file(str(path), as_attachment=not inline,
                     download_name=f'{row["name"]}.{ext}'
                     if ext and not row['name'].endswith(ext) else row['name'])
