"""将开放对象统一到当前IPC及ordinary/cancel_only用途；保留旧候选。"""
import argparse,copy,json
from pathlib import Path
import build_open_plan as P
import build_open_lifecycle as L
HERE=Path(__file__).resolve().parent
IPC=HERE.parent/'c04-lifecycle/continuation-binding-ipc.schema.json'
SID='https://leafseamer.invalid/contracts/c08-controller/open-contract.schema.json'
obj=P.obj;ref=P.ref
def build():
    ipc=json.loads(IPC.read_bytes());old=json.loads(P.IPC.read_bytes())['$id'];iid=ipc['$id']
    def rewrite(v):
        if isinstance(v,list):return [rewrite(x) for x in v]
        if not isinstance(v,dict):return v
        return {k:(x.replace(old+'#/',iid+'#/').replace(P.SID+'#/','#/') if k=='$ref' else copy.deepcopy(x) if k in ('const','enum') else rewrite(x)) for k,x in v.items()}
    d=rewrite(P.build()['$defs']);d.pop('ReadyCommit')
    d['Basis']['properties']['kind']['enum'].append('scope')
    for n in ('OpenPlan','OpenDispatch','OpenAckEvidence'):
        d[n]['properties']['format_version']={'const':{'OpenPlan':'gate-open-plan/0.3.0-draft.1','OpenDispatch':'gate-open-dispatch/0.3.0-draft.1','OpenAckEvidence':'gate-open-evidence/0.3.0-draft.1'}[n]};d[n]['required'].append('format_version')
    legacy=L.build()['$defs']
    for n in ('Holder','ControlProjection','ResourceSafetyEvidence','HoldObservation'):d[n]=rewrite(legacy[n])
    d['GateProjection']=obj(record_ref=ref('Ref'),binding=ref('Binding'),gate_revision=ref('Counter'),gate_token=ref('Id'),barrier_id=ref('Id'),phase={'enum':['fenced','ready','scoped']},activation_id={'anyOf':[ref('Id'),{'type':'null'}]},lease_until_tick_ns=ref('Counter'))
    d['EligibilityRefs']=obj(**{k:ref('Ref') for k in ('control_authority','resource_safety','gate_safety','authorization')})
    d['OpenProposal']=obj(format_version={'const':'gate-open-proposal/0.3.0-draft.1'},plan=ref('OpenPlan'),eligibility_refs=ref('EligibilityRefs'),control_before=ref('ControlProjection'),gate_before=ref('GateProjection'),proposal_digest=ref('Digest'))
    d['OpenAdoption']=obj(format_version={'const':'gate-open-adoption/0.3.0-draft.1'},commit_id=ref('Id'),revision={'const':'1'},purpose={'enum':['ordinary','cancel_only']},proposal_ref=ref('Ref'),dispatch_ref=ref('Ref'),evidence_ref=ref('Ref'),gate_access_ref=ref('Ref'),protection_assessment_ref={'anyOf':[ref('Ref'),{'type':'null'}]},eligibility_refs=ref('EligibilityRefs'),control_after=ref('ControlProjection'),gate_after=ref('GateProjection'),committed_tick_ns=ref('Counter'),adoption_digest=ref('Digest'))
    branches={}
    for branch,assessment,state,phase in [('then',{'type':'null'},'ready','ready'),('else',ref('Ref'),'protected','scoped')]:
        branches[branch]={'properties':dict(protection_assessment_ref=assessment,control_after={'properties':{'gate_state':{'const':state}}},gate_after={'properties':{'phase':{'const':phase}}})}
    d['OpenAdoption']['allOf']=[{'if':{'properties':{'purpose':{'const':'ordinary'}}},**branches}]
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}
def encoded():return (json.dumps(build(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'open-contract.schema.json'
    if a.check:assert path.read_bytes()==encoded()
    else:path.write_bytes(encoded())
