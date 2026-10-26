"""持久撤销切点、历史全集和writer边界验收；不发送设备指令。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from jsonschema.exceptions import ValidationError
import check_final_authorization as F
import revocation_source_model as M
A=M.A;HERE=M.HERE;ROOT=F.ROOT
def inputs():return list(dict.fromkeys(F.inputs()+[HERE/n for n in ('build_revocation_source.py','revocation-source.schema.json','revocation-source.sql','revocation_source_model.py','check_revocation_source.py','REVOCATION_SOURCE.md')]))
def fixture():
    db,connections,cmd,auth,pid,provider,response=F.fixture()
    F.T.E.O.execute(db,F.T.T.preview(db,lambda:F.T.E.receive(db,pid,response,provider)))
    v,_,_=F.T.T.preview(db,lambda:F.T.candidate(db,pid,provider));u=F.use(v,db)
    F.tx(db,lambda:F.publish_use(db,u));M.install(db)
    return db,connections,u
def run():
    checks=[];connections=[]
    def check(name,condition=True):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error) as e:
            check(name,reason is None or reason in str(e));return
        raise AssertionError('未拒绝:'+name)
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');connections.append(c);return c
    def event(db,u,kind='principal',revision='4',eid='event',**changes):return F.tx(db,lambda:A.install_floor(db,F.floor(u,kind,revision,eid,**changes)))
    def history(db,v):return F.tx(db,lambda:M.read(db,M.reference(v)))
    def current(db,v):return F.tx(db,lambda:M.current(db,M.reference(v)))
    def snapshot(db):return F.T.T.V.SC.snapshot(db)
    try:
        check('Schema生成物一致',(HERE/'revocation-source.schema.json').read_bytes()==M.G.encoded())
        db,others,u=fixture();connections.extend([db,*others]);ur=F.use_ref(u);empty=M.capture(db,ur)
        tables=len([n for n in snapshot(db) if not n.startswith('sqlite_')]);check('既有253表增加两张持久来源表',tables==255)
        check('全库核对另含SQLite自增状态表',len(snapshot(db))==256 and 'sqlite_sequence' in snapshot(db))
        check('空切点不称有效授权',empty['members']==[] and empty['observed_through']=='0' and empty['observed_floor_result']=='no_matching_denial')
        check('依赖由完整原件派生',set(d['kind'] for d in empty['dependencies'])=={'principal','credential','trust','grant'})
        check('同来源重投固定身份',M.capture(db,ur)==empty)
        denied('不接受错摘要的使用原件',lambda:M.capture(db,dict(ur,digest=A.F.digest('other'))),'revocation_use_binding')
        c=fork(db);event(c,u,revision='4');equal=M.capture(c,ur)
        check('下界相等不拒绝',equal['observed_floor_result']=='no_matching_denial' and len(equal['members'])==1)
        denied('相等下界的新事件也使旧切点过时',lambda:current(c,empty),'revocation_snapshot_stale')
        check('旧空切点可查原不追加入新事件',history(c,empty)==empty)
        event(c,u,revision='2',eid='lower');lower=M.capture(c,ur)
        check('乱序低下界保留全集',len(lower['members'])==2 and lower['observed_floor_result']=='no_matching_denial')
        event(c,u,revision='5',eid='higher');higher=M.capture(c,ur)
        check('严格低于下界拒绝',higher['observed_floor_result']=='denied' and higher['members'][-1]['denial']=='below_floor')
        event(c,u,revision='1',eid='late.low');late=M.capture(c,ur)
        check('后到低下界不撤销拒绝',late['observed_floor_result']=='denied' and len(late['members'])==4)
        check('历史完整成员按当时切点重建',history(c,equal)==equal and history(c,higher)==higher)
        denied('调用方删成员重算摘要仍不是原件',lambda:F.tx(c,lambda:M.read(c,dict(M.reference(higher),digest=A.F.digest('changed')))),'revocation_snapshot_columns')
        # 首次持久时注入重算ID和摘要的错误正文；不更新既有历史或关闭约束。
        for label,mutate in [
            ('缺成员',lambda x:x.update(members=[])),
            ('少依赖',lambda x:x.update(dependencies=[d for d in x['dependencies'] if d['kind']!='grant'])),
            ('同数量错成员',lambda x:x['members'][0]['event_ref'].update(id='unrelated')),
            ('错误入账位置',lambda x:x['members'][0].update(sequence='2')),
            ('伪造未命中拒绝',lambda x:x.update(observed_floor_result='no_matching_denial')),
            ('跨设备绑定',lambda x:x['binding'].update(device_id='other.device'))]:
            c=fork(db);event(c,u,revision='5');event(c,u,eid='unrelated',target_id='unrelated')
            bad=F.tx(c,lambda:M.derive(c,ur));mutate(bad);bad.pop('snapshot_id');bad.pop('snapshot_digest')
            bad['snapshot_id']='revocation_cut_'+A.F.digest(bad)[7:];bad=A.sealed(bad,'snapshot_digest')
            F.tx(c,lambda:c.execute('INSERT INTO authorization_revocation_snapshot VALUES(?,?,?,?,?)',(bad['snapshot_id'],ur['id'],int(bad['observed_through']) or None,bad['snapshot_digest'],A.raw(bad))))
            denied('重算摘要仍拒绝/'+label,lambda:history(c,bad),'revocation_snapshot_originals')
        for kind,revision,reason in [('credential','0','credential_revoked'),('trust','0','issuer_epoch_revoked'),('grant','2','below_floor')]:
            c=fork(db);event(c,u,kind,revision);v=M.capture(c,ur)
            check('完整依赖拒绝/'+kind,v['observed_floor_result']=='denied' and v['members'][0]['denial']==reason)
            check('已拒绝也能查当前拒绝元数据/'+kind,current(c,v)==v)
        for key,value in [('issuer_id','another'),('issuer_epoch','another'),('target_id','another')]:
            c=fork(db);event(c,u,**{key:value});check('无关事件不扰动当前切点/'+key,current(c,empty)==empty and M.capture(c,ur)==empty)
        c=fork(db);event(c,u,'trust','0',target_id='different.trust.label');check('trust拒绝覆盖整个发行代次',M.capture(c,ur)['observed_floor_result']=='denied')
        c=fork(db);before=snapshot(c);e=F.floor(u)
        denied('撤销及入账顺序同事务回滚',lambda:F.tx(c,lambda:(A.install_floor(c,e),(_ for _ in ()).throw(ValueError('fault')))),'fault')
        check('撤销失败全255表保持',snapshot(c)==before)
        c.execute("CREATE TRIGGER inject_order_failure BEFORE INSERT ON authorization_revocation_order BEGIN SELECT RAISE(ABORT,'injected order failure'); END")
        denied('顺序写入失败不能提交孤立撤销',lambda:event(c,u),'injected order failure')
        check('顺序失败连事件及自增状态一起回滚',snapshot(c)==before)
        c.execute('DROP TRIGGER inject_order_failure')
        event(c,u,revision='5');check('首次事件必带入账顺序',c.execute('SELECT count(*) FROM authorization_revocation_order').fetchone()[0]==1)
        F.tx(c,lambda:A.install_floor(c,e));check('相同事件重投不重复入账',c.execute('SELECT count(*) FROM authorization_revocation_order').fetchone()[0]==1)
        for table in ('authorization_floor_event','authorization_revocation_order','authorization_revocation_snapshot'):
            denied('历史不可删/'+table,lambda table=table:F.tx(c,lambda:c.execute('DELETE FROM '+table)))
        for kwargs in ({'fail_after':True},{'omit':True},{'commit_fault':'before'}):
            c=fork(db);event(c,u);before=snapshot(c)
            denied('封存异常/'+str(kwargs),lambda:M.capture(c,ur,**kwargs));check('封存回滚全库/'+str(kwargs),snapshot(c)==before)
        c=fork(db);event(c,u);denied('提交后观察丢失',lambda:M.capture(c,ur,commit_fault='after'),'injected_commit_after')
        v=M.capture(c,ur);check('查到已提交原件不重建身份',history(c,v)==v)
        c=fork(db);before=snapshot(c)
        denied('不接受外部事务',lambda:F.tx(c,lambda:M.capture(c,ur)),'revocation_capture_owns_transaction');check('外部事务拒绝零写',snapshot(c)==before)
        c=fork(db);event(c,u);before=snapshot(c)
        denied('非空旧账本不编造历史顺序',lambda:M.install(c),'revocation_install_nonempty');check('安装拒绝不改变原表',snapshot(c)==before)
        # 每依赖真实4096/4097容量，不缩小模型常量代替边界。
        c=fork(db)
        F.tx(c,lambda:[A.install_floor(c,F.floor(u,revision='0',eid='capacity.'+str(i))) for i in range(4096)])
        v=M.capture(c,ur);check('4096事件全部保留',len(v['members'])==4096)
        event(c,u,revision='0',eid='capacity.4096');denied('4097不截断为成功',lambda:M.capture(c,ur),'revocation_capacity')
        check('容量溢出后原历史仍可读',history(c,v)==v)
        # 完整人员和扩展依赖在首次登记前选定，不改写历史使用原件。
        c=fork(db);human=copy.deepcopy(u);human['use_id']='human'
        human['identity']['origin']='manual';human['identity']['requester']['kind']='human'
        a=human['authorization_binding'];a.update(principal_kind='human',origin='manual',session_id='human.session',session_revision='4',grant_id=None,grant_revision=None,arm_generation=None,extension_instance_id='extension',extension_approval_revision='3')
        human['snapshot'].update({k:v for k,v in a.items() if k in human['snapshot']})
        def publish():
            challenge,response=F.capture(human);A.store_challenge(c,challenge);A.store_response(c,response);A.store_use(c,human)
        F.tx(c,publish);h=M.capture(c,F.use_ref(human))
        check('人员及扩展依赖不丢失',set(d['kind'] for d in h['dependencies'])=={'principal','credential','trust','session','extension'})
        event(c,human,'session','5',eid='session');check('人员会话撤销拒绝',M.capture(c,F.use_ref(human))['observed_floor_result']=='denied')
        event(c,human,'extension','4',eid='extension');check('扩展授权撤销同时保留',sum(m['denial'] is not None for m in M.capture(c,F.use_ref(human))['members'])==2)
        # 本机WAL双连接；不把该实验称为跨进程或真实认证验收。
        with tempfile.TemporaryDirectory(prefix='leafseamer-revocation-') as directory:
            path=Path(directory)/'source.sqlite';left=sqlite3.connect(path,isolation_level=None);db.backup(left);left.execute('PRAGMA journal_mode=WAL');right=sqlite3.connect(path,isolation_level=None,timeout=0)
            try:
                for x in (left,right):x.execute('PRAGMA foreign_keys=ON');x.execute('PRAGMA recursive_triggers=ON')
                left.execute('BEGIN');check('旧读快照初始可查原',M.read(left,M.reference(empty))==empty)
                event(right,u,revision='5');check('旧读仍只见旧切点',M.read(left,M.reference(empty))==empty)
                denied('旧读升级writer失败不得沿用',lambda:M.current(left,M.reference(empty)));left.rollback()
                denied('新writer拒绝旧切点',lambda:current(left,empty),'revocation_snapshot_stale')
                v=M.capture(left,ur);check('新writer取到拒绝全集',v['observed_floor_result']=='denied')
                left.execute('BEGIN IMMEDIATE');denied('第二writer不能越过在持锁选择',lambda:event(right,u,eid='second'));left.rollback()
            finally:left.close();right.close()
        for c in dict.fromkeys(connections):check('退出事务及外键完整',not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone())
        return dict(all_passed=True,approved=False,cases_passed=len(checks),candidate_tables=tables,checks=checks,
            historical_complete_members_verified=True,local_floor_order_atomicity_verified=True,wal_writer_recheck_verified=True,
            authority_authenticity_verified=False,open_authorization_integrated=False,revocation_protection_atomicity_verified=False,full_open_verified=False,device_tests_executed=0,
            inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()})
    finally:
        for c in dict.fromkeys(connections):c.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();path=HERE/'revocation-source-report.json'
    if a.check_report:
        r=json.loads(path.read_bytes());assert r['inputs']=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};print(json.dumps(dict(bindings_valid=True,inputs=len(r['inputs']),rerun=False)))
    else:
        r=run()
        if a.report:path.write_bytes(A.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
