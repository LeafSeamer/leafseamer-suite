"""237表Controller与六表准备接收库的离线实验，不连接网络或设备。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import build_preparation_delivery as G
import preparation_delivery_model as M
import check_preparation_completion as C
I,U,F,J,A,B,D,u=C.I,C.U,C.F,C.J,C.A,C.B,C.D,C.u
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(C.INPUTS+[HERE/n for n in ('PREPARATION_DELIVERY.md','build_preparation_delivery.py',
 'preparation-delivery.schema.json','preparation-receiver.sql','preparation_delivery_model.py','check_preparation_delivery.py')]))

def binding(authority='controller',database='database.1',generation='1',mode='arm',execution=None):
    return dict(controller_scope=dict(authority_service_id=authority,database_instance_id=database),
      origin_scope=dict(authority_service_id='seamer',database_instance_id='source.db'),preparation_id='p',run_id='run',
      generation=generation,mode=mode,execution_id=execution,request_digest=D)

def empty(authority='controller',database='database.1'):
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(C.G.build().decode())
    db.execute('INSERT INTO controller_scope VALUES(1,?,?,?)',(authority,database,'controller-storage/0.1.0-draft.1'))
    return db

def first_close(authority='controller',database='database.1',generation='1',mode='arm',execution=None):
    db=empty(authority,database)
    for eid in ('exit.0','exit.1'):
        C.tx(db,U.mutate(F.adapt([F.F.exit_step(eid)]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    steps=F.adapt(F.F.P.close(first=True,generation=generation))
    steps=[('run_deny_event' if t=='cp_deny_event' else t,v) for t,v in steps if t!='cp_protection_target']
    steps=U.mutate(steps,'cp_request',mode=mode,execution_id=execution)
    index=next(i for i,(t,v) in enumerate(steps) if t=='cp_protection')+1
    steps[index:index]=[I('cp_protection_target',close_id='close.p.one',target_id=e,target_body=B) for e in ('exit.0','exit.1')]
    steps[-1:-1]=[I('ce_fence',fence_id='f',protection_id=None,close_id='close.p.one',issued_cut_revision=u(0),cut_body=B)]+[
      I('ce_target',fence_id='f',exit_id=e,ledger_digest=D,target_body=B) for e in ('exit.0','exit.1')]+[
      I('ce_cut_commit',fence_id='f',audit_body=B,outbox_event_id='cut.f',outbox_body=B)]
    C.tx(db,C.Q.capture(db,steps,'run','f',(),0,20))
    return db

def finish_first(db):
    C.tx(db,C.Q.closure('f',[],cid='run.preparations',tick=24))
    for n,e in enumerate(('exit.0','exit.1')):
        bid='run.barrier.'+str(n)
        C.tx(db,F.adapt([A.attempt(bid,eid=e)]));C.tx(db,F.adapt(A.ack(bid,e,items=False,tick=25)))
        C.tx(db,F.adapt([A.I('ce_result_binding',fence_id='f',exit_id=e,barrier_id=bid,kind='worker_ack',binding_body=B),F.F.result(e,items=())[-1]]))
    C.tx(db,C.R.P.application())
    steps=F.adapt(F.F.P.complete(previous='1'))
    steps.insert(2,I('pc_binding',completion_id='evidence.p',fence_id='f',receipt_id='receipt.f',receipt_body=B,binding_body=B,audit_body=B))
    C.tx(db,steps)

def observation_steps(value):
    key=('plan','target',value['preparation_revision'].zfill(20),int(value['protection_revision']))
    return [('INSERT INTO po_observation VALUES(?,?,?,?,?,?,?,?,?)',key+(value['state'],value['protection_state'],M.canonical(value['binding']),value['observation_digest'],M.canonical(value))),
      ('INSERT INTO po_observation_commit VALUES(?,?,?,?,?,?)',key+(B,B))]

def summary(db):return db.execute('SELECT observed_state,observed_targets FROM po_closure_summary WHERE plan_id=?',('plan',)).fetchone()

def run():
    assert (HERE/'preparation-delivery.schema.json').read_bytes()==G.encoded()
    M.jsonschema.Draft202012Validator.check_schema(G.schema())
    checks=[];connections=[]
    def check(n,a,e=True):assert a==e,(n,a,e);checks.append(dict(name=n,observed=a,expected=e))
    def controller(**kw):db=C.fixture(**kw);connections.append(db);return db
    def first(**kw):db=first_close(**kw);connections.append(db);return db
    def receiver(bindings=None,sealed=True):
        db=M.receiver();connections.append(db)
        if sealed:M.execute(db,M.plan_steps('plan',bindings or {'target':binding()},B))
        return db
    def receive(db,v,target='target',**kw):return M.receive(db,'plan',target,v,v['binding']['controller_scope'],**kw)
    def denied(n,db,action):
        before=U.snapshot(db)
        try:action()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,M.jsonschema.ValidationError):pass
        else:raise AssertionError(n+':未拒绝')
        check(n+'全库不变',U.snapshot(db)==before)
    try:
        c=controller();accepted=M.export_event(c,'p','1','0');applied=M.export_event(c,'p','2','0');closing=M.export_event(c,'p')
        C.tx(c,C.complete());closed=M.export_event(c,'p')
        C.tx(c,[C.revoke('barrier')]);invalid=M.export_event(c,'p')
        check('正常准备路径三种历史状态',[v['state'] for v in (accepted,applied,closing)],['accepted','applied','closing'])
        check('历史成功导出字节不因撤回改变',M.export_event(c,'p','4','1'),closed)
        check('当前导出读取最新失效',(invalid['preparation_revision'],invalid['protection_revision'],invalid['protection_state']),('4','2','indeterminate'))
        check('当前完成保留原准备回执',invalid['applied_receipt_ref'],applied['applied_receipt_ref'])
        check('原回执使用精确字节摘要',closed['completion']['receipt_ref']['bytes_digest'],M.digest(B))
        for kind,cause in [('prepare','prepare_closure'),('barrier','run_barrier_ack'),('retirement','retirement')]:
            actual=controller(retired=kind=='retirement');C.tx(actual,C.complete());C.tx(actual,[C.revoke(kind)])
            value=M.export_event(actual,'p');check(kind+'失效原件原因',value['cause']['kind'],cause)
            s=receiver();receive(s,value);check(kind+'失效先到接收',summary(s),('indeterminate',1))
            receive(s,M.export_event(actual,'p','4','1'));check(kind+'成功历史迟到不回退',summary(s),('indeterminate',1))
        denied('历史导出必须显式保护修订',c,lambda:M.export_event(c,'p','4'))
        denied('非closed不能指定保护修订',c,lambda:M.export_event(c,'p','2','1'))
        denied('未知准备不伪造记录',c,lambda:M.export_event(c,'missing'))
        for order in ((accepted,applied,closing,closed,invalid),(invalid,closing,accepted,closed,applied),(closed,applied,accepted,closing,invalid)):
            db=receiver();check('六表接收库',len(U.snapshot(db)),6)
            for v in order:check('合法到达'+v['state']+v['protection_revision'],receive(db,v),'stored')
            check('乱序汇总不回退',summary(db),('indeterminate',1))
            before=U.snapshot(db);check('丢响应后重复只查原',receive(db,closed),'duplicate')
            check('重复不重写账本',U.snapshot(db)==before)
        db=receiver();receive(db,applied);check('准备applied不是关闭applied',summary(db),('pending',1))
        for state in ('rejected','indeterminate'):
            d=empty();connections.append(d);C.tx(d,F.adapt(F.F.P.register()));C.tx(d,F.adapt(F.F.P.change(state=state)))
            v=M.export_event(d,'p');check(state+'真实准备状态可导出',v['state'],state)
            s=receiver();receive(s,v);check(state+'不冒充完成保护',summary(s),('pending',1))
        c2=first(authority='controller.second',database='database.second',generation='99999999999999999999')
        first_pending=M.export_event(c2,'p');check('关闭先到revision1不发grant',(first_pending['state'],first_pending['preparation_revision'],first_pending['applied_receipt_ref']),('closing','1',None))
        check('大代次无浮点损失',first_pending['binding']['generation'],'99999999999999999999')
        denied('关闭先到后不能补发grant',c2,lambda:C.tx(c2,F.adapt(F.F.P.change())))
        finish_first(c2);first_done=M.export_event(c2,'p')
        check('关闭先到真实完成',first_done['preparation_revision'],'2')
        check('关闭先到始终无准备grant',c2.execute('SELECT count(*) FROM cp_grant').fetchone()[0],0)
        bindings={'target':binding(),'second':binding('controller.second','database.second','99999999999999999999')}
        db=receiver(bindings);receive(db,closed);check('缺第二Controller保持pending',summary(db),('pending',1))
        receive(db,first_done,'second');check('两个真实库完成后汇总',summary(db),('applied',2))
        receive(db,first_pending,'second');check('迟到closing不降低关闭观察',summary(db),('applied',2))
        C.tx(c2,[C.revoke('barrier')]);receive(db,M.export_event(c2,'p'),'second');check('第二Controller失效优先',summary(db),('indeterminate',2))
        d=first(mode='recovery',execution='execution');finish_first(d);v=M.export_event(d,'p')
        s=receiver({'target':binding(mode='recovery',execution='execution')});receive(s,v);check('恢复模式来源独立绑定',summary(s),('applied',1))
        # 合法结构、同认证域、同计划绑定的矛盾证据必须持久留痕，不仅抛异常留下旧绿色状态。
        conflicts=[]
        v=copy.deepcopy(closed);v['completion']['receipt_ref']['bytes_digest']='sha256:'+'b'*64;conflicts.append(('same_revision_conflict',M.seal(v)))
        v=copy.deepcopy(invalid);v['completion']['id']='other.completion';conflicts.append(('completion_conflict',M.seal(v)))
        v=copy.deepcopy(applied);v['applied_receipt_ref']['id']='other.receipt';conflicts.append(('receipt_conflict',M.seal(v)))
        d=empty();connections.append(d);C.tx(d,F.adapt(F.F.P.register()));C.tx(d,F.adapt(F.F.P.change(state='rejected')))
        conflicts.append(('history_conflict',M.export_event(d,'p')))
        for reason,value in conflicts:
            db=receiver();receive(db,closed)
            check(reason+'持久冲突',receive(db,value),'conflict')
            check(reason+'目标未确认',summary(db),('unconfirmed',1))
            check(reason+'诊断类别',db.execute('SELECT kind FROM po_conflict').fetchone()[0],reason)
            check(reason+'冲突去重',receive(db,value),'conflict_duplicate')
            another=copy.deepcopy(value)
            if another['close_ref'] is not None:another['close_ref']['bytes_digest']='sha256:'+'c'*64
            else:another=copy.deepcopy(conflicts[0][1]);another['completion']['receipt_ref']['bytes_digest']='sha256:'+'c'*64
            M.seal(another)
            before=U.snapshot(db);check(reason+'不同后续冲突保持首证据',receive(db,another),'conflict_retained')
            check(reason+'冲突存储不增长',U.snapshot(db)==before)
            receive(db,closed);receive(db,invalid);check(reason+'后续正常通知不能清冲突',summary(db),('unconfirmed',1))
            db=receiver();receive(db,closed);denied(reason+'冲突事务异常',db,lambda:receive(db,value,fail_after=0))
            db.execute("CREATE TRIGGER fail_conflict BEFORE INSERT ON po_conflict BEGIN SELECT RAISE(ABORT,'injected'); END")
            denied(reason+'冲突写入失败',db,lambda:receive(db,value))
        for index in (0,1):
            db=receiver();denied('接收逐写异常'+str(index),db,lambda:receive(db,closed,fail_after=index))
            steps=observation_steps(closed);denied('接收缺写'+str(index),db,lambda:M.execute(db,steps[:index]+steps[index+1:]))
        plan=M.plan_steps('plan',{'target':binding()},B)
        for index in range(len(plan)):
            db=receiver(sealed=False);denied('计划缺写'+str(index),db,lambda:M.execute(db,plan[:index]+plan[index+1:]))
            denied('计划逐写异常'+str(index),db,lambda:M.execute(db,plan,fail_after=index))
        db=receiver(sealed=False);denied('空计划不能自动成功',db,lambda:M.execute(db,M.plan_steps('plan',{},B)))
        denied('重复准备目标不能冒充完整集合',db,lambda:M.execute(db,M.plan_steps('plan',{'a':binding(),'b':binding()},B)))
        db=receiver();denied('封存后不能追加目标',db,lambda:M.execute(db,[('INSERT INTO po_target VALUES(?,?,?)',('plan','extra',M.canonical(binding('other'))))]))
        for name,index,value in [('body_capacity',8,b'x'*16385),('revision_capacity',2,u(5)),('state_pair',5,'pending')]:
            steps=observation_steps(closed);args=list(steps[0][1]);args[index]=value;steps[0]=(steps[0][0],tuple(args))
            denied('SQL后备约束'+name,db,lambda steps=steps:M.execute(db,steps))
        for field,value in [('preparation_id','other'),('run_id','other'),('generation','2'),('request_digest','sha256:'+'b'*64)]:
            v=copy.deepcopy(closed);v['binding'][field]=value;M.seal(v)
            db=receiver();denied('计划来源错配'+field,db,lambda:receive(db,v))
        db=receiver();denied('正文不能授予认证身份',db,lambda:M.receive(db,'plan','target',closed,dict(authority_service_id='other',database_instance_id='database.1')))
        bad=[]
        for field,value in [('preparation_revision',4),('preparation_revision','04'),('previous_revision','2'),('protection_revision','0'),('observation_digest','sha256:'+'0'*64)]:
            v=copy.deepcopy(closed);v[field]=value
            if field!='observation_digest':M.seal(v)
            bad.append((field,v))
        v=copy.deepcopy(closed);v['completion']['cut_ref']['id']='other';bad.append(('cut',M.seal(v)))
        v=copy.deepcopy(closed);v['cause']['object_id']='other';bad.append(('initial_cause',M.seal(v)))
        v=copy.deepcopy(invalid);v['cause']=dict(kind='prepare_closure',object_id='other');bad.append(('closure_cause',M.seal(v)))
        v=copy.deepcopy(closed);v['binding']['generation']='1\n';bad.append(('generation_newline',M.seal(v)))
        v=copy.deepcopy(closed);v['binding']['generation']=1;bad.append(('generation_number',M.seal(v)))
        v=copy.deepcopy(closed);v['binding']['execution_id']='unexpected';bad.append(('arm_execution',M.seal(v)))
        v=copy.deepcopy(closed);v['binding']['mode']='recovery';bad.append(('recovery_without_execution',M.seal(v)))
        v=copy.deepcopy(closed);v['binding']['preparation_id']='x'*129;bad.append(('identifier_capacity',M.seal(v)))
        v=copy.deepcopy(closed);v['extra']=True;bad.append(('extra',M.seal(v)))
        v=copy.deepcopy(first_done);v['applied_receipt_ref']=applied['applied_receipt_ref'];bad.append(('close_first_fake_grant',M.seal(v)))
        for name,v in bad:
            db=receiver();denied('结构或关联反例'+name,db,lambda:receive(db,v))
        # 拒绝前面的验证错误不写冲突账本；错误身份不能污染计划。
        check('非法来件不污染目标',summary(db),('pending',0))
        db=receiver();receive(db,closed);receive(db,conflicts[0][1])
        for table in M.TABLES:
            for op in ('UPDATE','DELETE'):
                sql=f'UPDATE {table} SET plan_id=plan_id' if op=='UPDATE' else f'DELETE FROM {table}'
                denied(table+op+'不可变',db,lambda sql=sql:db.execute(sql))
        check('Controller外键完整',c2.execute('PRAGMA foreign_key_check').fetchall(),[])
        check('接收库外键完整',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'preparation-delivery-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        d=json.loads(read(target));assert set(d['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert d['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=237,receiver_tables=6,sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
