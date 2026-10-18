"""应用工厂：配置、鉴权中间件、安全头、静态资源与 SPA 回退"""
import logging
import logging.handlers
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import yaml
from flask import Flask, current_app, g, jsonify, request, send_file, send_from_directory
from werkzeug.security import generate_password_hash

from server.common import ApiError, now_str
from server.db.conn import close_db, execute, init_db, query_one
from server.service import auth, settings

BASE_DIR = Path(__file__).resolve().parents[1]

# 单 IP 请求桶：{key: deque[timestamp]}。定期清扫，避免无限增长
_rate_bucket = defaultdict(deque)
_rate_lock = threading.Lock()
_rate_swept_at = 0.0
RATE_SWEEP_SECONDS = 60
RATE_IDLE_SECONDS = 120

# 必须改密时仍可访问的接口（改密流程本身 + 身份查询 + 登出）
MUST_CHANGE_ALLOW = {
    '/api/auth/me', '/api/auth/password', '/api/auth/logout', '/api/health',
}
PWD_CHANGE_REQUIRED = 4031


def setup_logging(app):
    """文件 + 控制台日志；重复创建 app（自测）时不会叠加 handler"""
    if getattr(app, '_fts_logging', False):
        return
    log_dir = Path(os.environ.get('FTS_LOG_DIR') or (BASE_DIR / 'log'))
    fmt = logging.Formatter('%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s')
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / 'server.log', maxBytes=5 * 1024 * 1024, backupCount=3,
            encoding='utf-8', delay=True)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    app._fts_logging = True


def create_app(config_path=None):
    app = Flask(__name__, static_folder=None)
    cfg_file = config_path or os.environ.get('FTS_CONFIG') or (BASE_DIR / 'server' / 'config.yaml')
    cfg = yaml.safe_load(Path(cfg_file).read_text(encoding='utf-8'))
    setup_logging(app)

    def abspath(p):
        path = Path(p)
        return path if path.is_absolute() else BASE_DIR / path

    app.config.update(
        CONFIG_PATH=str(cfg_file),
        DB_PATH=str(abspath(cfg['paths']['database'])),
        UPLOAD_DIR=str(abspath(cfg['paths']['uploads'])),
        BACKUP_DIR=str(abspath(cfg['paths']['backups'])),
        WEBROOT=str(abspath(cfg['paths']['webroot'])),
        SECRET_KEY_FILE=str(abspath(cfg['paths']['secret_key_file'])),
        HOST=os.environ.get('FTS_HOST', cfg['server']['host']),
        PORT=int(os.environ.get('FTS_PORT', cfg['server']['port'])),
        DEBUG=bool(cfg['server']['debug']),
        MAX_CONTENT_LENGTH=int(cfg.get('upload', {}).get('max_mb', 200)) * 1024 * 1024,
    )
    for d in ('DB_PATH', 'UPLOAD_DIR', 'BACKUP_DIR'):
        Path(app.config[d]).parent.mkdir(parents=True, exist_ok=True) if d == 'DB_PATH' \
            else Path(app.config[d]).mkdir(parents=True, exist_ok=True)

    from server.blueprint.admin_bp import bp as admin_bp
    from server.blueprint.auth_bp import bp as auth_bp
    from server.blueprint.data_bp import bp as data_bp
    from server.blueprint.family_bp import bp as family_bp
    from server.blueprint.io_bp import bp as io_bp
    from server.blueprint.pedigree_bp import bp as pedigree_bp
    from server.blueprint.print_bp import bp as print_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(family_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(pedigree_bp)
    app.register_blueprint(io_bp)
    app.register_blueprint(print_bp)
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db(BASE_DIR / 'server' / 'db' / 'schema.sql').close()
        settings.ensure_defaults()
        _ensure_admin()
        from server.service.backup import start_scheduler
        start_scheduler(app)

    @app.before_request
    def _before():
        g.current_user = None
        token = request.cookies.get(auth.ACCESS_COOKIE)
        if token:
            g.current_user = auth.user_from_token(token)
        _rate_limit()
        _csrf_check()
        _enforce_password_change()

    @app.after_request
    def _after(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Referrer-Policy'] = 'same-origin'
        resp.headers['Content-Security-Policy'] = _CSP
        if request.path.startswith('/api/') or resp.mimetype == 'text/html':
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        elif request.path.startswith('/assets/'):
            # 构建产物文件名带内容哈希，可长期缓存
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        if settings.get_bool('security.force_https', False):
            resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return resp

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify({'code': err.code, 'msg': err.msg, 'data': None}), err.http_status

    @app.errorhandler(sqlite3.IntegrityError)
    def _integrity(err):
        """约束冲突属于「入参不合法」，返回 400 而不是 500"""
        text = str(err)
        if 'UNIQUE' in text:
            msg = '数据重复，已存在相同记录'
        elif 'FOREIGN KEY' in text:
            msg = '关联对象不存在或已被删除'
        elif 'CHECK' in text:
            msg = '字段取值不合法'
        else:
            msg = '数据校验失败'
        app.logger.warning('integrity error: %s', text)
        return jsonify({'code': 400, 'msg': msg, 'data': None}), 400

    @app.errorhandler(404)
    def _404(err):
        if request.path.startswith('/api/'):
            return jsonify({'code': 404, 'msg': '接口不存在', 'data': None}), 404
        return _spa()

    @app.errorhandler(Exception)
    def _500(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return err
        if app.config['DEBUG']:
            raise err
        app.logger.exception('unhandled error')
        return jsonify({'code': 500, 'msg': '服务器内部错误', 'data': None}), 500

    @app.get('/api/health')
    def health():
        return jsonify({'code': 0, 'msg': 'ok', 'data': {'time': now_str()}})

    @app.get('/')
    def index():
        return _spa()

    @app.get('/assets/<path:filename>')
    def assets(filename):
        return send_from_directory(Path(app.config['WEBROOT']) / 'assets', filename)

    @app.get('/<path:path>')
    def spa(path):
        # 兜底路由不能吞掉未匹配的 /api/*，否则客户端会把 HTML 当 JSON 解析
        if path.startswith('api/') or path == 'api':
            return jsonify({'code': 404, 'msg': '接口不存在', 'data': None}), 404
        return _spa()

    return app


_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")


def _spa():
    root = Path(current_app.config['WEBROOT'])
    idx = root / 'index.html'
    if not idx.exists():
        return jsonify({'code': 0, 'msg': '前端尚未构建，请执行 web 目录下 npm run build',
                        'data': None}), 200
    return send_file(idx)


def _rate_limit():
    """仅对 /api/ 限流；IP 取受信代理后的真实来源，桶定期清扫"""
    global _rate_swept_at
    path = request.path
    if not path.startswith('/api/'):
        return
    from server.service.netutil import client_ip
    ip = client_ip()
    now = time.time()
    is_login = path.startswith('/api/auth/login')
    if is_login:
        limit, window = max(settings.get_int('security.login_limit_per_minute', 20), 1), 60
    else:
        limit, window = max(settings.get_int('security.rate_limit_per_minute', 120), 1), 60
    key = ip + ('|login' if is_login else '|api')
    with _rate_lock:
        if now - _rate_swept_at > RATE_SWEEP_SECONDS:
            _rate_swept_at = now
            for k in [k for k, b in _rate_bucket.items()
                      if not b or now - b[-1] > RATE_IDLE_SECONDS]:
                _rate_bucket.pop(k, None)
        bucket = _rate_bucket[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ApiError('请求过于频繁，请稍后再试', code=429)
        bucket.append(now)


def _csrf_check():
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    origin = request.headers.get('Origin')
    if not origin:
        return
    host = request.host
    allowed = [o.strip() for o in settings.get_str('security.allowed_origins', '').split(',') if o.strip()]
    if origin in (f'http://{host}', f'https://{host}') or origin in allowed:
        return
    raise ApiError('跨站请求被拒绝', code=403)


def _enforce_password_change():
    """强制改密：后端拦截，而不是只在前端提示"""
    user = getattr(g, 'current_user', None)
    if not user or not user['must_change_pwd']:
        return
    if request.path in MUST_CHANGE_ALLOW or not request.path.startswith('/api/'):
        return
    raise ApiError('请先修改初始密码', code=PWD_CHANGE_REQUIRED, http_status=403)


def _ensure_admin():
    """首次启动创建超管：口令取 FTS_ADMIN_PASSWORD，未设置则随机生成并仅打印一次"""
    row = query_one('SELECT COUNT(*) c FROM users')
    if row['c'] > 0:
        return
    password = os.environ.get('FTS_ADMIN_PASSWORD') or secrets.token_urlsafe(12)
    execute(
        'INSERT INTO users (username, password_hash, real_name, status, is_superuser,'
        ' must_change_pwd, token_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
        ('admin', generate_password_hash(password, method='scrypt'),
         '超级管理员', 1, 1, 1, 1, now_str(), now_str()))
    banner = (
        '\n' + '=' * 62 + '\n'
        '已创建超级管理员账号 admin\n'
        f'  初始密码：{password}\n'
        '  该密码仅显示一次，首次登录后必须修改。\n'
        '  如需指定初始密码，请在首次启动前设置环境变量 FTS_ADMIN_PASSWORD。\n'
        + '=' * 62
    )
    print(banner)
    logging.getLogger(__name__).warning('已创建初始超级管理员，初始口令已打印至标准输出')


app = create_app()


if __name__ == '__main__':
    app.run(host=app.config['HOST'], port=app.config['PORT'], debug=app.config['DEBUG'])
