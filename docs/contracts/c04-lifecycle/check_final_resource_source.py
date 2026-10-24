"""资源与归属来源的同库关系实验；未解除最终许可阻断。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import check_final_encoding_source as T
import final_resource_source_model as M
import check_ownership_storage as O
V=T.V;F=M.F;HERE=T.HERE;ROOT=T.ROOT;clone=copy.deepcopy
CLOCK='clock_'+'1'*64;DESCRIPTOR=F.digest('synthetic_clock')

def execute(db,steps):
    raw_execute=O.U.execute
    def normalized(connection,step):
        table,value=step;value=dict(value)
        for field in ('clock_domain','clock_domain_id'):
            if field in value:value[field]=CLOCK
        for field in ('descriptor','descriptor_digest'):
            if field in value:value[field]=DESCRIPTOR
        raw_execute(connection,(table,value))
    with patch.object(O.U,'execute',side_effect=normalized):O.U.tx(db,steps)

def fixture():
    raw_execute=O.U.execute
    def normalized(connection,step):
        table,value=step;value=dict(value)
        for field in ('clock_domain','clock_domain_id'):
            if field in value:value[field]=CLOCK
        for field in ('descriptor','descriptor_digest'):
            if field in value:value[field]=DESCRIPTOR
        raw_execute(connection,(table,value))
    with patch.object(O.U,'execute',side_effect=normalized):db=O.fresh(holder='alice')
    execute(db,O.S.snapshot(db,'before',20,'base'))
    writes=O.acquire(db);writes=O.U.mutate(writes,'ow_source',sampled_tick=O.u(21),acquired_tick=O.u(21),expires_tick=O.u(30))
    writes=O.U.mutate(writes,'ow_commit',committed_tick=O.u(21));execute(db,writes)
    execute(db,O.snapshot(db,'after',22));execute(db,O.snapshot(db,'later',23))
    v,originals,cut=V.fixture(kind='cancel')
    ex=M.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',('exit.0',));binding=dict(scope=M.E.A.scope(db),writer_exit_id=ex['exit_id'],**{k:ex[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest')})
    own=M.one(db,'SELECT * FROM ow_record WHERE hold_id=?',('hc',));identity=clone(v['identity'])
    identity.update(command_ref=V.ref(own['command_id']),cancellation_ref=V.ref(own['cancellation_id']),execution_ref=V.ref(own['execution_id']),requester=dict(kind=own['principal_kind'],**{k:own[k] for k in ('issuer_id','issuer_epoch','principal_id')}))
    v.update(binding=binding,identity=identity,hold_ref=M.ref('hc',1,own['hold_digest']),selected_tick_ns='31',sealed_tick_ns='32')
    for role in originals:
        originals[role]['scope']=clone(binding['scope']);originals[role]['body']['binding']=clone(binding);originals[role]['body']['identity']=clone(identity)
    return db,F.seal(v),originals

def preview(db,fn):return T.T.preview(db,fn)

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');dbs.append(c);return c
    def reject(name,db,fn,reason=None):
        before=O.U.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as error:
            if reason:assert reason in str(error),(name,str(error))
            check(name,before==O.U.snapshot(db) and not db.in_transaction)
        else:raise AssertionError('未拒绝:'+name)
    try:
        db,v,o=fixture();dbs.append(db);safety=V.ref('source.resource_safety')
        check('非空资源夹具为完整182表',len(O.U.snapshot(db))==182)
        actual=preview(db,lambda:M.read(db,v,'after','later',safety));check('四角色从持久表读取',set(actual)=={'control','ownership','resource_before','resource_after'})
        o.update(clone(actual));V.refresh(v,o)
        check('四角色封存引用逐项对账',preview(db,lambda:M.verify(db,v,o))=='storage_relationships_valid_requires_provider_verification')
        for role in actual:
            bad=clone(o);bad[role]['source_ref']=dict(bad[role]['source_ref'],digest=F.digest('substituted'));vv=clone(v);V.refresh(vv,bad)
            reject('重算摘要也不能替换原件:'+role,db,lambda vv=vv,bad=bad:preview(db,lambda:M.verify(db,vv,bad)),'resource_projection_'+role)
        bad=clone(v);bad['inputs']['control']['id']='other';bad=F.seal(bad)
        reject('Seal输入Ref不能绕开逐项核验',db,lambda:preview(db,lambda:M.verify(db,bad,o)),'resource_projection_control')
        bad=clone(v);bad['seal_digest']=F.digest('wrong')
        reject('Seal自身摘要先校验',db,lambda:preview(db,lambda:M.read(db,bad,'after','later',safety)),'resource_seal_digest')
        check('采样回执过期不抹去已封存归属',int(M.one(db,'SELECT expires_tick FROM ow_source')['expires_tick'])<32 and actual['ownership']['source_ref']['id']=='owner')
        check('保护占用集合真实存在',len(actual['resource_after']['body']['holds'])==1 and actual['resource_after']['body']['holds'][0]['hold_ref']==v['hold_ref'])
        added=preview(db,lambda:M.pair(db,'before','later','device','hc','create',20,32))
        check('新增占用前后集合显式分离',added[1]==[] and len(added[3])==1)
        original=O.U.snapshot(db);preview(db,lambda:M.read(db,v,'after','later',safety));check('解析不改变持久状态',original==O.U.snapshot(db))
        reject('事务外不解析资源',db,lambda:M.inventory(db,'later','device',32),'resource_transaction_required')
        reject('旧快照不能作为当前后态',db,lambda:preview(db,lambda:M.pair(db,'before','after','device','hc','create',20,32)),'resource_snapshot_not_current')
        reject('新hold不能声明复用',db,lambda:preview(db,lambda:M.pair(db,'before','later','device','hc','reuse',20,32)),'resource_reuse_set')
        reject('既存hold不能声明新增',db,lambda:preview(db,lambda:M.pair(db,'after','later','device','hc','create',31,32)),'resource_create_set')
        reject('不存在的目标hold不能复用',db,lambda:preview(db,lambda:M.pair(db,'after','later','device','missing','reuse',31,32)),'resource_reuse_set')
        for selected,now in ((19,32),(33,32),(31,90)):
            reject('资源时间边界'+str((selected,now)),db,lambda selected=selected,now=now:preview(db,lambda:M.pair(db,'before','later','device','hc','create',selected,now)))
        for field in ('controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','descriptor_digest'):
            binding=dict(v['binding'],**{field:'changed'})
            reject('控制绑定错出口:'+field,db,lambda binding=binding:preview(db,lambda:M.control(db,binding,v['identity'],'transaction')),'resource_exit')
        binding=clone(v['binding']);binding['scope']['database_instance_id']='other'
        reject('资源跨数据库拒绝',db,lambda:preview(db,lambda:M.control(db,binding,v['identity'],'transaction')),'resource_scope')
        for field in ('issuer_id','issuer_epoch','principal_id'):
            identity=clone(v['identity']);identity['requester'][field]='other'
            reject('同名不同完整身份:'+field,db,lambda identity=identity:preview(db,lambda:M.control(db,v['binding'],identity,'transaction')),'resource_control_principal')
        for name,edit in [('错父命令',lambda value:value['identity']['command_ref'].update(id='other')),('错取消执行',lambda value:value['identity']['execution_ref'].update(id='other')),('错占用摘要',lambda value:value['hold_ref'].update(digest=F.digest('other')))]:
            bad=clone(v);edit(bad);bad=F.seal(bad)
            reject(name,db,lambda bad=bad:preview(db,lambda:M.read(db,bad,'after','later',safety)))
        # SQL守卫拒绝缺旧风险、错归属；未停用或重建任何守卫。
        reject('新快照遗漏旧风险',db,lambda:execute(db,O.S.snapshot(db,'missing',24,'base')),'open_hold_set')
        for field,value in [('owner_ref','missing'),('owner_digest',F.digest('wrong')),('authority_state_id','other')]:
            reject('快照归属不能重标:'+field,db,lambda field=field,value=value:execute(db,O.U.mutate(O.snapshot(db,'bad',24),'go_hold',**{field:value})))
        c=fork(db);execute(c,O.snapshot(c,'unknown',24,classification='unknown'))
        reject('既存风险不能在复用时改分类',c,lambda:preview(c,lambda:M.pair(c,'later','unknown','device','hc','reuse',31,32)),'resource_reuse_set')
        c=fork(db);execute(c,[O.revoke()]);reject('来源撤回后旧归属不再可采用',c,lambda:preview(c,lambda:M.read(c,v,'after','later',safety)))
        check('来源撤回保留不可变历史',c.execute('SELECT count(*) FROM ow_record').fetchone()[0]==1 and c.execute('SELECT count(*) FROM cr_risk_hold').fetchone()[0]==1)
        reject('风险代次推进使前后态失效',c,lambda:preview(c,lambda:M.pair(c,'after','later','device','hc','reuse',31,32)),'resource_safety_changed')
        c=fork(db);execute(c,O.U.offer(c));execute(c,O.takeover(c))
        reject('接管pending不采用旧控制',c,lambda:preview(c,lambda:M.control(c,v['binding'],v['identity'],'transaction')),'resource_pending_control')
        # 将当前完整242表编码正例的真实control加入其封存关联向量。
        full,connections,cmd,auth,pid,provider,response=T.fixture();dbs.extend(connections)
        check('普通编码夹具为完整242表',len(O.U.snapshot(full))==242)
        T.E.O.execute(full,preview(full,lambda:T.E.receive(full,pid,response,provider)))
        seal,originals,cut=preview(full,lambda:T.candidate(full,pid,provider))
        current=preview(full,lambda:M.control(full,seal['binding'],seal['identity'],seal['transaction_id']));originals['control']=current
        for role in ('ownership','permit_authority','gate_access'):
            originals[role]['body'].update(control_authority_ref=current['source_ref'],control_epoch=current['body']['control_epoch'],effective_version=current['body']['effective_version'])
        V.refresh(seal,originals)
        check('242表编码链接通当前控制来源',len(preview(full,lambda:T.M.planned(full,seal,originals,cut,pid,provider)))==19)
        check('原临时发送守卫仍全部存在',full.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for connection in dbs:assert not connection.in_transaction and not connection.execute('PRAGMA foreign_key_check').fetchone()
        check('全部外键及事务完整')
        check('本轮未产生最终许可',all(connection.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==0 for connection in dbs if connection.execute("SELECT 1 FROM sqlite_schema WHERE name='ci_issue'").fetchone()))
        return checks
    finally:
        for connection in dbs:connection.close()

def inputs():return list(dict.fromkeys(T.inputs()+O.INPUTS+[HERE/n for n in ('final_resource_source_model.py','check_final_resource_source.py','FINAL_RESOURCE_SOURCE.md')] ))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');args=parser.parse_args();target=HERE/'final-resource-source-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if args.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),control_in_242_table_encoding_path=True,nonempty_resource_fixture_tables=182,
            full_242_table_hold_transaction_executed=False,sql_positive_issue_path_executed=False,provider_authenticity_verified=False,production_clearance=False,
            runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if args.report:target.write_bytes(T.E.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
