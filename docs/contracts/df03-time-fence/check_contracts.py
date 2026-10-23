"""人工预期的TIME共享账本/切点快照检查，不执行SQLite、NTP或设备。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from build_contracts import HERE,IPC,build,encoded
import reference_model as M

ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','registry.schema.json','reference_model.py','check_contracts.py')]+[IPC]


def R(name):return dict(id=name,revision='1',digest=M.digest(name))
def clone(value):return copy.deepcopy(value)


def fixture():
    domain=dict(authority_service_id='controller',database_instance_id='database',provider_id='provider',provider_boot_id='provider-boot',
        runtime_binding_ref=R('runtime'),clock_domain_id='clock_'+'1'*64,descriptor_digest=M.digest('descriptor'),clock_generation='1')
    binding=dict(domain=domain,source_ref=R('source'),profile_ref=R('profile'),approval_ref=R('approval'),policy_ref=R('policy'),time_generation='1')
    inv=M.seal(dict(invalidation_id='invalid1',revision='1',old_binding=clone(binding),next_time_generation='2',cause_ref=R('cause'),
        deny_new_utc_permits=True,protection_operation_ref=R('operation')),'invalidation_digest')
    def issue(name,seq,kind='ordinary',exit_id='a',initial=None,required=True,disposition='unknown',resolution='unresolved'):
        first=initial or name
        return dict(permit_id=name,kind=kind,issued_revision=str(seq),exit_id=exit_id,packet_ref=R('packet.'+first),
            transmission_ref=R('transmission.'+name),initial_permit_id=first,business_anchor_id=first if kind=='ordinary' else None,
            time_required=required,time_binding=clone(binding) if required else None,disposition=disposition,resolution=resolution)
    exits=[dict(exit_id=e,clock_domain_id=domain['clock_domain_id'],descriptor_digest=domain['descriptor_digest'],retired=e=='r') for e in ('a','b','r')]
    rows=[issue('o1',1,disposition='in_flight',resolution='effect_resolved'),issue('o2',2,initial='o1'),issue('c1',3,kind='cancel'),
        issue('i1',4,required=False),issue('r1',5,exit_id='r')]
    registry=M.seal(dict(registry_id='registry',revision='1',authority_service_id='controller',database_instance_id='database',
        issued_head='5',exits=exits,issues=rows),'registry_digest')
    # 完整预期手写，不调用selected生成目标。
    targets=[dict(exit_id='a',business_anchor_ids=['o1'],ordinary_permit_ids=['o2'],cancel_permit_ids=['c1']),
             dict(exit_id='b',business_anchor_ids=[],ordinary_permit_ids=[],cancel_permit_ids=[]),
             dict(exit_id='r',business_anchor_ids=['r1'],ordinary_permit_ids=['r1'],cancel_permit_ids=[])]
    cut=M.seal(dict(cut_id='cut1',revision='1',operation_ref=R('operation'),invalidation=clone(inv),
        registry_ref=M.reference(registry,'registry_id','registry_digest'),issued_cut_revision='5',targets=targets),'cut_digest')
    attempt=dict(barrier_id='barrier1',cut_ref=M.reference(cut,'cut_id','cut_digest'),exit_id='a',ordinal='1',previous_barrier_id=None)
    ack=M.seal(dict(ack_id='ack1',revision='1',attempt_ref=M.attempt_ref(attempt),invalidation_ref=M.reference(inv,'invalidation_id','invalidation_digest'),
        minimum_time_generation='2',effective_tick_ns='50',ordinary_coverage=[dict(permit_id='o2',disposition='not_sent',proof='never_received')],
        cancel_coverage=[dict(permit_id='c1',disposition='unknown',proof='send_uncertain')],
        business_coverage=[dict(permit_id='o1',disposition='in_flight')]),'ack_digest')
    return registry,inv,cut,attempt,ack


def run():
    checks=[]
    def check(name,actual,expected=None):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    schema=build();check('生成字节',(HERE/'registry.schema.json').read_bytes()==encoded(schema),True)
    Draft202012Validator.check_schema(schema)
    ipc=json.loads(IPC.read_bytes());resources=Registry().with_resources([(s['$id'],Resource.from_contents(s)) for s in (schema,ipc)])
    def valid(name,value):return Draft202012Validator({'$ref':schema['$id']+'#/$defs/'+name},registry=resources).is_valid(value)
    registry,inv,cut,attempt,ack=fixture()
    for name,value in [('Registry',registry),('Cut',cut),('Attempt',attempt),('Ack',ack)]:
        check('结构:'+name,valid(name,value),True)
        z=clone(value);z['extra']=True;check('额外字段:'+name,valid(name,z),False)
    check('Registry关联',M.registry_error(registry))
    check('固定完整切点',M.cut_error(cut,registry,inv))
    check('首次尝试',M.attempt_error(attempt,cut,[],{}))
    check('原ACK完整覆盖',M.ack_error(ack,attempt,cut,registry))
    check('采用当前尝试',M.adoption_error(ack,attempt,[attempt],{}))
    check('全部应用',M.application_error(cut,['a','b','r']))
    check('漏空出口不能应用',M.application_error(cut,['a','r']),'incomplete_application')
    check('重复出口不算完整',M.application_error(cut,['a','b','r','r']),'incomplete_application')
    # 每个变异独立给出预期；重新摘要不能掩盖事实错配。
    mutations=[
        ('同许可跨类别复用',lambda z:z['issues'][2].update(permit_id='o1'),'identity_collision'),
        ('两个局部水位冲突',lambda z:z['issues'][2].update(issued_revision='2'),'shared_sequence'),
        ('缺历史行',lambda z:z['issues'].pop(0),'shared_sequence'),
        ('错head',lambda z:z.update(issued_head='6'),'shared_sequence'),
        ('换序不掩盖缺口',lambda z:z['issues'].reverse(),'shared_sequence'),
        ('缺出口',lambda z:z['exits'].pop(),'exit_missing'),
        ('重复出口',lambda z:z['exits'].append(clone(z['exits'][0])),'identity_collision'),
        ('出口乱序',lambda z:z['exits'].reverse(),'exit_order'),
        ('取消冒用普通初始',lambda z:z['issues'][2].update(initial_permit_id='o1'),'initial_binding'),
        ('重传换packet',lambda z:z['issues'][1].update(packet_ref=R('wrong')),'initial_binding'),
        ('错业务锚',lambda z:z['issues'][1].update(business_anchor_id='wrong'),'business_anchor'),
        ('取消夹普通锚',lambda z:z['issues'][2].update(business_anchor_id='o1'),'cancel_anchor'),
        ('降级UTC需求',lambda z:z['issues'][2].update(time_required=False),'time_shape'),
        ('重复传输原件',lambda z:z['issues'][2].update(transmission_ref=clone(z['issues'][0]['transmission_ref'])),'transmission_collision'),
        ('跨authority',lambda z:z['issues'][2]['time_binding']['domain'].update(authority_service_id='other'),'scope'),
        ('错时钟域',lambda z:z['issues'][2]['time_binding']['domain'].update(clock_domain_id='clock_'+'2'*64),'domain'),
        ('未知冒充未发核销',lambda z:z['issues'][2].update(resolution='never_sent'),'resolution_contradiction')]
    for name,mutate,reason in mutations:
        z=clone(registry);mutate(z);M.seal(z,'registry_digest');check(name,M.registry_error(z),reason)
    for name,mutate,reason in [
        ('漏取消许可',lambda z:z['targets'][0].update(cancel_permit_ids=[]),'target_set'),
        ('漏原初始锚',lambda z:z['targets'][0].update(business_anchor_ids=[]),'target_set'),
        ('漏空活出口',lambda z:z['targets'].pop(1),'target_set'),
        ('漏退役未决出口',lambda z:z['targets'].pop(),'target_set'),
        ('即时许可混入UTC',lambda z:z['targets'][0]['ordinary_permit_ids'].append('i1'),'target_set'),
        ('错共享切点',lambda z:z.update(issued_cut_revision='4'),'cut_watermark'),
        ('错Registry引用',lambda z:z.update(registry_ref=R('wrong')),'registry_ref'),
        ('错操作身份',lambda z:z.update(operation_ref=R('wrong')),'operation'),
        ('目标乱序',lambda z:z['targets'].reverse(),'target_set')]:
        z=clone(cut);mutate(z);M.seal(z,'cut_digest');check(name,M.cut_error(z,registry,inv),reason)
    z=clone(cut);z['invalidation']['next_time_generation']='3';M.seal(z['invalidation'],'invalidation_digest');M.seal(z,'cut_digest')
    check('重算原件不是批准',M.cut_error(z,registry,inv),'invalidation_authority')
    check('精确代次后继',M.cut_error(z,registry,z['invalidation']),'generation')
    z=clone(cut);z['invalidation']['old_binding']['time_generation']=str(M.LIMIT);z['invalidation']['next_time_generation']='0'
    M.seal(z['invalidation'],'invalidation_digest');M.seal(z,'cut_digest');check('代次不回绕',M.cut_error(z,registry,z['invalidation']),'generation')
    for name,mutate,reason in [
        ('ACK漏取消分支',lambda z:z.update(cancel_coverage=[]),'coverage_set'),
        ('ACK多余许可',lambda z:z['ordinary_coverage'].append(dict(permit_id='i1',disposition='unknown',proof='send_uncertain')),'coverage_set'),
        ('ACK错误proof',lambda z:z['ordinary_coverage'][0].update(proof='transport_entered'),'proof'),
        ('末次未发不能清原已发',lambda z:z['business_coverage'][0].update(disposition='not_sent'),'business_coverage'),
        ('ACK错失效原件',lambda z:z.update(invalidation_ref=R('wrong')),'invalidation'),
        ('ACK错floor回显',lambda z:z.update(minimum_time_generation='3'),'floor_echo'),
        ('ACK错尝试',lambda z:z.update(attempt_ref=R('wrong')),'attempt')]:
        z=clone(ack);mutate(z);M.seal(z,'ack_digest');check(name,M.ack_error(z,attempt,cut,registry),reason)
    check('ACK先验当前端点',M.ack_error(ack,attempt,cut,registry,False),'peer')
    z=clone(registry);z['issues'][1]['disposition']='in_flight';M.seal(z,'registry_digest')
    check('已知发送不可降级',M.ack_error(ack,attempt,cut,z),'downgrade')
    later={**clone(attempt),'barrier_id':'barrier2','ordinal':'2','previous_barrier_id':'barrier1'}
    for reason,expected in [('cache_miss',None),('deadline_elapsed',None),('channel_lost','retry_basis')]:
        check('尝试恢复:'+reason,M.attempt_error(later,cut,[attempt],{'barrier1':reason}),expected)
    check('无失败不得重装',M.attempt_error(later,cut,[attempt],{}),'retry_basis')
    check('退役出口不得重装',M.attempt_error(later,cut,[attempt],{'barrier1':'cache_miss'},False),'retired')
    check('已采用不重装',M.attempt_error(later,cut,[attempt],{'barrier1':'cache_miss'},True,True),'already_applied')
    check('旧ACK保留原件有效',M.ack_error(ack,attempt,cut,registry))
    check('旧ACK不替新尝试',M.adoption_error(ack,attempt,[attempt,later],{'barrier1':'cache_miss'}),'not_latest')
    check('失败尝试不采用',M.adoption_error(ack,attempt,[attempt],{'barrier1':'deadline_elapsed'}),'failed_attempt')
    check('更高floor保留',M.merge_floor('4',ack),'4')
    check('新floor推进',M.merge_floor('1',ack),'2')
    binding=inv['old_binding'];domain=binding['domain']
    check('先失效阻旧UTC',M.issue_after_invalidation(True,binding,domain,'2',True),'denied_generation')
    check('即时不受UTC子域拒绝',M.issue_after_invalidation(False,None,domain,'2',False))
    check('即时不得夹带旧时间',M.issue_after_invalidation(False,binding,domain,'2',False),'unexpected_time')
    newer={**clone(binding),'time_generation':'2'}
    check('新代仍需合格State',M.issue_after_invalidation(True,newer,domain,'2',False),'unqualified')
    check('新代只通过时间子域',M.issue_after_invalidation(True,newer,domain,'2',True))
    z=clone(registry);z['issues'][0]['resolution']='never_sent';M.seal(z,'registry_digest')
    check('迟到强事实重新未决',M.pending(z['issues'][0]),True)
    check('原核销不被覆盖',z['issues'][0]['resolution'],'never_sent')
    z=clone(registry);z['exits'][2]['retired']=False;z['issues'][4]['resolution']='effect_resolved';M.seal(z,'registry_digest')
    check('空活出口仍在集合',[x['exit_id'] for x in M.selected(z,inv)],['a','b','r'])
    z['exits'][2]['retired']=True;M.seal(z,'registry_digest')
    check('已退役且已核销可不纳入',[x['exit_id'] for x in M.selected(z,inv)],['a','b'])
    z=clone(registry);z['exits'][1].update(clock_domain_id='clock_'+'2'*64,descriptor_digest=M.digest('other-domain'));M.seal(z,'registry_digest')
    check('另一域空出口不混入',[x['exit_id'] for x in M.selected(z,inv)],['a','r'])
    z=clone(registry);z['issues'][2]['time_binding']['time_generation']='2';M.seal(z,'registry_digest')
    check('迟到旧cut选择不扩大到新代',M.selected(z,inv)[0]['cancel_permit_ids'],[])
    z=clone(registry);z['issues'][2]['time_binding']['source_ref']=R('old-source');M.seal(z,'registry_digest')
    check('同域旧源仍受floor保护',M.selected(z,inv)[0]['cancel_permit_ids'],['c1'])
    # 256边界与完整集合超限；每例人工固定目标，不用selected生成预期。
    for count,expected in ((256,None),(257,'capacity')):
        z=clone(registry);z.update(issues=[],issued_head='0')
        z['exits']=[{**clone(registry['exits'][0]),'exit_id':f'e{j:03}'} for j in range(count)]
        M.seal(z,'registry_digest');candidate=clone(cut)
        candidate.update(registry_ref=M.reference(z,'registry_id','registry_digest'),issued_cut_revision='0',
            targets=[dict(exit_id=f'e{j:03}',business_anchor_ids=[],ordinary_permit_ids=[],cancel_permit_ids=[]) for j in range(count)])
        M.seal(candidate,'cut_digest');check('目标容量:'+str(count),M.cut_error(candidate,z,inv),expected)
    for count,expected in ((256,None),(257,'capacity')):
        z=clone(registry);z['exits']=[clone(registry['exits'][0])]
        z['issues']=[{**clone(registry['issues'][2]),'permit_id':f'c{j:03}','initial_permit_id':f'c{j:03}',
            'issued_revision':str(j+1),'packet_ref':R(f'p{j}'),'transmission_ref':R(f't{j}')} for j in range(count)]
        z['issued_head']=str(count);M.seal(z,'registry_digest');candidate=clone(cut)
        candidate.update(registry_ref=M.reference(z,'registry_id','registry_digest'),issued_cut_revision=str(count),
            targets=[dict(exit_id='a',business_anchor_ids=[],ordinary_permit_ids=[],cancel_permit_ids=[f'c{j:03}' for j in range(count)])])
        M.seal(candidate,'cut_digest');check('取消完整集合容量:'+str(count),M.cut_error(candidate,z,inv),expected)
    empty=clone(registry);empty.update(issues=[],issued_head='0',exits=[]);M.seal(empty,'registry_digest')
    empty_cut=clone(cut);empty_cut.update(registry_ref=M.reference(empty,'registry_id','registry_digest'),issued_cut_revision='0',targets=[]);M.seal(empty_cut,'cut_digest')
    check('真实空集合可冻结',M.cut_error(empty_cut,empty,inv))
    check('真实空集合可应用',M.application_error(empty_cut,[]))
    for field,value,reason in [('ordinal','3','attempt_ordinal'),('previous_barrier_id','wrong','previous')]:
        z=clone(later);z[field]=value;check('尝试:'+field,M.attempt_error(z,cut,[attempt],{'barrier1':'cache_miss'}),reason)
    z=clone(registry);z['issues'][2].update(kind='ordinary',initial_permit_id='c1',business_anchor_id='c1',packet_ref=clone(z['issues'][0]['packet_ref']));M.seal(z,'registry_digest')
    check('同packet不能另建初始许可',M.registry_error(z),'initial_collision')
    # 本地模型只核结构和给定原件，不虚构对真实来源的证明。
    z=clone(registry);z['issues'][0]['transmission_ref']=R('synthetic-but-well-formed');M.seal(z,'registry_digest')
    check('限制反证:Ref合法不证明真实原件',M.registry_error(z))
    for bad in ('01','1\n','-0',1):
        z=clone(registry);z['issued_head']=bad;check('严格计数字段:'+repr(bad),valid('Registry',z),False)
    return dict(version='time-fence-registry/0.1.0-draft.1',approved=False,all_passed=True,check_count=len(checks),checks=checks,
        runtime_validation=dict(sqlite=0,ipc=0,ntp=0,authority=0,device=0,concurrency=0,disk_crash=0),
        artifact_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    path=HERE/'reference-report.json'
    if args.check_report:
        def raw(p):return subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if args.staged else p.read_bytes()
        report=json.loads(raw(path));assert set(report['artifact_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for rel,d in report['artifact_sha256'].items():assert hashlib.sha256(raw(ROOT/rel)).hexdigest()==d,rel
        print(f'{len(INPUTS)}项输入绑定一致；未重跑检查')
    else:
        if args.staged:parser.error('--staged仅用于--check-report')
        report=run()
        if args.report:path.write_bytes(encoded(report))
        print(json.dumps({k:report[k] for k in ('all_passed','check_count','runtime_validation')},ensure_ascii=False))
