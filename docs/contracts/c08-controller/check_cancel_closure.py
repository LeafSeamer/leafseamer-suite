"""两阶段关闭119表内存参考检查；无服务、网络或磁盘数据库入口。"""
import argparse,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_cancel_closure as G
import check_cancel_resource as X
HERE,ROOT,F,I,B,D,U,V,C,Q,T,R=G.HERE,X.ROOT,X.F,X.I,X.B,X.D,X.U,X.V,X.C,X.Q,X.T,X.R
INPUTS=list(dict.fromkeys(X.INPUTS+G.SOURCES+[HERE/n for n in
 ('build_cancel_closure.py','controller-cancel-closure.sql','CANCEL_CLOSURE.md','check_cancel_closure.py')]))

def extra(steps,table,**fields):
    result=[]
    for sql,args in steps:
        if sql.startswith('INSERT INTO '+table+' '):
            v=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args));v.update(fields)
            result.append(I(table,**v))
        else:result.append((sql,args))
    return result
def cut(stage='ordinary',members=None,prepares=None):
    members=members if members is not None else [('permit.1','exit.0',0)]+([('cancel.1','exit.0',0)] if stage=='all' else [])
    prepares=prepares if prepares is not None else (['prepare.cancel'] if stage=='all' else [])
    return [I('cc_cut',cut_id=stage,cancellation_id='cancel',stage=stage,previous_cut_id='ordinary' if stage=='all' else None,
        issued_revision=U(2 if stage=='all' else 1),cut_digest=D,cut_body=B)]+[
        I('cc_target',cut_id=stage,exit_id=e,target_digest=D,target_body=B) for e in ('exit.0','exit.1')]+[
        I('cc_member',cut_id=stage,exit_id=e,permit_id=p,entered_known=k) for p,e,k in members]+[
        I('cc_cut_prepare',cut_id=stage,exit_id='exit.0',prepare_id=p) for p in prepares]+[
        I('cc_cut_commit',cut_id=stage,validation_body=B,audit_body=B,outbox_id='cut.'+stage,outbox_body=B)]
def attempt(stage='ordinary',eid='exit.0',bid=None,n=1,previous=None):
    bid=bid or stage+'.'+eid
    return I('cc_attempt',barrier_id=bid,cut_id=stage,exit_id=eid,ordinal=n,previous_barrier_id=previous,
        request_digest=D,request_body=B,audit_body=B,outbox_id='request.'+bid,outbox_body=B)
def ack(stage='ordinary',eid='exit.0',bid=None,state='unknown',cancelstate='unknown'):
    bid=bid or stage+'.'+eid
    members=[] if eid=='exit.1' else [('permit.1',state)]+([('cancel.1',cancelstate)] if stage=='all' else [])
    return [I('cc_coverage',barrier_id=bid,cut_id=stage,exit_id=eid,permit_id=p,disposition=s,proof=T.PROOF[s]) for p,s in members]+(
        [I('cc_ack_prepare',barrier_id=bid,cut_id=stage,exit_id=eid,prepare_id='prepare.cancel')] if stage=='all' and eid=='exit.0' else [])+[
        I('cc_ack',barrier_id=bid,ack_digest=D,ack_body=B,effective_tick=U(7),gate_io_seq=U(8),validation_body=B,audit_body=B)]
def closure(stage='ordinary',hid=None,bid=None,retired=()):
    hid=hid or 'close.'+stage
    return [I('cc_selection',closure_id=hid,cut_id=stage,exit_id=e,
        kind='supervisor_retired' if e in retired else 'worker_ack',
        barrier_id=None if e in retired else bid if e=='exit.0' and bid else stage+'.'+e,
        retirement_exit_id=e if e in retired else None,validation_body=B,audit_body=B) for e in ('exit.0','exit.1')]+[
        I('cc_closure',closure_id=hid,cut_id=stage,closure_digest=D,closure_body=B,validation_body=B,
          audit_body=B,outbox_id='closure.'+hid,outbox_body=B)]
def prepare():
    return I('cc_prepare',prepare_id='prepare.cancel',cancellation_id='cancel',ordinary_closure_id='close.ordinary',
        execution_id='execution.cancel',execution_digest=D,primitive_id='primitive.cancel',exit_id='exit.0',
        prepare_body=B,validation_body=B,audit_body=B,outbox_id='prepare.out',outbox_body=B)
def packet():
    return I('cc_packet',packet_id='packet.cancel',prepare_id='prepare.cancel',packet_digest=D,
        packet_bytes=B,packet_body=B,validation_body=B)
def dispatch():
    steps=Q.cancel();steps.insert(-1,I('cc_dispatch',permit_id='cancel.1',packet_id='packet.cancel'));return steps
def progress(hid='close.all'):
    return extra(V.progress(5,2,'indeterminate','closed',state_args=V.SENT),'cv_cancel_revision',closure_id=hid)
def revoke(hid):
    return I('cc_revocation',closure_id=hid,reason_body=B,audit_body=B,outbox_id='revoke.'+hid,outbox_body=B)

def run():
    assert (HERE/'controller-cancel-closure.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='closed'):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        F.tx(db,V.public(C.initial(),1));F.tx(db,V.public(C.prepare(),2));F.tx(db,Q.ordinary(V.public(C.dispatch(),3)))
        F.tx(db,F.P.mutate(V.cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=V.SENT),'cv_cancel','mode','cooperative'))
        if stage=='accepted':return db
        F.tx(db,cut())
        for e in ('exit.0','exit.1'):F.tx(db,[attempt(eid=e)]);F.tx(db,ack(eid=e))
        F.tx(db,closure())
        if stage=='ordinary':return db
        F.tx(db,[prepare(),packet()])
        if stage=='prepared':return db
        F.tx(db,dispatch())
        if stage=='sent':return db
        F.tx(db,cut('all'))
        for e in ('exit.0','exit.1'):F.tx(db,[attempt('all',e)])
        if stage=='allcut':return db
        for e in ('exit.0','exit.1'):F.tx(db,ack('all',e))
        if stage=='allacked':return db
        F.tx(db,closure('all'))
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def atomic(name,stage,steps):
        for n in range(len(steps)):
            db=fresh(stage);denied(name+'缺写'+str(n),db,steps[:n]+steps[n+1:])
            db=fresh(stage);before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError as e:check(name+'主动异常'+str(n),str(e),'injected_before_commit')
            else:raise AssertionError('未注入异常')
            check(name+'回滚'+str(n),F.snapshot(db)==before)
    try:
        db=fresh();check('119表组合',len(F.snapshot(db)),119)
        atomic('ordinary切点','accepted',cut());atomic('all切点','sent',cut('all'))
        atomic('取消发送关联','prepared',dispatch());atomic('完整ACK','allcut',ack('all'))
        atomic('关闭汇总','allacked',closure('all'));atomic('公开关闭','closed',progress())
        db=fresh('accepted');denied('仅有BODY不能编码',db,[prepare()],'cancel_prepare_closure')
        db=fresh('ordinary');denied('ordinary不能公开closed',db,progress('close.ordinary'),'public_all_closure_required')
        db=fresh('sent');denied('遗漏准备不可all',db,cut('all',prepares=[]),'closure_prepare_set')
        db=fresh('sent');denied('遗漏取消历史不可all',db,cut('all',members=[('permit.1','exit.0',0)]),'closure_member_set')
        db=fresh('allcut');denied('未收ACK不能汇总',db,closure('all'))
        db=fresh('prepared');bad=F.P.mutate(dispatch(),'ci_cancel_commit','packet_bytes',b'changed')
        denied('传输须绑定原字节',db,bad,'cancel_dispatch_source')
        db=fresh('prepared');F.tx(db,[revoke('close.ordinary')]);denied('撤回ordinary后禁签发',db,dispatch(),'cancel_dispatch_source')
        db=fresh('sent');allsteps=cut('all')
        # all切点插入即锁住新取消签发，不等待公开closed。
        tx=Q.cancel('late',3,1,'cancel.1');tx.insert(-1,I('cc_dispatch',permit_id='late',packet_id='packet.cancel'))
        denied('all同事务阻止后续签发',db,allsteps+tx,'cancel_issuance_closed')
        db=fresh('allcut');p=extra([prepare()],'cc_prepare',prepare_id='new',primitive_id='new',outbox_id='new')
        denied('all后不能新增准备',db,p,'cancel_prepare_closed')
        # 失败原ACK迟到仍贡献强事实，但不能采用旧attempt。
        db=fresh('allcut');F.tx(db,[I('cc_failure',barrier_id='all.exit.0',reason='deadline_elapsed',evidence_body=B,audit_body=B),
            attempt('all',bid='retry',n=2,previous='all.exit.0')])
        F.tx(db,ack('all',bid='retry'));F.tx(db,ack('all','exit.1'))
        F.tx(db,ack('all',state='in_flight',cancelstate='in_flight'))
        check('迟到普通强事实',db.execute("SELECT disposition FROM ce_current_disposition WHERE permit_id='permit.1'").fetchone()[0],'in_flight')
        check('迟到取消强事实',db.execute("SELECT disposition FROM cf_disposition WHERE permit_id='cancel.1'").fetchone()[0],'in_flight')
        denied('旧ACK不能代新尝试',db,closure('all'),'closure_ack_not_current')
        F.tx(db,closure('all',bid='retry'));check('当前关闭不清在途',db.execute('SELECT count(*) FROM cf_open_permit').fetchone()[0],1)
        # 已释放后才到达失败尝试的强ACK，必须原子地撤销旧never_sent依赖。
        db=fresh('allcut');F.tx(db,[I('cc_failure',barrier_id='all.exit.0',reason='cache_miss',evidence_body=B,audit_body=B),
            attempt('all',bid='retry',n=2,previous='all.exit.0')])
        F.tx(db,ack('all',bid='retry'));F.tx(db,ack('all','exit.1'));F.tx(db,closure('all',bid='retry'))
        F.tx(db,progress());F.tx(db,X.closure())
        F.tx(db,R.close()+R.settle(kind='effect_resolved')+[T.report(state='not_sent')]+X.settlement()+X.release())
        before=F.snapshot(db);late=ack('all',cancelstate='in_flight')
        try:F.tx(db,late,len(late)-1)
        except RuntimeError:check('迟到ACK和资源失效共同回滚',F.snapshot(db)==before)
        else:raise AssertionError('未注入异常')
        F.tx(db,late);check('迟到关闭ACK重开旧资源',db.execute('SELECT count(*) FROM cr_risk_hold').fetchone()[0],1)
        check('迟到来源精确记录',db.execute('SELECT source_kind FROM cr_release_invalidation').fetchone()[0],'cancel_closure_ack')
        # RUN seal至来源commit之间，预写coverage也不能靠后封存ACK改变切点事实。
        db=fresh('allcut');pending=F.fence(revision=2)
        marker=next(i for i,s in enumerate(pending) if s[0].startswith('INSERT INTO run_protection_commit '))
        pending[marker:marker]=ack('all',cancelstate='in_flight')
        denied('RUN窗口拒绝新关闭ACK',db,pending,'pending_cut')
        # 重采来源只能新建汇总；旧关闭历史及拒绝不可改写。
        db=fresh();F.tx(db,progress());F.tx(db,[revoke('close.all')])
        check('撤回隐藏当前公开投影',db.execute('SELECT count(*) FROM cv_current').fetchone()[0],0)
        check('撤回保留公开历史',db.execute('SELECT count(*) FROM cv_history').fetchone()[0],5)
        F.tx(db,closure('all',hid='close.all.new'))
        check('重新验证使用新关闭身份',db.execute('SELECT count(*) FROM cc_closure').fetchone()[0],3)
        denied('无撤回不能替换有效关闭',db,closure('all',hid='close.all.duplicate'),'closure_already_valid')
        denied('旧ordinary撤回不复活签发',db,dispatch())
        db=fresh('allcut')
        for e in ('exit.0','exit.1'):F.tx(db,[I('ce_retirement',exit_id=e,supervisor_evidence_body=B)])
        F.tx(db,closure('all',retired=('exit.0','exit.1')))
        check('退休关闭不伪造未发送',db.execute("SELECT disposition FROM cf_disposition WHERE permit_id='cancel.1'").fetchone()[0],'unknown')
        db=fresh();F.tx(db,progress());F.tx(db,X.closure())
        F.tx(db,R.close()+R.settle(kind='effect_resolved')+[T.report(state='not_sent')]+X.settlement()+X.release())
        check('完整链可核销',db.execute('SELECT count(*) FROM cr_risk_hold').fetchone()[0],0)
        F.tx(db,[revoke('close.all')]);check('关闭撤回同事务重开占用',db.execute('SELECT count(*) FROM cr_risk_hold').fetchone()[0],1)
        check('关闭撤回同事务锁存',db.execute('SELECT count(*) FROM cr_device_protection').fetchone()[0],1)
        for table in G.TABLES:
            if not db.execute('SELECT 1 FROM '+table).fetchone():continue
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for sql in (f'UPDATE {table} SET {column}={column}',f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                denied(table+sql.split()[0],db,[(sql,())])
        for d in connections:
            assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert d.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库完整性',True);return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'cancel-closure-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='119表ordinary-all关闭候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'cancel-closure-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
