"""生成失败布防退出候选；旧83表产物保持独立。"""
import argparse,json
from pathlib import Path
import build_arm_storage as A
HERE=Path(__file__).resolve().parent
VERSION='arm-exit/0.1.0-draft.1'
SOURCES=A.SOURCES+[HERE/'build_arm_exit.py',HERE/'arm-exit.sql']
TABLES=('aa_stop','aa_attempt','aa_target','aa_attempt_commit','aa_exit','aa_exit_pin','aa_exit_commit')

def schema():
    def obj(**p):return dict(type='object',properties=p,required=list(p),additionalProperties=False)
    ident=dict(type='string',minLength=1,maxLength=128,pattern=r'^[A-Za-z0-9_.:-]+(?![\s\S])')
    u=dict(type='string',pattern=r'^(0|[1-9][0-9]{0,19})(?![\s\S])')
    digest=dict(type='string',pattern=r'^sha256:[0-9a-f]{64}(?![\s\S])')
    common=dict(contract_version={'const':VERSION},arm_operation_id=ident,request_epoch=ident,actor=obj(principal_id=ident),idempotency_key=ident)
    defs={'StopIntent':obj(**common,expected_run_revision=u,reason={'enum':['operator_cancel','preparation_failed','source_fault','authorization_lost','time_unqualified','storage_recovered']}),
      'RetryIntent':obj(**common,previous_plan_id=ident,reason={'const':'proof_invalidated'}),
      'ObservationPin':obj(target_id=ident,status_revision={'const':'1'},observation_digest=digest),
      'ExitResult':obj(contract_version={'const':VERSION},arm_operation_id=ident,run_id=ident,generation=u,plan_id=ident,
          run_revision=u,state={'const':'paused'},resources_cleared={'const':False},budget_released={'const':False},
          observations=dict(type='array',maxItems=256,uniqueItems=True,items={'$ref':'#/$defs/ObservationPin'}))}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/arm-exit.schema.json',
        'title':VERSION,'x-approved':False,'not':{},'$defs':defs}

def schema_bytes():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
def build():
    sql=A.build().decode()
    changes={
      " CHECK((source_plan=plan_id AND preparation_plan IS NULL) OR(preparation_plan=plan_id AND source_plan IS NULL)),\n CHECK((source_plan IS NULL)!=(preparation_plan IS NULL))":
      " arm_exit_plan TEXT UNIQUE REFERENCES aa_attempt(plan_id) DEFERRABLE INITIALLY DEFERRED,\n CHECK((source_plan IS NOT NULL)+(preparation_plan IS NOT NULL)+(arm_exit_plan IS NOT NULL)=1),\n CHECK(coalesce(source_plan,preparation_plan,arm_exit_plan)=plan_id)",
      "INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NEW.plan_id,NULL)":"INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NEW.plan_id,NULL,NULL)",
      "INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NEW.plan_id)":"INSERT INTO protection_plan_registry VALUES(NEW.plan_id,NULL,NEW.plan_id,NULL)",
      "FROM pq_plan p JOIN pq_commit k USING(plan_id)) GROUP BY run_id;":"FROM pq_plan p JOIN pq_commit k USING(plan_id)\n UNION ALL SELECT run_id,substr('00000000000000000000'||generation,-20) FROM aa_stop) GROUP BY run_id;"}
    for old,new in changes.items():assert sql.count(old)==1,old;sql=sql.replace(old,new,1)
    extension=(HERE/'arm-exit.sql').read_text(encoding='utf-8').replace('__NEXT__',A.Q.R.P.successor('NEW.revision_before'))
    sql+='\n'+extension
    for table in TABLES:
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_arm_exit'); END;\n"
    for table,fields in {'aa_stop':('generation','revision_before','revision_after','slot_revision'),'aa_exit':('generation','revision_before','revision_after','slot_revision')}.items():
        invalid=' OR '.join(f"length(NEW.{f}) NOT BETWEEN 1 AND 20 OR NEW.{f} GLOB '*[^0-9]*' OR (NEW.{f}!='0' AND substr(NEW.{f},1,1)='0') OR instr(NEW.{f},char(0))>0" for f in fields)
        sql+=f"\nCREATE TRIGGER {table}_u20 BEFORE INSERT ON {table} WHEN {invalid} BEGIN SELECT RAISE(ABORT,'arm_exit_u20'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    for name,raw in [('seamer-arm-exit.sql',build()),('arm-exit.schema.json',schema_bytes())]:
        if args.check:assert (HERE/name).read_bytes()==raw,'生成漂移:'+name
        else:(HERE/name).write_bytes(raw)
