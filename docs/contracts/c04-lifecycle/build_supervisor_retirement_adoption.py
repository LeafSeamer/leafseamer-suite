"""控制器出口完整启动绑定及监督退役采用的候选字段。"""
import argparse,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
SOURCE=HERE.parent/'df02-supervisor/retirement-source.schema.json';SUP=HERE.parent/'df02-supervisor/supervisor.schema.json';ENC=HERE.parent/'c08-controller/encoding-authority.schema.json'
SID='https://leafseamer.invalid/contracts/c04-lifecycle/supervisor-retirement-adoption.schema.json'
def external(path,name):return {'$ref':json.loads(path.read_bytes())['$id']+'#/$defs/'+name}
def obj(p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def schema():
    ident=external(SUP,'Id');digest=external(SUP,'Digest');ref=external(ENC,'Ref');binding=external(ENC,'Binding')
    runtime=obj(dict(format_version={'const':'runtime-exit-binding/0.1.0-draft.1'},binding_id=ident,revision={'const':'1'},binding=binding,source=external(SOURCE,'SourceIdentity'),intent=external(SUP,'ExtensionLaunchIntent'),admission_receipt=external(SUP,'AdmissionReceipt'),authorization_evidence_ref=ref,binding_digest=digest))
    adopted=obj(dict(format_version={'const':'supervisor-retirement-adoption/0.1.0-draft.1'},adoption_id=ident,revision={'const':'1'},binding=binding,runtime_binding_ref=ref,source_bundle=external(SOURCE,'Bundle'),adoption_digest=digest))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':{'RuntimeExitBinding':runtime,'RetirementAdoption':adopted}}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'supervisor-retirement-adoption.schema.json'
    if a.check:assert target.read_bytes()==encoded()
    else:target.write_bytes(encoded())
