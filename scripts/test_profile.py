"""用户反馈专项：旧库无损迁移、规范日期、成员联系信息、婚姻次序与再婚亲子。"""
import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from _testenv import bootstrap, assert_isolated, cleanup, relax_bootstrap_admin
bootstrap('profile')
from server.app import app
from server.db.conn import query, query_one, execute
from server.db.migrate import ensure_profile_fields
from server.service import dates
assert_isolated(app)
relax_bootstrap_admin(app)
PASS, FAIL = [], []
def check(name, result):
    (PASS if result else FAIL).append(name)
    print(('PASS ' if result else 'FAIL ') + name)
c=app.test_client();c.post('/api/auth/login',json={'username':'admin','password':'admin123'})
c.put('/api/admin/settings',json={'security.rate_limit_per_minute':10000})
fid=c.post('/api/admin/families',json={'name':'反馈验收'}).get_json()['data']['id'];base=f'/api/families/{fid}'
contacts={'address':'杭州市测试住址','phone':'+86 13800138000','company':'测试公司','position':'工程师'}
people=[]
for gen,name,kind in [(1,'父亲',1),(1,'母亲甲',3),(1,'母亲乙',3),(2,'孩子甲',1),(2,'孩子乙',2),(1,'其他A',1)]:
    people.append(c.post(base+'/persons',json={'name':name,'generation':gen,'type':kind}).get_json()['data']['id'])
dad,mom1,mom2,kid1,kid2,other=people
pid=c.post(base+'/persons',json={'name':'联系成员','generation':1,'birth_date':'1980-02-29',**contacts}).get_json()['data']['id']
p=c.get(base+f'/persons/{pid}').get_json()['data']
check('联系字段完整保存读取',all(p[k]==v for k,v in contacts.items()))
check('日日期规范值与精度',p['birth_date_iso']=='1980-02-29' and p['birth_date_precision']=='day')
for value,precision in [('1900','year'),('1900-03','month'),('乙卯年正月廿七','text')]:
    r=c.put(base+f'/persons/{pid}',json={'birth_date':value})
    p=c.get(base+f'/persons/{pid}').get_json()['data']
    check('日期精度 '+precision,r.status_code==200 and p['birth_date_precision']==precision and
          p['birth_date_iso']==(None if precision=='text' else value))
check('拒绝不存在公历日期',c.put(base+f'/persons/{pid}',json={'birth_date':'2026-02-30'}).status_code==400)
check('拒绝非文本手机号',c.put(base+f'/persons/{pid}',json={'phone':12345}).status_code==400)
eid=c.post(base+'/events',json={'name':'建祠','time':'2000-05'}).get_json()['data']['id']
with app.app_context():
    event=query_one('SELECT * FROM event WHERE id=?',(eid,))
check('事件也有日期统计字段',event['time_iso']=='2000-05' and event['time_precision']=='month')
m1=c.post(base+'/marriages',json={'spouse1_id':dad,'spouse2_id':mom1,'marriage_order':1,'marriage_date':'1950-01-02'}).get_json()['data']['id']
r=c.post(base+'/marriages',json={'spouse1_id':dad,'spouse2_id':mom2,'marriage_order':1})
check('同一A次序重复被拒绝',r.status_code==400 and '次序' in r.get_json()['msg'])
m2=c.post(base+'/marriages',json={'spouse1_id':dad,'spouse2_id':mom2,'marriage_order':2}).get_json()['data']['id']
check('不同A可使用相同次序',c.post(base+'/marriages',json={'spouse1_id':other,'spouse2_id':mom1,'marriage_order':1}).status_code==200)
check('编辑排除自身',c.put(base+f'/marriages/{m1}',json={'marriage_order':1}).status_code==200)
check('编辑拒绝与另一段次序冲突',c.put(base+f'/marriages/{m2}',json={'marriage_order':1}).status_code==400)
check('后端仍拒绝相同配偶',c.post(base+'/marriages',json={'spouse1_id':dad,'spouse2_id':dad,'marriage_order':3}).status_code==400)
with app.app_context():
    m=query_one('SELECT * FROM marriage WHERE id=?',(m1,))
check('婚姻日期规范字段',m['marriage_date_iso']=='1950-01-02' and m['marriage_date_precision']=='day')
for mother,child in [(mom1,kid1),(mom2,kid2)]:
    c.post(base+'/parentchild',json={'father_id':dad,'mother_id':mother,'children':[{'child_id':child,'father_type':1,'mother_type':1}]})
with app.app_context():
    pc={(r['parent_id'],r['child_id']) for r in query('SELECT * FROM parentchild WHERE family_id=?',(fid,))}
check('再婚孩子分别对应母亲', (mom1,kid1) in pc and (mom2,kid2) in pc and (mom1,kid2) not in pc and (mom2,kid1) not in pc)

# 父母身份按成员类型判定，候选分页和提交校验采用相同规则。
typed = {}
for kind in range(1, 7):
    typed[kind] = c.post(base+'/persons', json={
        'name':f'类型候选{kind}', 'generation':1, 'type':kind}).get_json()['data']['id']
for role, allowed in [('father_id', (1, 4, 5)), ('mother_id', (2, 3, 6))]:
    for kind, parent in typed.items():
        with app.app_context():
            before = query_one('SELECT COUNT(*) c FROM parentchild WHERE family_id=?', (fid,))['c']
        r = c.post(base+'/parentchild', json={role:parent, 'children':[{'child_id':kid1}]})
        check(f'{role} 成员类型 {kind}', r.status_code == (200 if kind in allowed else 400))
        if kind not in allowed:
            with app.app_context():
                check(f'{role} 无效类型 {kind} 不写入', query_one(
                    'SELECT COUNT(*) c FROM parentchild WHERE family_id=?', (fid,))['c'] == before)
    result = c.get(base+'/persons', query_string={
        'types':','.join(map(str, allowed)), 'keyword':'类型候选', 'size':2}).get_json()['data']
    second = c.get(base+'/persons', query_string={
        'types':','.join(map(str, allowed)), 'keyword':'类型候选', 'size':2, 'page':2}).get_json()['data']
    check(f'{role} 候选先筛选再分页', result['total']==3 and len(result['items'])==2
          and {p['type'] for p in result['items']+second['items']}==set(allowed))
check('候选类型参数拒绝非法类型', c.get(base+'/persons?types=1,7').status_code==400)
c.post(base+'/parentchild', json={'parent_id':other, 'child_id':kid1, 'type':1})
with app.app_context():
    before = query_one('SELECT COUNT(*) c FROM parentchild WHERE family_id=?', (fid,))['c']
r=c.post(base+'/parentchild', json={'father_id':other, 'mother_id':typed[4],
    'children':[{'child_id':kid2,'father_type':3}, {'child_id':kid1,'father_type':4}]})
with app.app_context():
    check('母亲类型错误整批拒绝且不更新已有关系', r.status_code==400 and query_one(
        'SELECT COUNT(*) c FROM parentchild WHERE family_id=?', (fid,))['c']==before and query_one(
        'SELECT id FROM parentchild WHERE parent_id=? AND child_id=?', (other,kid2)) is None and query_one(
        'SELECT type FROM parentchild WHERE parent_id=? AND child_id=?', (other,kid1))['type']==1)
with app.app_context():
    try:
        execute('INSERT INTO marriage(family_id,spouse1_id,spouse2_id,marriage_order,created_at,updated_at) VALUES (?,?,?,?,?,?)',(fid,dad,other,1,'x','x'))
        protected=False
    except sqlite3.IntegrityError:
        protected=True
check('数据库兜底防并发重复次序',protected)

# 真实旧库快照与幂等迁移：不删除旧重复婚姻、不推算农历。
with tempfile.TemporaryDirectory(prefix='fts_profile_migration_') as folder:
    root=Path(folder);con=sqlite3.connect(root/'old.db',isolation_level=None)
    fields={'address','phone','company','position'}
    for names in dates.DATE_FIELDS.values():
        fields.update(f+s for f in names for s in ('_iso','_precision'))
    schema=Path('server/db/schema.sql').read_text()
    schema='\n'.join(line for line in schema.splitlines() if not (line.strip().split(' ')[0] in fields))
    con.executescript(schema)
    con.execute("INSERT INTO family(id,name,slug,created_at,updated_at) VALUES (1,'旧谱','old','x','x')")
    for i,value in [(1,'1920-05-03'),(2,'甲子年'),(3,'1900')]:
        con.execute('INSERT INTO person(id,family_id,generation,name,birth_date,created_at,updated_at) VALUES (?,1,1,?,?,?,?)',(i,str(i),value,'x','x'))
    for spouse in (2,3):
        con.execute("INSERT INTO marriage(family_id,spouse1_id,spouse2_id,created_at,updated_at) VALUES (1,1,?,'x','x')",(spouse,))
    ensure_profile_fields(con,root/'backups');ensure_profile_fields(con,root/'backups')
    rows=con.execute('SELECT birth_date,birth_date_iso,birth_date_precision FROM person ORDER BY id').fetchall()
    check('旧日期原文与统计回填',rows==[('1920-05-03','1920-05-03','day'),('甲子年',None,'text'),('1900','1900','year')])
    check('迁移保留旧重复婚姻',con.execute('SELECT COUNT(*) FROM marriage').fetchone()[0]==2)
    snapshots=list((root/'backups').glob('before_profile_*.db'))
    check('迁移前快照且幂等不重复备份',len(snapshots)==1)
    with sqlite3.connect(snapshots[0]) as before:
        check('快照可读取且保留原行',before.execute('SELECT COUNT(*) FROM person').fetchone()[0]==3)
    con.close()

# 普通用户隐私规则必须覆盖新联系字段与统计日期，避免通过导出绕过。
c.put(base+f'/persons/{pid}',json={'birth_date':'1980-02-29','is_private':True})
c.post('/api/admin/users',json={'username':'profile_viewer','password':'ProfileTest123','must_change_pwd':False})
uid=c.get('/api/admin/users?keyword=profile_viewer').get_json()['data'][0]['id']
c.post(f'/api/admin/families/{fid}/members',json={'user_id':uid,'role':'member'})
v=app.test_client();v.post('/api/auth/login',json={'username':'profile_viewer','password':'ProfileTest123'})
p=v.get(base+f'/persons/{pid}').get_json()['data']
check('私有成员联系方式和规范日期脱敏',all(p[k] is None for k in [*contacts,'birth_date_iso','birth_date_precision']))
data=json.loads(c.get(base+'/export?format=json').data)
check('JSON 导出含新字段',all(next(p for p in data['persons'] if p['id']==pid)[k]==value for k,value in contacts.items()))
target=c.post('/api/admin/families',json={'name':'联系资料导入'}).get_json()['data']['id']
r=c.post(f'/api/families/{target}/import',data={'file':(io.BytesIO(json.dumps(data).encode()),'data.json')})
with app.app_context():
    p=query_one('SELECT * FROM person WHERE family_id=? AND name=?',(target,'联系成员'))
check('新字段导入往返',r.status_code==200 and all(p[k]==value for k,value in contacts.items()) and p['birth_date_iso']=='1980-02-29')
# 历史错误日期保持原文，编辑其他字段不强迫改造旧数据。
with app.app_context():
    execute('UPDATE person SET birth_date=? WHERE id=?', ('1900-00-00', pid))
r=c.put(base+f'/persons/{pid}',json={'birth_date':'1900-00-00','position':'修谱志愿者'})
check('编辑旧非标准日期不丢原文',r.status_code==200 and c.get(base+f'/persons/{pid}').get_json()['data']['birth_date']=='1900-00-00')
check('拒绝生卒区间倒置',c.post(base+'/persons',json={'name':'无效日期','generation':1,'birth_date':'2000','death_date':'1990'}).status_code==400)
# 第三方 GEDCOM 没有自定义次序时，按读入先后分配 A 的次序。
ged='\n'.join(['0 HEAD','0 @A@ INDI','1 NAME 三方A','1 SEX M','0 @B@ INDI','1 NAME 三方B','1 SEX F',
               '0 @C@ INDI','1 NAME 三方C','1 SEX F','0 @F1@ FAM','1 HUSB @A@','1 WIFE @B@',
               '0 @F2@ FAM','1 HUSB @A@','1 WIFE @C@','0 TRLR'])
r=c.post(f'/api/families/{target}/import',data={'file':(io.BytesIO(ged.encode()),'external.ged')})
with app.app_context():
    orders=[r['marriage_order'] for r in query('SELECT m.marriage_order FROM marriage m JOIN person p ON p.id=m.spouse1_id '
                                             'WHERE m.family_id=? AND p.name=? ORDER BY m.marriage_order',(target,'三方A'))]
check('第三方多段婚姻可导入且次序不重复',r.status_code==200 and orders==[1,2])
print(f'结果：通过 {len(PASS)}，失败 {len(FAIL)}')
cleanup();sys.exit(bool(FAIL))
