"""跨域保护只复用已核销旧出口，当前域关闭保持原协议。"""
import argparse,json
import build_snapshot_domain_order as B
HERE=B.HERE;SID='https://leafseamer.invalid/contracts/c04-lifecycle/domain-protection.schema.json'
def schema():
    S=B.B.R.B;defs={'ActiveProtection':{'$ref':'https://leafseamer.invalid/design/c04-lifecycle/final-authorization.schema.json#/$defs/ClockProtectionCommit'}}
    retired=B.B.schema()['$defs']['RecoveryCloseChoice']['properties']['targets']['items']['oneOf'][1]
    defs['DomainProtection']=S.obj(dict(format_version={'const':'domain-protection/0.1.0-draft.1'},protection_id=S.external(S.SUP,'Id'),revision={'const':'1'},active_protection={'$ref':'#/$defs/ActiveProtection'},retired={'type':'array','minItems':1,'maxItems':256,'items':retired},protection_digest=S.external(S.SUP,'Digest')))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':SID,'$defs':defs}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();data=(json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode();path=HERE/'domain-protection.schema.json'
    if a.check:assert path.read_bytes()==data
    else:path.write_bytes(data)
