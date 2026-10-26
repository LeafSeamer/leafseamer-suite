"""提供者同库采用候选；以独立模块名生成设计Schema。"""
import argparse,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
SID='https://leafseamer.invalid/contracts/df03-provider/adoption.schema.json'
PROVIDER=json.loads((BASE/'df02-supervisor/time-provider-source.schema.json').read_bytes())
CHANNEL=json.loads((BASE/'df03-collector/channel-v02.schema.json').read_bytes())
TIME=json.loads((BASE/'df03-reference/reference.schema.json').read_bytes())
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def schema():
    r=lambda n:{'$ref':TIME['$id']+'#/$defs/'+n}
    adoption=obj(format_version={'const':'time-provider-adoption/0.1.0-draft.1'},adoption_id=r('Id'),revision={'const':'1'},
        runtime={'$ref':PROVIDER['$id']},channel={'$ref':CHANNEL['$id']+'#/$defs/Channel'},
        configuration={'$ref':CHANNEL['$id']+'#/$defs/Configuration'},bootstrap_state_ref=r('Ref'),source_slot_id=r('Id'),
        binding_storage_id=r('Id'),bootstrap_commit_id=r('Id'),interval_receipt_ref=r('Ref'),adoption_digest=r('Digest'))
    revoke=obj(format_version={'const':'time-provider-revocation/0.1.0-draft.1'},revocation_id=r('Id'),revision={'const':'1'},
        adoption_ref=r('Ref'),invalidation_ref=r('Ref'),cause_ref=r('Ref'),invalidation_commit_id=r('Id'),
        next_binding_storage_id=r('Id'),revocation_digest=r('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,
        '$defs':dict(Adoption=adoption,Revocation=revoke),'oneOf':[{'$ref':'#/$defs/Adoption'},{'$ref':'#/$defs/Revocation'}]}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'adoption.schema.json'
    if a.check:assert path.read_bytes()==encoded()
    else:path.write_bytes(encoded())
