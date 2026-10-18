"""修复回归测试：覆盖代码审查报告中的 P0/P1/P2 修复点

与 test_m1..m4 一样跑在独立临时库上，不触碰 data/app.db。
"""
import io
import json
import sqlite3
import sys
import time

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('fixes')
from server.app import app  # noqa: E402

assert_isolated(app)
relax_bootstrap_admin(app)

PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  {extra}' if extra else ''))


def sql(query, args=()):
    with app.app_context():
        from server.db.conn import query as q
        return q(query, args)


def scalar(query, args=()):
    with app.app_context():
        from server.db.conn import query_one as q1
        return q1(query, args)


admin = app.test_client()
admin.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
admin.put('/api/admin/settings', json={'security.login_limit_per_minute': 10000,
                                       'security.rate_limit_per_minute': 10000})

print('== 批次1 交付链路（静态一致性） ==')
root = __import__('pathlib').Path(__file__).resolve().parents[1]
pkg = json.loads((root / 'web' / 'package.json').read_text(encoding='utf-8'))
check('package.json 含 build 脚本', pkg.get('scripts', {}).get('build') is not None, str(pkg.get('scripts')))
check('package.json 含 typecheck 脚本', 'typecheck' in pkg.get('scripts', {}))
dockerfile = (root / 'deploy' / 'Dockerfile').read_text(encoding='utf-8')
check('Dockerfile 从 /server/webroot 取产物', '/server/webroot' in dockerfile)
check('Dockerfile 提供 FTS_CONFIG 指向的配置', 'COPY server/config.yaml ./config.yaml' in dockerfile)
check('Dockerfile 不再指向 /app/data/config.yaml', '/app/data/config.yaml' not in dockerfile)
startbat = (root / 'deploy' / 'start.bat').read_text(encoding='utf-8')
check('start.bat 切到仓库根目录', '%~dp0..' in startbat)
check('存在 .dockerignore', (root / '.dockerignore').exists())
reqs = (root / 'server' / 'requirements.txt').read_text(encoding='utf-8')
check('requirements 移除未使用依赖 Pillow', 'Pillow' not in reqs)

print('== 批次2 安全边界 ==')
# 1) 伪造 X-Forwarded-For 不能绕过限流
admin.put('/api/admin/settings', json={'security.login_limit_per_minute': 3})
codes = []
probe = app.test_client()
for i in range(5):
    r = probe.post('/api/auth/login', json={'username': 'nobody', 'password': 'x'},
                   headers={'X-Forwarded-For': f'1.1.1.{i}'},
                   environ_base={'REMOTE_ADDR': '203.0.113.9'})
    codes.append(r.status_code)
admin.put('/api/admin/settings', json={'security.login_limit_per_minute': 10000})
check('伪造 XFF 无法绕过登录限流', 429 in codes, str(codes))

# 2) 已下线的账号枚举接口
check('user-search 接口已下线', admin.get('/api/families/user-search?keyword=a').status_code == 404)

# 3) 改密后旧令牌立即失效
admin.post('/api/admin/users', json={'username': 'u_pwd', 'password': 'test1234'})
u_pwd = scalar('SELECT id FROM users WHERE username=?', ('u_pwd',))['id']
c_a = app.test_client()
c_a.post('/api/auth/login', json={'username': 'u_pwd', 'password': 'test1234'})
old_token = c_a.get_cookie('fts_token').value
r = c_a.put('/api/auth/password', json={'old_password': 'test1234', 'new_password': 'test5678'})
check('改密成功', r.status_code == 200, r.get_json().get('msg', ''))
c_old = app.test_client()
c_old.set_cookie('fts_token', old_token)
check('改密后旧 Cookie 失效', c_old.get('/api/auth/me').status_code == 401)
check('改密后当前会话仍可用', c_a.get('/api/auth/me').status_code == 200)
check('新密码可登录', app.test_client().post(
    '/api/auth/login', json={'username': 'u_pwd', 'password': 'test5678'}).status_code == 200)

# 4) must_change_pwd 后端强制
admin.post(f'/api/admin/users/{u_pwd}/reset-password', json={'password': 'reset1234'})
c_m = app.test_client()
c_m.post('/api/auth/login', json={'username': 'u_pwd', 'password': 'reset1234'})
r = c_m.get('/api/families')
body = r.get_json() or {}
check('待改密时业务接口被拒（4031）', r.status_code == 403 and body.get('code') == 4031,
      f'{r.status_code} {body.get("code")}')
check('待改密时 /auth/me 仍可访问', c_m.get('/api/auth/me').status_code == 200)
c_m.put('/api/auth/password', json={'old_password': 'reset1234', 'new_password': 'test1234'})
check('改密后业务接口恢复', c_m.get('/api/families').status_code == 200)

# 5) 家谱管理员不能授予 admin
fid = admin.post('/api/admin/families', json={'name': '安全测试谱'}).get_json()['data']['id']
admin.post('/api/admin/users', json={'username': 'u_fadmin', 'password': 'test1234'})
admin.post('/api/admin/users', json={'username': 'u_fmember', 'password': 'test1234'})
u_fadmin = scalar('SELECT id FROM users WHERE username=?', ('u_fadmin',))['id']
u_fmember = scalar('SELECT id FROM users WHERE username=?', ('u_fmember',))['id']
admin.post(f'/api/admin/families/{fid}/members', json={'user_id': u_fadmin, 'role': 'admin'})
admin.post(f'/api/admin/families/{fid}/members', json={'user_id': u_fmember, 'role': 'member'})
c_fa = app.test_client()
c_fa.post('/api/auth/login', json={'username': 'u_fadmin', 'password': 'test1234'})
r = c_fa.post(f'/api/families/{fid}/members', json={'user_id': u_pwd, 'role': 'admin'})
check('家谱管理员不可授予 admin（403）', r.status_code == 403, str(r.status_code))
admin.post(f'/api/admin/families/{fid}/members', json={'user_id': u_pwd, 'role': 'member'})
check('超管仍可授予 admin', admin.put(
    f'/api/admin/families/{fid}/members/{u_pwd}', json={'role': 'admin'}).status_code == 200)

# 6) 普通成员看不到他人手机号
c_fm = app.test_client()
c_fm.post('/api/auth/login', json={'username': 'u_fmember', 'password': 'test1234'})
rows = c_fm.get(f'/api/families/{fid}/members').get_json()['data']
check('普通成员名单不含手机号', all('phone' not in r for r in rows), str(rows[:1]))
rows = c_fa.get(f'/api/families/{fid}/members').get_json()['data']
check('家谱管理员名单含手机号', any('phone' in r for r in rows))

# 7) 静态资源缓存与安全头
check('API 响应 no-store', 'no-store' in admin.get('/api/health').headers.get('Cache-Control', ''))
assets = [p.name for p in (root / 'server' / 'webroot' / 'assets').glob('*')]
if assets:
    r = admin.get(f'/assets/{assets[0]}')
    check('静态资源长缓存 immutable', 'immutable' in r.headers.get('Cache-Control', ''),
          r.headers.get('Cache-Control', ''))
check('下发 CSP 头', "default-src 'self'" in admin.get('/api/health').headers.get('Content-Security-Policy', ''))

print('== 批次3 数据正确性 ==')
# 8) 参数错误统一 400
cases = [
    ('世代非数字', admin.post(f'/api/families/{fid}/persons', json={'name': 'x', 'generation': 'abc'})),
    ('类型越界', admin.post(f'/api/families/{fid}/persons', json={'name': 'x', 'generation': 1, 'type': 99})),
    ('分页非数字', admin.get(f'/api/families/{fid}/persons?page=abc')),
    ('日志 limit 非数字', admin.get('/api/admin/logs?limit=abc')),
    ('婚姻双方同一人', admin.post(f'/api/families/{fid}/marriages',
                              json={'spouse1_id': 1, 'spouse2_id': 1})),
]
for label, resp in cases:
    check(f'{label} 返回 400', resp.status_code == 400, str(resp.status_code))

# 9) 空串外键落库为 NULL
pid = admin.post(f'/api/families/{fid}/persons',
                 json={'name': '空分支', 'generation': 1, 'branch_id': ''}).get_json()['data']['id']
check('branch_id 空串转 NULL', scalar('SELECT branch_id FROM person WHERE id=?', (pid,))['branch_id'] is None)

# 10) 亲子环检测
a = admin.post(f'/api/families/{fid}/persons', json={'name': '环A', 'generation': 1}).get_json()['data']['id']
b = admin.post(f'/api/families/{fid}/persons', json={'name': '环B', 'generation': 2}).get_json()['data']['id']
admin.post(f'/api/families/{fid}/parentchild', json={'parent_id': a, 'child_ids': [b]})
r = admin.post(f'/api/families/{fid}/parentchild', json={'parent_id': b, 'child_ids': [a]})
check('亲子环被拒绝（400）', r.status_code == 400, f'{r.status_code} {r.get_json().get("msg")}')
check('环路未入库', len(sql('SELECT id FROM parentchild WHERE family_id=?', (fid,))) == 1)

# 11) 事务回滚：分支改人失败不留半成品
bid = admin.post(f'/api/families/{fid}/branches', json={'name': '分支1'}).get_json()['data']['id']
admin.put(f'/api/families/{fid}/branches/{bid}', json={'person_ids': [pid]})
r = admin.put(f'/api/families/{fid}/branches/{bid}', json={'person_ids': [999999]})
with app.app_context():
    from server.common import ApiError
check('非法 person_ids 返回 4xx', r.status_code in (400, 404), str(r.status_code))
check('失败后原归属保留', scalar('SELECT branch_id FROM person WHERE id=?', (pid,))['branch_id'] == bid)

# 12) 删除人物清理从属行
ev = admin.post(f'/api/families/{fid}/events',
                json={'name': '事件', 'time': '2026-10-18'}).get_json()['data']['id']
victim = admin.post(f'/api/families/{fid}/persons',
                    json={'name': '临时', 'generation': 1}).get_json()['data']['id']
admin.post(f'/api/families/{fid}/events/{ev}/persons', json={'person_id': victim})
admin.delete(f'/api/families/{fid}/persons/{victim}')
check('删除人物后无 eventperson 孤儿',
      scalar('SELECT COUNT(*) c FROM eventperson WHERE person_id=?', (victim,))['c'] == 0)

# 13) 外键约束真实生效
with app.app_context():
    from server.db.conn import get_db
    con = get_db()
    fks = con.execute('PRAGMA foreign_key_list(marriage)').fetchall()
    check('婚姻表已声明外键', len(fks) >= 2, str(len(fks)))
    check('foreign_key_check 无违规', not con.execute('PRAGMA foreign_key_check').fetchall())
    try:
        con.execute('INSERT INTO marriage (family_id, spouse1_id, spouse2_id, marriage_order,'
                    ' created_at, updated_at) VALUES (?,?,?,1,?,?)',
                    (fid, 987654, 987655, 'x', 'x'))
        con.rollback()
        check('悬空 spouse_id 被外键拦截', False)
    except sqlite3.IntegrityError:
        con.rollback()
        check('悬空 spouse_id 被外键拦截', True)

# 14) 导入 ID 重映射
src = {
    'persons': [{'id': 901, 'generation': 1, 'name': '源甲', 'type': 1},
                {'id': 902, 'generation': 1, 'name': '源乙', 'type': 2},
                {'id': 903, 'generation': 2, 'name': '源丙', 'type': 1}],
    'marriages': [{'id': 91, 'spouse1_id': 901, 'spouse2_id': 902}],
    'parentchild': [{'id': 92, 'parent_id': 901, 'child_id': 903}],
    'branches': [{'id': 93, 'name': '源分支', 'parent_id': None}],
}
fid2 = admin.post('/api/admin/families', json={'name': '导入目标谱'}).get_json()['data']['id']
r = admin.post(f'/api/families/{fid2}/import',
               data={'file': (io.BytesIO(json.dumps(src, ensure_ascii=False).encode()), 'd.json')},
               content_type='multipart/form-data')
check('导入成功', r.status_code == 200, r.get_json().get('msg', ''))
m = scalar('SELECT * FROM marriage WHERE family_id=?', (fid2,))
check('婚姻关系指向新 ID 且同谱',
      m and m['spouse1_id'] not in (901, 902)
      and scalar('SELECT family_id FROM person WHERE id=?', (m['spouse1_id'],))['family_id'] == fid2)
pc = scalar('SELECT * FROM parentchild WHERE family_id=?', (fid2,))
check('亲子关系指向新 ID', pc and pc['parent_id'] not in (901, 902, 903))
check('导入计数为实际入库数', r.get_json()['data']['imported'].get('person') == 3,
      str(r.get_json()['data'].get('imported')))

# 15) 导出 → 导入闭环（同一份数据可再次导入）
r = admin.get(f'/api/families/{fid2}/export?format=json')
fid3 = admin.post('/api/admin/families', json={'name': '闭环谱'}).get_json()['data']['id']
payload = io.BytesIO(r.data)
r = admin.post(f'/api/families/{fid3}/import',
               data={'file': (payload, 'data.json')}, content_type='multipart/form-data')
check('导出包可再次导入', r.status_code == 200 and r.get_json()['data']['person'] == 3,
      str(r.get_json().get('data')))

# 16) ZIP 数据包内的资源原件可解包导入
import pathlib  # noqa: E402
admin.post(f'/api/families/{fid2}/resources',
           data={'file': (io.BytesIO(b'PDFDATA'), 'a.pdf'), 'name': '原件'},
           content_type='multipart/form-data')
blob = admin.get(f'/api/families/{fid2}/export?format=json&include_resources=1').data
fid4 = admin.post('/api/admin/families', json={'name': '资源导入谱'}).get_json()['data']['id']
r = admin.post(f'/api/families/{fid4}/import',
               data={'file': (io.BytesIO(blob), 'pkg.zip')}, content_type='multipart/form-data')
check('ZIP 导入含资源', r.status_code == 200 and r.get_json()['data']['resource'] == 1,
      str(r.get_json().get('data')))
row = scalar('SELECT storage_path FROM resource WHERE family_id=?', (fid4,))
check('资源文件已落地', bool(row) and (pathlib.Path(app.config['UPLOAD_DIR']) / row['storage_path']).exists())

# 17) GEDCOM 导入按家谱结构推算世代
ged = ('0 HEAD\n1 CHAR UTF-8\n0 @P1@ INDI\n1 NAME 甲\n1 SEX M\n'
       '0 @P2@ INDI\n1 NAME 乙\n1 SEX M\n0 @P3@ INDI\n1 NAME 丙\n1 SEX M\n'
       '0 @F1@ FAM\n1 HUSB @P1@\n1 CHIL @P2@\n0 @F2@ FAM\n1 HUSB @P2@\n1 CHIL @P3@\n0 TRLR\n')
fid5 = admin.post('/api/admin/families', json={'name': 'GED 世代'}).get_json()['data']['id']
admin.post(f'/api/families/{fid5}/import',
           data={'file': (io.BytesIO(ged.encode()), 'x.ged')}, content_type='multipart/form-data')
gens = [r['generation'] for r in sql('SELECT generation FROM person WHERE family_id=?'
                                    ' ORDER BY id', (fid5,))]
check('GEDCOM 世代分层正确', gens == [1, 2, 3], str(gens))

# 18) /api 未匹配路径返回 JSON 404
r = admin.get('/api/not-exists')
check('/api/* 未匹配返回 JSON 404', r.status_code == 404 and r.is_json, str(r.status_code))

# 17) 分页上限统一为 500（前端付印请求 size=500 不再被截断）
d = admin.get(f'/api/families/{fid}/persons?size=9999').get_json()['data']
check('分页上限 500', d['size'] == 500, str(d['size']))

# 18) 在世者脱敏
living = admin.post(f'/api/families/{fid}/persons',
                    json={'name': '在世者', 'generation': 1, 'birth_date': '1990-01-01',
                          'record': '生平详情'}).get_json()['data']['id']
admin.put('/api/admin/settings', json={'privacy.mask_living': True})
rows = c_fm.get(f'/api/families/{fid}/persons?size=500').get_json()['data']['items']
masked = next((x for x in rows if x['id'] == living), None)
check('普通用户看不到在世者生日', masked and masked['birth_date'] is None
      and masked.get('masked') is True, str(masked and masked.get('masked')))
rows = c_fa.get(f'/api/families/{fid}/persons?size=500').get_json()['data']['items']
seen = next((x for x in rows if x['id'] == living), None)
check('家谱管理员仍可见', seen and seen['birth_date'] == '1990-01-01')
admin.put('/api/admin/settings', json={'privacy.mask_living': False})

# 19) 删用户保护唯一家谱管理员
admin.delete(f'/api/admin/families/{fid}/members/1')  # 先移出超管
admin.delete(f'/api/admin/families/{fid}/members/{u_pwd}')  # 与上一步一起，让 u_fadmin 成为唯一管理员
r = admin.delete(f'/api/admin/users/{u_fadmin}')
check('唯一家谱管理员不可删除', r.status_code == 400, str(r.status_code))

# 20) 备份文件名不冲突
with app.app_context():
    from server.service.backup import backup_all
    from pathlib import Path
    tdir = Path(app.config['BACKUP_DIR']) / 'stamp_probe'
    p1 = backup_all(app.config['DB_PATH'], tdir, Path(app.config['UPLOAD_DIR']), False)
    p2 = backup_all(app.config['DB_PATH'], tdir, Path(app.config['UPLOAD_DIR']), False)
    check('连续两次备份文件名不同', p1.name != p2.name, f'{p1.name} / {p2.name}')

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
cleanup()
sys.exit(1 if FAIL else 0)
