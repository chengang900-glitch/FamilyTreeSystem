"""入参校验与分页：非法参数统一转 400，避免 ValueError/类型错误落到 500"""
from flask import request

from server.common import ApiError
from server.service import settings

MAX_PAGE_SIZE = 500


def to_int(value, field, default=None, minimum=None, maximum=None, required=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ApiError(f'缺少参数：{field}')
        return default
    if isinstance(value, bool):
        value = int(value)
    try:
        num = int(str(value).strip())
    except (TypeError, ValueError):
        raise ApiError(f'参数 {field} 需为整数')
    if minimum is not None and num < minimum:
        raise ApiError(f'参数 {field} 不能小于 {minimum}')
    if maximum is not None and num > maximum:
        raise ApiError(f'参数 {field} 不能大于 {maximum}')
    return num


def to_optional_id(value, field):
    """空串 / 0 / null 统一转 None，避免 TEXT '' 混入整型外键列"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    num = to_int(value, field)
    if num is None or num <= 0:
        return None
    return num


def to_id_list(value, field):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ApiError(f'参数 {field} 需为数组')
    return [to_int(v, field, minimum=1) for v in value]


def page_args(default_size=None):
    """分页参数：非数字 → 400；超过上限按上限截断（保持前端 size=500 的既有调用可用）"""
    page = to_int(request.args.get('page'), 'page', 1, minimum=1)
    size = to_int(request.args.get('size'), 'size',
                  default_size or settings.get_int('site.page_size', 50), minimum=1)
    return page, min(size, MAX_PAGE_SIZE)


def query_int(name, **kwargs):
    """读取 query string 中的可选整数；空值返回 None"""
    return to_int(request.args.get(name), name, **kwargs)
