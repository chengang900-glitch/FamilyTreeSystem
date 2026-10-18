"""自测环境隔离

每个自测脚本在 import server.app 之前调用 setup()，把 FTS_CONFIG 指向独立临时目录，
避免像早期版本那样直接把测试数据写进 data/app.db（生产库）。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_state = {}


def setup(tag='test'):
    root = Path(tempfile.mkdtemp(prefix=f'fts_{tag}_'))
    (root / 'data').mkdir(parents=True, exist_ok=True)
    cfg = root / 'config.yaml'
    cfg.write_text(
        'server:\n'
        '  host: 127.0.0.1\n'
        '  port: 8100\n'
        '  debug: false\n'
        '\n'
        'paths:\n'
        f'  database: {(root / "data" / "app.db").as_posix()}\n'
        f'  uploads: {(root / "data" / "uploads").as_posix()}\n'
        f'  backups: {(root / "data" / "backups").as_posix()}\n'
        f'  webroot: {(REPO / "server" / "webroot").as_posix()}\n'
        f'  secret_key_file: {(root / "data" / "secret.key").as_posix()}\n'
        '\n'
        'upload:\n'
        '  max_mb: 200\n',
        encoding='utf-8')
    os.environ['FTS_CONFIG'] = str(cfg)
    os.environ.setdefault('FTS_ADMIN_PASSWORD', 'admin123')
    # 日志也写到临时目录，避免自测记录污染生产 log/server.log
    os.environ.setdefault('FTS_LOG_DIR', str(root / 'log'))
    _state['root'] = root
    return cfg


def bootstrap(tag='test'):
    """在导入应用之前完成路径准备与 sys.path 设置"""
    here = Path(__file__).resolve().parent
    for p in (str(here), str(REPO)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return setup(tag)


def assert_isolated(app):
    db = Path(app.config['DB_PATH']).as_posix()
    if 'fts_' not in db and os.environ.get('FTS_ALLOW_PROD_DB') != '1':
        raise SystemExit(f'拒绝在非测试库上运行自测：{db}\n'
                         '（如确需如此，请设置 FTS_ALLOW_PROD_DB=1）')


def relax_bootstrap_admin(app):
    """测试用：清掉首登强制改密标记，让既有用例沿用 admin/admin123 流程

    强制改密本身由 scripts/test_fixes.py 单独覆盖。
    """
    with app.app_context():
        from server.db.conn import execute
        execute('UPDATE users SET must_change_pwd=0 WHERE username=?', ('admin',))


def cleanup():
    root = _state.pop('root', None)
    if root and root.exists():
        shutil.rmtree(root, ignore_errors=True)
