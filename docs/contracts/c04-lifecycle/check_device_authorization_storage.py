"""九表授权采用的逐写、漏写、一次消费及双连接竞争验证。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from jsonschema.exceptions import ValidationError
import check_device_authorization as F
import device_authorization_storage_model as S
M=S.M;HERE=S.HERE;ROOT=HERE.parents[2]
def inputs():return list(dict.fromkeys(F.inputs()+[HERE/n for n in ('device-authorization-storage.sql','device_authorization_storage_model.py','check_device_authorization_storage.py','DEVICE_AUTHORIZATION_STORAGE.md')]))
def fresh():
    db=sqlite3.connect(':memory:',isolation_level=None);db.execute('PRAGMA foreign_keys=ON');S.install(db);return db
def tx(db,fn):
    db.execute('BEGIN IMMEDIATE')
    try:v=fn();db.commit();return v
    except BaseException:db.rollback();raise
def fixtures(db):
    initial,state,evidence=F.fixture();context=state['context'];binding=evidence['requirement']['binding']
    init,w=S.apply(db,'initialize',dict(kind='initialize',context=context),'5')
    revalidation=dict(kind='revalidate',expected=init['after'],context=context,authorization=F.recovery(initial,binding),binding=binding)
    return initial,state,evidence,init,revalidation
def all_rows(db):return {r[0]:list(db.execute('SELECT * FROM '+r[0]+' ORDER BY rowid')) for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name LIKE 'da_%' ORDER BY name")}
def run():
    checks=[];connections=[]
    def check(name,condition=True):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error) as e:check(name,reason is None or reason in str(e));return
        raise AssertionError('未拒绝:'+name)
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');connections.append(c);return c
    try:
        db=fresh();connections.append(db);initial,state,e,init,revalidate=fixtures(db);context=state['context'];scope=context['scope'];device=context['device_id']
        check('九表完整安装',len(all_rows(db))==9)
        pre=fork(db);accepted,writes=S.apply(db,'recover',revalidate,'10')
        check('恢复授权与State一致采用',accepted['after']['state_ref']==M.reference(state,'state') and len(writes)==8)
        check('恢复只消费一次',db.execute('SELECT count(*) FROM da_consumption').fetchone()[0]==1)
        check('同键重投查原且不延长窗口',S.apply(db,'recover',revalidate,'999')[0]==accepted)
        bad=copy.deepcopy(revalidate);bad['authorization']['operation_id']='other';denied('同键异内容拒绝',lambda:S.apply(db,'recover',bad,'10'),'storage_request_conflict')
        denied('不同键不能重复恢复旧状态',lambda:S.apply(db,'recover.again',revalidate,'10'),'storage_head_cas')
        select=dict(kind='select',expected=accepted['after'],evidence=e);before_select=fork(db);selected,selection_writes=S.apply(db,'select',select,'10')
        for field in ('worker_boot_id','controller_boot_id','device_session_id','ipc_session_id','writer_exit_id','descriptor_digest'):
            c=fork(before_select);bad=copy.deepcopy(select);b=bad['evidence']['requirement']['binding'];b[field]=M.R.digest('other') if field=='descriptor_digest' else 'other'
            M.R.seal(bad['evidence']['requirement']);bad['evidence']=M.seal(bad['evidence'],'evidence_digest')
            denied('首次取证不能跨恢复授权绑定/'+field,lambda:S.apply(c,'wrong.binding',bad,'10'),'storage_recovery_binding')
        check('首次取证形成当前选择',selected['after']['evidence_ref']==M.reference(e,'evidence') and len(selection_writes)==6)
        refresh=dict(kind='select',expected=selected['after'],evidence=F.refreshed(e));before_refresh=fork(db);renewed,_=S.apply(db,'refresh',refresh,'15')
        check('刷新不变授权修订但推进选择',renewed['after']['state_ref']==selected['after']['state_ref'] and int(renewed['after']['generation'])==int(selected['after']['generation'])+1)
        protect=dict(kind='protect',expected=selected['after'],context=context,reasons=['revoked']);before_protect=fork(db);protected,protection_writes=S.apply(db,'protect',protect,'16')
        check('保护不被更早刷新阻挡',protected['before']==renewed['after'] and protected['after']['evidence_ref'] is None and len(protection_writes)==6)
        check('保护推进授权修订',protected['after']['state_ref']['revision']=='3')
        denied('保护后旧刷新拒绝',lambda:S.apply(db,'refresh.late',refresh,'17'),'storage_head_cas')
        for oid,record in [('initialize',init),('recover',accepted),('select',selected),('refresh',renewed),('protect',protected)]:
            check('历史提交及完整交付查原/'+oid,tx(db,lambda:S.read_commit(db,oid))==record)
        check('保护后旧请求重投只查原',S.apply(db,'refresh',refresh,'1000')[0]==renewed and tx(db,lambda:S.head(db,scope,device))==protected['after'])
        # 每类写集的每一步主动异常及漏写均比较全九表。
        cases=[('initialize',fresh(),dict(kind='initialize',context=context),'5',['state','head','commit','audit','outbox','seal']),
            ('recover',pre,revalidate,'10',writes),('select',before_select,select,'10',selection_writes),('refresh',before_refresh,refresh,'15',selection_writes),('protect',before_protect,protect,'16',protection_writes)]
        connections.append(cases[0][1])
        for label,template,request,now,steps in cases:
            for step in steps:
                for knob in ('fail_after','omit'):
                    c=fork(template);before=all_rows(c)
                    denied(label+'/'+knob+'/'+step,lambda:S.apply(c,label,request,now,**{knob:step}))
                    check('全库保持/'+label+'/'+knob+'/'+step,all_rows(c)==before and not c.in_transaction)
            c=fork(template);before=all_rows(c);denied('COMMIT前故障/'+label,lambda:S.apply(c,label,request,now,commit_fault='before'))
            check('COMMIT前回滚/'+label,all_rows(c)==before)
            c=fork(template);denied('COMMIT后观察丢失/'+label,lambda:S.apply(c,label,request,now,commit_fault='after'))
            original=tx(c,lambda:S.read_commit(c,label));check('COMMIT后查原/'+label,S.apply(c,label,request,'999')[0]==original)
        c=fork(before_refresh);bad=copy.deepcopy(refresh);bad['expected']['evidence_ref']=None
        denied('不能谎称当前没有旧证据',lambda:S.apply(c,'omit.previous',bad,'15'),'storage_head_cas')
        denied('到期后新证据不能作为首次选择',lambda:S.apply(c,'expired.refresh',refresh,'20'),'requirement_window')
        for sql in ('DELETE FROM da_head','UPDATE da_head SET evidence_id=NULL,generation=\'00000000000000000999\'','DELETE FROM da_evidence','UPDATE da_consumption SET state_id=state_id'):
            denied('SQL不允许清空当前或改消费/'+sql,lambda:tx(c,lambda:c.execute(sql)))
        expire=dict(kind='protect',expected=selected['after'],context=context,reasons=['evidence_expired']);expired,_=S.apply(c,'expire',expire,'20')
        bad=dict(kind='select',expected=expired['after'],evidence=F.refreshed(e));denied('已保护不接受单独有效的新证据',lambda:S.apply(c,'resurrect',bad,'20'),'state_protected')
        # 两个实际连接分别按顺序提交，另测持锁排他；不称为多进程验收。
        for mode in ('DELETE','WAL'):
            with tempfile.TemporaryDirectory(prefix='leafseamer-device-auth-') as directory:
                path=Path(directory)/'state.sqlite';left=sqlite3.connect(path,isolation_level=None);before_refresh.backup(left);left.execute('PRAGMA journal_mode='+mode);right=sqlite3.connect(path,isolation_level=None,timeout=0)
                try:
                    for x in (left,right):x.execute('PRAGMA foreign_keys=ON')
                    winner,_=S.apply(left,'winner',refresh,'15');other=copy.deepcopy(refresh);other['evidence']['evidence_id']='other';other['evidence']=M.seal(other['evidence'],'evidence_digest')
                    denied(mode+'两次刷新只有一个旧选择CAS成功',lambda:S.apply(right,'loser',other,'15'),'storage_head_cas')
                    closed,_=S.apply(right,'revoke',protect,'16');check(mode+'刷新先提交仍被撤权覆盖',closed['before']==winner['after'] and closed['after']['evidence_ref'] is None)
                    denied(mode+'撤权先提交后刷新拒绝',lambda:S.apply(left,'late',refresh,'17'),'storage_head_cas')
                    left.execute('BEGIN IMMEDIATE');denied(mode+'持锁时第二writer不能写',lambda:S.apply(right,'locked',refresh,'18'));left.rollback()
                    if mode=='WAL':
                        left.execute('BEGIN');h=S.head(left,scope,device);check('WAL旧读仅查元数据',h==closed['after'])
                        denied('不接受外部旧读事务作为writer',lambda:S.apply(left,'external',refresh,'18'),'storage_writer_connection');left.rollback()
                finally:left.close();right.close()
        for c in connections:check('连接事务和外键完整',not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone())
        return dict(all_passed=True,approved=False,cases_passed=len(checks),candidate_tables=9,checks=checks,
            local_adoption_atomicity_verified=True,revalidation_single_consumption_verified=True,selection_cas_verified=True,protection_over_refresh_verified=True,
            authority_sources_verified=False,full_controller_integration_verified=False,protection_ipc_executed=False,full_open_verified=False,device_tests_executed=0,
            inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
    finally:
        for c in dict.fromkeys(connections):c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'device-authorization-storage-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,inputs=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(S.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
