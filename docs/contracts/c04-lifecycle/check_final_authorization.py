"""授权撤销与最终编码来源的局部SQLite实验；身份取证均为合成。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import check_final_encoding_source as T
import final_authorization_model as M
G=M.G;HERE=G.HERE;ROOT=T.ROOT;clone=copy.deepcopy

def use(v):
    identity=clone(v['identity']);p=identity['requester'];manual=identity['origin']=='manual'
    a=dict(**{k:p[k] for k in ('issuer_id','issuer_epoch','principal_id')},audience=v['binding']['scope']['authority_service_id'],principal_kind=p['kind'],origin=identity['origin'],
        session_id='session' if manual else None,credential_id='credential',subject_revision='4',session_revision='4' if manual else None,policy_revision='2',scope_digest=M.F.digest('scope'),
        grant_id=None if manual else 'grant',grant_revision=None if manual else '4',arm_generation=None if manual else '1',extension_instance_id=None,extension_approval_revision=None)
    s={k:x for k,x in a.items() if k in M.SCHEMA['$defs']['AuthorizationSnapshot']['properties']}
    s.update(snapshot_id='snapshot',issuer_revision='8',challenge_id='challenge',permissions=['device.command'],
        validity=dict(not_before='2026-01-01T00:00:00.000Z',expires_at='2026-01-01T01:00:00.000Z'),fresh_for_ms=1,state='active')
    return M.sealed(dict(format_version='authorization-use/1',use_id='use',revision='1',binding=clone(v['binding']),identity=identity,authorization_binding=a,snapshot=s,
        challenge_sent_tick_ns='1',received_tick_ns='50',local_freshness_limit_ms=1,not_before_tick_ns='49',authorization_before_tick_ns='80',
        authority_evidence_ref=T.V.ref('authority'),scope_evidence_ref=T.V.ref('scope'),validity_evidence_ref=T.V.ref('validity')),'use_digest')

def use_ref(u):return M.E.ref(u['use_id'],u['revision'],u['use_digest'])
def floor(u,kind='principal',revision='5',eid='event',**changes):
    a=u['authorization_binding'];target={'principal':a['principal_id'],'credential':a['credential_id'],'session':a['session_id'],'grant':a['grant_id'],'trust':'trust.domain','extension':'extension'}[kind]
    s=dict(kind=kind,issuer_id=a['issuer_id'],issuer_epoch=a['issuer_epoch'],target_id=target,revision_floor=revision);s.update(changes)
    return M.sealed(dict(event_id=eid,scope=u['binding']['scope'],selector=s,operation_ref=T.V.ref('operation.'+eid)),'event_digest')

def tx(db,fn):
    db.execute('BEGIN IMMEDIATE')
    try:out=fn();db.commit();return out
    except BaseException:db.rollback();raise

def attach(v,o,authorization):
    o['authorization']=authorization
    for role in ('gate_access','permit_authority'):o[role]['body']['authorization_ref']=authorization['source_ref']
    T.V.refresh(v,o)

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def reject(n,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error) as error:
            if reason:assert reason in str(error),(n,str(error))
            check(n)
        else:raise AssertionError('未拒绝:'+n)
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');dbs.append(c);return c
    try:
        check('Schema生成字节一致',(HERE/'final-authorization.schema.json').read_bytes()==G.raw(G.build()))
        Draft202012Validator.check_schema(M.SCHEMA);check('根拒绝实例',not Draft202012Validator(M.SCHEMA).is_valid({}))
        db,connections,cmd,auth,pid,provider,response=T.fixture();dbs.extend(connections)
        T.E.O.execute(db,T.T.preview(db,lambda:T.E.receive(db,pid,response,provider)))
        db.executescript((HERE/'final-authorization.sql').read_text('utf-8'))
        v,o,cut=T.T.preview(db,lambda:T.candidate(db,pid,provider));u=use(v)
        # 采样回执到达后才产生有效资格；此fixture接收tick为50，仍早于选取51。
        u=M.sealed(dict(u,received_tick_ns='50'),'use_digest');ur=use_ref(u)
        tx(db,lambda:M.store_use(db,u));auth_projection=T.T.preview(db,lambda:M.read(db,ur,v));attach(v,o,auth_projection)
        check('244表含真实编码原件及本地撤销候选',len(T.T.V.SC.snapshot(db))==244)
        check('普通自动化可规划19条附属封存写集',len(T.T.preview(db,lambda:M.planned(db,v,o,cut,pid,provider,ur)))==19)
        reject('事务外读取拒绝',lambda:M.read(db,ur,v),'authorization_transaction_required')
        for kind in ('principal','grant','credential','trust'):
            c=fork(db);tx(c,lambda:M.install_floor(c,floor(u,kind)))
            reject('撤销后不能采用旧投影:'+kind,lambda:T.T.preview(c,lambda:M.planned(c,v,o,cut,pid,provider,ur)),
                'authorization_permanent_denial' if kind in ('credential','trust') else 'authorization_revision_floor')
            check('撤销保留packet与授权历史:'+kind,c.execute('SELECT count(*) FROM ep_reply').fetchone()[0]==c.execute('SELECT count(*) FROM authorization_use').fetchone()[0]==1)
        for changes in (dict(target_id='someone.else'),dict(issuer_epoch='other.epoch'),dict(issuer_id='other.issuer')):
            c=fork(db);tx(c,lambda:M.install_floor(c,floor(u,**changes)))
            check('不同撤销命名空间不命中:'+str(changes),T.T.preview(c,lambda:M.read(c,ur,v))==auth_projection)
        c=fork(db);equal=floor(u,revision='4');tx(c,lambda:M.install_floor(c,equal))
        fresh=T.T.preview(c,lambda:M.read(c,ur,v));check('等于下界仍需当前资格且产生新切点',fresh!=auth_projection)
        reject('等于下界也不能复用旧切点',lambda:T.T.preview(c,lambda:M.planned(c,v,o,cut,pid,provider,ur)),'authorization_current_projection')
        vv,oo=clone(v),clone(o);attach(vv,oo,fresh)
        check('重选新切点可规划',len(T.T.preview(c,lambda:M.planned(c,vv,oo,cut,pid,provider,ur)))==19)
        tx(c,lambda:M.install_floor(c,equal));check('同事件重传幂等',c.execute('SELECT count(*) FROM authorization_floor_event').fetchone()[0]==1)
        changed=floor(u,revision='7');reject('同事件不同内容拒绝',lambda:tx(c,lambda:M.install_floor(c,changed)),'authorization_floor_identity')
        tx(c,lambda:M.install_floor(c,floor(u,revision='5',eid='high')));tx(c,lambda:M.install_floor(c,floor(u,revision='1',eid='low')))
        reject('乱序低下界不覆盖高下界',lambda:T.T.preview(c,lambda:M.read(c,ur,v)),'authorization_revision_floor')
        for table in ('authorization_use','authorization_floor_event'):
            reject('禁止删除:'+table,lambda table=table:tx(c,lambda:c.execute('DELETE FROM '+table)))
        c=fork(db)
        def partial_floor():
            M.install_floor(c,floor(u));raise ValueError('fault_after_floor')
        reject('撤销写后事务失败回滚',lambda:tx(c,partial_floor),'fault_after_floor')
        check('失败事务不留下半个撤销',c.execute('SELECT count(*) FROM authorization_floor_event').fetchone()[0]==0 and T.T.preview(c,lambda:M.read(c,ur,v))==auth_projection)
        # 两个相邻大整数不能经float合并；下界相等与低一位必须得到不同结果。
        c=fork(db);large=clone(u);large['use_id']='large'
        for owner in ('authorization_binding','snapshot'):large[owner]['subject_revision']='9007199254740993'
        large=M.sealed(large,'use_digest');tx(c,lambda:M.store_use(c,large))
        tx(c,lambda:M.install_floor(c,floor(large,revision='9007199254740993')))
        T.T.preview(c,lambda:M.read(c,use_ref(large),v));check('大整数下界精确相等可读')
        tx(c,lambda:M.install_floor(c,floor(large,revision='9007199254740994',eid='next')))
        reject('大整数低一位拒绝',lambda:T.T.preview(c,lambda:M.read(c,use_ref(large),v)),'authorization_revision_floor')
        for name,mutate,reason in [
            ('错误audience',lambda x:x['authorization_binding'].update(audience='other'),'authorization_audience'),
            ('旧epoch',lambda x:x['authorization_binding'].update(issuer_epoch='old'),'authorization_requester'),
            ('主体修订不符',lambda x:x['snapshot'].update(subject_revision='3'),'authorization_snapshot_subject_revision'),
            ('非active',lambda x:x['snapshot'].update(state='revoked'),'authorization_permission'),
            ('缺执行权限',lambda x:x['snapshot'].update(permissions=[]),'authorization_permission'),
            ('过期等号',lambda x:x.update(authorization_before_tick_ns='52'),'authorization_window'),
            ('发送challenge后才计新鲜度',lambda x:x.update(received_tick_ns='1000001',authorization_before_tick_ns='2000000'),'authorization_window'),
            ('新clockdomain不能复用',lambda x:x['binding'].update(clock_domain_id='clock_'+'9'*64),'authorization_use_binding'),
            ('委托不能降级普通入口',lambda x:x['authorization_binding'].update(extension_instance_id='extension',extension_approval_revision='1'),'authorization_delegation_not_integrated')]:
            c=fork(db);bad=clone(u);bad['use_id']='bad';mutate(bad);bad=M.sealed(bad,'use_digest');tx(c,lambda:M.store_use(c,bad))
            reject(name,lambda:T.T.preview(c,lambda:M.read(c,use_ref(bad),v)),reason)
        for b,reason in [(b' '+M.raw(u),'authorization_body_digest'),(b'{"use_id":"duplicate",'+M.raw(u)[1:],'authorization_duplicate_key')]:
            reject('严格正文:'+reason,lambda b=b:M.decode('AuthorizationUse',b,u['use_digest'],'use_digest'),reason)
        c=fork(db);late=clone(u);late.update(use_id='late',authorization_before_tick_ns='2000000',received_tick_ns='999999')
        late=M.sealed(late,'use_digest');tx(c,lambda:M.store_use(c,late))
        lv=clone(v);lv.update(selected_tick_ns='1000000',sealed_tick_ns='1000000');lv=M.F.seal(lv)
        actual=T.T.preview(c,lambda:M.read(c,use_ref(late),lv))
        check('慢响应仍以发送tick计算剩余新鲜度',actual['body']['before_tick_ns']=='1000001')
        lv=M.F.seal(dict(lv,sealed_tick_ns='1000001'))
        reject('新鲜度截止等号拒绝而不从接收延长',lambda:T.T.preview(c,lambda:M.read(c,use_ref(late),lv)),'authorization_window')
        c=fork(db)
        def fill():
            for i in range(4097):M.install_floor(c,floor(u,revision='4',eid='bounded.'+str(i)))
        tx(c,fill)
        reject('撤销事件超容量保护而非截断放行',lambda:T.T.preview(c,lambda:M.read(c,ur,v)),'authorization_floor_capacity')
        c=fork(db);event=floor(u,revision='4');tx(c,lambda:M.install_floor(c,event))
        reject('不可更新已有下界',lambda:tx(c,lambda:c.execute("UPDATE authorization_floor_event SET revision_floor='00000000000000000000'")))
        # 实际文件库双连接：在封存读取事务持锁期间撤销不能越过它；提交后撤销先于下次规划。
        logdir=(ROOT/'logs').resolve();logdir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='leafseamer-auth-',dir=logdir) as directory:
            assert Path(directory).resolve().parent==logdir
            a=sqlite3.connect(str(Path(directory)/'candidate.sqlite'),isolation_level=None,timeout=0);db.backup(a)
            b=sqlite3.connect(str(Path(directory)/'candidate.sqlite'),isolation_level=None,timeout=0)
            try:
                a.execute('BEGIN IMMEDIATE');M.planned(a,v,o,cut,pid,provider,ur)
                reject('另一个writer不能越过当前封存事务',lambda:b.execute('BEGIN IMMEDIATE'),'locked')
                a.commit();tx(b,lambda:M.install_floor(b,floor(u)))
                reject('提交后下一次规划必须见撤销',lambda:tx(a,lambda:M.planned(a,v,o,cut,pid,provider,ur)),'authorization_revision_floor')
            finally:
                a.close();b.close()
        # manual会话撤销独立于组织run；这里只读实际持久授权行，不声称manual完整编码已贯通。
        mv,mo,mc=T.V.fixture();mu=use(mv);mu=M.sealed(dict(mu,received_tick_ns='50'),'use_digest')
        manual=sqlite3.connect(':memory:',isolation_level=None);dbs.append(manual)
        manual.executescript('CREATE TABLE controller_scope(singleton,authority_service_id,database_instance_id); INSERT INTO controller_scope VALUES(1,\'controller\',\'database\');'+(HERE/'final-authorization.sql').read_text('utf-8'))
        tx(manual,lambda:M.store_use(manual,mu));tx(manual,lambda:M.read(manual,use_ref(mu),mv));check('manual完整会话绑定可读取')
        tx(manual,lambda:M.install_floor(manual,floor(mu,'session')))
        reject('会话撤销阻断manual使用',lambda:tx(manual,lambda:M.read(manual,use_ref(mu),mv)),'authorization_revision_floor')
        check('组织自动化不依赖人员session',all(x[0]!='session' for x in M.dependencies(u['authorization_binding'])))
        check('四个最终阻断保持',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        check('最终issue及封存未产生',db.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==db.execute('SELECT count(*) FROM fa_seal').fetchone()[0]==0)
        for c in dbs:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        check('连接事务和外键完整');return checks
    finally:
        for c in dbs:c.close()

def inputs():return list(dict.fromkeys(T.inputs()+G.SOURCES+[HERE/n for n in ('final-authorization.schema.json','final-authorization.sql','final_authorization_model.py','check_final_authorization.py','FINAL_AUTHORIZATION.md')]+[ROOT/'docs/rebirth-f04-f05-design.md',ROOT/'docs/rebirth-df04-storage-design.md']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'final-authorization-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),candidate_tables=244,local_file_two_writer_order_verified=True,
            authority_authenticity_verified=False,scope_evidence_verified=False,utc_validity_evidence_verified=False,full_final_issue_executed=False,
            runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
