"""生成来源基线、连续补齐与同步检查点的内部候选契约。"""
import argparse,json
from pathlib import Path
import build_workload_budget as B
import build_arm_budget as A
HERE=Path(__file__).resolve().parent
VERSION='source-resync/0.1.0-draft.1'
SOURCES=B.SOURCES+[HERE/'build_source_resync.py',HERE/'source-resync.sql']

def schema():
    old=A.schema()['$defs'];ident=old['Profile']['properties']['profile_id'];u=old['Vector']['properties']['logical_rows'];sha=old['Binding']['properties']['profile_digest']
    common=dict(contract_version={'const':VERSION},transition_id=ident,baseline_id=ident,source_id=ident,source_key_digest=sha,fault_id=ident,
        expected_source_revision=u,delivery_ref={'$ref':'#/$defs/Ref'},request_epoch=ident,actor=A.obj(principal_id=ident),idempotency_key=ident)
    d={'Scope':old['Scope'],'Ref':old['Ref']}
    d['Baseline']=A.obj(**common,kind={'const':'baseline'},watermark=u,snapshot_ref={'$ref':'#/$defs/Ref'})
    d['Delta']=A.obj(**common,kind={'const':'delta'},source_sequence=u,event_ref={'$ref':'#/$defs/Ref'})
    d['Ready']=A.obj(**common,kind={'const':'ready'},through_sequence=u,last_delta_id=ident,checkpoint_ref={'$ref':'#/$defs/Ref'})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://leafseamer.invalid/design/c04-lifecycle/source-resync.schema.json',
        'title':VERSION,'x-approved':False,'not':{},'$defs':d}

def schema_bytes():return (json.dumps(schema(),ensure_ascii=False,indent=2)+'\n').encode()

def successor(before,after):
    b=f"substr('00000000000000000000'||{before},-20)";a=f"substr('00000000000000000000'||{after},-20)"
    hi=f'CAST(substr({b},1,10) AS INTEGER)';lo=f'CAST(substr({b},11,10) AS INTEGER)'
    return f"({b}!='99999999999999999999' AND {a}=printf('%010d%010d',{hi}+({lo}=9999999999),({lo}+1)%10000000000))"

def build():
    sql=B.build().decode()+'\n'+(HERE/'source-resync.sql').read_text(encoding='utf-8')
    for table in ('rs_limit','rs_transition','rs_commit'):
        for op in ('UPDATE','DELETE'):sql+=f"\nCREATE TRIGGER {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_source_resync'); END;\n"
    fields=('revision_before','revision_after','sequence_before','sequence_after','floor_before','floor_after')
    checks=' OR '.join(f"length(NEW.{k}) NOT BETWEEN 1 AND 20 OR NEW.{k} GLOB '*[^0-9]*' OR(NEW.{k}!='0' AND substr(NEW.{k},1,1)='0') OR instr(NEW.{k},char(0))>0" for k in fields)
    sql+=f"\nCREATE TRIGGER rs_u20 BEFORE INSERT ON rs_transition WHEN {checks} BEGIN SELECT RAISE(ABORT,'resync_u20'); END;\n"
    sql+=f"\nCREATE TRIGGER rs_successor BEFORE INSERT ON rs_transition WHEN NOT {successor('NEW.revision_before','NEW.revision_after')} OR(NEW.kind='delta' AND NOT {successor('NEW.sequence_before','NEW.sequence_after')}) BEGIN SELECT RAISE(ABORT,'resync_successor'); END;\n"
    for kind,proof in (('baseline','snapshot_ref'),('delta','event_ref'),('ready','checkpoint_ref')):
        bad=' OR '.join(f"json_type(NEW.request_body,'$.{ref}.{key}') IS NOT 'text' OR length(json_extract(NEW.request_body,'$.{ref}.{key}'))=0"
            for ref in ('delivery_ref',proof) for key in ('scope.authority_service_id','scope.database_instance_id','id','revision','digest'))
        sql+=f"\nCREATE TRIGGER rs_{kind}_refs BEFORE INSERT ON rs_transition WHEN NEW.kind='{kind}' AND ({bad}) BEGIN SELECT RAISE(ABORT,'resync_reference_required'); END;\n"
    return sql.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for path,raw in [(HERE/'seamer-source-resync.sql',build()),(HERE/'source-resync.schema.json',schema_bytes())]:
        if a.check:assert path.read_bytes()==raw,'生成漂移'
        else:path.write_bytes(raw)
