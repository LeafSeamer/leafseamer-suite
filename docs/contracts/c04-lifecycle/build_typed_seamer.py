"""为完整Seamer组合库增加类型化继续运行写集；旧候选保持不变。"""
import argparse,sqlite3
from pathlib import Path
import build_continuation_trigger as B
HERE=Path(__file__).resolve().parent
SOURCES=B.SOURCES+[Path(__file__),HERE/'typed-seamer.sql']
def amend(sql,name,changes):
    parts=[];pending='';found=0
    for line in sql.splitlines(keepends=True):
        pending+=line
        if not sqlite3.complete_statement(pending):continue
        if name in pending:
            for old,new in changes:
                assert pending.count(old)==1,(name,old);pending=pending.replace(old,new)
            found+=1
        parts.append(pending);pending=''
    assert found==1,name;return ''.join(parts)+pending
def build():
    sql=B.seamer_sql().decode()
    sql=amend(sql,'CREATE TABLE execution (',[
        (' execution_id TEXT PRIMARY KEY NOT NULL,',' typed_source_id TEXT REFERENCES typed_execution_source(execution_id) DEFERRABLE INITIALLY DEFERRED,\n execution_id TEXT PRIMARY KEY NOT NULL,')])
    sql=amend(sql,'CREATE TABLE command_submission (',[
        (' issuer_id TEXT NOT NULL,',' issuer_epoch TEXT NOT NULL,request_key_body BLOB NOT NULL CHECK(json_valid(request_key_body)), issuer_id TEXT NOT NULL,'),
        ('UNIQUE(target_authority,target_database,issuer_id,principal_id,request_epoch,operation_id,idempotency_key)',
         'UNIQUE(target_authority,target_database,issuer_id,issuer_epoch,principal_id,request_epoch,operation_id,idempotency_key)')])
    # 新身份和正文永久不可变；旧状态迁移守卫保持。
    sql+='\n'+(HERE/'typed-seamer.sql').read_text(encoding='utf-8')
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'seamer-typed.sql'
    if a.check:assert path.read_bytes()==build()
    else:path.write_bytes(build())
