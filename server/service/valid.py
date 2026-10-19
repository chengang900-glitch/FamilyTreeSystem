"""入参校验与分页：非法参数统一转 400，避免 ValueError/类型错误落到 500"""
from flask import request

from server.common import ApiError

CONTACT_FIELDS = ('address', 'phone', 'company', 'position')


def contacts(data):
    out = {}
    for key, maximum in (('address', 1000), ('phone', 50), ('company', 200), ('position', 100)):
        if key not in data:
            continue
        value = data[key]
        if value is not None and not isinstance(value, str):
            raise ApiError('住址、手机号、单位和职位须为文本')
        value = value.strip() if value else None
        if value and len(value) > maximum:
            raise ApiError(f'{key} 超过 {maximum} 字符上限')
        out[key] = value
    return out
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


def check_date_order(start, end, field='日期'):
    """仅拒绝确定颠倒的日期区间；年/月精度不补造未知日，农历文字不强比。"""
    if not start or not end:
        return
    import calendar
    from datetime import date
    from server.service.dates import date_info
    def interval(value):
        iso, precision = date_info(value, strict=False)
        if not iso:
            return None
        parts = [int(x) for x in iso.split('-')]
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        first = date(year, month, day)
        if precision == 'year':
            return first, date(year, 12, 31)
        if precision == 'month':
            return first, date(year, month, calendar.monthrange(year, month)[1])
        return first, first
    s, e = interval(start), interval(end)
    if s and e and e[1] < s[0]:
        raise ApiError(f'{field}不能早于起始日期')


def paged_request():
    """请求是否显式要求分页；未带 page/size 时保持旧的数组返回，兼容旧客户端。"""
    return request.args.get('page') is not None or request.args.get('size') is not None


def page_args(default_size=None):
    """分页参数：非数字 → 400；超过上限按上限截断（保持前端 size=500 的既有调用可用）"""
    page = to_int(request.args.get('page'), 'page', 1, minimum=1)
    size = to_int(request.args.get('size'), 'size',
                  default_size or settings.get_int('site.page_size', 50), minimum=1)
    return page, min(size, MAX_PAGE_SIZE)


def query_int(name, **kwargs):
    """读取 query string 中的可选整数；空值返回 None"""
    return to_int(request.args.get(name), name, **kwargs)
