"""恢复关闭依据二选一的附属布局；保留既有ACK存储及其不可变原件。"""
import argparse,json,re
import build_authorization_close_ack as A
import build_retired_close_set as R
HERE=A.HERE;SID='https://leafseamer.invalid/contracts/c04-lifecycle/recovery-close-choice.schema.json'
NAMES=('go_valid_recovery','authorization_base_go_valid_recovery','pd_base_go_valid_recovery','go_recovery_seal','pd_recovery_guard','ij_base_go_ready_candidate')
def originals():
    base=A.B.B.build().decode();ack=A.sql().decode();result={}
    for name in NAMES:
        source=ack if name in ('go_valid_recovery','authorization_base_go_valid_recovery') else base
        kind='TRIGGER' if name in ('go_recovery_seal','pd_recovery_guard') else 'VIEW'
        pattern=rf'CREATE {kind} {name}\b.*?'+(r'\nEND;' if kind=='TRIGGER' else ';')
        found=re.findall(pattern,source,re.S);assert len(found)==1,name;result[name]=found[0]
    return result
def sql():
    old=originals();ready=old['ij_base_go_ready_candidate']
    marker='go_recovery_target t JOIN go_recovery_commit rk';assert ready.count(marker)==1
    ready=ready.replace(marker,'gr_valid_target t JOIN go_valid_recovery rk')
    return ('\n'.join('DROP '+('TRIGGER' if 'CREATE TRIGGER' in s else 'VIEW')+' '+n+';' for n,s in old.items())+'\n'+(HERE/'recovery-close-choice.sql').read_text('utf-8')+'\n'+ready+'\n').encode()
def schema():
    B=R.B;ref=B.external(B.ENC,'Ref');ident=B.external(B.SUP,'Id');digest=B.external(B.SUP,'Digest')
    ack=B.obj(dict(kind={'const':'worker_ack'},close_ref=ref,ack_ref=ref,preparation_closure_ref=ref))
    retired=B.obj(dict(kind={'const':'supervisor_retired'},close_ref=ref,retired_completion_ref=ref,writer_exit_id=ident))
    receipt=B.obj(dict(format_version={'const':'recovery-close-choice/0.1.0-draft.1'},recovery_id=ident,revision={'const':'1'},binding=B.external(B.ENC,'Binding'),snapshot_ref=ref,provider_ref=ref,selected_tick_ns={'type':'string','pattern':'^(0|[1-9][0-9]{0,19})$'},targets={'type':'array','minItems':1,'maxItems':256,'items':{'oneOf':[ack,retired]}},recovery_digest=digest))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':{'RecoveryCloseChoice':receipt}}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,raw in [('recovery-close-choice-layout.sql',sql()),('recovery-close-choice.schema.json',(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode())]:
        target=HERE/name
        if a.check:assert target.read_bytes()==raw,name
        else:target.write_bytes(raw)
