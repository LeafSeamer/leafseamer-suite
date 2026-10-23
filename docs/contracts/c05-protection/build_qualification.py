"""生成准备当前资格及保护传播候选；不改变旧报告和公共基线。"""
import argparse,json
from pathlib import Path
import build_registration as R
HERE=Path(__file__).resolve().parent
VERSION='preparation-qualification/0.1.0-draft.1'
SOURCES=R.SOURCES+[HERE/'build_qualification.py',HERE/'qualification.sql',HERE.parent/'c08-controller/preparation-delivery.schema.json']


def schema():
    old=json.loads(SOURCES[-1].read_bytes());binding=old['$defs']['Binding'];p=binding['properties']
    def obj(**v):return dict(type='object',properties=v,required=list(v),additionalProperties=False)
    value=obj(contract_version={'const':VERSION},event_id=p['preparation_id'],binding={'$ref':'#/$defs/Binding'},
      reason={'enum':['authorization_revoked','grant_expired','controller_instance_changed','stream_unconfirmed']},
      proof_ref=obj(scope=p['controller_scope'],id=p['preparation_id'],revision=p['generation'],digest=p['request_digest']),withdrawal_digest=p['request_digest'])
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c05-protection/preparation-qualification.schema.json',
      'title':VERSION,'x-approved':False,'not':{},'$defs':{'Binding':binding,'Withdrawal':value}}


def schema_bytes():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()
def build():
    sql=R.build().decode()
    old=' FOREIGN KEY(plan_id) REFERENCES p1_plan(plan_id) DEFERRABLE INITIALLY DEFERRED,'
    # 只共享sp保护观察计划；po仍要求来源P1封存，不能冒充准备关闭原件。
    assert sql.count(old)==2
    sql=sql.replace(old,' FOREIGN KEY(plan_id) REFERENCES protection_plan_registry(plan_id) DEFERRABLE INITIALLY DEFERRED,',1)
    old="CREATE VIEW p1_deny AS SELECT r.run_id,max(substr('00000000000000000000'||r.generation,-20)) AS generation\n FROM p1_run r JOIN p1_commit k USING(plan_id) GROUP BY r.run_id;"
    assert sql.count(old)==1
    sql=sql.replace(old,"""CREATE VIEW p1_deny AS SELECT run_id,max(generation) AS generation FROM (
 SELECT r.run_id,substr('00000000000000000000'||r.generation,-20) AS generation FROM p1_run r JOIN p1_commit k USING(plan_id)
 UNION ALL SELECT p.run_id,substr('00000000000000000000'||p.generation,-20) FROM pq_plan p JOIN pq_commit k USING(plan_id)) GROUP BY run_id;""")
    sql+='\n'+(HERE/'qualification.sql').read_text(encoding='utf-8').replace('__REV_NEXT__',R.P.successor('NEW.revision_before'))
    for table in ('protection_plan_registry','pq_observation','pq_fault','pq_plan','pq_target','pq_commit'):
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_preparation_qualification'); END;\n"
    for table in ('execution_start','step_ready','command_submission','transition_commit'):
        sql+=f"""\nCREATE TRIGGER pq_gate_{table} BEFORE INSERT ON {table} WHEN EXISTS(
 SELECT 1 FROM execution e JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE e.execution_id=NEW.execution_id AND q.qualification!='observed_applied')
 OR EXISTS(SELECT 1 FROM execution e JOIN p1_deny d USING(run_id) WHERE e.execution_id=NEW.execution_id
 AND substr('00000000000000000000'||e.arm_generation,-20)<=d.generation)
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;\n"""
    sql+="""CREATE TRIGGER pq_gate_attempt BEFORE INSERT ON submission_attempt WHEN EXISTS(
 SELECT 1 FROM command_submission s JOIN execution e USING(execution_id) JOIN p1_preparation p ON p.run_id=e.run_id AND p.generation=e.arm_generation
 JOIN pq_current q USING(registration_id) WHERE s.submission_id=NEW.submission_id AND q.qualification!='observed_applied')
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;
CREATE TRIGGER pq_gate_ready BEFORE UPDATE ON recovery_operation WHEN NEW.state='ready' AND EXISTS(
 SELECT 1 FROM p1_preparation p JOIN pq_current q USING(registration_id) WHERE p.recovery_operation_id=NEW.operation_id AND q.qualification!='observed_applied')
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;
CREATE TRIGGER pq_gate_adoption BEFORE INSERT ON pr_receipt WHEN NOT EXISTS(
 SELECT 1 FROM pq_current q WHERE q.registration_id=NEW.registration_id AND q.qualification='observed_applied')
 BEGIN SELECT RAISE(ABORT,'preparation_current_unqualified'); END;
"""
    return sql.encode()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for name,raw in [('seamer-qualification.sql',build()),('preparation-qualification.schema.json',schema_bytes())]:
        target=HERE/name
        if a.check:assert target.read_bytes()==raw,'生成漂移:'+name
        else:target.write_bytes(raw)
