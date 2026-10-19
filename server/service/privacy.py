"""在世者信息脱敏（对应设置项 privacy.mask_living）

默认关闭。开启后，家谱普通用户（非家谱管理员、非超管）读取成员数据时，
在世成员的生日、籍贯、安葬地、生平与备注字段返回空，并带 masked=True 标记。
"""
from flask import g

from server.db.conn import query
from server.service import settings
from server.service.permission import current_user

MASK_FIELDS = ('birth_date', 'birth_date_iso', 'birth_date_precision', 'birth_place', 'bury_address',
               'record', 'notes', 'address', 'phone', 'company', 'position')


def can_see_private() -> bool:
    user = current_user()
    if user is None:
        return False
    return bool(user['is_superuser']) or getattr(g, 'family_role', None) == 'admin'


def should_mask() -> bool:
    return settings.get_bool('privacy.mask_living', False) and not can_see_private()


def _hide(item):
    for key in MASK_FIELDS:
        if key in item:
            item[key] = None
    item['masked'] = True


def mask_person(row):
    item = dict(row)
    # 单条记录级隐私：非管理员始终看不到详情；全局在世者脱敏再叠加
    if item.get('is_private') and not can_see_private():
        _hide(item)
    elif not item.get('death_date') and should_mask():
        _hide(item)
    return item


def visible_person_ids(family_id):
    """返回当前用户不可见生日的成员 ID（供世系树使用）。"""
    conditions = ['is_private=1']
    if should_mask():
        conditions.append("(death_date IS NULL OR TRIM(death_date)='')")
    rows = query(f"SELECT id FROM person WHERE family_id=? AND ({' OR '.join(conditions)})",
                 (family_id,))
    return {r['id'] for r in rows}
