"""快照提交序号与受保护换域的内部候选，不依赖跨域tick排序。"""
import argparse,json,re
import build_recovery_close_choice as B
HERE=B.HERE;SID='https://leafseamer.invalid/contracts/c04-lifecycle/snapshot-domain-order.schema.json'
def original():
    values=re.findall(r'CREATE VIEW go_current_snapshot AS.*?;',B.A.B.B.build().decode(),re.S);assert len(values)==1;return values[0]
def schema():
    S=B.R.B;ref=S.external(S.ENC,'Ref');binding=S.external(S.ENC,'Binding');ident=S.external(S.SUP,'Id');digest=S.external(S.SUP,'Digest');counter={'type':'string','pattern':'^(0|[1-9][0-9]{0,19})$'}
    transition=S.obj(dict(format_version={'const':'protected-domain-transition/0.1.0-draft.1'},transition_id=ident,revision={'const':'1'},before_control_ref=ref,after_control_ref=ref,new_clock_descriptor=S.external(S.SUP,'ClockDomainDescriptor'),provider_ref=ref,selected_tick_ns=counter,transition_digest=digest))
    order=S.obj(dict(format_version={'const':'snapshot-domain-order/0.1.0-draft.1'},binding=binding,snapshot_ref=ref,ordinal={'type':'string','pattern':'^[1-9][0-9]{0,19}$'}))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':{'ProtectedDomainTransition':transition,'SnapshotDomainOrder':order}}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();raw=(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode();target=HERE/'snapshot-domain-order.schema.json'
    if a.check:assert target.read_bytes()==raw
    else:target.write_bytes(raw)
