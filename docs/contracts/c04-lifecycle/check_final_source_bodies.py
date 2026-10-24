"""具名来源正文的构造、持久绑定和对抗实验；全部外部身份仍为合成。"""
import argparse,copy,hashlib,json,re
from unittest.mock import patch
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import check_final_resource_source as T
import check_continuation_storage as CS
import final_source_bodies_model as M
G=M.G;HERE=G.HERE;ROOT=T.ROOT;O=T.O;V=T.V;clone=copy.deepcopy

def identity(s):
    value=V.fixture(kind=s['kind'],origin=s['origin'])[0]['identity']
    value.update(command_ref=V.ref(s['command_id']),requester=dict(kind=s['principal_kind'],**{k:s[k] for k in ('issuer_id','issuer_epoch','principal_id')}))
    if s['kind']=='ordinary':value['attempt_ref']=V.ref(s['attempt_id'])
    else:value.update(cancellation_ref=V.ref(s['cancellation_id']),execution_ref=V.ref(s['execution_id']))
    return value

def materializer(corrupt=None):
    """只规范新合成fixture的初始写入，不用于修改既有库或修正负例。"""
    context={'observations':[]};raw_tx=O.U.tx;raw_execute=O.U.execute
    def owner_fields(db,row):
        value=dict(row);o=M.one(db,'SELECT * FROM ow_ownership WHERE ownership_id=?',(value['owner_ref'],))
        value.update(owner_revision=o['revision'],owner_digest=o['ownership_digest']);return value
    def decorate(db,table,value):
        row=dict(value)
        if table=='ct_state':
            body=M.control_body(db,row);row.update(record_body=M.raw(body),record_digest=body['record_digest'])
        elif table=='ow_source':
            body=M.receipt_body(db,row,identity(row));row.update(receipt_body=M.raw(body),source_digest=body['receipt_digest'])
        elif table=='ow_ownership':
            body=M.ownership_body(db,row);row.update(ownership_body=M.raw(body),ownership_digest=body['ownership_digest'])
        elif table=='go_snapshot':
            observations=[owner_fields(db,x) for x in context['observations'] if x['snapshot_id']==row['snapshot_id']]
            body=M.snapshot_body(db,row,observations);row.update(evidence_body=M.raw(body),evidence_digest=body['evidence_digest'])
        elif table=='go_hold':row=owner_fields(db,row)
        if corrupt:row=corrupt(table,row)
        return row
    def execute(db,step):table,row=step;raw_execute(db,(table,decorate(db,table,row)))
    def transaction(db,steps,fault=None):
        context['observations']=[dict(v) for table,v in steps if table=='go_hold'];return raw_tx(db,steps,fault)
    def sql_parts(write):
        sql,args=write;match=re.fullmatch(r'INSERT INTO (\w+)\s*\(([^)]+)\) VALUES\s*\([?,]+\)',sql)
        if not match:return None
        return match[1],dict(zip(match[2].split(','),args))
    def sql_transaction(db,steps,fail_after=None,fail=None):
        if fail is not None:fail_after=fail
        parsed=[sql_parts(x) for x in steps];context['observations']=[v for item in parsed if item for table,v in [item] if table=='go_hold']
        db.execute('BEGIN IMMEDIATE')
        try:
            for n,write in enumerate(steps):
                item=parsed[n]
                if item:write=T.T.E.I(item[0],**decorate(db,*item))
                db.execute(*write)
                if fail_after==n:raise RuntimeError('injected')
            db.commit()
        except BaseException:
            if db.in_transaction:db.rollback()
            raise
    return execute,transaction,sql_transaction

def fixture(corrupt=None):
    execute,transaction,_=materializer(corrupt)
    with patch.object(O.U,'execute',side_effect=execute),patch.object(O.U,'tx',side_effect=transaction):return T.fixture()

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def reject(name,fn,reason=None):
        try:fn()
        except (ValueError,RuntimeError,ValidationError) as error:
            if reason:assert reason in str(error),(name,str(error))
            check(name)
        else:raise AssertionError('未拒绝:'+name)
    try:
        check('Schema生成字节一致',(HERE/'final-source-bodies.schema.json').read_bytes()==G.raw(G.build()))
        Draft202012Validator.check_schema(M.SCHEMA);check('Schema有效且根拒绝直接实例',not Draft202012Validator(M.SCHEMA).is_valid({}))
        db,v,o=fixture();dbs.append(db)
        check('非空正文夹具实际为182表',len(O.U.snapshot(db))==182)
        actual=T.preview(db,lambda:M.read(db,v,'after','later'));o.update(clone(actual));V.refresh(v,o)
        check('五角色完整正文和表列通过',T.preview(db,lambda:M.verify(db,v,o))=='stored_bodies_and_relationships_valid_requires_current_providers')
        check('资源安全Ref取实际hazard切点',actual['resource_before']['body']['resource_safety_ref']==actual['resource_after']['body']['resource_safety_ref']==actual['resource_safety']['source_ref'])
        before=O.U.snapshot(db);T.preview(db,lambda:M.verify(db,v,o));check('严格读取不改数据库',before==O.U.snapshot(db))
        # 使用同一套真实关系，但旧占位正文不得自动升级为新格式。
        old,ov,oo=T.fixture();dbs.append(old)
        T.preview(old,lambda:T.M.read(old,ov,'after','later',V.ref('safety')))
        reject('旧合成正文仅列关系通过仍拒绝采用',lambda:T.preview(old,lambda:M.read(old,ov,'after','later')))
        control=T.preview(db,lambda:M.control(db,'base'));owner=T.preview(db,lambda:M.ownership(db,'owner'));snapshot=T.preview(db,lambda:M.snapshot(db,'later'))
        source=M.one(db,'SELECT * FROM ow_source WHERE source_id=?',('source',));receipt=json.loads(source['receipt_body'])
        cut=T.preview(db,lambda:M.safety(db,'device',snapshot['resource_safety_ref']['revision']))
        for name,body,key in [('ControlStorageRecord',control,'record_digest'),('Ownership',owner,'ownership_digest'),('OwnershipReceipt',receipt,'receipt_digest'),('ResourceSnapshotRecord',snapshot,'evidence_digest'),('ResourceSafetyCut',cut,'cut_digest')]:
            check('具名Schema与摘要正例:'+name,M.decode(name,M.raw(body),key,body[key])==body)
            bad=dict(body,unexpected=True);bad=M.sealed(bad,key)
            reject('封闭字段:'+name,lambda name=name,bad=bad,key=key:M.decode(name,M.raw(bad),key,bad[key]))
            reject('列摘要不符:'+name,lambda name=name,body=body,key=key:M.decode(name,M.raw(body),key,M.F.digest('other')),'source_body_digest')
            bad=dict(body,**{key:M.F.digest('self_asserted')})
            reject('正文与列同值仍须自摘要正确:'+name,lambda name=name,bad=bad,key=key:M.decode(name,M.raw(bad),key,bad[key]),'source_body_digest')
            duplicate=b'{"format_version":"wrong",'+M.raw(body)[1:]
            reject('重复JSON键:'+name,lambda name=name,duplicate=duplicate,key=key,body=body:M.decode(name,duplicate,key,body[key]),'source_duplicate_key')
            reject('持久正文不是规范JSON:'+name,lambda name=name,body=body,key=key:M.decode(name,b' '+M.raw(body),key,body[key]),'source_body_not_canonical')
        reject('非有限JSON数值先拒绝',lambda:M.decode('ControlStorageRecord',b'{"x":NaN}','record_digest',control['record_digest']),'source_nonfinite')
        big=M.sealed(dict(control,observed_tick_ns='9007199254740993'),'record_digest')
        check('超过2的53次方仍保持十进制字符串',M.decode('ControlStorageRecord',M.raw(big),'record_digest',big['record_digest'])['observed_tick_ns']=='9007199254740993')
        for value in ('01',9007199254740993):
            bad=dict(control,observed_tick_ns=value)
            reject('计数拒绝非规范类型:'+str(value),lambda bad=bad:M.validate('ControlStorageRecord',bad))
        wrong=clone(v);wrong['identity']['source_ref']['digest']=M.F.digest('other');wrong=M.F.seal(wrong)
        reject('完整ExecutionIdentity摘要不能偷换',lambda:T.preview(db,lambda:M.read(db,wrong,'after','later')),'source_full_identity')
        for role in actual:
            bad=clone(o);bad[role]['source_ref']=dict(bad[role]['source_ref'],digest=M.F.digest('fake'));vv=clone(v);V.refresh(vv,bad)
            reject('最终投影仍须绑定真实正文:'+role,lambda vv=vv,bad=bad:T.preview(db,lambda:M.verify(db,vv,bad)),'source_projection_'+role)
        # 新写入保持SQL列不变，仅伪造正文并重算列摘要；SQL可以接受，严格解析必须拒绝。
        def change_snapshot(table,row):
            if table=='go_snapshot':
                value=json.loads(row['evidence_body']);value['resource_id']='forged';value=M.sealed(value,'evidence_digest')
                return dict(row,evidence_body=M.raw(value),evidence_digest=value['evidence_digest'])
            return row
        corrupt,cv,co=fixture(change_snapshot);dbs.append(corrupt)
        reject('同摘要错误正文不能冒充资源列',lambda:T.preview(corrupt,lambda:M.read(corrupt,cv,'after','later')),'source_snapshot_columns')
        # provider真假不是由正确摘要推出：当前fixture确为合成，报告明确保留此限制。
        check('来源回执明示合成提供者',receipt['provider_id']=='fixture.provider')
        # 对实际242表初始开放和普通编码链仅规范存储正文，真实SQL守卫保持运行。
        execute,transaction,sql_transaction=materializer()
        with patch.object(O.U,'execute',side_effect=execute),patch.object(O.U,'tx',side_effect=transaction),patch.object(T.T.E.O,'execute',side_effect=sql_transaction),patch.object(CS.C,'execute',side_effect=sql_transaction):
            full,connections,cmd,auth,pid,provider,response=T.T.fixture()
        dbs.extend(connections);T.T.E.O.execute(full,T.preview(full,lambda:T.T.E.receive(full,pid,response,provider)))
        seal,originals,read_cut=T.preview(full,lambda:T.T.candidate(full,pid,provider))
        c=M.one(full,'SELECT * FROM go_authority WHERE device_id=?',(seal['binding']['device_id'],));s=M.one(full,'SELECT * FROM go_valid_snapshot WHERE device_id=?',(seal['binding']['device_id'],))
        T.preview(full,lambda:M.control(full,c['change_id']));T.preview(full,lambda:M.snapshot(full,s['snapshot_id']))
        check('242表编码链实际保存完整控制和资源正文',len(O.U.snapshot(full))==242 and len(T.preview(full,lambda:T.T.M.planned(full,seal,originals,read_cut,pid,provider)))==19)
        check('四个最终签发阻断保持',full.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        for connection in dbs:assert not connection.in_transaction and not connection.execute('PRAGMA foreign_key_check').fetchone()
        check('全部连接外键与事务完整')
        check('全部Controller许可仍为零',all(c.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==0 for c in dbs if c.execute("SELECT 1 FROM sqlite_schema WHERE name='ci_issue'").fetchone()))
        return checks
    finally:
        for connection in dbs:connection.close()

def inputs():return list(dict.fromkeys(T.inputs()+G.SOURCES+[HERE/n for n in ('final_source_bodies_model.py','check_final_source_bodies.py','final-source-bodies.schema.json','FINAL_SOURCE_BODIES.md')] ))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');args=p.parse_args();target=HERE/'final-source-bodies-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if args.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),storage_body_integrity_verified=True,provider_authenticity_verified=False,
            typed_control_and_empty_resources_in_242_tables=True,typed_nonempty_ownership_fixture_tables=182,full_242_table_hold_transaction_executed=False,sql_positive_issue_path_executed=False,
            production_clearance=False,runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if args.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
