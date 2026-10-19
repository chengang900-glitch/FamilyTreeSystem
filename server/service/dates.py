"""保留原始日期，同时提供可统计的 ISO 值与精度；不推算未知月份或农历。"""
import re
from datetime import date

from server.common import ApiError

DATE_FIELDS = {'person': ('birth_date', 'death_date'),
               'marriage': ('marriage_date', 'divorce_date'), 'event': ('time',)}


def date_info(value, strict=True):
    if value is None or value == '':
        return None, None
    if not isinstance(value, str):
        if strict:
            raise ApiError('日期必须为文本或空值')
        return None, 'text'
    text = value.strip()
    if not text:
        return None, None
    if re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', text):
        pieces = [int(p) for p in text.split('-')]
        try:
            date(pieces[0], pieces[1] if len(pieces) > 1 else 1, pieces[2] if len(pieces) > 2 else 1)
        except ValueError:
            if strict:
                raise ApiError('公历日期不合法，请检查年月日')
            return None, 'text'
        return text, {1: 'year', 2: 'month', 3: 'day'}[len(pieces)]
    return None, 'text'


def values(data, fields, strict=True, current=None):
    out = {}
    for field in fields:
        if field not in data:
            continue
        unchanged = current is not None and current[field] == data[field]
        iso, precision = date_info(data[field], strict and not unchanged)
        out.update({field: data[field], field + '_iso': iso, field + '_precision': precision})
    return out


def sync_family(family_id):
    """导入记录按原始值重算，绝不信任文件提供的统计字段。"""
    from server.db.conn import execute, query
    for table, fields in DATE_FIELDS.items():
        for row in query(f'SELECT * FROM {table} WHERE family_id=?', (family_id,)):
            fields_to_set = values(dict(row), fields, strict=False)
            changes = {k: v for k, v in fields_to_set.items() if row[k] != v}
            if changes:
                execute(f'UPDATE {table} SET ' + ','.join(f'{k}=?' for k in changes) + ' WHERE id=?',
                        list(changes.values()) + [row['id']])
