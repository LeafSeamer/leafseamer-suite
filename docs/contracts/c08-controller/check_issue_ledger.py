"""共享签发94表内存约束检查；没有业务或磁盘数据库入口。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
import build_issue_ledger as G
import check_command as C

HERE,ROOT,F,I,B,D=G.HERE,C.ROOT,C.F,C.I,C.B,C.D
V=F.L.load('public_issue_fixture',HERE.parent/'c02-command-view/check_storage.py')
U=V.U
INPUTS=list(dict.fromkeys(V.INPUTS+G.SOURCES+[HERE/n for n in
    ('build_issue_ledger.py','controller-issue.sql','ISSUE_LEDGER.md','check_issue_ledger.py')]))

def issue(pid,n,kind):
    return I('ci_issue',permit_id=pid,issued_revision=U(n),kind=kind,
             ordinary_id=pid if kind=='ordinary' else None,cancel_id=pid if kind=='cancel' else None)

def ordinary(steps):
    result=[]
    for sql,args in steps:
        if sql.startswith('INSERT INTO ce_permit '):
            fields=dict(zip(sql.split('(',1)[1].split(')',1)[0].split(','),args))
            result.append(issue(fields['permit_id'],int(fields['issued_revision']),'ordinary'))
        result.append((sql,args))
    return result

def cancel(pid='cancel.1',n=2,ordinal=0,initial=None,origin='manual'):
    return [issue(pid,n,'cancel'),I('ci_cancel_transmission',permit_id=pid,issued_revision=U(n),
        issue_kind='cancel',cancellation_id='cancel',exit_id='exit.0',execution_id='execution.cancel',
        execution_digest=D,primitive_id='primitive.cancel',packet_id='packet.cancel',packet_digest=D,
        ordinal=ordinal,initial_permit_id=initial,origin=origin,
        origin_authority='seamer' if origin=='automation' else None,
        origin_database='source.db' if origin=='automation' else None,
        run_id='run' if origin=='automation' else None,generation=U(1) if origin=='automation' else None,
        time_required=0,time_binding_body=None,transmission_body=B),
        I('ci_cancel_commit',permit_id=pid,ordinary_closure_body=B,execution_validation_body=B,
          guard_body=B,budget_charge_body=B,packet_bytes=B,dispatch_intent_body=B,audit_body=B,
          outbox_id='dispatch.'+pid,outbox_body=B)]

def run():
    assert (HERE/'controller-issue.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,observed=actual,expected=expected))
    def fresh(sent=True,cooperative=True):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON')
        db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        F.tx(db,V.public(C.initial(),1));F.tx(db,V.public(C.initial('two'),1,'two'))
        F.tx(db,V.public(C.prepare('two',aid='b'),2,'two'))
        if sent:F.tx(db,ordinary(V.public(C.dispatch('two',aid='b',attempts=('b',)),3,'two')))
        steps=V.cancel(cut=1 if sent else 0)
        if cooperative:steps=F.P.mutate(steps,'cv_cancel','mode','cooperative')
        F.tx(db,steps)
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    try:
        db=fresh();check('94表',len(F.snapshot(db)),94)
        F.tx(db,cancel());F.tx(db,ordinary(F.transmission('ordinary.3',3,1,'permit.1',aid='b')))
        check('普通取消普通连续',db.execute('SELECT kind,issued_revision FROM ci_issue ORDER BY issued_revision').fetchall(),
              [('ordinary',U(1)),('cancel',U(2)),('ordinary',U(3))])
        denied('提交后同身份只查原',db,cancel())
        check('原取消仍可查询',db.execute('SELECT count(*) FROM ci_cancel_transmission WHERE permit_id=?',('cancel.1',)).fetchone()[0],1)
        db=fresh(False);F.tx(db,cancel(n=1))
        F.tx(db,ordinary(V.public(C.dispatch('two',aid='b',attempts=('b',),issued=2),3,'two')))
        check('取消普通连续',db.execute('SELECT kind FROM ci_issue ORDER BY issued_revision').fetchall(),[('cancel',),('ordinary',)])
        for n in range(3):
            db=fresh();steps=cancel();denied('取消缺写'+str(n),db,steps[:n]+steps[n+1:])
            before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError as e:check('取消主动异常'+str(n),str(e),'injected_before_commit')
            else:raise AssertionError('异常未发生')
            check('取消异常回滚'+str(n),F.snapshot(db)==before)
            F.tx(db,steps);check('回滚未消耗序号'+str(n),db.execute('SELECT max(issued_revision) FROM ci_issue').fetchone()[0],U(2))
        db=fresh()
        for label,steps in [('跳号',cancel(n=3)),('重复序号',cancel(n=1)),('跨类型ID',cancel(pid='permit.1')),
                            ('孤立普通',[issue('orphan',2,'ordinary')]),('孤立取消',[issue('orphan',2,'cancel')])]:
            denied(label,db,steps)
        mutate=F.P.mutate
        for field,value in [('issue_kind','ordinary'),('issued_revision',U(3)),('exit_id','missing'),
                            ('ordinal',1),('initial_permit_id','missing'),('origin_authority','seamer'),
                            ('time_required',1),('time_binding_body',B)]:
            denied('错误取消字段'+field,db,mutate(cancel(),'ci_cancel_transmission',field,value))
        denied('普通缺共享登记',db,F.transmission('plain',2,1,'permit.1',aid='b'),'ordinary_issue_pair')
        denied('普通缺提交',db,ordinary(F.transmission('plain',2,1,'permit.1',aid='b'))[:-1])
        db=fresh(cooperative=False);denied('普通取消模式不能发保护',db,cancel(),'cancel_execution_binding')
        db=fresh();db.execute(*F.exit_step('wrong','another.device'))
        denied('取消错设备',db,mutate(cancel(),'ci_cancel_transmission','exit_id','wrong'),'cancel_execution_binding')
        db=fresh();db.execute(*I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B))
        denied('取消退役出口',db,cancel(),'exit_retired')
        db=fresh();F.tx(db,cancel())
        resend=cancel('cancel.2',3,1,'cancel.1')
        for field,value,error in [('execution_id','changed','cancel_execution_changed'),
                                 ('packet_id','changed','cancel_initial_binding'),
                                 ('exit_id','exit.1','cancel_initial_binding'),
                                 ('initial_permit_id','permit.1','cancel_initial_binding'),
                                 ('ordinal',2,'cancel_ordinal')]:
            denied('取消重传'+field,db,mutate(resend,'ci_cancel_transmission',field,value),error)
        F.tx(db,resend);check('取消重传独立许可',db.execute('SELECT count(*) FROM ci_cancel_transmission').fetchone()[0],2)
        denied('取消重传原字节不可换',db,mutate(cancel('cancel.3',4,2,'cancel.1'),
            'ci_cancel_commit','packet_bytes',b'different'),'cancel_bytes_changed')
        for state,future in [('indeterminate','pending'),('confirmed','closed')]:
            db=fresh();F.tx(db,V.progress(3,2,state,future,state_args={'phase':'queued'}))
            denied('取消未知或关闭禁止签发'+state,db,cancel(),'cancel_execution_closed')
        # 人工取消不继承父命令run；旧RUN集合仍完整时可封存，但必须使用共享head。
        db=fresh();F.tx(db,cancel())
        denied('RUN拒绝旧普通水位',db,F.fence(revision=1,queued=('one',)),'cut_revision')
        F.tx(db,F.fence(revision=2,queued=('one',)))
        check('RUN共享水位',db.execute('SELECT issued_cut_revision FROM ce_fence').fetchone()[0],U(2))
        db=fresh();F.tx(db,cancel(origin='automation'))
        denied('RUN不能遗漏取消coverage',db,F.fence(revision=2,queued=('one',)),'cancel_run_coverage_not_merged')
        db=fresh();F.tx(db,cancel())
        # 新命令取消受理必须看包含取消传输的全局head。
        args=dict(n=4,key='two',cid='cancel.two',attempts=('b',),permits=('permit.1',),state_args=dict(
            phase='dispatching',effect='possible',resource='held',attempts=('b',)))
        denied('取消受理旧普通水位',db,V.cancel(cut=1,**args),'cancel_cut_highwater')
        F.tx(db,V.cancel(cut=2,**args))
        check('取消受理共享head',db.execute("SELECT cut_revision FROM cv_cancel WHERE cancellation_id='cancel.two'").fetchone()[0],U(2))
        # 普通命令的资源释放即使不涉及取消，也必须读取共享head。
        db=fresh();F.tx(db,cancel())
        F.tx(db,C.R.close(key='two')+C.R.settle(key='two',kind='effect_resolved'))
        release=C.R.release(key='two',kind='module_settled',revision=2,attempts=(('b','h','close.h'),))
        denied('释放拒绝旧普通水位',db,mutate(release,'cr_release','issued_cut_revision',U(1)),'release_binding')
        F.tx(db,release)
        check('释放共享head',db.execute('SELECT issued_cut_revision FROM cr_release').fetchone()[0],U(2))
        # 被取消命令的普通资源不能遗漏该取消分支。
        db=fresh();args['cid']='cancel.two'
        steps=mutate(V.cancel(cut=1,**args),'cv_cancel','mode','cooperative');F.tx(db,steps)
        F.tx(db,mutate(cancel(),'ci_cancel_transmission','cancellation_id','cancel.two'))
        denied('资源拒绝遗漏取消分支',db,release,'cancel_resource_coverage_not_merged')
        db=fresh();F.tx(db,mutate(V.cancel(cut=1,**args),'cv_cancel','mode','cooperative'))
        F.tx(db,C.R.close(key='two')+C.R.settle(key='two',kind='effect_resolved'))
        prior_release=mutate(release,'cr_release','issued_cut_revision',U(1))
        later_cancel=mutate(cancel(),'ci_cancel_transmission','cancellation_id','cancel.two')
        denied('释放在先同事务取消不能绕过',db,prior_release+later_cancel,'cancel_resource_coverage_not_merged')
        F.tx(db,prior_release)
        denied('释放提交后取消仍不能绕过',db,later_cancel,'cancel_resource_coverage_not_merged')
        # 封存后的同事务插入必须被阻断，而不是把漏项带到COMMIT。
        db=fresh();steps=F.fence(revision=1,queued=('one',))
        denied('RUN封存后不可分配',db,steps[:-1]+[issue('late',2,'cancel')]+steps[-1:],'pending_cut')
        for table in ('ci_issue','ci_cancel_transmission','ci_cancel_commit'):
            db=fresh();F.tx(db,cancel())
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for sql in (f'UPDATE {table} SET {column}={column}',f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                denied(table+sql.split()[0],db,[(sql,())])
        check('非空BODY不证普通已关闭',db.execute('SELECT ordinary_closure_body FROM ci_cancel_commit').fetchone()[0]==B)
        for d in connections:
            assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert d.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库FK及完整性',True)
        sql="SELECT printf('%010d%010d',CAST(substr(?,1,10) AS INTEGER)+(substr(?,11,10)='9999999999'),(CAST(substr(?,11,10) AS INTEGER)+1)%10000000000)"
        for value,expected in [('00000000009999999999','00000000010000000000'),('9223372036854775807','09223372036854775808')]:
            v=value.zfill(20);check('仅算术探针'+v,db.execute(sql,(v,v,v)).fetchone()[0],expected)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'issue-ledger-report.json'))
        assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,
            scope='共享签发94表内存候选；完整取消覆盖尚未归并',runtime_tests_executed=0,
            device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,
            inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'issue-ledger-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
