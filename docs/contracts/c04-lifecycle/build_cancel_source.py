"""从当前公共命令与IPC类型图派生取消原件候选，不修改既有批准契约。"""
import argparse,copy,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
COMMAND=HERE/'command-contract.schema.json';CANCEL=HERE.parent/'c02-cancellation/cancellation.schema.json'
SOURCES=[Path(__file__),COMMAND,CANCEL]
def ref(name):return {'$ref':'#/$defs/'+name}
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def walk(v,fn):
    if isinstance(v,list):return [walk(x,fn) for x in v]
    if not isinstance(v,dict):return v
    return {k:fn(x) if k=='$ref' else walk(x,fn) for k,x in v.items()}
def schema():
    defs=copy.deepcopy(json.loads(COMMAND.read_bytes())['$defs']);old=json.loads(CANCEL.read_bytes())['$defs']
    for name,source in (('CancelCut','Cut'),('CancelPolicy','Policy')):
        defs[name]=walk(old[source],lambda r:'#/$defs/S8__'+r.split('/')[-1])
    defs['CancelContent']=obj(scope=ref('S8__Scope'),command_id=ref('S8__Id'),expected_state_ref=ref('S8__Ref'),reason=dict(type='string',maxLength=1024))
    defs['SocketRegistration']=obj(format_version={'const':'cancel-socket-registration/0.1.0-draft.1'},scope=ref('S8__Scope'),
        exit=ref('S8__Exit'),observer_ref=ref('S8__Ref'),registration_digest=ref('S8__Digest'))
    defs['CommandState']=ref('V__S0_State')
    roots=['CancelCut','CancelPolicy','CancelContent','SocketRegistration','CommandState','CancelReceipt','CancelOperation','TransmissionPermit','S8__DenySnapshot','S8__Packet','S9__TransportPacket']
    selected={}
    def include(name):
        if name in selected:return
        selected[name]=copy.deepcopy(defs[name])
        def visit(r):
            assert r.startswith('#/$defs/'),r
            include(r.split('/')[-1]);return r
        walk(defs[name],visit)
    for root in roots:include(root)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/cancel-source.schema.json',
      'title':'cancel-source/0.1.0-draft.1','x-approved':False,'not':{},'$defs':selected}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'cancel-source.schema.json'
    if a.check:assert target.read_bytes()==encoded(),'生成漂移'
    else:target.write_bytes(encoded())
