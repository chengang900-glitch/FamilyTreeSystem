"""M4-M6 自测：世系树数据、导入导出、PDF/Word 付印"""
import io
import json
import sys
import zipfile

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('m4')
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
fid = admin.post('/api/admin/families', json={'name': '王氏家谱', 'surname': '王',
                                              'compiler': '王敬修'}).get_json()['data']['id']

ids = {}
for gen, name, t in [(1, '王大有', 1), (1, '李氏', 3), (2, '王二', 1), (2, '王三', 1),
                     (3, '王小四', 1), (3, '王小五', 2)]:
    ids[name] = admin.post(f'/api/families/{fid}/persons',
                           json={'generation': gen, 'name': name, 'type': t}).get_json()['data']['id']
admin.post(f'/api/families/{fid}/marriages',
           json={'spouse1_id': ids['王大有'], 'spouse2_id': ids['李氏']})
admin.post(f'/api/families/{fid}/parentchild',
           json={'parent_id': ids['王大有'], 'child_ids': [ids['王二'], ids['王三']]})
admin.post(f'/api/families/{fid}/parentchild',
           json={'parent_id': ids['王二'], 'child_ids': [ids['王小四'], ids['王小五']]})

print('== M4 世系树数据 ==')
d = admin.get(f'/api/families/{fid}/pedigree').get_json()['data']
check('节点数正确', d['total'] == 6, str(d['total']))
root_node = next(n for n in d['nodes'] if n['id'] == d['root'])
check('自动选始祖为根', root_node['name'] == '王大有', root_node['name'])
check('亲子关系装配', len(root_node['children']) == 2, str(root_node['children']))
check('配偶关系装配', len(root_node['spouses']) == 1)
check('指定根节点', admin.get(f'/api/families/{fid}/pedigree?root={ids["王二"]}')
      .get_json()['data']['root'] == ids['王二'])

print('== M5 导出 ==')
r = admin.get(f'/api/families/{fid}/export?format=json')
data = json.loads(r.data.decode('utf-8'))
check('导出 JSON', len(data['persons']) == 6 and len(data['marriages']) == 1)
check('JSON 含九大模块', all(k in data for k in
                        ['family', 'branches', 'persons', 'marriages', 'parentchild',
                         'events', 'eventpersons', 'resources', 'resource_relations']))

r = admin.get(f'/api/families/{fid}/export?format=csv')
z = zipfile.ZipFile(io.BytesIO(r.data))
check('导出 CSV 压缩包', 'persons.csv' in z.namelist() and 'marriages.csv' in z.namelist())

r = admin.get(f'/api/families/{fid}/export?format=gedcom')
z = zipfile.ZipFile(io.BytesIO(r.data))
ged = z.read([n for n in z.namelist() if n.endswith('.ged')][0]).decode('utf-8')
check('导出 GEDCOM', 'INDI' in ged and 'FAM' in ged and '王大有' in ged)

r = admin.get(f'/api/families/{fid}/export?format=json&modules=persons')
check('按模块导出', 'persons' in json.loads(r.data.decode('utf-8')))

print('== M5 导入 ==')
fid2 = admin.post('/api/admin/families', json={'name': '导入目标'}).get_json()['data']['id']
payload = io.BytesIO(json.dumps(data, ensure_ascii=False).encode('utf-8'))
r = admin.post(f'/api/families/{fid2}/import',
               data={'file': (payload, 'data.json'), 'strategy': 'append'},
               content_type='multipart/form-data')
check('导入 JSON', r.status_code == 200, r.get_json().get('msg', ''))
st = r.get_json()['data']
check('导入数据一致', st['person'] == 6 and st['marriage'] == 1 and st['parentchild'] == 4, str(st))

ged_bytes = io.BytesIO(ged.encode('utf-8'))
fid3 = admin.post('/api/admin/families', json={'name': 'GEDCOM 导入'}).get_json()['data']['id']
r = admin.post(f'/api/families/{fid3}/import',
               data={'file': (ged_bytes, 'x.ged')}, content_type='multipart/form-data')
check('导入 GEDCOM', r.status_code == 200, r.get_json().get('msg', ''))
st = r.get_json()['data']
check('GEDCOM 成员与关系', st['person'] == 6 and st['marriage'] == 1, str(st))

r = admin.post(f'/api/families/{fid2}/import',
               data={'file': (io.BytesIO(b'{}'), 'bad.txt')}, content_type='multipart/form-data')
check('不支持的格式被拒', r.status_code == 400)

print('== M6 付印 ==')
r = admin.post(f'/api/families/{fid}/print/estimate', json={'mode': 'lineage', 'paper': 'A4'})
check('页数预估', r.get_json()['data']['pages'] >= 1, str(r.get_json()['data']))

r = admin.post(f'/api/families/{fid}/print/pdf',
               json={'mode': 'lineage', 'paper': 'A4', 'add_cover': True,
                     'include_spouse': True, 'include_children': True, 'compiler': '王敬修'})
check('导出 PDF', r.status_code == 200 and r.data[:4] == b'%PDF', str(r.data[:8]))
check('PDF 体积合理', len(r.data) > 1000, f'{len(r.data)} bytes')

r = admin.post(f'/api/families/{fid}/print/docx', json={'mode': 'lineage', 'paper': 'A5'})
check('导出 Word', r.status_code == 200 and r.data[:2] == b'PK', str(r.data[:4]))

r = admin.post(f'/api/families/{fid}/print/pdf',
               json={'mode': 'person', 'root_id': ids['王二'], 'paper': '16K', 'add_cover': False})
check('个人模式 PDF', r.status_code == 200 and r.data[:4] == b'%PDF')

print('== 权限 ==')
admin.post('/api/admin/users', json={'username': 'm6_view', 'password': 'test1234', 'must_change_pwd': False})
uid = admin.get('/api/admin/users?keyword=m6_view').get_json()['data'][0]['id']
admin.post(f'/api/admin/families/{fid}/members', json={'user_id': uid, 'role': 'member'})
v = app.test_client()
v.post('/api/auth/login', json={'username': 'm6_view', 'password': 'test1234'})
check('普通用户可导出 PDF', v.post(f'/api/families/{fid}/print/pdf', json={}).status_code == 200)
check('普通用户不可导入', v.post(f'/api/families/{fid}/import',
                           data={'file': (io.BytesIO(b'{}'), 'a.json')},
                           content_type='multipart/form-data').status_code == 403)

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
    sys.exit(1)

cleanup()
