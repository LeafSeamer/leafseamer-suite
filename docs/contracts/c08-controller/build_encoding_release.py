"""生成编码缓存释放契约及完整IPC候选，不实现运行服务。"""
import argparse,copy,json
import build_encoding_authority as E
S=E.S;HERE=E.HERE;obj=S.obj;ref=S.ref
VERSION='ipc/0.12.0-encoding-release-draft.1'
FEATURE='encoding_release_after_quiescence'
SID='https://leafseamer.invalid/design/c08-controller/encoding-release.schema.json'
IID='https://leafseamer.invalid/design/c08-controller/encoding-release-ipc.schema.json'

def schema():
    prior=E.schema()['$defs'];d={n:copy.deepcopy(prior[n]) for n in ('Id','Counter','Digest','Ref','Scope','Binding')}
    d['ReleaseRequest']=obj(release_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),prepare_id=ref('Id'),
      encoding_authorization_ref=ref('Ref'),encode_message_id=ref('Id'),encode_frame_digest=ref('Digest'),
      revocation_ref=ref('Ref'),selected_tick_ns=ref('Counter'),request_digest=ref('Digest'))
    d['ReleaseAck']=obj(release_ref=ref('Ref'),binding=ref('Binding'),prepare_id=ref('Id'),
      release_message_id=ref('Id'),release_frame_digest=ref('Digest'),disposed_tick_ns=ref('Counter'),
      state={'const':'released'},encoder_quiescent={'const':True},consumers_quiescent={'const':True},cache_empty={'const':True})
    d['ReleaseAdoption']=obj(adoption_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),prepare_id=ref('Id'),
      release_ref=ref('Ref'),ack_message_id=ref('Id'),ack_frame_digest=ref('Digest'),encoding_reservation_ref=ref('Ref'),
      reserved_bytes={'type':'integer','minimum':1,'maximum':65536},received_tick_ns=ref('Counter'),
      committed_tick_ns=ref('Counter'),adoption_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,'x-runtime-approved':False,'not':{},'$defs':d}

def ipc(local):
    s=json.loads((HERE/'encoding-authority-ipc.schema.json').read_bytes());s.update({'$id':IID,'title':VERSION});d=s['$defs']
    for n,v in local['$defs'].items():
        if n!='ReleaseAdoption':d['ER__'+n]=S.rename(v,lambda u:'#/$defs/ER__'+u.split('/')[-1])
    for name,base,body in [('RELEASE_ENCODING','S9__FENCE','ReleaseRequest'),('RELEASE_ENCODING_ACK','S9__FENCE_ACK','ReleaseAck')]:
        f=copy.deepcopy(d[base]);f['properties']['type']={'const':name};f['properties']['body']=ref('ER__'+body)
        f['properties']['seq']={'allOf':[ref('ER__Counter'),{'pattern':'^[1-9]'}]}
        d['ER__'+name]=f;s['oneOf'].append(ref('ER__'+name))
    for b in s['oneOf']:d[b['$ref'].split('/')[-1]]['properties']['ipc_version']={'const':VERSION}
    d['S9__HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['S9__HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for n,k in [('S9__HELLOBody','supported_features'),('S9__HELLO_ACKBody','selected_features')]:
        d[n]['properties'][k]['allOf'].append({'contains':{'const':FEATURE}})
    return s

def build():
    s=schema();return {'encoding-release.schema.json':s,'encoding-release-ipc.schema.json':ipc(s)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for n,v in build().items():
        raw=S.encoded(v);target=HERE/n
        if a.check:assert target.read_bytes()==raw,'生成漂移:'+n
        else:target.write_bytes(raw)
