"""资源候选的66表内存实验；不接受磁盘DB或设备连接参数。"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import check_barrier_attempt as BA

F = BA.F
HERE, ROOT, I, B, D, U = F.HERE, F.ROOT, F.I, F.B, F.D, F.U
INPUTS = list(dict.fromkeys(BA.INPUTS + [HERE/n for n in (
    'resource.sql', 'RESOURCE_STORAGE.md', 'LIFECYCLE.md', 'check_resource.py')]))


def validation(name, purpose, subject, key='one', device='dev.1', policy='release.policy'):
    return I('cr_validation', validation_id=name, scope_id=1,
             command_id=None if purpose == 'recovery' else 'command.'+key,
             device_id=device, purpose=purpose, subject_id=subject, subject_digest=D,
             policy_ref=policy, provider_ref='trusted.fixture', source_body=B, receipt_body=B)


def command(key='one', origin='automation'):
    steps = F.command(key, origin)
    at = next(i for i, s in enumerate(steps) if s[0].startswith('INSERT INTO ca_commit '))
    steps.insert(at, I('cr_claim', command_id='command.'+key,
                       release_policy_ref='release.policy', policy_body=B))
    return steps


def dispatch(key='one', aid='a', hid='h', pid='permit.1', pkt='pkt', revision=1):
    return [
        F.attempt(aid, key), F.packet(pkt, aid),
        validation('v.'+hid, 'hold', hid, key),
        I('cr_hold', hold_id=hid, command_id='command.'+key, attempt_id=aid,
          validation_id='v.'+hid, hold_digest=D, hold_body=B),
        *F.transmission(pid, revision=revision, pkt=pkt, aid=aid),
        I('cr_hold_commit', hold_id=hid, audit_body=B, outbox_id='hold.'+hid, outbox_body=B)]


def close(hid='h', key='one', vid=None):
    vid = vid or 'close.'+hid
    return [validation(vid, 'close', hid, key),
            I('cr_hold_close', hold_id=hid, validation_id=vid,
              closure_digest=D, closure_body=B, audit_body=B)]


def settle(pid='permit.1', sid='s', key='one', kind='never_sent'):
    steps = []
    if kind == 'never_sent':
        steps.append(F.report(pid, 'not_sent', 'not.'+sid))
    steps += [F.settlement(pid, kind, sid, 'not.'+sid), validation('v.'+sid, 'settlement', sid, key),
              I('cr_settlement_validation', settlement_id=sid, validation_id='v.'+sid, settlement_digest=D)]
    return steps


def release(rid='r', hid='h', key='one', revision=1, kind='never_sent',
            attempts=(('a', 'h', 'close.h'),), members=(('permit.1', 's'),)):
    return [validation('v.'+rid, 'release', rid, key),
            I('cr_release', release_id=rid, hold_id=hid, command_id='command.'+key, kind=kind,
              issued_cut_revision=U(revision), validation_id='v.'+rid,
              release_digest=D, cut_body=B, release_body=B),
            *[I('cr_release_attempt', release_id=rid, attempt_id=a, hold_id=h,
                closure_validation_id=c) for a, h, c in attempts],
            *[I('cr_release_member', release_id=rid, permit_id=p, settlement_id=s) for p, s in members],
            I('cr_release_commit', release_id=rid, audit_body=B, outbox_id='release.'+rid, outbox_body=B)]


def recovery(name='recover', members=('r',)):
    return [validation('v.'+name, 'recovery', name),
            I('cr_recovery', recovery_id=name, device_id='dev.1', validation_id='v.'+name,
              recovery_digest=D, recovery_body=B),
            *[I('cr_recovery_member', recovery_id=name, release_id=r) for r in members],
            I('cr_recovery_commit', recovery_id=name, audit_body=B, outbox_id=name, outbox_body=B)]


def run():
    checks, connections = [], []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(name=name, expected=expected, observed=actual))

    def fresh(stage='sent', origin='automation'):
        db = F.L.fixture()
        connections.append(db)
        for name in ('fence.sql', 'barrier-attempt.sql', 'resource.sql'):
            db.executescript((HERE/name).read_text(encoding='utf-8'))
        db.execute(*F.A.namespace())
        F.tx(db, F.P.register())
        F.tx(db, F.P.change())
        if stage == 'empty':
            return db
        F.tx(db, command(origin=origin))
        db.execute(*F.exit_step())
        db.execute(*F.exit_step('exit.1'))
        if stage == 'queued':
            return db
        F.tx(db, dispatch())
        if stage == 'sent':
            return db
        F.tx(db, close()+settle())
        if stage == 'settled':
            return db
        F.tx(db, release())
        if stage == 'released':
            return db
        db.execute(*F.report())
        if stage == 'invalid':
            return db
        F.tx(db, settle(sid='fixed', kind='effect_resolved') +
             release('r.fixed', kind='module_settled', members=(('permit.1', 'fixed'),)))
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
            # 提供者原件可独立提交；本实验仍将其与领域写集一并回滚。
            denied(name+'缺写'+str(i), db, steps[:i]+steps[i+1:])
            db = fresh(stage)
            before = F.snapshot(db)
            try:
                F.tx(db, steps, cut=i)
            except RuntimeError:
                check(name+'故障'+str(i), F.snapshot(db) == before, True)
            else:
                raise AssertionError('没有注入故障')

    def risks(db):
        return [r[0] for r in db.execute('SELECT hold_id FROM cr_risk_hold ORDER BY hold_id')]

    def protected(db):
        return [r[0] for r in db.execute('SELECT release_id FROM cr_device_protection ORDER BY release_id')]

    try:
        check('66表组合', len(F.snapshot(fresh())), 66)
        atomic('T1受理含claim', 'empty', command())
        atomic('T2占用和首传输', 'queued', dispatch())
        atomic('完整释放封存', 'settled', release())
        atomic('保护恢复封存', 'repaired', recovery())

        for origin in ('manual', 'automation'):
            db = fresh(origin=origin)
            check(origin+'共用风险视图', risks(db), ['h'])
            F.tx(db, command('two', 'manual' if origin == 'automation' else 'automation'))
            denied(origin+'阻另一来源取得hold', db, dispatch('two', 'b', 'h2', 'permit.2', 'pkt2', 2), 'resource_busy')
            F.tx(db, close()+settle()+release())
            check(origin+'独立释放后风险清理', risks(db), [])
            F.tx(db, dispatch('two', 'b', 'h2', 'permit.2', 'pkt2', 2))
            check(origin+'另命令可以取得hold', risks(db), ['h2'])
            # 确实进入传输的旧事实须接收，不能以唯一活跃hold冲突丢弃。
            db.execute(*F.report())
            check(origin+'迟到保留双风险占用', risks(db), ['h', 'h2'])
            check(origin+'同事务建立设备保护', protected(db), ['r'])
            denied(origin+'保护阻新holder重传', db,
                   F.transmission('permit.3', 3, 1, 'permit.2', 'pkt2', 'b'), 'device_protected')
            check(origin+'旧发送事实原件仍在', db.execute(
                "SELECT count(*) FROM ce_report WHERE report_id='report'").fetchone()[0], 1)

        db = fresh()
        denied('未释放旧attempt不能创建新attempt', db, [F.attempt('retry')], 'previous_attempt_unreleased')
        F.tx(db, F.transmission('permit.2', 2, 1, 'permit.1'))
        F.tx(db, close()+settle()+settle('permit.2', 's2'))
        denied('同packet最后重传不代表全部传输', db,
               release(revision=2, members=(('permit.2', 's2'),)), 'release_permit_set')
        denied('完整成员也不能互换核销', db,
               release(revision=2, members=(('permit.1', 's2'), ('permit.2', 's'))), 'release_member_unproven')
        F.tx(db, release(revision=2, members=(('permit.1', 's'), ('permit.2', 's2'))))
        check('同packet两份许可独立归档', db.execute('SELECT count(*) FROM cr_release_member').fetchone()[0], 2)
        # 源事实、失效与保护派生必须同一次提交；回滚不能留下其中任何半边。
        for source in ('report', 'revocation'):
            db = fresh('released')
            step = F.report() if source == 'report' else I(
                'cr_validation_revocation', validation_id='v.r', reason_body=B, audit_body=B)
            before = F.snapshot(db)
            try:
                F.tx(db, [step], cut=0)
            except RuntimeError:
                check(source+'与派生保护原子回滚', F.snapshot(db) == before, True)
            else:
                raise AssertionError('未注入故障')
            F.tx(db, [step])
            check(source+'提交同时锁存保护', protected(db), ['r'])
        db = fresh('released')
        db.execute(*validation('unrelated', 'hold', 'other.hold'))
        db.execute(*I('cr_validation_revocation', validation_id='unrelated', reason_body=B, audit_body=B))
        check('无关原件撤回不误保护', protected(db), [])
        check('无关原件撤回不改变风险', risks(db), [])
        for label, sql in [('更新', 'UPDATE cr_validation_revocation SET reason_body=reason_body'),
                           ('删除', 'DELETE FROM cr_validation_revocation'),
                           ('替换', 'INSERT OR REPLACE INTO cr_validation_revocation SELECT * FROM cr_validation_revocation')]:
            denied('撤回墓碑'+label, db, [(sql, ())], None if label == '替换' else 'immutable_resource')

        db = fresh('released')
        denied('关闭后同attempt不能发新许可', db,
               F.transmission('permit.2', 2, 1, 'permit.1'), 'hold_closed')
        F.tx(db, dispatch(aid='retry', hid='h.retry', pid='permit.2', pkt='pkt2', revision=2))
        check('后续attempt不追溯推翻先前释放', risks(db), ['h.retry'])
        F.tx(db, close('h.retry')+settle('permit.2', 's2'))
        denied('只列最后attempt拒绝', db,
               release('r2', 'h.retry', revision=2, attempts=(('retry', 'h.retry', 'close.h.retry'),),
                       members=(('permit.2', 's2'),)), 'release_attempt_set')
        all_attempts = (('a', 'h', 'close.h'), ('retry', 'h.retry', 'close.h.retry'))
        denied('只列最后传输拒绝', db, release('r2', 'h.retry', revision=2, attempts=all_attempts,
               members=(('permit.2', 's2'),)), 'release_permit_set')
        F.tx(db, release('r2', 'h.retry', revision=2, attempts=all_attempts,
                        members=(('permit.1', 's'), ('permit.2', 's2'))))
        check('全部历史已核销传输仍在cut', db.execute(
            "SELECT count(*) FROM cr_release_member WHERE release_id='r2'").fetchone()[0], 2)
        db.execute(*F.report())
        check('迟到旧传输推翻两个依赖释放', protected(db), ['r', 'r2'])
        check('历史两hold均保留风险', risks(db), ['h', 'h.retry'])

        for field, value, error in [
            ('device_id', 'other.device', 'release_binding'),
            ('command_id', 'command.missing', None),
            ('policy_ref', 'other.policy', 'release_binding'),
            ('subject_id', 'other.release', 'release_binding'),
            ('purpose', 'settlement', 'release_binding'),
            ('subject_digest', 'sha256:'+'b'*64, 'release_binding'),
            ('scope_id', 2, None)]:
            denied('拒绝释放提供者错配'+field, fresh('settled'),
                   F.P.mutate(release(), 'cr_validation', field, value), error)
        denied('切点水位错配', fresh('settled'),
               F.P.mutate(release(), 'cr_release', 'issued_cut_revision', U(2)), 'release_binding')
        for v in ('1', '-1'.zfill(20), 'x'*20, '0'*19+'\n'):
            denied('非法切点'+repr(v), fresh('settled'),
                   F.P.mutate(release(), 'cr_release', 'issued_cut_revision', v))
        db = fresh()
        F.tx(db, settle())
        denied('缺后续写关闭证明不能释放', db, release())
        db = fresh()
        F.tx(db, close()+[F.settlement(kind='effect_resolved', sid='raw')])
        denied('原核销BODY不代替验证', db, release(members=(('permit.1', 'raw'),)))
        db = fresh()
        F.tx(db, close()+settle(kind='effect_resolved'))
        denied('效果核销不能伪装never_sent', db, release(), 'release_member_unproven')
        F.tx(db, release(kind='module_settled'))
        db.execute(*F.report())
        check('独立效果证明不被重复发送观察推翻', risks(db), [])
        check('独立效果证明无误保护', protected(db), [])

        for vid in ('v.r', 'v.s', 'close.h'):
            db = fresh('released')
            db.execute(*I('cr_validation_revocation', validation_id=vid, reason_body=B, audit_body=B))
            check('撤回提供者原件重开风险'+vid, risks(db), ['h'])
            check('撤回提供者原件锁存保护'+vid, protected(db), ['r'])
        db = fresh('released')
        db.execute(*I('cr_validation_revocation', validation_id='close.h', reason_body=B, audit_body=B))
        F.tx(db, close(vid='close.new')+release('r.new', attempts=(('a', 'h', 'close.new'),)))
        check('新关闭证据可独立核对释放', risks(db), [])
        check('新释放不隐式解除设备保护', protected(db), ['r'])
        db = fresh('invalid')
        denied('风险未清理不得恢复', db, recovery(), 'recovery_resource_busy')
        db = fresh('repaired')
        denied('恢复漏旧保护项', db, recovery(members=()), 'recovery_protection_set')
        F.tx(db, recovery())
        check('完整恢复后保护清理', protected(db), [])
        before = F.snapshot(db)
        check('恢复响应丢失可查原记录', db.execute(
            "SELECT recovery_id FROM cr_recovery_commit WHERE recovery_id='recover'").fetchone()[0], 'recover')
        check('查原不生成新许可', F.snapshot(db) == before, True)
        denied('原恢复身份不能重写', db, recovery())
        db.execute(*I('cr_validation_revocation', validation_id='v.recover', reason_body=B, audit_body=B))
        check('恢复证据撤回重新保护', protected(db), ['r'])
        F.tx(db, recovery('recover2'))
        check('新恢复原件可重新核对', protected(db), [])
        F.tx(db, command('two', 'manual')+dispatch('two', 'b', 'h2', 'permit.2', 'pkt2', 2))
        F.tx(db, close('h2', 'two')+settle('permit.2', 's2', 'two')+
             release('r2', 'h2', 'two', 2, attempts=(('b', 'h2', 'close.h2'),), members=(('permit.2', 's2'),)))
        db.execute(*F.report('permit.2', 'in_flight', 'late2'))
        check('恢复后新保护不被旧恢复覆盖', protected(db), ['r2'])

        # 迟到的旧屏障ACK和逐出口应用均可独立提升发送事实。
        for source in ('ack', 'target'):
            db = fresh()
            F.tx(db, F.fence(items=(('permit.1', 'exit.0', 0),)))
            if source == 'ack':
                F.tx(db, [BA.attempt()])
            F.tx(db, close()+settle()+release())
            if source == 'ack':
                F.tx(db, BA.ack(state='in_flight'))
            else:
                db.execute(*I('ce_retirement', exit_id='exit.0', supervisor_evidence_body=B))
                F.tx(db, BA.select(state='in_flight', kind='supervisor_retired'))
            check(source+'强证据重开风险', risks(db), ['h'])
            check(source+'强证据锁存保护', protected(db), ['r'])

        db = fresh('repaired')
        F.tx(db, recovery())
        for table in ('cr_validation', 'cr_claim', 'cr_hold', 'cr_hold_commit', 'cr_hold_close',
                      'cr_settlement_validation', 'cr_release', 'cr_release_attempt', 'cr_release_member',
                      'cr_release_commit', 'cr_release_invalidation', 'cr_recovery', 'cr_recovery_member',
                      'cr_recovery_commit'):
            col = db.execute('PRAGMA table_info('+table+')').fetchone()[1]
            for label, sql in [('更新', f'UPDATE {table} SET {col}={col}'),
                               ('删除', 'DELETE FROM '+table),
                               ('替换', f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')]:
                denied(table+label, db, [(sql, ())], None if label == '替换' else 'immutable_resource')
        denied('释放封存后不可添加成员', db,
               [I('cr_release_member', release_id='r', permit_id='permit.1', settlement_id='s')], 'release_frozen')
        denied('恢复封存后不可添加成员', db,
               [I('cr_recovery_member', recovery_id='recover', release_id='r')], 'recovery_frozen')
        check('所有外键通过', db.execute('PRAGMA foreign_key_check').fetchall(), [])
        check('所有数据库完整性通过', db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        check('合成BODY不证明提供者权威', db.execute(
            "SELECT receipt_body FROM cr_validation LIMIT 1").fetchone()[0] == B, True)
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
        data = json.loads(read(HERE/'resource-report.json'))
        assert set(data['inputs']) == {p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:
            assert data['inputs'][p.relative_to(ROOT).as_posix()] == hashlib.sha256(read(p)).hexdigest()
        print(json.dumps(dict(all_passed=True, matched_bindings=len(INPUTS))))
    else:
        checks = run()
        data = dict(all_passed=True, cases_passed=len(checks), approved=False,
                    scope='66表内存组合的资源占用、释放、迟到失效及保护恢复',
                    runtime_tests_executed=0, device_tests_executed=0, sqlite_version=sqlite3.sqlite_version,
                    checks=checks, inputs={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in INPUTS})
        if args.report:
            (HERE/'resource-report.json').write_bytes((json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks', 'inputs')}, ensure_ascii=False))
