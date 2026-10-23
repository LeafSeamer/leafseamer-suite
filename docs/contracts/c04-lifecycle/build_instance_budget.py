"""生成来源保护的独立实例分区与104表候选，不改变旧102表产物。"""
import argparse,json
from pathlib import Path
import build_recovery_budget as R
import build_arm_budget as A
HERE=Path(__file__).resolve().parent
VERSION='source-instance-budget/0.1.0-draft.1'
DIMENSIONS=R.DIMENSIONS
SOURCES=R.SOURCES+[HERE/'build_instance_budget.py',HERE/'instance-budget.sql']
def schema():
    old=A.schema()['$defs'];positive=old['Profile']['properties']['episodes'];ident=old['Profile']['properties']['profile_id'];sha=old['Binding']['properties']['profile_digest']
    defs={'Vector':old['Vector'],'Scope':old['Scope']}
    defs['PoolProfile']=A.obj(contract_version={'const':VERSION},profile_id=ident,scope={'$ref':'#/$defs/Scope'},purpose={'const':'simulation'},
        arm_profile_digest=sha,total_capacity={'$ref':'#/$defs/Vector'},per_episode={'$ref':'#/$defs/Vector'},episodes=positive,per_source_episodes=positive,max_row_bytes=positive,max_queue_wait_ns=positive)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/instance-budget.schema.json','title':VERSION,'x-approved':False,'not':{},'$defs':defs}
def schema_bytes():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
def build():
    sql=R.build().decode()
    old=' OR NOT EXISTS(SELECT 1 FROM pb_expected_account WHERE plan_id=NEW.plan_id)'
    assert sql.count(old)==1
    sql=sql.replace(old," OR (NOT EXISTS(SELECT 1 FROM pb_expected_account WHERE plan_id=NEW.plan_id) AND NOT EXISTS(SELECT 1 FROM p1_plan WHERE plan_id=NEW.plan_id))",1)
    sql+='\n'+(HERE/'instance-budget.sql').read_text(encoding='utf-8')
    # 四维固定分区严格等于总容量，来源池不借run区，反之亦然。
    partition=' AND '.join(f'NEW.total_{d}=c.{d}+NEW.{d}*NEW.episodes AND json_extract(NEW.profile_body,\'$.total_capacity.{d}\') IS CAST(NEW.total_{d} AS TEXT) AND json_extract(NEW.profile_body,\'$.per_episode.{d}\') IS CAST(NEW.{d} AS TEXT)' for d in DIMENSIONS)
    sql+=f"\nCREATE TRIGGER ib_partition BEFORE INSERT ON ib_pool WHEN NOT EXISTS(SELECT 1 FROM arm_capacity c WHERE c.profile_digest=NEW.arm_profile_digest AND {partition}) BEGIN SELECT RAISE(ABORT,'instance_budget_partition'); END;\n"
    vector=' AND '.join(f'NEW.{d}=p.{d}' for d in DIMENSIONS)
    sql+=f"\nCREATE TRIGGER ib_vector BEFORE INSERT ON ib_use WHEN NOT EXISTS(SELECT 1 FROM ib_pool p WHERE p.singleton=NEW.pool_id AND {vector}) BEGIN SELECT RAISE(ABORT,'instance_charge_vector'); END;\n"
    balance=','.join(f'p.{d}*count(u.plan_id) AS spent_{d},p.{d}*(p.episodes-count(u.plan_id)) AS held_{d}' for d in DIMENSIONS)
    sql+=f"\nCREATE VIEW ib_balance AS SELECT p.singleton,p.episodes-count(u.plan_id) AS episodes_left,{balance} FROM ib_pool p LEFT JOIN ib_use u ON u.pool_id=p.singleton GROUP BY p.singleton;\n"
    for table in ('ib_pool','ib_use'):
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_instance_budget'); END;\n"
    available="""SELECT 1 FROM ib_balance b JOIN ib_pool p USING(singleton) WHERE b.episodes_left>0
 AND NOT EXISTS(SELECT 1 FROM p1_dependency d WHERE d.run_id=__RUN__
 AND (SELECT count(*) FROM ib_use u WHERE u.source_id=d.source_id)>=p.per_source_episodes)"""
    for table,run in (('arm_operation','NEW.run_id'),('recovery_operation','NEW.run_id'),('execution_start','NEW.run_id'),
        ('arm_ready_commit','(SELECT run_id FROM arm_operation WHERE operation_id=NEW.operation_id)')):
        sql+=f"\nCREATE TRIGGER ib_{table}_admission BEFORE INSERT ON {table} WHEN NOT EXISTS({available.replace('__RUN__',run)}) BEGIN SELECT RAISE(ABORT,'instance_budget_unavailable'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for path,raw in [(HERE/'seamer-instance-budget.sql',build()),(HERE/'instance-budget.schema.json',schema_bytes())]:
        if a.check:assert path.read_bytes()==raw,'生成漂移'
        else:path.write_bytes(raw)
