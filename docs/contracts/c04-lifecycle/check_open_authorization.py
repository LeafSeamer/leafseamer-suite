"""需求格式的正反例；合成引用通过并不表示权威来源通过。"""
import argparse,copy,hashlib,json
import jsonschema
import rfc8785
import build_open_authorization as B
import open_authorization_requirement as M
HERE=B.HERE;ROOT=HERE.parents[2]
def reference(name):return dict(id=name,revision='1',digest=M.digest(name))
def fixture(mode='manual',purpose='ordinary'):
    who=dict(issuer_id='issuer',issuer_epoch='epoch',principal_id='operator')
    binding=dict(scope=dict(authority_service_id='controller',database_instance_id='database'),controller_boot_id='core.boot',worker_boot_id='worker.boot',
        writer_exit_id='exit',ipc_session_id='ipc.session',device_id='device',device_session_id='device.session',clock_domain_id='clock_'+'a'*64,descriptor_digest=M.digest('descriptor'))
    human=dict(principal=copy.deepcopy(who),session_id='session',credential_id='credential',**{n:reference(n) for n in ('challenge_ref','response_ref','scope_proof_ref','validity_ref')})
    cancel={n:reference(n) for n in ('protection_scope_ref','assessment_ref','cancel_authorization_ref','ownership_ref')}
    return M.seal(dict(format_version='open-authorization-requirement/0.1.0-draft.1',requirement_id='requirement',revision='1',binding=binding,
        purpose=purpose,control_mode=mode,holder=who if mode=='manual' else None,
        control_state_ref=reference('control'),control_authority_ref=reference('authority'),
        evaluator={n:reference(n) for n in ('runtime_ref','policy_ref','authority_response_ref','scope_proof_ref','validity_ref')},
        holder_evidence=human if mode=='manual' and purpose=='ordinary' else None,cancel_evidence=cancel if purpose=='cancel_only' else None,
        authorization_state_ref=reference('authorization'),revocation_cut_ref=reference('revocations'),selected_tick_ns='10',expires_tick_ns='20'))
def inputs():
    return [HERE/n for n in ('build_open_authorization.py','open_authorization_requirement.py','check_open_authorization.py','open-authorization.schema.json','OPEN_AUTHORIZATION.md',
        'open_source_model.py','final_authorization_model.py','OPEN_PROVIDER_SOURCE.md')]+[B.BASE,HERE.parent/'c08-controller/build_scoped_gate.py']
def run():
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))
    def accept(name,value,now='10'):check(name,M.validate_requirement(value,now) is None)
    def reject(name,value,now='10',error=None):
        try:M.validate_requirement(value,now)
        except (ValueError,jsonschema.ValidationError) as exc:
            check(name,error is None or str(exc)==error);return
        raise AssertionError(name)
    jsonschema.Draft202012Validator.check_schema(B.build());check('生成物字节一致',B.encoded()==(HERE/'open-authorization.schema.json').read_bytes())
    for mode in ('manual','automatic'):
        for purpose in ('ordinary','cancel_only'):accept(mode+'/'+purpose,fixture(mode,purpose))
    base=fixture()
    def change(name,path,value,expected=None):
        v=copy.deepcopy(base);target=v
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value;reject(name,M.seal(v),error=expected)
    change('手动缺持有人',['holder'],None)
    change('手动缺当前人员证据',['holder_evidence'],None)
    change('普通请求夹带取消证据',['cancel_evidence'],fixture(purpose='cancel_only')['cancel_evidence'])
    change('错误发行者即使重算摘要',['holder_evidence','principal','issuer_id'],'other','holder_identity')
    change('错误发行代次',['holder_evidence','principal','issuer_epoch'],'other','holder_identity')
    change('错误持有人',['holder_evidence','principal','principal_id'],'other','holder_identity')
    for field in ('challenge_ref','response_ref','scope_proof_ref','validity_ref'):
        change('人员缺完整来源/'+field,['holder_evidence',field],None)
    for field in ('runtime_ref','policy_ref','authority_response_ref','scope_proof_ref','validity_ref'):
        change('评估器缺完整来源/'+field,['evaluator',field],None)
    for field in ('authorization_state_ref','revocation_cut_ref','control_state_ref','control_authority_ref'):
        change('拒绝裸ID/'+field,[field],'placeholder')
    for field in ('ready','allowed','device_command_authorization_use'):
        change('拒绝调用方扩充许可/'+field,[field],True)
    v=fixture('automatic');v['holder']=base['holder'];reject('自动模式不借人员持有',M.seal(v))
    v=fixture('automatic');v['holder_evidence']=base['holder_evidence'];reject('自动模式不借单人授权',M.seal(v))
    for mode in ('manual','automatic'):
        v=fixture(mode,'cancel_only');v['cancel_evidence']=None;reject('限定取消不能空证据/'+mode,M.seal(v))
        v=fixture(mode,'cancel_only');v['holder_evidence']=base['holder_evidence'];reject('限定取消不能借普通人员证据/'+mode,M.seal(v))
    for value in (10,'01','-1','1.0','100000000000000000000','10\n'):
        change('拒绝非规范时间/'+repr(value),['selected_tick_ns'],value)
    accept('选择时刻等号可解析',base,'10');accept('到期前可解析',base,'19')
    reject('到期等号拒绝',base,'20','requirement_window');reject('选择之前拒绝',base,'9','requirement_window')
    change('零宽窗口拒绝',['expires_tick_ns'],'10','requirement_window')
    change('倒置窗口拒绝',['expires_tick_ns'],'9','requirement_window')
    v=fixture();v.update(selected_tick_ns='99999999999999999998',expires_tick_ns='99999999999999999999');M.seal(v)
    accept('20位整数无浮点舍入',v,'99999999999999999998');reject('20位终点等号拒绝',v,'99999999999999999999','requirement_window')
    v=fixture();v['requirement_digest']=M.digest('wrong');reject('错误摘要拒绝',v,error='requirement_digest')
    v=fixture();v['evaluator']['policy_ref']['digest']=M.digest('changed');reject('嵌套摘要纳入根摘要',v,error='requirement_digest')
    accept('重算全部合成引用仍只通过格式',M.seal(v))
    check('成功返回不含任何许可',M.validate_requirement(base,'10') is None)
    check('根Schema不可误作通用放行器',not jsonschema.Draft202012Validator(B.build()).is_valid(base))
    return dict(all_passed=True,approved=False,cases_passed=len(checks),checks=checks,synthetic_references_structurally_accepted=True,
        authority_sources_verified=False,sqlite_integration_verified=False,revocation_atomicity_verified=False,full_open_verified=False,device_tests_executed=0,
        inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'open-authorization-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,inputs=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(rfc8785.dumps(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
