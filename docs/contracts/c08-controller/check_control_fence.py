"""控制屏障与生效的内存组合实验；不连接服务或设备，不测试磁盘故障。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_control_fence as G
import check_control_storage as U
import check_result_dependency as D
HERE=G.HERE;ROOT=HERE.parents[2]
I,u,B,H=U.row,U.u,U.BODY,U.DIGEST
F,V,C,Q,X,P,R=D.F,D.V,D.C,D.Q,D.X,D.P,D.R
INPUTS=list(dict.fromkeys(G.SOURCES+D.INPUTS+[HERE/n for n in
 ('check_control_storage.py','check_control_fence.py','controller-control-fence.sql','CONTROL_FENCE.md')]))

def adapt(steps):
    out=[]
    for sql,args in D.bind(steps):
        assert sql.startswith('INSERT INTO '),sql
        table=sql.split()[2].split('(')[0]
        fields=sql.split('(',1)[1].split(')',1)[0].split(',')
        out.append(I(table,**{k.strip():('device' if v=='dev.1' else v) for k,v in zip(fields,args)}))
    return out

def delivery(attempt=1,exits=('exit.0','exit.1')):
    return [I('cu_delivery',barrier_id=f'barrier.{attempt}.{e}',attempt_id=f'op.attempt.{attempt}',operation_id='op',exit_id=e,
        target_gate_revision=u(attempt),request_digest=H,request_body=B,outbox_id=f'fence.{attempt}.{e}',outbox_body=B) for e in exits]

def start(db,kind='accept',members=('permit.1','cancel.1'),exits=('exit.0','exit.1'),retired=(),queued=False,entered=(),water=2):
    actor='alice' if kind=='release' else 'bob'
    steps=U.start(db,kind=kind,actor=actor)
    extra=[I('cu_cut',operation_id='op',change_id='accept',device_id='device',issued_revision=u(water),cut_digest=H,cut_body=B,audit_body=B)]
    extra += [I('cu_target',operation_id='op',exit_id=e) for e in exits]
    extra += [I('cu_member',operation_id='op',exit_id='exit.0',permit_id=p,entered_known=int(p in entered)) for p in members]
    extra += delivery(exits=tuple(e for e in exits if e not in retired))
    if queued:extra += adapt(V.public(C.revision(2,'block',key='queued',phase='finished',outcome='blocked',effect='not_sent',latched=1,terminal=2),2,key='queued'))
    return steps[:-1]+extra+steps[-1:]

def ack(exit_id='exit.0',attempt=1,members=('permit.1','cancel.1'),state='unknown',version=4):
    bid=f'barrier.{attempt}.{exit_id}'
    return [I('cu_coverage',barrier_id=bid,operation_id='op',exit_id=exit_id,permit_id=p,disposition=state,
        proof={'unknown':'send_uncertain','in_flight':'transport_entered','not_sent':'discarded_unconsumed'}[state]) for p in members]+[
        I('cu_ack',barrier_id=bid,control_epoch='control.epoch',installed_version=u(version),gate_revision=u(attempt),
          issued_revision=u(2),cut_digest=H,effective_tick=u(15),ack_digest=H,ack_body=B,provider_ref='trusted.fixture',validation_body=B,audit_body=B)]

def effective(db,attempt=1,members=('permit.1','cancel.1'),exits=('exit.0','exit.1'),retired=(),state='unknown',now=16):
    old=U.current(db);o=U.one(db,"SELECT * FROM ct_operation WHERE operation_id='op'")
    e=U.one(db,"SELECT * FROM ct_current_operation WHERE operation_id='op'")
    steps=U.change(db,'effective','effective',op='op',now=now);steps[0][1]['state_id']='effective'
    steps += [U.state(old,'effective',effective_version=o['target_version'],mode='automatic' if o['kind']=='release' else 'manual',
      **U.p('holder',o['target_id']),pending_operation_id=None,gate_state='protected'),
      I('ct_operation_event',change_id='effective',operation_id='op',revision=u(int(e['revision'])+1),state='effective',
        attempt_id=f'op.attempt.{attempt}',failure_code=None,result_digest=H,result_body=B),
      I('cu_authorization',change_id='effective',operation_id='op',issuer_id='issuer',issuer_epoch='epoch',
        principal_id=o['requester_id'] if o['kind']=='release' else o['target_id'],clock_domain='domain',descriptor='descriptor',
        issued_tick=u(15),expires_tick=u(20),provider_ref='trusted.fixture',snapshot_digest=H,snapshot_body=B)]
    steps += [I('cu_selection',change_id='effective',operation_id='op',exit_id=x,
      barrier_id=None if x in retired else f'barrier.{attempt}.{x}',retirement_exit_id=x if x in retired else None) for x in exits]
    steps += [I('cu_effective_member',change_id='effective',permit_id=p,disposition=state) for p in members]
    steps += [I('cu_effective',change_id='effective',operation_id='op',attempt_id=f'op.attempt.{attempt}',control_state_id='effective',
      selection_digest=H,selection_body=B,provider_ref='trusted.fixture',validation_body=B)]
    return U.finish(steps)

def revoke(kind='ack',object_id='barrier.1.exit.0'):
    return I('cu_revocation',kind=kind,object_id=object_id,reason_body=B,audit_body=B)

def run():
    assert (HERE/'controller-control-fence.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[];sql=G.build().decode()
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,observed=actual,expected=expected))
    def oldtx(db,steps):U.tx(db,adapt(steps))
    def release_both(db):
        oldtx(db,X.cut('all',prepares=['prep.primitive.cancel']))
        for x in ('exit.0','exit.1'):
            oldtx(db,[X.attempt('all',x)])
            oldtx(db,X.extra(X.ack('all',x,state='not_sent',cancelstate='not_sent'),'cc_ack_prepare',prepare_id='prep.primitive.cancel'))
        oldtx(db,X.closure('all'));oldtx(db,X.progress());oldtx(db,D.Z.closure())
        oldtx(db,R.close()+R.settle(kind='effect_resolved'))
        oldtx(db,[D.T.report(state='not_sent')]+D.Z.settlement())
        oldtx(db,D.H.release(parent=True));oldtx(db,D.H.release('rp',parent=True,hold='h'))
    def fresh(stage='offered',mixed=True,queued=False,exits=True):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(sql)
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        oldtx(db,[F.A.namespace()]);oldtx(db,F.P.register());oldtx(db,F.P.change())
        if exits:oldtx(db,[F.exit_step(),F.exit_step('exit.1')])
        if mixed:
            oldtx(db,V.public(C.initial(),1));oldtx(db,V.public(C.prepare(),2));oldtx(db,Q.ordinary(V.public(C.dispatch(),3)))
            oldtx(db,F.P.mutate(V.cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=V.SENT),'cv_cancel','mode','cooperative'))
            oldtx(db,X.cut())
            for x in ('exit.0','exit.1'):oldtx(db,[X.attempt(eid=x)]);oldtx(db,X.ack(eid=x))
            oldtx(db,X.closure());oldtx(db,D.H.acquire());oldtx(db,P.prepare('primitive.cancel'));oldtx(db,P.dispatch())
        if stage=='raw':return db
        if queued:oldtx(db,V.public(C.initial(key='queued'),1,key='queued'))
        U.tx(db,U.bootstrap(db))
        if stage=='base':return db
        U.tx(db,U.offer(db))
        if stage=='offered':return db
        U.tx(db,start(db,queued=queued))
        if stage=='pending':return db
        U.tx(db,ack());U.tx(db,ack('exit.1',members=()))
        if stage=='acked':return db
        U.tx(db,effective(db));return db
    def denied(name,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as exc:check(name,str(exc) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',U.snapshot(db)==before)
    def atomic(name,factory,writer,omit=True):
        db=factory();steps=writer(db);U.tx(db,steps);check(name+'完整提交',True);db.close();connections.remove(db)
        for n in range(len(steps)):
            db=factory();steps=writer(db)
            if omit:denied(name+'缺写'+str(n),db,steps[:n]+steps[n+1:])
            before=U.snapshot(db)
            try:U.tx(db,steps,n)
            except RuntimeError:check(name+'主动异常'+str(n),U.snapshot(db)==before)
            else:raise AssertionError('未注入异常')
            db.close();connections.remove(db)
    try:
        db=fresh('effective');check('161表组合',len(U.snapshot(db)),161)
        check('转交后持有人和生效版本',[(U.current(db)[k]) for k in ('holder_id','effective_version','reserved_version','pending_operation_id','gate_state')],['bob',u(4),u(4),None,'protected'])
        check('生效不清两类资源',db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id').fetchall(),[('h',),('hc',)])
        check('初始Receipt保持修订1',db.execute("SELECT initial_result_revision FROM ct_request WHERE change_id='accept'").fetchone()[0],u(1))
        check('普通及取消两类切点',db.execute('SELECT permit_id FROM cu_member ORDER BY permit_id').fetchall(),[('cancel.1',),('permit.1',)])
        check('空成员旧出口仍有屏障',db.execute('SELECT exit_id FROM cu_target ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        atomic('完整T3',fresh,start)
        atomic('带排队终结T3',lambda:fresh(queued=True),lambda d:start(d,queued=True))
        atomic('原ACK',lambda:fresh('pending'),lambda d:ack())
        atomic('T4',lambda:fresh('acked'),effective)
        for kind in ('acquire','release'):
            db=fresh('base');U.tx(db,start(db,kind=kind));U.tx(db,ack());U.tx(db,ack('exit.1',members=()));U.tx(db,effective(db))
            check(kind+'生效目标',U.current(db)['holder_id'],None if kind=='release' else 'bob')
        db=fresh('base',mixed=False,exits=False);U.tx(db,start(db,kind='acquire',members=(),exits=(),water=0));U.tx(db,effective(db,members=(),exits=()))
        check('零出口允许生效但不开闸',U.current(db)['gate_state'],'protected')
        for table,values in [('cu_cut',dict(issued_revision=u(1))),('cu_member',dict(entered_known=1)),('cu_delivery',dict(attempt_id='missing'))]:
            db=fresh();denied('T3错配'+table,db,U.mutate(start(db),table,**values))
        db=fresh(queued=True);denied('排队命令未终结',db,start(db),'control_queued_not_blocked')
        for values in (dict(control_epoch='wrong'),dict(installed_version=u(5)),dict(gate_revision=u(2)),dict(issued_revision=u(1)),dict(cut_digest='wrong')):
            db=fresh('pending');denied('ACK错配'+next(iter(values)),db,U.mutate(ack(),'cu_ack',**values),'control_ack_binding')
        db=fresh('pending');denied('ACK覆盖额外许可',db,U.mutate(ack(),'cu_coverage',permit_id='missing'))
        db=fresh('pending');denied('ACK分类与证明不符',db,U.mutate(ack(),'cu_coverage',disposition='in_flight'))
        for values in (dict(issuer_id='other'),dict(issuer_epoch='other'),dict(principal_id='other'),dict(clock_domain='other'),dict(descriptor='other'),dict(issued_tick=u(17)),dict(expires_tick=u(16))):
            db=fresh('acked');denied('T4授权错配'+next(iter(values)),db,U.mutate(effective(db),'cu_authorization',**values),'control_effective_authorization')
        for values in (dict(effective_version=u(5)),dict(holder_id='other'),dict(reserved_version=u(5)),dict(control_epoch='other'),dict(gate_state='ready')):
            db=fresh('acked');denied('T4状态错配'+next(iter(values)),db,U.mutate(effective(db),'ct_state',**values))
        db=fresh('acked');denied('T4把未知伪造未发',db,U.mutate(effective(db),'cu_effective_member',disposition='not_sent'),'control_effective_classification')
        db=fresh('pending');U.tx(db,U.settle(db));steps=U.settle(db,'retry');U.tx(db,steps[:-1]+delivery(2)+steps[-1:])
        U.tx(db,ack(state='in_flight'));U.tx(db,ack('exit.1',members=()))
        check('迟到旧ACK仍保留已发事实',db.execute('SELECT disposition FROM cu_current_disposition ORDER BY permit_id').fetchall(),[('in_flight',),('in_flight',)])
        denied('旧attempt不可生效',db,effective(db,state='in_flight'),'control_effective_binding')
        U.tx(db,ack(attempt=2));U.tx(db,ack('exit.1',attempt=2,members=()))
        U.tx(db,effective(db,attempt=2,state='in_flight'));check('重试保留原目标版本',U.current(db)['effective_version'],u(4))
        db=fresh('pending');U.tx(db,U.settle(db));steps=U.settle(db,'retry');U.tx(db,steps[:-1]+delivery(2)+steps[-1:])
        U.tx(db,ack(attempt=2));U.tx(db,ack('exit.1',attempt=2,members=()))
        steps=effective(db,attempt=2);steps[-1:-1]=ack(state='in_flight')
        denied('T4选择后迟到强事实必须重分类',db,steps,'control_effective_classification')
        db=fresh('acked');steps=effective(db);steps.insert(-1,revoke());denied('选完后撤回不可封存',db,steps,'control_selection_invalid')
        db=fresh('effective');before=U.current(db);U.tx(db,[revoke()])
        check('撤回不修改历史控制',U.current(db)==before)
        check('撤回隐藏有效证据',db.execute('SELECT count(*) FROM cu_valid_effective').fetchone()[0],0)
        check('撤回原子捕获全部活出口',db.execute('SELECT exit_id FROM cu_protection ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        oldtx(db,[F.exit_step('exit.2')]);check('新出口补捕获',db.execute('SELECT count(*) FROM cu_protection').fetchone()[0],3)
        db=fresh('acked');oldtx(db,[F.exit_step('exit.2')]);denied('T4不能遗漏后来出口',db,effective(db),'control_unfenced_new_exit')
        db=fresh('pending');U.tx(db,ack(state='not_sent'))
        check('未发证据原件贡献分类',db.execute('SELECT disposition FROM cu_current_disposition ORDER BY permit_id').fetchall(),[('not_sent',),('not_sent',)])
        U.tx(db,[revoke()]);check('撤回未发恢复未知',db.execute('SELECT disposition FROM cu_current_disposition ORDER BY permit_id').fetchall(),[('unknown',),('unknown',)])
        db=fresh('pending');U.tx(db,ack(state='in_flight'));U.tx(db,[revoke()]);check('撤回不抹除已发事实',db.execute('SELECT disposition FROM cu_current_disposition ORDER BY permit_id').fetchall(),[('in_flight',),('in_flight',)])
        # 退休证据只证明旧出口不再写，不能把历史影响判成未发。
        db=fresh();U.tx(db,[I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B)])
        U.tx(db,start(db,retired=('exit.0',)));U.tx(db,ack('exit.1',members=()))
        denied('退休不制造未发',db,effective(db,retired=('exit.0',),state='not_sent'),'control_effective_classification')
        U.tx(db,effective(db,retired=('exit.0',)));U.tx(db,[revoke('retirement','exit.0')])
        check('退休证明撤回也保护原退休出口',db.execute('SELECT exit_id FROM cu_protection ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        db=fresh();U.tx(db,[I('ce_retirement',exit_id='exit.1',supervisor_evidence_body=B)])
        denied('空成员退休出口仍保留依赖',db,start(db,exits=('exit.0',)),'control_target_set')
        U.tx(db,start(db,retired=('exit.1',)));U.tx(db,ack());U.tx(db,effective(db,retired=('exit.1',)))
        db=fresh('acked');steps=effective(db);steps.insert(-1,I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B))
        denied('选ACK后出口退休最终复核',db,steps,'control_selection_invalid')
        # 签发提交必须再次读当前控制；前置permit行不是通行证。
        db=fresh('base',mixed=False);oldtx(db,V.public(C.initial(),1));oldtx(db,V.public(C.prepare(),2))
        denied('控制已登记禁止普通新签发',db,adapt(Q.ordinary(V.public(C.dispatch(),3))),'control_gate_not_ready')
        db=fresh('pending');denied('接管期间禁止取消新签发',db,adapt(P.dispatch(pid='cancel.2',n=3,ordinal=1,initial='cancel.1')),'control_gate_not_ready')
        for cancel in (False,True):
            db=fresh('raw',mixed=cancel)
            if not cancel:oldtx(db,V.public(C.initial(),1));oldtx(db,V.public(C.prepare(),2))
            steps=adapt(P.dispatch(pid='cancel.2',n=3,ordinal=1,initial='cancel.1') if cancel else Q.ordinary(V.public(C.dispatch(),3)))
            at=next(n for n,(t,_) in enumerate(steps) if t==('ci_cancel_commit' if cancel else 'ce_transmission_commit'))
            steps[at:at]=U.bootstrap(db)
            denied(('取消' if cancel else '普通')+'预写permit后控制改变最终拒绝',db,steps,'control_gate_not_ready')
        # 切点已冻结；后续资源核销不能抹掉迟到ACK中的已发送事实。
        db=fresh('pending');release_both(db)
        check('核销后两个占用均释放',db.execute('SELECT count(*) FROM cr_risk_hold').fetchone()[0],0)
        before=U.snapshot(db)
        try:U.tx(db,ack(state='in_flight'),2)
        except RuntimeError:check('迟到强事实及保护同回滚',U.snapshot(db)==before)
        U.tx(db,ack(state='in_flight'))
        check('迟到强事实重开双占用',db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id').fetchall(),[('h',),('hc',)])
        check('迟到强事实同事务创建保护事故',db.execute('SELECT count(*) FROM ro_incident').fetchone()[0],2)
        db=fresh('pending');U.tx(db,ack(state='not_sent'));release_both(db);U.tx(db,[revoke()])
        check('未发证明撤回重开双占用',db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id').fetchall(),[('h',),('hc',)])
        check('未发证明撤回关联明确来源',db.execute("SELECT count(*) FROM cr_release_invalidation WHERE source_kind='control_ack_revocation'").fetchone()[0],2)
        oldtx(db,D.H.release('rc.new',parent=True));oldtx(db,D.H.release('rp.new',parent=True,hold='h'))
        check('撤回不追溯污染后续独立新取证',db.execute('SELECT count(*) FROM cr_risk_hold').fetchone()[0],0)
        check('新取证不清旧保护事故',db.execute('SELECT count(*) FROM ro_incident').fetchone()[0],2)
        db=fresh('raw');release_both(db);U.tx(db,U.bootstrap(db));U.tx(db,U.offer(db))
        U.tx(db,start(db,members=()));U.tx(db,ack(members=()));U.tx(db,ack('exit.1',members=()));U.tx(db,effective(db,members=()))
        check('可靠完整核销可省许可但不退共享水位',db.execute('SELECT issued_revision FROM cu_cut').fetchone()[0],u(2))
        check('核销后仍保留全部历史出口',db.execute('SELECT count(*) FROM cu_target').fetchone()[0],2)
        # 真实插入边界数据，两类别各自计数，拒绝超限而不截断集合。
        for count in (256,257):
            db=fresh('raw')
            for n in range(2,count+1):oldtx(db,P.dispatch(pid='cancel.'+str(n),n=n+1,ordinal=n-1,initial='cancel.1'))
            U.tx(db,U.bootstrap(db));U.tx(db,U.offer(db))
            members=('permit.1',)+tuple('cancel.'+str(n) for n in range(1,count+1))
            steps=start(db,members=members,water=count+1)
            if count==257:denied('每出口取消257拒绝',db,steps,'control_capacity')
            else:U.tx(db,steps);check('普通1及取消256完整纳入',db.execute('SELECT count(*) FROM cu_member').fetchone()[0],257)
        db=fresh('effective',queued=True);U.tx(db,[revoke()])
        for table in G.TABLES:
            assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]>0,table
            col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for verb in ('UPDATE','DELETE'):
                before=U.snapshot(db)
                try:db.execute('UPDATE '+table+' SET '+col+'='+col if verb=='UPDATE' else 'DELETE FROM '+table)
                except sqlite3.IntegrityError as exc:check(table+verb,str(exc),'immutable_control_fence')
                else:raise AssertionError(table+'历史可改')
                check(table+verb+'不改变历史',U.snapshot(db)==before)
        denied('cut封存后不补目标',db,[I('cu_target',operation_id='op',exit_id='exit.1')],'control_cut_sealed')
        denied('ACK封存后不补覆盖',db,[ack()[0]],'control_ack_frozen')
        denied('T4封存后不补选择',db,[next(s for s in effective(db) if s[0]=='cu_selection')],'control_effective_sealed')
        for db in connections:
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库完整性',True)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'control-fence-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='161表控制屏障与生效候选',
          runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
          sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'control-fence-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
