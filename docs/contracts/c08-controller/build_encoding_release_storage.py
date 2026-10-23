"""生成缓存释放同库候选，不执行业务迁移。"""
import argparse
import build_encoding_storage as E
import build_layout as L
HERE=E.HERE
TABLES=('er_request','er_request_commit','er_ack','er_adoption','er_ack_commit')
SOURCES=E.SOURCES+[HERE/'build_encoding_release_storage.py',HERE/'encoding-release-storage.sql']

def build():
    text=E.build().decode()
    text=L.replace(text,'max_live_prepares INTEGER NOT NULL CHECK(max_live_prepares BETWEEN 1 AND 4096),',
      'max_live_prepares INTEGER NOT NULL CHECK(max_live_prepares BETWEEN 1 AND 4096),\n max_metadata_prepares INTEGER NOT NULL CHECK(max_metadata_prepares BETWEEN 1 AND 65536),',1)
    text=L.replace(text,'authorization_id TEXT NOT NULL UNIQUE, authorization_digest TEXT NOT NULL,',
      "reservation_id TEXT NOT NULL UNIQUE, reservation_revision TEXT NOT NULL CHECK(reservation_revision='00000000000000000001'), reservation_digest TEXT NOT NULL,\n authorization_id TEXT NOT NULL UNIQUE, authorization_digest TEXT NOT NULL,",1)
    text=L.replace(text,'CREATE TABLE ep_revocation(\n prepare_id TEXT PRIMARY KEY REFERENCES ep_request_commit(prepare_id),',
      "CREATE TABLE ep_revocation(\n prepare_id TEXT PRIMARY KEY REFERENCES ep_request_commit(prepare_id),\n revocation_id TEXT NOT NULL UNIQUE, revocation_revision TEXT NOT NULL CHECK(revocation_revision='00000000000000000001'), revocation_digest TEXT NOT NULL,\n revoked_tick TEXT NOT NULL CHECK(length(revoked_tick)=20 AND revoked_tick NOT GLOB '*[^0-9]*'),",1)
    text=L.replace(text,"basis TEXT NOT NULL CHECK(basis IN ('never_attempted','supervisor_retired')),",
      "basis TEXT NOT NULL CHECK(basis IN ('never_attempted','supervisor_retired','worker_released')),\n worker_adoption_id TEXT UNIQUE,",1)
    text=L.replace(text,"CHECK((basis='never_attempted' AND retirement_exit_id IS NULL) OR (basis='supervisor_retired' AND retirement_exit_id IS NOT NULL))",
      "CHECK((basis='never_attempted' AND retirement_exit_id IS NULL AND worker_adoption_id IS NULL) OR (basis='supervisor_retired' AND retirement_exit_id IS NOT NULL AND worker_adoption_id IS NULL) OR (basis='worker_released' AND retirement_exit_id IS NULL AND worker_adoption_id IS NOT NULL)),\n UNIQUE(prepare_id,worker_adoption_id),\n FOREIGN KEY(prepare_id,worker_adoption_id) REFERENCES er_adoption(prepare_id,adoption_id) DEFERRABLE INITIALLY DEFERRED",1)
    text+='\n'+(HERE/'encoding-release-storage.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for action,suffix in [('UPDATE','u'),('DELETE','d')]:
            text+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_encoding_release'); END;\n"
    return text.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    raw=build();target=HERE/'controller-encoding-release.sql'
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
