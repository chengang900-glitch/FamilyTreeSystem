"""超级管理员：用户管理、家谱管理、角色指派、日志、备份"""
import io
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, request, send_file

from server.common import ApiError, now_str, ok
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, auth, settings, valid
from server.service.filepath import safe_upload_path
from server.service.permission import current_user, require_super_admin

bp = Blueprint('admin', __name__, url_prefix='/api/admin')


def _user_row(r):
    families = query(
        'SELECT f.id, f.name, fm.role FROM family_members fm'
        ' JOIN family f ON f.id=fm.family_id WHERE fm.user_id=?', (r['id'],))
    return {
        'id': r['id'], 'username': r['username'], 'real_name': r['real_name'],
        'phone': r['phone'], 'email': r['email'], 'status': r['status'],
        'is_superuser': bool(r['is_superuser']),
        'must_change_pwd': bool(r['must_change_pwd']),
        'last_login_at': r['last_login_at'], 'created_at': r['created_at'],
        'families': [{'id': f['id'], 'name': f['name'], 'role': f['role']} for f in families],
    }


@bp.get('/users')
@require_super_admin
def list_users():
    kw = (request.args.get('keyword') or '').strip()
    sql = 'SELECT * FROM users'
    args = []
    if kw:
        sql += ' WHERE username LIKE ? OR real_name LIKE ? OR phone LIKE ?'
        args = [f'%{kw}%'] * 3
    sql += ' ORDER BY id'
    rows = query(sql, args)
    return ok([_user_row(r) for r in rows])


@bp.post('/users')
@require_super_admin
def create_user():
    me = current_user()
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username):
        raise ApiError('账号需为 3-32 位字母、数字、下划线、点或连字符')
    if query_one('SELECT id FROM users WHERE username=?', (username,)):
        raise ApiError('账号已存在')
    err = auth.validate_password(password)
    if err:
        raise ApiError(err)
    uid = execute(
        'INSERT INTO users (username, password_hash, real_name, phone, email, status,'
        ' is_superuser, must_change_pwd, token_version, created_at, updated_at)'
        ' VALUES (?,?,?,?,?,?,?,?,1,?,?)',
        (username, auth.hash_password(password), data.get('real_name'),
         data.get('phone'), data.get('email'),
         1 if data.get('status', 1) else 0,
         1 if data.get('is_superuser') else 0,
         1 if data.get('must_change_pwd', 1) else 0,
         now_str(), now_str()))
    audit.log(me['id'], None, 'create_user', 'user', uid, username)
    return ok({'id': uid}, msg='用户已创建')


@bp.put('/users/<int:uid>')
@require_super_admin
def update_user(uid):
    me = current_user()
    row = query_one('SELECT * FROM users WHERE id=?', (uid,))
    if row is None:
        raise ApiError('用户不存在', code=404)
    data = request.get_json(silent=True) or {}
    fields = []
    args = []
    for key in ('real_name', 'phone', 'email'):
        if key in data:
            fields.append(f'{key}=?')
            args.append(data[key])
    if 'status' in data:
        if uid == me['id'] and not data['status']:
            raise ApiError('不能停用自己；请由另一位超级管理员操作')
        fields.append('status=?')
        args.append(1 if data['status'] else 0)
    if 'is_superuser' in data:
        if uid == me['id'] and not data['is_superuser']:
            raise ApiError('不能取消自己的超级管理员权限')
        fields.append('is_superuser=?')
        args.append(1 if data['is_superuser'] else 0)
    if fields:
        fields.append('updated_at=?')
        args.append(now_str())
        args.append(uid)
        execute(f'UPDATE users SET {",".join(fields)} WHERE id=?', args)
    audit.log(me['id'], None, 'update_user', 'user', uid,
              audit.change(row, data, ('real_name', 'phone', 'email', 'status', 'is_superuser')))
    return ok(msg='已保存')


@bp.delete('/users/<int:uid>')
@require_super_admin
def delete_user(uid):
    me = current_user()
    if uid == me['id']:
        raise ApiError('不能删除自己')
    # 不允许删掉某家谱唯一的管理员，否则会留下无人可管的家谱
    sole = query(
        'SELECT f.name FROM family_members fm JOIN family f ON f.id=fm.family_id'
        " WHERE fm.user_id=? AND fm.role='admin'"
        ' AND (SELECT COUNT(*) FROM family_members m2 WHERE m2.family_id=fm.family_id'
        " AND m2.role='admin') = 1", (uid,))
    if sole:
        names = '、'.join(r['name'] for r in sole)
        raise ApiError(f'该用户是「{names}」的唯一家谱管理员，请先指派新的管理员')
    with transaction():
        execute('DELETE FROM family_members WHERE user_id=?', (uid,))
        execute('DELETE FROM users WHERE id=?', (uid,))
    audit.log(me['id'], None, 'delete_user', 'user', uid)
    return ok(msg='用户已删除')


@bp.post('/users/<int:uid>/reset-password')
@require_super_admin
def reset_password(uid):
    me = current_user()
    if query_one('SELECT id FROM users WHERE id=?', (uid,)) is None:
        raise ApiError('用户不存在', code=404)
    data = request.get_json(silent=True) or {}
    password = data.get('password') or ''
    err = auth.validate_password(password)
    if err:
        raise ApiError(err)
    execute('UPDATE users SET password_hash=?, must_change_pwd=1, failed_count=0,'
            ' locked_until=NULL, token_version=token_version+1, updated_at=? WHERE id=?',
            (auth.hash_password(password), now_str(), uid))
    audit.log(me['id'], None, 'reset_password', 'user', uid)
    return ok(msg='密码已重置，该用户下次登录需修改密码')


@bp.get('/families')
@require_super_admin
def list_families():
    rows = query('SELECT f.*, (SELECT COUNT(*) FROM family_members m WHERE m.family_id=f.id) AS member_count,'
                 ' (SELECT COUNT(*) FROM person p WHERE p.family_id=f.id) AS person_count'
                 ' FROM family f ORDER BY f.id')
    return ok([dict(r) for r in rows])


@bp.post('/families')
@require_super_admin
def create_family():
    me = current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        raise ApiError('请输入家谱名称')
    slug = uuid.uuid4().hex[:10]
    visibility = valid.to_int(data.get('visibility'), 'visibility', 0, minimum=0, maximum=1)
    with transaction():
        fid = execute(
            'INSERT INTO family (name, slug, surname, hall_name, generation_chars, generation_frozen,'
            ' origin_place, compiler, description, visibility, status, created_by, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (name, slug, data.get('surname'), data.get('hall_name'), data.get('generation_chars'),
             1 if data.get('generation_frozen') else 0, data.get('origin_place'),
             data.get('compiler'), data.get('description'),
             visibility, 1, me['id'], now_str(), now_str()))
        execute('UPDATE family SET slug=? WHERE id=?', (f'f{fid}', fid))
        execute('INSERT INTO family_members (family_id, user_id, role, granted_by, granted_at)'
                ' VALUES (?,?,?,?,?)', (fid, me['id'], 'admin', me['id'], now_str()))
    audit.log(me['id'], fid, 'create_family', 'family', fid, name)
    return ok({'id': fid, 'slug': f'f{fid}'}, msg='家谱已创建')


@bp.put('/families/<int:fid>')
@require_super_admin
def update_family(fid):
    me = current_user()
    current = query_one('SELECT * FROM family WHERE id=?', (fid,))
    if current is None:
        raise ApiError('家谱不存在', code=404)
    data = request.get_json(silent=True) or {}
    allowed = ('name', 'surname', 'hall_name', 'generation_chars', 'origin_place',
               'compiler', 'description')
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
    if 'status' in data:
        fields.append('status=?')
        args.append(1 if data['status'] else 0)
    if fields:
        fields.append('updated_at=?')
        args.append(now_str())
        args.append(fid)
        execute(f'UPDATE family SET {",".join(fields)} WHERE id=?', args)
    audit.log(me['id'], fid, 'update_family', 'family', fid,
              audit.change(current, data, tuple(allowed) + ('generation_frozen', 'visibility', 'status')))
    return ok(msg='已保存')


@bp.delete('/families/<int:fid>')
@require_super_admin
def delete_family(fid):
    me = current_user()
    fam = query_one('SELECT slug FROM family WHERE id=?', (fid,))
    if fam is None:
        raise ApiError('家谱不存在', code=404)
    with transaction():
        # 顺序必须满足外键：先删从属/关系表，再删人物，最后删家谱
        for table in ('eventperson', 'resource_relation', 'marriage', 'parentchild',
                      'person', 'event', 'branch', 'resource'):
            execute(f'DELETE FROM {table} WHERE family_id=?', (fid,))
        execute('DELETE FROM family_members WHERE family_id=?', (fid,))
        execute('DELETE FROM family WHERE id=?', (fid,))
    # 数据库提交成功后再清理上传目录，避免回滚后文件已经没了
    try:
        upload = safe_upload_path(fam['slug'])
    except ApiError:
        upload = None
    if upload is not None and upload.is_dir():
        shutil.rmtree(upload, ignore_errors=True)
    # operation_log 保留：审计留痕优先于「删谱即销账」
    audit.log(me['id'], fid, 'delete_family', 'family', fid)
    return ok(msg='家谱及其数据已删除')


@bp.get('/families/<int:fid>/members')
@require_super_admin
def family_members(fid):
    rows = query('SELECT u.id, u.username, u.real_name, u.phone, u.status, fm.role, fm.granted_at'
                 ' FROM family_members fm JOIN users u ON u.id=fm.user_id'
                 ' WHERE fm.family_id=? ORDER BY fm.role, u.id', (fid,))
    return ok([dict(r) for r in rows])


@bp.post('/families/<int:fid>/members')
@require_super_admin
def add_family_member(fid):
    me = current_user()
    data = request.get_json(silent=True) or {}
    uid = valid.to_int(data.get('user_id'), 'user_id', minimum=1, required=True)
    role = data.get('role') or 'member'
    if role not in ('admin', 'member'):
        raise ApiError('角色取值不合法')
    if query_one('SELECT id FROM users WHERE id=?', (uid,)) is None:
        raise ApiError('用户不存在', code=404)
    if query_one('SELECT id FROM family_members WHERE family_id=? AND user_id=?', (fid, uid)):
        raise ApiError('该用户已在此家谱中')
    execute('INSERT INTO family_members (family_id, user_id, role, granted_by, granted_at)'
            ' VALUES (?,?,?,?,?)', (fid, uid, role, me['id'], now_str()))
    audit.log(me['id'], fid, 'grant_role', 'user', uid, role)
    return ok(msg='已加入家谱')


@bp.put('/families/<int:fid>/members/<int:uid>')
@require_super_admin
def update_family_member(fid, uid):
    me = current_user()
    role = (request.get_json(silent=True) or {}).get('role')
    if role not in ('admin', 'member'):
        raise ApiError('角色取值不合法')
    row = query_one('SELECT role FROM family_members WHERE family_id=? AND user_id=?', (fid, uid))
    if row is None:
        raise ApiError('该用户不在此家谱中', code=404)
    if role == 'member' and row['role'] == 'admin':
        admins = query('SELECT id FROM family_members WHERE family_id=? AND role="admin"', (fid,))
        if len(admins) <= 1:
            raise ApiError('至少需要保留一名家谱管理员')
    execute('UPDATE family_members SET role=? WHERE family_id=? AND user_id=?', (role, fid, uid))
    audit.log(me['id'], fid, 'change_role', 'user', uid, role)
    return ok(msg='角色已更新')


@bp.delete('/families/<int:fid>/members/<int:uid>')
@require_super_admin
def remove_family_member(fid, uid):
    me = current_user()
    row = query_one('SELECT role FROM family_members WHERE family_id=? AND user_id=?', (fid, uid))
    if row and row['role'] == 'admin':
        admins = query('SELECT id FROM family_members WHERE family_id=? AND role="admin"', (fid,))
        if len(admins) <= 1:
            raise ApiError('至少需要保留一名家谱管理员')
    execute('DELETE FROM family_members WHERE family_id=? AND user_id=?', (fid, uid))
    audit.log(me['id'], fid, 'revoke_member', 'user', uid)
    return ok(msg='已移出家谱')


@bp.get('/logs')
@require_super_admin
def logs():
    limit = valid.to_int(request.args.get('limit'), 'limit', 100, minimum=1, maximum=500)
    fid = valid.to_int(request.args.get('family_id'), 'family_id', minimum=1)
    sql = ('SELECT l.*, u.username FROM operation_log l LEFT JOIN users u ON u.id=l.user_id')
    args = []
    if fid:
        sql += ' WHERE l.family_id=?'
        args.append(fid)
    sql += ' ORDER BY l.id DESC LIMIT ?'
    args.append(limit)
    return ok([dict(r) for r in query(sql, args)])


@bp.get('/logs/export')
@require_super_admin
def logs_export():
    limit = valid.to_int(request.args.get('limit'), 'limit', 10000, minimum=1, maximum=10000)
    fid = valid.to_int(request.args.get('family_id'), 'family_id', minimum=1)
    sql = ('SELECT l.*, u.username FROM operation_log l LEFT JOIN users u ON u.id=l.user_id')
    args = []
    if fid:
        sql += ' WHERE l.family_id=?'
        args.append(fid)
    sql += ' ORDER BY l.id DESC LIMIT ?'
    args.append(limit)
    rows = query(sql, args)
    return send_file(io.BytesIO(audit.export_csv(rows)), mimetype='text/csv',
                     as_attachment=True, download_name='operation_logs.csv')


@bp.post('/backup')
@require_super_admin
def backup_now():
    from server.service.backup import do_backup
    path = do_backup()
    audit.log(current_user()['id'], None, 'backup')
    return ok({'file': path.name}, msg='备份已生成')


@bp.get('/backups')
@require_super_admin
def backup_list():
    from pathlib import Path
    from flask import current_app
    d = Path(current_app.config['BACKUP_DIR'])
    files = []
    if d.exists():
        for p in sorted(d.glob('backup_*.zip'), key=lambda x: x.stat().st_mtime, reverse=True):
            files.append({'name': p.name, 'size': p.stat().st_size,
                          'time': datetime.fromtimestamp(p.stat().st_mtime,
                                                         timezone(timedelta(hours=8)))
                          .strftime('%Y-%m-%d %H:%M:%S')})
    return ok(files)


@bp.get('/backups/<path:name>')
@require_super_admin
def backup_download(name):
    """下载备份 ZIP；只允许数据目录内的 backup_*.zip 文件名。"""
    if Path(name).name != name or not re.fullmatch(r'backup_[0-9_]+\.zip', name):
        raise ApiError('备份文件名不合法', code=400)
    path = Path(current_app.config['BACKUP_DIR']) / name
    if not path.is_file():
        raise ApiError('备份不存在', code=404)
    return send_file(str(path), as_attachment=True, download_name=name)


@bp.get('/stats')
@require_super_admin
def stats():
    return ok({
        'users': query_one('SELECT COUNT(*) c FROM users')['c'],
        'families': query_one('SELECT COUNT(*) c FROM family')['c'],
        'persons': query_one('SELECT COUNT(*) c FROM person')['c'],
        'pending_logs': query_one('SELECT COUNT(*) c FROM operation_log')['c'],
    })


@bp.get('/settings')
@require_super_admin
def get_settings():
    return ok(settings.all_settings())


@bp.put('/settings')
@require_super_admin
def put_settings():
    me = current_user()
    data = request.get_json(silent=True) or {}
    known = {r['key']: r['type'] for r in settings.all_settings()}
    items = {}
    for key, value in data.items():
        if key not in known:
            continue
        typ = known[key]
        if typ == 'bool':
            items[key] = bool(value) if isinstance(value, bool) else str(value).lower() in ('1', 'true', 'yes', 'on')
        elif typ == 'int':
            try:
                items[key] = int(value)
            except (TypeError, ValueError):
                raise ApiError(f'{key} 需为整数')
        else:
            items[key] = str(value)
    if items:
        settings.set_many(items)
        audit.log(me['id'], None, 'update_settings', detail=','.join(items.keys()))
    return ok(msg='设置已保存')
