"""结构迁移：为既有数据库补齐外键约束，并清理迁移前就已存在的脏数据

背景：早期版本 schema 未声明任何外键（`PRAGMA foreign_keys=ON` 形同虚设），
导致删除人物留下孤儿 `eventperson`、导入可写入悬空 `spouse2_id` 等问题。
新建库由 schema.sql 直接带外键；旧库在启动时按 SQLite 官方推荐的
「新建表 → 拷贝 → 删旧表 → 改名」流程重建，整个过程在一个事务内完成，
任何异常都会整体回滚，不会留下半迁移状态。

调用方：`server/db/conn.init_db()`。失败不会阻断启动，但会记录 error 日志。
"""
import logging
import re

logger = logging.getLogger(__name__)

# 需要外键的表（重建顺序按依赖关系排列，外键检查本身在事务内关闭）
FK_TABLES = [
    'family_members', 'branch', 'person', 'marriage',
    'parentchild', 'event', 'eventperson', 'resource', 'resource_relation',
]

_TABLE_RE = re.compile(
    r'CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\(.*?\n\);', re.S)
_INDEX_RE = re.compile(
    r'CREATE INDEX IF NOT EXISTS\s+(\w+)\s+ON\s+(\w+)\s*\(([^)]*)\);')

# 迁移前清理：唯一键去重（否则拷贝进带 UNIQUE 的新表会失败）
_DEDUPE = [
    'DELETE FROM eventperson WHERE id NOT IN'
    ' (SELECT MIN(id) FROM eventperson GROUP BY event_id, person_id)',
    'DELETE FROM family_members WHERE id NOT IN'
    ' (SELECT MIN(id) FROM family_members GROUP BY family_id, user_id)',
    'DELETE FROM resource_relation WHERE id NOT IN'
    ' (SELECT MIN(id) FROM resource_relation GROUP BY resource_id, entity_type, entity_id)',
    "UPDATE resource SET fid = fid || '-' || id WHERE id NOT IN"
    ' (SELECT MIN(id) FROM resource GROUP BY fid)',
]

# 清理悬空引用（外键一旦建立，这些行会直接导致拷贝失败）
_ORPHANS = [
    'DELETE FROM person WHERE family_id NOT IN (SELECT id FROM family)',
    'DELETE FROM branch WHERE family_id NOT IN (SELECT id FROM family)',
    'DELETE FROM marriage WHERE family_id NOT IN (SELECT id FROM family)'
    ' OR spouse1_id NOT IN (SELECT id FROM person)'
    ' OR spouse2_id NOT IN (SELECT id FROM person)',
    'DELETE FROM parentchild WHERE family_id NOT IN (SELECT id FROM family)'
    ' OR parent_id NOT IN (SELECT id FROM person)'
    ' OR child_id NOT IN (SELECT id FROM person) OR parent_id = child_id',
    'DELETE FROM event WHERE family_id NOT IN (SELECT id FROM family)',
    'DELETE FROM eventperson WHERE family_id NOT IN (SELECT id FROM family)'
    ' OR event_id NOT IN (SELECT id FROM event)'
    ' OR person_id NOT IN (SELECT id FROM person)',
    'DELETE FROM resource WHERE family_id NOT IN (SELECT id FROM family)',
    'DELETE FROM resource_relation WHERE family_id NOT IN (SELECT id FROM family)'
    ' OR resource_id NOT IN (SELECT id FROM resource)',
    'DELETE FROM resource_relation WHERE'
    " (entity_type='person' AND entity_id NOT IN (SELECT id FROM person))"
    " OR (entity_type='branch' AND entity_id NOT IN (SELECT id FROM branch))"
    " OR (entity_type='event' AND entity_id NOT IN (SELECT id FROM event))"
    " OR (entity_type='marriage' AND entity_id NOT IN (SELECT id FROM marriage))"
    " OR (entity_type='parentchild' AND entity_id NOT IN (SELECT id FROM parentchild))",
    'DELETE FROM family_members WHERE family_id NOT IN (SELECT id FROM family)'
    ' OR user_id NOT IN (SELECT id FROM users)',
    # 可选归属：失效则置空（不删数据）
    'UPDATE person SET branch_id=NULL WHERE branch_id IS NOT NULL'
    " AND (CAST(branch_id AS TEXT)='' OR branch_id NOT IN (SELECT id FROM branch))",
    'UPDATE event SET branch_id=NULL WHERE branch_id IS NOT NULL'
    " AND (CAST(branch_id AS TEXT)='' OR branch_id NOT IN (SELECT id FROM branch))",
    'UPDATE branch SET parent_id=NULL WHERE parent_id IS NOT NULL'
    " AND (CAST(parent_id AS TEXT)='' OR parent_id NOT IN (SELECT id FROM branch)"
    ' OR parent_id = id)',
]

# 满足 NOT NULL / CHECK 约束
_CONSTRAINTS = [
    "UPDATE person SET name='未命名' WHERE name IS NULL OR TRIM(name)=''",
    'UPDATE person SET generation=1 WHERE generation IS NULL'
    ' OR CAST(generation AS INTEGER) < 1',
    'UPDATE person SET type=1 WHERE type IS NULL'
    ' OR CAST(type AS INTEGER) NOT BETWEEN 1 AND 8',
    'UPDATE person SET is_private=0 WHERE is_private IS NULL',
    'UPDATE marriage SET marriage_order=1 WHERE marriage_order IS NULL'
    ' OR CAST(marriage_order AS INTEGER) < 1',
    'UPDATE parentchild SET type=1 WHERE type IS NULL'
    ' OR CAST(type AS INTEGER) NOT BETWEEN 1 AND 7',
    "UPDATE event SET name='未命名事件' WHERE name IS NULL OR TRIM(name)=''",
    "UPDATE event SET time='' WHERE time IS NULL",
    'UPDATE event SET type=1 WHERE type IS NULL'
    ' OR CAST(type AS INTEGER) NOT BETWEEN 1 AND 2',
    'UPDATE resource SET type=1 WHERE type IS NULL'
    ' OR CAST(type AS INTEGER) NOT BETWEEN 1 AND 7',
    "UPDATE resource SET name='未命名' WHERE name IS NULL OR TRIM(name)=''",
    "UPDATE branch SET name='未命名分支' WHERE name IS NULL OR TRIM(name)=''",
]


def _schema_parts(schema_path):
    text = open(schema_path, 'r', encoding='utf-8').read()
    tables = {m.group(1): m.group(0) for m in _TABLE_RE.finditer(text)}
    indexes = {}
    for m in _INDEX_RE.finditer(text):
        indexes.setdefault(m.group(2), []).append(m.group(0))
    return tables, indexes


def _needs_migration(con) -> bool:
    """以 person 表是否已声明外键作为迁移标记"""
    try:
        return not con.execute('PRAGMA foreign_key_list(person)').fetchall()
    except Exception:
        return False


def _columns(con, table) -> list:
    return [r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()]


def _apply(con, statements, label):
    for sql in statements:
        try:
            cur = con.execute(sql)
            if cur.rowcount and cur.rowcount > 0:
                logger.info('[migrate] %s: %s 行受影响 → %s', label, cur.rowcount, sql[:70])
        except Exception:
            logger.warning('[migrate] %s 语句跳过：%s', label, sql[:90], exc_info=True)


def _rebuild(con, table, ddl, index_sqls):
    tmp = f'{table}__new'
    con.execute(f'DROP TABLE IF EXISTS {tmp}')
    con.execute(ddl.replace(f'CREATE TABLE IF NOT EXISTS {table}',
                            f'CREATE TABLE {tmp}', 1))
    old_cols = _columns(con, table)
    new_cols = _columns(con, tmp)
    cols = [c for c in new_cols if c in old_cols]
    collist = ', '.join(f'"{c}"' for c in cols)
    con.execute(f'INSERT INTO {tmp} ({collist}) SELECT {collist} FROM {table}')
    con.execute(f'DROP TABLE {table}')
    con.execute(f'ALTER TABLE {tmp} RENAME TO {table}')
    for sql in index_sqls:
        con.execute(sql)


def ensure_constraints(con, schema_path):
    """幂等：旧库补外键，新库直接返回"""
    if not _needs_migration(con):
        return True
    tables, indexes = _schema_parts(schema_path)
    missing = [t for t in FK_TABLES if t not in tables]
    if missing:
        logger.error('[migrate] schema 缺少表定义，跳过迁移：%s', missing)
        return False

    legacy = con.execute('PRAGMA legacy_alter_table').fetchone()[0]
    fk = con.execute('PRAGMA foreign_keys').fetchone()[0]
    try:
        con.execute('PRAGMA foreign_keys=OFF')
        con.execute('PRAGMA legacy_alter_table=ON')
        con.execute('BEGIN IMMEDIATE')
        _apply(con, _DEDUPE, 'dedupe')
        _apply(con, _ORPHANS, 'orphan')
        _apply(con, _CONSTRAINTS, 'constraint')
        for table in FK_TABLES:
            _rebuild(con, table, tables[table], indexes.get(table, []))
        bad = con.execute('PRAGMA foreign_key_check').fetchall()
        if bad:
            raise RuntimeError(f'外键校验未通过，回滚迁移：{bad[:3]}')
        con.execute('COMMIT')
        logger.info('[migrate] 外键约束已补齐（%d 张表）', len(FK_TABLES))
        return True
    except Exception:
        try:
            con.execute('ROLLBACK')
        except Exception:
            pass
        logger.exception('[migrate] 结构迁移失败，已回滚；本次仍以无外键模式运行')
        return False
    finally:
        con.execute(f'PRAGMA foreign_keys={1 if fk else 0}')
        con.execute(f'PRAGMA legacy_alter_table={1 if legacy else 0}')


def ensure_profile_fields(con, backup_dir):
    """增量补联系方式与日期统计列；旧库变更前快照，保留历史文本和重复次序。"""
    import sqlite3
    from datetime import datetime
    from pathlib import Path
    from server.service.dates import DATE_FIELDS, date_info

    additions = {'person': ['address', 'phone', 'company', 'position'], 'marriage': [], 'event': []}
    for table, fields in DATE_FIELDS.items():
        additions[table] += [f + suffix for f in fields for suffix in ('_iso', '_precision')]
    missing = {table: [c for c in columns if c not in _columns(con, table)] for table, columns in additions.items()}
    if any(missing.values()):
        directory = Path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / ('before_profile_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
        with sqlite3.connect(snapshot) as target:
            con.backup(target)
        logger.info('[migrate] 扩展字段前数据库快照：%s', snapshot.name)
    con.execute('BEGIN IMMEDIATE')
    try:
        for table, columns in missing.items():
            # 多 worker 可能在等锁期间已由另一进程补列；持锁后再次检查。
            columns = [column for column in columns if column not in _columns(con, table)]
            for column in columns:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
            for field in DATE_FIELDS[table]:
                if field + '_iso' in columns:
                    for row in con.execute(f'SELECT id,{field} FROM {table}').fetchall():
                        iso, precision = date_info(row[1], strict=False)
                        con.execute(f'UPDATE {table} SET {field}_iso=?,{field}_precision=? WHERE id=?',
                                    (iso, precision, row[0]))
        # 触发器保护并发与导入路径。旧重复记录不删除、不自动改号，仍可读取并手工纠正。
        for action in ('INSERT', 'UPDATE'):
            event = action if action == 'INSERT' else 'UPDATE OF family_id,spouse1_id,marriage_order'
            con.execute(f'''CREATE TRIGGER IF NOT EXISTS marriage_order_{action.lower()}
                BEFORE {event} ON marriage
                WHEN EXISTS (SELECT 1 FROM marriage m WHERE m.family_id=NEW.family_id
                    AND m.spouse1_id=NEW.spouse1_id AND m.marriage_order=NEW.marriage_order
                    AND m.id<>NEW.id)
                BEGIN SELECT RAISE(ABORT, '成员 A 的本段次序已使用，请选择其他次序'); END''')
        for table, fields in DATE_FIELDS.items():
            for field in fields:
                con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_{field}_iso ON {table}(family_id,{field}_iso)')
        con.execute('COMMIT')
    except BaseException:
        con.execute('ROLLBACK')
        raise


def ensure_child_order(con, backup_dir):
    """排行按每位父/母名下的全部子女统一编号；旧记录保持空值，不根据生日编造。"""
    import sqlite3
    from datetime import datetime
    from pathlib import Path
    if 'child_order' not in _columns(con, 'parentchild'):
        directory = Path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / ('before_child_order_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
        with sqlite3.connect(snapshot) as target:
            con.backup(target)
        logger.info('[migrate] 亲子排行补列前快照：%s', snapshot.name)
    con.execute('BEGIN IMMEDIATE')
    try:
        if 'child_order' not in _columns(con, 'parentchild'):
            con.execute('ALTER TABLE parentchild ADD COLUMN child_order INTEGER CHECK (child_order IS NULL OR child_order > 0)')
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_parentchild_order ON parentchild(family_id,parent_id,child_order) WHERE child_order IS NOT NULL')
        con.execute('COMMIT')
    except BaseException:
        con.execute('ROLLBACK')
        raise


def ensure_person_types(con, backup_dir):
    """将旧人物表类型范围扩到8；保留原DDL、数据、索引、触发器及自增序列。"""
    import os
    import sqlite3
    from datetime import datetime
    from pathlib import Path
    old_check = re.compile(r'CHECK\s*\(\s*type\s+BETWEEN\s+1\s+AND\s+6\s*\)', re.I)
    def ddl():
        return con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='person'").fetchone()[0]
    if not old_check.search(ddl()):
        return
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / ('before_person_types_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
    with sqlite3.connect(snapshot) as target:
        con.backup(target)
    os.chmod(snapshot, 0o600)
    fk = con.execute('PRAGMA foreign_keys').fetchone()[0]
    legacy = con.execute('PRAGMA legacy_alter_table').fetchone()[0]
    try:
        con.execute('PRAGMA foreign_keys=OFF')
        con.execute('PRAGMA legacy_alter_table=ON')
        con.execute('BEGIN IMMEDIATE')
        original = ddl()
        # 等待写锁期间另一worker可能已经迁移；持锁后再次确认。
        if not old_check.search(original):
            con.execute('COMMIT')
            return
        objects = con.execute("SELECT sql FROM sqlite_master WHERE tbl_name='person'"
                              " AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        sequence = con.execute("SELECT seq FROM sqlite_sequence WHERE name='person'").fetchone()
        new = old_check.sub('CHECK (type BETWEEN 1 AND 8)', original)
        new, count = re.subn(r'^CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(?:person|"person"|`person`|\[person\])(?=\s*\()',
                             'CREATE TABLE person__types_new', new, count=1, flags=re.I)
        if count != 1:
            raise RuntimeError('无法识别人物表定义，已停止类型迁移')
        con.execute(new)
        columns = ','.join('"' + c.replace('"', '""') + '"' for c in _columns(con, 'person'))
        con.execute(f'INSERT INTO person__types_new ({columns}) SELECT {columns} FROM person')
        con.execute('DROP TABLE person')
        con.execute('ALTER TABLE person__types_new RENAME TO person')
        for row in objects:
            con.execute(row[0])
        if sequence:
            con.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='person'", (sequence[0],))
        if con.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('人物类型迁移外键校验失败，已回滚')
        con.execute('COMMIT')
        logger.info('[migrate] 人物类型已扩展到8，迁移前快照：%s', snapshot.name)
    except BaseException:
        if con.in_transaction:
            con.execute('ROLLBACK')
        raise
    finally:
        con.execute(f'PRAGMA foreign_keys={1 if fk else 0}')
        con.execute(f'PRAGMA legacy_alter_table={1 if legacy else 0}')
