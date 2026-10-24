"""完整命令受理候选；明确改写新绑定路径和跨域身份列。"""
import argparse
from pathlib import Path
import build_typed_seamer as B
HERE=Path(__file__).resolve().parent
SOURCES=B.B.SOURCES+[Path(B.__file__),Path(__file__),HERE/'typed-controller.sql']
def build():
    sql=B.B.controller_sql().decode()
    sql=B.amend(sql,'CREATE TABLE ca_request_key (',[(
        '  content_body BLOB NOT NULL CHECK(length(content_body)>0),',
        '  content_body BLOB NOT NULL CHECK(json_valid(content_body)),\n  request_key_body BLOB NOT NULL CHECK(json_valid(request_key_body)),\n  transport_body BLOB CHECK(transport_body IS NULL OR json_valid(transport_body)),')])
    sql=B.amend(sql,'CREATE TABLE cn_command(',[(
        'execution_id TEXT NOT NULL,step_id TEXT NOT NULL,submission_id TEXT NOT NULL,request_digest TEXT NOT NULL,',
        'execution_id TEXT NOT NULL,step_id TEXT NOT NULL,request_digest TEXT NOT NULL,')])
    sql=B.amend(sql,'CREATE TRIGGER cn_command_guard ',[
        (" AND NEW.step_id=json_extract(e.binding_body,'$.step_id') AND NEW.submission_id=json_extract(e.binding_body,'$.submission_id')", " AND NEW.step_id=json_extract(e.binding_body,'$.step_id')"),
        ('$.continuation.adoption_digest','$.automation_binding.continuation.adoption_ref.digest'),
        ('$.continuation.transfer_id','$.automation_binding.continuation.transfer_ref.id'),
        ('$.continuation.grant_ref','$.automation_binding.continuation.grant_ref')])
    sql=B.amend(sql,'CREATE TRIGGER cn_accept_guard ',[("'$.continuation'","'$.automation_binding.continuation'")])
    return (sql+'\n'+(HERE/'typed-controller.sql').read_text(encoding='utf-8')).encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();path=HERE/'controller-typed.sql'
    if a.check:assert path.read_bytes()==build()
    else:path.write_bytes(build())
