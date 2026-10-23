"""占用归属与发送主体子契约检查；原SQL只用于缺口复现，无设备或业务入口。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
import build_hold_ownership as G
import check_open_lifecycle as L
import check_open_storage as S
import hold_ownership_model as M
O=L.O;HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(L.INPUTS+S.INPUTS+[HERE/n for n in ('FINAL_ADMISSION.md','build_hold_ownership.py',
 'hold_ownership_model.py','hold-ownership.schema.json','check_hold_ownership.py')]))
OWNER_FIELDS=('scope','device_id','hold_ref','identity','control_authority_ref','control_epoch','effective_version',
 'clock_domain_id','descriptor_digest','acquired_tick_ns')
GUARD_FIELDS=('permit_id','issued_revision','identity','binding','hold_ref','ownership_ref','control_authority_ref',
 'control_epoch','effective_version','authorization_ref','packet_ref','ordinal','selected_tick_ns','expires_tick_ns')
def clone(value):return json.loads(json.dumps(value))
def fixture(kind='ordinary',origin='manual'):
    p,d,e,t,c=L.fixture();c,error=L.M.publish(t,e,d,p,c,50);assert error is None
    principal=dict(kind='human' if origin=='manual' else 'service',issuer_id='issuer',issuer_epoch='epoch',principal_id='bob' if origin=='manual' else 'seamer')
    if origin=='automation':c['control_projection'].update(mode='automatic',holder=None)
    identity=dict(kind=kind,command_ref=L.ref('command'),attempt_ref=L.ref('attempt') if kind=='ordinary' else None,
      cancellation_ref=L.ref('cancel') if kind=='cancel' else None,execution_ref=L.ref('execution') if kind=='cancel' else None,
      requester=principal,origin=origin,source_ref=L.ref('source.'+kind))
    owner=O.seal(dict(format_version='hold-ownership/0.1.0-draft.1',ownership_id='ownership',revision='1',
      scope=c['binding']['scope'],device_id='device',hold_ref=L.ref('hold'),identity=identity,
      control_authority_ref=c['control_projection']['authority_ref'],control_epoch='control.epoch',effective_version='2',
      clock_domain_id=c['binding']['clock_domain_id'],descriptor_digest=c['binding']['descriptor_digest'],acquired_tick_ns='50',
      source_receipt_ref=L.ref('owner.provider')),'ownership_digest')
    permit=O.seal(dict(format_version='permit-authority/0.1.0-draft.1',permit_id='permit',issued_revision='1',identity=identity,
      binding=c['binding'],hold_ref=owner['hold_ref'],ownership_ref=O.reference(owner,'ownership_id','ownership_digest'),
      control_authority_ref=owner['control_authority_ref'],control_epoch='control.epoch',effective_version='2',
      authorization_ref=c['eligibility_refs']['authorization'],guard_ref=L.ref('guard'),packet_ref=L.ref('packet'),ordinal='0',
      selected_tick_ns='51',expires_tick_ns='70'),'authority_digest')
    observation=dict(hold_ref=owner['hold_ref'],owner_ref=permit['ownership_ref'],control_authority_ref=owner['control_authority_ref'],state='active')
    c.update(executions={identity['source_ref']['id']:identity},ownerships={'hold':owner},risk_hold_ids=['hold'],
      ownership_receipts={'owner.provider':dict(ref=owner['source_receipt_ref'],content={k:owner[k] for k in OWNER_FIELDS})},
      authorization_ref=permit['authorization_ref'],guard_receipts={'guard':dict(ref=permit['guard_ref'],content={k:permit[k] for k in GUARD_FIELDS})},
      send_window_end='70',parent_requester=dict(kind='human',issuer_id='issuer',issuer_epoch='epoch',principal_id='alice'))
    return clone([owner,permit,observation,c,p,t])
def run():
    assert (HERE/'hold-ownership.schema.json').read_bytes()==G.encoded(),'生成漂移'
    schemas=[G.build(),L.G.build(),L.P.G.build(),json.loads(L.P.G.IPC.read_bytes())]
    for schema in schemas:Draft202012Validator.check_schema(schema)
    registry=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in schemas])
    def valid(name,v):return Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=registry).is_valid(v)
    checks=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,observed=copy.deepcopy(actual),expected=copy.deepcopy(expected)))
    def evaluate(values,now=52):
        owner,permit,observation,c,p,t=values
        if not valid('Ownership',owner) or not valid('PermitAuthority',permit):return 'schema'
        return M.permit_error(permit,c,now)
    def case(name,mutate,expected,kind='ordinary',origin='manual',now=52):
        values=fixture(kind,origin);mutate(*values);check(name,evaluate(values,now),expected)
    def seal_permit(permit):O.seal(permit,'authority_digest')
    def store_owner(owner,c):O.seal(owner,'ownership_digest');c['ownerships']['hold']=clone(owner)
    def rebind_owner(owner,permit,c):
        store_owner(owner,c);c['ownership_receipts']['owner.provider']['content']={k:clone(owner[k]) for k in OWNER_FIELDS}
        permit['ownership_ref']=O.reference(owner,'ownership_id','ownership_digest');seal_permit(permit)
    def rebind_guard(permit,c):
        seal_permit(permit);c['guard_receipts']['guard']['content']={k:clone(permit[k]) for k in GUARD_FIELDS}
    for kind in ('ordinary','cancel'):
        for origin in ('manual','automation'):
            values=fixture(kind,origin);owner,permit,observation,c,_,_=values
            for name,v in [('Ownership',owner),('PermitAuthority',permit),('ExecutionIdentity',owner['identity'])]:
                check(kind+origin+'结构:'+name,valid(name,v),True)
            check(kind+origin+'主体关联',evaluate(values),None)
            check(kind+origin+'完整资源归属',M.resources_error([observation],c),None)
    check('根拒直接实例',Draft202012Validator(schemas[0],registry=registry).is_valid(fixture()[0]),False)
    for name,index in (('Ownership',0),('PermitAuthority',1)):
        baseline=fixture()[index]
        for field in baseline:
            value=clone(baseline);del value[field];check(name+'缺字段:'+field,valid(name,value),False)
        value=clone(baseline);value['extra']='injected';check(name+'拒额外字段',valid(name,value),False)
    for value in ('01','-1','1\n',1,str(10**20)):
        case('计数词法:'+repr(value),lambda o,v,s,c,p,t,x=value:v.update(issued_revision=x),'schema')
    for kind in ('ordinary','cancel'):
        for field in ('attempt_ref','cancellation_ref','execution_ref'):
            baseline=fixture(kind)[1]['identity'][field]
            case('执行分支互斥:'+kind+field,lambda o,v,s,c,p,t,f=field,b=baseline:v['identity'].update({f:L.ref('wrong') if b is None else None}),'schema',kind)
        case('主体类型:'+kind,lambda o,v,s,c,p,t:v['identity']['requester'].update(kind='service'),'schema',kind)
    case('permit摘要篡改',lambda o,v,s,c,p,t:v.update(permit_id='other'),'permit_digest')
    for field in fixture()[1]['binding']:
        def change(o,v,s,c,p,t,f=field):
            v['binding'][f]=dict(authority_service_id='other',database_instance_id='database') if f=='scope' else (
              'clock_'+'2'*64 if f=='clock_domain_id' else O.digest('other') if f=='descriptor_digest' else 'other')
            seal_permit(v)
        case('重算摘要不消除出口错配:'+field,change,'permit_binding')
    for kind in ('ordinary','cancel'):
        for field in ('issuer_id','issuer_epoch','principal_id'):
            def change(o,v,s,c,p,t,f=field):v['identity']['requester'][f]='other';seal_permit(v)
            case('不借父身份或同名主体:'+kind+field,change,'execution_source',kind)
        for field in ('command_ref','source_ref'):
            def change(o,v,s,c,p,t,f=field):v['identity'][f]=L.ref('other');seal_permit(v)
            case('原件引用:'+kind+field,change,'execution_source',kind)
    case('原owner不可仅重算摘要',lambda o,v,s,c,p,t:(o.update(effective_version='3'),O.seal(o,'ownership_digest'),c['ownerships'].update(hold=o)),
      'ownership_receipt')
    for field in ('scope','device_id','hold_ref','identity','control_authority_ref','control_epoch','effective_version','clock_domain_id','descriptor_digest','acquired_tick_ns'):
        def change(o,v,s,c,p,t,f=field):
            receipt=c['ownership_receipts']['owner.provider']['content'];receipt[f]=None
        case('独立来源回执逐字段绑定:'+field,change,'ownership_receipt')
    for field in ('control_authority_ref','control_epoch','effective_version'):
        def change(o,v,s,c,p,t,f=field):
            o[f]=L.ref('old.authority') if f=='control_authority_ref' else 'old.epoch' if f=='control_epoch' else '1'
            rebind_owner(o,v,c)
        case('旧控制归属不能迁到新holder:'+field,change,'ownership_control')
    case('接管pending立即拒绝',lambda o,v,s,c,p,t:c['control_projection'].update(pending_operation_id='takeover'),'pending_control')
    for field in ('issuer_id','issuer_epoch','principal_id'):
        case('当前holder完整身份:'+field,lambda o,v,s,c,p,t,f=field:c['control_projection']['holder'].update({f:'other'}),'manual_holder')
    case('manual不能借automatic',lambda o,v,s,c,p,t:c['control_projection'].update(mode='automatic',holder=None),'manual_holder')
    case('automation不能借manual',lambda o,v,s,c,p,t:c['control_projection'].update(mode='manual'),'automation_mode',origin='automation')
    case('automatic不能残留holder',lambda o,v,s,c,p,t:c['control_projection'].update(holder=dict(issuer_id='issuer',issuer_epoch='epoch',principal_id='bob')),
      'automation_mode',origin='automation')
    case('当前授权换代',lambda o,v,s,c,p,t:c.update(authorization_ref=L.ref('auth.new')),'permit_authorization')
    case('新控制投影未更新permit',lambda o,v,s,c,p,t:(v.update(effective_version='99'),seal_permit(v)),'permit_control')
    case('借用父普通hold引用',lambda o,v,s,c,p,t:(v.update(hold_ref=L.ref('parent.hold')),seal_permit(v)),'ownership_missing','cancel')
    case('Ownership引用摘要必须精确',lambda o,v,s,c,p,t:(v.update(ownership_ref=L.ref('other')),seal_permit(v)),'permit_owner')
    for field in GUARD_FIELDS:
        case('Guard精确绑定:'+field,lambda o,v,s,c,p,t,f=field:c['guard_receipts']['guard']['content'].update({f:None}),'permit_guard')
    for now,expected in ((50,'permit_expired'),(51,None),(69,None),(70,'permit_expired')):
        case('半开发送窗口:'+str(now),lambda *args:None,expected,now=now)
    case('取得hold之前不得选择',lambda o,v,s,c,p,t:(v.update(selected_tick_ns='49'),rebind_guard(v,c)),'permit_expired')
    case('不能延长原发送窗口',lambda o,v,s,c,p,t:(v.update(expires_tick_ns='71'),rebind_guard(v,c)),'permit_window')
    case('旧运行域不能迁移',lambda o,v,s,c,p,t:(o.update(clock_domain_id='clock_'+'2'*64),rebind_owner(o,v,c),rebind_guard(v,c)),'ownership_clock')
    owner,permit,observation,c,p,t=fixture('cancel')
    check('取消Requester独立于父actor',permit['identity']['requester']!=c['parent_requester'],True)
    check('取消独立主体可通过但不代表完整发送',M.permit_error(permit,c,52),None)
    # 新原件确实来自旧控制；伪造的观察却自报当前权威，复现旧判定缺口。
    owner,permit,observation,c,p,t=fixture()
    owner['control_authority_ref']=L.ref('old.authority');rebind_owner(owner,permit,c)
    observation['owner_ref']=permit['ownership_ref']
    L.resource_update(c,[observation]);check('旧开放模型接受仅自报的当前active',L.M.current_error(t,p,c,52),None)
    check('新原件关联拒绝改标签',M.resources_error([observation],c),'ownership_relabelled')
    observation['control_authority_ref']=owner['control_authority_ref']
    check('诚实保留旧归属仍不能当前发送',M.resources_error([observation],c),'ownership_control')
    owner,permit,observation,c,p,t=fixture()
    for label,observations,expected in [('遗漏',[],'ownership_hold_set'),('重复',[observation,observation],'ownership_hold_set'),
      ('换Ref',[dict(observation,hold_ref=L.ref('hold',2))],'ownership_observation'),
      ('换owner',[dict(observation,owner_ref=L.ref('other'))],'ownership_observation')]:
        check('资源全集:'+label,M.resources_error(observations,c),expected)
    c['ownerships']={};check('缺原件不得回填当前holder',M.resources_error([observation],c),'ownership_missing')
    owner,permit,observation,c,p,t=fixture('cancel');c['control_projection']['gate_state']='protected'
    check('主体子检查故意不等于ready',M.permit_error(permit,c,52),None)
    L.resource_update(c,[dict(observation,state='unknown')]);check('旧全局开放仍拒unknown',L.M.current_error(t,p,c,52),'control_not_ready')
    c['control_projection']['gate_state']='ready';check('未知父风险仍阻全局ready',L.M.current_error(t,p,c,52),'resource_blocked')
    db=S.fresh(mixed=True)
    try:
        steps=S.snapshot(db);steps.insert(1,S.I('go_hold',snapshot_id='snap',hold_id='h',authority_state_id='effective',owner_ref='self.reported',classification='active'))
        S.U.tx(db,steps)
        check('旧178表可接受未绑定实际归属的active',db.execute('SELECT count(*) FROM go_valid_snapshot').fetchone()[0],1)
        check('旧布局仍保留四个最终签发阻断',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        check('旧库外键检查',db.execute('PRAGMA foreign_key_check').fetchall(),[])
        check('旧库完整性',db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
    finally:db.close()
    check('全部合成权威可通过是限制反证',evaluate(fixture()),None)
    return checks
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'hold-ownership-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),scope='不可变占用归属及发送主体子契约',sqlite_version=sqlite3.sqlite_version,
          runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,new_sql_layout_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
