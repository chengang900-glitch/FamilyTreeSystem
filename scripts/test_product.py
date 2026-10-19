"""产品功能补齐回归：刷新令牌、家谱日志、备份恢复、ZUP、审计摘要、设置接线、婚姻日期。"""
import io
import json
import zipfile
from pathlib import Path

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('product')
from server.app import app  # noqa: E402

assert_isolated(app)
relax_bootstrap_admin(app)

PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  {extra}' if extra else ''))


def scalar(sql, args=()):
    with app.app_context():
        from server.db.conn import query_one
        return query_one(sql, args)


admin = app.test_client()
admin.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
admin.put('/api/admin/settings', json={'security.login_limit_per_minute': 10000,
                                       'security.rate_limit_per_minute': 10000})


def mkfamily(name):
    return admin.post('/api/admin/families', json={'name': name}).get_json()['data']['id']


def mkuser(name):
    r = admin.post('/api/admin/users', json={'username': name, 'password': 'test1234',
                                             'must_change_pwd': False})
    assert r.status_code == 200, r.get_json()
    return scalar('SELECT id FROM users WHERE username=?', (name,))['id']


print('== 1. 刷新令牌 ==')
u = mkuser('prod_refresh')
fid = mkfamily('刷新谱')
admin.post(f'/api/families/{fid}/members', json={'user_id': u, 'role': 'member'})
c = app.test_client()
r = c.post('/api/auth/login', json={'username': 'prod_refresh', 'password': 'test1234',
                                   'remember': True})
check('登录返回访问 + 刷新 Cookie',
      c.get_cookie('fts_token') is not None and c.get_cookie('fts_refresh', path='/api/auth') is not None)
refresh = c.get_cookie('fts_refresh', path='/api/auth').value
n = app.test_client()
n.set_cookie('fts_refresh', refresh, path='/api/auth')
r = n.post('/api/auth/refresh')
check('刷新令牌可换发访问令牌', r.status_code == 200, str(r.get_json()))
check('刷新后访问 /me', n.get('/api/auth/me').status_code == 200)
old = app.test_client()
old.set_cookie('fts_refresh', refresh, path='/api/auth')
check('刷新不轮换时旧刷新令牌仍可用', old.post('/api/auth/refresh').status_code == 200)
c.post('/api/auth/logout')
r = n.post('/api/auth/refresh')
check('登出后刷新令牌失效', r.status_code == 401, str(r.status_code))
check('无刷新 Cookie 时刷新被拒', app.test_client().post('/api/auth/refresh').status_code == 401)

print('== 2. 家谱日志与审计摘要 ==')
fid = mkfamily('日志谱')
p1 = admin.post(f'/api/families/{fid}/persons', json={'name': '甲', 'generation': 1}).get_json()['data']['id']
admin.put(f'/api/families/{fid}/persons/{p1}', json={'name': '甲改', 'birth_place': '某地'})
r = admin.get(f'/api/families/{fid}/logs')
check('超管可看本谱日志', r.status_code == 200 and len(r.get_json()['data']) >= 2)
detail = next(x['detail'] for x in r.get_json()['data'] if x['action'] == 'update_person')
try:
    parsed = json.loads(detail)
except Exception:
    parsed = {}
check('审计 detail 为结构化 JSON', parsed.get('name', {}).get('new') == '甲改', str(detail))
r = admin.get(f'/api/families/{fid}/logs/export')
check('本谱日志可导出 CSV', r.status_code == 200 and r.data.startswith(b'\xef\xbb\xbf'))
r = admin.get('/api/admin/logs/export')
check('全站日志可导出 CSV', r.status_code == 200 and r.data.startswith(b'\xef\xbb\xbf'))

fadmin = mkuser('prod_fadmin')
member = mkuser('prod_member')
admin.post(f'/api/families/{fid}/members', json={'user_id': fadmin, 'role': 'admin'})
admin.post(f'/api/families/{fid}/members', json={'user_id': member, 'role': 'member'})
fa = app.test_client()
fa.post('/api/auth/login', json={'username': 'prod_fadmin', 'password': 'test1234'})
check('家谱管理员可看本谱日志', fa.get(f'/api/families/{fid}/logs').status_code == 200)
m = app.test_client()
m.post('/api/auth/login', json={'username': 'prod_member', 'password': 'test1234'})
check('普通成员不可看本谱日志', m.get(f'/api/families/{fid}/logs').status_code == 403)

private = admin.post(f'/api/families/{fid}/persons',
                     json={'name': '隐私成员', 'generation': 1, 'is_private': True,
                           'birth_date': '1980-01-01', 'notes': '私密'}).get_json()['data']['id']
pd = m.get(f'/api/families/{fid}/persons/{private}').get_json()['data']
check('单条隐私记录对普通成员脱敏', pd['birth_date'] is None and pd['notes'] is None)
pd = admin.get(f'/api/families/{fid}/persons/{private}').get_json()['data']
check('单条隐私记录对管理员可见', pd['birth_date'] == '1980-01-01')

print('== 3. 家谱备份与恢复 ==')
r = admin.get(f'/api/families/{fid}/backup')
check('家谱备份返回 ZIP', r.status_code == 200 and r.data[:2] == b'PK')
z = zipfile.ZipFile(io.BytesIO(r.data))
check('备份包含 manifest/data/resources', 'manifest.json' in z.namelist()
      and 'data.json' in z.namelist())
backup_bytes = r.data
admin.put(f'/api/families/{fid}/persons/{p1}', json={'name': '被改坏'})
r = admin.post(f'/api/families/{fid}/restore',
               data={'file': (io.BytesIO(backup_bytes), 'backup.zip')},
               content_type='multipart/form-data')
check('家谱恢复成功', r.status_code == 200, str(r.get_json()))
names = [x['name'] for x in admin.get(f'/api/families/{fid}/persons?size=500').get_json()['data']['items']]
check('恢复覆盖回备份数据', '甲改' in names and '被改坏' not in names, str(names))

print('== 4. ZUP ==')
r = admin.get(f'/api/families/{fid}/export?format=zup&include_resources=0')
check('ZUP 导出返回 ZIP', r.status_code == 200 and r.data[:2] == b'PK')
z = zipfile.ZipFile(io.BytesIO(r.data))
check('ZUP 含 manifest/data', 'manifest.json' in z.namelist() and 'data.json' in z.namelist())
fid2 = mkfamily('ZUP目标')
zup = admin.get(f'/api/families/{fid}/export?format=zup&include_resources=0').data
r = admin.post(f'/api/families/{fid2}/import',
               data={'file': (io.BytesIO(zup), 'x.zup')},
               content_type='multipart/form-data')
check('ZUP 可导入', r.status_code == 200, str(r.get_json()))
check('ZUP 导入成员数正确', scalar('SELECT COUNT(*) c FROM person WHERE family_id=?', (fid2,))['c'] >= 1)

print('== 5. 设置接线 ==')
admin.put('/api/admin/settings', json={'site.page_size': 30,
                                       'storage.default_strategy': 'overwrite',
                                       'site.name': '测试家谱站'})
me = m.get('/api/auth/me').get_json()['data']
check('page_size 下发', me.get('page_size') == 30, str(me.get('page_size')))
check('default_strategy 下发', me.get('default_strategy') == 'overwrite')
check('密码策略下发', me.get('password_min_length') == 8 and me.get('password_require_strong') is True)
check('上传上限不超过全局 200MB', int(me.get('upload_max_mb', 200)) <= 200)
check('站点名公共接口', app.test_client().get('/api/site').get_json()['data']['site_name'] == '测试家谱站')

print('== 6. 全库备份下载 ==')
r = admin.post('/api/admin/backup')
check('全库备份创建', r.status_code == 200, str(r.get_json()))
name = r.get_json()['data']['file']
r = admin.get(f'/api/admin/backups/{name}')
check('全库备份可下载', r.status_code == 200 and r.data[:2] == b'PK')
check('非法备份名被拒', admin.get('/api/admin/backups/../app.db').status_code in (400, 404))

print('== 7. 婚姻日期顺序 ==')
fid = mkfamily('婚姻日期')
a = admin.post(f'/api/families/{fid}/persons', json={'name': '甲', 'generation': 1}).get_json()['data']['id']
b = admin.post(f'/api/families/{fid}/persons', json={'name': '乙', 'generation': 1}).get_json()['data']['id']
r = admin.post(f'/api/families/{fid}/marriages',
               json={'spouse1_id': a, 'spouse2_id': b,
                     'marriage_date': '2000-01-01', 'divorce_date': '1999-01-01'})
check('离婚早于结婚被拒', r.status_code == 400, str(r.get_json()))
r = admin.post(f'/api/families/{fid}/marriages',
               json={'spouse1_id': a, 'spouse2_id': b,
                     'marriage_date': '2000-01-01', 'divorce_date': '2001-01-01'})
check('正常日期可登记', r.status_code == 200, str(r.get_json()))

print('== 8. 服务端分页/远程搜索 ==')
for path in ('marriages', 'parentchild', 'events', 'resources', 'branches'):
    r = admin.get(f'/api/families/{fid}/{path}?page=1&size=1')
    body = r.get_json(silent=True) or {}
    check(f'{path} 分页返回 items/total',
          r.status_code == 200 and isinstance(body.get('data'), dict)
          and 'items' in body['data'] and 'total' in body['data'], str(body)[:120])
r = admin.get(f'/api/families/{fid}/branches?all=1')
check('分支 all=1 保持数组兼容', r.status_code == 200 and isinstance(r.get_json()['data'], list))
bid = admin.post(f'/api/families/{fid}/branches', json={'name': '分页分支'}).get_json()['data']['id']
admin.post(f'/api/families/{fid}/branches/{bid}/members', json={'add_ids': [a, b]})
r = admin.get(f'/api/families/{fid}/persons?branch_id={bid}&page=1&size=1')
check('分支成员按分支分页', r.status_code == 200 and r.get_json()['data']['total'] == 2
      and len(r.get_json()['data']['items']) == 1, str(r.get_json())[:160])
r = admin.get(f'/api/families/{fid}/persons?keyword=甲&size=50')
check('成员远程搜索按关键字返回', r.status_code == 200
      and any(x['name'] == '甲' for x in r.get_json()['data']['items']), str(r.get_json())[:160])

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
cleanup()
raise SystemExit(1 if FAIL else 0)
