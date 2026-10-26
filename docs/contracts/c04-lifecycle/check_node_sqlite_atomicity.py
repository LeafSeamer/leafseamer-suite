"""固定Node候选驱动的漏写、回执丢失与真实双进程竞争验收。"""
import argparse,hashlib,json,platform,sqlite3
from pathlib import Path
import check_node_sqlite_durability as D
T=D.T;HERE=D.HERE;ROOT=D.ROOT
def inputs():return D.inputs()+[HERE/'check_node_sqlite_atomicity.py',HERE/'NODE_SQLITE_ATOMICITY.md',ROOT/'docs/contracts/toolchain/metadata-observation.json']
def run(runtime):
    assert platform.system()=='Windows';node,package,identity=D.artifacts(runtime);checks=[];observations=[];bridges=[];connections=[]
    def check(name,condition):checks.append(dict(name=name,passed=bool(condition)))
    try:
        seed,others,_=T.T.fixture();connections.extend(others);connections.append(seed);before=D.state(seed);statements=[]
        class Record(T.Wrapped):
            def execute(self,sql,args=()):
                result=self.db.execute(sql,args)
                if sql.startswith('INSERT INTO '):statements.append(dict(sql=sql,parameters=[D.encoded(x) for x in args]))
                return result
        copy=sqlite3.connect(':memory:',isolation_level=None);connections.append(copy);seed.backup(copy);copy.execute('PRAGMA foreign_keys=ON');copy.execute('PRAGMA recursive_triggers=ON');_,writes=T.capture(Record(copy));after=D.state(copy)
        assert len(statements)==len(writes)==8
        a=D.Bridge(node,package);b=D.Bridge(node,package);bridges.extend([a,b]);assert a.request(dict(action='ping'))==b.request(dict(action='ping'))==dict(ok=True)
        with D.temporary(bridges,connections) as directory:
            def fresh(name,mode):
                folder=Path(directory)/name;folder.mkdir();(folder/'.leafseamer-offline-test').write_text('node-sqlite-retired-cancel/1');path=folder/'case.sqlite';db=sqlite3.connect(path);seed.backup(db);db.close()
                setup=a.request(dict(action='setup',path=str(path),mode=mode));assert setup['ok'];return path,setup['facts']
            def inspect(name,path,expected,bridge=b):
                value=bridge.request(dict(action='inspect',path=str(path)))
                check(name+'检查连接成功',value['ok'])
                if value['ok']:
                    check(name+'完整性与外键',value['integrity']==['ok'] and not value['foreign_keys'])
                    check(name+'完整表值',D.normalized(value['state'])==D.normalized(expected))
                return value
            def transaction(bridge,path,**options):return bridge.request(dict(action='transaction',path=str(path),statements=statements,**options))
            for mode in ('DELETE','WAL'):
                for kind in ('fail_after','omit'):
                    for index in range(8):
                        name=f'{mode}:{kind}:{index+1}';path,facts=fresh(name.replace(':','_'),mode);result=transaction(a,path,**{kind:index+1 if kind=='fail_after' else index})
                        code=result.get('code','');rejected=not result['ok'] and (code=='test_precommit_fault' if kind=='fail_after' else code.startswith('SQLITE_CONSTRAINT'))
                        check(name+'预期拒绝',rejected);check(name+'无未清事务',result.get('rollback_completed',not result.get('transaction_open_on_error',False)) and not result.get('close_failed',False))
                        inspect(name,path,before);observations.append(dict(case=name,result=result))
                path,facts=fresh(mode+'_lost_commit',mode);result=transaction(a,path,lose_commit_observation=True)
                check(mode+'提交回执丢失仍无伪回滚',not result['ok'] and result['code']=='test_commit_observation_lost' and result['transaction_open_on_error'] is False and 'rollback_completed' not in result)
                inspect(mode+'提交已保存',path,after);duplicate=transaction(a,path);check(mode+'盲重放被拒绝',not duplicate['ok'] and duplicate['code'].startswith('SQLITE_CONSTRAINT'));inspect(mode+'重放不改原件',path,after)
                observations.append(dict(case=mode+':lost_commit',result=result,duplicate=duplicate))
                path,facts=fresh(mode+'_contention',mode);held=a.request(dict(action='write',path=str(path),phase='after_member',statements=statements));assert held==dict(ok=True,barrier='after_member',in_transaction=True)
                competing=transaction(b,path);check(mode+'实际第二进程writer被排他',not competing['ok'] and competing['code']=='SQLITE_BUSY');inspect(mode+'其他进程看不见未提交',path,before)
                assert a.request(dict(action='close'))==dict(ok=True);inspect(mode+'关闭未提交连接全部回滚',path,before)
                finished=transaction(b,path);check(mode+'重新开始新事务可完整提交',finished['ok']);inspect(mode+'竞争结束完整原件',path,after,bridge=a)
                observations.append(dict(case=mode+':contention',result=competing,facts=facts))
            path,facts=fresh('WAL_stale_snapshot','WAL');held=b.request(dict(action='hold_snapshot',path=str(path)));assert held['ok'] and held['in_transaction'] and D.normalized(held['state'])==D.normalized(before)
            assert transaction(a,path)['ok'];upgraded=b.request(dict(action='upgrade_snapshot',statement=statements[0]));check('WAL旧读事务不可升级writer',not upgraded['ok'] and upgraded['code']=='SQLITE_BUSY_SNAPSHOT');check('WAL升级失败明确回滚',upgraded.get('rollback_completed') is True)
            inspect('WAL新事务读取新原件',path,after);observations.append(dict(case='WAL:stale_snapshot',result=upgraded,facts=facts))
        return dict(all_passed=all(c['passed'] for c in checks),approved=False,cases_passed=sum(c['passed'] for c in checks),cases_failed=sum(not c['passed'] for c in checks),checks=checks,observations=observations,artifacts=identity,windows_version=platform.version(),workload_sha256=hashlib.sha256(T.R.raw(statements)).hexdigest(),snapshot_table_count=len(before),two_storage_processes_verified=True,storage_worker_thread_used=True,actual_service_supervision_verified=False,complete_node_writer_verified=False,commit_io_error_injected=False,linux_verified=False,device_tests_executed=0)
    finally:
        for bridge in bridges:bridge.close()
        for db in connections:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path);p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'node-sqlite-atomicity-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:
        r=json.loads(target.read_bytes());assert r['inputs']==hashes;print(json.dumps(dict(bindings_match=True,report_all_passed=r['all_passed'],matched_bindings=len(hashes))))
    else:
        assert a.runtime;r=run(a.runtime.resolve());r['inputs']=hashes
        if a.report:target.write_bytes(T.R.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs','observations')}))
        if not r['all_passed']:raise SystemExit(1)
