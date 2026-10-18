"""在世者信息脱敏（对应设置项 privacy.mask_living）

默认关闭。开启后，家谱普通用户（非家谱管理员、非超管）读取成员数据时，
在世成员的生日、籍贯、安葬地、生平与备注字段返回空，并带 masked=True 标记。
"""
from flask import g

from server.db.conn import query
from server.service import settings
from server.service.permission import current_user

MASK_FIELDS = ('birth_date', 'birth_place', 'bury_address', 'record', 'notes')


def can_see_private() -> bool:
    user = current_user()
    if user is None:
        return False
    return bool(user['is_superuser']) or getattr(g, 'family_role', None) == 'admin'


def should_mask() -> bool:
    return settings.get_bool('privacy.mask_living', False) and not can_see_private()


def mask_person(row):
    if not should_mask():
        return dict(row)
    item = dict(row)
    if not item.get('death_date'):
        for key in MASK_FIELDS:
            if key in item:
                item[key] = None
        item['masked'] = True
    return item


def visible_person_ids(family_id):
    """脱敏开启时，返回当前用户不可见详情的在世成员 ID 集合（供世系树使用）"""
    if not should_mask():
        return set()
    rows = query('SELECT id FROM person WHERE family_id=? AND (death_date IS NULL'
                 " OR TRIM(death_date)='')", (family_id,))
    return {r['id'] for r in rows}
