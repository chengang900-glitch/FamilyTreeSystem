"""认证：密码哈希、JWT 签发与校验、登录锁定"""
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from server.common import now_str
from server.db.conn import query_one, execute
from server.service import settings

ACCESS_COOKIE = 'fts_token'


def _secret() -> str:
    key = current_app.config.get('SECRET_KEY')
    if key:
        return key
    path = Path(current_app.config['SECRET_KEY_FILE'])
    if path.exists():
        key = path.read_text(encoding='utf-8').strip()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        path.write_text(key, encoding='utf-8')
    current_app.config['SECRET_KEY'] = key
    return key


def hash_password(raw: str) -> str:
    return generate_password_hash(raw, method='scrypt')


def verify_password(stored: str, raw: str) -> bool:
    try:
        return check_password_hash(stored, raw)
    except Exception:
        return False


def validate_password(raw: str):
    """按系统设置校验密码强度，返回错误文案或 None"""
    if not raw:
        return '密码不能为空'
    if len(raw) < settings.get_int('security.password_min_length', 8):
        return f"密码长度不能少于 {settings.get_int('security.password_min_length', 8)} 位"
    if settings.get_bool('security.password_require_strong', True):
        if not any(c.isalpha() for c in raw) or not any(c.isdigit() for c in raw):
            return '密码需同时包含字母与数字'
    return None


def issue_token(user_row, remember=False) -> str:
    hours = settings.get_int('security.refresh_days', 7) * 24 if remember \
        else settings.get_int('security.session_hours', 8)
    payload = {
        'uid': user_row['id'],
        'tv': user_row['token_version'],
        'exp': datetime.now(timezone.utc) + timedelta(hours=hours),
        'iat': datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _secret(), algorithm='HS256')


def decode_token(token: str):
    try:
        return jwt.decode(token, _secret(), algorithms=['HS256'])
    except jwt.PyJWTError:
        return None


def user_from_token(token: str):
    payload = decode_token(token)
    if not payload:
        return None
    row = query_one('SELECT * FROM users WHERE id=?', (payload['uid'],))
    if row is None or row['status'] != 1:
        return None
    if row['token_version'] != payload.get('tv'):
        return None
    return row


def is_locked(row) -> bool:
    if not row['locked_until']:
        return False
    return now_str() < row['locked_until']


def register_fail(user_id):
    limit = settings.get_int('security.login_fail_limit', 5)
    minutes = settings.get_int('security.login_lock_minutes', 10)
    row = query_one('SELECT failed_count FROM users WHERE id=?', (user_id,))
    count = (row['failed_count'] if row else 0) + 1
    locked = None
    if count >= limit:
        count = 0
        locked = (datetime.now(timezone(timedelta(hours=8)))
                  + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    execute('UPDATE users SET failed_count=?, locked_until=?, updated_at=? WHERE id=?',
            (count, locked, now_str(), user_id))


def clear_fail(user_id):
    execute('UPDATE users SET failed_count=0, locked_until=NULL WHERE id=?', (user_id,))


def cookie_max_age(remember=False) -> int:
    if remember:
        return settings.get_int('security.refresh_days', 7) * 86400
    return settings.get_int('security.session_hours', 8) * 3600


def set_auth_cookie(resp, token: str, remember=False):
    """统一下发会话 Cookie（httpOnly + SameSite=Strict + 可选 Secure）"""
    resp.set_cookie(
        ACCESS_COOKIE, token,
        httponly=True, samesite='Strict',
        secure=settings.get_bool('security.force_https', False),
        max_age=cookie_max_age(remember), path='/')
    return resp


def bump_token_version(user_id):
    """使该用户已签发的所有令牌立即失效（改密 / 重置 / 登出）"""
    execute('UPDATE users SET token_version=token_version+1, updated_at=? WHERE id=?',
            (now_str(), user_id))


def client_ip() -> str:
    """真实客户端 IP：仅当直连对端是受信代理时才采信 X-Forwarded-For"""
    from server.service.netutil import client_ip as _client_ip
    return _client_ip()
