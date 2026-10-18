"""操作审计"""
import logging

from server.common import now_str
from server.db.conn import execute

logger = logging.getLogger(__name__)


def log(user_id, family_id, action, target_type=None, target_id=None, detail=None):
    try:
        from server.service.netutil import client_ip
        ip = client_ip()
        execute(
            'INSERT INTO operation_log (user_id, family_id, action, target_type, target_id, detail, ip, created_at)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (user_id, family_id, action, target_type, target_id, detail, ip, now_str()))
    except Exception:
        # 审计写入失败不应阻断业务，但必须留痕，便于排查「日志缺行」
        logger.warning('审计日志写入失败 action=%s user=%s', action, user_id, exc_info=True)
