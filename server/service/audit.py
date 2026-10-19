"""操作审计：写入、变更摘要、清理与导出"""
import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone

from server.common import now_str
from server.db.conn import execute

logger = logging.getLogger(__name__)


def log(user_id, family_id, action, target_type=None, target_id=None, detail=None):
    try:
        from server.service.netutil import client_ip
        ip = client_ip()
        # 统一审计详情为 JSON：update 是 before/after，create/delete 等归为 summary
        if detail is not None and not (isinstance(detail, str) and detail.lstrip().startswith('{')):
            detail = json.dumps({'summary': detail}, ensure_ascii=False)
        execute(
            'INSERT INTO operation_log (user_id, family_id, action, target_type, target_id, detail, ip, created_at)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (user_id, family_id, action, target_type, target_id, detail, ip, now_str()))
    except Exception:
        # 审计写入失败不应阻断业务，但必须留痕，便于排查「日志缺行」
        logger.warning('审计日志写入失败 action=%s user=%s', action, user_id, exc_info=True)


def change(old, data, fields):
    """把 update 类操作保存为结构化变更摘要 JSON（只记录实际发生变化的字段）。"""
    if not isinstance(data, dict):
        return None
    old = dict(old) if old is not None else {}
    changes = {}
    for key in fields:
        if key not in data:
            continue
        before = old.get(key)
        after = data[key]
        if str(before) != str(after):
            changes[key] = {'old': before, 'new': after}
    return json.dumps(changes, ensure_ascii=False) if changes else '{}'


def cleanup(days):
    """按保留期清理审计日志；days<=0 表示永久保留。返回删除行数。"""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)) \
        .strftime('%Y-%m-%d %H:%M:%S')
    try:
        from server.db.conn import get_db
        con = get_db()
        cur = con.execute('DELETE FROM operation_log WHERE created_at < ?', (cutoff,))
        con.commit()
        return cur.rowcount or 0
    except Exception:
        logger.warning('审计日志清理失败 days=%s', days, exc_info=True)
        return 0


def export_csv(rows):
    """operation_log 行导出为 UTF-8 BOM CSV，便于 Excel 直接打开。"""
    buf = io.StringIO()
    fields = ['id', 'created_at', 'user_id', 'username', 'family_id', 'action',
              'target_type', 'target_id', 'detail', 'ip']
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) if hasattr(row, 'get') else row[k] for k in fields})
    return buf.getvalue().encode('utf-8-sig')
