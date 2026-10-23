"""开放持久化候选的内存SQLite检查；不连接产品服务或设备。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_open_storage as G
import check_control_fence as F
U=F.U;I,u,B,H=F.I,F.u,F.B,F.H
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(F.INPUTS+G.SOURCES+[HERE/n for n in ('OPEN_STORAGE.md','OPEN_LIFECYCLE.md',
 'check_open_storage.py','controller-open.sql')]))
def fresh(mixed=False):
    db=sqlite3.connect(':memory:',isolation_level=None);db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON')
    db.executescript(G.build().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    if mixed:
        U.tx(db,F.adapt([F.F.A.namespace()]));U.tx(db,F.adapt(F.F.P.register()));U.tx(db,F.adapt(F.F.P.change()))
    U.tx(db,U.mutate(F.adapt([F.F.exit_step()]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    if mixed:
        for steps in (F.V.public(F.C.initial(),1),F.V.public(F.C.prepare(),2),F.Q.ordinary(F.V.public(F.C.dispatch(),3))):U.tx(db,F.adapt(steps))
    members=('permit.1',) if mixed else ()
    U.tx(db,U.bootstrap(db));U.tx(db,U.offer(db));U.tx(db,F.start(db,members=members,exits=('exit.0',),water=int(mixed)))
    U.tx(db,U.mutate(F.ack(members=members),'cu_ack',issued_revision=u(int(mixed))))
    U.tx(db,F.effective(db,members=members,exits=('exit.0',)))
    return db
def snapshot(db,sid='snap',tick=20,authority='effective'):
    current=U.current(db)
    return [I('go_snapshot',snapshot_id=sid,device_id='device',exit_id='exit.0',authority_state_id=authority,control_state_id=current['change_id'],
      safety_revision=db.execute("SELECT coalesce(max(revision),?) FROM go_hazard WHERE device_id='device'",(u(0),)).fetchone()[0],
      authorization_ref='auth.1',resource_ref='resource.'+sid,run_snapshot_ref='run.1',command_snapshot_ref='command.1',time_snapshot_ref='time.1',
      sampled_tick=u(tick),expires_tick=u(90),provider_ref='fixture.provider',evidence_digest=H,evidence_body=B),I('go_snapshot_commit',snapshot_id=sid,audit_body=B)]
def gate(gid='gate.1',previous=None,rev=1,wire=1,phase='fenced',ready=None):
    return I('go_gate',gate_id=gid,exit_id='exit.0',previous_id=previous,record_revision=u(rev),gate_revision=u(wire),gate_token='token.'+str(wire),
      barrier_id='barrier.1.exit.0',phase=phase,ready_id=ready,lease_until_tick=u(100),record_digest='sha256:'+str(rev%10)*64,record_body=B)
def plan(pid='plan',sid='snap',gid='gate.1',cid='effective',recovery=None,selected=25):
    return [I('go_plan',plan_id=pid,snapshot_id=sid,before_gate_id=gid,before_control_id=cid,
      basis_kind='gate_recovery' if recovery else 'activation',activation_id=None if recovery else 'effective',resource_recovery_id=None,gate_recovery_id=recovery,
      selected_tick=u(selected),expires_tick=u(80),plan_digest=H,proposal_digest='sha256:'+'b'*64,body=B),I('go_plan_commit',plan_id=pid,audit_body=B)]
def dispatch(pid='plan',did='dispatch',tick=26,seq=1):return [I('go_dispatch',dispatch_id=did,plan_id=pid,exit_id='exit.0',message_id=did+'.message',outbound_seq=u(seq),reserved_tick=u(tick),frame_digest=H,frame_body=B,outbox_body=B,audit_body=B)]
def evidence(did='dispatch',eid='evidence',tick=28,wire=1,seq=1):return [I('go_evidence',evidence_id=eid,dispatch_id=did,exit_id='exit.0',message_id=eid+'.message',reply_to=did+'.message',
      inbound_seq=u(seq),received_tick=u(tick),gate_token='token.'+str(wire),gate_revision=u(wire),run_snapshot_ref='run.1',command_snapshot_ref='command.1',
      time_snapshot_ref='time.1',observer_ref='fixture.observer',evidence_digest=H,frame_body=B,validation_body=B,audit_body=B)]
def ready(db,rid='ready',pid='plan',eid='evidence',gid='gate.2',previous='gate.1',rev=2,wire=1,tick=30):
    steps=U.change(db,rid,'ready',now=tick);steps[0][1]['state_id']=rid
    steps += [U.state(U.current(db),rid,gate_state='ready',record_digest='sha256:'+str(rev%10)*64)]
    steps += [gate(gid,previous,rev,wire,'ready',rid),I('go_ready',ready_id=rid,plan_id=pid,evidence_id=eid,change_id=rid,after_gate_id=gid,committed_tick=u(tick),ready_digest=H,transition_digest=H,transition_body=B)]
    return U.finish(steps)
def protect(db,cid='protect',close='close',rev=1,gid='gate.2'):
    now=max(40,int(db.execute('SELECT now_tick FROM ct_current_change').fetchone()[0])+1)
    steps=U.change(db,cid,'gate_protect',now=now);steps[0][1]['state_id']=cid
    steps += [U.state(U.current(db),cid,gate_state='protected'),I('go_close',close_id=close,device_id='device',exit_id='exit.0',revision=u(rev),
      protection_change_id=cid,gate_id=gid,reason_ref='reason.'+cid,body=B,outbox_body=B,audit_body=B)]
    return U.finish(steps)
def close_ack(close='close',ack='close.ack',tick=41):return [I('go_close_ack',ack_id=ack,close_id=close,exit_id='exit.0',received_tick=u(tick),evidence_digest=H,observer_ref='fixture.observer',body=B,validation_body=B,audit_body=B)]
def add_exit(db,existing_gate='gate.2'):
    steps=protect(db,'register.protect','register.close',2 if db.execute('SELECT count(*) FROM go_close').fetchone()[0] else 1,existing_gate)
    steps=[U.mutate(F.adapt([F.F.exit_step('exit.1')]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor')[0]]+steps
    steps.insert(-1,I('go_close',close_id='registration.exit.1',device_id='device',exit_id='exit.1',revision=u(1),protection_change_id='register.protect',gate_id=None,reason_ref='new.exit',body=B,outbox_body=B,audit_body=B))
    return steps
def recovery(db,rid='recover',sid='snap.2',close='close',ack='close.ack',tick=45):
    snapshots=snapshot(db,sid,tick)
    snapshots[0][1]['safety_revision']=u(int(snapshots[0][1]['safety_revision'])+1)
    return [I('go_recovery',recovery_id=rid,device_id='device',snapshot_id=sid,now_tick=u(tick),recovery_digest=H,body=B,provider_ref='fixture.provider')]+snapshots+[
      I('go_recovery_target',recovery_id=rid,close_id=close,ack_id=ack),I('go_recovery_commit',recovery_id=rid,audit_body=B,outbox_body=B)]
def run():
    assert (HERE/'controller-open.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,observed=actual,expected=expected))
    def stage(level='acked'):
        db=fresh();connections.append(db)
        if level=='base':return db
        U.tx(db,snapshot(db));U.tx(db,[gate()])
        if level=='snapshot':return db
        U.tx(db,plan())
        if level=='planned':return db
        U.tx(db,dispatch())
        if level=='dispatched':return db
        U.tx(db,evidence())
        if level=='acked':return db
        U.tx(db,ready(db))
        if level=='ready':return db
        U.tx(db,protect(db));U.tx(db,close_ack());U.tx(db,[gate('gate.3','gate.2',3,2)])
        if level=='closed':return db
        U.tx(db,recovery(db));return db
    def denied(name,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as exc:
            if error:check(name,str(exc),error)
            else:check(name,True)
        else:raise AssertionError(name+'应拒绝')
        check(name+'全库回滚',U.snapshot(db)==before)
    def atomic(name,level,make):
        count=len(make(stage(level)))
        for index in range(count):
            db=stage(level);steps=make(db);denied(name+'缺写'+str(index),db,steps[:index]+steps[index+1:])
            before=U.snapshot(db)
            try:U.tx(db,steps,fault=index)
            except RuntimeError as exc:assert str(exc)=='injected'
            else:raise AssertionError('未触发故障')
            check(name+'主动异常'+str(index),U.snapshot(db)==before)
    try:
        db=stage('ready');check('T5持久提交后仍是当前候选',db.execute('SELECT ready_id FROM go_ready_candidate').fetchall(),[('ready',)])
        check('控制安全历史仍是T4',db.execute('SELECT change_id FROM go_authority').fetchall(),[('effective',)])
        check('输出控制记录ready',U.current(db)['gate_state'],'ready')
        check('新组合表数量',db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],178)
        atomic('快照','base',snapshot);atomic('计划','snapshot',lambda db:plan());atomic('T5','acked',ready)
        atomic('保护','ready',protect);atomic('恢复','closed',recovery);atomic('新出口关闭','ready',add_exit)
        for table,field,value,error in [
          ('go_ready','plan_id','missing',None),('go_ready','evidence_id','missing',None),
          ('go_ready','after_gate_id','missing',None),('go_ready','committed_tick',u(31),'open_ready_binding'),
          ('ct_state','holder_id','mallory','control_state_transition'),('ct_state','record_revision',u(99),'control_state_transition'),
          ('ct_state','record_digest',H,'open_ready_binding'),('go_gate','gate_token','wrong','open_gate_transition')]:
            db=stage();denied('T5字段:'+field,db,U.mutate(ready(db),table,**{field:value}),error)
        for tick,accepted in ((79,True),(80,False),(90,False)):
            db=stage()
            if accepted:U.tx(db,ready(db,tick=tick));check('期限内T5',True)
            else:denied('到期T5:'+str(tick),db,ready(db,tick=tick),'open_ready_binding')
        db=stage('ready');U.tx(db,snapshot(db,'snap.new',35));check('正常完整快照更新不自失效',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],1)
        db=stage('ready');denied('关闭不能让单调时刻回退',db,U.mutate(protect(db),'ct_change',now_tick=u(29)),'open_clock_order')
        db=stage('ready');denied('同域时钟描述符不能偷换',db,U.mutate(protect(db),'ct_change',descriptor='other'),'open_clock_order')
        db=stage('closed');denied('关闭ACK不能早于关闭请求',db,close_ack(ack='earlier',tick=39),'open_close_ack_binding')
        db=stage('ready');steps=U.mutate(snapshot(db,'auth.new',35),'go_snapshot',authorization_ref='auth.2');U.tx(db,steps)
        check('新授权投影撤旧ready',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage('ready');U.tx(db,protect(db));check('风险后旧快照失效',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        U.tx(db,snapshot(db,'recovered',41));check('风险清空不复活旧安全代次',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage('ready');U.tx(db,[I('go_revocation',kind='open_ack',object_id='evidence',reason_body=B,audit_body=B)])
        check('原开放ACK撤回立即撤候选',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage('ready');U.tx(db,[F.revoke()]);check('T4原件撤回撤当前候选',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage();steps=ready(db);steps.insert(-1,F.revoke());denied('T5封存前原件撤回复核',db,steps,'open_ready_binding')
        db=stage('ready');denied('新增出口不能漏持久关闭登记',db,F.adapt([F.F.exit_step('exit.1')]))
        U.tx(db,add_exit(db))
        check('新增出口推进安全代次并撤旧ready',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage('closed');U.tx(db,add_exit(db,'gate.3'))
        denied('恢复不能遗漏新增活出口',db,recovery(db),'open_recovery_incomplete')
        db=stage('ready');U.tx(db,protect(db));check('保护不保留当前ready',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        db=stage('recovered');U.tx(db,plan('plan.2','snap.2','gate.3','protect','recover',46));U.tx(db,dispatch('plan.2','dispatch.2',47,2));U.tx(db,evidence('dispatch.2','evidence.2',48,2,2))
        U.tx(db,ready(db,'ready.2','plan.2','evidence.2','gate.4','gate.3',4,2,49))
        check('新恢复新计划可以再次ready',db.execute('SELECT ready_id FROM go_ready_candidate').fetchall(),[('ready.2',)])
        U.tx(db,protect(db,'protect.2','close.2',2,'gate.4'));U.tx(db,close_ack('close.2','close.ack.2',51))
        denied('已消费ACK不能第二次恢复',db,recovery(db,'recover.2','snap.3','close','close.ack',55))
        U.tx(db,recovery(db,'recover.2','snap.3','close.2','close.ack.2',55));check('第二次恢复需新关闭与原ACK',True)
        db=stage('closed');U.tx(db,[I('go_revocation',kind='close_ack',object_id='close.ack',reason_body=B,audit_body=B)])
        denied('撤回关闭ACK不能恢复',db,recovery(db),'open_recovery_incomplete')
        db=stage('closed');steps=recovery(db);steps.insert(-1,I('go_revocation',kind='close_ack',object_id='close.ack',reason_body=B,audit_body=B))
        denied('恢复封存前撤回不能借早先选择',db,steps,'open_recovery_incomplete')
        db=stage('recovered');denied('恢复封存后不得追加目标',db,[I('go_recovery_target',recovery_id='recover',close_id='close',ack_id='close.ack')],'open_members_sealed')
        db=stage('snapshot');denied('快照封存后不得补hold',db,[I('go_hold',snapshot_id='snap',hold_id='missing',authority_state_id='effective',owner_ref='x',classification='active')],'open_members_sealed')
        db=stage('dispatched');denied('伪reply_to',db,U.mutate(evidence(),'go_evidence',reply_to='wrong'),'open_evidence_binding')
        U.tx(db,evidence(tick=100));check('迟到真实ACK保存历史',True);denied('迟到原ACK不ready',db,ready(db,tick=101),'open_ready_binding')
        db=stage('ready');before=U.snapshot(db);denied('同ready重复不造第二次提交',db,ready(db))
        db=fresh(mixed=True);connections.append(db);steps=snapshot(db)
        denied('完整资源快照不可漏真实hold',db,steps,'open_hold_set')
        hold=db.execute('SELECT hold_id FROM cr_risk_hold').fetchone()[0]
        steps.insert(1,I('go_hold',snapshot_id='snap',hold_id=hold,authority_state_id='base',owner_ref='fixture.command',classification='active'))
        U.tx(db,steps);U.tx(db,[gate()]);denied('旧控制归属不能借active开闸',db,plan(),'open_plan_invalid')
        before=db.execute('SELECT count(*) FROM go_hazard').fetchone()[0]
        validation=db.execute('SELECT validation_id FROM cr_hold WHERE hold_id=?',(hold,)).fetchone()[0]
        U.tx(db,[I('cr_validation_revocation',validation_id=validation,reason_body=B,audit_body=B)])
        check('真实资源来源撤回同事务推进风险代次',db.execute('SELECT count(*) FROM go_hazard').fetchone()[0],before+1)
        db=stage('ready')
        denied('开放候选不绕过尚未归并的最终发送门槛',db,[I('ce_permit',permit_id='new',attempt_id='missing',exit_id='exit.0',issued_revision=u(1),packet_id='missing',ordinal=0,kind='initial',parent_permit_id=None,permit_body=B)],'control_gate_not_ready')
        denied('不存在的来源不得伪造安全事件',db,[I('go_hazard',device_id='device',revision=u(2),source_kind='close',source_id='fake')],'hazard_source')
        for table in G.TABLES:
            # 仅在有实际行时验证不可变，空表不伪报覆盖。
            candidates=[d for d in connections if d.execute('SELECT count(*) FROM '+table).fetchone()[0]]
            assert candidates,table
            db=candidates[0]
            for verb in ('UPDATE','DELETE'):
                column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
                statement='UPDATE '+table+' SET '+column+'='+column if verb=='UPDATE' else 'DELETE FROM '+table
                try:db.execute(statement)
                except sqlite3.IntegrityError as exc:check(table+verb,str(exc),'immutable_open_storage')
                else:raise AssertionError(table+'历史可改')
        for db in connections:
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库完整性',True)
        check('非空合成BODY通过不证明实际提供者',True)
        return checks
    finally:
        for db in connections:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'open-storage-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),scope='开放持久化候选',sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
