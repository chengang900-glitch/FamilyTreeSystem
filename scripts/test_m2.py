"""M2 自测：成员、婚姻、亲子、分支（含批量归人）与家谱成员管理"""
import sys

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('m2')
from server.app import app  # noqa: E402

assert_isolated(app)
relax_bootstrap_admin(app)

PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  {extra}' if extra else ''))


admin = app.test_client()
admin.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
admin.put('/api/admin/settings', json={'security.login_limit_per_minute': 10000,
                                       'security.rate_limit_per_minute': 10000})

r = admin.post('/api/admin/families', json={'name': '刘氏家谱', 'surname': '刘'})
fid = r.get_json()['data']['id']

print('== 成员 ==')
people = []
for i, (gen, name, ptype) in enumerate([
    (1, '刘伟', 1), (1, '韩颖', 3), (2, '刘世昌', 1),
    (2, '刘世荣', 1), (3, '刘子轩', 1), (3, '刘子涵', 2),
]):
    r = admin.post(f'/api/families/{fid}/persons',
                   json={'generation': gen, 'name': name, 'type': ptype})
    people.append(r.get_json()['data']['id'])
check('批量创建成员', len(people) == 6, str(people))

check('缺少姓名被拒', admin.post(f'/api/families/{fid}/persons',
                              json={'generation': 1}).status_code == 400)
check('世代非正整数被拒', admin.post(f'/api/families/{fid}/persons',
                                 json={'generation': 0, 'name': '测试'}).status_code == 400)

lst = admin.get(f'/api/families/{fid}/persons').get_json()['data']
check('成员列表分页', lst['total'] == 6 and len(lst['items']) == 6)
check('按世代筛选', admin.get(f'/api/families/{fid}/persons?generation=2')
      .get_json()['data']['total'] == 2)
check('按姓名搜索', admin.get(f'/api/families/{fid}/persons?keyword=子')
      .get_json()['data']['total'] == 2)

check('更新成员', admin.put(f'/api/families/{fid}/persons/{people[0]}',
                         json={'courtesy_name': '仲文', 'birth_date': '1956-08-08'}).status_code == 200)

print('== 分支 ==')
r = admin.post(f'/api/families/{fid}/branches',
               json={'name': '长房', 'hall_name': '敦本堂', 'generation_chars': '木火土金水'})
bid = r.get_json()['data']['id']
check('创建分支', r.status_code == 200)
r = admin.post(f'/api/families/{fid}/branches/{bid}/members',
               json={'add_ids': people[:3]})
check('批量归入分支', r.status_code == 200)
bl = admin.get(f'/api/families/{fid}/branches').get_json()['data']
check('分支人数统计', bl[0]['person_count'] == 3, str(bl[0]['person_count']))
admin.post(f'/api/families/{fid}/branches/{bid}/members', json={'remove_ids': [people[2]]})
bl = admin.get(f'/api/families/{fid}/branches').get_json()['data']
check('移出分支', bl[0]['person_count'] == 2)

print('== 婚姻 ==')
r = admin.post(f'/api/families/{fid}/marriages',
               json={'spouse1_id': people[0], 'spouse2_id': people[1], 'marriage_order': 1,
                     'marriage_date': '1980-01-01'})
check('登记婚姻', r.status_code == 200)
check('重复配偶被拒', admin.post(f'/api/families/{fid}/marriages',
                             json={'spouse1_id': people[0], 'spouse2_id': people[0]}).status_code == 400)
ml = admin.get(f'/api/families/{fid}/marriages').get_json()['data']
check('婚姻列表含配偶姓名', ml[0]['spouse1_name'] == '刘伟' and ml[0]['spouse2_name'] == '韩颖')

print('== 亲子 ==')
r = admin.post(f'/api/families/{fid}/parentchild',
               json={'parent_id': people[0], 'child_ids': [people[2], people[3]], 'type': 1})
check('一次登记多名子女', r.get_json()['data']['count'] == 2)
admin.post(f'/api/families/{fid}/parentchild',
           json={'parent_id': people[1], 'child_ids': [people[2]]})
pc = admin.get(f'/api/families/{fid}/parentchild').get_json()['data']
check('亲子关系列表', len(pc) == 3)
check('删除有亲子关系的成员被拒',
      admin.delete(f'/api/families/{fid}/persons/{people[0]}').status_code == 400)

print('== 越权与隔离 ==')
r = admin.post('/api/admin/users', json={'username': 'm2_viewer', 'password': 'test1234', 'must_change_pwd': False})
vid = r.get_json()['data']['id']
viewer = app.test_client()
viewer.post('/api/auth/login', json={'username': 'm2_viewer', 'password': 'test1234'})
admin.post(f'/api/admin/families/{fid}/members', json={'user_id': vid, 'role': 'member'})
check('普通用户可查看成员', viewer.get(f'/api/families/{fid}/persons').status_code == 200)
check('普通用户不可新增成员', viewer.post(f'/api/families/{fid}/persons',
                                   json={'generation': 1, 'name': 'X'}).status_code == 403)
other = app.test_client()
other.post('/api/auth/login', json={'username': 'm2_viewer', 'password': 'test1234'})
check('未加入家谱不可查看', other.get('/api/families/999/persons').status_code == 403)

r = admin.post('/api/admin/families', json={'name': '另一家谱'})
fid2 = r.get_json()['data']['id']
check('跨谱成员不可见', admin.get(f'/api/families/{fid2}/persons').get_json()['data']['total'] == 0)
check('跨谱更新被拒', admin.put(f'/api/families/{fid2}/persons/{people[0]}',
                            json={'name': 'Y'}).status_code == 403)

print('== 统计 ==')
st = admin.get(f'/api/families/{fid}/stats').get_json()['data']
check('家谱统计', st['persons'] == 6 and st['marriages'] == 1 and st['parentchild'] == 3, str(st))

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
    sys.exit(1)

cleanup()
