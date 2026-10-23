"""生成94表共享签发候选；固定输入转换，不是迁移器或业务writer。"""
import argparse
from pathlib import Path
import build_layout as L

HERE=Path(__file__).resolve().parent
SOURCES=[HERE/n for n in ('controller.sql','fence.sql','barrier-attempt.sql','resource.sql','command.sql')]
SOURCES += [HERE.parent/'c02-command-view/storage.sql',HERE/'issue-ledger.sql']

def build():
    base,fence,attempt,resource,command,public,ledger=[p.read_text(encoding='utf-8') for p in SOURCES]
    successor=""" SELECT CASE WHEN NEW.issued_revision!=(SELECT printf('%010d%010d',
  CAST(substr(v,1,10) AS INTEGER)+(substr(v,11,10)='9999999999'),
  (CAST(substr(v,11,10) AS INTEGER)+1)%10000000000)
  FROM (SELECT coalesce(max(issued_revision),'00000000000000000000') v FROM ce_permit))
  THEN RAISE(ABORT,'issued_successor') END;
"""
    fence=L.replace(fence,successor,'',1)
    fence=L.replace(fence,' permit_body BLOB NOT NULL CHECK(length(permit_body)>0),',
        " permit_body BLOB NOT NULL CHECK(length(permit_body)>0),\n"
        " issue_kind TEXT NOT NULL DEFAULT 'ordinary' CHECK(issue_kind='ordinary'),\n"
        " FOREIGN KEY(permit_id,issued_revision,issue_kind) REFERENCES ci_issue(permit_id,issued_revision,kind) DEFERRABLE INITIALLY DEFERRED,",1)
    old="(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ce_permit)"
    new="(SELECT coalesce(max(issued_revision),'00000000000000000000') FROM ci_issue)"
    fence=L.replace(fence,old,new,1)
    resource=L.replace(resource,old,new,1)
    public=L.replace(public,old,new,2)
    # 保护已有原文件；只有本候选组合改用共享authority。
    result='-- 生成物：共享签发94表候选，禁止部署；请修改唯一源并重新生成。\n'
    result+='\n'.join((base,fence,attempt,resource,command,public,ledger))
    for table in ('ci_issue','ci_cancel_transmission','ci_cancel_commit'):
        for action,suffix in (('UPDATE','u'),('DELETE','d')):
            result+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_issue'); END;\n"
    assert old not in result
    return result.encode('utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    data=build();target=HERE/'controller-issue.sql'
    if a.check:assert target.read_bytes()==data,'生成漂移'
    else:target.write_bytes(data)
