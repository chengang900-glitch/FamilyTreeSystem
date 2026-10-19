"""M1 自测：认证、三级鉴权、越权防护、系统设置"""
import sys

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('m1')
from server.app import app  # noqa: E402

assert_isolated(app)
relax_bootstrap_admin(app)

c = app.test_client()
c.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
c.put('/api/admin/settings', json={'security.login_limit_per_minute': 10000,
                                   'security.rate_limit_per_minute': 10000})
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  {extra}' if extra else ''))


def login(u, p):
    return c.post('/api/auth/login', json={'username': u, 'password': p})


def query_role():
    rows = c.get(f'/api/admin/families/{fid}/members').get_json()['data']
    for r in rows:
        if r['id'] == uid:
            return r['role']
    return None


print('== 认证 ==')
r = login('admin', 'admin123')
check('admin 登录成功', r.status_code == 200 and r.get_json()['data']['is_superuser'])
check('未登录访问家谱列表返回 401', app.test_client().get('/api/families').status_code == 401)
check('错误密码返回 400', login('admin', 'bad').status_code == 400)

print('== 家谱与用户 ==')
r = c.post('/api/admin/families', json={'name': '张氏家谱', 'surname': '张'})
fid = r.get_json()['data']['id']
check('创建家谱', r.status_code == 200, f'fid={fid}')
check('家谱列表可见', any(f['id'] == fid for f in c.get('/api/families').get_json()['data']))

r = c.post('/api/admin/users', json={'username': 'u_member', 'password': 'test1234',
                                     'real_name': '张三', 'must_change_pwd': False})
uid = r.get_json()['data']['id']
check('创建普通用户', r.status_code == 200, f'uid={uid}')
check('弱密码被拒', c.post('/api/admin/users', json={'username': 'u2', 'password': 'abc'}).status_code == 400)

r = c.post(f'/api/admin/families/{fid}/members', json={'user_id': uid, 'role': 'member'})
check('指派家谱成员', r.status_code == 200)

print('== 权限边界 ==')
c2 = app.test_client()
r = c2.post('/api/auth/login', json={'username': 'u_member', 'password': 'test1234'})
check('普通用户登录', r.status_code == 200)
check('普通用户可见所属家谱', any(f['id'] == fid for f in c2.get('/api/families').get_json()['data']))
check('普通用户可读家谱详情', c2.get(f'/api/families/{fid}').status_code == 200)
check('普通用户不可编辑家谱（403）', c2.put(f'/api/families/{fid}', json={'surname': '李'}).status_code == 403)
check('普通用户不可访问超管接口（403）', c2.get('/api/admin/users').status_code == 403)
check('普通用户不可访问未加入家谱（403）', c2.get('/api/families/9999').status_code == 403)

print('== 角色升级 ==')
c.put(f'/api/admin/families/{fid}/members/{uid}', json={'role': 'admin'})
check('升级为家谱管理员', query_role() == 'admin')
check('管理员可编辑家谱', c2.put(f'/api/families/{fid}', json={'surname': '张'}).status_code == 200)
c.delete(f'/api/admin/families/{fid}/members/1')
check('唯一管理员不可降级', c.put(f'/api/admin/families/{fid}/members/{uid}',
                              json={'role': 'member'}).status_code == 400)
check('唯一管理员不可移除', c.delete(f'/api/admin/families/{fid}/members/{uid}').status_code == 400)

print('== 系统设置 ==')
r = c.get('/api/admin/settings')
check('读取设置', r.status_code == 200 and len(r.get_json()['data']) > 10)
r = c.put('/api/admin/settings', json={'site.name': '张家谱', 'privacy.mask_living': True,
                                       'security.password_min_length': 10})
check('保存设置', r.status_code == 200)
vals = {s['key']: s['value'] for s in c.get('/api/admin/settings').get_json()['data']}
check('设置生效', vals['site.name'] == '张家谱' and vals['privacy.mask_living'] is True
      and vals['security.password_min_length'] == 10)
c.put('/api/admin/settings', json={'site.name': '家谱管理系统', 'privacy.mask_living': False,
                                   'security.password_min_length': 8})

print('== 登录锁定 ==')
c3 = app.test_client()
codes = [c3.post('/api/auth/login', json={'username': 'u_member', 'password': 'x'}).status_code
         for _ in range(6)]
check('连续失败后锁定', 400 in codes, str(codes))
r = c3.post('/api/auth/login', json={'username': 'u_member', 'password': 'test1234'})
check('锁定期间正确密码也被拒', r.status_code == 400, r.get_json()['msg'])

print('== 审计 ==')
logs = c.get('/api/admin/logs').get_json()['data']
check('审计日志记录', any(l['action'] in ('login', 'create_family') for l in logs))

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
    sys.exit(1)

cleanup()
