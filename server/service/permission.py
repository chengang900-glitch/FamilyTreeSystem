"""权限：三级鉴权装饰器与越权校验"""
from functools import wraps

from flask import g

from server.common import ApiError
from server.db.conn import query, query_one

ROLE_LEVEL = {'member': 1, 'admin': 2}


def current_user():
    return getattr(g, 'current_user', None)


def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            raise ApiError('未登录或登录已过期', code=401)
        return f(*args, **kwargs)
    return wrapper


def require_super_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            raise ApiError('未登录或登录已过期', code=401)
        if not user['is_superuser']:
            raise ApiError('仅超级管理员可操作', code=403)
        return f(*args, **kwargs)
    return wrapper


def family_role(family_id, role='member'):
    """解析当前用户在该家谱中的角色，不满足则抛 403"""
    user = current_user()
    if user is None:
        raise ApiError('未登录或登录已过期', code=401)
    fam = query_one('SELECT status FROM family WHERE id=?', (family_id,))
    if fam is None:
        # 对普通用户不暴露家谱是否存在，统一返回无权限
        if user['is_superuser']:
            raise ApiError('家谱不存在', code=404)
        raise ApiError('无权访问该家谱', code=403)
    # 归档家谱不再允许普通成员访问；超管仍可维护
    if fam['status'] != 1 and not user['is_superuser']:
        raise ApiError('该家谱已归档，暂不可访问', code=403)
    if user['is_superuser']:
        return 'admin'
    row = query_one('SELECT role FROM family_members WHERE family_id=? AND user_id=?',
                    (family_id, user['id']))
    actual = row['role'] if row else None
    if actual is None:
        raise ApiError('无权访问该家谱', code=403)
    if ROLE_LEVEL.get(actual, 0) < ROLE_LEVEL.get(role, 1):
        raise ApiError('当前角色无权执行该操作', code=403)
    return actual


def require_family(role='member'):
    """装饰器：路径参数中须含 family_id"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            family_id = kwargs.get('family_id') or kwargs.get('fid')
            if family_id is None:
                raise ApiError('缺少家谱标识', code=400)
            g.family_role = family_role(int(family_id), role)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def assert_in_family(table, record_id, family_id):
    """写操作二次校验：目标记录必须属于当前家谱"""
    row = query_one(f'SELECT family_id FROM {table} WHERE id=?', (record_id,))
    if row is None:
        raise ApiError('记录不存在', code=404)
    if int(row['family_id']) != int(family_id):
        raise ApiError('记录不属于当前家谱', code=403)
    return True


def visible_families(user):
    """当前用户可访问的家谱列表（超管返回全部）"""
    if user['is_superuser']:
        return query_all_families()
    return query(
        'SELECT f.id, f.name, f.slug, f.surname, f.visibility, f.status, fm.role'
        ' FROM family_members fm JOIN family f ON f.id = fm.family_id'
        ' WHERE fm.user_id=? AND f.status=1 ORDER BY f.id', (user['id'],))


def query_all_families():
    from server.db.conn import query
    return query('SELECT id, name, slug, surname, visibility, status,'
                 " 'admin' AS role FROM family ORDER BY id")
