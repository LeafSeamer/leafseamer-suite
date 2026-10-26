"""生成完整换闸原件及附属存储约束，不改变已批准IPC。"""
import argparse,copy,json
import build_gate_close as G
HERE=G.HERE
def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
def ref(n):return {'$ref':'#/$defs/'+n}
def schema():
    d=copy.deepcopy(G.schema()['$defs']);r=ref
    d['FenceOrigin']=obj(format_version={'const':'gate-fence-origin/0.1.0-draft.1'},request_id=r('Id'),request_ref=r('Ref'),close_ref=r('Ref'),close_ack_ref=r('Ref'),preparation_closure_ref=r('Ref'),control_state_ref=r('Ref'),safety_revision=r('Counter'),origin_digest=r('Digest'))
    d['FenceObservation']=obj(frame_ref=r('Ref'),observer_ref=r('Ref'),received_tick_ns=r('Counter'))
    d['FencedGateRecord']=obj(format_version={'const':'fenced-gate-record/0.1.0-draft.1'},gate_id=r('Id'),revision=r('Counter'),binding=r('Binding'),previous_gate_ref={'anyOf':[r('Ref'),{'type':'null'}]},request_ref=r('Ref'),ack_frame_ref=r('Ref'),gate_revision=r('Counter'),gate_token=r('Id'),barrier_id=r('Id'),phase={'const':'fenced'},lease_until_tick_ns=r('Counter'),committed_tick_ns=r('Counter'),record_digest=r('Digest'))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/contracts/c04-lifecycle/typed-gate-fence.schema.json','$defs':d,'x-approved':False}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'typed-gate-fence.schema.json';data=(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
    if a.check:assert path.read_bytes()==data
    else:path.write_bytes(data)
