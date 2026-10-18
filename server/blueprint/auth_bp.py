"""认证：登录、登出、当前用户、修改密码"""
from flask import Blueprint, make_response, request

from server.common import ApiError, now_str, ok
from server.db.conn import execute, query, query_one
from server.service import audit, auth, settings
from server.service.permission import current_user, require_login, visible_families

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _profile(user):
    families = []
    for f in visible_families(user):
        families.append({
            'id': f['id'], 'name': f['name'], 'slug': f['slug'],
            'surname': f['surname'], 'visibility': f['visibility'], 'role': f['role'],
        })
    return {
        'id': user['id'], 'username': user['username'], 'real_name': user['real_name'],
        'phone': user['phone'], 'email': user['email'],
        'is_superuser': bool(user['is_superuser']),
        'must_change_pwd': bool(user['must_change_pwd']),
        'families': families,
    }


@bp.post('/login')
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    remember = bool(data.get('remember'))
    if not username or not password:
        raise ApiError('请输入账号与密码')

    row = query_one('SELECT * FROM users WHERE username=?', (username,))
    if row is None:
        raise ApiError('账号或密码错误')
    if auth.is_locked(row):
        raise ApiError(f"账号已锁定，请在 {row['locked_until']} 后重试")
    if not auth.verify_password(row['password_hash'], password):
        auth.register_fail(row['id'])
        audit.log(row['id'], None, 'login_fail', detail=username)
        raise ApiError('账号或密码错误')
    if row['status'] != 1:
        raise ApiError('账号已停用，请联系管理员')

    auth.clear_fail(row['id'])
    execute('UPDATE users SET last_login_at=?, updated_at=? WHERE id=?',
            (now_str(), now_str(), row['id']))
    audit.log(row['id'], None, 'login')
    token = auth.issue_token(row, remember)
    resp = make_response(ok(_profile(row)))
    auth.set_auth_cookie(resp, token, remember)
    return resp


@bp.post('/logout')
@require_login
def logout():
    user = current_user()
    auth.bump_token_version(user['id'])
    audit.log(user['id'], None, 'logout')
    resp = make_response(ok())
    resp.delete_cookie(auth.ACCESS_COOKIE, path='/')
    return resp


@bp.get('/me')
@require_login
def me():
    user = current_user()
    data = _profile(user)
    data['site_name'] = settings.get_str('site.name', '家谱管理系统')
    data['page_size'] = settings.get_int('site.page_size', 50)
    return ok(data)


@bp.put('/password')
@require_login
def change_password():
    user = current_user()
    data = request.get_json(silent=True) or {}
    old = data.get('old_password') or ''
    new = data.get('new_password') or ''
    if not auth.verify_password(user['password_hash'], old):
        raise ApiError('原密码不正确')
    err = auth.validate_password(new)
    if err:
        raise ApiError(err)
    execute('UPDATE users SET password_hash=?, must_change_pwd=0, updated_at=? WHERE id=?',
            (auth.hash_password(new), now_str(), user['id']))
    # 改密即让所有旧令牌失效（含密码泄露场景），并给当前会话换发新令牌
    auth.bump_token_version(user['id'])
    audit.log(user['id'], None, 'change_password')
    row = query_one('SELECT * FROM users WHERE id=?', (user['id'],))
    resp = make_response(ok(msg='密码已更新'))
    auth.set_auth_cookie(resp, auth.issue_token(row), remember=False)
    return resp


@bp.get('/logs')
@require_login
def my_logs():
    user = current_user()
    rows = query('SELECT * FROM operation_log WHERE user_id=? ORDER BY id DESC LIMIT 50',
                 (user['id'],))
    return ok([dict(r) for r in rows])
