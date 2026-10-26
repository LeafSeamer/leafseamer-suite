"""关闭ACK的固定日志映射与当前资格候选；不修改既有历史制品。"""
import argparse,json,re
import build_authorization_close_dispatch as B
HERE=B.HERE
SOURCES=list(dict.fromkeys(B.SOURCES+[HERE/'build_authorization_close_ack.py',HERE/'authorization-close-ack.sql']))
def original():
    values=re.findall(r'CREATE TRIGGER ij_domain_seal BEFORE INSERT ON ij_commit BEGIN\n.*?\nEND;',B.sql().decode(),re.S)
    assert len(values)==1;return values[0]
def recovery():
    values=re.findall(r'CREATE VIEW go_valid_recovery AS.*?;',B.B.build().decode(),re.S)
    assert len(values)==1;return values[0]
def sql():
    trigger=original();marker="(f.domain_kind='handshake' AND NEW.disposition='applied'";assert trigger.count(marker)==1
    extra="(f.domain_kind='authentication_close_ack' AND EXISTS(SELECT 1 FROM authorization_close_ack a WHERE a.ack_id=f.domain_id AND a.frame_id=f.frame_id AND a.disposition=NEW.disposition AND a.received_tick=NEW.committed_tick)) OR\n "
    view=recovery().replace('CREATE VIEW go_valid_recovery AS','CREATE VIEW authorization_base_go_valid_recovery AS',1)
    return ('DROP TRIGGER ij_domain_seal;\n'+trigger.replace(marker,extra+marker)+'\nDROP VIEW go_valid_recovery;\n'+view+'\n'+(HERE/'authorization-close-ack.sql').read_text('utf-8')).encode()
def schema():
    defs=B.schema()['$defs'];ref=lambda n:{'$ref':'#/$defs/'+n}
    props=dict(format_version={'const':'authentication-close-ack/1'},ack_id=ref('Id'),revision={'const':'1'},close_id=ref('Id'),
        dispatch_ref=ref('Ref'),frame_ref=ref('Ref'),observer_ref=ref('Ref'),wire_digest=ref('Digest'),received_tick_ns=ref('Counter'),
        disposition={'enum':['applied','historical']},ack_digest=ref('Digest'))
    defs['ClockCloseAcknowledgement']=dict(type='object',properties=props,required=list(props),additionalProperties=False)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/authorization-close-ack.schema.json','x-approved':False,'not':{},'$defs':defs}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,raw in [('authorization-close-ack-journal.sql',sql()),('authorization-close-ack.schema.json',(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode())]:
        path=HERE/name
        if a.check:assert path.read_bytes()==raw,name
        else:path.write_bytes(raw)
