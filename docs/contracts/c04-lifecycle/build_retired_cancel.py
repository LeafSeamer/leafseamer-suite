"""跨域取消准备来源的独立候选；保留旧同域格式与一般准备守卫。"""
import argparse,copy,json,re
from pathlib import Path
import build_cancel_source as C
HERE=C.HERE;SQL=HERE.parent/'c08-controller/prepare-deny-storage.sql';ENC=HERE.parent/'c08-controller/encoding-authority.schema.json'
def schema():
    s=copy.deepcopy(C.schema());d=s['$defs'];ref=C.ref;obj=C.obj
    d['RetiredCancelEncodingId']=copy.deepcopy(json.loads(ENC.read_bytes())['$defs']['Id'])
    d['RetiredCancelStorageRef']=obj(id=dict(type='string',minLength=1,maxLength=256),revision={'const':'1'},digest=ref('S8__Digest'))
    d['RetiredCancelMember']=obj(prepare_id=ref('RetiredCancelEncodingId'),exit_id=ref('S8__Id'),authorization_id=ref('RetiredCancelEncodingId'),authorization_digest=ref('S8__Digest'),completion_ref=ref('RetiredCancelStorageRef'),adoption_ref=ref('RetiredCancelStorageRef'),revocation_ref=ref('RetiredCancelStorageRef'))
    d['RetiredCancelSource']=obj(format_version={'const':'retired-cancel-source/0.1.0-draft.1'},selection=ref('CancelPrepareSource'),retirements=dict(type='array',items=ref('RetiredCancelMember'),minItems=1,maxItems=4096,uniqueItems=True))
    s.update({'$id':'https://leafseamer.invalid/design/c04-lifecycle/retired-cancel.schema.json','title':'retired-cancel/0.1.0-draft.1'});return s
def original():return re.search(r'CREATE TRIGGER pd_cut_seal\b.*?\nEND;',SQL.read_text('utf-8'),re.S).group(0)
def trigger():
    old="WHERE m.cut_id=NEW.cut_id AND (r.revoked_tick>NEW.committed_tick OR k.committed_tick>NEW.committed_tick))"
    new="WHERE m.cut_id=NEW.cut_id AND (r.revoked_tick>NEW.committed_tick OR k.committed_tick>NEW.committed_tick)\n AND NOT EXISTS(SELECT 1 FROM crp_valid v WHERE v.cut_id=m.cut_id AND v.prepare_id=m.prepare_id))"
    v=original();assert v.count(old)==1;return v.replace(old,new)
def encoded():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,data in [('retired-cancel.schema.json',encoded()),('retired-cancel-seal.sql',(trigger()+'\n').encode())]:
        path=HERE/name
        if a.check:assert path.read_bytes()==data,'生成漂移:'+name
        else:path.write_bytes(data)
