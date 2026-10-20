"""91表公开修订/取消参考实验；仅内存SQLite，不连接服务或设备。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE.parent/'c08-controller'))
import check_command as C
F,I,B,D=C.F,C.I,C.B,C.D
def U(value):
    return '00000000000000000000' if value == 0 else C.U(value)
INPUTS=list(dict.fromkeys(C.INPUTS+[HERE/n for n in
    ('storage.sql','STORAGE.md','check_storage.py','command.schema.json')]))


def public(steps,n,key='one',members=(),cancel=None,cancel_revision=None):
    """装配人工预期集合；不读取待测视图生成快照成员。"""
    steps=list(steps)
    at=next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO cm_commit '))
    cmd,sid='command.'+key,'snapshot.'+key+'.'+str(n)
    extra=[]
    if n==1:
        extra.append(I('cv_metadata',command_id=cmd,initial_revision=U(1),metadata_digest=D,metadata_body=B))
    extra += [I('cv_snapshot',snapshot_id=sid,command_id=cmd,state_revision=U(n),state_digest=D,
        total=U(len(members)),snapshot_digest=D,manifest_body=B,validation_body=B)]
    extra += [I('cv_snapshot_member',snapshot_id=sid,ordinal=U(i),evidence_id=e,
        evidence_revision=U(r)) for i,(e,r) in enumerate(members)]
    extra += [I('cv_record',command_id=cmd,revision=U(n),state_digest=D,metadata_digest=D,
        snapshot_id=sid,cancellation_id=cancel,cancellation_revision=U(cancel_revision) if cancel else None,
        record_digest=D,record_body=B,validation_body=B)]
    steps[at:at]=extra
    return steps


def evidence(eid,n,kind='observation',key='one',revision=1,subject=None,source=None):
    return I('cv_evidence',evidence_id=eid,revision=U(revision),command_id='command.'+key,
        first_state_revision=U(n),kind=kind,source_digest=D,view_digest=D,
        source_body=B,view_body=B,validation_body=B,
        decision_id=source if kind=='decision' else None,release_id=source if kind=='release' else None,
        resolution_id=source if kind=='resolution' else None,
        subject_id=subject,subject_revision=U(1) if subject else None,
        protection_ref_body=B if subject else None)


def cancel(n=2,key='one',cid='cancel',attempts=(),permits=(),cut=0,state_args=None,members=()):
    cmd='command.'+key
    steps=[
        I('cv_cancel_key',key_id='key.'+cid,namespace_id='ns',operation_id='cancelCommand',
          idempotency_key='idem.'+cid,request_digest=D,content_body=B,authorization_body=B),
        I('cv_cancel',cancellation_id=cid,command_id=cmd,key_id='key.'+cid,mode='before_dispatch_only',
          accepted_revision=U(n-1),accepted_state_digest=D,initial_revision=U(1),
          cut_revision=U(cut),cut_digest=D,cut_body=B,policy_body=B),
        I('cv_cancel_deny',command_id=cmd,cancellation_id=cid),
        *[I('cv_cancel_attempt',cancellation_id=cid,attempt_id=a) for a in attempts],
        *[I('cv_cancel_target',cancellation_id=cid,exit_id=e) for e in ('exit.0','exit.1')],
        *[I('cv_cancel_permit',cancellation_id=cid,permit_id=p) for p in permits],
        I('cv_cancel_revision',cancellation_id=cid,revision=U(1),command_id=cmd,state_revision=U(n),
          state='requested',future_writes='pending',closure_validation_body=None,
          result_validation_body=None,operation_digest=D,operation_body=B)]
    steps += public(C.revision(n,'observe',key,**(state_args or {})),n,key,members,cid,1)
    steps += [
        I('cv_cancel_receipt',cancellation_id=cid,initial_revision=U(1),initial_operation_digest=D,
          receipt_digest=D,receipt_body=B),
        I('cv_cancel_commit',cancellation_id=cid,audit_body=B,outbox_id='cancel.event.'+cid,outbox_body=B)]
    return steps


UNKNOWN=dict(phase='finished',outcome='unknown',effect='possible',resource='unresolved',
             latched=1,terminal=5,attempts=('a',))
SENT=dict(phase='dispatching',effect='possible',resource='held',attempts=('a',))
WAITING=dict(phase='awaiting_evidence',effect='possible',resource='held',attempts=('a',))


def progress(n=7,revision=2,state='indeterminate',future='pending',state_args=None):
    return [I('cv_cancel_revision',cancellation_id='cancel',revision=U(revision),command_id='command.one',
        state_revision=U(n),state=state,future_writes=future,
        closure_validation_body=B if future=='closed' else None,
        result_validation_body=B if state in ('confirmed','unsupported','failed','too_late') else None,
        operation_digest=D,operation_body=B)]+public(C.revision(n,'observe',**(state_args or UNKNOWN)),
        n,cancel='cancel',cancel_revision=revision)


def run():
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='queued'):
        db=F.L.fixture();connections.append(db)
        for f in ('fence.sql','barrier-attempt.sql','resource.sql','command.sql'):
            db.executescript((C.HERE/f).read_text(encoding='utf8'))
        db.executescript((HERE/'storage.sql').read_text(encoding='utf8'))
        db.execute(*F.A.namespace())
        F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        if stage=='empty':return db
        F.tx(db,public(C.initial(),1))
        if stage=='queued':return db
        F.tx(db,public(C.prepare(),2))
        if stage=='prepared':return db
        F.tx(db,public(C.dispatch(),3))
        if stage=='sent':return db
        F.tx(db,public(C.report(**WAITING),4))
        if stage=='waiting':return db
        F.tx(db,public(C.revision(5,'timeout',**UNKNOWN),5))
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as exc:
            check(name,str(exc) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def atomic(name,stage,steps):
        for i in range(len(steps)):
            db=fresh(stage)
            denied(name+'缺写'+str(i),db,steps[:i]+steps[i+1:])
            db=fresh(stage);before=F.snapshot(db)
            try:F.tx(db,steps,cut=i)
            except RuntimeError:check(name+'主动异常'+str(i),F.snapshot(db)==before)
            else:raise AssertionError('没有注入异常')
    def mutation(steps,table,field,value):
        return F.P.mutate(steps,table,field,value)
    try:
        check('91表组合',len(F.snapshot(fresh())),91)
        atomic('初始公开修订','empty',public(C.initial(),1))
        atomic('排队取消完整写集','queued',cancel())
        atomic('在途取消完整写集','sent',cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=SENT))
        first=[evidence('observation.a',2)]+public(C.revision(2,'observe'),2,members=(('observation.a',1),))
        atomic('新证据与完整快照','queued',first)
        db=fresh();F.tx(db,cancel())
        check('取消初始仅requested',db.execute('SELECT state,future_writes FROM cv_cancel_current').fetchall(),
              [('requested','pending')])
        check('取消受理不伪造命令终态',db.execute('SELECT phase,outcome FROM cm_current').fetchone(),
              ('queued','pending'))
        before=F.snapshot(db)
        check('提交后响应丢失查询原回执',db.execute(
            'SELECT receipt_digest FROM cv_cancel_receipt WHERE cancellation_id=?',('cancel',)).fetchone(),(D,))
        check('查原没有新增写',F.snapshot(db)==before)
        denied('同父命令不可换身份重建取消',db,cancel(3,cid='other'))
        denied('取消后禁止准备',db,public(C.prepare(n=3),3,cancel='cancel',cancel_revision=1),'command_cancelled')
        for table in ('cv_cancel_attempt','cv_cancel_target','cv_cancel_permit'):
            field={'cv_cancel_attempt':'attempt_id','cv_cancel_target':'exit_id','cv_cancel_permit':'permit_id'}[table]
            denied('捕获后不得追加'+table,db,[I(table,cancellation_id='cancel',**{field:'late'})],'cancel_cut_frozen')
        for field,value,error in [('accepted_state_digest','sha256:'+'b'*64,'cancel_cas'),
                                  ('accepted_revision',U(0),'cancel_cas'),
                                  ('cut_revision',U(1),'cancel_cut_highwater')]:
            denied('新取消关联'+field,fresh(),mutation(cancel(),'cv_cancel',field,value),error)
        denied('初始取消不能自报confirmed',fresh(),
               mutation(cancel(),'cv_cancel_revision','state','confirmed'))
        denied('原回执不可引用异初始操作',fresh(),mutation(cancel(),'cv_cancel_receipt',
               'initial_operation_digest','sha256:'+'b'*64),'cancel_receipt_pair')
        db=fresh()
        db.execute(*I('ca_namespace_closure',namespace_id='ns',protection_operation_id='closed',closure_body=B))
        denied('关闭namespace不新建取消',db,cancel(),'cancel_namespace_closed')
        db=fresh();F.tx(db,cancel())
        db.execute(*I('ca_namespace_closure',namespace_id='ns',protection_operation_id='closed',closure_body=B))
        check('namespace关闭保留原回执',db.execute('SELECT count(*) FROM cv_cancel_receipt').fetchone()[0],1)
        db=fresh('prepared');F.tx(db,cancel(3,attempts=('a',),state_args={'attempts':('a',)}))
        denied('取消后禁止取得hold',db,public(C.dispatch(n=4),4,cancel='cancel',cancel_revision=1),'command_cancelled')
        db=fresh('sent');F.tx(db,cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=SENT))
        denied('取消后禁止普通协议重传',db,F.transmission('permit.2',2,1,'permit.1'),'command_cancelled')
        F.tx(db,public(C.report(5,**WAITING),5,cancel='cancel',cancel_revision=1))
        check('已发送迟到事实仍可保存',db.execute('SELECT disposition FROM ce_report').fetchall(),[('in_flight',)])
        check('保存迟到事实不恢复发送资格',db.execute('SELECT count(*) FROM cv_cancel_deny').fetchone()[0],1)
        check('完整cut保留许可',db.execute('SELECT permit_id FROM cv_cancel_permit').fetchall(),[('permit.1',)])
        db=fresh('sent')
        capture=cancel(4,attempts=('a',),permits=('permit.1',),cut=1,state_args=SENT)
        omitted=[s for s in capture if not s[0].startswith('INSERT INTO cv_cancel_permit ')]
        denied('捕获不能遗漏已发许可',db,omitted,'cancel_permit_set')
        db=fresh('unknown');F.tx(db,cancel(6,attempts=('a',),permits=('permit.1',),cut=1,state_args=UNKNOWN))
        F.tx(db,progress())
        denied('不确定取消不可重新requested',db,progress(8,3,'requested'),'cancel_regression')
        F.tx(db,progress(8,3,'confirmed','closed'))
        check('取消确认保持原unknown和未决',db.execute(
            'SELECT outcome,resource_status,paused_latched,terminal_revision FROM cm_current').fetchone(),
            ('unknown','unresolved',1,U(5)))
        for s,f in [('requested','closed'),('confirmed','pending'),('failed','closed')]:
            denied('固定取消结论及关闭不可回退'+s+f,db,progress(9,4,s,f))
        check('原取消回执仍引用修订1',db.execute(
            'SELECT initial_revision FROM cv_cancel_receipt').fetchone()[0],U(1))
        check('公开记录选当前取消修订',db.execute(
            'SELECT cancellation_revision FROM cv_current').fetchone()[0],U(3))
        denied('当前修订不可漏取消摘要',db,public(C.revision(9,'observe',**UNKNOWN),9),'cancel_projection')
        denied('当前修订不可混旧取消摘要',db,
               public(C.revision(9,'observe',**UNKNOWN),9,cancel='cancel',cancel_revision=1),'cancel_projection')
        denied('取消进展不可跳号',db,progress(9,5,'confirmed','closed'),'cancel_successor')
        db=fresh('unknown');F.tx(db,cancel(6,attempts=('a',),permits=('permit.1',),cut=1,state_args=UNKNOWN))
        denied('未提交前序不可插入后继绕过单调检查',db,
               [progress()[0],progress(8,3,'requested')[0]],'cancel_previous_uncommitted')
        atomic('取消进展同状态发布','unknown',
               cancel(6,attempts=('a',),permits=('permit.1',),cut=1,state_args=UNKNOWN)+progress())
        db=fresh('unknown')
        released=C.R.close()+C.R.settle(kind='effect_resolved')+C.R.release(
            rid='release.r',kind='module_settled')+C.resolution(rid='resolution.z')+[
            evidence('release.r',6,kind='release',source='release.r'),
            evidence('resolution.z',6,kind='resolution',source='resolution.z')]+public(
            C.revision(6,'reconcile',phase='finished',outcome='unknown',effect='verified',latched=1,
                terminal=5,resolution='resolution.z',decision='e.resolution.z',attempts=('a',),releases=('release.r',)),
            6,members=(('release.r',1),('resolution.z',1)))
        F.tx(db,released)
        check('释放和核对原件进入同修订快照',db.execute(
            'SELECT kind FROM cv_evidence ORDER BY kind').fetchall(),[('release',),('resolution',)])
        check('释放后当前记录与固定终态分开',db.execute(
            'SELECT outcome,resource_status FROM cm_current').fetchone(),('unknown','clear'))
        for kind,field in [('release','source_digest'),('resolution','revision')]:
            bad=list(released)
            index=next(i for i,s in enumerate(bad) if s[0].startswith('INSERT INTO cv_evidence ') and kind in s[1])
            bad[index]=mutation([bad[index]],'cv_evidence',field,
                'sha256:'+'b'*64 if field=='source_digest' else U(2))[0]
            denied('拒绝错配'+kind+'原件',fresh('unknown'),bad,kind+'_source')
        F.tx(db,[I('cr_validation_revocation',validation_id='v.release.r',reason_body=B,audit_body=B)])
        check('原件失效后隐藏旧clear公开记录',db.execute('SELECT count(*) FROM cv_current').fetchone()[0],0)
        check('原件失效仍保留历史记录',db.execute('SELECT count(*) FROM cv_history').fetchone()[0],6)
        db=fresh();F.tx(db,first)
        original=db.execute('SELECT * FROM cv_snapshot_member WHERE snapshot_id=?',('snapshot.one.2',)).fetchall()
        second=[evidence('observation.b',3)]+public(C.revision(3,'observe'),3,
            members=(('observation.a',1),('observation.b',1)))
        F.tx(db,second)
        check('迟到证据不改旧分页',db.execute('SELECT * FROM cv_snapshot_member WHERE snapshot_id=?',
              ('snapshot.one.2',)).fetchall(),original)
        check('新快照含全部历史',db.execute('SELECT evidence_id FROM cv_snapshot_member WHERE snapshot_id=? ORDER BY ordinal',
              ('snapshot.one.3',)).fetchall(),[('observation.a',),('observation.b',)])
        missing=public(C.revision(4,'observe'),4,members=(('observation.b',1),))
        denied('count正确仍拒遗漏历史成员',db,missing,'snapshot_members')
        swapped=public(C.revision(4,'observe'),4,members=(('observation.b',1),('observation.a',1)))
        denied('完整成员排序必须固定',db,swapped,'snapshot_order')
        gap=public(C.revision(4,'observe'),4,members=(('observation.a',1),('observation.b',1)))
        denied('公开State摘要不得另换',db,mutation(gap,'cv_record','state_digest','sha256:'+'b'*64),
               'complete_public_revision_required')
        denied('total不得冒充完整集合',db,mutation(gap,'cv_snapshot','total',U(3)),'snapshot_count')
        denied('不能向历史修订追加证据',db,[evidence('observation.late',2)],'evidence_revision_frozen')
        denied('不能向旧快照补成员',db,[I('cv_snapshot_member',snapshot_id='snapshot.one.2',ordinal=U(1),
               evidence_id='observation.b',evidence_revision=U(1))],'snapshot_frozen')
        invalid=[evidence('invalidation.a',4,kind='invalidation',subject='observation.a')]+public(C.revision(4,'observe'),4,
            members=(('invalidation.a',1),('observation.a',1),('observation.b',1)))
        F.tx(db,invalid)
        check('失效记录不删除历史证据',db.execute('SELECT count(*) FROM cv_evidence').fetchone()[0],3)
        db=fresh()
        source=C.decision('decision.a',kind='failure',effect='not_sent')
        linked=source+[evidence('decision.a',2,kind='decision',source='decision.a')]+public(
            C.revision(2,'observe'),2,members=(('decision.a',1),))
        F.tx(db,linked)
        check('decision原件物理关联',db.execute('SELECT decision_id FROM cv_evidence').fetchone()[0],'decision.a')
        other=C.decision('decision.b',kind='failure',effect='not_sent')+[
            evidence('decision.b',3,kind='decision',source='decision.b')]+public(C.revision(3,'observe'),3,
            members=(('decision.a',1),('decision.b',1)))
        denied('公共摘要不替代来源摘要',db,
               mutation(other,'cv_evidence','source_digest','sha256:'+'b'*64),'decision_source')
        F.tx(db,public(C.initial('two'),1,'two'))
        denied('跨命令证据不能入快照',db,public(C.revision(2,'observe','two'),2,'two',
            members=(('decision.a',1),)),'snapshot_members')
        # 此反证保留提供者责任：非空BODY可通过SQL，不能据此宣称完成内容校验。
        check('SQL不证明完整公开JSON',db.execute('SELECT record_body FROM cv_current LIMIT 1').fetchone()[0]==B)
        db=fresh('unknown');F.tx(db,cancel(6,attempts=('a',),permits=('permit.1',),cut=1,state_args=UNKNOWN))
        F.tx(db,progress(7,2,'confirmed','closed'))
        all_tables=['cv_metadata','cv_evidence','cv_snapshot','cv_snapshot_member','cv_record','cv_cancel_key',
            'cv_cancel','cv_cancel_revision','cv_cancel_receipt','cv_cancel_deny','cv_cancel_attempt','cv_cancel_target',
            'cv_cancel_permit','cv_cancel_commit']
        # 给证据两表加入行，使UPDATE/DELETE/REPLACE实际触发，而非空表通过。
        F.tx(db,[evidence('observation.a',8)]+public(C.revision(8,'observe',**UNKNOWN),8,
            members=(('observation.a',1),),cancel='cancel',cancel_revision=2))
        for table in all_tables:
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for mode,sql in [('UPDATE',f'UPDATE {table} SET {column}={column}'),
                             ('DELETE','DELETE FROM '+table),
                             ('REPLACE',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')]:
                denied(table+mode,db,[(sql,())])
        check('外键检查',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        check('完整性检查',db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
        return checks
    finally:
        for db in connections:db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true')
    p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true')
    args=p.parse_args()
    if args.staged and not args.check_report:p.error('--staged需配合--check-report')
    if args.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        data=json.loads(read(HERE/'storage-report.json'))
        assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run()
        data=dict(all_passed=True,cases_passed=len(checks),approved=False,
            scope='91表内存组合的公开修订、取消受理进度及固定证据索引',
            runtime_tests_executed=0,device_tests_executed=0,sqlite_version=sqlite3.sqlite_version,
            checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if args.report:(HERE/'storage-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
