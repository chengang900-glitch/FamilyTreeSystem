"""统一响应与异常定义"""
from flask import jsonify


class ApiError(Exception):
    def __init__(self, msg, code=400, http_status=None):
        super().__init__(msg)
        self.msg = msg
        self.code = code
        known = (400, 401, 403, 404, 409, 429)
        self.http_status = http_status or (code if code in known else 400)


def ok(data=None, msg='ok'):
    return jsonify({'code': 0, 'msg': msg, 'data': data if data is not None else {}})


def now_str():
    """UTC+8 当前时间字符串，与原型 sqlite datetime('now','+8 hours') 保持一致"""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
