"""系统设置：默认值、读取、写入

缓存策略：进程内缓存 + 30 秒 TTL。多 worker（gunicorn -w 2）部署下，
某个 worker 改了设置，其余 worker 最迟 30 秒后自然失效重读，
避免「改了密码策略但部分请求仍按旧策略执行」的随机漂移。
"""
import time

from server.common import now_str
from server.db.conn import execute, query, query_one

CACHE_TTL_SECONDS = 30

_cache = {}
_cache_at = 0.0
_cache_pid = None

# 已下线/从未实现的旧配置项：启动时清理，避免设置页出现「可点但无效」的开关
OBSOLETE_KEYS = ('access.public_read', 'member.scope', 'upload.max_mb')

DEFAULTS = [
    ('privacy.mask_living', 'false', 'bool', 'access', '在世者信息脱敏',
     '开启后，家族普通用户（非家谱管理员）看不到在世成员的生卒、籍贯与生平详情'),
    ('export.member_include_resources', 'false', 'bool', 'access', '普通用户可导出资源原件',
     '关闭时，普通用户导出的数据包不含文献原件，仅含数据'),
    ('security.password_min_length', '8', 'int', 'security', '密码最小长度', ''),
    ('security.password_require_strong', 'true', 'bool', 'security', '密码需字母+数字组合', ''),
    ('security.login_fail_limit', '5', 'int', 'security', '连续登录失败锁定阈值', ''),
    ('security.login_lock_minutes', '10', 'int', 'security', '锁定时长（分钟）', ''),
    ('security.session_hours', '8', 'int', 'security', '访问令牌有效期（小时）', ''),
    ('security.refresh_days', '7', 'int', 'security', '记住登录有效期（天）', ''),
    ('security.force_https', 'false', 'bool', 'security', '强制 HTTPS 与 HSTS',
     '公网部署请在 Nginx 终止 TLS 后开启'),
    ('security.allowed_origins', '', 'str', 'security', '允许的 Origin 白名单',
     '逗号分隔；留空表示仅允许同源'),
    ('security.rate_limit_per_minute', '120', 'int', 'security', '单 IP 每分钟请求上限', ''),
    ('security.login_limit_per_minute', '20', 'int', 'security', '登录接口每分钟尝试上限', ''),
    ('security.trusted_proxies', '127.0.0.1,::1', 'str', 'security', '受信反向代理地址',
     '逗号分隔的 IP/CIDR；仅这些地址发来的 X-Forwarded-For 会被采信。Docker 部署填 172.16.0.0/12'),
    ('site.name', '家谱管理系统', 'str', 'site', '站点名称', ''),
    ('site.page_size', '50', 'int', 'site', '列表默认分页条数', ''),
    ('storage.upload_max_mb', '200', 'int', 'storage', '单文件上传上限（MB）', ''),
    ('storage.default_strategy', 'append', 'str', 'storage', '数据导入默认策略',
     'append=追加导入；overwrite=先清空本谱业务数据再导入'),
    ('storage.backup_enabled', 'true', 'bool', 'storage', '自动备份开关', ''),
    ('storage.backup_interval_minutes', '60', 'int', 'storage', '自动备份间隔（分钟）', ''),
    ('storage.backup_keep_count', '5', 'int', 'storage', '自动备份保留份数', ''),
]


def ensure_defaults():
    ts = now_str()
    for key, value, typ, group, label, desc in DEFAULTS:
        row = query_one('SELECT key FROM system_settings WHERE key=?', (key,))
        if row is None:
            execute(
                'INSERT INTO system_settings (key, value, type, group_name, label, description, updated_at)'
                ' VALUES (?,?,?,?,?,?,?)',
                (key, value, typ, group, label, desc, ts))
    for key in OBSOLETE_KEYS:
        execute('DELETE FROM system_settings WHERE key=?', (key,))
    invalidate()


def _load_all():
    global _cache, _cache_at, _cache_pid
    import os
    pid = os.getpid()
    fresh = _cache and (time.time() - _cache_at) < CACHE_TTL_SECONDS and _cache_pid == pid
    if not fresh:
        rows = query('SELECT key, value FROM system_settings')
        _cache = {r['key']: r['value'] for r in rows}
        _cache_at = time.time()
        _cache_pid = pid
    return _cache


def get_raw(key, default=None):
    val = _load_all().get(key)
    return default if val is None else val


def get_str(key, default=''):
    return str(get_raw(key, default))


def get_int(key, default=0):
    try:
        return int(str(get_raw(key, default)))
    except (TypeError, ValueError):
        return default


def get_bool(key, default=False):
    val = str(get_raw(key, 'true' if default else 'false')).strip().lower()
    return val in ('1', 'true', 'yes', 'on')


def set_many(items: dict):
    ts = now_str()
    for key, value in items.items():
        typ = 'bool' if isinstance(value, bool) else 'int' if isinstance(value, int) else 'str'
        text = 'true' if value is True else 'false' if value is False else str(value)
        execute('UPDATE system_settings SET value=?, type=?, updated_at=? WHERE key=?',
                (text, typ, ts, key))
    invalidate()


def all_settings():
    rows = query('SELECT key, value, type, group_name, label, description, updated_at'
                 ' FROM system_settings ORDER BY group_name, key')
    out = []
    for r in rows:
        item = dict(r)
        item['value'] = _cast(r['value'], r['type'])
        out.append(item)
    return out


def _cast(text, typ):
    if typ == 'bool':
        return str(text).strip().lower() in ('1', 'true', 'yes', 'on')
    if typ == 'int':
        try:
            return int(text)
        except (TypeError, ValueError):
            return 0
    return text


def invalidate():
    global _cache, _cache_at
    _cache = {}
    _cache_at = 0.0
