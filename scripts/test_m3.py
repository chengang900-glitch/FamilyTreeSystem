"""M3 自测：事件与参与人、文献资源上传/关联/鉴权下载"""
import io
import sys

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('m3')
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
fid = admin.post('/api/admin/families', json={'name': '陈氏家谱', 'surname': '陈'}).get_json()['data']['id']
p1 = admin.post(f'/api/families/{fid}/persons', json={'generation': 1, 'name': '陈国强'}).get_json()['data']['id']
p2 = admin.post(f'/api/families/{fid}/persons', json={'generation': 2, 'name': '陈明'}).get_json()['data']['id']
bid = admin.post(f'/api/families/{fid}/branches', json={'name': '东房'}).get_json()['data']['id']

print('== 事件 ==')
r = admin.post(f'/api/families/{fid}/events',
               json={'name': '祠堂重修', 'time': '1990-03-12', 'place': '祖祠',
                     'branch_id': bid, 'type': 1})
eid = r.get_json()['data']['id']
check('创建事件', r.status_code == 200)
check('缺少时间被拒', admin.post(f'/api/families/{fid}/events',
                             json={'name': '无时间'}).status_code == 400)
r = admin.post(f'/api/families/{fid}/events',
               json={'name': 'x', 'time': '2000-01-01', 'branch_id': 9999})
check('关联不存在的分支被拒', r.status_code in (403, 404), str(r.status_code))
admin.post(f'/api/families/{fid}/events/{eid}/persons',
           json={'person_id': p1, 'role': '组织者'})
admin.post(f'/api/families/{fid}/events/{eid}/persons',
           json={'person_id': p2, 'role': '参与者'})
eps = admin.get(f'/api/families/{fid}/events/{eid}/persons').get_json()['data']
check('参与人登记', len(eps) == 2 and eps[0]['name'] == '陈国强', str([e['name'] for e in eps]))
check('重复参与人被拒', admin.post(f'/api/families/{fid}/events/{eid}/persons',
                             json={'person_id': p1}).status_code == 400)
ev = admin.get(f'/api/families/{fid}/events').get_json()['data']
check('事件列表含参与人数', ev[0]['person_count'] == 2)

print('== 资源上传 ==')
def payload(name='光绪老谱', fname='old-book.pdf', body=b'PDF-BYTES-TEST'):
    return {'file': (io.BytesIO(body), fname), 'name': name, 'type': 1}


r = admin.post(f'/api/families/{fid}/resources', data=payload(),
               content_type='multipart/form-data')
rid = r.get_json()['data']['id']
check('上传成功', r.status_code == 200, r.get_json().get('msg', ''))
check('禁止的文件类型被拒', admin.post(f'/api/families/{fid}/resources',
                                data=payload('恶意文件', 'evil.exe', b'x'),
                                content_type='multipart/form-data').status_code == 400)
rl = admin.get(f'/api/families/{fid}/resources').get_json()['data']
check('资源列表', len(rl) == 1 and rl[0]['name'] == '光绪老谱')
check('文件大小登记', rl[0]['file_size'] == 14, str(rl[0]['file_size']))

print('== 关联 ==')
admin.post(f'/api/families/{fid}/resources/{rid}/relations',
           json={'entity_type': 'person', 'entity_id': p1})
admin.post(f'/api/families/{fid}/resources/{rid}/relations',
           json={'entity_type': 'event', 'entity_id': eid})
rels = admin.get(f'/api/families/{fid}/resources/{rid}/relations').get_json()['data']
check('多实体关联', len(rels) == 2)
r = admin.post(f'/api/families/{fid}/resources/{rid}/relations',
               json={'entity_type': 'person', 'entity_id': 9999})
check('关联跨谱对象被拒', r.status_code in (400, 404), str(r.status_code))

print('== 鉴权下载 ==')
r = admin.get(f'/api/families/{fid}/files/{rid}')
check('授权用户可下载', r.status_code == 200 and b'PDF-BYTES-TEST' in r.data)

admin.post('/api/admin/users', json={'username': 'm3_viewer', 'password': 'test1234'})
uid = admin.get('/api/admin/users?keyword=m3_viewer').get_json()['data'][0]['id']
admin.post(f'/api/admin/families/{fid}/members', json={'user_id': uid, 'role': 'member'})
viewer = app.test_client()
viewer.post('/api/auth/login', json={'username': 'm3_viewer', 'password': 'test1234'})
check('本谱普通用户可下载', viewer.get(f'/api/families/{fid}/files/{rid}').status_code == 200)

outsider = app.test_client()
admin.post('/api/admin/users', json={'username': 'm3_out', 'password': 'test1234'})
uid2 = admin.get('/api/admin/users?keyword=m3_out').get_json()['data'][0]['id']
outsider.post('/api/auth/login', json={'username': 'm3_out', 'password': 'test1234'})
check('非本谱用户下载被拒', outsider.get(f'/api/families/{fid}/files/{rid}').status_code == 403)
check('普通用户不可上传', viewer.post(f'/api/families/{fid}/resources', data=payload(),
                              content_type='multipart/form-data').status_code == 403)

print('== 删除级联 ==')
check('删除资源', admin.delete(f'/api/families/{fid}/resources/{rid}').status_code == 200)
check('关联一并清理', admin.get(f'/api/families/{fid}/resources').get_json()['data'] == [])

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
    sys.exit(1)

cleanup()
