"""数据库连接、事务与初始化

事务约定：
- 连接以 autocommit 模式打开（isolation_level=None），由本模块显式控制事务；
- 单条 execute/executemany 在无事务上下文时立即提交（保持原有语义）；
- 需要「多语句原子生效」时使用 `with transaction():`，内部所有 execute 不再各自提交，
  异常时整体回滚。
"""
import sqlite3
import threading
from contextlib import contextmanager

from flask import current_app, g

_state = threading.local()

SCHEMA_SQL = None


def _depth() -> int:
    return getattr(_state, 'depth', 0)


def get_db():
    if 'db' not in g:
        con = sqlite3.connect(current_app.config['DB_PATH'], timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=15000')
        g.db = con
    return g.db


def close_db(e=None):
    con = g.pop('db', None)
    if con is not None:
        if _depth():
            con.rollback()
            _state.depth = 0
        con.close()


def query(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def query_one(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def execute(sql, args=()):
    con = get_db()
    cur = con.execute(sql, args)
    if _depth() == 0:
        con.commit()
    return cur.lastrowid


def execute_count(sql, args=()) -> int:
    """执行并返回受影响行数（导入统计用，避免 OR IGNORE 计数失真）"""
    con = get_db()
    cur = con.execute(sql, args)
    if _depth() == 0:
        con.commit()
    return cur.rowcount


def executemany(sql, seq):
    con = get_db()
    cur = con.executemany(sql, seq)
    if _depth() == 0:
        con.commit()
    return cur.rowcount


@contextmanager
def transaction():
    """事务上下文：可嵌套，仅最外层真正开启/提交"""
    con = get_db()
    if _depth() > 0:
        _state.depth += 1
        try:
            yield con
        finally:
            _state.depth -= 1
        return
    con.execute('BEGIN IMMEDIATE')
    _state.depth = 1
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        _state.depth = 0


def init_db(schema_path):
    """建表（幂等）并执行结构迁移，返回连接"""
    con = sqlite3.connect(current_app.config['DB_PATH'], timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    with open(schema_path, 'r', encoding='utf-8') as f:
        con.executescript(f.read())
    con.execute('PRAGMA journal_mode=WAL')

    from server.db.migrate import ensure_constraints
    ensure_constraints(con, schema_path)
    from server.db.migrate import ensure_profile_fields, ensure_child_order
    from pathlib import Path
    ensure_profile_fields(con, current_app.config.get('BACKUP_DIR', Path(current_app.config['DB_PATH']).parent / 'backups'))
    ensure_child_order(con, current_app.config.get('BACKUP_DIR', Path(current_app.config['DB_PATH']).parent / 'backups'))
    # 历史库可能残留绝对路径/../ 形式的 storage_path，启动时清空（不删文件）
    from server.service.filepath import sanitize_resource_paths
    sanitize_resource_paths(con)
    # 多态关联没有外键，顺手清理历史删除留下的悬空关系
    try:
        con.execute(
            "DELETE FROM resource_relation WHERE"
            " (entity_type='person' AND entity_id NOT IN (SELECT id FROM person))"
            " OR (entity_type='branch' AND entity_id NOT IN (SELECT id FROM branch))"
            " OR (entity_type='event' AND entity_id NOT IN (SELECT id FROM event))"
            " OR (entity_type='marriage' AND entity_id NOT IN (SELECT id FROM marriage))"
            " OR (entity_type='parentchild' AND entity_id NOT IN (SELECT id FROM parentchild))"
        )
        con.commit()
    except sqlite3.Error:
        con.rollback()
    return con
