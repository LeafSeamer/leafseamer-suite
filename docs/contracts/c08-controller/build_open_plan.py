"""开放计划候选的唯一局部格式源；借用固定IPC正文，不生成服务。"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
IPC = HERE.parent/'df03-service/ipc.schema.json'
SID = 'https://leafseamer.invalid/design/c08-controller/open-plan.schema.json'


def obj(**fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


def ref(name):
    return {'$ref': '#/$defs/'+name}


def build():
    ipc = json.loads(IPC.read_bytes())
    old = lambda name: {'$ref': ipc['$id']+'#/$defs/S9__'+name}
    definitions = {
        'Id': dict(type='string', minLength=1, maxLength=128, pattern=r'^[A-Za-z0-9_.:-]+$(?![\s\S])'),
        'Counter': dict(type='string', pattern=r'^(0|[1-9][0-9]{0,19})$(?![\s\S])'),
        'Digest': dict(type='string', pattern=r'^sha256:[0-9a-f]{64}$(?![\s\S])'),
        'Scope': obj(authority_service_id=ref('Id'), database_instance_id=ref('Id')),
        'Ref': obj(id=ref('Id'), revision=ref('Counter'), digest=ref('Digest')),
        'Binding': obj(scope=ref('Scope'), controller_boot_id=ref('Id'), worker_boot_id=ref('Id'),
            writer_exit_id=ref('Id'), ipc_session_id=ref('Id'), device_id=ref('Id'),
            device_session_id=ref('Id'), clock_domain_id=dict(type='string',pattern=r'^clock_[0-9a-f]{64}$(?![\s\S])'),
            descriptor_digest=ref('Digest')),
        'StateRefs': obj(control=ref('Ref'), gate=ref('Ref'), authorization=ref('Ref'), resource=ref('Ref')),
        'Basis': obj(kind={'enum':['activation','resource_recovery','gate_recovery']}, record_ref=ref('Ref')),
    }
    definitions['OpenPlan'] = obj(plan_id=ref('Id'), revision={'const':'1'}, binding=ref('Binding'),
        state_refs=ref('StateRefs'), basis=ref('Basis'), body=old('OPEN_GATEBody'),
        selected_tick_ns=ref('Counter'), expires_tick_ns=ref('Counter'), plan_digest=ref('Digest'))
    definitions['OpenDispatch'] = obj(dispatch_id=ref('Id'), revision={'const':'1'}, plan_ref=ref('Ref'),
        frame=old('OPEN_GATE'), reserved_tick_ns=ref('Counter'), dispatch_digest=ref('Digest'))
    definitions['OpenAckEvidence'] = obj(evidence_id=ref('Id'), revision={'const':'1'}, plan_ref=ref('Ref'),
        dispatch_ref=ref('Ref'), frame=old('OPEN_GATE_ACK'), received_tick_ns=ref('Counter'),
        observer_receipt_ref=ref('Ref'), evidence_digest=ref('Digest'))
    definitions['ReadyCommit'] = obj(ready_id=ref('Id'), revision={'const':'1'}, plan_ref=ref('Ref'),
        dispatch_ref=ref('Ref'), evidence_ref=ref('Ref'), state_refs=ref('StateRefs'),
        committed_tick_ns=ref('Counter'), ready_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,
        'title':'gate-open-plan/0.1.0-draft.1','x-approved':False,'x-runtime-approved':False,
        'not':{},'$defs':definitions}


def encoded():
    return (json.dumps(build(), ensure_ascii=False, indent=2)+'\n').encode()


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    path=HERE/'open-plan.schema.json'
    if args.check: assert path.read_bytes()==encoded(),'生成漂移'
    else: path.write_bytes(encoded())
