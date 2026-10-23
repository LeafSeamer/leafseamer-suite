"""生成失败保护重新关闭候选，保留94表历史布局。"""
import argparse,json
from pathlib import Path
import build_failure_protection as F
HERE=Path(__file__).resolve().parent
VERSION='failure-protection-retry/0.1.0-draft.1'
SOURCES=F.SOURCES+[HERE/'build_protection_retry.py',HERE/'protection-retry.sql']
def schema():
    def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
    ident=dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+(?![\s\S])')
    defs={'RetryIntent':obj(contract_version={'const':VERSION},root_plan_id=ident,previous_plan_id=ident,request_epoch=ident,
        actor=obj(principal_id=ident),idempotency_key=ident,reason={'const':'proof_invalidated'}),
        'RetryResult':obj(contract_version={'const':VERSION},root_plan_id=ident,plan_id=ident,attempt_index=dict(type='integer',minimum=1,maximum=16),
            actions_replayed={'const':False},resources_cleared={'const':False},budget_released={'const':False})}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$defs':defs,'not':{}}
def schema_bytes():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
def build():
    sql=F.build().decode()
    changes={
      " CHECK((source_plan IS NOT NULL)+(preparation_plan IS NOT NULL)+(arm_exit_plan IS NOT NULL)+(failure_plan IS NOT NULL)=1),\n CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan,failure_plan)=plan_id)":
      " retry_plan TEXT UNIQUE REFERENCES sr_attempt(plan_id) DEFERRABLE INITIALLY DEFERRED,\n CHECK((source_plan IS NOT NULL)+(preparation_plan IS NOT NULL)+(arm_exit_plan IS NOT NULL)+(failure_plan IS NOT NULL)+(retry_plan IS NOT NULL)=1),\n CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan,failure_plan,retry_plan)=plan_id)",
      "VALUES(NEW.plan_id,NEW.plan_id,NULL,NULL,NULL)":"VALUES(NEW.plan_id,NEW.plan_id,NULL,NULL,NULL,NULL)",
      "VALUES(NEW.plan_id,NULL,NEW.plan_id,NULL,NULL)":"VALUES(NEW.plan_id,NULL,NEW.plan_id,NULL,NULL,NULL)",
      "VALUES(NEW.plan_id,NULL,NULL,NEW.plan_id,NULL)":"VALUES(NEW.plan_id,NULL,NULL,NEW.plan_id,NULL,NULL)",
      "VALUES(NEW.plan_id,NULL,NULL,NULL,NEW.plan_id)":"VALUES(NEW.plan_id,NULL,NULL,NULL,NEW.plan_id,NULL)"
    }
    for old,new in changes.items():assert sql.count(old)==1,old;sql=sql.replace(old,new,1)
    sql+='\n'+(HERE/'protection-retry.sql').read_text(encoding='utf-8')
    for table in ('sr_attempt','sr_target','sr_commit'):
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_protection_retry'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,raw in [('seamer-protection-retry.sql',build()),('protection-retry.schema.json',schema_bytes())]:
        if a.check:assert (HERE/name).read_bytes()==raw,'生成漂移:'+name
        else:(HERE/name).write_bytes(raw)
