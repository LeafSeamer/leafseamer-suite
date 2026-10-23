"""人工预期的有限正反例；不调用判定器计算 expected。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import rfc8785

ROOT=Path(__file__).resolve().parent
D='sha256:'+'1'*64
U='00000000-0000-4000-8000-000000000001'


def digest(v): return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()


def build():
    anchors=dict(command_id='cmd-1',attempt_id='attempt-1',worker_boot_id='boot-1',device_session_id='session-1',
                 collection_generation='1',catalog_revision='2')
    frames=[]
    for i,kind in enumerate(('set_send','set_ack','query_send','query_result')):
        frames.append(dict(evidence_id=f'ev-{i}',**anchors,protocol_request_id='set-1' if i<2 else 'query-1',
            kind=kind,io_seq=str(i+1),tick_ns=str((i+1)*1000000),success=True if i in (1,3) else None,
            scene_uuid=U if i in (0,3) else None))
    bundle=dict(policy_id='obs.program_scene.cut.v1',**anchors,target_scene_uuid=U,
        set_request_id='set-1',query_request_id='query-1',frames=frames,
        evaluation_tick_ns='5000000',deadline_tick_ns='1000000000',max_query_age_ms=500,
        catalog_current=True,fixture_current=True,durable=True)
    footprint=dict(action_ref='sim.marker.set',manifest_digest=D,semantics_revision='1',complete=True,
        reads=[],writes=['device/A/marker'],failure_writes=['device/A/marker'],resources=['device/A'],
        safe_failure_classes=['rejected_before_effect'])
    proof=dict(proof_id='proof-1',proof_revision='1',generator_version='finite-dsl-1',definition_digest=D,
        bindings_digest=D,failed_step_id='step-1',successor_step_ids=['step-2'],failed_footprint=footprint,
        successor_reads=['device/B/state'],successor_writes=['device/B/marker'],successor_resources=['device/B'],
        graph_complete=True,control_dependency=False,verdict='independent')
    snapshot=dict(preview_id='preview-1',run_id='run-1',run_revision='8',service_boot_id='seamer-boot-1',
        request_epoch='epoch-1',definition_digest=D,plan_digest=D,authorization_digest=D,control_digest=D,
        proof_bindings_digest=D,evidence_digest=D,arm_generation='2',issued_tick_ns='1000000',
        expires_tick_ns='30001000000',unresolved_command_ids=[],proposed_step_ids=['step-2'])
    snapshot['preview_digest']=digest(snapshot)
    catalog=dict(device_id='obs-1',device_session_id='session-1',collection_ref='collection-1',
        collection_generation='1',catalog_revision='2',binding_revision='1',status='ready',
        entries=[dict(scene_id='scene-1',obs_scene_uuid=U,display_name='Scene A')])
    operation=dict(operation_id='recovery-1',run_id='run-1',preview_id='preview-1',request_digest=D,
        previous_run_revision='8',committed_run_revision='9',recovery_generation='3',state='reserved',
        new_execution_id='exec-2',new_command_ids=[],consumed=True)
    models=dict(CatalogBinding=catalog,ObsEvidenceFrame=frames[0],ObsCompletionBundle=bundle,
        EffectFootprint=footprint,IndependenceProof=proof,RecoverySnapshot=snapshot,RecoveryOperation=operation)
    examples=[dict(case_id='EX-'+n,model=n,instance=v,schema_valid=True,semantic_error=None) for n,v in models.items()]
    def example(cid,model,field,value,valid,error=None):
        v=copy.deepcopy(models[model]);v[field]=value
        examples.append(dict(case_id=cid,model=model,instance=v,schema_valid=valid,semantic_error=error))
    example('EX-extra','RecoveryOperation','retry_old_intent',True,False)
    example('EX-integer-revision','RecoverySnapshot','run_revision',8,False)
    example('EX-bad-uuid','ObsEvidenceFrame','scene_uuid','by-name',False)
    example('EX-missing-frame','ObsCompletionBundle','frames',frames[:3],False)
    example('EX-reopened','RecoveryOperation','state','queued',False)
    example('EX-wildcard','EffectFootprint','writes',['device/*'],False)
    example('EX-duplicate-scene','CatalogBinding','entries',catalog['entries']+[dict(scene_id='scene-2',obs_scene_uuid=U,display_name='B')],True,'catalog_identity')
    example('EX-bad-digest','RecoverySnapshot','preview_digest','sha256:'+'2'*64,True,'preview_digest')
    v=copy.deepcopy(snapshot);v['expires_tick_ns']=v['issued_tick_ns'];v['preview_digest']=digest({k:x for k,x in v.items() if k!='preview_digest'})
    examples.append(dict(case_id='EX-zero-ttl',model='RecoverySnapshot',instance=v,schema_valid=True,semantic_error='preview_window'))
    example('EX-no-revision-advance','RecoveryOperation','committed_run_revision','8',True,'revision_advance')
    example('EX-forged-proof','IndependenceProof','successor_reads',['device/A/marker'],True,'proof_verdict')
    obs=[]
    def oc(cid,expected,edit=None):
        v=copy.deepcopy(bundle)
        if edit:edit(v)
        obs.append(dict(case_id=cid,bundle=v,expected=expected))
    oc('O01','verified')
    oc('O02','identity',lambda v:v['frames'][3].update(device_session_id='session-old'))
    oc('O03','identity',lambda v:v['frames'][1].update(worker_boot_id='boot-old'))
    oc('O04','identity',lambda v:v['frames'][3].update(catalog_revision='1'))
    oc('O05','order',lambda v:v['frames'][2].update(io_seq='2'))
    oc('O06','order',lambda v:v['frames'][2].update(tick_ns='1'))
    oc('O07','request',lambda v:v['frames'][3].update(protocol_request_id='set-1'))
    oc('O08','request',lambda v:v.update(query_request_id='set-1'))
    oc('O09','ack',lambda v:v['frames'][1].update(success=False))
    oc('O10','predicate',lambda v:v['frames'][3].update(scene_uuid='00000000-0000-4000-8000-000000000002'))
    oc('O11','deadline',lambda v:v.update(evaluation_tick_ns=v['deadline_tick_ns']))
    oc('O12','age',lambda v:v.update(evaluation_tick_ns='504000000'))
    oc('O13','verified',lambda v:v.update(evaluation_tick_ns='503999999'))
    oc('O14','generation',lambda v:v.update(catalog_current=False))
    oc('O15','generation',lambda v:v.update(fixture_current=False))
    oc('O16','durability',lambda v:v.update(durable=False))
    oc('O17','kind',lambda v:v['frames'][3].update(kind='set_ack'))
    oc('O18','identity',lambda v:v['frames'][3].update(evidence_id='ev-0'))
    oc('O19','predicate',lambda v:v['frames'][0].update(scene_uuid=None))
    oc('O20','age',lambda v:v.update(evaluation_tick_ns='3999999'))
    deps=[]
    def pc(cid,expected,edit=None):
        v=copy.deepcopy(proof)
        if edit:edit(v)
        deps.append(dict(case_id=cid,proof=v,expected=expected))
    pc('P01','independent')
    pc('P02','dependent',lambda v:v.update(successor_reads=['device/A/marker']))
    pc('P03','dependent',lambda v:v.update(successor_reads=['device/A']))
    pc('P04','dependent',lambda v:v.update(successor_writes=['device/A/marker/detail']))
    pc('P05','dependent',lambda v:v.update(successor_resources=['device/A']))
    pc('P06','dependent',lambda v:v.update(control_dependency=True))
    pc('P07','unknown',lambda v:v.update(graph_complete=False))
    pc('P08','unknown',lambda v:v['failed_footprint'].update(complete=False))
    pc('P09','dependent',lambda v:v['failed_footprint'].update(failure_writes=['device/B']))
    pc('P10','independent',lambda v:v.update(successor_reads=['device/AB']))
    pc('P11','dependent',lambda v:v['failed_footprint'].update(resources=['device/B']))
    continues=[]
    cbase=dict(context='simple_sequence',required=False,outcome='failed',failure_class='rejected_before_effect',
        resource_status='clear',release_proved=True,proof_current=True,proof_verdict='independent',gates_valid=True)
    def cc(cid,expected,**changes):continues.append(dict(case_id=cid,input=dict(cbase,**changes),safe_failure_classes=footprint['safe_failure_classes'],expected=expected))
    cc('C01',True)
    for i,(field,value) in enumerate([('context','transition'),('context','parallel'),('required',True),
        ('outcome','unknown'),('outcome','blocked'),('outcome','expired'),('outcome','cancelled'),
        ('failure_class','permission_revoked'),('resource_status','unresolved'),('release_proved',False),
        ('proof_current',False),('proof_verdict','dependent'),('gates_valid',False)],2):cc(f'C{i:02}',False,**{field:value})
    current={k:snapshot[k] for k in ('run_revision','service_boot_id','request_epoch','definition_digest',
        'plan_digest','authorization_digest','control_digest','proof_bindings_digest','evidence_digest','arm_generation')}
    recovery=[]
    def rc(cid,actions,expected,*,snap_edit=None,ctx_edit=None):
        s=copy.deepcopy(snapshot);ctx=dict(current)
        if snap_edit:
            s.update(snap_edit);s['preview_digest']=digest({k:x for k,x in s.items() if k!='preview_digest'})
        if ctx_edit:ctx.update(ctx_edit)
        recovery.append(dict(case_id=cid,snapshot=s,current=ctx,actions=actions,expected=expected))
    def a(key='actor-A/key-1',**kw):return dict(key=key,request_digest=D,now_tick_ns='2000000',authorized=True,storage_healthy=True,**kw)
    rc('R01',[a(),a('actor-B/key-2')],['accepted','conflict'])
    rc('R02',[a('actor-B/key-2'),a()],['accepted','conflict'])
    rc('R03',[a(),a()],['accepted','existing'])
    b=a();b['request_digest']='sha256:'+'2'*64
    rc('R04',[a(),b],['accepted','request_conflict'])
    b=a();b['now_tick_ns']=snapshot['expires_tick_ns']
    rc('R05',[b],['expired'])
    rc('R06',[a(),b],['accepted','existing'])
    rc('R07',[a()],['stale'],ctx_edit={'service_boot_id':'new-boot'})
    rc('R08',[a()],['stale'],ctx_edit={'control_digest':'sha256:'+'2'*64})
    rc('R09',[a()],['stale'],ctx_edit={'authorization_digest':'sha256:'+'2'*64})
    rc('R10',[a()],['stale'],ctx_edit={'proof_bindings_digest':'sha256:'+'2'*64})
    rc('R11',[a()],['unresolved'],snap_edit={'unresolved_command_ids':['cmd-old']})
    b=a();b['authorized']=False
    rc('R12',[a(),b],['accepted','forbidden'])
    b=a();b['storage_healthy']=False
    rc('R13',[b,a()],['protected','accepted'])
    rc('R14',[a()],['conflict'],ctx_edit={'run_revision':'9'})
    rc('R15',[a()],['stale'],ctx_edit={'request_epoch':'new-epoch'})
    rc('R16',[a()],['stale'],ctx_edit={'evidence_digest':'sha256:'+'2'*64})
    b=a();b['now_tick_ns']='999999'
    rc('R17',[b],['expired'])
    rc('R18',[a()],['stale'],ctx_edit={'arm_generation':'3'})
    rc('R19',[a()],['stale'],ctx_edit={'plan_digest':'sha256:'+'2'*64})
    rc('R20',[a()],['invalid_snapshot'])
    recovery[-1]['snapshot']['proposed_step_ids']=['tampered-step']
    return dict(examples=examples,obs_cases=obs,proof_cases=deps,continue_cases=continues,recovery_cases=recovery)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    content=json.dumps(build(),ensure_ascii=False,indent=2)+'\n';path=ROOT/'cases.json'
    if args.check:
        if path.read_text(encoding='utf-8')!=content:raise SystemExit('人工向量生成漂移')
    else:path.write_text(content,encoding='utf-8',newline='\n')
