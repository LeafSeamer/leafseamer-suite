"""完整时间原件到现行IPC下界的离线检查；合成提供者，不运行产品。"""
import argparse
import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path
from jsonschema.exceptions import ValidationError
import check_contracts as C
import gate_snapshot_source_model as M

HERE = M.HERE
ROOT = HERE.parents[2]
COLLECTOR = M.BASE/'df03-collector'
spec = importlib.util.spec_from_file_location('time_storage_fixture', COLLECTOR/'check_storage.py')
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def fixtures():
    result = C.isolated_fixture('df03-reference', 'C.fixture()')
    context, anchor, _, _, invalidation = result['value']
    return context, anchor, invalidation, [Path(p) for p in result['inputs']]


def steps(context, anchor, invalidation, operation, mutation=None):
    batch = {'bootstrap': L.bootstrap, 'publish': L.publication, 'invalidate': L.invalidation}[operation]()
    binding = copy.deepcopy(context['binding'])
    if operation == 'invalidate':
        binding['time_generation'] = '2'
    state = copy.deepcopy(context['state'])
    state.update(revision={'bootstrap':'1','publish':'2','invalidate':'3'}[operation], binding=binding,
        status={'bootstrap':'collecting','publish':'qualified','invalidate':'unavailable'}[operation],
        current_anchor_ref=M.T.object_ref(anchor, 'anchor_id', 'anchor_digest') if operation == 'publish' else None,
        invalidation_ref=M.T.object_ref(invalidation, 'invalidation_id', 'invalidation_digest') if operation == 'invalidate' else None)
    M.T.seal(state, 'state_digest')
    result = []
    for sql, args in batch:
        args = list(args)
        if sql.startswith('INSERT INTO ts_binding '): args[-1] = M.raw(binding)
        if sql.startswith('INSERT INTO ts_state '): args[-1] = M.raw(state)
        if sql.startswith('INSERT INTO ts_anchor '):
            args[0], args[3], args[-1] = anchor['anchor_id'], anchor['anchor_tick_ns'].zfill(20), M.raw(anchor)
        if sql.startswith('INSERT INTO ts_state ') and operation == 'publish': args[4] = anchor['anchor_id']
        if sql.startswith('INSERT INTO ts_invalidation '):
            # 沿用SQL写集的事务身份，完整原件在首次持久前绑定该身份。
            args[0] = invalidation['invalidation_id']
            args[-1] = M.raw(invalidation)
        if mutation: args = mutation(sql, args)
        result.append((sql, tuple(args)))
    return result


def fixture(data, publication=True, mutation=None):
    c, anchor, invalidation = data[:3]
    db = sqlite3.connect(':memory:', isolation_level=None)
    try:
        db.executescript((COLLECTOR/'storage.sql').read_text('utf-8'))
        domain = c['binding']['domain']
        db.execute('INSERT INTO ts_scope VALUES(1,?,?,?)',
            (domain['authority_service_id'], domain['database_instance_id'], 'reference-time-storage/0.1.0-draft.1'))
        db.execute(*L.insert('ts_binding', 'b1', 1, L.u(1), M.raw(c['binding'])))
        L.transact(db, steps(c, anchor, invalidation, 'bootstrap'))
        db.execute(*L.insert('ts_poll', 'p.c1', 'b1', 'correlation.c1', L.BODY))
        if publication: L.transact(db, steps(c, anchor, invalidation, 'publish', mutation))
        return db
    except BaseException:
        db.close()
        raise


def inputs(inherited):
    return list(dict.fromkeys(inherited + [HERE/n for n in ('gate_snapshot_source_model.py',
        'check_gate_snapshot_source.py', 'GATE_SNAPSHOT_SOURCE.md', 'reference_model.py', 'check_contracts.py', 'build_contracts.py')]
        + [COLLECTOR/n for n in ('storage.sql','check_storage.py')]
        + [M.BASE/'c04-lifecycle/continuation-binding-ipc.schema.json']))


def run():
    checks = []
    data = fixtures()
    domain = data[0]['binding']['domain']
    worker = {k: domain[k] for k in M.SHARED}
    worker['runtime_binding_ref'] = dict(id='worker.runtime', revision='1', digest=M.T.digest('worker'))
    connections = []
    def fresh(publication=True, mutation=None):
        db = fixture(data, publication, mutation); connections.append(db); return db
    def check(name, actual, expected=True):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(name=name, observed=actual, expected=expected))
    def denied(name, operation, reason=None):
        try: operation()
        except (ValueError, ValidationError) as error:
            check(name, str(error) == reason if reason else True)
        else: raise AssertionError(name+':未拒绝')
    try:
        db = fresh(); before = L.snapshot(db)
        denied('事务外拒绝', lambda: M.current(db, domain), 'time_source_transaction')
        db.execute('BEGIN IMMEDIATE')
        state = M.source(db, '2'); snapshot = M.current(db, domain)
        check('状态原件来自持久列', state['revision'] == '2' and state['status'] == 'qualified')
        check('精确下界与状态水位', snapshot['snapshot_revision'] == '2' and snapshot['minimum_time_generation'] == '1')
        check('确定性身份重复读取', M.current(db, domain) == snapshot)
        check('两运行身份可共享时钟', M.for_open(db, snapshot, domain, worker) == snapshot)
        check('不把提供者改成worker', snapshot['domain']['runtime_binding_ref'] != worker['runtime_binding_ref'])
        check('同快照重复接收', M.for_open(db, snapshot, domain, worker, snapshot) == snapshot)
        for field in domain:
            bad = copy.deepcopy(domain)
            if field == 'runtime_binding_ref': bad[field]['id'] = 'other.runtime'
            elif field == 'clock_domain_id': bad[field] = 'clock_'+'2'*64
            elif field == 'descriptor_digest': bad[field] = M.T.digest('other')
            elif field == 'clock_generation': bad[field] = '2'
            else: bad[field] = 'other'
            denied('提供者域错绑:'+field, lambda bad=bad: M.current(db, bad), 'time_provider_domain')
        for field in M.SHARED:
            bad = dict(worker, **{field:'other'})
            denied('出口域错绑:'+field, lambda bad=bad: M.for_open(db, snapshot, domain, bad), 'time_exit_clock')
        for field, value in (('snapshot_revision','3'), ('minimum_time_generation','2'), ('snapshot_id','forged')):
            bad = copy.deepcopy(snapshot); bad[field] = value; M.T.seal(bad, 'snapshot_digest')
            denied('重算摘要不洗白:'+field, lambda bad=bad: M.for_open(db, bad, domain, worker), 'time_snapshot_stale_or_forged')
        for field in ('minimum_time_generation','snapshot_revision'):
            retained = copy.deepcopy(snapshot); retained[field] = '9'; M.T.seal(retained, 'snapshot_digest')
            denied('不降低已装水位:'+field, lambda retained=retained: M.for_open(db, snapshot, domain, worker, retained), 'time_retained_floor')
        db.commit(); check('读取没有写入', L.snapshot(db) == before)
        L.transact(db, steps(*data[:3], 'invalidate'))
        db.execute('BEGIN IMMEDIATE'); latest = M.current(db, domain)
        check('失效精确推进floor', latest['snapshot_revision'] == '3' and latest['minimum_time_generation'] == '2')
        check('失效不捏造UTC资格', M.source(db,'3')['status'] == 'unavailable' and M.source(db,'3')['current_anchor_ref'] is None)
        check('不可用仍交付拒绝下界', M.for_open(db, latest, domain, worker, snapshot) == latest)
        check('旧原件仍可查', M.derive(M.source(db,'2')) == snapshot)
        denied('查原不恢复旧OPEN资格', lambda: M.for_open(db, snapshot, domain, worker), 'time_snapshot_stale_or_forged')
        db.commit()
        cold = fresh(False); cold.execute('BEGIN IMMEDIATE')
        check('collecting也只提供floor', M.current(cold,domain)['minimum_time_generation'] == '1')
        cold.rollback()
        for field, value in (('revision','9'), ('status','collecting'), ('binding',dict(data[0]['binding'],time_generation='2'))):
            def corrupt(sql,args,field=field,value=value):
                if sql.startswith('INSERT INTO ts_state '):
                    body=json.loads(args[-1]); body[field]=value
                    if field=='status': body['current_anchor_ref']=None
                    args[-1]=M.raw(M.T.seal(body,'state_digest'))
                return args
            bad=fresh(mutation=corrupt); bad.execute('BEGIN IMMEDIATE')
            denied('完整BODY与物理列冲突:'+field,lambda bad=bad:M.current(bad,domain),'time_state_columns');bad.rollback()
        for label, transform in (
            ('占位正文', lambda _: L.BODY),
            ('重复键',lambda v:b'{"revision":"2",'+v[1:]),
            ('非规范空白',lambda v:b' '+v),
            ('超容量',lambda _:b' '*65537)):
            def corrupt(sql,args,transform=transform):
                if sql.startswith('INSERT INTO ts_state '): args[-1]=transform(args[-1])
                return args
            bad=fresh(mutation=corrupt);bad.execute('BEGIN IMMEDIATE')
            denied('拒原件:'+label,lambda bad=bad:M.current(bad,domain));bad.rollback()
        for field,value in (('anchor_id','different'),('anchor_tick_ns','11'),('binding',dict(data[0]['binding'],time_generation='2'))):
            def corrupt(sql,args,field=field,value=value):
                if sql.startswith('INSERT INTO ts_anchor '):
                    body=json.loads(args[-1]);body[field]=value;args[-1]=M.raw(M.T.seal(body,'anchor_digest'))
                return args
            bad=fresh(mutation=corrupt);bad.execute('BEGIN IMMEDIATE')
            denied('Anchor完整原件错绑:'+field,lambda bad=bad:M.current(bad,domain),'time_anchor_columns');bad.rollback()
        for field,value in (('invalidation_id','different'),('next_time_generation','3'),('old_binding',dict(data[0]['binding'],time_generation='9'))):
            def corrupt(sql,args,field=field,value=value):
                if sql.startswith('INSERT INTO ts_invalidation '):
                    body=json.loads(args[-1]);body[field]=value;args[-1]=M.raw(M.T.seal(body,'invalidation_digest'))
                return args
            bad=fresh();L.transact(bad,steps(*data[:3],'invalidate',corrupt));bad.execute('BEGIN IMMEDIATE')
            denied('Invalidation完整原件错绑:'+field,lambda bad=bad:M.current(bad,domain),'time_invalidation_columns');bad.rollback()
        bad=fresh();batch=steps(*data[:3],'invalidate')
        # seal尚未形成时，即便同一连接已看到head和State，也不能读取半个写集。
        bad.execute('BEGIN IMMEDIATE')
        for sql,args in batch[:-1]:bad.execute(sql,args)
        denied('失效缺seal拒绝来源',lambda:M.current(bad,domain),'time_source_cardinality');bad.rollback()
        bad.execute('BEGIN IMMEDIATE');check('缺seal回滚保持旧来源',M.current(bad,domain)==snapshot);bad.rollback()
        huge=copy.deepcopy(state);huge['revision']='99999999999999999999';huge['binding']['time_generation']='18446744073709551616';M.T.seal(huge,'state_digest')
        big=M.derive(huge)
        check('U20与超过uint64不转浮点',big['snapshot_revision']==huge['revision'] and big['minimum_time_generation']==huge['binding']['time_generation'])
        check('外键完整',all(not d.execute('PRAGMA foreign_key_check').fetchall() for d in connections))
        return dict(approved=False, all_passed=True, check_count=len(checks), checks=checks,
            sqlite_version=sqlite3.sqlite_version, table_count=14, physical_source_validation=True,
            full_controller_integration=False, runtime_validation=False, ntp_validation=False,
            artifact_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs(data[3])})
    finally:
        for db in connections: db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    path=HERE/'gate-snapshot-source-report.json'
    if args.staged and not args.check_report:parser.error('--staged需配合--check-report')
    if args.check_report:
        def read(p):return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else p.read_bytes()
        report=json.loads(read(path));expected=inputs([Path(p) for p in C.isolated_fixture('df03-reference','None')['inputs']]);assert set(report['artifact_sha256'])=={p.relative_to(ROOT).as_posix() for p in expected}
        for p in expected:assert hashlib.sha256(read(p)).hexdigest()==report['artifact_sha256'][p.relative_to(ROOT).as_posix()],p
        assert report['all_passed'] and all(c['observed']==c['expected'] for c in report['checks'])
        print(json.dumps(dict(input_count=len(expected),binding_valid=True,rerun=False)))
    else:
        report=run()
        if args.report:path.write_bytes((json.dumps(report,ensure_ascii=False,separators=(',',':'))+'\n').encode())
        print(json.dumps({k:report[k] for k in ('check_count','all_passed','physical_source_validation','full_controller_integration','runtime_validation')}))
