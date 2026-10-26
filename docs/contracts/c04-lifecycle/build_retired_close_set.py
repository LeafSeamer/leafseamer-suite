"""跨运行域退役关闭完成集合；不伪造旧域时间或worker ACK。"""
import argparse,json
import build_supervisor_retirement_adoption as B
HERE=B.HERE
SID='https://leafseamer.invalid/contracts/c04-lifecycle/retired-close-set.schema.json'
def schema():
    ref=B.external(B.ENC,'Ref');ident=B.external(B.SUP,'Id');digest=B.external(B.SUP,'Digest')
    prep=B.obj(dict(prepare_id=ident,encoding_authorization_ref=ref,revocation_ref=ref,encoding_frame_ref=ref,basis={'const':'retired'}))
    target=B.obj(dict(binding=B.external(B.ENC,'Binding'),runtime_binding_ref=ref,retirement_adoption_ref=ref,close_ref=ref,cut_ref=ref,prepare_head={'type':'string','pattern':'^(0|[1-9][0-9]{0,19})$'},preparations={'type':'array','maxItems':4096,'items':prep}))
    value=B.obj(dict(format_version={'const':'retired-close-set/0.1.0-draft.1'},completion_id=ident,revision={'const':'1'},anchor_exit_id=ident,worker_identity_digest=digest,targets={'type':'array','minItems':1,'maxItems':256,'items':target},completion_digest=digest))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':{'RetiredCloseSet':value}}
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();target=HERE/'retired-close-set.schema.json'
    if a.check:assert target.read_bytes()==encoded()
    else:target.write_bytes(encoded())
