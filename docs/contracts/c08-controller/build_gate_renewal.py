"""生成独立换闸屏障候选；仅设计资料，不执行迁移或设备I/O。"""
import argparse,copy,json
from pathlib import Path
import build_ownership_storage as O
import build_scoped_gate as S
import build_layout as L
import build_control_storage as C
HERE=Path(__file__).resolve().parent
VERSION='ipc/0.10.0-gate-renewal-draft.1'
TABLES=('gf_request','gf_ack','gf_commit','gf_revocation')
SOURCES=O.SOURCES+[HERE/'build_gate_renewal.py',HERE/'gate-renewal.sql']

def sql():
    v=O.build().decode()
    v=L.replace(v,'barrier_id TEXT NOT NULL REFERENCES cu_ack(barrier_id),',
      'barrier_id TEXT NOT NULL, control_barrier_id TEXT REFERENCES cu_ack(barrier_id),\n renewal_id TEXT REFERENCES gf_commit(request_id) DEFERRABLE INITIALLY DEFERRED,',1)
    v=L.replace(v,"UNIQUE(exit_id,record_revision), CHECK((phase='ready')=(ready_id IS NOT NULL))",
      "UNIQUE(exit_id,record_revision), CHECK((phase='ready')=(ready_id IS NOT NULL)),\n CHECK((control_barrier_id IS barrier_id AND renewal_id IS NULL) OR (renewal_id IS barrier_id AND control_barrier_id IS NULL))",1)
    old="SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cu_ack a JOIN cu_delivery d USING(barrier_id) WHERE a.barrier_id=NEW.barrier_id AND d.exit_id=NEW.exit_id\n AND a.gate_revision<=NEW.gate_revision) THEN RAISE(ABORT,'open_gate_barrier') END;"
    new="""SELECT CASE WHEN NEW.control_barrier_id IS NOT NULL AND (NOT EXISTS(
 SELECT 1 FROM cu_ack a JOIN cu_delivery d USING(barrier_id) WHERE a.barrier_id=NEW.control_barrier_id
 AND d.exit_id=NEW.exit_id AND a.gate_revision=NEW.gate_revision)
 OR (NEW.phase='fenced' AND EXISTS(SELECT 1 FROM go_gate p WHERE p.phase='fenced' AND p.control_barrier_id=NEW.control_barrier_id)))
 THEN RAISE(ABORT,'open_gate_barrier') END;"""
    v=L.replace(v,old,new,1)
    # 普通开放仍需原全部条件；这里只增加当前换闸证据条件。
    v=L.replace(v,"WHERE c.pending_operation_id IS NULL AND g.phase='fenced'", "WHERE (g.renewal_id IS NULL OR EXISTS(SELECT 1 FROM gf_valid_fence f WHERE f.request_id=g.renewal_id)) AND c.pending_operation_id IS NULL AND g.phase='fenced'",1)
    v=L.replace(v,"'exit','ownership'))","'exit','ownership','gate_fence'))",1)
    v+='\n'+(HERE/'gate-renewal.sql').read_text(encoding='utf-8')
    v=L.replace(v,'@GF_SUCCESSOR@',C.successor("coalesce((SELECT max(revision) FROM go_hazard WHERE device_id=r.device_id),'00000000000000000000')"),1)
    for t in TABLES:
        for action,suffix in [('UPDATE','u'),('DELETE','d')]:
            v+=f"\nCREATE TRIGGER {t}_{suffix} BEFORE {action} ON {t} BEGIN SELECT RAISE(ABORT,'immutable_gate_fence'); END;\n"
    return v.encode()

def ipc():
    s=S.ipc(S.schema());s['$id']='https://leafseamer.invalid/design/c08-controller/gate-renewal-ipc.schema.json';s['title']=VERSION
    d=s['$defs'];r=lambda n:S.ref('SG__'+n)
    d['GF__Request']=S.obj(request_id=r('Id'),binding=r('Binding'),control_authority_ref=r('Ref'),
      before_gate_ref=S.null(r('Ref')),close_ack_ref=r('Ref'),target_gate_revision=r('Counter'),gate_token=r('Id'),
      selected_tick_ns=r('Counter'),expires_tick_ns=r('Counter'),lease_until_tick_ns=r('Counter'),request_digest=r('Digest'))
    d['GF__Ack']=S.obj(request_id=r('Id'),request_digest=r('Digest'),binding=r('Binding'),
      gate_revision=r('Counter'),gate_token=r('Id'),effective_tick_ns=r('Counter'),state={'const':'fenced'})
    for name,base,body in [('GATE_FENCE','S9__FENCE','GF__Request'),('GATE_FENCE_ACK','S9__FENCE_ACK','GF__Ack')]:
        frame=copy.deepcopy(d[base]);frame['properties']['type']={'const':name};frame['properties']['body']=S.ref(body)
        d['GF__'+name]=frame;s['oneOf'].append(S.ref('GF__'+name))
    for branch in s['oneOf']:d[branch['$ref'].split('/')[-1]]['properties']['ipc_version']={'const':VERSION}
    d['S9__HELLOBody']['properties']['supported_ipc_versions']['items']={'const':VERSION}
    d['S9__HELLO_ACKBody']['properties']['selected_ipc_version']={'const':VERSION}
    for n,k in [('S9__HELLOBody','supported_features'),('S9__HELLO_ACKBody','selected_features')]:
        d[n]['properties'][k]['allOf'].append({'contains':{'const':'fresh_gate_fence'}})
    return s

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,data in [('controller-gate-renewal.sql',sql()),('gate-renewal-ipc.schema.json',S.encoded(ipc()))]:
        path=HERE/name
        if a.check:assert path.read_bytes()==data,'生成漂移:'+name
        else:path.write_bytes(data)
