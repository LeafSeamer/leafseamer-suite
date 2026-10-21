"""采集器独立IPC设计源；不启动进程或发包。"""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SID = 'https://leafseamer.invalid/design/df03-collector/collector.schema.json'
VERSION = 'time-collector/0.1.0-draft.1'
FEATURES = ['one_shot_poll', 'candidate_only', 'monotonic_stop']
spec = importlib.util.spec_from_file_location('time_projection', BASE/'df03-service/build_contracts.py')
projection = importlib.util.module_from_spec(spec); spec.loader.exec_module(projection)


def obj(**p): return dict(type='object', properties=p, required=list(p), additionalProperties=False)
def ref(n): return {'$ref': SID+'#/$defs/'+n}
def null(s): return {'anyOf': [s, {'type':'null'}]}
def arr(s, limit=256): return dict(type='array', items=s, maxItems=limit, uniqueItems=True)
def enum(*x): return {'enum': list(x)}
def encoded(v): return (json.dumps(v, ensure_ascii=False, indent=2)+'\n').encode()


def build():
    source = json.loads((BASE/'df03-reference/reference.schema.json').read_bytes())
    tr = lambda n: {'$ref': source['$id']+'#/$defs/'+n}
    d = {n:tr(n) for n in ('Id','Ref','UInt','Positive','Digest','Domain','Binding')}
    d['Channel'] = obj(channel_id=ref('Id'), domain=ref('Domain'), core_boot_id=ref('Id'),
        core_runtime_binding_ref=ref('Ref'), bootstrap_receipt_ref=ref('Ref'), role={'const':'time_provider'})
    d['Limits'] = obj(max_sources=dict(type='integer',minimum=1,maximum=4),
        max_outstanding=dict(type='integer',minimum=1,maximum=4),
        max_frame_bytes=dict(type='integer',minimum=4096,maximum=262144),
        max_blob_bytes=dict(type='integer',minimum=48,maximum=65536),
        minimum_poll_interval_ns=ref('Positive'),poll_lease_ns=ref('Positive'),capacity_profile_ref=ref('Ref'))
    d['Configuration'] = obj(config_id=ref('Id'),revision=ref('Positive'),binding=ref('Binding'),
        source=tr('Source'),profile=tr('Profile'),policy=tr('Policy'),approval=tr('Approval'),
        collector_artifact_ref=ref('Ref'),bootstrap_receipt_ref=ref('Ref'),stop_generation=ref('Positive'),
        limits=ref('Limits'),config_digest=ref('Digest'))
    d['PollIntent'] = obj(poll_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),config_ref=ref('Ref'),
        correlation_ref=ref('Ref'),endpoint_ref=ref('Ref'),issued_tick_ns=ref('UInt'),
        not_before_tick_ns=ref('UInt'),expires_tick_ns=ref('Positive'),stop_generation=ref('Positive'),poll_digest=ref('Digest'))
    d['BlobDescriptor'] = obj(content_ref=ref('Ref'),size=dict(type='integer',minimum=1,maximum=65536),
        purpose=enum('request','response','diagnostic'),owner=ref('Domain'),sensitive={'const':True},sealed_ref=ref('Ref'))
    evidence = ('request','exchange','authentication','error','era')
    models = ('Request','Exchange','AuthEvidence','ErrorEvidence','EraEvidence')
    d['Capture'] = obj(capture_id=ref('Id'),revision={'const':'1'},poll_ref=ref('Ref'),binding=ref('Binding'),
        reported_tick_ns=ref('UInt'),status=enum('candidate','failed','indeterminate'),
        **{n:null(tr(t)) for n,t in zip(evidence,models)},failure=null(tr('Failure')),
        blobs=arr(ref('BlobDescriptor'),3),capture_digest=ref('Digest'))
    d['Capture']['allOf'] = [
        {'if':{'properties':{'status':{'const':'candidate'}}},'then':{'properties':{
            **{n:tr(t) for n,t in zip(evidence,models)},'failure':{'type':'null'}}},
         'else':{'properties':{n:{'type':'null'} for n in evidence if n!='request'}}},
        {'if':{'properties':{'status':{'const':'failed'}}},'then':{'properties':{'failure':tr('Failure')}},
         'else':{'properties':{'failure':{'type':'null'}}}}]
    d['CommitReceipt'] = obj(receipt_id=ref('Id'),revision={'const':'1'},capture_ref=ref('Ref'),poll_ref=ref('Ref'),
        result=enum('published','rejected','failure_recorded'),record_ref=ref('Ref'),anchor_ref=null(ref('Ref')),
        receipt_digest=ref('Digest'))
    d['CommitReceipt']['allOf'] = [{'if':{'properties':{'result':{'const':'published'}}},
        'then':{'properties':{'anchor_ref':ref('Ref')}},'else':{'properties':{'anchor_ref':{'type':'null'}}}}]
    d['Stop'] = obj(stop_id=ref('Id'),revision={'const':'1'},config_ref=ref('Ref'),
        stop_generation=ref('Positive'),poll_refs=arr(ref('Ref'),4),stop_digest=ref('Digest'))
    features = {**arr(ref('Id'),8), 'allOf':[{'contains':{'const':f}} for f in FEATURES]}
    d['HELLOBody'] = obj(version={'const':VERSION},features=features)
    d['ACCEPTBody'] = obj(version={'const':VERSION},features=features)
    d['CONFIGUREBody'] = obj(configuration=ref('Configuration'))
    d['CONFIG_ACKBody'] = obj(config_ref=ref('Ref'),result=enum('configured','rejected'),
        reason=null(enum('binding','authority','capacity','stopped')))
    d['POLLBody'] = obj(poll=ref('PollIntent'))
    d['POLL_ACKBody'] = obj(poll_ref=ref('Ref'),result=enum('reserved','rejected'),
        reason=null(enum('binding','expired','capacity','interval','stopped','identity_conflict')))
    for n,success in [('CONFIG_ACKBody','configured'),('POLL_ACKBody','reserved')]:
        d[n]['allOf']=[{'if':{'properties':{'result':{'const':success}}},
            'then':{'properties':{'reason':{'type':'null'}}},'else':{'properties':{'reason':{'type':'string'}}}}]
    d['CAPTURE_REPORTBody'] = obj(capture=ref('Capture'))
    d['REPORT_STOREDBody'] = obj(receipt=ref('CommitReceipt'))
    d['QUERY_CAPTUREBody'] = obj(poll_ref=ref('Ref'))
    d['CAPTURE_STATUSBody'] = obj(poll_ref=ref('Ref'),state=enum('reserved','consumed','reported','cache_missing'),capture=null(ref('Capture')))
    d['CAPTURE_STATUSBody']['allOf']=[{'if':{'properties':{'state':{'const':'reported'}}},
        'then':{'properties':{'capture':ref('Capture')}},'else':{'properties':{'capture':{'type':'null'}}}}]
    d['QUERY_COMMITBody'] = obj(capture_ref=ref('Ref'))
    d['COMMIT_STATUSBody'] = obj(capture_ref=ref('Ref'),state=enum('known','not_found','unavailable'),receipt=null(ref('CommitReceipt')))
    d['COMMIT_STATUSBody']['allOf']=[{'if':{'properties':{'state':{'const':'known'}}},
        'then':{'properties':{'receipt':ref('CommitReceipt')}},'else':{'properties':{'receipt':{'type':'null'}}}}]
    d['STOPBody'] = obj(stop=ref('Stop'))
    d['STOP_ACKBody'] = obj(stop_ref=ref('Ref'),consumed_poll_refs=arr(ref('Ref'),4),closed_tick_ns=ref('UInt'))
    outbound = {'ACCEPT','CONFIGURE','POLL','REPORT_STORED','QUERY_CAPTURE','COMMIT_STATUS','STOP'}
    responses = {'ACCEPT','CONFIG_ACK','POLL_ACK','REPORT_STORED','CAPTURE_STATUS','COMMIT_STATUS','STOP_ACK'}
    names = ['HELLO','ACCEPT','CONFIGURE','CONFIG_ACK','POLL','POLL_ACK','CAPTURE_REPORT','REPORT_STORED',
             'QUERY_CAPTURE','CAPTURE_STATUS','QUERY_COMMIT','COMMIT_STATUS','STOP','STOP_ACK']
    for n in names:
        d[n] = obj(version={'const':VERSION},type={'const':n},channel=ref('Channel'),
            direction={'const':'core_to_collector' if n in outbound else 'collector_to_core'},
            message_id=ref('Id'),sequence=ref('Positive'),reply_to=ref('Id') if n in responses else {'type':'null'},body=ref(n+'Body'))
    root = {'$schema':source['$schema'],'$id':SID,'title':VERSION,'x-approved':False,'x-runtime-approved':False,
            '$defs':d,'oneOf':[ref(n) for n in names]}
    p = projection.Projection({source['$id']:source,SID:root},SID)
    result = p.document({k:v for k,v in root.items() if k!='$defs'},SID)
    # 显式提供领域入口别名；不能用短名把不同资源的Ref合并。
    for n in ('Channel','Limits','Configuration','PollIntent','BlobDescriptor','Capture','CommitReceipt','Stop'):
        result['$defs'][n] = p.project(ref(n),SID)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    output=encoded(build())
    if a.check: assert (HERE/'collector.schema.json').read_bytes()==output
    else: (HERE/'collector.schema.json').write_bytes(output)
