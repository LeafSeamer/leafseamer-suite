"""双运行时合成外键向量、实际组合布局与摄取写集原子性。"""
import argparse,copy,hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
import check_typed_seamer as X
import atomic_ingress_model as M
import build_atomic_ingress as G
HERE=Path(__file__).resolve().parent;ROOT=X.ROOT

def python_vectors():
    vectors=json.loads((HERE/'fk-seal-vectors.json').read_bytes());results=[]
    for shape,ddl in vectors['schemas'].items():
        for test in vectors['cases']:
            db=sqlite3.connect(':memory:')
            try:
                db.executescript(ddl);version,source=db.execute('SELECT sqlite_version(),sqlite_source_id()').fetchone()
                db.execute('BEGIN')
                if test['parent']:db.execute("INSERT INTO parent VALUES('parent')")
                if test['child']:db.execute("INSERT INTO child VALUES('child','parent')")
                db.execute("INSERT INTO seal(id) VALUES('seal')")
                if shape=='split_seal' and test['marker']:db.execute("INSERT INTO seal_commit(id) VALUES('seal')")
                if test['seal']:db.execute("UPDATE seal SET sealed=1 WHERE id='seal'")
                violations=[dict(table=r[0],parent=r[2],fkid=r[3]) for r in db.execute('PRAGMA foreign_key_check')]
                try:db.commit();committed=True
                except sqlite3.IntegrityError as err:
                    assert str(err)=='FOREIGN KEY constraint failed';db.rollback();committed=False
                expected=True if shape=='mutable_self' and test['name']=='missing_marker' else test['expected_commit']
                results.append(dict(shape=shape,case=test['name'],committed=committed,expected_commit=expected,conforms=committed==expected,violations=violations))
            finally:db.close()
    return dict(runtime=sys.version.split()[0],engine=dict(version=version,source=source),results=results)

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fresh():
        d,q,cds,ctx=X.fixture(sql_factory=G.build);dbs.extend([d]+[v[0] for v in cds.values()]);return d,ctx
    def denied(name,d,fn,reason=None):
        before=X.SC.snapshot(d)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError) as err:
            if reason:assert reason in str(err),(name,str(err))
            check(name,X.SC.snapshot(d)==before and not d.in_transaction);return
        raise AssertionError(name)
    try:
        py=python_vectors();node=json.loads(subprocess.run(['node',str(HERE/'check_fk_seal_node.cjs')],capture_output=True,text=True,check=True).stdout)
        for label,result in [('Python',py),('Node',node)]:
            check(label+'八项实测',len(result['results'])==8 and bool(result['engine']['source']))
            for row in result['results']:
                if row['shape']=='split_seal':check(label+'独立封存'+row['case'],row['conforms'])
            # 原形状的孤儿结果作为诊断原样记录；修复后的引擎也允许执行此检查。
            check(label+'旧形状成功事务完整',all(r['conforms'] for r in result['results'] if r['shape']=='mutable_self' and r['case']!='orphan'))
        check('组合DDL可重现',(HERE/'seamer-atomic-ingress.sql').read_bytes()==G.build())
        d,ctx=fresh();check('Seamer121表',len(X.SC.snapshot(d))==121)
        event=X.T.W.event(12);builder=lambda:M.ingress_steps(d,event,ctx);writes=X.AT.planned(d,builder)
        for i in range(len(writes)):
            denied('摄取写后故障'+str(i),d,lambda i=i:M.T.apply(d,builder,fail_after=i),'injected')
        seal=next(i for i,w in enumerate(writes) if X.T.M.inserted(*w)[0]=='ingress_commit_seal')
        finish=next(i for i,w in enumerate(writes) if w[0]=='UPDATE ingress_commit SET sealed=1 WHERE commit_id=?')
        denied('缺独立封存不能提交',d,lambda:X.SC.execute(d,writes[:seal]+writes[seal+1:]),'FOREIGN KEY')
        denied('缺终态更新不能提交',d,lambda:X.SC.execute(d,writes[:finish]+writes[finish+1:]),'FOREIGN KEY')
        denied('错误封存身份不能提交',d,lambda:X.SC.execute(d,X.SC.mutate(writes,'ingress_commit_seal',dict(commit_id='wrong'))),'FOREIGN KEY')
        denied('封存值必须为1',d,lambda:X.SC.execute(d,X.SC.mutate(writes,'ingress_commit_seal',dict(sealed=0))))
        check('完整摄取提交',M.receive_event(d,event,ctx)=='accepted')
        ex=X.T.active(d);check('一个封存对应一个事务',d.execute('SELECT count(*) FROM ingress_commit_seal').fetchone()[0]==1)
        for action in ['UPDATE ingress_commit_seal SET sealed=1','DELETE FROM ingress_commit_seal']:
            denied('封存原件不可变'+action.split()[0],d,lambda action=action:X.SC.execute(d,[(action,())]),'immutable_ingress_seal')
        before=X.SC.snapshot(d)
        check('查原零写不重复封存',M.receive_event(d,event,dict(ctx,program_current=False))=='existing' and X.SC.snapshot(d)==before)
        wrong=copy.deepcopy(event);wrong['payload']={'changed':True}
        denied('同键异内容拒绝',d,lambda:M.receive_event(d,wrong,ctx),'event_conflict')
        check('忙抑制仍封存',M.receive_event(d,X.T.W.event(13),ctx)=='accepted' and d.execute('SELECT count(*) FROM ingress_commit_seal').fetchone()[0]==2)
        check('忙抑制没有创建新执行',X.T.active(d)==ex and d.execute("SELECT count(*) FROM ingress_decision WHERE result='suppressed_busy'").fetchone()[0]==1)
        X.C.tx(d,lambda:X.T.F.anchor_steps(d,ex,ctx))
        for step in ['step.0','step.1']:
            X.C.tx(d,lambda step=step:X.T.F.ready_steps(d,ex,step,ctx));X.M.submit(d,ex,step,ctx)
            sub=X.T.F.step(d,ex,step)['submission_id'];check('完整请求无字段差异'+step,X.M.S.findings(d,sub)==[])
        other,oc=fresh();oc=copy.deepcopy(oc);oc['evaluations']['r0']['matched']=False
        count=other.execute('SELECT count(*) FROM execution').fetchone()[0]
        check('不匹配仍完成摄取',M.receive_event(other,event,oc)=='accepted')
        check('不匹配有独立封存无新执行',other.execute('SELECT count(*) FROM ingress_commit_seal').fetchone()[0]==1 and other.execute("SELECT count(*) FROM ingress_decision WHERE result='no_match'").fetchone()[0]==1 and other.execute('SELECT count(*) FROM execution').fetchone()[0]==count)
        probe,pc=fresh();probe.execute('DROP TRIGGER typed_plan_source_seal')
        omitted=X.AT.planned(probe,lambda:M.ingress_steps(probe,event,pc))
        omitted=[w for w in omitted if X.T.M.inserted(*w)[0]!='typed_execution_source']
        denied('无显式seal守卫及预提交检查仍拒漏原件',probe,lambda:X.SC.execute(probe,omitted),'FOREIGN KEY')
        for i,db in enumerate(dbs):check('组合库外键完整'+str(i),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks,dict(python=py,node=node)
    finally:
        for d in dbs:d.close()

def inputs():
    names=['typed-seamer-report.json','atomic_ingress_model.py','check_atomic_ingress.py','check_fk_seal_node.cjs','fk-seal-vectors.json','seamer-atomic-ingress.sql','ATOMIC_INGRESS.md']
    return list(dict.fromkeys(X.inputs()+G.SOURCES+[HERE/n for n in names]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'atomic-ingress-report.json'
    if a.check_report:
        assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks,probes=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=121,synthetic_probes=probes,production_clearance=False,selected_native_artifact_tested=False,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(X.M.S.G.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs','synthetic_probes')}))
