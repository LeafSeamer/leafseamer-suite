"""命令读取、取消及证据HTTP候选；仅生成设计资料，不提供服务。"""
import argparse
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SID = 'https://leafseamer.invalid/design/c02-command-view/command.schema.json'
VERSION = 'command-view/0.1.0-draft.1'
SOURCES = [BASE/p for p in ('c08-controller/lifecycle.schema.json', 'c02-admission/admission.schema.json',
    'c05-protection/protocol.schema.json', 'c05-protection/protection.schema.json',
    'df01-source/source/public.schema.json')]


def obj(**p):
    return dict(type='object', properties=p, required=list(p), additionalProperties=False)


def ref(n):
    return {'$ref': '#/$defs/'+n}


def nullable(v):
    return {'anyOf': [v, {'type': 'null'}]}


def array(v, maximum=256, minimum=0):
    return dict(type='array', items=v, minItems=minimum, maxItems=maximum)


def enum(*v):
    return {'enum': list(v)}


def encoded(v):
    return (json.dumps(v, ensure_ascii=False, indent=2)+'\n').encode()


def build():
    sources = [json.loads(p.read_bytes()) for p in SOURCES]
    life, admission, protocol, _, public = sources
    ext = lambda source, name: {'$ref': source['$id']+'#/$defs/'+name}
    d = {n: ext(life, n) for n in ('Id','Digest','Counter','PositiveCounter','Ref','Scope',
        'State','Policy','DecisionEvidence','ReleaseEvidence','Resolution','PacketRef','CompletionLevel')}
    d.update({n: ext(public, n) for n in ('Actor','ControlVersion','Dispatch','Timestamp','Version')})
    d['RequestIdentity'] = ext(admission, 'RequestIdentity')
    d['InitialCommandRef'] = ext(admission, 'CommandRef')
    d['AutomationOriginBinding'] = ext(protocol, 'AutomationOriginBinding')
    d['RunBinding'] = ext(protocol, 'RunBinding')
    d['Observation'] = ext(public, 'CompletionEvidence')
    d['Invalidation'] = obj(invalidation_id=ref('Id'),scope=ref('Scope'),command_id=ref('Id'),
        subject_ref=ref('Ref'),reason_code=ref('Id'),protection_ref=ref('Ref'))
    d['EvidenceKind'] = enum('observation','decision','release','resolution','invalidation')
    d['EvidenceRecord'] = obj(scope=ref('Scope'), command_id=ref('Id'), source_ref=ref('Ref'),
        kind=ref('EvidenceKind'), body={}, view_digest=ref('Digest'))
    bodies = dict(observation='Observation', decision='DecisionEvidence',
                  release='ReleaseEvidence', resolution='Resolution', invalidation='Invalidation')
    d['EvidenceRecord']['oneOf'] = [
        {'properties': {'kind': {'const': k}, 'body': ref(v)}} for k,v in bodies.items()]
    d['EvidenceIndex'] = obj(snapshot_ref=ref('Ref'), state_ref=ref('Ref'), total=ref('Counter'))
    d['AttemptExit'] = obj(exit_ref=ref('Ref'), worker_boot_id=ref('Id'), ipc_session_id=ref('Id'),
        device_session_id=ref('Id'), clock_domain_id=ref('Id'), descriptor_digest=ref('Digest'),
        send_started_at=nullable(ref('Timestamp')), protocol_request_ids=array(ref('Id')))
    d['AttemptView'] = obj(attempt_id=ref('Id'), ordinal=dict(type='integer',minimum=1,maximum=16),
        prepared_state_ref=ref('Ref'), packet_refs=array(ref('PacketRef')), exits=array(ref('AttemptExit')),
        outcome=enum('pending','succeeded','failed','unknown','cancelled','not_sent'),
        evidence_refs=array(ref('Ref')))
    d['CompletionView'] = obj(required=ref('CompletionLevel'), achieved=nullable(ref('CompletionLevel')),
        policy_ref=ref('Ref'), evidence_refs=array(ref('Ref')))
    d['CancellationState'] = enum('requested','confirmed','unsupported','failed','indeterminate','too_late')
    d['CancellationView'] = obj(operation_ref=ref('Ref'), state=ref('CancellationState'),
        future_writes=enum('pending','closed','indeterminate'), reason_code=nullable(ref('Id')))
    d['CommandRecord'] = obj(command_id=ref('Id'), scope=ref('Scope'), revision=ref('PositiveCounter'),
        initial_command_ref=ref('InitialCommandRef'), request_identity=ref('RequestIdentity'),
        target=obj(device_id=ref('Id'),action_id=ref('Id'),capability_version=ref('Version')),
        actor=ref('Actor'), origin=enum('manual','automation'), run_binding=nullable(ref('RunBinding')),
        automation_binding=nullable(ref('AutomationOriginBinding')), accepted_at=ref('Timestamp'),
        dispatch=ref('Dispatch'), control_binding=ref('ControlVersion'), policy=ref('Policy'),
        state_ref=ref('Ref'), state=ref('State'), completion=ref('CompletionView'),
        attempts=array(ref('AttemptView'),16), cancellation=nullable(ref('CancellationView')),
        evidence_index=ref('EvidenceIndex'), record_digest=ref('Digest'))
    d['CommandRecord']['allOf'] = [{
        'if': {'properties': {'origin': {'const':'manual'}}},
        'then': {'properties': {'run_binding': {'type':'null'}, 'automation_binding': {'type':'null'}}},
        'else': {'properties': {'run_binding': ref('RunBinding'), 'automation_binding': ref('AutomationOriginBinding')}}}]
    d['CommandRead'] = obj(view=enum('current','historical'), record=ref('CommandRecord'))
    d['Cursor'] = dict(type='string', minLength=16, maxLength=4096, pattern='^[A-Za-z0-9_-]+$(?![\\s\\S])')
    d['EvidencePage'] = obj(scope=ref('Scope'), command_id=ref('Id'), snapshot_ref=ref('Ref'),
        state_ref=ref('Ref'), offset=ref('Counter'), total=ref('Counter'),
        items=array(ref('EvidenceRecord'),64), next_cursor=nullable(ref('Cursor')), page_digest=ref('Digest'))
    d['CancelKey'] = obj(target_scope=ref('Scope'),issuer_id=ref('Id'),issuer_epoch=ref('Id'),
        principal_id=ref('Id'),request_epoch=ref('Id'),operation_id={'const':'cancelCommand'},
        idempotency_key=ref('Id'))
    d['CancelIdentity'] = obj(key=ref('CancelKey'),request_digest=ref('Digest'))
    d['CancelContent'] = obj(scope=ref('Scope'),command_id=ref('Id'),expected_state_ref=ref('Ref'),
        reason=dict(type='string',maxLength=1024))
    d['CancelRequest'] = obj(context_id=ref('Id'),idempotency_key=ref('Id'),
        expected_state_ref=ref('Ref'),reason=dict(type='string',maxLength=1024))
    d['CancelReceipt'] = obj(identity=ref('CancelIdentity'),command_id=ref('Id'),scope=ref('Scope'),
        cancellation_id=ref('Id'),initial_operation_ref=ref('Ref'),accepted_state_ref=ref('Ref'),
        receipt_digest=ref('Digest'))
    d['CancelOperation'] = obj(cancellation_id=ref('Id'),scope=ref('Scope'),command_id=ref('Id'),
        revision=ref('PositiveCounter'),identity=ref('CancelIdentity'),state=ref('CancellationState'),
        mode=enum('before_dispatch_only','cooperative'),future_writes=enum('pending','closed','indeterminate'),
        command_state_ref=ref('Ref'),evidence_refs=array(ref('Ref')),
        reason_code=nullable(ref('Id')),operation_digest=ref('Digest'))
    d['CancelLookup'] = {'oneOf': [
        obj(state={'const':'found'},receipt=ref('CancelReceipt')),
        obj(state=enum('not_found','indeterminate'),receipt={'type':'null'})]}
    d['Error'] = obj(code=enum('invalid','unauthenticated','forbidden','not_found','state_conflict',
        'identity_conflict','cancellation_exists','snapshot_conflict','snapshot_gone','context_expired','payload_too_large','invalid_semantics',
        'capacity','unavailable','state_projection_pending'),request_id=ref('Id'),
        retry_action=enum('none','read_original','read_current'))
    d['Error']['allOf']=[{'if':{'properties':{'code':{'const':'state_projection_pending'}}},
        'then':{'properties':{'retry_action':{'const':'read_current'}}}}]
    schema = {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':VERSION,
              'not':{},'x-approved':False,'x-runtime-approved':False,'$defs':d}
    resources = {s['$id']:(f'S{i}',s) for i,s in enumerate([schema]+sources)}
    components = {}

    def project(v, base):
        if isinstance(v,list):
            return [project(x,base) for x in v]
        if not isinstance(v,dict):
            return copy.deepcopy(v)
        out={}
        for k,x in v.items():
            if k=='$ref':
                uri,n=(base+x if x.startswith('#') else x).split('#/$defs/')
                prefix,source=resources[uri]
                assert '/' not in n
                name=prefix+'_'+n
                if name not in components:
                    components[name]={}
                    components[name]=project(source['$defs'][n],uri)
                out[k]='#/components/schemas/'+name
            elif k not in ('$schema','$id'):
                out[k]=copy.deepcopy(x) if k in ('const','enum','default','examples') else project(x,base)
        return out

    media=lambda n:{'application/json':{'schema':project(ref(n),SID)}}
    base='/api/v1/commands/{command_id}'
    routes=[
        ('get',base,'getCommand',None,'CommandRead','command.read','read-current'),
        ('get',base+'/revisions/{revision}','getCommandRevision',None,'CommandRead','command.read','read-history'),
        ('post',base+'/cancel','cancelCommand','CancelRequest','CancelReceipt','command.cancel','never-auto-retry'),
        ('post',base+'/cancellations/lookup','lookupCommandCancellation','CancelIdentity','CancelLookup','command.read','read-original'),
        ('get',base+'/cancellations/{cancellation_id}','getCommandCancellation',None,'CancelOperation','command.read','read-current'),
        ('get',base+'/evidence','getCommandEvidence',None,'EvidencePage','command.evidence.read','read-snapshot'),
        ('get',base+'/evidence/{evidence_id}/revisions/{revision}','getCommandEvidenceRevision',None,'EvidenceRecord',
         'command.evidence.read','read-history')]
    paths={}
    errors={'400':['invalid'],'401':['unauthenticated'],'403':['forbidden'],'404':['not_found'],
        '409':['state_conflict','identity_conflict','cancellation_exists','snapshot_conflict'],'410':['snapshot_gone','context_expired'],
        '413':['payload_too_large'],'422':['invalid_semantics'],'429':['capacity'],'503':['unavailable']}
    for method,path,operation,request,response,permission,retry in routes:
        codes=['200','202'] if operation=='cancelCommand' else ['200']
        responses={c:dict(description='持久记录；受理或历史视图均不表示设备已停止或当前可写',content=media(response)) for c in codes}
        for code,names in errors.items():
            names=list(names)
            if operation=='getCommand' and code=='503':
                names.append('state_projection_pending')
            value=project(ref('Error'),SID)
            value={'allOf':[value,{'properties':{'code':{'enum':names}}}]}
            responses[code]=dict(description='错误不授予写入重试；按retry_action仅查询',content={
                'application/json':{'schema':value}})
        for response_item in responses.values():
            response_item['headers']={'Cache-Control':{'schema':{'const':'no-store'}}}
        parameters=[dict(name='X-LeafSeamer-Contract',**{'in':'header'},required=True,schema={'const':VERSION})]
        for name in ('command_id','revision','cancellation_id','evidence_id'):
            if '{'+name+'}' in path:
                parameters.append(dict(name=name,**{'in':'path'},required=True,
                    schema=project(ref('PositiveCounter' if name=='revision' else 'Id'),SID)))
        if operation=='getCommandEvidence':
            parameters += [dict(name='state_revision',**{'in':'query'},required=True,schema=project(ref('PositiveCounter'),SID)),
                dict(name='cursor',**{'in':'query'},required=False,schema=project(ref('Cursor'),SID)),
                dict(name='limit',**{'in':'query'},required=True,schema=dict(type='integer',minimum=1,maximum=64))]
        security=[{'humanBearer':[]},{'serviceBearer':[]}]
        if operation=='cancelCommand':
            security=[{'humanBearer':[],'csrfToken':[]},{'serviceBearer':[]}]
        op=dict(operationId=operation,security=security,parameters=parameters,responses=responses,
            **{'x-required-permission':permission,'x-retry-policy':retry,'x-authority':'controller',
               'x-subject-profiles':['human_device_scope','paired_seamer_own_automation']})
        if request:
            op['requestBody']=dict(required=True,content=media(request))
        if operation=='getCommand':
            op['responses']['200']['content']['application/json']['schema']={'allOf':[
                project(ref('CommandRead'),SID),{'properties':{'view':{'const':'current'}}}]}
        if operation=='getCommandRevision':
            op['responses']['200']['content']['application/json']['schema']={'allOf':[
                project(ref('CommandRead'),SID),{'properties':{'view':{'const':'historical'}}}]}
        paths.setdefault(path,{})[method]=op
    api=dict(openapi='3.1.1',info=dict(title='命令读取取消与证据候选',version=VERSION),paths=paths,
        components=dict(schemas=components,securitySchemes={
            'humanBearer':dict(type='http',scheme='bearer'),
            'serviceBearer':dict(type='http',scheme='bearer'),
            'csrfToken':dict(type='apiKey',**{'in':'header'},name='X-CSRF-Token')}))
    return {'command.schema.json':schema,'command.openapi.json':api}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    for name,value in build().items():
        if args.check:
            assert (HERE/name).read_bytes()==encoded(value),name
        else:
            (HERE/name).write_bytes(encoded(value))
