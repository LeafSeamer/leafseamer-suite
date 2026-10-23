"""执行登记与保护切点的内存参考检查；没有网络、设备或外部数据库入口。"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import check_layout as L

HERE, ROOT = L.HERE, L.ROOT
P, A = L.PREP, L.ADM
I, B, D, U = L.insert, L.BODY, L.DIGEST, L.decimal
INPUTS = list(dict.fromkeys(L.INPUTS + [HERE/n for n in ('fence.sql','FENCE.md','check_fence.py')]
                          + [ROOT/'docs/rebirth-f02-f03-design.md',
                             ROOT/'docs/rebirth-c11-obs-atem-design.md']))


def tx(db, steps, cut=None):
    P.transact(db, L.prep_steps(steps), cut)


def command(key='one', origin='automation', prep='p'):
    steps = P.mutate(A.creation(key=key, idem='request.'+key), 'ca_request_key', 'device_id', 'dev.1')
    index = next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO ca_commit '))
    steps.insert(index, I('ce_command',command_id='command.'+key,device_id='dev.1',origin=origin,
                         prep_key=prep if origin=='automation' else None,
                         receipt_id='receipt.'+prep if origin=='automation' else None,binding_body=B))
    return steps


def exit_step(name='exit.0', device='dev.1'):
    return I('ce_exit',exit_id=name,device_id=device,controller_boot_id='core',
             worker_boot_id='worker.'+name,ipc_session_id='ipc.'+name,
             device_session_id='device.'+name,clock_domain_id='clock',
             descriptor_digest=D,runtime_binding_body=B)


def attempt(name='a', key='one'):
    return I('ce_attempt',attempt_id=name,command_id='command.'+key,authorization_body=B,attempt_body=B)


def packet(name='pkt', aid='a', eid='exit.0', primitive='primitive.1'):
    return I('ce_packet',packet_id=name,attempt_id=aid,exit_id=eid,primitive_id=primitive,packet_body=B)


def transmission(name='permit.1', revision=1, ordinal=0, parent=None, pkt='pkt', aid='a', eid='exit.0'):
    return [
        I('ce_permit',permit_id=name,attempt_id=aid,exit_id=eid,packet_id=pkt,
          issued_revision=U(revision),ordinal=ordinal,kind='initial' if ordinal==0 else 'protocol_resend',
          parent_permit_id=parent,permit_body=B),
        I('ce_transmission_commit',permit_id=name,guard_body=B,budget_charge_body=B,
          dispatch_intent_body=B,audit_body=B)]


def report(pid='permit.1', state='in_flight', rid='report', eid='exit.0'):
    return I('ce_report',report_id=rid,permit_id=pid,exit_id=eid,disposition=state,
             proof={'in_flight':'transport_entered','not_sent':'never_received','unknown':'send_uncertain'}[state],
             evidence_body=B)


def settlement(pid='permit.1', kind='never_sent', sid='settled', rid='report'):
    return I('ce_settlement',settlement_id=sid,permit_id=pid,kind=kind,
             report_id=rid if kind=='never_sent' else None,evidence_body=B)


def fence(targets=('exit.0','exit.1'), items=(('permit.1','exit.0',0),),
          queued=(), revision=1, source='protect', name='f', key='protection', raise_deny=True):
    # 期望集合由每个用例显式提供，不查询待测expected_*视图生成。
    if source=='protect':
        steps=L.protect(key=key,targets=len(targets),raise_deny=raise_deny)
        steps=[s for s in steps if not s[0].startswith('INSERT INTO run_protection_target ')]
        steps[1:1]=[I('run_protection_target',protection_id=key,target_id=e,target_body=B) for e in targets]
        close=None
    else:
        close='close.p.one'
        steps=P.mutate(P.close(previous='2',receipt='receipt.p',raise_deny=raise_deny),
                       'cp_protection','target_count',len(targets))
        steps=[s for s in steps if not s[0].startswith('INSERT INTO cp_protection_target ')]
        index=next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO cp_protection '))+1
        steps[index:index]=[I('cp_protection_target',close_id=close,target_id=e,target_body=B) for e in targets]
    additions=[I('ce_fence',fence_id=name,protection_id=key if source=='protect' else None,
                 close_id=close,issued_cut_revision=str(revision).zfill(20),cut_body=B)]
    additions += [I('ce_target',fence_id=name,exit_id=e,ledger_digest=D,target_body=B) for e in targets]
    additions += [I('ce_item',fence_id=name,permit_id=p,exit_id=e,entered_known=k) for p,e,k in items]
    additions += [I('ce_queued',fence_id=name,command_id='command.'+c,reason='run_generation_denied') for c in queued]
    additions += [I('ce_cut_commit',fence_id=name,audit_body=B,outbox_event_id='cut.'+name,outbox_body=B)]
    return steps[:-1]+additions+steps[-1:]


def result(eid='exit.0', items=(('permit.1','unknown'),), name='f', kind='worker_ack'):
    steps=[I('ce_coverage',fence_id=name,permit_id=p,exit_id=eid,disposition=state,
             proof={'in_flight':'transport_entered','not_sent':'never_received','unknown':'send_uncertain'}[state],
             evidence_body=B) for p,state in items]
    return steps+[I('ce_target_result',fence_id=name,exit_id=eid,evidence_kind=kind,evidence_body=B,audit_body=B)]


def application(name='f'):
    return I('ce_application',fence_id=name,receipt_id='receipt.'+name,receipt_body=B,
             audit_body=B,outbox_event_id='applied.'+name,outbox_body=B)


def snapshot(db):
    return {t:sorted(db.execute('SELECT * FROM '+t).fetchall(),key=repr)
            for t, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")}


def run():
    checks, connections=[],[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def fresh(stage='sent'):
        db=L.fixture(); connections.append(db)
        db.executescript((HERE/'fence.sql').read_text(encoding='utf-8'))
        db.execute(*A.namespace())
        if stage=='empty': return db
        tx(db,P.register());tx(db,P.change())
        if stage=='prepared': return db
        tx(db,command())
        db.execute(*exit_step());db.execute(*exit_step('exit.1'))
        if stage=='queued': return db
        tx(db,[attempt(),packet()])
        if stage=='attempt': return db
        tx(db,transmission())
        return db
    def denied(name,db,steps,message=None):
        before=snapshot(db)
        try: tx(db,steps)
        except sqlite3.IntegrityError as error:
            check(name,str(error) if message else 'constraint_rejected',message or 'constraint_rejected')
        else: raise AssertionError(name+': 必须拒绝')
        check(name+'全库回滚',snapshot(db)==before,True)
    def open_ids(db):
        return [r[0] for r in db.execute('SELECT permit_id FROM ce_open_permit ORDER BY permit_id')]
    def atomic(label,stage,steps,setup=()):
        for i in range(len(steps)):
            db=fresh(stage);tx(db,setup) if setup else None
            denied(label+'缺写'+str(i),db,steps[:i]+steps[i+1:])
            db=fresh(stage);tx(db,setup) if setup else None
            before=snapshot(db)
            try: tx(db,steps,cut=i)
            except RuntimeError as e: check(label+'异常'+str(i),str(e),'injected_before_commit')
            else: raise AssertionError('未注入异常')
            check(label+'回滚'+str(i),snapshot(db)==before,True)
    try:
        db=fresh()
        check('组合46表',len(snapshot(db)),46)
        check('初始许可未决',open_ids(db),['permit.1'])
        check('所有FK',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        atomic('T1投影','prepared',command())
        atomic('T2许可','attempt',transmission())
        for source in ('protect','close'):
            atomic('P2'+source,'sent',fence(source=source))
            db=fresh();tx(db,fence(source=source))
            denied(source+'阻断新重传',db,transmission('late',2,1,'permit.1'),'run_denied')
            denied(source+'阻断新attempt',db,[attempt('late')],'run_denied')
            denied(source+'阻断新命令',db,command('late'),
                   'run_denied' if source=='protect' else 'preparation_not_applied')
            check(source+'保留在途未决',open_ids(db),['permit.1'])
        atomic('出口结果','sent',result(),fence())
        db=fresh();tx(db,fence())
        denied('汇总前缺出口',db,[application()],'coverage_incomplete')
        tx(db,result());check('单出口先落盘',db.execute('SELECT count(*) FROM ce_target_result').fetchone()[0],1)
        denied('不能把其余出口漏掉',db,[application()],'coverage_incomplete')
        tx(db,result('exit.1',()));tx(db,[application()])
        check('applied不核销',open_ids(db),['permit.1'])
        check('汇总FK',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        denied('固定回执不可替换',db,[('INSERT OR REPLACE INTO ce_application SELECT * FROM ce_application',())],'immutable')
        denied('冻结覆盖不可追加',db,result(),'coverage_frozen')
        db=fresh('empty');tx(db,fence(targets=(),items=(),revision=0))
        tx(db,[application()]);check('空目标仍持久拒绝',db.execute('SELECT count(*) FROM run_deny_current').fetchone()[0],1)
        db=fresh('queued');tx(db,fence(items=(),queued=('one',),revision=0))
        denied('queued不可后派',db,[attempt()],'run_denied')
        db=fresh('queued')
        denied('漏queued',db,fence(items=(),revision=0),'queued_set_incomplete')
        db=fresh()
        denied('漏旧出口',db,fence(targets=('exit.0',)),'target_set_incomplete')
        denied('漏许可',db,fence(items=()),'intent_set_incomplete')
        denied('切点不是当前高水位',db,fence(revision=0),'cut_revision')
        denied('原容器与切点错配',db,P.mutate(fence(),'run_protection_target','target_id','other'),'source_targets')
        denied('不能捏造已发送',db,P.mutate(fence(),'ce_item','entered_known',1),'entered_snapshot')
        db.execute(*report())
        tx(db,fence(items=(('permit.1','exit.0',1),)))
        denied('已知进入传输不可降级',db,result(),'coverage_downgrade')
        tx(db,result(items=(('permit.1','in_flight'),)))
        check('未等全集已采纳单出口强证据',db.execute('SELECT disposition FROM ce_current_disposition').fetchone()[0],'in_flight')
        db=fresh();tx(db,fence());tx(db,result(items=(('permit.1','not_sent'),)))
        db.execute(*report())
        check('迟到进入传输覆盖旧未发判断',db.execute('SELECT disposition FROM ce_current_disposition').fetchone()[0],'in_flight')
        check('原ACK保持原文',db.execute('SELECT disposition FROM ce_coverage').fetchone()[0],'not_sent')
        db=fresh();tx(db,fence())
        tx(db,result(items=(('permit.1','in_flight'),)))
        check('只有单出口ACK也立即保留强证据',
              db.execute('SELECT disposition FROM ce_current_disposition').fetchone()[0],'in_flight')
        db.execute(*report(state='not_sent',rid='contradictory'))
        denied('其余出口未齐仍禁止未发核销',db,[settlement(rid='contradictory')],'not_sent_unproven')
        db=fresh();db.execute(*report(state='not_sent'));db.execute(*settlement())
        check('可靠未发可核销',open_ids(db),[])
        db.execute(*report(rid='late'))
        check('更强证据重新列为未决',open_ids(db),['permit.1'])
        denied('不能以旧未发再次核销',db,[settlement(sid='again')],'not_sent_unproven')
        db.execute(*settlement(kind='effect_resolved',sid='resolved'))
        check('后续效果核对可另追加',open_ids(db),[])
        db=fresh()
        db.execute(*I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B))
        denied('退役出口不可新重传',db,transmission('late',2,1,'permit.1'),'exit_retired')
        tx(db,fence())
        denied('退役不证未发',db,result(items=(('permit.1','not_sent'),),kind='supervisor_retired'),'coverage_downgrade')
        tx(db,result(kind='supervisor_retired'))
        check('退役出口仍保留未知',open_ids(db),['permit.1'])
        db=fresh();tx(db,fence())
        denied('未有退役事实不能伪造',db,result(kind='supervisor_retired'),'retirement_unproven')
        db=fresh()
        tx(db,transmission('permit.2',2,1,'permit.1'))
        db.execute(*report());db.execute(*report('permit.2','not_sent','last'))
        db.execute(*settlement('permit.2',rid='last'))
        check('最后未发不清原发送',open_ids(db),['permit.1'])
        tx(db,[packet('pkt.2',primitive='primitive.2')]+transmission('permit.3',3,pkt='pkt.2'))
        check('同attempt不同primitive可独立初发',db.execute('SELECT count(*) FROM ce_permit WHERE ordinal=0').fetchone()[0],2)
        denied('不能跨packet借重传parent',db,transmission('bad',4,1,'permit.1',pkt='pkt.2'))
        denied('ordinal不可跳号',db,transmission('bad',4,3,'permit.1'),'ordinal_successor')
        denied('全局revision不可跳号',db,transmission('bad',5,2,'permit.1'),'issued_successor')
        denied('packet出口错配',db,transmission('bad',4,2,'permit.1',eid='exit.1'))
        db=fresh();tx(db,command('manual','manual'))
        tx(db,[attempt('m','manual'),packet('manual','m',primitive='manual')]+
           transmission('manual',2,pkt='manual',aid='m'))
        tx(db,fence(revision=2))
        check('run屏障不包含手动许可',db.execute('SELECT permit_id FROM ce_item').fetchall(),[('permit.1',)])
        tx(db,transmission('manual.2',3,1,'manual',pkt='manual',aid='m'))
        check('run拒绝不直接拦手动',db.execute("SELECT count(*) FROM ce_permit WHERE permit_id='manual.2'").fetchone()[0],1)
        db=fresh()
        tx(db,P.register('other',run='other.run'));tx(db,P.change('other'))
        tx(db,command('other',prep='other'))
        tx(db,[attempt('other','other'),packet('other','other',primitive='other')]+
           transmission('other',2,pkt='other',aid='other'))
        tx(db,fence(revision=2))
        check('相同设备的另一run不误纳入',db.execute('SELECT permit_id FROM ce_item').fetchall(),[('permit.1',)])
        # 已提交更强事实作为本次前态；新保护任何切点失败不得清除旧floor。
        first=fence()
        second=fence(source='close',name='close.f',raise_deny=False)
        atomic('已有floor后关闭','sent',second,first)
        db=fresh();tx(db,first);tx(db,second)
        check('close复用公共floor',db.execute('SELECT count(*) FROM run_deny_event').fetchone()[0],1)
        db=fresh()
        for n in range(2,258):
            tx(db,transmission('permit.'+str(n),n,n-1,'permit.1'))
        oversized=tuple(('permit.'+str(n),'exit.0',0) for n in range(1,258))
        denied('超256许可不能截断保护',db,fence(items=oversized,revision=257),'fence_capacity')
        check('容量拒绝保持原许可全集',len(open_ids(db)),257)
        db=fresh('empty')
        pending=fence(targets=(),items=(),revision=0)
        denied('空集合也不可先于来源提交应用',db,pending[:-1]+[application()]+pending[-1:],'cut_uncommitted')
        # seal后、来源commit前的同事务窗口不得追加改变登记集合。
        db=fresh();steps=fence()
        for table_step in (exit_step('late'),report(),settlement(kind='effect_resolved'),
                           I('ce_retirement',exit_id='exit.0',supervisor_evidence_body=B)):
            denied('seal后拒新增'+table_step[0].split()[2],db,steps[:-1]+[table_step]+steps[-1:],'pending_cut')
        db=fresh();tx(db,fence())
        tx(db,result());tx(db,result('exit.1',()));tx(db,[application()])
        for table in ('ce_command','ce_exit','ce_attempt','ce_packet','ce_permit','ce_transmission_commit',
                      'ce_fence','ce_target','ce_item','ce_cut_commit','ce_target_result','ce_coverage','ce_application'):
            col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            denied(table+'禁更新',db,[(f'UPDATE {table} SET {col}={col}',())],'immutable')
            denied(table+'禁删除',db,[('DELETE FROM '+table,())],'immutable')
        check('BODY不证明真实权威',db.execute('SELECT guard_body FROM ce_transmission_commit').fetchone()[0]==B,True)
        return checks
    finally:
        for db in connections: db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true')
    parser.add_argument('--staged',action='store_true')
    args=parser.parse_args()
    if args.staged and not args.check_report: parser.error('--staged需与--check-report共用')
    if args.check_report:
        read=(lambda p:subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        evidence=json.loads(read(HERE/'fence-report.json'))
        assert set(evidence['inputs'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS: assert evidence['inputs'][p.relative_to(ROOT).as_posix()]==hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run()
        # 快照只用于比较，不将整份合成库重复写入报告。
        evidence=dict(scope='46表内存组合的执行登记、运行保护切点及逐出口应用候选',
                      all_passed=True,cases_passed=len(checks),approved=False,runtime_tests_executed=0,
                      device_tests_executed=0,sqlite_version=sqlite3.sqlite_version,checks=checks,
                      inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report: (HERE/'fence-report.json').write_bytes((json.dumps(evidence,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in evidence.items() if k not in ('checks','inputs')},ensure_ascii=False))
