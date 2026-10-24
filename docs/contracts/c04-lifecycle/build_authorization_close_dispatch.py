"""认证关闭日志的固定附属候选；不修改上游历史布局或解除最终签发阻断。"""
import argparse,json,re
import build_typed_encoding_path as B
HERE=B.HERE
SOURCES=list(dict.fromkeys(B.SOURCES+[HERE/'build_authorization_close_dispatch.py',HERE/'final-authorization.schema.json',HERE/'authorization-close-dispatch.sql']))
def original():
    matches=re.findall(r'CREATE TRIGGER ij_domain_seal BEFORE INSERT ON ij_commit BEGIN\n.*?\nEND;',B.build().decode(),re.S)
    assert len(matches)==1;return matches[0]
def sql():
    old=original();marker="(f.domain_kind='handshake' AND NEW.disposition='applied'"
    assert old.count(marker)==1
    added="(f.domain_kind='authentication_close' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM authorization_close_dispatch d WHERE d.close_id=f.domain_id AND d.frame_id=f.frame_id AND d.selected_tick=NEW.committed_tick)) OR\n "
    return ('DROP TRIGGER ij_domain_seal;\n'+old.replace(marker,added+marker)+'\n'+(HERE/'authorization-close-dispatch.sql').read_text('utf-8')).encode()
def schema():
    source=json.loads((HERE/'final-authorization.schema.json').read_bytes())['$defs'];defs={}
    def include(name):
        if name in defs:return
        defs[name]=source[name]
        def walk(v):
            if isinstance(v,dict):
                if '$ref' in v:include(v['$ref'].split('/')[-1])
                for x in v.values():walk(x)
            elif isinstance(v,list):
                for x in v:walk(x)
        walk(defs[name])
    for name in ('Id','Ref','Counter','Digest','ClockCloseTarget'):include(name)
    props=dict(format_version={'const':'authentication-close-dispatch/1'},dispatch_id={'$ref':'#/$defs/Id'},revision={'const':'1'},
        protection_ref={'$ref':'#/$defs/Ref'},close_id={'$ref':'#/$defs/Id'},target={'$ref':'#/$defs/ClockCloseTarget'},
        frame_ref={'$ref':'#/$defs/Ref'},wire_digest={'$ref':'#/$defs/Digest'},wire_bytes={'$ref':'#/$defs/Counter'},
        selected_tick_ns={'$ref':'#/$defs/Counter'},state={'const':'queued'},dispatch_digest={'$ref':'#/$defs/Digest'})
    defs['ClockCloseDispatch']=dict(type='object',properties=props,required=list(props),additionalProperties=False)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/authorization-close-dispatch.schema.json','x-approved':False,'not':{},'$defs':defs}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,raw in [('authorization-close-journal.sql',sql()),('authorization-close-dispatch.schema.json',(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode())]:
        path=HERE/name
        if a.check:assert path.read_bytes()==raw,name
        else:path.write_bytes(raw)
