"""普通设备关闭的完整日志与ACK，不要求伪造认证故障。"""
import argparse,copy,json,re
import build_authorization_close_ack as A
import build_recovery_close_choice as R
HERE=A.HERE
def originals():
    trigger=re.findall(r'CREATE TRIGGER ij_domain_seal\b.*?\nEND;',A.sql().decode(),re.S);view=re.findall(r'CREATE VIEW gr_valid_target\b.*?;',R.sql().decode(),re.S)
    assert len(trigger)==len(view)==1;return dict(ij_domain_seal=trigger[0],gr_valid_target=view[0])
def schema():
    defs=copy.deepcopy(A.schema()['$defs']);defs['ClockCloseBody']['properties']['reason']={'$ref':'#/$defs/Id'}
    dispatch=defs.pop('ClockCloseDispatch');dispatch['properties']['format_version']={'const':'gate-close-dispatch/0.1.0-draft.1'}
    dispatch['properties']['close_ref']=dispatch['properties'].pop('protection_ref');dispatch['required']=['close_ref' if s=='protection_ref' else s for s in dispatch['required']]
    ack=defs.pop('ClockCloseAcknowledgement');ack['properties']['format_version']={'const':'gate-close-ack/0.1.0-draft.1'}
    defs.update(GateCloseDispatch=dispatch,GateCloseAcknowledgement=ack)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/contracts/c04-lifecycle/gate-close.schema.json','$defs':defs,'x-approved':False}
def sql():
    old=originals();marker="(f.domain_kind='handshake' AND NEW.disposition='applied'";assert old['ij_domain_seal'].count(marker)==1
    extra="(f.domain_kind='gate_close' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM gate_close_dispatch d WHERE d.close_id=f.domain_id AND d.frame_id=f.frame_id AND d.selected_tick=NEW.committed_tick)) OR\n (f.domain_kind='gate_close_ack' AND EXISTS(SELECT 1 FROM gate_close_ack a WHERE a.ack_id=f.domain_id AND a.frame_id=f.frame_id AND a.disposition=NEW.disposition AND a.received_tick=NEW.committed_tick)) OR\n "
    return ('DROP TRIGGER ij_domain_seal;\n'+old['ij_domain_seal'].replace(marker,extra+marker)+'\nDROP VIEW gr_valid_target;\n'+old['gr_valid_target'].replace('CREATE VIEW gr_valid_target','CREATE VIEW gc_base_gr_valid_target',1)+'\n'+(HERE/'gate-close.sql').read_text('utf-8')).encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,data in [('gate-close.schema.json',(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()),('gate-close-journal.sql',sql())]:
        path=HERE/name
        if a.check:assert path.read_bytes()==data
        else:path.write_bytes(data)
