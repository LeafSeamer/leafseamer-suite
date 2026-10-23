"""完整组合布局中的两侧签发/采用/R5实验；不证明普通触发或真实设备恢复。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import continuation_storage_model as M
import check_source_resync as S
import check_continuation as V
import check_control_storage as U
import check_layout as L
import check_fence as FENCE
G=M.G;P=M.P;R=M.R;I=M.I;C=S.C;AT=S.AT;W=S.W;RB=S.RB;PRE=L.PREP
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(S.INPUTS+G.SOURCES+V.INPUTS+[Path(U.__file__),Path(L.__file__),Path(PRE.__file__),Path(FENCE.__file__)]+[HERE/n for n in
    ('continuation_storage_model.py','check_continuation_storage.py','CONTINUATION_STORAGE.md')]))

def ref(sc,ident,digest=None,revision='1'):return dict(scope=sc,id=ident,revision=revision,digest=digest or M.M.digest(ident))
def alter(steps,changes):
    result=[]
    for sql,args in steps:
        table=sql.split()[2].split('(')[0];fields=sql.split('(',1)[1].split(')',1)[0].split(',');values=dict(zip((f.strip() for f in fields),args))
        values.update(changes.get(table,{}));result.append(I(table,**values))
    return result

def controller_seed(p):
    d=sqlite3.connect(':memory:',isolation_level=None);d.row_factory=sqlite3.Row
    d.execute('PRAGMA foreign_keys=ON');d.execute('PRAGMA recursive_triggers=ON');d.executescript(G.controller_sql().decode())
    sc=dict(authority_service_id=p['controller_authority'],database_instance_id=p['controller_database'])
    d.execute('INSERT INTO controller_scope VALUES(1,?,?,?)',(*M.M.scope_key(sc),'controller-storage/0.1.0-draft.1'));d.execute('INSERT INTO cr_limit VALUES(1,8)')
    for steps in (PRE.register(preparation=p['preparation_id'],generation=p['generation'],run=p['run_id']),PRE.change()):
        C.execute(d,alter(steps,dict(cp_request=dict(origin_database='db',mode='recovery',execution_id=p['execution_id'],request_digest=p['request_digest'],request_body=p['request_body']),
            cp_receipt=dict(request_digest=p['request_digest']))))
    devices=[]
    for dev in ('dev.1','dev.2'):
        steps=[]
        for table,value in U.bootstrap(d,holder=None):
            value={k:(v.replace('base','base.'+dev) if isinstance(v,str) else v) for k,v in value.items()}
            if table=='ct_change':value['device_id']=dev
            steps.append(I(table,**value))
        C.execute(d,steps)
        devices.append(dict(device_id=dev,control_ref=ref(sc,'base.'+dev,U.DIGEST),authorization_ref=ref(sc,'authorization.'+dev),action_set_ref=ref(sc,'actions.'+dev)))
    t=dict(controller_scope=sc,preparation_ref=ref(sc,p['preparation_id'],p['request_digest']),recovery_grant_ref=ref(sc,'grant.p',PRE.DIGEST),devices=devices)
    return d,t

def fixture():
    d,oldq,ctx,ts=S.T.fixture(sql_factory=G.seamer_sql)
    d.execute('INSERT INTO rc_limit VALUES(1,8)');d.execute("INSERT INTO rs_limit VALUES(1,'simulation',64,8)")
    ctx.update(delivery_current=True,delivery_ref=S.ref('delivery'),snapshot_verified=True,snapshot_ref=S.ref('snapshot'),continuity_verified=True,
        event_ref=S.ref('event.11'),checkpoint_verified=True,checkpoint_ref=S.ref('checkpoint'))
    S.B.protect(d,C.fault('1'),ctx)
    for kind in ('baseline','delta','ready'):S.M.apply(d,S.request(d,ctx,kind),ctx)
    rq,rc=W.recovery(d,ctx,ts);rq['resolved_latches']=[x[0] for x in d.execute('SELECT latch_id FROM pause_latch WHERE cleared_start_id IS NULL')]
    RB.M.reserve(d,rq,rc);RB.prepared(d,rq);S.observe(d);R.apply(d,lambda:R.start_steps(d,rq['operation_id'],rc))
    C.execute(d,R.event('terminal','r0','STEP_TERMINAL')+[
        I('step_terminal',terminal_id='terminal',execution_id=rq['execution_id'],step_id='step',run_id='r0',outcome='succeeded',evidence_body=AT.B,result_ref_body=AT.B,tx_id='terminal.STEP_TERMINAL'),
        ("UPDATE step_state SET state='finished',outcome='succeeded',terminal_id='terminal',revision='2' WHERE execution_id=?",(rq['execution_id'],))])
    q,a,receipts,s,cs,cmd=V.fixture();cds={};targets=[]
    for p in P.rows(d,"SELECT * FROM p1_preparation WHERE generation='2' ORDER BY controller_authority,controller_database"):
        cd,t=controller_seed(p);targets.append(t);cds[M.M.scope_key(t['controller_scope'])]=(cd,None)
    sc=dict(authority_service_id='seamer',database_instance_id='db')
    q=M.M.seal(dict(q,origin_scope=sc,run_id='r0',generation='2',recovery_operation_id=rq['operation_id'],recovery_execution_id=rq['execution_id'],
        continuation_plan_ref=ref(sc,'continued.plan'),approval_ref=ref(sc,'continued.approval'),targets=targets),'request_digest')
    template=next(iter(cs.values()))
    for t in targets:
        key=M.M.scope_key(t['controller_scope']);cd,_=cds[key]
        cc=dict(template,read_authorized=True,scope=t['controller_scope'],origin_scope=sc,run_id='r0',generation='2',recovery_execution_id=q['recovery_execution_id'],
            preparation_ref=t['preparation_ref'],recovery_grant_ref=t['recovery_grant_ref'],devices=t['devices'],plan_ref=q['continuation_plan_ref'],
            approval_ref=q['approval_ref'],approval_subject=M.M.approval_subject(q),qualification_ref=ref(t['controller_scope'],'qualification'))
        cds[key]=(cd,cc)
    s.update(binding={k:q[k] for k in s['binding']},required_targets=copy.deepcopy(targets),approval_ref=q['approval_ref'],approval_subject=M.M.approval_subject(q),
        required_evidence=True,no_unresolved=True)
    s=M.seamer_snapshot(d,q,s)
    return d,q,s,cds,ctx

def issued(d,q,s,cds):
    M.register(d,q,s);rs=[]
    for t in q['targets']:
        cd,cc=cds[M.M.scope_key(t['controller_scope'])];r=M.issue(cd,q,t,cc)
        M.tx(d,lambda:M.receive_steps(d,q,r,cd,cc));rs.append(r)
    proof=dict(operation_id=q['recovery_operation_id'],execution_id=q['recovery_execution_id'],request_digest=q['request_digest'],receipt_refs=[M.M.receipt_ref(r) for r in rs],
        resources_clear=True,retained_parent_refs=[t['preparation_ref'] for t in q['targets']])
    proof['ref']=ref(V.scope('supervisor'),'release',M.M.digest(proof));s['release_proof']=proof
    a=M.M.seal(dict(**M.common(q),request_digest=q['request_digest'],adoption_id='adoption',revision='1',
        expected_run_revision=s['run_revision'],expected_slot_revision=s['slot_revision'],expected_operation_revision=s['operation_revision'],
        receipt_refs=proof['receipt_refs'],release_proof_ref=proof['ref']),'adoption_digest')
    return a,rs

def run():
    checks=[];dbs=[]
    def check(n,value=True):assert value,n;checks.append(dict(name=n,passed=True))
    def fresh():
        value=fixture();dbs.append(value[0]);dbs.extend(v[0] for v in value[3].values());return value
    def denied(n,db,call,reason=None):
        before=C.snapshot(db)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,C.snapshot(db)==before);return
        raise AssertionError(n+':应拒绝')
    def atomic(n,db,builder):
        steps=AT.planned(db,builder)
        for i in range(len(steps)):
            if len(steps)>1:denied(n+'缺写'+str(i),db,lambda i=i:C.execute(db,steps[:i]+steps[i+1:]))
            else:
                before=C.snapshot(db);C.execute(db,[]);check(n+'省略唯一写入无副作用',C.snapshot(db)==before)
            denied(n+'写后异常'+str(i),db,lambda i=i:M.tx(db,builder,fail_after=i),'injected')
        return steps
    try:
        d,q,s,cds,ctx=fresh();check('Seamer117表',len(C.snapshot(d))==117)
        atomic('转交请求',d,lambda:M.request_steps(d,q,s));M.register(d,q,s);before=C.snapshot(d)
        check('同请求查原',M.register(d,q,dict(s,write_authorized=False))=='existing' and C.snapshot(d)==before)
        denied('同代换身份',d,lambda:M.register(d,M.M.seal(dict(q,transfer_id='different'),'request_digest'),s),'identity_conflict')
        t=q['targets'][0];cd,cc=cds[M.M.scope_key(t['controller_scope'])];check('Controller235表',len(C.snapshot(cd))==235)
        original={k:v for k,v in C.snapshot(cd).items() if k.startswith('cp_')}
        atomic('Controller签发',cd,lambda:M.issue_steps(cd,q,t,cc));r=M.issue(cd,q,t,cc)
        check('旧准备与grant字节保持',original=={k:v for k,v in C.snapshot(cd).items() if k.startswith('cp_')})
        before=C.snapshot(cd);check('响应丢失查原',M.issue(cd,q,t,dict(cc,write_authorized=False))==r and C.snapshot(cd)==before)
        atomic('回执观测',d,lambda:M.receive_steps(d,q,r,cd,cc));M.tx(d,lambda:M.receive_steps(d,q,r,cd,cc))
        d,q,s,cds,ctx=fresh();a,rs=issued(d,q,s,cds)
        atomic('完整采用',d,lambda:M.adoption_steps(d,q,a,s,cds));M.tx(d,lambda:M.adoption_steps(d,q,a,s,cds))
        before=C.snapshot(d);check('采用响应丢失查原',M.adopt(d,q,a,dict(s,write_authorized=False),cds)=='existing' and C.snapshot(d)==before)
        steps=atomic('R5',d,lambda:M.r5_steps(d,q,s,cds));M.finish(d,q,s,cds)
        before=C.snapshot(d);check('R5响应丢失不重跑动作',M.finish(d,q,dict(s,write_authorized=False),cds)=='existing' and C.snapshot(d)==before)
        check('R5回armed',tuple(d.execute('SELECT lifecycle,arm_generation,active_execution_id FROM run').fetchone())==('armed','2',None))
        check('恢复锁精确释放',d.execute('SELECT release_id FROM recovery_lock').fetchone()[0]=='transfer.release')
        check('R5保存采用引用',d.execute('SELECT adoption_digest FROM rc_r5_link').fetchone()[0]==a['adoption_digest'])
        denied('普通trigger尚未联接不能偷用旧准备',d,lambda:W.execute(d,ctx,12),'resync_plan_target_unprepared')
        for table in G.ST:
            denied('Seamer历史不可删'+table,d,lambda table=table:C.execute(d,[('DELETE FROM '+table,())]),'immutable_continuation')
        # 两库并非一个事务：Controller签发后Seamer采用失败不删除远端已提交原件。
        d,q,s,cds,ctx=fresh();a,rs=issued(d,q,s,cds);before=[C.snapshot(v[0]) for v in cds.values()]
        denied('失效审批不采用',d,lambda:M.tx(d,lambda:M.adoption_steps(d,q,a,dict(s,approval_current=False),cds)),'approval')
        check('采用失败远端原件保留',before==[C.snapshot(v[0]) for v in cds.values()])
        for field in ('expected_run_revision','expected_slot_revision','expected_operation_revision'):
            bad=M.M.seal(dict(a,**{field:'999'}),'adoption_digest')
            denied('采用CAS'+field,d,lambda bad=bad:M.tx(d,lambda:M.adoption_steps(d,q,bad,s,cds)),'adoption_cas')
        # SQL不以关系模型成功代替完整原件和最后seal。
        writes=AT.planned(d,lambda:M.adoption_steps(d,q,a,s,cds))
        denied('SQL错采用摘要',d,lambda:C.execute(d,C.mutate(writes,'rc_adoption_commit',dict(adoption_digest='wrong'))),'continuation_adoption_seal')
        for field,value in [('origin_scope',V.scope('other')),('generation','3'),('recovery_execution_id','other')]:
            bad=M.M.seal(dict(a,**{field:value}),'adoption_digest')
            changed=C.mutate(writes,'rc_adoption',dict(adoption_body=M.raw(bad),adoption_digest=bad['adoption_digest']))
            changed=C.mutate(changed,'rc_adoption_commit',dict(adoption_digest=bad['adoption_digest']))
            denied('SQL重摘要采用错绑'+field,d,lambda changed=changed:C.execute(d,changed),'continuation_request_binding')
        first=M.M.scope_key(q['targets'][0]['controller_scope']);cd,cc=cds[first]
        C.execute(cd,[I('cr_revocation',transfer_id=q['transfer_id'],proof_body=AT.B,audit_body=AT.B,outbox_body=AT.B)])
        check('撤权立即退出当前资格',cd.execute('SELECT count(*) FROM cr_current').fetchone()[0]==0)
        check('撤权后仍可查原',M.issue(cd,q,q['targets'][0],cc)==rs[0])
        denied('撤权后拒绝采用',d,lambda:M.tx(d,lambda:M.adoption_steps(d,q,a,s,cds)),'preparation_denied')
        # 发起签发前关闭与采用后关闭，都通过原cp_close/RUN_DENY；没有删除任何守卫。
        for after in (False,True):
            d,q,s,cds,ctx=fresh();first=M.M.scope_key(q['targets'][0]['controller_scope']);cd,cc=cds[first]
            if after:
                a,rs=issued(d,q,s,cds);M.tx(d,lambda:M.adoption_steps(d,q,a,s,cds))
            p=R.one(cd,'cp_request','prep_key','p')
            close=alter(L.prep_steps(FENCE.fence(source='close',targets=(),items=(),revision=0)),
                dict(cp_close=dict(request_digest=p['request_digest'],request_body=p['request_body']),run_deny_event=dict(origin_database='db',run_id='r0',generation=U.u(2)),
                    ce_fence=dict(prepare_cut_id='prepare.cut.f')))
            index=next(i for i,(sql,_) in enumerate(close) if sql.startswith('INSERT INTO ce_cut_commit'))
            close[index:index]=[I('pd_cut',cut_id='prepare.cut.f',kind='run',control_id=None,cancel_id=None,run_id='f',close_id=None,
                prepare_head=U.u(0),selected_tick=U.u(20),selector_digest=AT.H,selector_body=AT.B),
                I('pd_cut_commit',cut_id='prepare.cut.f',committed_tick=U.u(20),audit_body=AT.B,outbox_body=AT.B)]
            C.execute(cd,close)
            check('原关闭留下RUN_DENY'+str(after),cd.execute('SELECT generation FROM run_deny_current').fetchone()[0]==U.u(2))
            if after:denied('采用后关闭不能R5',d,lambda:M.tx(d,lambda:M.r5_steps(d,q,s,cds)),'preparation_denied')
            else:denied('关闭先到不能签发',cd,lambda:M.issue(cd,q,q['targets'][0],cc),'preparation_denied')
        d,q,s,cds,ctx=fresh();t=q['targets'][0];cd,cc=cds[M.M.scope_key(t['controller_scope'])]
        writes=AT.planned(cd,lambda:M.issue_steps(cd,q,t,cc))
        for table,patch in [('cr_issue',dict(prep_key='missing')),('cr_issue',dict(request_digest='wrong')),('cr_device',dict(device_id='other')),
            ('cr_device',dict(control_state_id='missing')),('cr_commit',dict(request_digest='wrong')),('cr_commit',dict(audit_body=b'')),('cr_commit',dict(outbox_body=b''))]:
            denied('SQL签发错配'+table+str(patch),cd,lambda table=table,patch=patch:C.execute(cd,C.mutate(writes,table,patch)))
        for field,value in [('generation','3'),('origin_scope',V.scope('other')),('continuation_grant_ref',t['recovery_grant_ref'])]:
            values=next(args for sql,args in writes if sql.startswith('INSERT INTO cr_issue'))
            sql=next(sql for sql,args in writes if sql.startswith('INSERT INTO cr_issue'));columns=sql.split('(',1)[1].split(')',1)[0].split(',')
            old=json.loads(dict(zip(columns,values))['receipt_body']);bad=M.M.seal(dict(old,**{field:value}),'receipt_digest')
            denied('SQL重摘要回执错绑'+field,cd,lambda bad=bad:C.execute(cd,C.mutate(writes,'cr_issue',dict(receipt_body=M.raw(bad),receipt_digest=bad['receipt_digest']))))
        M.register(d,q,s);r=M.issue(cd,q,t,cc)
        C.execute(cd,[I('cr_revocation',transfer_id=q['transfer_id'],proof_body=AT.B,audit_body=AT.B,outbox_body=AT.B)])
        check('晚到回执只补历史',M.receive(d,q,r,cd,cc)=='accepted')
        before=C.snapshot(d);check('晚到回执查原零写',M.receive(d,q,r,cd,cc)=='existing' and C.snapshot(d)==before)
        check('晚到回执不产生采用或R5',d.execute('SELECT count(*) FROM rc_adoption').fetchone()[0]==0 and d.execute('SELECT count(*) FROM rc_r5_link').fetchone()[0]==0)
        for table in ('cr_issue','cr_device','cr_commit','cr_revocation','cr_limit'):
            denied('Controller历史不可删'+table,cd,lambda table=table:C.execute(cd,[('DELETE FROM '+table,())]),'immutable_continuation')
        # 已提交控制修订的改变使当前资格失效；不直接伪造当前view或关闭SQL守卫。
        d,q,s,cds,ctx=fresh();a,rs=issued(d,q,s,cds);cd,cc=next(iter(cds.values()))
        old=U.one(cd,"SELECT * FROM ct_current_state WHERE device_id='dev.1'");change=U.one(cd,'SELECT * FROM ct_change WHERE change_id=?',(old['change_id'],))
        change.update(change_id='restart',state_id='restart',kind='restart',sequence=U.u(2),previous_id=old['change_id'])
        restart=U.finish([('ct_change',change),U.state(old,'restart',gate_state='protected')])
        C.execute(cd,[I(table,**v) for table,v in restart])
        check('真实控制修订改变使cr_current失效',cd.execute('SELECT count(*) FROM cr_current').fetchone()[0]==0)
        denied('控制修订改变后采用拒绝',d,lambda:M.adopt(d,q,a,s,cds),'control_snapshot_changed')
        for i,db in enumerate(dbs):
            check('外键已开启'+str(i),db.execute('PRAGMA foreign_keys').fetchone()[0]==1)
            check('外键完整'+str(i),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks
    finally:
        for db in dbs:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'continuation-storage-report.json'
    def read(path):return subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else path.read_bytes()
    if a.check_report:
        result=json.loads(read(target));assert result['inputs']=={x.relative_to(ROOT).as_posix():hashlib.sha256(read(x)).hexdigest() for x in INPUTS}
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();result=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=117,controller_tables=235,
            ordinary_trigger_chain_tests_executed=0,runtime_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
            checks=checks,inputs={x.relative_to(ROOT).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in INPUTS})
        if a.report:target.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in result.items() if k not in ('checks','inputs')}))
