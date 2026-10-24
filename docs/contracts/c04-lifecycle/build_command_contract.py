"""命令消费包：单一类型图派生公共OpenAPI与完整IPC，不修改旧版本。"""
import argparse,copy,hashlib,json
from pathlib import Path
import build_continuation_binding as B
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
VERSION='command-contract/0.1.0-draft.1'
SID='https://leafseamer.invalid/design/c04-lifecycle/command-contract.schema.json'
SOURCES=B.SOURCES+[Path(__file__),Path(B.__file__),BASE/'c02-admission/admission.openapi.json',BASE/'c02-command-view/command.openapi.json']
raw=B.raw;ref=B.ref
# 精确列出被归并的节点；不依据名字后缀猜测类型含义。
OVERRIDES={'A__S0_CommandRequest':'CommandRequest','A__S1_CommandRequest':'CommandRequest',
 'A__S0_CommandContent':'CommandContent','A__S1_AutomationOriginBinding':'AutomationOriginBinding',
 'A__S1_RunBinding':'RunBinding','V__S0_AutomationOriginBinding':'AutomationOriginBinding',
 'V__S3_AutomationOriginBinding':'AutomationOriginBinding','V__S0_RunBinding':'RunBinding','V__S3_RunBinding':'RunBinding',
 'A__S0_Scope':'Scope','A__S1_Scope':'Scope','A__S2_Scope':'Scope',
 'V__S0_Scope':'Scope','V__S1_Scope':'Scope','V__S2_Scope':'Scope','V__S3_Scope':'Scope','V__S4_Scope':'Scope',
 'V__S2_RequestKey':'RequestKey','V__S2_RequestIdentity':'RequestIdentity'}
EXPORTS={'RequestKey':'A__S0_RequestKey','RequestIdentity':'A__S0_RequestIdentity',
 'RequestAdjudication':'A__S0_RequestAdjudication','LookupResult':'A__S0_LookupResult','RejectRequest':'A__S0_RejectRequest',
 'CommandRead':'V__S0_CommandRead','CommandRecord':'V__S0_CommandRecord','CancelRequest':'V__S0_CancelRequest',
 'CancelReceipt':'V__S0_CancelReceipt','CancelLookup':'V__S0_CancelLookup','CancelOperation':'V__S0_CancelOperation',
 'EvidencePage':'V__S0_EvidencePage','EvidenceRecord':'V__S0_EvidenceRecord'}
def refs(v):
    if isinstance(v,list):return [r for x in v for r in refs(x)]
    if not isinstance(v,dict):return []
    return ([v['$ref']] if '$ref' in v else [])+[r for k,x in v.items() if k not in ('$ref','const','enum','examples') for r in refs(x)]
def import_api(api,prefix):
    def rename(uri):
        assert uri.startswith('#/components/schemas/'),uri
        return '#/$defs/'+prefix+uri.split('/')[-1]
    return B.walk(api,rename)
def build():
    prior=B.build();binding=prior['continuation-binding.schema.json'];ipc=prior['continuation-binding-ipc.schema.json']
    d=copy.deepcopy(ipc['$defs'])
    for n,v in binding['$defs'].items():
        if n in d:assert d[n]==v,n
        d[n]=copy.deepcopy(v)
    d['RunBinding']=ref('S2__RunBinding');d['Scope']=ref('CN__Scope');paths={};security={};operations=[]
    for prefix,path in zip(('A__','V__'),SOURCES[-2:]):
        source=json.loads(path.read_bytes());api=import_api(source,prefix)
        for n,v in api['components']['schemas'].items():assert prefix+n not in d;d[prefix+n]=v
        for n,v in api['components']['securitySchemes'].items():
            assert n not in security or security[n]==v;security[n]=v
        for path,item in api['paths'].items():
            assert path not in paths;paths[path]=item
            for method,op in item.items():
                operations.append(dict(path=path,method=method,operation_id=op['operationId']))
                headers=[p for p in op['parameters'] if p['in']=='header' and p['name']=='X-LeafSeamer-Contract'];assert len(headers)==1
                headers[0]['schema']={'const':VERSION};headers[0]['required']=True
                op['x-source-contract']=source['info']['version']
    for old,new in OVERRIDES.items():assert old in d;d[old]=ref(new)
    for n,target in EXPORTS.items():assert n not in d;d[n]=ref(target)
    # 单一类型图不承诺所有旧ID词法均已收敛；本包只做已批准绑定的精确同版归并。
    catalog=dict(binding,**{'$id':SID,'title':VERSION,'$defs':d})
    public_roots=list(dict.fromkeys(r.split('/')[-1] for r in refs(paths)))
    public_defs=B.closure(d,public_roots)
    to_api=lambda x:B.walk(x,lambda r:'#/components/schemas/'+r.split('/')[-1])
    api=dict(openapi='3.1.1',info=dict(title='完整公共命令消费契约候选',version=VERSION),
        paths=to_api(paths),components=dict(schemas=to_api(public_defs),securitySchemes=security),
        **{'x-approved':False,'x-canonical-schema':SID})
    wire={k:copy.deepcopy(v) for k,v in ipc.items() if k!='$defs'}
    wire['$id']=SID.replace('.schema.json','-ipc.schema.json')
    wire['oneOf']=[{'$ref':SID+r['$ref']} for r in ipc['oneOf']]
    outputs={'command-contract.schema.json':catalog,'command-contract.openapi.json':api,'command-contract-ipc.schema.json':wire}
    exports={n:SID+'#/$defs/'+n for n in [*prior['continuation-binding-manifest.json']['exports'],'RunBinding','Scope',*EXPORTS]}
    manifest=dict(contract_version=VERSION,approved=False,scope='command-api-and-ipc-only',canonical_schema=SID,
        ipc_version=B.IPC_VERSION,required_feature=B.FEATURE,exports=exports,operations=operations,
        generation_entrypoint='build_command_contract.py',runtime_codegen_executed=False,
        source_inputs={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES},
        artifacts={n:hashlib.sha256(raw(v)).hexdigest() for n,v in outputs.items()},
        storage_ready=False,final_admission_ready=False)
    outputs['command-contract-manifest.json']=manifest
    return outputs
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,value in build().items():
        if a.check:assert (HERE/name).read_bytes()==raw(value),name
        else:(HERE/name).write_bytes(raw(value))
