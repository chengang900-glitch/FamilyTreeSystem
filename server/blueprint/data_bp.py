"""事件、文献资源、资源关联与鉴权下载"""
import os
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from server.common import ApiError, now_str
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, settings, valid
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


def _upload_dir(family_id) -> Path:
    slug = query_one('SELECT slug FROM family WHERE id=?', (family_id,))['slug']
    path = Path(current_app.config['UPLOAD_DIR']) / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------- 事件 ----------------
@bp.get('/<int:family_id>/events')
@require_login
@require_family('member')
def event_list(family_id):
    rows = query('SELECT e.*, b.name AS branch_name,'
                 ' (SELECT COUNT(*) FROM eventperson ep WHERE ep.event_id=e.id) AS person_count'
                 ' FROM event e LEFT JOIN branch b ON b.id=e.branch_id'
                 ' WHERE e.family_id=? ORDER BY e.time DESC, e.id DESC', (family_id,))
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
    return jsonify({'code': 0, 'msg': '事件已添加', 'data': {'id': eid}})


@bp.put('/<int:family_id>/events/<int:eid>')
@require_login
@require_family('admin')
def event_update(family_id, eid):
    assert_in_family('event', eid, family_id)
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
        fields.append('updated_at=?')
        args += [now_str(), eid]
        execute(f'UPDATE event SET {",".join(fields)} WHERE id=?', args)
    audit.log(current_user()['id'], family_id, 'update_event', 'event', eid)
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
    execute('DELETE FROM eventperson WHERE id=? AND family_id=?', (epid, family_id))
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
    rows = query(f'SELECT * FROM resource WHERE {" AND ".join(where)} ORDER BY id DESC', args)
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
    rel = str(target.relative_to(current_app.config['UPLOAD_DIR'])).replace('\\', '/')
    rid = execute(
        'INSERT INTO resource (family_id, name, fid, type, storage_path, file_size, mime_type,'
        ' description, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (family_id, name, fid, rtype, rel, size, MIME_MAP.get(ext, file.mimetype),
         request.form.get('description'), request.form.get('notes'), now_str(), now_str()))
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
    audit.log(current_user()['id'], family_id, 'update_resource', 'resource', rid)
    return jsonify({'code': 0, 'msg': '已保存', 'data': None})


@bp.delete('/<int:family_id>/resources/<int:rid>')
@require_login
@require_family('admin')
def resource_delete(family_id, rid):
    row = query_one('SELECT * FROM resource WHERE id=?', (rid,))
    if row is None or row['family_id'] != family_id:
        raise ApiError('资源不存在', code=404)
    path = Path(current_app.config['UPLOAD_DIR']) / row['storage_path']
    with transaction():
        execute('DELETE FROM resource_relation WHERE resource_id=? AND family_id=?', (rid, family_id))
        execute('DELETE FROM resource WHERE id=?', (rid,))
    # 数据库记录提交成功后再删文件，避免事务回滚后文件已丢失
    if path.exists():
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
    execute('DELETE FROM resource_relation WHERE id=? AND family_id=?', (relid, family_id))
    return jsonify({'code': 0, 'msg': '关联已移除', 'data': None})


# ---------------- 鉴权下载 ----------------
@bp.get('/<int:family_id>/files/<int:rid>')
@require_login
@require_family('member')
def file_download(family_id, rid):
    row = query_one('SELECT * FROM resource WHERE id=? AND family_id=?', (rid, family_id))
    if row is None:
        raise ApiError('资源不存在', code=404)
    path = Path(current_app.config['UPLOAD_DIR']) / row['storage_path']
    if not path.exists():
        raise ApiError('文件已丢失', code=404)
    ext = path.suffix.lstrip('.')
    return send_file(str(path), as_attachment=True, download_name=f'{row["name"]}.{ext}'
                     if ext and not row['name'].endswith(ext) else row['name'])
