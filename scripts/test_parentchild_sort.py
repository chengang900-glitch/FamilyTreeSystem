"""亲子列表默认排序回归，只使用隔离临时库。"""
import sys

from _testenv import bootstrap, assert_isolated, cleanup, relax_bootstrap_admin

bootstrap('parentchild_sort')
from server.app import app

assert_isolated(app)
relax_bootstrap_admin(app)
results = []


def check(name, condition):
    results.append(condition)
    print(('PASS ' if condition else 'FAIL ') + name)


try:
    c = app.test_client()
    c.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
    c.put('/api/admin/settings', json={'security.rate_limit_per_minute': 10000})
    fid = c.post('/api/admin/families', json={'name': '排序验收'}).json['data']['id']
    base = f'/api/families/{fid}'

    def person(name, generation, birth='', kind=1):
        response = c.post(base + '/persons', json={
            'name': name, 'generation': generation, 'type': kind, 'birth_date': birth})
        assert response.status_code == 200, response.json
        return response.json['data']['id']

    # 故意按世代倒序建父母，且同名父母必须按身份分组。
    later = person('共同姓父母', 3)
    dad = person('共同姓父母', 1)
    mom = person('共同姓母亲', 1, kind=3)
    middle = person('共同姓父母', 2)
    unknown = person('共同姓生日不详', 4)
    text = person('共同姓农历原文', 4, '甲子年正月初一')
    newer = person('共同姓较晚出生', 4, '2005-02-03')
    older = person('共同姓较早出生', 4, '1990-06-01')
    same = person('共同姓同日出生', 4, '1990-06-01')
    year = person('共同姓仅知年份', 4, '1988')
    month = person('共同姓仅知月份', 4, '1989-12')

    def link(parent, child, order=None):
        response = c.post(base + '/parentchild', json={
            'parent_id': parent, 'child_id': child, 'child_order': order})
        assert response.status_code == 200, response.json

    # 插入顺序、排行与生日顺序故意不一致，父母记录交错。
    for parent, child, order in [
        (later, newer, None), (dad, unknown, None), (mom, newer, 1),
        (dad, newer, 1), (middle, older, None), (dad, same, None),
        (mom, older, 2), (dad, text, None), (dad, older, 2),
        (dad, month, None), (dad, year, None),
    ]:
        link(parent, child, order)

    expected = [(dad, child) for child in (year, month, older, same, newer, unknown, text)]
    expected += [(mom, older), (mom, newer), (middle, older), (later, newer)]
    rows = c.get(base + '/parentchild').json['data']
    pairs = lambda items: [(row['parent_id'], row['child_id']) for row in items]
    check('默认完整列表按世代、父母身份、子女生日排序', pairs(rows) == expected)
    parents = [row['parent_id'] for row in rows]
    check('同一父母连续且同名不同人不合并', parents == [dad] * 7 + [mom] * 2 + [middle, later])
    dad_rows = [row for row in rows if row['parent_id'] == dad]
    check('仅知年份月份按已知值排序，不忽略日期精度', pairs(dad_rows[:2]) == [(dad, year), (dad, month)])
    check('相同生日按成员ID稳定排列', pairs(dad_rows[2:4]) == [(dad, older), (dad, same)])
    check('空生日和农历原文放组末且保持稳定', pairs(dad_rows[-2:]) == [(dad, unknown), (dad, text)])
    check('生日排序不修改人工排行', next(r for r in rows if r['parent_id'] == dad and r['child_id'] == newer)['child_order'] == 1
          and next(r for r in rows if r['parent_id'] == dad and r['child_id'] == older)['child_order'] == 2)
    paged = []
    for page in range(1, 5):
        response = c.get(base + '/parentchild', query_string={'page': page, 'size': 3})
        data = response.json['data']
        check(f'第{page}页总数与分页数量正确', response.status_code == 200 and data['total'] == 11
              and len(data['items']) == (3 if page < 4 else 2))
        paged.extend(data['items'])
    check('跨页保持全局顺序且不漏不重', pairs(paged) == expected
          and len({row['id'] for row in paged}) == 11)
    filtered = c.get(base + '/parentchild', query_string={'keyword': '较早', 'size': 50}).json['data']
    check('搜索后仍按父母世代排序', pairs(filtered['items']) == [(dad, older), (mom, older), (middle, older)])
    check('列表未额外返回生日或联系方式', all(not any(key in row for key in
          ('birth_date', 'birth_date_iso', 'phone', 'address')) for row in rows))
    other = c.post('/api/admin/families', json={'name': '其他谱'}).json['data']['id']
    check('另一家谱列表仍为空', c.get(f'/api/families/{other}/parentchild').json['data'] == [])
    check('未登录仍拒绝读取', app.test_client().get(base + '/parentchild').status_code == 401)
finally:
    cleanup()

print(f'{sum(results)}/{len(results)} checks passed')
sys.exit(0 if all(results) else 1)
