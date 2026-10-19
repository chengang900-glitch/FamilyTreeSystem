"""复审修复专项回归：路径穿越、删谱、脱敏、XFF、管理员互删、分支增量、GEDCOM 等

所有用例使用独立临时库，不触碰 data/app.db。
"""
import io
import json
import zipfile
from pathlib import Path

from _testenv import assert_isolated, bootstrap, cleanup, relax_bootstrap_admin  # noqa: E402

bootstrap('review2')
from server.app import app  # noqa: E402

# 本机测试环境可能没有 reportlab；页数预估只需要纸尺寸，打桩避免环境差异
from server.blueprint import print_bp  # noqa: E402
print_bp.paper_size = lambda key: (595.0, 842.0)

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


def rows(sql, args=()):
    with app.app_context():
        from server.db.conn import query as q
        return q(sql, args)


admin = app.test_client()
admin.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
admin.put('/api/admin/settings', json={'security.login_limit_per_minute': 10000,
                                       'security.rate_limit_per_minute': 10000})


def mkfamily(name):
    return admin.post('/api/admin/families', json={'name': name}).get_json()['data']['id']


def mkperson(fid, name, generation=1, **kwargs):
    body = {'name': name, 'generation': generation, **kwargs}
    return admin.post(f'/api/families/{fid}/persons', json=body).get_json()['data']['id']


def mkuser(name, must_change=False):
    r = admin.post('/api/admin/users', json={'username': name, 'password': 'test1234',
                                             'must_change_pwd': must_change})
    assert r.status_code == 200, r.get_json()
    with app.app_context():
        from server.db.conn import query_one
        return query_one('SELECT id FROM users WHERE username=?', (name,))['id']


print('== 1. 资源路径穿越 ==')
fid = mkfamily('路径穿越测试')
outside_dir = Path(app.config['UPLOAD_DIR']).parent.parent / 'outside_secret'
outside_dir.mkdir(parents=True, exist_ok=True)
outside = outside_dir / 'secret.txt'
outside.write_text('OUTSIDE-SECRET', encoding='utf-8')
payload = {
    'persons': [{'id': 1, 'name': '测试', 'generation': 1}],
    'resources': [{'id': 10, 'name': '恶意资源', 'fid': 'evil', 'type': 1,
                   'storage_path': str(outside), 'file_size': 10}],
}
r = admin.post(f'/api/families/{fid}/import',
               data={'file': (io.BytesIO(json.dumps(payload).encode()), 'evil.json')},
               content_type='multipart/form-data')
check('导入绝对路径资源不报错但路径被丢弃', r.status_code == 200, str(r.get_json()))
rid = scalar('SELECT id FROM resource WHERE family_id=?', (fid,))['id']
r = admin.get(f'/api/families/{fid}/files/{rid}')
check('绝对路径资源不可下载', r.status_code == 404, str(r.status_code))
r = admin.delete(f'/api/families/{fid}/resources/{rid}')
check('删除资源不会删除上传目录外文件', r.status_code == 200 and outside.exists(), str(r.status_code))

print('== 2. 删除带关系家谱 ==')
fid = mkfamily('删谱测试')
p1 = mkperson(fid, '甲')
p2 = mkperson(fid, '乙', 2)
admin.post(f'/api/families/{fid}/parentchild', json={'parent_id': p1, 'child_ids': [p2]})
admin.post(f'/api/families/{fid}/marriages', json={'spouse1_id': p1, 'spouse2_id': p2})
r = admin.delete(f'/api/admin/families/{fid}')
check('带婚姻/亲子的家谱可删除', r.status_code == 200, str(r.get_json()))
check('家谱与人物已清空', scalar('SELECT COUNT(*) c FROM family WHERE id=?', (fid,))['c'] == 0
      and scalar('SELECT COUNT(*) c FROM person WHERE family_id=?', (fid,))['c'] == 0)

print('== 3. 导出/付印脱敏 ==')
fid = mkfamily('脱敏测试')
living = mkperson(fid, '在世者', birth_date='1990-01-01', record='私密生平',
                  bury_address='某墓地')
admin.put('/api/admin/settings', json={'privacy.mask_living': True})
uid = mkuser('review_member')
admin.post(f'/api/families/{fid}/members', json={'user_id': uid, 'role': 'member'})
m = app.test_client()
m.post('/api/auth/login', json={'username': 'review_member', 'password': 'test1234'})
detail = m.get(f'/api/families/{fid}/persons/{living}').get_json()['data']
check('详情页脱敏生效', detail['birth_date'] is None and detail['record'] is None)
export = m.get(f'/api/families/{fid}/export?format=json')
person = [x for x in json.loads(export.data)['persons'] if x['id'] == living][0]
check('JSON 导出不泄露在世者生日', person['birth_date'] is None, str(person['birth_date']))
docx = m.post(f'/api/families/{fid}/print/docx', json={'mode': 'lineage'})
text = ''
if docx.status_code == 200:
    import docx as docxlib
    d = docxlib.Document(io.BytesIO(docx.data))
    text = '\n'.join(p.text for p in d.paragraphs)
check('Word 付印不泄露生日/生平', '1990-01-01' not in text and '私密生平' not in text)
admin.put('/api/admin/settings', json={'privacy.mask_living': False})

print('== 4. XFF 受信代理 ==')
mkuser('review_xff')
x = app.test_client()
x.post('/api/auth/login', json={'username': 'review_xff', 'password': 'test1234'},
       headers={'X-Forwarded-For': '6.6.6.6, 203.0.113.5'},
       environ_base={'REMOTE_ADDR': '127.0.0.1'})
row = scalar("SELECT ip FROM operation_log WHERE action='login'"
             " AND user_id=(SELECT id FROM users WHERE username='review_xff')"
             ' ORDER BY id DESC LIMIT 1')
check('取最右侧非代理地址', row['ip'] == '203.0.113.5', str(row['ip']))

print('== 5. 家谱管理员权限 ==')
fid = mkfamily('权限测试')
ua = mkuser('review_a1')
ub = mkuser('review_a2')
uc = mkuser('review_c')
admin.post(f'/api/families/{fid}/members', json={'user_id': ua, 'role': 'admin'})
admin.post(f'/api/families/{fid}/members', json={'user_id': ub, 'role': 'admin'})
admin.post(f'/api/families/{fid}/members', json={'user_id': uc, 'role': 'member'})
a1 = app.test_client()
a1.post('/api/auth/login', json={'username': 'review_a1', 'password': 'test1234'})
r = a1.delete(f'/api/families/{fid}/members/{ub}')
check('家谱管理员不能移除其他管理员', r.status_code == 403, str(r.status_code))
r = a1.delete(f'/api/families/{fid}/members/{uc}')
check('家谱管理员仍可移除普通成员', r.status_code == 200, str(r.status_code))
r = a1.get(f'/api/families/{fid}/members/search?keyword=review')
check('成员搜索不再返回手机号', r.status_code == 200
      and all('phone' not in x for x in r.get_json()['data']), str(r.get_json()))

print('== 6. 分支增量保存 ==')
fid = mkfamily('分支增量')
persons = [mkperson(fid, f'成员{i}') for i in range(1, 4)]
bid = admin.post(f'/api/families/{fid}/branches',
                 json={'name': '长房', 'person_ids': [persons[0], persons[1]]}).get_json()['data']['id']
r = admin.put(f'/api/families/{fid}/branches/{bid}',
              json={'add_ids': [persons[2]], 'remove_ids': [persons[0]]})
check('分支增量更新成功', r.status_code == 200, str(r.get_json()))
branches = {x['id']: x for x in rows('SELECT id, branch_id FROM person WHERE family_id=?', (fid,))}
check('未提交的成员归属不被清空',
      branches[persons[1]]['branch_id'] == bid and branches[persons[2]]['branch_id'] == bid,
      str(branches))
check('被移除成员归属清空', branches[persons[0]]['branch_id'] is None)
r = admin.put(f'/api/families/{fid}/branches/{bid}', json={'person_ids': [persons[1]]})
check('person_ids 全量接口仍兼容', r.status_code == 200, str(r.get_json()))

print('== 7. GEDCOM 单亲往返 ==')
fid = mkfamily('GEDCOM单亲源')
father = mkperson(fid, '父', type=1)
mother = mkperson(fid, '母', type=2)
child = mkperson(fid, '子', 2, type=1)
admin.post(f'/api/families/{fid}/marriages', json={'spouse1_id': father, 'spouse2_id': mother})
admin.post(f'/api/families/{fid}/parentchild', json={'parent_id': father, 'child_ids': [child]})
r = admin.get(f'/api/families/{fid}/export?format=gedcom&include_resources=0')
z = zipfile.ZipFile(io.BytesIO(r.data))
ged = z.read(z.namelist()[0]).decode('utf-8')
fid2 = mkfamily('GEDCOM单亲目标')
r = admin.post(f'/api/families/{fid2}/import',
               data={'file': (io.BytesIO(ged.encode()), 'one.ged')},
               content_type='multipart/form-data')
links = rows('SELECT p1.name parent, p2.name child FROM parentchild pc'
             ' JOIN person p1 ON p1.id=pc.parent_id JOIN person p2 ON p2.id=pc.child_id'
             ' WHERE pc.family_id=?', (fid2,))
check('单亲 GEDCOM 往返不凭空多出父母', len(links) == 1 and links[0]['parent'] == '父',
      str([dict(x) for x in links]))

print('== 8. 新建用户默认强制改密 ==')
r = admin.post('/api/admin/users', json={'username': 'review_force', 'password': 'test1234'})
uid = scalar('SELECT id FROM users WHERE username=?', ('review_force',))['id']
check('默认 must_change_pwd=1',
      scalar('SELECT must_change_pwd FROM users WHERE id=?', (uid,))['must_change_pwd'] == 1)
c = app.test_client()
c.post('/api/auth/login', json={'username': 'review_force', 'password': 'test1234'})
check('未改密前业务接口被拦截', c.get('/api/families').get_json()['code'] == 4031)

print('== 9. 环检测与孤儿清理 ==')
fid = mkfamily('环检测')
a = admin.post(f'/api/families/{fid}/branches', json={'name': 'A'}).get_json()['data']['id']
b = admin.post(f'/api/families/{fid}/branches', json={'name': 'B', 'parent_id': a}).get_json()['data']['id']
r = admin.put(f'/api/families/{fid}/branches/{a}', json={'parent_id': b})
check('分支父子环被拒', r.status_code == 400, str(r.get_json()))
cycle = {'persons': [{'id': 1, 'name': '甲', 'generation': 1},
                     {'id': 2, 'name': '乙', 'generation': 2}],
         'parentchild': [{'id': 1, 'parent_id': 1, 'child_id': 2},
                         {'id': 2, 'parent_id': 2, 'child_id': 1}]}
r = admin.post(f'/api/families/{fid}/import',
               data={'file': (io.BytesIO(json.dumps(cycle).encode()), 'cycle.json')},
               content_type='multipart/form-data')
check('导入亲子环被拒', r.status_code == 400, str(r.get_json()))

fid = mkfamily('孤儿关联')
p1 = mkperson(fid, '甲')
p2 = mkperson(fid, '乙', 2)
mid = admin.post(f'/api/families/{fid}/marriages',
                 json={'spouse1_id': p1, 'spouse2_id': p2}).get_json()['data']['id']
r = admin.post(f'/api/families/{fid}/resources',
               data={'file': (io.BytesIO(b'hello'), 'a.txt'), 'name': '附件'},
               content_type='multipart/form-data')
rid = r.get_json()['data']['id']
admin.post(f'/api/families/{fid}/resources/{rid}/relations',
           json={'entity_type': 'marriage', 'entity_id': mid})
admin.delete(f'/api/families/{fid}/marriages/{mid}')
check('删除婚姻同步清理资源关联',
      scalar('SELECT COUNT(*) c FROM resource_relation WHERE entity_type="marriage"'
             ' AND entity_id=?', (mid,))['c'] == 0)

print('== 10. 归档与入参校验 ==')
fid = mkfamily('归档测试')
mkperson(fid, '族人')
uid = mkuser('review_arch')
admin.post(f'/api/families/{fid}/members', json={'user_id': uid, 'role': 'member'})
admin.put(f'/api/admin/families/{fid}', json={'status': 0})
u = app.test_client()
u.post('/api/auth/login', json={'username': 'review_arch', 'password': 'test1234'})
check('归档家谱普通成员不可访问', u.get(f'/api/families/{fid}/persons').status_code == 403)
check('归档家谱超管仍可访问', admin.get(f'/api/families/{fid}/persons').status_code == 200)

fid = mkfamily('参数测试')
mkperson(fid, '参数人')
r = admin.post(f'/api/families/{fid}/print/estimate',
               json={'mode': 'lineage', 'generations': '3'})
check('付印 generations 字符串被转成整数而非 500', r.status_code == 200, str(r.get_json()))
r = admin.post(f'/api/families/{fid}/print/estimate',
               json={'mode': 'lineage', 'paper': {'x': 1}})
check('付印 paper 非字符串返回 400', r.status_code == 400, str(r.get_json()))
r = admin.post(f'/api/families/{fid}/import',
               data={'file': (io.BytesIO(json.dumps(
                   {'persons': [{'id': 1, 'name': {'bad': 1}, 'generation': 1}]}).encode()),
                   'bad.json')}, content_type='multipart/form-data')
check('导入非字符串姓名不再 500', r.status_code in (200, 400), str(r.status_code))
r = admin.get('/assets/not-exist.js')
check('缺失静态资源返回 404', r.status_code == 404, str(r.status_code))
check('缺失静态资源不缓存 immutable',
      'immutable' not in (r.headers.get('Cache-Control') or ''))

print('== 11. 多段婚姻 ==')
fid = mkfamily('多段婚姻')
spouses = [mkperson(fid, f'配偶{i}') for i in range(1, 5)]
for order, other in enumerate(spouses[1:], 1):
    r = admin.post(f'/api/families/{fid}/marriages',
                   json={'spouse1_id': spouses[0], 'spouse2_id': other, 'marriage_order': order})
    check(f'同一成员可登记与 {other} 的婚姻', r.status_code == 200, str(r.get_json()))
ml = admin.get(f'/api/families/{fid}/marriages').get_json()['data']
check('同一成员三段婚姻可同时存在', len(ml) == 3, str(len(ml)))

print(f'\n结果：通过 {len(PASS)}，失败 {len(FAIL)}')
if FAIL:
    print('失败项：', FAIL)
cleanup()
raise SystemExit(1 if FAIL else 0)
