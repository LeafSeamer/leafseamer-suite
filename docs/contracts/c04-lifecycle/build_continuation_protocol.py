"""继续运行内部HTTP候选；复用不可变原件，生成封闭Schema和两份OpenAPI。"""
import argparse,copy,json
from pathlib import Path
import build_continuation as B
HERE=Path(__file__).resolve().parent
VERSION='run-continuation-http/0.1.0-draft.1'
SID='https://leafseamer.invalid/design/c04-lifecycle/continuation-protocol.schema.json'
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def ref(n):return {'$ref':'#/$defs/'+n}
def nullable(n):return {'oneOf':[ref(n),{'type':'null'}]}
def array(n,maximum,minimum=0):return dict(type='array',items=ref(n),minItems=minimum,maxItems=maximum,uniqueItems=True)
def raw(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
ROUTES=[
 ('controller','','issueContinuation','IssueInput','ControllerRecord','automation.prepare','origin','lookup-only-after-uncertainty','201'),
 ('controller','/lookup','lookupControllerContinuation','LookupInput','ControllerLookup','automation.prepare.read','origin','read-only','200'),
 ('seamer','','registerContinuation','IssueInput','SeamerRecord','automation.continuation.manage','origin','lookup-only-after-uncertainty','201'),
 ('seamer','/lookup','lookupSeamerContinuation','LookupInput','SeamerLookup','automation.continuation.read','origin','read-only','200'),
 ('seamer','/receipts','observeContinuationReceipt','ReceiptInput','ReceiptAck','automation.continuation.notify','controller','same-original-observation-only','201'),
 ('seamer','/adoptions','adoptContinuation','AdoptionInput','SeamerRecord','automation.continuation.manage','origin','lookup-only-after-uncertainty','201'),
 ('seamer','/finish','finishContinuation','FinishInput','SeamerRecord','automation.continuation.manage','origin','lookup-only-after-uncertainty','201'),
 ('seamer','/withdrawals','observeContinuationWithdrawal','WithdrawalNotice','WithdrawalAck','automation.continuation.protect','controller','same-identity-monotonic-protection-only','202')]

def build():
    d=copy.deepcopy(B.schema()['$defs']);ident=d['Request']['properties']['transfer_id'];sha=d['Ref']['properties']['digest']
    d['TransferIdentity']=obj(target_scope=ref('Scope'),origin_scope=ref('Scope'),transfer_id=ident,request_digest=sha)
    ver={'const':VERSION}
    d['IssueInput']=obj(protocol_version=ver,target_scope=ref('Scope'),request=ref('Request'))
    d['LookupInput']=obj(protocol_version=ver,identity=ref('TransferIdentity'))
    d['ReceiptInput']=obj(protocol_version=ver,target_scope=ref('Scope'),receipt=ref('Receipt'))
    d['AdoptionInput']=obj(protocol_version=ver,target_scope=ref('Scope'),adoption=ref('Adoption'))
    d['FinishInput']=obj(protocol_version=ver,identity=ref('TransferIdentity'),adoption_ref=ref('Ref'))
    # commit_digest只绑定旧commit_body；不能冒充整份transition_commit摘要。
    d['FinishRecord']=obj(commit_id=ident,execution_id=ident,adoption_digest=sha,commit_body_digest=sha)
    d['ControllerRecord']=obj(protocol_version=ver,request=ref('Request'),receipt=ref('Receipt'),qualification={'const':'not_asserted'})
    d['SeamerRecord']=obj(protocol_version=ver,request=ref('Request'),receipts=array('Receipt',32),
        adoption=nullable('Adoption'),finish=nullable('FinishRecord'),qualification={'const':'not_asserted'})
    d['SeamerRecord']['allOf']=[{'if':{'properties':{'adoption':{'type':'null'}}},'then':{'properties':{'finish':{'type':'null'}}}}]
    for domain in ('Controller','Seamer'):
        d[domain+'Lookup']={'oneOf':[obj(state={'const':'found'},record=ref(domain+'Record')),
            obj(state={'enum':['not_found','indeterminate']},record={'type':'null'})]}
    d['WithdrawalNotice']=obj(protocol_version=ver,identity=ref('TransferIdentity'),controller_scope=ref('Scope'),
        receipt_ref=ref('Ref'),revocation_ref=ref('Ref'),notice_digest=sha)
    d['WithdrawalAck']=obj(protocol_version=ver,identity=ref('TransferIdentity'),controller_scope=ref('Scope'),notice_digest=sha,
        protection_plan_id=ident,receipt_state={'const':'recorded'},protection_completion={'const':'not_asserted'})
    d['ReceiptAck']=obj(protocol_version=ver,identity=ref('TransferIdentity'),controller_scope=ref('Scope'),receipt_ref=ref('Ref'),
        receipt_state={'const':'recorded'},activation={'const':'not_asserted'})
    d['CommandGrantBinding']=obj(origin_scope=ref('Scope'),run_id=ident,generation=d['Request']['properties']['generation'],
        execution_id=ident,step_id=ident,submission_id=ident,device_id=ident,transfer_ref=ref('Ref'),
        adoption_ref=ref('Ref'),receipt_ref=ref('Ref'),grant_ref=ref('Ref'),plan_ref=ref('Ref'))
    d['ProtocolError']=obj(code={'enum':['invalid','unauthenticated','forbidden','conflict','capacity','unavailable','version']},request_id=ident)
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'title':VERSION,'x-approved':False,'not':{},'$defs':d}
    def project(value):
        if isinstance(value,list):return [project(x) for x in value]
        if not isinstance(value,dict):return value
        return {k:('#/components/schemas/'+v.split('/')[-1] if k=='$ref' else copy.deepcopy(v) if k in ('const','enum') else project(v)) for k,v in value.items()}
    outputs={'continuation-protocol.schema.json':schema}
    content=lambda n:{'application/json':{'schema':{'$ref':'#/components/schemas/'+n}}}
    for domain in ('controller','seamer'):
        paths={}
        for dom,suffix,operation,request,response,permission,owner,retry,created in ROUTES:
            if dom!=domain:continue
            responses={code:dict(description='已持久记录或同一原件；不证明当前可执行或设备完成',content=content(response)) for code in sorted({'200',created})}
            for code in ('400','401','403','409','413','422','429','503'):
                responses[code]=dict(description='无成功原件证明；不允许换身份重做',content=content('ProtocolError'))
            for value in responses.values():value['headers']={'Cache-Control':dict(required=True,schema={'const':'no-store'})}
            paths['/internal/automation/continuations'+suffix]={'post':dict(operationId=operation,security=[{'InternalMTLS':[]}],
                parameters=[dict(name='X-LeafSeamer-Contract',**{'in':'header'},required=True,schema={'const':VERSION})],
                requestBody=dict(required=True,content=content(request)),responses=responses,
                **{'x-required-permission':permission,'x-required-peer-role':owner,'x-retry-policy':retry,
                   'x-max-request-jcs-bytes':270336 if request=='IssueInput' else 20480,'x-max-response-jcs-bytes':1048576})}
        outputs['continuation-'+domain+'.openapi.json']=dict(openapi='3.1.1',info=dict(title='继续运行'+domain+'内部候选',version=VERSION),
            **{'x-approved':False},paths=paths,components=dict(schemas=project(d),securitySchemes={'InternalMTLS':dict(type='mutualTLS')}))
    return outputs

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check:assert (HERE/name).read_bytes()==raw(value),name
        else:(HERE/name).write_bytes(raw(value))
