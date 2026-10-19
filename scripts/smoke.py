"""端到端冒烟测试：针对已启动的服务（默认 http://127.0.0.1:8100）

管理员密码默认 admin123，可用环境变量覆盖：
    SMOKE_USER=admin SMOKE_PASSWORD=xxxxxxxx python scripts/smoke.py
若服务端管理员仍处于「首次登录需改密」状态，本脚本会提示并以退出码 2 结束。
"""
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8100'
ADMIN_USER = os.environ.get('SMOKE_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('SMOKE_PASSWORD', 'admin123')
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  {extra}' if extra else ''))


def client():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(op, method, path, body=None, headers=None):
    url = BASE + path
    data = None
    hdr = {'X-Requested-With': 'fetch'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        hdr['Content-Type'] = 'application/json'
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        resp = op.open(req, timeout=30)
        raw = resp.read()
        try:
            return resp.status, json.loads(raw.decode('utf-8')), dict(resp.headers)
        except Exception:
            return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode('utf-8')), dict(e.headers)
        except Exception:
            return e.code, raw, dict(e.headers)


print('== 服务可用性 ==')
anon = client()
st, raw, h = call(anon, 'GET', '/')
html = raw if isinstance(raw, bytes) else b''
check('首页返回 HTML', st == 200 and b'id="root"' in html, str(st))
check('安全响应头', h.get('X-Content-Type-Options') == 'nosniff'
      and h.get('X-Frame-Options') == 'DENY')
st, body, _ = call(anon, 'GET', '/api/families')
check('未登录访问受保护接口返回 401', body.get('code') == 401, str(body.get('code')))

print('== 登录 ==')
adm = client()
st, body, _ = call(adm, 'POST', '/api/auth/login',
                   {'username': ADMIN_USER, 'password': ADMIN_PASSWORD})
check('超级管理员登录', body.get('code') == 0, body.get('msg', ''))
check('返回超级管理员标识', body.get('data', {}).get('is_superuser') is True)
if body.get('data', {}).get('must_change_pwd'):
    print('\n  提示：该管理员账号处于「首次登录需改密」状态（后端会拦截业务接口）。')
    print('        请先在浏览器登录修改密码，再用 SMOKE_PASSWORD=新密码 重跑本脚本。')
    print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}（提前结束）')
    sys.exit(2)

print('== 家谱与业务数据 ==')
suffix = uuid.uuid4().hex[:6]
st, body, _ = call(adm, 'POST', '/api/admin/families',
                   {'name': f'冒烟测试家谱{suffix}', 'surname': '烟'})
fid = body['data']['id']
check('创建家谱', st == 200)

persons = []
for gen, name in [(1, '烟祖'), (2, '烟父'), (3, '烟子')]:
    st, body, _ = call(adm, 'POST', f'/api/families/{fid}/persons',
                       {'generation': gen, 'name': name, 'type': 1})
    persons.append(body['data']['id'])
check('创建三代成员', len(persons) == 3)

call(adm, 'POST', f'/api/families/{fid}/parentchild',
     {'parent_id': persons[0], 'child_ids': [persons[1]]})
call(adm, 'POST', f'/api/families/{fid}/parentchild',
     {'parent_id': persons[1], 'child_ids': [persons[2]]})
st, body, _ = call(adm, 'GET', f'/api/families/{fid}/pedigree')
d = body['data']
check('世系树数据装配', d['total'] == 3 and d['root'] == persons[0], str(d['root']))
rootkids = [n for n in d['nodes'] if n['id'] == d['root']][0]['children']
check('亲子链路正确', rootkids == [persons[1]], str(rootkids))

print('== 分支与事件 ==')
st, body, _ = call(adm, 'POST', f'/api/families/{fid}/branches',
                   {'name': '长房', 'hall_name': '敦本堂'})
bid = body['data']['id']
call(adm, 'POST', f'/api/families/{fid}/branches/{bid}/members', {'add_ids': persons[:2]})
st, body, _ = call(adm, 'GET', f'/api/families/{fid}/branches')
check('分支批量归人', body['data'][0]['person_count'] == 2)

st, body, _ = call(adm, 'POST', f'/api/families/{fid}/events',
                   {'name': '祭祖', 'time': '2026-04-05'})
eid = body['data']['id']
call(adm, 'POST', f'/api/families/{fid}/events/{eid}/persons',
     {'person_id': persons[0], 'role': '组织者'})
st, body, _ = call(adm, 'GET', f'/api/families/{fid}/events')
check('事件与参与人', body['data'][0]['person_count'] == 1)

print('== 资源上传与下载 ==')
boundary = '----smokeboundary'
payload = b'--' + boundary.encode() + b'\r\n' \
    + b'Content-Disposition: form-data; name="file"; filename="smoke.pdf"\r\n' \
    + b'Content-Type: application/pdf\r\n\r\n' + b'PDFDATA' + b'\r\n' \
    + b'--' + boundary.encode() + b'\r\n' \
    + b'Content-Disposition: form-data; name="name"\r\n\r\n' + '烟谱'.encode('utf-8') + b'\r\n' \
    + b'--' + boundary.encode() + b'\r\n' \
    + b'Content-Disposition: form-data; name="type"\r\n\r\n1\r\n' \
    + b'--' + boundary.encode() + b'--\r\n'
op = adm
req = urllib.request.Request(
    f'{BASE}/api/families/{fid}/resources', data=payload, method='POST',
    headers={'Content-Type': f'multipart/form-data; boundary={boundary}',
             'X-Requested-With': 'fetch'})
res = json.loads(op.open(req, timeout=30).read().decode('utf-8'))
rid = res['data']['id']
check('资源上传', res['code'] == 0)
st, raw, _ = call(op, 'GET', f'/api/families/{fid}/files/{rid}')
check('资源鉴权下载', b'PDFDATA' in (raw if isinstance(raw, bytes) else b''))

print('== 导出与付印 ==')
st, raw, _ = call(adm, 'GET', f'/api/families/{fid}/export?format=json')
ok_json = ('persons' in raw) if isinstance(raw, dict) else (b'"persons"' in raw)
check('导出 JSON', ok_json)
st, raw, _ = call(adm, 'POST', f'/api/families/{fid}/print/pdf',
                  {'mode': 'lineage', 'paper': 'A4', 'add_cover': True})
check('导出 PDF', isinstance(raw, bytes) and raw[:4] == b'%PDF', str(raw[:4]) if isinstance(raw, bytes) else '')
st, raw, _ = call(adm, 'POST', f'/api/families/{fid}/print/docx', {'mode': 'lineage'})
check('导出 Word', isinstance(raw, bytes) and raw[:2] == b'PK')

print('== 权限 ==')
uname = f'smoke_{suffix}'
call(adm, 'POST', '/api/admin/users', {'username': uname, 'password': 'test1234', 'must_change_pwd': False})
st, body, _ = call(adm, 'GET', f'/api/admin/users?keyword={uname}')
uid = body['data'][0]['id']
call(adm, 'POST', f'/api/admin/families/{fid}/members', {'user_id': uid, 'role': 'member'})
usr = client()
st, body, _ = call(usr, 'POST', '/api/auth/login', {'username': uname, 'password': 'test1234'})
check('普通用户登录', body.get('code') == 0, body.get('msg', ''))
st, body, _ = call(usr, 'GET', f'/api/families/{fid}/persons')
check('普通用户可读', body.get('data', {}).get('total') == 3)
st, body, _ = call(usr, 'POST', f'/api/families/{fid}/persons',
                   {'generation': 1, 'name': 'X'})
check('普通用户写入被拒 403', st == 403, str(st))
st, body, _ = call(usr, 'GET', '/api/admin/users')
check('普通用户访问超管接口被拒 403', st == 403)

print('== 系统设置与备份 ==')
st, body, _ = call(adm, 'PUT', '/api/admin/settings', {'site.name': '烟氏谱牒'})
check('保存系统设置', body.get('code') == 0)
st, body, _ = call(adm, 'GET', '/api/admin/settings')
vals = {s['key']: s['value'] for s in body['data']}
check('设置生效', vals.get('site.name') == '烟氏谱牒')
call(adm, 'PUT', '/api/admin/settings', {'site.name': '家谱管理系统'})

st, body, _ = call(adm, 'POST', '/api/admin/backup')
check('手动备份', body.get('code') == 0, body.get('msg', ''))
st, body, _ = call(adm, 'GET', '/api/admin/backups')
check('备份列表', isinstance(body.get('data'), list) and len(body['data']) >= 1)

print('== 清理 ==')
call(adm, 'DELETE', f'/api/admin/families/{fid}')
call(adm, 'DELETE', f'/api/admin/users/{uid}')

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
    sys.exit(1)
