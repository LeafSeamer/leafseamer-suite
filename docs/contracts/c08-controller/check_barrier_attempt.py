"""51表内存组合的屏障尝试检查；无进程、IPC、网络或磁盘故障模拟。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import check_fence as F

HERE,ROOT=F.HERE,F.ROOT
I,B,D,U=F.I,F.B,F.D,F.U
INPUTS=list(dict.fromkeys(F.INPUTS+[HERE/n for n in ('BARRIER_ATTEMPTS.md','barrier-attempt.sql','check_barrier_attempt.py')]))


def attempt(barrier='b1', ordinal=1, previous=None, eid='exit.0'):
    return I('ce_barrier_attempt',barrier_id=barrier,fence_id='f',exit_id=eid,ordinal=U(ordinal),
             previous_barrier_id=previous,request_digest=D,request_body=B,audit_body=B,
             outbox_event_id='barrier.'+barrier,outbox_body=B)


def failure(barrier='b1', reason='cache_miss'):
    return I('ce_barrier_failure',barrier_id=barrier,reason=reason,evidence_body=B,audit_body=B)


def ack(barrier='b1', eid='exit.0', state='unknown', items=True, tick=100):
    steps=[]
    if items:
        steps.append(I('ce_barrier_coverage',barrier_id=barrier,fence_id='f',exit_id=eid,permit_id='permit.1',
                       disposition=state,proof={'unknown':'send_uncertain','in_flight':'transport_entered',
                                               'not_sent':'never_received'}[state]))
    return steps+[I('ce_barrier_ack',barrier_id=barrier,effective_tick=str(tick).zfill(20),
                    ack_digest=D,ack_body=B,audit_body=B)]


def select(barrier='b1',eid='exit.0',state='unknown',kind='worker_ack'):
    steps=F.result(eid, (('permit.1',state),) if eid=='exit.0' else (),kind=kind)
    steps.insert(-1,I('ce_result_binding',fence_id='f',exit_id=eid,
                     barrier_id=barrier if kind=='worker_ack' else None,kind=kind,binding_body=B))
    return steps


def run():
    checks,connections=[],[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='attempt', entered=False):
        db=F.L.fixture();connections.append(db)
        for name in ('fence.sql','barrier-attempt.sql'):
            db.executescript((HERE/name).read_text(encoding='utf-8'))
        db.execute(*F.A.namespace())
        F.tx(db,F.P.register());F.tx(db,F.P.change());F.tx(db,F.command())
        db.execute(*F.exit_step());db.execute(*F.exit_step('exit.1'))
        F.tx(db,[F.attempt(),F.packet()]+F.transmission())
        if entered:db.execute(*F.report())
        if stage=='registered':return db
        F.tx(db,F.fence(items=(('permit.1','exit.0',int(entered)),)))
        if stage=='cut':return db
        F.tx(db,[attempt()])
        if stage=='ack':F.tx(db,ack(state='in_flight' if entered else 'unknown'))
        return db
    def denied(name,db,steps,error=None):
        before=F.snapshot(db)
        try:F.tx(db,steps)
        except sqlite3.IntegrityError as exc:
            check(name,str(exc) if error else 'constraint_rejected',error or 'constraint_rejected')
        else:raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚',F.snapshot(db)==before,True)
    def atomic(name,stage,steps):
        for i in range(len(steps)):
            db=fresh(stage);denied(name+'缺写'+str(i),db,steps[:i]+steps[i+1:])
            db=fresh(stage);before=F.snapshot(db)
            try:F.tx(db,steps,cut=i)
            except RuntimeError:check(name+'故障回滚'+str(i),F.snapshot(db)==before,True)
            else:raise AssertionError('未注入故障')
    try:
        db=fresh();check('51表组合',len(F.snapshot(db)),51)
        denied('未冻结不能发屏障',fresh('registered'),[attempt()],'cut_uncommitted')
        atomic('原ACK','attempt',ack())
        atomic('采用ACK','ack',select())
        for col in ('request_body','audit_body','outbox_body'):
            denied('尝试缺必需记录'+col,fresh('cut'),F.P.mutate([attempt()],'ce_barrier_attempt',col,None))
        denied('无失败依据不追加尝试',db,[attempt('b2',2,'b1')],'retry_basis')
        denied('首序号不可跳过',fresh('cut'),[attempt('b2',2,'b1')],'barrier_ordinal')
        denied('无ACK不得采用',db,select(),'ack_not_current')
        db.execute(*failure());F.tx(db,[attempt('b2',2,'b1')])
        F.tx(db,ack('b1',state='in_flight',tick=90))
        check('晚到旧ACK只补历史',db.execute('SELECT barrier_id FROM ce_barrier_ack').fetchall(),[('b1',)])
        check('未采用也保留强证据',db.execute('SELECT disposition FROM ce_current_disposition').fetchone()[0],'in_flight')
        denied('不能选已替代ACK',db,select('b1',state='in_flight'),'ack_not_current')
        F.tx(db,ack('b2',state='not_sent',tick=110))
        denied('不能把新ACK原文改写',db,select('b2',state='unknown'),'selected_coverage_mismatch')
        F.tx(db,select('b2',state='not_sent'))
        check('最终引用只指新尝试',db.execute('SELECT barrier_id FROM ce_result_binding').fetchone()[0],'b2')
        check('原覆盖不被迟到证据覆写',db.execute('SELECT disposition FROM ce_coverage').fetchone()[0],'not_sent')
        check('旧强证据继续保护',db.execute('SELECT disposition FROM ce_current_disposition').fetchone()[0],'in_flight')
        denied('完成后不再新尝试',db,[attempt('b3',3,'b2')],'target_already_applied')
        denied('不能删除旧ACK',db,[("DELETE FROM ce_barrier_ack WHERE barrier_id='b1'",())],'immutable')
        F.tx(db,[attempt('other',eid='exit.1')]);F.tx(db,ack('other','exit.1',items=False))
        F.tx(db,select('other','exit.1'));F.tx(db,[F.application()])
        check('汇总不核销原许可',db.execute('SELECT count(*) FROM ce_open_permit').fetchone()[0],1)
        check('全部FK通过',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        db=fresh();db.execute(*failure(reason='channel_lost'))
        denied('换连接不复用旧出口重试',db,[attempt('b2',2,'b1')],'retry_basis')
        db.execute(*I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B))
        denied('退役不重新发屏障',db,[attempt('b2',2,'b1')],'exit_retired')
        F.tx(db,select(kind='supervisor_retired'))
        check('监督退役不伪造workerACK',db.execute('SELECT barrier_id FROM ce_result_binding').fetchone()[0],None)
        db=fresh(entered=True)
        denied('切点已进入传输不能降级',db,ack(),'barrier_coverage_downgrade')
        F.tx(db,ack(state='in_flight'))
        denied('已存ACK不制造失败再重试',db,[failure()],'ack_already_stored')
        denied('同ACK不可追加coverage',db,ack(state='in_flight'),'barrier_ack_frozen')
        db=fresh();db.execute(*failure())
        denied('跨出口不能借上一尝试',db,[attempt('b2',2,'b1','exit.1')])
        denied('跨切点不能借上一尝试',db,F.P.mutate([attempt('b2',2,'b1')],'ce_barrier_attempt','fence_id','alien'))
        F.tx(db,[attempt('b2',2,'b1')]);db.execute(*failure('b2','deadline_elapsed'))
        denied('重试只能指紧邻前次',db,[attempt('b3',3,'b1')],'retry_basis')
        F.tx(db,[attempt('b3',3,'b2')])
        check('序号只增且历史保留',db.execute('SELECT count(*) FROM ce_barrier_attempt').fetchone()[0],3)
        for table in ('ce_barrier_attempt','ce_barrier_failure'):
            col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for label,sql in [('更新',f'UPDATE {table} SET {col}={col}'),
                              ('删除','DELETE FROM '+table),('替换',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')]:
                denied(table+label,db,[(sql,())])
        # 失败依据和ACK在各自事务提交；主动异常不能留下半条记录。
        for label,stage,steps in [('尝试','cut',[attempt()]),('失败','attempt',[failure()])]:
            db=fresh(stage);before=F.snapshot(db)
            try:F.tx(db,steps,cut=0)
            except RuntimeError:check(label+'提交前异常',F.snapshot(db)==before,True)
        check('BODY仍是合成前提',db.execute('SELECT request_body FROM ce_barrier_attempt').fetchone()[0]==B,True)
        return checks
    finally:
        for db in connections:db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true')
    args=parser.parse_args()
    if args.staged and not args.check_report:parser.error('--staged需与--check-report共用')
    if args.check_report:
        read=(lambda p:subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else type(HERE).read_bytes
        data=json.loads(read(HERE/'barrier-attempt-report.json'))
        assert set(data['inputs'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:assert data['inputs'][p.relative_to(ROOT).as_posix()]==hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run()
        data=dict(all_passed=True,cases_passed=len(checks),approved=False,runtime_tests_executed=0,
                  device_tests_executed=0,sqlite_version=sqlite3.sqlite_version,checks=checks,
                  inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report:(HERE/'barrier-attempt-report.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
