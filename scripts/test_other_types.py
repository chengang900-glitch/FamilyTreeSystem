"""其他（男/女）：登记、关系、导入导出、付印排除及旧库迁移。仅使用隔离库。"""
import io,json,sqlite3,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch
from _testenv import bootstrap,cleanup,relax_bootstrap_admin,assert_isolated
bootstrap('other_types')
try:
    from server.app import app
    from server.db.conn import query
    assert_isolated(app);relax_bootstrap_admin(app)
    c=app.test_client();c.post('/api/auth/login',json={'username':'admin','password':'admin123'})
    c.put('/api/admin/settings',json={'security.rate_limit_per_minute':10000})
    fid=c.post('/api/admin/families',json={'name':'其他类型验收'}).json['data']['id'];base=f'/api/families/{fid}'
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name);print('PASS',name)
    ids={}
    for t in [1,3,5,6,7,8]:
        r=c.post(base+'/persons',json={'name':f'验收成员{t}','generation':1 if t in [1,3,5,6] else 2,'type':t})
        check(f'创建类型{t}',r.status_code==200);ids[t]=r.json['data']['id']
    for t in [0,9,-1]:check(f'拒绝类型{t}',c.post(base+'/persons',json={'name':'无效','generation':1,'type':t}).status_code==400)
    check('编辑其他类型',c.put(base+f'/persons/{ids[7]}',json={'type':8}).status_code==200 and c.put(base+f'/persons/{ids[7]}',json={'type':7}).status_code==200)
    check('筛选其他类型',c.get(base+'/persons?types=7,8').json['data']['total']==2)
    for child in [7,8]:check(f'外孙登记其他子女{child}',c.post(base+'/parentchild',json={'father_id':ids[5],'children':[{'child_id':ids[child]}]}).status_code==200)
    check('其他男作为父亲',c.post(base+'/parentchild',json={'father_id':ids[7],'children':[{'child_id':ids[1]}]}).status_code==200)
    check('其他女作为母亲',c.post(base+'/parentchild',json={'mother_id':ids[8],'children':[{'child_id':ids[1]}]}).status_code==200)
    check('父母性别不能颠倒',c.post(base+'/parentchild',json={'father_id':ids[8],'children':[{'child_id':ids[3]}]}).status_code==400)
    check('世系图保留其他',any(n['type']==8 for n in c.get(base+'/pedigree').json['data']['nodes']))
    for fmt in ['json','gedcom']:
        raw=c.get(base+'/export?format='+fmt).data
        if fmt=='gedcom':
            z=zipfile.ZipFile(io.BytesIO(raw));raw=z.read(z.namelist()[0])
            from server.service.gedcom import loads
            people,_=loads(raw.decode());check('GEDCOM男女保留',next(p for p in people if p['type']==7)['name']=='验收成员7' and '1 SEX M' in raw.decode())
        target=c.post('/api/admin/families',json={'name':'往返'+fmt}).json['data']['id']
        r=c.post(f'/api/families/{target}/import',data={'file':(io.BytesIO(raw),'members.'+('ged' if fmt=='gedcom' else 'json'))})
        check(fmt+'导入保留两类其他',r.status_code==200 and c.get(f'/api/families/{target}/persons?types=7,8').json['data']['total']==2)
    # 其他配偶不能通过附注进入付印。
    c.post(base+'/marriages',json={'spouse1_id':ids[3],'spouse2_id':ids[7],'marriage_order':1})
    from server.blueprint import print_bp
    with app.app_context():
        for template in ['original','traditional','european','compilation']:
            fam,items,pmap,children,spouses=print_bp._load(fid,None,'lineage',0)
            text='\n'.join(str(t) for _,t in print_bp._lines(fam,items,pmap,children,spouses,{'template':template,'include_spouse':True,'include_children':True}))
            check(template+'正文及亲属附注排除其他',len(items)==4 and '验收成员7' not in text and '验收成员8' not in text)
    for endpoint in ['estimate','pdf','docx']:
        check(endpoint+'拒绝其他主人物',c.post(base+'/print/'+endpoint,json={'mode':'person','root_id':ids[7]}).status_code==400)
    r=c.post(base+'/print/estimate',json={'mode':'lineage','include_spouse':True,'include_children':True})
    check('付印估算排除其他',r.status_code==200 and r.json['data']['persons']==4)
    r=c.post(base+'/print/docx',json={'mode':'lineage','include_spouse':True,'include_children':True})
    xml=zipfile.ZipFile(io.BytesIO(r.data)).read('word/document.xml').decode()
    check('实际Word排除其他',r.status_code==200 and '验收成员7' not in xml and '验收成员8' not in xml)
    from pypdf import PdfReader
    for template in ['original','traditional','european','compilation']:
        options={'mode':'lineage','template':template,'add_cover':False,'include_spouse':True,'include_children':True}
        pdf=c.post(base+'/print/pdf',json=options)
        text=''.join(''.join((page.extract_text() or '').split()) for page in PdfReader(io.BytesIO(pdf.data)).pages)
        check(template+'实际PDF及预览排除其他',pdf.status_code==200 and '验收成员5' in text and '验收成员7' not in text and '验收成员8' not in text)
        estimate=c.post(base+'/print/estimate',json=options)
        check(template+'估算人数一致',estimate.status_code==200 and estimate.json['data']['persons']==4)
    word=c.post(base+'/print/docx',json={'mode':'lineage','template':'compilation','include_spouse':True,'include_children':True})
    xml=zipfile.ZipFile(io.BytesIO(word.data)).read('word/document.xml').decode()
    check('汇编Word排除其他',word.status_code==200 and '验收成员7' not in xml and '验收成员8' not in xml)
    from server.db.migrate import ensure_person_types
    schema=(Path(__file__).resolve().parents[1]/'server/db/schema.sql').read_text().replace('CHECK (type BETWEEN 1 AND 8)','CHECK (type BETWEEN 1 AND 6)',1)
    with tempfile.TemporaryDirectory(prefix='fts_other_migration_') as folder:
        folder=Path(folder);con=sqlite3.connect(folder/'old.db',isolation_level=None);con.executescript(schema)
        con.execute("INSERT INTO family(id,name,slug,created_at,updated_at) VALUES(1,'旧谱','old','x','x')")
        con.execute("INSERT INTO person(id,family_id,generation,name,type,notes,created_at,updated_at) VALUES(1,1,1,'原成员',5,'原备注','x','x')")
        con.execute('CREATE INDEX custom_person_name ON person(name)')
        con.execute("CREATE TRIGGER custom_person_trigger AFTER UPDATE OF notes ON person BEGIN SELECT 1; END")
        con.execute("UPDATE sqlite_sequence SET seq=500 WHERE name='person'")
        before=con.execute('SELECT * FROM person').fetchall();foreign=con.execute('PRAGMA foreign_key_list(person)').fetchall()
        ensure_person_types(con,folder/'backups')
        check('旧库原字段值不变',con.execute('SELECT * FROM person').fetchall()==before)
        check('保留外键',con.execute('PRAGMA foreign_key_list(person)').fetchall()==foreign and not con.execute('PRAGMA foreign_key_check').fetchall())
        check('保留自定义索引触发器',con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('custom_person_name','custom_person_trigger')").fetchone()[0]==2)
        check('保留自增高水位',con.execute("SELECT seq FROM sqlite_sequence WHERE name='person'").fetchone()[0]==500)
        con.execute("INSERT INTO person(family_id,generation,name,type,created_at,updated_at) VALUES(1,2,'新其他',8,'x','x')")
        check('迁移后其他可入库且ID不复用',con.execute("SELECT id FROM person WHERE name='新其他'").fetchone()[0]==501)
        snapshots=list((folder/'backups').glob('before_person_types_*.db'));ensure_person_types(con,folder/'backups')
        check('迁移幂等',len(list((folder/'backups').glob('*.db')))==len(snapshots)==1)
        old=sqlite3.connect(snapshots[0]);check('旧库快照可读',old.execute('SELECT name,type FROM person').fetchall()==[('原成员',5)]);old.close()
        con.close()
        bad=sqlite3.connect(folder/'bad.db',isolation_level=None);bad.executescript(schema);bad.execute('PRAGMA foreign_keys=OFF')
        bad.execute("INSERT INTO person(family_id,generation,name,type,created_at,updated_at) VALUES(999,1,'坏引用',1,'x','x')");bad.execute('PRAGMA foreign_keys=ON')
        try:ensure_person_types(bad,folder/'bad-backup');failed=False
        except RuntimeError:failed=True
        check('迁移异常回滚且恢复外键开关',failed and '1 AND 6' in bad.execute("SELECT sql FROM sqlite_master WHERE name='person'").fetchone()[0] and bad.execute('PRAGMA foreign_keys').fetchone()[0]==1 and bad.execute('SELECT COUNT(*) FROM person').fetchone()[0]==1)
        bad.close()
    print(f'其他类型检查：{len(passed)} 项通过')
finally:cleanup()
