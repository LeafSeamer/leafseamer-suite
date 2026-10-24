"""封存字段、跨原件关系和提交观察的离线向量；不执行设备或完整SQL签发。"""
import argparse,copy,hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import final_admission_model as M
G=M.G;HERE=G.HERE;ROOT=HERE.parents[2];clone=copy.deepcopy
def ref(name):return dict(id=name,revision='1',digest=M.digest(name))
def refresh(v,o):
    for role,source in o.items():
        source['ref']['digest']=M.projection_digest(source);v['inputs'][role]=clone(source['ref'])
    v.update(M.seal(v));return v
def fixture(kind='ordinary',origin='manual',retry=False):
    binding=dict(scope=dict(authority_service_id='controller',database_instance_id='database'),controller_boot_id='controller.boot',worker_boot_id='worker.boot',writer_exit_id='exit',ipc_session_id='ipc',device_id='device',device_session_id='device.session',clock_domain_id='clock_'+'1'*64,descriptor_digest=M.digest('clock'))
    identity=dict(kind=kind,command_ref=ref('command'),attempt_ref=ref('attempt') if kind=='ordinary' else None,cancellation_ref=ref('cancel') if kind=='cancel' else None,execution_ref=ref('execution') if kind=='cancel' else None,
        requester=dict(kind='human' if origin=='manual' else 'service',issuer_id='issuer',issuer_epoch='epoch',principal_id='operator'),origin=origin,source_ref=ref('request'))
    roles=list(G.COMMON)+(list(G.CANCEL) if kind=='cancel' else [])
    sources={r:ref('source.'+r) for r in roles};inputs={r:None for r in (*G.COMMON,*G.CANCEL)}
    v=dict(format_version=G.VERSION,seal_id='seal',revision='1',transaction_id='transaction',binding=clone(binding),identity=clone(identity),command_state_ref=ref('state'),permit_id='permit',transmission_id='transmission',issued_revision='9007199254740993',ordinal='0',transmission_kind='initial',previous_permit_ref=None,
        packet_ref=dict(packet_id='packet',packet_digest=M.digest('packet')),encoding_packet_ref=ref('encoding.packet'),hold_ref=ref('hold'),hold_transition='create' if kind=='ordinary' else 'reuse',inputs=inputs,
        selected_tick_ns='51',sealed_tick_ns='52',send_window=dict(not_before_tick_ns='53',before_tick_ns='70'),seal_digest=M.digest('placeholder'))
    cut=dict(transaction_id=v['transaction_id'],binding=clone(binding),command_state_ref=clone(v['command_state_ref']),identity=clone(identity),selected_tick_ns=51,sealed_tick_ns=52,previous_issue_revision=9007199254740992)
    common=dict(binding=clone(binding),identity=clone(identity))
    bodies={r:clone(common) for r in roles}
    bodies['origin'].update(command_state_ref=clone(v['command_state_ref']))
    bodies['capability'].update(encoding_source_ref=sources['encoding'])
    bodies['encoding'].update(packet_record_ref=clone(v['encoding_packet_ref']),packet_ref=clone(v['packet_ref']),received_tick_ns='50',expires_tick_ns='65')
    for r in ('authorization','gate_access','guard','budget','time'):bodies[r].update(not_before_tick_ns='53' if r=='time' else '49',before_tick_ns='70' if r=='guard' else '80')
    bodies['control'].update(pending_operation_id=None,control_epoch='control.epoch',effective_version='3',mode='manual' if origin=='manual' else 'automatic',holder=clone(identity['requester']) if origin=='manual' else None)
    for r in ('ownership','permit_authority','gate_access'):bodies[r].update(control_authority_ref=sources['control'],control_epoch='control.epoch',effective_version='3')
    bodies['ownership'].update(hold_ref=clone(v['hold_ref']))
    bodies['permit_authority'].update(hold_ref=clone(v['hold_ref']),**{k:v[k] for k in ('permit_id','issued_revision','ordinal','transmission_id')},ownership_ref=sources['ownership'],authorization_ref=sources['authorization'],guard_ref=sources['guard'],packet_ref=clone(v['encoding_packet_ref']))
    bodies['gate_access'].update(purpose='ordinary' if kind=='ordinary' else 'cancel_only',restricted_identity=clone(identity) if kind=='cancel' else None,authorization_ref=sources['authorization'],resource_safety_ref=sources['resource_safety'],gate_safety_ref=sources['gate_safety'])
    bodies['gate_commit'].update(access_ref=sources['gate_access'])
    for r in ('guard','budget','time'):bodies[r].update(permit_id=v['permit_id'],issued_revision=v['issued_revision'])
    bodies['guard'].update(packet_ref=clone(v['packet_ref']),gate_access_ref=sources['gate_access'],ownership_ref=sources['ownership'],protection_assessment_ref=sources.get('protection_assessment'))
    bodies['budget'].update(charge_kind='new_transmission',charged_permit_id=v['permit_id'])
    bodies['time'].update(clock_domain_id=binding['clock_domain_id'],descriptor_digest=binding['descriptor_digest'])
    hold=dict(hold_ref=clone(v['hold_ref']),ownership_ref=sources['ownership'],classification='active')
    parent=dict(hold_ref=ref('parent.hold'),ownership_ref=ref('parent.owner'),classification='unknown')
    before=[] if kind=='ordinary' else [hold,parent]
    for r,holds in [('resource_before',before),('resource_after',[hold] if kind=='ordinary' else before)]:bodies[r].update(resource_safety_ref=sources['resource_safety'],holds=clone(holds))
    if kind=='cancel':
        bodies['ordinary_closure'].update(stage='ordinary')
        bodies['protection_assessment'].update(resource_ref=sources['resource_after'])
        bodies['primitive_dependency'].update(execution_ref=clone(identity['execution_ref']),transmission_id=v['transmission_id'])
    originals={r:dict(role=r,ref=ref('projection.'+r),source_ref=clone(sources[r]),scope=clone(binding['scope']),transaction_id=v['transaction_id'],body=clone(bodies[r])) for r in roles}
    refresh(v,originals)
    if retry:
        prior=clone(v);v.update(seal_id='seal.next',permit_id='permit.next',transmission_id='transmission.next',issued_revision='9007199254740994',ordinal='1',transmission_kind='protocol_resend',previous_permit_ref=M.reference(prior),hold_transition='reuse')
        cut.update(previous_issue_revision=9007199254740993,previous_permit=prior,previous_sources=clone(sources))
        for r in ('guard','budget','permit_authority'):originals[r]['source_ref']=ref('next.'+r)
        originals['permit_authority']['body'].update(guard_ref=originals['guard']['source_ref'],**{k:v[k] for k in ('permit_id','transmission_id','issued_revision','ordinal')})
        for r in ('guard','budget','time'):originals[r]['body'].update(permit_id=v['permit_id'],issued_revision=v['issued_revision'])
        originals['budget']['body']['charged_permit_id']=v['permit_id']
        originals['resource_before']['body']['holds']=clone(originals['resource_after']['body']['holds'])
        if kind=='cancel':originals['primitive_dependency']['body']['transmission_id']=v['transmission_id']
        refresh(v,originals)
    return v,originals,cut

def observation(v,outcome):return M.seal(dict(observation_id='observation',transaction_id=v['transaction_id'],scope=v['binding']['scope'],seal_ref=M.reference(v),permit_id=v['permit_id'],outcome=outcome,observed_tick_ns='53',observer_ref=ref('local.writer')),'observation_digest')
def run():
    checks=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def reject(n,f,reason=None):
        try:f()
        except (ValueError,ValidationError) as error:
            if reason:assert str(error)==reason,(n,str(error))
            check(n);return
        raise AssertionError(n)
    def mutation(n,edit,kind='ordinary',retry=False,reason=None):
        v,o,c=fixture(kind,retry=retry);edit(v,o,c);refresh(v,o);reject(n,lambda:M.verify(v,o,c),reason)
    check('生成字节一致',(HERE/'final-admission.schema.json').read_bytes()==G.raw(G.build()))
    Draft202012Validator.check_schema(G.build());check('Schema有效')
    for kind in ('ordinary','cancel'):
        for origin in ('manual','automation'):
            for retry in (False,True):check('跨原件正例'+kind+origin+str(retry),M.verify(*fixture(kind,origin,retry))=='cross_object_binding_valid')
    baseline=fixture()[0];reject('根禁止直接实例',lambda:Draft202012Validator(G.build()).validate(baseline))
    for field in baseline:
        v=clone(baseline);del v[field];reject('Seal缺字段'+field,lambda v=v:M.validate('Seal',v))
    for role in (*G.COMMON,*G.CANCEL):
        v,o,c=fixture('cancel');del o[role];reject('原件缺角色'+role,lambda v=v,o=o,c=c:M.verify(v,o,c))
        mutation('原件错事务'+role,lambda v,o,c,r=role:o[r].update(transaction_id='other'),'cancel')
        mutation('投影错主体'+role,lambda v,o,c,r=role:o[r]['body']['identity']['requester'].update(principal_id='other'),'cancel')
        mutation('投影错scope'+role,lambda v,o,c,r=role:o[r]['scope'].update(database_instance_id='other'),'cancel')
    for value in ('01','1\n','-1',1,str(10**20)):
        v=clone(baseline);v['issued_revision']=value;reject('大整数词法'+repr(value),lambda v=v:M.validate('Seal',v))
    mutation('全局issue不能跳号',lambda v,o,c:c.update(previous_issue_revision=5))
    mutation('接管pending拒绝',lambda v,o,c:o['control']['body'].update(pending_operation_id='takeover'))
    mutation('同名新issuer_epoch拒绝',lambda v,o,c:o['control']['body']['holder'].update(issuer_epoch='new'))
    mutation('接管换代不能复用旧hold',lambda v,o,c:o['control']['body'].update(control_epoch='next'))
    mutation('新资源不能漏旧风险',lambda v,o,c:o['resource_before']['body']['holds'].append(dict(hold_ref=ref('old'),ownership_ref=ref('old.owner'),classification='unknown')))
    mutation('取消不能清父unknown',lambda v,o,c:o['resource_after']['body']['holds'].pop(),'cancel')
    mutation('取消不能重标父hold',lambda v,o,c:o['resource_after']['body']['holds'][1].update(classification='active'),'cancel')
    mutation('重复资源不能靠集合消除',lambda v,o,c:o['resource_after']['body']['holds'].append(clone(o['resource_after']['body']['holds'][0])))
    mutation('资源安全代次变化拒绝',lambda v,o,c:o['resource_after']['body'].update(resource_safety_ref=ref('new.safety')))
    mutation('新增hold必须另有后态快照',lambda v,o,c:o['resource_after'].update(source_ref=clone(o['resource_before']['source_ref'])),reason='resource_snapshot_identity')
    mutation('普通不能借取消闸',lambda v,o,c:o['gate_access']['body'].update(purpose='cancel_only'))
    mutation('取消不能借普通闸',lambda v,o,c:o['gate_access']['body'].update(purpose='ordinary'),'cancel')
    mutation('取消错Plan',lambda v,o,c:o['primitive_dependency']['body'].update(execution_ref=ref('other')),'cancel')
    mutation('取消评估不得借前态',lambda v,o,c:o['protection_assessment']['body'].update(resource_ref=ref('before')),'cancel')
    mutation('Guard不能借父actor',lambda v,o,c:o['guard']['body']['identity']['requester'].update(principal_id='parent'),'cancel')
    mutation('Guard必须指本次范围',lambda v,o,c:o['guard']['body'].update(gate_access_ref=ref('other')))
    mutation('编码packet不能替换',lambda v,o,c:o['encoding']['body']['packet_ref'].update(packet_digest=M.digest('other')))
    mutation('三元packet不等于两字段packet',lambda v,o,c:v.update(encoding_packet_ref=dict(v['packet_ref'])))
    mutation('封存tick到期等号拒绝',lambda v,o,c:(v.update(sealed_tick_ns='70'),c.update(sealed_tick_ns=70)))
    mutation('编码在封存前到期拒绝',lambda v,o,c:o['encoding']['body'].update(expires_tick_ns='52'))
    mutation('窗口不得扩到最长提供者',lambda v,o,c:v['send_window'].update(before_tick_ns='80'))
    mutation('窗口下界不得提前',lambda v,o,c:v['send_window'].update(not_before_tick_ns='49'))
    mutation('窗口交集为空拒绝',lambda v,o,c:o['time']['body'].update(not_before_tick_ns='70'))
    for role in ('authorization','gate_access','budget'):
        mutation('封存不能借未来资格'+role,lambda v,o,c,r=role:o[r]['body'].update(not_before_tick_ns='53'),reason='current_validity_'+role)
    mutation('封存采样不得早于选择',lambda v,o,c:(v.update(sealed_tick_ns='50'),c.update(sealed_tick_ns=50)),reason='sampling_order')
    mutation('TIME不得借另一域',lambda v,o,c:o['time']['body'].update(clock_domain_id='clock_'+'2'*64))
    mutation('预算不得借旧permit',lambda v,o,c:o['budget']['body'].update(charged_permit_id='old'))
    for role in ('guard','budget','permit_authority'):
        def reused(v,o,c,r=role):
            o[r]['source_ref']=clone(c['previous_sources'][r])
            if r=='guard':o['permit_authority']['body']['guard_ref']=clone(o[r]['source_ref'])
        mutation('重传必须新原件'+role,reused,retry=True,reason='resend_fresh_'+role)
    def change_prior(v,o,c,field,value):
        c['previous_permit'][field]=value;c['previous_permit']=M.seal(c['previous_permit']);v['previous_permit_ref']=M.reference(c['previous_permit'])
    mutation('重传不能改原packet',lambda v,o,c:change_prior(v,o,c,'packet_ref',dict(packet_id='other',packet_digest=v['packet_ref']['packet_digest'])),retry=True,reason='resend_fixed_packet_ref')
    mutation('重传必须新transmission身份',lambda v,o,c:change_prior(v,o,c,'transmission_id',v['transmission_id']),retry=True,reason='resend_ordinal')
    # source_ref在投影摘要中，不能在保持投影摘要时替换被引用原件。
    v,o,c=fixture();o['capability']['source_ref']=ref('different');reject('源Ref也参与投影摘要',lambda:M.verify(v,o,c))
    for outcome,result in [('committed','committed_requires_recheck'),('rolled_back','no_issue'),('unknown','quarantine_lookup_only')]:
        v,_,_=fixture();obs=observation(v,outcome);check('提交结果'+outcome,M.observe(v,obs)==result)
        wrong=M.seal(dict(obs,permit_id='other'),'observation_digest');reject('提交观察错许可'+outcome,lambda:M.observe(v,wrong))
    for field in ('guard_ack_ref','commit_observation_ref','send_report_ref'):
        v=clone(baseline);v[field]=ref('future');reject('Seal不得引用未来'+field,lambda v=v:M.validate('Seal',v))
    # 限制反证：本地提供者全伪造但内部一致仍能通过绑定；不能把本函数当授权提供者。
    v,o,c=fixture();v['identity']['requester']['principal_id']='synthetic.forged';c['identity']=clone(v['identity'])
    for source in o.values():source['body']['identity']=clone(v['identity'])
    o['control']['body']['holder']=clone(v['identity']['requester']);refresh(v,o)
    check('绑定验证不是来源真实性证明',M.verify(v,o,c)=='cross_object_binding_valid')
    return checks
def inputs():return list(dict.fromkeys(G.SOURCES+[HERE/n for n in ('final_admission_model.py','check_final_admission.py','final-admission.schema.json','FINAL_ADMISSION_SEAL.md')]+[HERE.parent/'c08-controller'/n for n in ('FINAL_ADMISSION.md','ENCODING_AUTHORITY.md','GATE_ORDER.md','scope-storage.sql','ownership-storage.sql','encoding-storage.sql')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'final-admission-report.json'
    bindings={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==bindings;print(json.dumps(dict(all_passed=True,matched_bindings=len(bindings))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),production_clearance=False,sql_issue_path_executed=False,provider_authenticity_verified=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings)
        if a.report:path.write_bytes(G.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
