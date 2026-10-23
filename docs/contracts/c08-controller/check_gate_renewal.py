"""换闸候选的内存约束和IPC结构检查；不执行真实网络或设备。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
import build_gate_renewal as G
import check_open_storage as S
import check_scoped_gate as Q
U,F,I,u,B,D=S.U,S.F,S.I,S.u,S.B,S.H
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(Q.input_paths(Q.old_frames()[1])+G.SOURCES+[HERE/n for n in
 ('GATE_RENEWAL.md','check_gate_renewal.py','controller-gate-renewal.sql','gate-renewal-ipc.schema.json')]))

def gate(gid='gate.1',previous=None,rev=1,wire=1,phase='fenced',ready=None,renewal=None):
    step=S.gate(gid,previous,rev,wire,phase,ready)
    step[1].update(control_barrier_id=step[1]['barrier_id'] if renewal is None else None,renewal_id=renewal)
    if renewal:step[1]['barrier_id']=renewal
    return step

def fresh():
    db=sqlite3.connect(':memory:',isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(G.sql().decode())
    db.execute("INSERT INTO controller_scope VALUES(1,'controller','database.1','controller-storage/0.1.0-draft.1')")
    U.tx(db,U.mutate(F.adapt([F.F.exit_step()]),'ce_exit',clock_domain_id='domain',descriptor_digest='descriptor'))
    U.tx(db,U.bootstrap(db));U.tx(db,U.offer(db));U.tx(db,F.start(db,members=(),exits=('exit.0',),water=0))
    U.tx(db,U.mutate(F.ack(members=()),'cu_ack',issued_revision=u(0)))
    U.tx(db,F.effective(db,members=(),exits=('exit.0',)))
    U.tx(db,[gate()]);U.tx(db,S.protect(db,gid='gate.1'));U.tx(db,S.close_ack())
    return db

def request(db,rid='renew',previous='gate.1',ack='close.ack',wire=2,tick=42,seq=1):
    return [I('gf_request',request_id=rid,device_id='device',exit_id='exit.0',previous_gate_id=previous,
      authority_state_id=db.execute('SELECT change_id FROM go_authority').fetchone()[0],control_state_id=U.current(db)['change_id'],
      close_ack_id=ack,safety_revision=db.execute("SELECT max(revision) FROM go_hazard WHERE device_id='device'").fetchone()[0],
      target_revision=u(wire),gate_token='token.'+str(wire),message_id='request.'+rid,outbound_seq=u(seq),
      selected_tick=u(tick),expires_tick=u(tick+10),lease_until_tick=u(100),request_digest=D,body=B,outbox_body=B,audit_body=B)]

def ack(rid='renew',aid='renew.ack',wire=2,tick=44,seq=1):
    return [I('gf_ack',ack_id=aid,request_id=rid,exit_id='exit.0',message_id=aid,reply_to='request.'+rid,inbound_seq=u(seq),
      request_digest=D,gate_revision=u(wire),gate_token='token.'+str(wire),effective_tick=u(tick-1),received_tick=u(tick),
      evidence_digest=D,observer_ref='fixture.observer',body=B,validation_body=B,audit_body=B)]

def commit(rid='renew',aid='renew.ack',gid='gate.2',previous='gate.1',rev=2,wire=2,tick=45):
    return [gate(gid,previous,rev,wire,renewal=rid),I('gf_commit',request_id=rid,ack_id=aid,gate_id=gid,
      committed_tick=u(tick),audit_body=B,outbox_body=B)]

def run():
    assert (HERE/'controller-gate-renewal.sql').read_bytes()==G.sql(),'生成SQL漂移'
    ipc=G.ipc();assert (HERE/'gate-renewal-ipc.schema.json').read_bytes()==G.S.encoded(ipc),'生成IPC漂移'
    Draft202012Validator.check_schema(ipc)
    checks=[];connections=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,observed=actual,expected=expected))
    def stage(level='acked'):
        db=fresh();connections.append(db)
        if level=='base':return db
        U.tx(db,request(db))
        if level=='requested':return db
        U.tx(db,ack())
        if level=='acked':return db
        U.tx(db,commit());return db
    def denied(name,db,steps,error=None):
        before=U.snapshot(db)
        try:U.tx(db,steps)
        except sqlite3.IntegrityError as exc:
            if error:assert str(exc)==error,(name,str(exc),error)
            check(name,U.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+name)
    try:
        old=S.fresh();connections.append(old);U.tx(old,[S.gate()])
        U.tx(old,[S.gate('forged','gate.1',2,2)])
        check('旧布局复现复用ACK提高闸修订',old.execute("SELECT gate_revision FROM go_current_gate").fetchone()[0],u(2))
        db=stage('base');denied('新版拒绝旧ACK提高闸修订',db,[gate('forged','gate.1',2,2)],'open_gate_barrier')
        check('共享组合186表',db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],186)
        db=stage('sealed');check('独立屏障采用仍protected',U.current(db)['gate_state'],'protected')
        check('采用不制造普通ready',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        check('有效屏障原件',db.execute('SELECT request_id FROM gf_valid_fence').fetchall(),[('renew',)])
        check('采用不改变控制授权',db.execute('SELECT change_id FROM go_authority').fetchall(),[('effective',)])
        db=stage('sealed');U.tx(db,S.recovery(db))
        check('恢复新安全代次保留已安装屏障',db.execute('SELECT count(*) FROM gf_valid_fence').fetchone()[0],1)
        U.tx(db,S.plan('plan.2','snap.2','gate.2','protect','recover',46));U.tx(db,S.dispatch('plan.2','dispatch.2',47,2))
        U.tx(db,S.evidence('dispatch.2','evidence.2',48,2,2))
        steps=S.ready(db,'ready.2','plan.2','evidence.2','gate.3','gate.2',3,2,49)
        steps=U.mutate(steps,'go_gate',barrier_id='renew',control_barrier_id=None,renewal_id='renew')
        U.tx(db,steps)
        check('新屏障接普通恢复及T5',db.execute('SELECT ready_id FROM go_ready_candidate').fetchall(),[('ready.2',)])
        U.tx(db,[I('gf_revocation',ack_id='renew.ack',reason_body=B,audit_body=B)])
        check('已开放后撤回屏障撤资格',db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0],0)
        for name,level,make in [('请求','base',request),('原ACK','requested',lambda db:ack()),('采用','acked',lambda db:commit())]:
            for index in range(len(make(stage(level)))):
                db=stage(level);steps=make(db)
                if len(steps)>1:denied(name+'缺写'+str(index),db,steps[:index]+steps[index+1:])
                before=U.snapshot(db)
                try:U.tx(db,steps,fault=index)
                except RuntimeError as exc:assert str(exc)=='injected'
                else:raise AssertionError('未触发主动异常')
                check(name+'主动异常'+str(index),U.snapshot(db)==before)
        for field,value in [('previous_gate_id',None),('authority_state_id','base'),('control_state_id','effective'),
          ('target_revision',u(1)),('gate_token','token.1'),('selected_tick',u(40)),('safety_revision',u(0)),('device_id','other')]:
            db=stage('base');denied('请求错配:'+field,db,U.mutate(request(db),'gf_request',**{field:value}),'gate_fence_request')
        for field,value in [('request_digest','wrong'),('reply_to','wrong'),('gate_revision',u(9)),('gate_token','wrong'),
          ('exit_id','other'),('effective_tick',u(41)),('received_tick',u(42))]:
            db=stage('requested');denied('ACK错配:'+field,db,U.mutate(ack(),'gf_ack',**{field:value}),'gate_fence_ack')
        for tick,ok in [(44,True),(51,True),(52,False),(53,False)]:
            db=stage()
            if ok:U.tx(db,commit(tick=tick));check('采用期限内:'+str(tick),True)
            else:denied('采用到期:'+str(tick),db,commit(tick=tick),'gate_fence_commit')
        db=stage('requested');U.tx(db,ack(tick=60));check('迟到ACK保留历史',db.execute('SELECT count(*) FROM gf_ack').fetchone()[0],1)
        denied('迟到ACK不得采用',db,commit(tick=60),'gate_fence_commit')
        for action in ('new_close','revoke_close','revoke_ack'):
            db=stage()
            steps=commit()
            if action=='new_close':changes=S.protect(db,'protect.2','close.2',2,'gate.2')
            elif action=='revoke_close':changes=[I('go_revocation',kind='close_ack',object_id='close.ack',reason_body=B,audit_body=B)]
            else:changes=[I('gf_revocation',ack_id='renew.ack',reason_body=B,audit_body=B)]
            denied('选择后改变:'+action,db,steps[:1]+changes+steps[1:],'gate_fence_commit')
        db=stage('sealed');before=U.snapshot(db)
        denied('同采用不得再次提交',db,commit())
        denied('同关闭ACK不得换新请求',db,request(db,'other','gate.2',wire=3))
        U.tx(db,[I('gf_revocation',ack_id='renew.ack',reason_body=B,audit_body=B)])
        check('撤回后原件不再有效',db.execute('SELECT count(*) FROM gf_valid_fence').fetchone()[0],0)
        check('撤回保留闸历史',db.execute('SELECT count(*) FROM go_gate').fetchone()[0],2)
        check('撤回进入共享安全代次',db.execute("SELECT count(*) FROM go_hazard WHERE source_kind='gate_fence'").fetchone()[0],1)
        denied('伪造安全来源',db,[I('go_hazard',device_id='device',revision=u(int(db.execute('SELECT max(revision) FROM go_hazard').fetchone()[0])+1),source_kind='gate_fence',source_id='fake')],'hazard_source')
        for table in G.TABLES:
            row=db.execute('SELECT * FROM '+table).fetchone();assert row is not None
            cols=[x[1] for x in db.execute('PRAGMA table_info('+table+')')]
            for action in ('update','delete','replace'):
                before=U.snapshot(db);db.execute('BEGIN IMMEDIATE')
                try:
                    if action=='update':db.execute(f'UPDATE {table} SET {cols[0]}={cols[0]}')
                    elif action=='delete':db.execute('DELETE FROM '+table)
                    else:db.execute('INSERT OR REPLACE INTO '+table+' VALUES('+','.join('?' for _ in row)+')',row)
                    db.execute('COMMIT')
                except sqlite3.IntegrityError:db.execute('ROLLBACK');check(table+':'+action,U.snapshot(db)==before)
                else:raise AssertionError('不可变性失效:'+table)
        # 新关闭、新请求与新ACK可以建立下一代；控制及资源恢复仍是另一事务。
        db=stage('sealed');U.tx(db,S.protect(db,'protect.2','close.2',2,'gate.2'));U.tx(db,S.close_ack('close.2','close.ack.2',46))
        U.tx(db,request(db,'renew.2','gate.2','close.ack.2',3,47,2));U.tx(db,ack('renew.2','renew.ack.2',3,49,2))
        U.tx(db,commit('renew.2','renew.ack.2','gate.3','gate.2',3,3,50))
        check('新关闭后仅新屏障有效',db.execute('SELECT request_id FROM gf_valid_fence').fetchall(),[('renew.2',)])
        db=stage('requested');U.tx(db,S.protect(db,'protect.2','close.2',2,'gate.1'));U.tx(db,S.close_ack('close.2','close.ack.2',46))
        denied('未知请求不复用修订',db,request(db,'renew.2','gate.1','close.ack.2',2,47,2))
        denied('未知请求不复用token',db,U.mutate(request(db,'renew.2','gate.1','close.ack.2',3,47,2),'gf_request',gate_token='token.2'))
        U.tx(db,request(db,'renew.2','gate.1','close.ack.2',3,47,2));U.tx(db,ack('renew.2','renew.ack.2',3,49,2))
        U.tx(db,commit('renew.2','renew.ack.2','gate.2','gate.1',2,3,50))
        U.tx(db,ack(tick=51))
        check('新代采用后迟到旧ACK只存历史',db.execute('SELECT count(*) FROM gf_ack').fetchone()[0],2)
        denied('迟到旧代不覆盖新闸',db,commit(gid='gate.3',previous='gate.2',rev=3,tick=51))
        check('四个最终签发阻断仍存在',db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0],4)
        # 每个旧帧的形状保留：Q的原夹具只用于结构，不冒充完整消息语义。
        old_ipc=G.S.ipc(G.S.schema())
        for branch in old_ipc['oneOf']:
            name=branch['$ref'].split('/')[-1];old=copy.deepcopy(old_ipc['$defs'][name]);new=copy.deepcopy(ipc['$defs'][name])
            old['properties']['ipc_version']=new['properties']['ipc_version'];check('保留旧帧结构:'+name,new==old)
        check('新版完整消息数量',len(ipc['oneOf']),48)
        validator=Draft202012Validator(ipc)
        for frame in Q.upgrade_frames(Q.old_frames()[0]):
            frame['ipc_version']=G.VERSION
            if frame['type']=='HELLO':
                frame['body']['supported_ipc_versions']=[G.VERSION];frame['body']['supported_features'].append('fresh_gate_fence')
            if frame['type']=='HELLO_ACK':
                frame['body']['selected_ipc_version']=G.VERSION;frame['body']['selected_features'].append('fresh_gate_fence')
            check('旧帧新版结构:'+frame['type'],validator.is_valid(frame))
        # 具体新帧结构正反例；关联和有效期由上述SQL另验，二者非端到端。
        _,_,_,ctx=Q.fixture()[:4]
        binding=ctx['binding'];ref=lambda key:dict(id=key,revision='1',digest=D)
        request_body=dict(request_id='renew',binding=binding,control_authority_ref=ref('effective'),before_gate_ref=ref('gate.1'),close_ack_ref=ref('close.ack'),
          target_gate_revision='2',gate_token='token.2',selected_tick_ns='42',expires_tick_ns='52',lease_until_tick_ns='100',request_digest=D)
        ack_body=dict(request_id='renew',request_digest=D,binding=binding,gate_revision='2',gate_token='token.2',effective_tick_ns='43',state='fenced')
        for name,body,reply in [('GATE_FENCE',request_body,None),('GATE_FENCE_ACK',ack_body,'request.renew')]:
            frame={k:binding[k] for k in ('ipc_session_id','controller_boot_id','worker_boot_id','device_id','clock_domain_id','descriptor_digest')}
            frame.update(ipc_version=G.VERSION,type=name,message_id='message',reply_to=reply,seq='1',body=body)
            validator=Draft202012Validator(ipc);check(name+'结构正例',validator.is_valid(frame))
            for key in body:
                bad=copy.deepcopy(frame);del bad['body'][key];check(name+'缺字段:'+key,validator.is_valid(bad),False)
            for key,value in [('ipc_version',G.S.VERSION),('seq','0')]:
                bad=copy.deepcopy(frame);bad[key]=value;check(name+'拒绝:'+key,validator.is_valid(bad),False)
        for db in connections:
            check('外键完整性',db.execute('PRAGMA foreign_key_check').fetchall(),[])
            check('数据库完整性',db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
    finally:
        for db in connections:db.close()
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'gate-renewal-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),tables=186,sqlite_version=sqlite3.sqlite_version,
          scope='独立换闸屏障与一次采用的内存约束及48帧结构',runtime_tests_executed=0,device_tests_executed=0,
          concurrency_tests_executed=0,disk_crash_tests_executed=0,checks=checks,
          inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
