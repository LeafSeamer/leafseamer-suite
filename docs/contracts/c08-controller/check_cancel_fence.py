"""RUN取消覆盖的99表内存验收；故障为主动异常，非磁盘或真实IPC。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
import build_cancel_fence as G
import check_issue_ledger as Q
import check_barrier_attempt as BA

HERE,ROOT,F,I,B,D,U,V,C=G.HERE,Q.ROOT,Q.F,Q.I,Q.B,Q.D,Q.U,Q.V,Q.C
INPUTS=list(dict.fromkeys(Q.INPUTS+G.SOURCES+[HERE/n for n in
    ('build_cancel_fence.py','cancel-fence.sql','controller-cancel-fence.sql','CANCEL_FENCE.md',
     'check_cancel_fence.py','check_barrier_attempt.py')]))
PROOF={'not_sent':'never_received','in_flight':'transport_entered','unknown':'send_uncertain'}

def report(pid='cancel.1',state='in_flight',rid='report.cancel',eid='exit.0'):
    return I('cf_report',report_id=rid,permit_id=pid,exit_id=eid,worker_report_id='worker.'+rid,
        disposition=state,proof=PROOF[state],source_digest=D,evidence_body=B,validation_body=B,audit_body=B)

def settle(pid='cancel.1',sid='settled.cancel',kind='never_sent',rid='report.cancel',barrier=None):
    return I('cf_settlement',settlement_id=sid,permit_id=pid,kind=kind,
        report_id=rid if kind=='never_sent' and not barrier else None,
        barrier_id=barrier if kind=='never_sent' else None,validation_body=B,audit_body=B)

def cut(items=(('cancel.1','exit.0',0),),revision=2,targets=('exit.0','exit.1'),source='protect'):
    steps=F.fence(revision=revision,queued=('one',),targets=targets,source=source)
    at=next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO ce_cut_commit '))
    steps[at:at]=[I('cf_run_item',fence_id='f',permit_id=p,exit_id=e,entered_known=k) for p,e,k in items]
    return steps

def ack(barrier='b1',eid='exit.0',items=(('cancel.1','unknown'),),ordinary='unknown'):
    steps=BA.ack(barrier,eid,ordinary,items=eid=='exit.0')
    extra=[I('cf_barrier_coverage',barrier_id=barrier,fence_id='f',exit_id=eid,permit_id=p,
        disposition=s,proof=PROOF[s]) for p,s in items]
    return steps[:-1]+extra+steps[-1:]

def select(barrier='b1',eid='exit.0',items=(('cancel.1','unknown'),),kind='worker_ack',ordinary='unknown'):
    steps=BA.select(barrier,eid,ordinary,kind)
    extra=[I('cf_target_coverage',fence_id='f',exit_id=eid,permit_id=p,disposition=s,
        proof=PROOF[s],evidence_body=B) for p,s in items]
    return steps[:-1]+extra+steps[-1:]

def run():
    assert (HERE/'controller-cancel-fence.sql').read_bytes()==G.build(),'生成漂移'
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(origin='automation',stage='registered',entered=False,eid='exit.0'):
        db=sqlite3.connect(':memory:',isolation_level=None);connections.append(db)
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON')
        db.executescript(G.build().decode())
        db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
        db.execute(*F.A.namespace());F.tx(db,F.P.register());F.tx(db,F.P.change())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        F.tx(db,V.public(C.initial(),1));F.tx(db,V.public(C.initial('two'),1,'two'))
        F.tx(db,V.public(C.prepare('two',aid='b'),2,'two'))
        F.tx(db,Q.ordinary(V.public(C.dispatch('two',aid='b',attempts=('b',)),3,'two')))
        F.tx(db,F.P.mutate(V.cancel(cut=1),'cv_cancel','mode','cooperative'))
        F.tx(db,F.P.mutate(Q.cancel(origin=origin),'ci_cancel_transmission','exit_id',eid))
        if entered:F.tx(db,[report(eid=eid)])
        if stage=='registered':return db
        F.tx(db,cut(items=(('cancel.1',eid,int(entered)),)))
        if stage=='cut':return db
        F.tx(db,[BA.attempt(eid=eid)])
        if stage=='ack':F.tx(db,ack(eid=eid,items=(('cancel.1','in_flight' if entered else 'unknown'),)))
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as e:check(name,str(e) if error else 'rejected',error or 'rejected')
        else:raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',F.snapshot(db)==before)
    def atomic(name,stage,steps):
        for n in range(len(steps)):
            db=fresh(stage=stage);denied(name+'缺写'+str(n),db,steps[:n]+steps[n+1:])
            db=fresh(stage=stage);before=F.snapshot(db)
            try:F.tx(db,steps,n)
            except RuntimeError as e:check(name+'主动异常'+str(n),str(e),'injected_before_commit')
            else:raise AssertionError('未注入异常')
            check(name+'异常全库回滚'+str(n),F.snapshot(db)==before)
    def open_ids(db):return [r[0] for r in db.execute('SELECT permit_id FROM cf_open_permit ORDER BY permit_id')]
    try:
        db=fresh();check('99表组合',len(F.snapshot(db)),99)
        atomic('取消cut','registered',cut())
        atomic('取消ACK','attempt',ack())
        atomic('取消采用','ack',select())
        db=fresh();F.tx(db,cut(source='close'))
        check('准备关闭同样捕获取消',db.execute('SELECT permit_id FROM cf_run_item').fetchall(),[('cancel.1',)])
        db=fresh();denied('cut漏取消',db,cut(items=()),'cancel_cut_set')
        denied('cut错入口',db,cut(items=(('cancel.1','exit.1',0),)))
        denied('cut虚构已发',db,cut(items=(('cancel.1','exit.0',1),)),'cancel_entered_snapshot')
        db=fresh(entered=True);denied('cut丢已发事实',db,cut(),'cancel_entered_snapshot')
        db=fresh(origin='manual');denied('不得继承父run',db,cut(),'cancel_cut_set')
        F.tx(db,cut(items=()));check('人工取消不属于旧automation',db.execute('SELECT count(*) FROM cf_run_item').fetchone()[0],0)
        for field,value in [('origin_authority','other'),('origin_database','other'),('run_id','other'),('generation',U(2))]:
            # 使用独立primitive不能更换原execution来源，故在初始签发前创建准确夹具。
            db=fresh(origin='manual');steps=Q.cancel('foreign.1',3,0,origin='automation')
            steps=F.P.mutate(steps,'ci_cancel_transmission','cancellation_id','other.cancel')
            F.tx(db,V.public(C.initial('other'),1,'other'))
            F.tx(db,F.P.mutate(V.cancel(key='other',cid='other.cancel',cut=2),'cv_cancel','mode','cooperative'))
            steps=F.P.mutate(steps,'ci_cancel_transmission',field,value);F.tx(db,steps)
            # 新增other仍queued，手写完整旧来源命令集；取消来源不应被误选。
            st=cut(items=(),revision=3)
            at=next(i for i,s in enumerate(st) if s[0].startswith('INSERT INTO ce_cut_commit '))
            st.insert(at,I('ce_queued',fence_id='f',command_id='command.other',reason='run_generation_denied'))
            F.tx(db,st);check('来源精确隔离'+field,db.execute('SELECT count(*) FROM cf_run_item').fetchone()[0],0)
        db=fresh(eid='exit.1');db.execute(*I('ce_retirement',exit_id='exit.1',supervisor_evidence_body=B))
        denied('退役未决出口不能漏',db,cut(items=(),targets=('exit.0',)),'cancel_cut_set')
        F.tx(db,cut(items=(('cancel.1','exit.1',0),)))
        check('退役未决出口保留',db.execute('SELECT exit_id FROM ce_target ORDER BY exit_id').fetchall(),[('exit.0',),('exit.1',)])
        db=fresh(stage='cut');denied('封存后不得补成员',db,[I('cf_run_item',fence_id='f',permit_id='cancel.1',exit_id='exit.0',entered_known=0)],'cancel_cut_frozen')
        for steps,label in [([report()],'报告'),([settle()],'核销')]:
            db=fresh();st=cut();denied('seal到来源提交冻结'+label,db,st[:-1]+steps+st[-1:],'pending_cut')
        db=fresh(stage='attempt')
        second=F.fence(name='f2',key='protection2',revision=2,raise_deny=False)
        at=next(i for i,s in enumerate(second) if s[0].startswith('INSERT INTO ce_cut_commit '))
        second.insert(at,I('cf_run_item',fence_id='f2',permit_id='cancel.1',exit_id='exit.0',entered_known=0))
        late=ack(items=(('cancel.1','in_flight'),))
        denied('预写覆盖不能在新seal后靠ACK改事实',db,late[:-1]+second[:-1]+late[-1:]+second[-1:],'pending_cut')
        db=fresh(stage='attempt');denied('ACK漏取消',db,BA.ack(),'cancel_ack_incomplete')
        db=fresh(stage='attempt',entered=True);denied('ACK不得降已发',db,ack(),'cancel_ack_downgrade')
        db=fresh(stage='ack');denied('结果漏取消',db,BA.select(),'cancel_result_incomplete')
        denied('结果不能重写ACK',db,select(items=(('cancel.1','not_sent'),)),'cancel_selected_mismatch')
        F.tx(db,select());denied('尚缺空出口不能汇总',db,[F.application()],'coverage_incomplete')
        F.tx(db,[BA.attempt('empty',eid='exit.1')]);F.tx(db,ack('empty','exit.1',()))
        F.tx(db,select('empty','exit.1',()));F.tx(db,[F.application()])
        check('普通和取消完整关闭可汇总',db.execute('SELECT count(*) FROM ce_application').fetchone()[0],1)
        check('applied不清取消资源风险',open_ids(db),['cancel.1'])
        check('原普通资源仍占用',db.execute('SELECT count(*) FROM cr_release').fetchone()[0],0)
        denied('RUN成功不解除取消资源阻断',db,C.R.release(revision=2),'cancel_resource_coverage_not_merged')
        F.tx(db,[report(rid='after.application')])
        check('应用后迟到报告仍保留强事实',db.execute('SELECT disposition FROM cf_disposition').fetchone()[0],'in_flight')
        # 丢缓存只重装同cut；失败尝试原ACK可留强事实，但不能采用为新attempt。
        db=fresh(stage='attempt');F.tx(db,[BA.failure(),BA.attempt('b2',2,'b1')])
        F.tx(db,ack('b1',items=(('cancel.1','in_flight'),)))
        check('迟到失败ACK立即保留强事实',db.execute('SELECT disposition FROM cf_disposition').fetchone()[0],'in_flight')
        denied('旧ACK不采用为当前',db,select('b1',items=(('cancel.1','in_flight'),)),'ack_not_current')
        F.tx(db,ack('b2'));F.tx(db,select('b2'))
        check('新采用不覆盖迟到强事实',db.execute('SELECT disposition FROM cf_disposition').fetchone()[0],'in_flight')
        # never_sent来自原报告或已封存ACK；强事实可重开，effect_resolved不由传输报告自动撤回。
        db=fresh();denied('未知不能核销未发',db,[settle()],'cancel_never_sent_unproven')
        F.tx(db,[report(state='not_sent'),settle()]);check('未发核销',open_ids(db),[])
        F.tx(db,[report(rid='late')]);check('迟到已发重开',open_ids(db),['cancel.1'])
        F.tx(db,[settle(sid='effect',kind='effect_resolved')]);check('效果核销独立',open_ids(db),[])
        F.tx(db,cut(items=()));check('核销后新cut不捕获',db.execute('SELECT count(*) FROM cf_run_item').fetchone()[0],0)
        db=fresh(stage='attempt');F.tx(db,ack(items=(('cancel.1','not_sent'),)))
        F.tx(db,[settle(barrier='b1')]);check('ACK原件未发核销',open_ids(db),[])
        denied('原件报告身份不换',db,[report(state='not_sent',rid='r') , report(state='unknown',rid='r')])
        db=fresh();F.tx(db,[report(state='not_sent',rid='first')])
        repeated=F.P.mutate([report(state='unknown',rid='second')],'cf_report','worker_report_id','worker.first')
        denied('换服务器ID不绕原报告身份',db,repeated)
        denied('报告出口必须匹配传输',db,[report(rid='wrong.exit',eid='exit.1')])
        denied('报告摘要不是任意字符串',db,F.P.mutate([report(rid='bad.digest')],'cf_report','source_digest','x'))
        # 精确退休只证明未来不再写，不能凭退休把未知降为未发。
        db=fresh(stage='cut');db.execute(*I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B))
        denied('退休不能制造未发',db,select(kind='supervisor_retired',items=(('cancel.1','not_sent'),)),'cancel_result_downgrade')
        F.tx(db,select(kind='supervisor_retired'))
        check('退休保持未知',db.execute('SELECT disposition FROM cf_target_coverage').fetchone()[0],'unknown')
        # 真实插入256/257成员，不是仅算一个阈值表达式。
        for count in (256,257):
            db=fresh()
            for n in range(1,count):F.tx(db,Q.cancel('cancel.'+str(n+1),n+2,n,'cancel.1',origin='automation'))
            members=tuple(('cancel.'+str(n),'exit.0',0) for n in range(1,count+1))
            if count==256:
                F.tx(db,cut(items=members,revision=count+1));check('256取消覆盖可封存',db.execute('SELECT count(*) FROM cf_run_item').fetchone()[0],256)
            else:denied('257取消不得截断',db,cut(items=members,revision=count+1),'cancel_fence_capacity')
        db=fresh(stage='ack');F.tx(db,select());F.tx(db,[report(state='not_sent'),settle()])
        for table in G.TABLES:
            column=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for sql in (f'UPDATE {table} SET {column}={column}',f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                denied(table+sql.split()[0],db,[(sql,())])
        for d in connections:
            assert d.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert d.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        check('全部内存库FK与完整性',True)
        return checks
    finally:
        for db in connections:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(HERE/'cancel-fence-report.json'));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,cases_passed=len(checks),approved=False,scope='99表RUN取消完整覆盖候选',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
            sqlite_version=sqlite3.sqlite_version,checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:(HERE/'cancel-fence-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
