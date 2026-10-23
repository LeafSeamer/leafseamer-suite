"""组合RUN保护状态与资源来源；不修改旧候选或运行产品迁移。"""
import argparse
import build_prepare_deny_storage as P
HERE=P.HERE;L=P.L
TABLES=('rr_manifest','rr_source','rr_manifest_commit')
SOURCES=P.SOURCES+[HERE/n for n in ('protection-delivery.sql','build_run_resource.py','run-resource.sql')]
def build():
    sql=P.build().decode()+'\n'+(HERE/'protection-delivery.sql').read_text(encoding='utf-8')
    sql=L.replace(sql,' FOREIGN KEY(validation_id) REFERENCES cd_manifest(validation_id) DEFERRABLE INITIALLY DEFERRED',
      ' FOREIGN KEY(validation_id) REFERENCES rr_manifest(validation_id) DEFERRABLE INITIALLY DEFERRED,\n FOREIGN KEY(validation_id) REFERENCES cd_manifest(validation_id) DEFERRABLE INITIALLY DEFERRED',1)
    # 最终来源视图由result-dependency.sql创建；旧初始定义已由该源DROP，须只改最后一份。
    marker='CREATE VIEW cr_valid_validation AS\n SELECT v.* FROM cr_validation v JOIN cd_manifest_commit'
    sql=L.replace(sql,marker,'CREATE VIEW rr_base_valid_validation AS\n SELECT v.* FROM cr_validation v JOIN cd_manifest_commit',1)
    sql+='\n'+(HERE/'run-resource.sql').read_text(encoding='utf-8')
    for table in TABLES:
        for op,suffix in [('UPDATE','u'),('DELETE','d')]:
            sql+=f"\nCREATE TRIGGER {table}_{suffix} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_run_resource'); END;\n"
    return sql.encode()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    raw=build();target=HERE/'controller-run-resource.sql'
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
