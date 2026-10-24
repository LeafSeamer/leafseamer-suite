"""从唯一命令类型图派生本地观察契约及完整Seamer接收布局。"""
import argparse
from pathlib import Path
import build_atomic_ingress as B
import build_command_contract as C
HERE=Path(__file__).resolve().parent
SOURCES=list(dict.fromkeys(B.SOURCES+C.SOURCES+[Path(__file__),HERE/'adjudication-receive.sql']))
def schema():
    defs=C.B.closure(C.build()['command-contract.schema.json']['$defs'],['RequestIdentity','LookupResult'])
    ref=lambda n:{'$ref':'#/$defs/'+n}
    ident=dict(type='string',minLength=1,maxLength=256,pattern=r'^[A-Za-z0-9_.:-]+$')
    observation=dict(type='object',additionalProperties=False,properties=dict(observation_id=ident,submission_id=ident,
      source=dict(enum=['create_response','lookup','transport_timeout','transport_error']),identity=ref('RequestIdentity'),
      result=dict(anyOf=[ref('LookupResult'),dict(type='null')])),required=['observation_id','submission_id','source','identity','result'])
    observation['allOf']=[
      {'if':{'properties':{'source':{'enum':['transport_timeout','transport_error']}}},'then':{'properties':{'result':{'type':'null'}}},'else':{'properties':{'result':ref('LookupResult')}}},
      {'if':{'properties':{'source':{'const':'create_response'}}},'then':{'properties':{'result':{'properties':{'state':{'const':'found'}}}}}}]
    defs['Observation']=observation
    return dict(**{'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/adjudication-receive.schema.json','$defs':defs,'$ref':'#/$defs/Observation'},title='adjudication-receive/0.1.0-draft.1',**{'x-approved':False,'x-boundary':'trusted-local-observer-not-public-http'})
def build():
    sql=B.B.amend(B.build().decode(),'CREATE TABLE submission_adjudication (',[(
      ' adjudication_id TEXT PRIMARY KEY NOT NULL,',
      ' observation_id TEXT NOT NULL UNIQUE REFERENCES sa_observation(observation_id) DEFERRABLE INITIALLY DEFERRED,\n adjudication_id TEXT PRIMARY KEY NOT NULL,')])
    return (sql+'\n'+(HERE/'adjudication-receive.sql').read_text(encoding='utf-8')).encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,data in [('seamer-adjudication-receive.sql',build()),('adjudication-receive.schema.json',C.raw(schema()))]:
        path=HERE/name
        if a.check:assert path.read_bytes()==data,name
        else:path.write_bytes(data)
