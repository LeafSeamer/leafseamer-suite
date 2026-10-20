"""77表命令修订候选的内存事务检查；无网络、业务writer或设备入口。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import check_resource as R

F, HERE, ROOT, I, B, D, U = R.F, R.HERE, R.ROOT, R.I, R.B, R.D, R.U
INPUTS = list(dict.fromkeys(R.INPUTS + [HERE/n for n in ('command.sql', 'COMMAND_STORAGE.md', 'check_command.py')]))


def validation(name, purpose, subject, key='one'):
    return I('cm_validation', validation_id=name, command_id='command.'+key, purpose=purpose,
             subject_id=subject, subject_digest=D, policy_ref='completion.policy',
             provider_ref='trusted.fixture', source_body=B, receipt_body=B)


def revision(n, kind, key='one', phase='queued', outcome='pending', effect='not_sent',
             resource='clear', latched=0, terminal=None, resolution=None, decision=None,
             attempts=(), releases=()):
    cmd, op = 'command.'+key, key+'.'+str(n)
    return [validation('v.'+op, 'transition', op, key),
            I('cm_revision', command_id=cmd, revision=U(n), operation_id=op, kind=kind,
              previous_revision=U(n-1) if n > 1 else None, previous_digest=D if n > 1 else None,
              state_digest=D, transition_digest=D, phase=phase, outcome=outcome, effect_status=effect, resource_status=resource,
              paused_latched=latched, terminal_revision=U(terminal) if terminal else None,
              resolution_id=resolution, decision_id=decision, validation_id='v.'+op, state_body=B),
            *[I('cm_revision_attempt', command_id=cmd, revision=U(n), attempt_id=a) for a in attempts],
            *[I('cm_revision_release', command_id=cmd, revision=U(n), release_id=r) for r in releases],
            I('cm_commit', operation_id=op, command_id=cmd, revision=U(n),
              audit_body=B, outbox_id='state.'+op, outbox_body=B)]


def initial(key='one', retry=False):
    steps = R.command(key)
    at = next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO ca_commit '))
    policy = I('cm_policy', command_id='command.'+key, required_completion='effect_verified',
               completion_policy_ref='completion.policy', retry_policy_ref='retry.policy' if retry else None,
               max_attempts=2 if retry else 1, original_deadline_body=B, policy_body=B)
    steps[at:at] = [policy]+revision(1, 'initial', key)
    return steps


def prepare(key='one', aid='a', pkt='pkt', n=2, ordinal=1, old=()):
    return [I('cm_attempt', attempt_id=aid, command_id='command.'+key, ordinal=ordinal, prepared_revision=U(n)),
            F.attempt(aid, key),
            *revision(n, 'prepare', key, attempts=(*old, aid))]


def dispatch(key='one', aid='a', hid='h', pid='permit.1', pkt='pkt', n=3, issued=1, attempts=('a',),
             releases=()):
    steps = R.dispatch(key, aid, hid, pid, pkt, issued)[1:]
    at = next(i for i,s in enumerate(steps) if s[0].startswith('INSERT INTO ce_permit '))
    steps.insert(at, I('cm_dispatch_binding', hold_id=hid, command_id='command.'+key, revision=U(n)))
    return steps+revision(n, 'dispatch', key, phase='dispatching', effect='possible',
                          resource='held', attempts=attempts, releases=releases)


def report(n=4, kind='transport', state='in_flight', rid='report', key='one', pid='permit.1',
           **state_args):
    return [I('cm_report_receipt', worker_boot_id='worker.exit.0', ipc_session_id='ipc.exit.0',
              worker_report_id='worker.'+rid, stored_report_id=rid, command_id='command.'+key,
              revision=U(n), report_digest=D),
            F.report(pid, state, rid), *revision(n, kind, key, **state_args)]


def decision(eid='e', kind='completion', key='one', achieved='effect_verified', effect='verified',
             retry=None, resolved=None):
    return [validation('v.'+eid, kind, eid, key),
            I('cm_decision', evidence_id=eid, command_id='command.'+key, kind=kind,
              achieved=achieved if kind == 'completion' else None, effect_status=effect,
              retry_policy_ref=retry, resolved_outcome=resolved, validation_id='v.'+eid,
              evidence_digest=D, evidence_body=B)]


def resolution(n=6, ordinal=1, rid='z', terminal=5):
    return decision('e.'+rid, 'resolution', resolved='succeeded')+[
        I('cm_resolution', resolution_id=rid, command_id='command.one', revision=U(ordinal),
          original_terminal_revision=U(terminal), published_revision=U(n), resolved_outcome='succeeded',
          decision_id='e.'+rid, resolver_ref='resolver', resolution_digest=D, resolution_body=B)]


def reconcile_release():
    return R.close()+R.settle(kind='effect_resolved')+R.release(kind='module_settled')+resolution()+revision(
        6, 'reconcile', phase='finished', outcome='unknown', effect='verified', latched=1, terminal=5,
        resolution='z', decision='e.z', attempts=('a',), releases=('r',))


def run():
    checks, connections = [], []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(name=name, expected=expected, observed=actual))

    def fresh(stage='waiting', retry=False):
        db = F.L.fixture()
        connections.append(db)
        for name in ('fence.sql', 'barrier-attempt.sql', 'resource.sql', 'command.sql'):
            db.executescript((HERE/name).read_text(encoding='utf-8'))
        db.execute(*F.A.namespace())
        F.tx(db, F.P.register())
        F.tx(db, F.P.change())
        db.execute(*F.exit_step())
        db.execute(*F.exit_step('exit.1'))
        if stage == 'empty':
            return db
        F.tx(db, initial(retry=retry))
        if stage == 'queued':
            return db
        F.tx(db, prepare())
        if stage == 'prepared':
            return db
        F.tx(db, dispatch())
        if stage == 'sent':
            return db
        F.tx(db, report(phase='awaiting_evidence', effect='possible', resource='held', attempts=('a',)))
        if stage == 'waiting':
            return db
        F.tx(db, revision(5, 'timeout', phase='finished', outcome='unknown', effect='possible',
                         resource='unresolved', latched=1, terminal=5, attempts=('a',)))
        if stage == 'unknown':
            return db
        F.tx(db, reconcile_release())
        return db

    def denied(name, db, steps, error=None):
        before = F.snapshot(db)
        try:
            F.tx(db, steps)
        except sqlite3.IntegrityError as exc:
            check(name, str(exc) if error else 'rejected', error or 'rejected')
        else:
            raise AssertionError(name+': 应拒绝')
        check(name+'全库回滚', F.snapshot(db) == before, True)

    def atomic(name, stage, steps):
        for i in range(len(steps)):
            db = fresh(stage)
            denied(name+'缺写'+str(i), db, steps[:i]+steps[i+1:])
            db = fresh(stage)
            before = F.snapshot(db)
            try:
                F.tx(db, steps, cut=i)
            except RuntimeError:
                check(name+'异常'+str(i), F.snapshot(db) == before, True)
            else:
                raise AssertionError('未注入故障')

    def state(db, view='cm_current'):
        return db.execute('SELECT phase,outcome,resource_status,paused_latched,terminal_revision,resolution_id '
                          'FROM '+view+" WHERE command_id='command.one'").fetchone()

    try:
        check('77表组合', len(F.snapshot(fresh())), 77)
        atomic('T1初始修订', 'empty', initial())
        atomic('准备修订', 'queued', prepare())
        atomic('T2派发修订', 'prepared', dispatch())
        atomic('报告与状态提交', 'sent', report(phase='awaiting_evidence', effect='possible',
                                             resource='held', attempts=('a',)))
        atomic('T6核对与释放', 'unknown', reconcile_release())
        db = fresh('resolved')
        check('原unknown及终态修订保持', state(db),
              ('finished', 'unknown', 'clear', 1, U(5), 'z'))
        check('Resolution独立修订', db.execute('SELECT revision,published_revision FROM cm_resolution').fetchone(),
              (U(1), U(6)))
        before = F.snapshot(db)
        check('REPORT_STORED可查持久原回执', db.execute(
            "SELECT revision FROM cm_report_receipt WHERE worker_report_id='worker.report'").fetchone()[0], U(4))
        check('只查原回执不再发送', F.snapshot(db) == before, True)
        for field, value, error in [('outcome', 'succeeded', 'terminal_immutable'),
                                    ('phase', 'queued', 'terminal_immutable'),
                                    ('terminal_revision', U(7), 'terminal_immutable'),
                                    ('paused_latched', 0, 'latch_immutable'),
                                    ('resolution_id', None, 'resolution_rewrite')]:
            base = revision(7, 'observe', phase='finished', outcome='unknown', effect='verified',
                            latched=1, terminal=5, resolution='z', attempts=('a',), releases=('r',))
            denied('固定终态字段'+field, db, F.P.mutate(base, 'cm_revision', field, value),
                   None if field in ('phase', 'paused_latched', 'resolution_id') else error)
        base = revision(7, 'observe', phase='finished', outcome='unknown', effect='verified',
                        latched=1, terminal=5, resolution='z', attempts=('a',), releases=('r',))
        denied('状态修订不可跳号', db, F.P.mutate(base, 'cm_revision', 'revision', U(8)), 'state_successor')
        denied('旧摘要不能CAS', db, F.P.mutate(base, 'cm_revision', 'previous_digest', 'sha256:'+'b'*64), 'state_cas')
        denied('丢弃已发布释放历史', db,
               [s for s in base if not s[0].startswith('INSERT INTO cm_revision_release ')], 'release_history_lost')
        denied('回执不能复用给新状态', db,
               F.P.mutate(base, 'cm_validation', 'subject_id', 'alien'), 'transition_provider_binding')
        denied('转换摘要与提供者不一致', db,
               F.P.mutate(base, 'cm_revision', 'transition_digest', 'sha256:'+'b'*64), 'transition_provider_binding')
        denied('终态不能重试', db, F.P.mutate(base, 'cm_revision', 'kind', 'retry'), 'terminal_immutable')

        db = fresh()
        F.tx(db, decision()+revision(5, 'complete', phase='finished', outcome='succeeded', effect='verified',
                                    resource='unresolved', terminal=5, decision='e', attempts=('a',)))
        check('完成仍可资源未决', state(db), ('finished', 'succeeded', 'unresolved', 0, U(5), None))
        denied('succeeded禁止追加旧许可', db, F.transmission('permit.2', 2, 1, 'permit.1'), 'permit_command_state')
        for achieved, effect in [('sent', 'possible'), ('acknowledged', 'acknowledged')]:
            denied('低完成层级'+achieved, fresh(), decision(achieved=achieved, effect=effect)+revision(
                5, 'complete', phase='finished', outcome='succeeded', effect=effect, resource='unresolved',
                terminal=5, decision='e', attempts=('a',)), 'completion_level')
        denied('假定clear不能绕过未决hold', fresh(), decision()+revision(
            5, 'complete', phase='finished', outcome='succeeded', effect='verified', terminal=5,
            decision='e', attempts=('a',)), 'resource_not_clear')
        db = fresh('unknown')
        F.tx(db, R.close()+R.settle(kind='effect_resolved')+R.release(kind='module_settled'))
        check('资源子域已清但公共状态仍未决', state(db)[2], 'unresolved')
        F.tx(db, initial('two'))
        F.tx(db, prepare('two', 'b', 'pkt2'))
        denied('缺Resolution及状态提交不能放行另命令', db,
               dispatch('two', 'b', 'h2', 'permit.2', 'pkt2', issued=2, attempts=('b',)), 'command_resource_unresolved')
        denied('unknown无核对不能直接clear', db, revision(
            6, 'release', phase='finished', outcome='unknown', effect='possible', latched=1, terminal=5,
            attempts=('a',), releases=('r',)))
        F.tx(db, resolution()+revision(6, 'reconcile', phase='finished', outcome='unknown', effect='verified',
            latched=1, terminal=5, resolution='z', decision='e.z', attempts=('a',), releases=('r',)))
        F.tx(db, dispatch('two', 'b', 'h2', 'permit.2', 'pkt2', issued=2, attempts=('b',)))
        check('完整核对释放后允许另命令取得资源', db.execute('SELECT hold_id FROM cr_risk_hold').fetchall(), [('h2',)])

        db = fresh('resolved')
        denied('Resolution不接受旧序号', db, resolution(7, 1, 'z2'), 'resolution_successor')
        denied('Resolution不改原终态引用', db, resolution(7, 2, 'z2', terminal=6), 'resolution_binding')
        denied('Resolution须与选中状态成对', db, resolution(7, 2, 'z2')+revision(
            7, 'observe', phase='finished', outcome='unknown', effect='verified', latched=1,
            terminal=5, resolution='z', attempts=('a',), releases=('r',)), 'resolution_pair')
        F.tx(db, resolution(7, 2, 'z2')+revision(
            7, 'reconcile', phase='finished', outcome='unknown', effect='verified', latched=1,
            terminal=5, resolution='z2', decision='e.z2', attempts=('a',), releases=('r',)))
        check('后续核对不替换最初终态', state(db)[4:], (U(5), 'z2'))

        db = fresh('queued')
        F.tx(db, revision(2, 'cancel', phase='finished', outcome='cancelled', terminal=2))
        check('纯排队取消无需虚构hold', state(db), ('finished', 'cancelled', 'clear', 0, U(2), None))
        denied('取消后不登记attempt', db, prepare(n=3), 'attempt_state')
        denied('未派发不能成功完成', fresh('queued'), decision()+revision(
            2, 'complete', phase='finished', outcome='succeeded', effect='verified', terminal=2,
            decision='e'), 'invalid_transition')
        denied('已有传输取消须独立证据', fresh(), revision(
            5, 'cancel', phase='finished', outcome='cancelled', effect='possible',
            resource='unresolved', terminal=5, attempts=('a',)), 'cancellation_required')
        for kind,outcome,evidence_kind in [('fail','failed','failure'),('cancel','cancelled','cancellation')]:
            db=fresh()
            F.tx(db,decision(kind=evidence_kind,effect='partial')+revision(
                5,kind,phase='finished',outcome=outcome,effect='partial',resource='unresolved',
                terminal=5,decision='e',attempts=('a',)))
            check('独立证据终结'+outcome,state(db)[:3],('finished',outcome,'unresolved'))
        for kind,outcome in [('block','blocked'),('expire','expired')]:
            denied('在途不能伪装'+outcome, fresh(), revision(
                5,kind,phase='finished',outcome=outcome,effect='possible',resource='unresolved',
                latched=1,terminal=5,attempts=('a',)), 'stop_unfenced_or_uncertain')
            db=fresh('prepared')
            F.tx(db,revision(3,kind,phase='finished',outcome=outcome,latched=1,terminal=3,attempts=('a',)))
            check('未签发许可时终结'+outcome,state(db)[:4],('finished',outcome,'clear',1))
        denied('首闭环禁止隐式retry', fresh(), decision(kind='failure', retry='retry.policy')+revision(
            5, 'retry', effect='verified', resource='held', decision='e', attempts=('a',)), 'retry_forbidden')
        db = fresh(retry=True)
        F.tx(db, R.close()+R.settle(kind='effect_resolved')+R.release(kind='module_settled')+
             decision(kind='failure', effect='partial', retry='retry.policy')+
             revision(5, 'retry', effect='partial', decision='e', attempts=('a',), releases=('r',)))
        # prepare/dispatch必须保留既往partial与释放引用，不能重置命令历史。
        next_prepare = prepare(aid='b', pkt='pkt2', n=6, ordinal=2, old=('a',))
        next_prepare = [s for s in next_prepare if not s[0].startswith(('INSERT INTO cm_validation ',
                        'INSERT INTO cm_revision ', 'INSERT INTO cm_revision_attempt ', 'INSERT INTO cm_commit '))]
        next_prepare += revision(6, 'prepare', effect='partial', attempts=('a', 'b'), releases=('r',))
        F.tx(db, next_prepare)
        next_dispatch = F.P.mutate(dispatch(aid='b', hid='h2', pid='permit.2', pkt='pkt2', n=7, issued=2,
                                             attempts=('a', 'b'), releases=('r',)), 'cm_revision', 'effect_status', 'partial')
        F.tx(db, next_dispatch)
        check('重试另建attempt且保留原partial', db.execute(
            'SELECT effect_status FROM cm_latest').fetchone()[0], 'partial')
        check('原策略与期限不随重试改变',
              db.execute('SELECT max_attempts,original_deadline_body FROM cm_policy').fetchone() == (2, B), True)
        denied('新尝试不借旧进入传输证据', db, revision(
            8,'transport',phase='awaiting_evidence',effect='partial',resource='held',
            attempts=('a','b'),releases=('r',)), 'invalid_transition')
        F.tx(db, report(8,pid='permit.2',rid='retry.report',phase='awaiting_evidence',
                       effect='partial',resource='held',attempts=('a','b'),releases=('r',)))
        check('新尝试独立报告后推进', state(db)[0], 'awaiting_evidence')

        db = fresh('resolved')
        # 撤回release原件先使旧clear投影不可发布；保护事实独立持久，不改旧终态。
        db.execute(*I('cr_validation_revocation', validation_id='v.r', reason_body=B, audit_body=B))
        check('迟到失效隐藏旧clear当前投影', state(db), None)
        check('历史终态仍可审计', state(db, 'cm_latest')[1], 'unknown')
        F.tx(db, revision(7, 'protect', phase='finished', outcome='unknown', effect='verified',
                         resource='unresolved', latched=1, terminal=5, resolution='z',
                         attempts=('a',), releases=('r',)))
        check('保护修订恢复保守当前投影', state(db)[2:4], ('unresolved', 1))
        for table in ('cm_policy','cm_validation','cm_decision','cm_attempt','cm_revision',
                      'cm_revision_attempt','cm_revision_release','cm_resolution','cm_report_receipt',
                      'cm_commit','cm_dispatch_binding'):
            col = db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for label,sql in [('更新',f'UPDATE {table} SET {col}={col}'),
                              ('删除','DELETE FROM '+table),
                              ('替换',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')]:
                denied(table+label, db, [(sql,())], None if label == '替换' else 'immutable_command')
        denied('报告原件不能先于身份映射独立提交', fresh('sent'), [F.report()], 'report_receipt_binding')
        db = fresh('sent')
        body = report(phase='awaiting_evidence', effect='possible', resource='held', attempts=('a',))
        for field in ('worker_boot_id','ipc_session_id','command_id'):
            denied('原报告归属错配'+field, db, F.P.mutate(body, 'cm_report_receipt', field, 'alien'), 'report_receipt_binding')
        F.tx(db, body)
        denied('同worker报告不能换内部ID重复写', db,
               F.P.mutate(report(5, 'observe', phase='awaiting_evidence', effect='possible',
                                resource='held', attempts=('a',)), 'cm_report_receipt', 'stored_report_id', 'alias'))
        F.tx(db,[F.packet('pkt.other','a','exit.1','primitive.2')]+
             F.transmission('permit.other',2,pkt='pkt.other',eid='exit.1'))
        F.tx(db,[I('cm_report_receipt',worker_boot_id='worker.exit.1',ipc_session_id='ipc.exit.1',
             worker_report_id='worker.report',stored_report_id='report.other',command_id='command.one',
             revision=U(5),report_digest=D),
             F.report('permit.other','in_flight','report.other','exit.1'),
             *revision(5,'observe',phase='awaiting_evidence',effect='possible',resource='held',attempts=('a',))])
        check('不同worker可有相同本地报告ID',db.execute(
            "SELECT count(*) FROM cm_report_receipt WHERE worker_report_id='worker.report'").fetchone()[0],2)
        check('外键全部通过', db.execute('PRAGMA foreign_key_check').fetchall(), [])
        check('完整性检查通过', db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        check('BODY仍为合成限制', db.execute('SELECT state_body FROM cm_latest').fetchone()[0] == B, True)
        return checks
    finally:
        for db in connections:
            db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--check-report', action='store_true')
    parser.add_argument('--staged', action='store_true')
    args = parser.parse_args()
    if args.staged and not args.check_report:
        parser.error('--staged需配合--check-report')
    if args.check_report:
        read = (lambda p: subprocess.check_output(['git', 'show', ':'+p.relative_to(ROOT).as_posix()],
                                                  cwd=ROOT)) if args.staged else type(HERE).read_bytes
        data = json.loads(read(HERE/'command-report.json'))
        assert set(data['inputs']) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:
            assert data['inputs'][p.relative_to(ROOT).as_posix()] == hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True, matched_bindings=len(INPUTS))))
    else:
        checks = run()
        data = dict(all_passed=True, cases_passed=len(checks), approved=False,
                    scope='77表内存组合的命令修订、固定终态、报告身份和资源联接',
                    runtime_tests_executed=0, device_tests_executed=0, sqlite_version=sqlite3.sqlite_version,
                    checks=checks, inputs={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in INPUTS})
        if args.report:
            (HERE/'command-report.json').write_bytes((json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks', 'inputs')}, ensure_ascii=False))
