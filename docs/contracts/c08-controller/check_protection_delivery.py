"""实际232表Controller与独立5表Seamer内存库的P3/P4实验；不连接服务。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import check_prepare_deny_storage as P
import protection_delivery_model as M
import build_protection_delivery as G
I,U,F,J,A,B,D,u=P.I,P.U,P.F,P.J,P.A,P.B,P.D,P.u
HERE=G.HERE;ROOT=HERE.parents[2]
NAMES=('PROTECTION_DELIVERY.md','protection-delivery.sql','protection-receiver.sql',
 'build_protection_delivery.py','protection-delivery.schema.json','protection_delivery_model.py','check_protection_delivery.py')
INPUTS=list(dict.fromkeys(P.INPUTS+[HERE/n for n in NAMES]))

def controller(prepare=True,retired=False,apply=True,abandoned=False):
    db=P.fresh();db.executescript((HERE/'protection-delivery.sql').read_text(encoding='utf-8'))
    U.tx(db,P.registration(db))
    if prepare:
        U.tx(db,J.encoding());U.tx(db,J.send_encoding());U.tx(db,[J.written('encode.prepare',12)]);U.tx(db,J.reply())
    U.tx(db,P.run_cut(db))
    if prepare:
        U.tx(db,P.deny(tick=21));U.tx(db,[J.attempted('deny.request.prepare',21),J.written('deny.request.prepare',21)])
        steps=U.mutate(P.ack(),'ij_frame',observed_tick=u(23))
        steps=U.mutate(steps,'pd_deny_ack',effective_tick=u(22),received_tick=u(23))
        U.tx(db,U.mutate(steps,'ij_commit',committed_tick=u(23)))
    U.tx(db,P.closure('f',[('prepare','deny_ack' if prepare else 'never_attempted')],cid='run.preparations',tick=24))
    for n,eid in enumerate(('exit.0','exit.1')):
        bid='run.barrier.'+str(n)
        if retired and n==1:
            U.tx(db,[P.E.retire(eid)]);kind='supervisor_retired';bid=None
        else:
            if abandoned and n==0:
                U.tx(db,F.adapt([A.attempt('abandoned',eid=eid)]));U.tx(db,F.adapt([A.failure('abandoned')]))
                U.tx(db,F.adapt([A.attempt(bid,eid=eid,ordinal=2,previous='abandoned')]))
                U.tx(db,F.adapt(A.ack('abandoned',eid,items=False,tick=25)))
            else:U.tx(db,F.adapt([A.attempt(bid,eid=eid)]))
            U.tx(db,F.adapt(A.ack(bid,eid,items=False,tick=25)));kind='worker_ack'
        U.tx(db,F.adapt([A.I('ce_result_binding',fence_id='f',exit_id=eid,barrier_id=bid,kind=kind,binding_body=B),F.F.result(eid,items=(),kind=kind)[-1]]))
    if apply:U.tx(db,application())
    return db
def application():return U.mutate(F.adapt([F.F.application()]),'ce_application',prepare_closure_id='run.preparations')
def revoke(db,kind):
    steps={'prepare':[I('pd_ack_revocation',ack_id='deny.ack.prepare',reason_body=B,audit_body=B,outbox_body=B)],
      'barrier':[I('ra_barrier_revocation',barrier_id='run.barrier.0',reason_body=B,audit_body=B)],
      'retirement':[I('cu_revocation',kind='retirement',object_id='exit.1',reason_body=B,audit_body=B)]}[kind]
    U.tx(db,steps)
def plan(db,bindings,pid='plan',omit=None):
    steps=[I('sp_plan',plan_id=pid,plan_digest=D,target_count=len(bindings),plan_body=M.canonical(bindings))]
    steps += [I('sp_target',plan_id=pid,target_id=target,binding_body=M.canonical(binding)) for target,binding in bindings.items()]
    steps += [I('sp_plan_commit',plan_id=pid,validation_body=B)]
    U.tx(db,steps if omit is None else steps[:omit]+steps[omit+1:])
def summary(db):return db.execute("SELECT observed_state,observed_targets FROM sp_observed_summary WHERE plan_id='plan'").fetchone()

def run():
    assert (HERE/'protection-delivery.schema.json').read_bytes()==G.encoded()
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected);checks.append(dict(name=name,observed=actual,expected=expected))
    def c(**kw):db=controller(**kw);connections.append(db);return db
    def s(bindings):
        db=M.receiver();connections.append(db);plan(db,bindings);return db
    def denied(name,db,action):
        before=U.snapshot(db)
        try:action()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,M.jsonschema.ValidationError):pass
        else:raise AssertionError(name+':未拒绝')
        check(name+'全库不变',U.snapshot(db)==before)
    try:
        M.jsonschema.Draft202012Validator.check_schema(G.schema())
        db=c();check('Controller完整表数',len(U.snapshot(db)),232)
        original=M.export_event(db,'f');scope=original['binding']['controller_scope']
        check('P3初始当前资格',original['state'],'applied')
        check('P3初始事件同事务',db.execute('SELECT revision,state FROM ra_status_event').fetchall(),[(1,'applied')])
        db=c(abandoned=True);U.tx(db,[I('ra_barrier_revocation',barrier_id='abandoned',reason_body=B,audit_body=B)])
        check('未采用ACK撤回不污染当前应用',M.export_event(db,'f')['state'],'applied')
        check('未采用ACK撤回不产生失效事件',db.execute('SELECT count(*) FROM ra_status_event').fetchone()[0],1)
        for kind in ('prepare','barrier','retirement'):
            db=c(retired=kind=='retirement');before=db.execute('SELECT receipt_body FROM ce_application').fetchone()
            revoke(db,kind);value=M.export_event(db,'f')
            check(kind+'当前失效',value['state'],'indeterminate')
            check(kind+'发布修订二',value['status_revision'],'2')
            check(kind+'历史回执保持',db.execute('SELECT receipt_body FROM ce_application').fetchone()==before)
            check(kind+'完整有效投影消失',db.execute('SELECT count(*) FROM pd_valid_application').fetchone()[0],0)
            check(kind+'当前查原返回撤回状态',M.export_event(db,'f')['cause']['kind'],
              {'prepare':'prepare_closure','barrier':'run_barrier_ack','retirement':'retirement'}[kind])
            check(kind+'历史事件不重新标当前',M.export_event(db,'f',1)['state'],'applied')
        db=c();revoke(db,'prepare');revoke(db,'barrier')
        check('多原因保留两份撤回原件',db.execute('SELECT count(*) FROM ra_invalid_evidence').fetchone()[0],2)
        check('多个原因不重复发布失效',db.execute('SELECT count(*) FROM ra_status_event').fetchone()[0],2)
        for kind in ('prepare','barrier','retirement'):
            db=c(retired=kind=='retirement',apply=False);revoke(db,kind)
            denied(kind+'先撤回不能应用',db,lambda:U.tx(db,application()))
        for kind in ('prepare','barrier','retirement'):
            db=c(retired=kind=='retirement')
            db.execute("CREATE TRIGGER inject_event BEFORE INSERT ON ra_status_event WHEN NEW.revision=2 BEGIN SELECT RAISE(ABORT,'injected'); END")
            denied(kind+'通知失败回滚撤回',db,lambda:revoke(db,kind))
        db=c(apply=False)
        db.execute("CREATE TRIGGER inject_event BEFORE INSERT ON ra_status_event BEGIN SELECT RAISE(ABORT,'injected'); END")
        denied('初始通知失败回滚P3',db,lambda:U.tx(db,application()))
        db=c();revoke(db,'prepare');invalid=M.export_event(db,'f')
        peer=copy.deepcopy(original);peer['binding']['controller_scope']['authority_service_id']='controller.peer';M.seal(peer)
        # 第二目标为独立手写的输送夹具，不声称另一个Controller进程已运行。
        seamer=s({'one':original['binding'],'two':peer['binding']})
        check('Seamer完整表数',len(U.snapshot(seamer)),5)
        check('完整目标未收到保持pending',summary(seamer),('pending',0))
        for fail in (0,1):denied('P4逐步失败'+str(fail),seamer,lambda:M.receive(seamer,'plan','one',original,scope,fail_after=fail))
        check('首次P4存储',M.receive(seamer,'plan','one',original,scope),'stored')
        check('缺第二目标不汇总',summary(seamer),('pending',1))
        before=U.snapshot(seamer);check('提交响应丢失只查原',M.receive(seamer,'plan','one',original,scope),'duplicate')
        check('重复无第二效果',U.snapshot(seamer)==before)
        M.receive(seamer,'plan','two',peer,peer['binding']['controller_scope'])
        check('完整目标仅汇总已观察应用',summary(seamer),('applied',2))
        M.receive(seamer,'plan','one',invalid,scope)
        check('收到失效降低已观察汇总',summary(seamer),('indeterminate',2))
        M.receive(seamer,'plan','one',original,scope)
        check('旧applied重投不能复活',summary(seamer),('indeterminate',2))
        reverse=s({'one':original['binding']})
        M.receive(reverse,'plan','one',invalid,scope);M.receive(reverse,'plan','one',original,scope)
        check('失效先到再补历史保持失效',summary(reverse),('indeterminate',1))
        check('两修订原件都保留',reverse.execute('SELECT count(*) FROM sp_observation').fetchone()[0],2)
        for key in ('operation_id','run_id','selector_digest','target_set_digest','deny_through_generation'):
            wrong=copy.deepcopy(original);wrong['binding'][key]=('2' if key=='deny_through_generation' else 'sha256:'+'0'*64 if key.endswith('digest') else 'other');M.seal(wrong)
            receiver=s({'one':original['binding']});denied('错绑定'+key,receiver,lambda:M.receive(receiver,'plan','one',wrong,scope))
        for which in ('origin_scope','controller_scope'):
            for field in ('authority_service_id','database_instance_id'):
                wrong=copy.deepcopy(original);wrong['binding'][which][field]='other';M.seal(wrong)
                receiver=s({'one':original['binding']});denied('跨域'+which+field,receiver,lambda:M.receive(receiver,'plan','one',wrong,wrong['binding']['controller_scope']))
        denied('认证域不能自填',reverse,lambda:M.receive(reverse,'plan','one',original,{'authority_service_id':'other','database_instance_id':'database.1'}))
        wrong=copy.deepcopy(original);wrong['receipt_ref']['bytes_digest']='sha256:'+'0'*64;M.seal(wrong)
        denied('同修订异正文不能覆盖',reverse,lambda:M.receive(reverse,'plan','one',wrong,scope))
        receiver=s({'one':original['binding']});M.receive(receiver,'plan','one',invalid,scope)
        denied('先收到失效也固定原回执身份',receiver,lambda:M.receive(receiver,'plan','one',wrong,scope))
        for field,value in [('status_revision','3'),('status_revision','01'),('state','applied'),('observation_digest','sha256:'+'0'*64)]:
            wrong=copy.deepcopy(invalid);wrong[field]=value
            if field!='observation_digest':M.seal(wrong)
            denied('格式或摘要'+field+value,reverse,lambda:M.receive(reverse,'plan','one',wrong,scope))
        for field in ('receipt_ref','prepare_closure_ref','cut_ref'):
            wrong=copy.deepcopy(invalid);wrong.pop(field);M.seal(wrong)
            denied('缺原件'+field,reverse,lambda:M.receive(reverse,'plan','one',wrong,scope))
            wrong=copy.deepcopy(original);wrong[field]['id']='other';M.seal(wrong)
            receiver=s({'one':original['binding']});M.receive(receiver,'plan','one',invalid,scope)
            denied('跨修订不能换原件'+field,receiver,lambda:M.receive(receiver,'plan','one',wrong,scope))
        wrong=copy.deepcopy(invalid);wrong['cause']['object_id']='other';M.seal(wrong)
        denied('准备撤回原因错配',reverse,lambda:M.receive(reverse,'plan','one',wrong,scope))
        for omit in range(3):
            receiver=M.receiver();connections.append(receiver)
            denied('P1导入缺写'+str(omit),receiver,lambda:plan(receiver,{'one':original['binding']},omit=omit))
        receiver=s({});check('已证明空全集可汇总',summary(receiver),('applied',0))
        receiver=s({'one':original['binding']})
        row=I('sp_observation',plan_id='plan',target_id='one',revision=1,state='applied',binding_body=M.canonical(original['binding']),
          identity_body=M.canonical(M.identity(original)),observation_digest=original['observation_digest'],body=M.canonical(original))
        commit=I('sp_observation_commit',plan_id='plan',target_id='one',revision=1,audit_body=B,outbox_body=B)
        denied('P4缺提交封存',receiver,lambda:U.tx(receiver,[row]))
        denied('P4缺原观察',receiver,lambda:U.tx(receiver,[commit]))
        for database,tables in ((reverse,('sp_plan','sp_target','sp_plan_commit','sp_observation','sp_observation_commit')),
          (db,('ra_status_event',))):
            for table in tables:
                check(table+'有非空不可变样本',database.execute('SELECT count(*) FROM '+table).fetchone()[0]>0)
                col=database.execute('PRAGMA table_info('+table+')').fetchone()[1]
                for stmt in (f'UPDATE {table} SET {col}={col}','DELETE FROM '+table):denied(table+stmt.split()[0],database,lambda:database.execute(stmt))
        check('两库外键完整',db.execute('PRAGMA foreign_key_check').fetchall()+reverse.execute('PRAGMA foreign_key_check').fetchall(),[])
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'protection-delivery-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=232,seamer_tables=5,
          sqlite_version=sqlite3.sqlite_version,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
