"""世系关系响应、亲子编辑与排行：只操作隔离临时库。"""
import io,json,sqlite3,sys,tempfile
from pathlib import Path
from _testenv import bootstrap,assert_isolated,relax_bootstrap_admin,cleanup
bootstrap('pedigree')
from server.app import app
from server.db.conn import query,query_one,execute
assert_isolated(app);relax_bootstrap_admin(app)
c=app.test_client();c.post('/api/auth/login',json={'username':'admin','password':'admin123'})
c.put('/api/admin/settings',json={'security.rate_limit_per_minute':10000})
checks=[]
def check(name,condition):
    assert condition,name
    checks.append(name);print('PASS',name)
fid=c.post('/api/admin/families',json={'name':'家庭布局验收'}).json['data']['id'];base=f'/api/families/{fid}'
def person(name,kind,birth=''):
    return c.post(base+'/persons',json={'name':name,'generation':1 if kind in (3,4) else 2,'type':kind,'birth_date':birth}).json['data']['id']
dad=person('父亲',4);mom=person('母亲',3);a=person('较晚出生的长女',2,'2005-01-01');b=person('较早出生的次子',1,'2000-01-01');unknown=person('生日不详',1)
c.post(base+'/marriages',json={'spouse1_id':dad,'spouse2_id':mom,'marriage_order':1})
r=c.post(base+'/parentchild',json={'father_id':dad,'mother_id':mom,'children':[{'child_id':a,'father_type':1,'mother_type':3,'child_order':1},{'child_id':b,'child_order':2},{'child_id':unknown}]})
check('男女统一手工排行可保存',r.status_code==200)
pcs=c.get(base+'/parentchild').json['data'];first=next(p for p in pcs if p['parent_id']==dad and p['child_id']==a)
check('排行由人工确认，不按生日覆写',first.get('child_order')==1)
check('生日不详不编造排行',all(p.get('child_order') is None for p in pcs if p['child_id']==unknown))
s=c.get(base+'/pedigree').json['data']
check('世系返回婚姻次序和亲子类型与排行',s['marriages'][0]['marriage_order']==1 and any(e['type']==3 and e['child_order']==1 for e in s['parentchild']))
check('世系旧节点结构保留',all(k in s['nodes'][0] for k in ('parents','children','spouses')))
r=c.put(base+f'/parentchild/{first["id"]}',json={'parent_id':mom,'parent_role':'father','child_id':a,'type':1})
check('编辑父亲拒绝女性类型',r.status_code==400)
r=c.put(base+f'/parentchild/{first["id"]}',json={'parent_id':dad,'parent_role':'father','child_id':b,'type':1})
check('编辑不能生成重复亲子关系',r.status_code==400)
r=c.put(base+f'/parentchild/{first["id"]}',json={'child_order':2})
check('同一父母下排行不能重复',r.status_code==400)
r=c.put(base+f'/parentchild/{first["id"]}',json={'type':4,'description':'经核对为继养','child_order':3})
check('编辑关系类型说明及排行',r.status_code==200 and next(p for p in c.get(base+'/parentchild').json['data'] if p['id']==first['id'])['child_order']==3)
r=c.put(base+f'/parentchild/{first["id"]}',json={'parent_id':a,'child_id':mom})
check('编辑仍拒绝亲属环',r.status_code==400)
check('非法排行被拒绝',c.put(base+f'/parentchild/{first["id"]}',json={'child_order':0}).status_code==400)
check('排行可以清空',c.put(base+f'/parentchild/{first["id"]}',json={'child_order':None}).status_code==200)
r=c.post(base+'/parentchild',json={'father_id':dad,'children':[{'child_id':a,'child_order':4},{'child_id':unknown,'child_order':2}]})
check('批量排行冲突整批回滚',r.status_code==400 and next(p for p in c.get(base+'/parentchild').json['data'] if p['id']==first['id'])['child_order'] is None)
# 独立谱和未登录隔离。
other=c.post('/api/admin/families',json={'name':'外谱'}).json['data']['id']
check('外谱编辑被拒绝',c.put(f'/api/families/{other}/parentchild/{first["id"]}',json={'description':'wrong'}).status_code in (400,403,404))
check('未登录不能读取关系',app.test_client().get(base+'/pedigree').status_code==401)
check('未登录不能编辑',app.test_client().put(base+f'/parentchild/{first["id"]}',json={'type':2}).status_code==401)
# 导出导入保留排行；JSON 和 GEDCOM 自定义扩展都不能丢失。
for fmt in ('json','gedcom'):
    raw=c.get(base+f'/export?format={fmt}').data
    if fmt=='gedcom':
        import zipfile
        z=zipfile.ZipFile(io.BytesIO(raw));raw=z.read(z.namelist()[0])
    target=c.post('/api/admin/families',json={'name':'导入排行'+fmt}).json['data']['id']
    result=c.post(f'/api/families/{target}/import',data={'file':(io.BytesIO(raw),'data.'+('ged' if fmt=='gedcom' else 'json'))})
    got=c.get(f'/api/families/{target}/parentchild').json['data']
    check(fmt+' 排行保真',result.status_code==200 and any(p.get('child_order')==2 for p in got))
bad=json.loads(c.get(base+'/export?format=json').data)
next(p for p in bad['parentchild'] if p['parent_id']==dad and p['child_id']==a)['child_order']=2
target=c.post('/api/admin/families',json={'name':'无效排行导入'}).json['data']['id']
r=c.post(f'/api/families/{target}/import',data={'file':(io.BytesIO(json.dumps(bad).encode()),'bad.json')})
check('导入重复排行整批回滚',r.status_code==400 and c.get(f'/api/families/{target}/persons').json['data']['total']==0)
# 模拟上一版库缺列，增量迁移不修改原有记录，且生成可读取备份。
from server.db.migrate import ensure_child_order
with tempfile.TemporaryDirectory(prefix='fts_order_migration_') as d:
    path=Path(d);con=sqlite3.connect(path/'old.db',isolation_level=None)
    con.executescript('CREATE TABLE parentchild(id INTEGER PRIMARY KEY,family_id INTEGER,parent_id INTEGER,child_id INTEGER); INSERT INTO parentchild VALUES(1,1,2,3);')
    ensure_child_order(con,path/'backups');ensure_child_order(con,path/'backups')
    check('旧库补列且原记录不变',con.execute('SELECT * FROM parentchild').fetchone()==(1,1,2,3,None))
    snapshots=list((path/'backups').glob('before_child_order_*.db'))
    check('排行迁移有备份且幂等',len(snapshots)==1 and sqlite3.connect(snapshots[0]).execute('SELECT COUNT(*) FROM parentchild').fetchone()[0]==1)
    con.close()
print(f'亲子/世系检查：{len(checks)} 项通过');cleanup()
