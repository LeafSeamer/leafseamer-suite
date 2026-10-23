"""共享消息与准备拒绝候选的唯一局部定义；不生成运行服务。"""
import argparse, copy, json
import build_encoding_release as E
HERE=E.HERE;S=E.S;obj=S.obj;ref=S.ref
VERSION='ipc/0.13.0-journal-draft.1'
FEATURES=['shared_direction_journal','terminal_volatile_close','prepare_deny_before_release']
SID='https://leafseamer.invalid/design/c08-controller/ipc-journal.schema.json'
IID='https://leafseamer.invalid/design/c08-controller/journal-ipc.schema.json'
# 方向与响应对象由协议逐项审阅；不能从名字的ACK/REJECTED后缀推导。
C2W=('HELLO_ACK OPEN_GATE DISPATCH REPORT_STORED FENCE QUERY_BARRIER CLOSE_GATE GUARD_INSTALL '
     'AUTH_FENCE TIME_FENCE RUN_FENCE ENCODE_PACKET PREPARE_PACKET_REJECTED RESEND_DISPATCH '
     'RESEND_REJECTED BARRIER_STORED CANCEL_FENCE CANCEL_GUARD ENCODE_CANCEL_PACKET '
     'CANCEL_PREPARE_REJECTED DISPATCH_CANCEL CANCEL_RESEND_REJECTED CANCEL_REPORT_STORED '
     'QUERY_CANCEL_EXECUTION GATE_FENCE RELEASE_ENCODING DENY_ENCODING').split()
W2C=('HELLO OPEN_GATE_ACK SEND_REPORT EVIDENCE_CANDIDATE FENCE_ACK CLOSE_GATE_ACK GUARD_ACK '
     'AUTH_FENCE_ACK TIME_FENCE_ACK RUN_FENCE_ACK PACKET_ENCODING_FAILED PREPARE_PACKET '
     'RESEND_REQUEST BARRIER_UNAVAILABLE CANCEL_FENCE_ACK CANCEL_GUARD_ACK PREPARE_CANCEL_PACKET '
     'CANCEL_ENCODING_FAILED CANCEL_RESEND_REQUEST CANCEL_SEND_REPORT CANCEL_EVIDENCE_CANDIDATE '
     'CANCEL_EXECUTION_STATUS GATE_FENCE_ACK RELEASE_ENCODING_ACK DENY_ENCODING_ACK').split()
REPLIES={
 'HELLO_ACK':['HELLO'],'OPEN_GATE_ACK':['OPEN_GATE'],'FENCE_ACK':['FENCE','QUERY_BARRIER'],
 'CLOSE_GATE_ACK':['CLOSE_GATE'],'GUARD_ACK':['GUARD_INSTALL'],
 'AUTH_FENCE_ACK':['AUTH_FENCE','QUERY_BARRIER'],'TIME_FENCE_ACK':['TIME_FENCE','QUERY_BARRIER'],
 'RUN_FENCE_ACK':['RUN_FENCE','QUERY_BARRIER'],'PREPARE_PACKET':['ENCODE_PACKET'],
 'PACKET_ENCODING_FAILED':['ENCODE_PACKET'],'PREPARE_PACKET_REJECTED':['PREPARE_PACKET'],
 'RESEND_DISPATCH':['RESEND_REQUEST'],'RESEND_REJECTED':['RESEND_REQUEST'],
 'BARRIER_UNAVAILABLE':['QUERY_BARRIER'],'CANCEL_FENCE_ACK':['CANCEL_FENCE','QUERY_BARRIER'],
 'CANCEL_GUARD_ACK':['CANCEL_GUARD'],'PREPARE_CANCEL_PACKET':['ENCODE_CANCEL_PACKET'],
 'CANCEL_ENCODING_FAILED':['ENCODE_CANCEL_PACKET'],'CANCEL_PREPARE_REJECTED':['PREPARE_CANCEL_PACKET'],
 'CANCEL_RESEND_REJECTED':['CANCEL_RESEND_REQUEST'],'CANCEL_EXECUTION_STATUS':['QUERY_CANCEL_EXECUTION'],
 'GATE_FENCE_ACK':['GATE_FENCE'],'RELEASE_ENCODING_ACK':['RELEASE_ENCODING'],
 'DENY_ENCODING_ACK':['DENY_ENCODING']}

def schema():
    d={n:copy.deepcopy(E.schema()['$defs'][n]) for n in ('Id','Counter','Digest','Ref','Scope','Binding')}
    d['Positive']={'allOf':[ref('Counter'),{'pattern':'^[1-9]'}]}
    d['DenyRequest']=obj(deny_id=ref('Id'),revision={'const':'1'},binding=ref('Binding'),prepare_id=ref('Id'),
      encoding_authorization_ref=ref('Ref'),encode_message_id=ref('Id'),encode_frame_digest=ref('Digest'),
      revocation_ref=ref('Ref'),selected_tick_ns=ref('Counter'),request_digest=ref('Digest'))
    d['DenyAck']=obj(deny_ref=ref('Ref'),binding=ref('Binding'),prepare_id=ref('Id'),
      deny_message_id=ref('Id'),deny_frame_digest=ref('Digest'),effective_tick_ns=ref('Counter'),
      state={'const':'denied'},future_use_denied={'const':True})
    d['FrameRecord']=obj(record_id=ref('Id'),session_ref=ref('Ref'),direction={'enum':['c2w','w2c']},
      sequence=ref('Positive'),message_id=ref('Id'),message_type={'enum':C2W+W2C},
      frame_digest=ref('Digest'),wire_digest=ref('Digest'),wire_length={'type':'integer','minimum':1},
      frame_object_ref=ref('Ref'),wire_object_ref=ref('Ref'),record_digest=ref('Digest'))
    d['EffectCommit']=obj(record_ref=ref('Ref'),disposition={'enum':['applied','historical','rejected']},
      domain_commit_refs={'type':'array','items':ref('Ref'),'minItems':1},audit_ref=ref('Ref'),
      reply_record_refs={'type':'array','items':ref('Ref')},committed_tick_ns=ref('Counter'))
    d['PreparationMember']=obj(prepare_id=ref('Id'),encoding_authorization_ref=ref('Ref'),writer_exit_id=ref('Id'),
      basis={'enum':['never_attempted','released','retired','deny_ack']},proof_ref=ref('Ref'))
    d['PreparationClosure']=obj(closure_id=ref('Id'),revision={'const':'1'},scope=ref('Scope'),
      operation_ref=ref('Ref'),selector_ref=ref('Ref'),registry_ref=ref('Ref'),prepare_head=ref('Counter'),
      members={'type':'array','items':ref('PreparationMember'),'maxItems':65536},closure_digest=ref('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'x-approved':False,
      'x-runtime-approved':False,'not':{},'$defs':d}

def build():
    local=schema();s=json.loads((HERE/'encoding-release-ipc.schema.json').read_bytes());d=s['$defs']
    s.update({'$id':IID,'title':VERSION,'x-approved':False,'x-runtime-approved':False})
    for n in ('Id','Counter','Positive','Digest','Ref','Scope','Binding','DenyRequest','DenyAck'):
        d['J__'+n]=S.rename(local['$defs'][n],lambda u:'#/$defs/J__'+u.split('/')[-1])
    for name,base,body in [('DENY_ENCODING','ER__RELEASE_ENCODING','DenyRequest'),
                           ('DENY_ENCODING_ACK','ER__RELEASE_ENCODING_ACK','DenyAck')]:
        f=copy.deepcopy(d[base]);f['properties']['type']={'const':name};f['properties']['body']=ref('J__'+body)
        d['J__'+name]=f;s['oneOf'].append(ref('J__'+name))
    manifest=[]
    for b in s['oneOf']:
        f=d[b['$ref'].split('/')[-1]];p=f['properties'];name=p['type']['const']
        assert (name in C2W)!=(name in W2C)
        p['ipc_version']={'const':VERSION};p['seq']=ref('J__Positive')
        p['journal_mode']={'const':'durable'};f['required'].append('journal_mode')
        if name in ('CLOSE_GATE','CLOSE_GATE_ACK'):
            p['journal_mode']={'enum':['durable','volatile_close']}
            p['seq']={'anyOf':[ref('J__Positive'),{'type':'null'}]}
            then={'properties':{'seq':{'type':'null'},'device_id':{'type':'null'}}}
            if name=='CLOSE_GATE':then['properties']['body']={'properties':{'scope':{'const':'controller'}}}
            f.setdefault('allOf',[]).append({'if':{'properties':{'journal_mode':{'const':'volatile_close'}}},
              'then':then,'else':{'properties':{'seq':ref('J__Positive')}}})
        f['x-direction']='c2w' if name in C2W else 'w2c'
        f['x-reply-to-types']=REPLIES.get(name,[])
        manifest.append({'type':name,'direction':f['x-direction'],'reply_to_types':REPLIES.get(name,[]),
          'schema_ref':b['$ref'],'volatile_allowed':name in ('CLOSE_GATE','CLOSE_GATE_ACK')})
    d['S9__HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['S9__HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for n,k in [('S9__HELLOBody','supported_features'),('S9__HELLO_ACKBody','selected_features')]:
        d[n]['properties'][k]['allOf'] += [{'contains':{'const':f}} for f in FEATURES]
    return {'ipc-journal.schema.json':local,'journal-ipc.schema.json':s,
      'ipc-journal-messages.json':{'version':VERSION,'approved':False,'messages':manifest}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for n,v in build().items():
        raw=S.encoded(v)
        if a.check:assert (HERE/n).read_bytes()==raw,'生成漂移:'+n
        else:(HERE/n).write_bytes(raw)
