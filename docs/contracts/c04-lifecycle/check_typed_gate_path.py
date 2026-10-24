"""完整类型化受理到首次开放候选的SQL正向链与故障检查；无设备I/O。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
import check_typed_command_view as V
import check_continuation_storage as CS
import check_attempt_inventory as AI
import typed_gate_path_model as M

HERE=M.G.HERE;ROOT=HERE.parents[2]
STAGES=('register','session','close_ack','close_preparations','renew','fence_write','fence_ack','fence_commit','recovery','plan','dispatch','open_write','evidence','ready')

def steps(name,db,c):
    if name in ('fence_write','open_write'):return M.write(c,'fence.message' if name=='fence_write' else 'open.message',14 if name=='fence_write' else 20)
    if name in ('register','session','renew','recovery','plan','ready'):return getattr(M,name)(db,c)
    return getattr(M,name)(c)

def mutate(writes,table,**patch):
    out=[];found=False
    for sql,args in writes:
        if sql.startswith('INSERT INTO '+table+' '):
            fields=sql.split('(',1)[1].split(')',1)[0].split(',');row=dict(zip(fields,args));row.update(patch);out.append(M.I(table,**row));found=True
        else:out.append((sql,args))
    assert found,table
    return out

def run():
    checks=[];dbs=[];saved={}
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fork(db):
        out=sqlite3.connect(':memory:',isolation_level=None);db.backup(out)
        out.execute('PRAGMA foreign_keys=ON');out.execute('PRAGMA recursive_triggers=ON');dbs.append(out);return out
    def reject(name,db,writes,reason=None,fault=None):
        before=V.SC.snapshot(db)
        try:M.execute(db,writes,fail_after=fault)
        except (ValueError,RuntimeError,sqlite3.IntegrityError) as err:
            if reason:assert reason in str(err),(name,str(err))
            check(name,not db.in_transaction and V.SC.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+name)
    def candidate(db):return db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0]
    def end(c):return [M.I('ij_end',end_id=M.key(c,'end'),session_id=M.key(c,'session'),reason='peer_lost',cause_frame_id=None,observed_tick=M.u('22'),evidence_body=M.B,audit_body=M.B)]
    try:
        d,cds,items,_=V.fixture(controller_factory=M.G.build);dbs=[d]+[x[0] for x in cds.values()]
        for item_index,item in enumerate(items):
            db=item[0];ad=V.M.decide(*item);command=ad['command_ref']['object_id'];c=M.context(db,command)
            original=V.M.read(db,command,V.reader(item))['record'];before_control=M.current(db,c);grant=bytes(db.execute('SELECT grant_body FROM cr_current').fetchone()[0])
            schema=tuple(tuple(row) for row in db.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name'))
            check('242表布局'+str(item_index),len(V.SC.snapshot(db))==242)
            for name in STAGES:
                if item_index==0:saved[name]=(fork(db),copy.deepcopy(c))
                writes=steps(name,db,c)
                if item_index==0:
                    for index in range(len(writes)):reject('逐写异常全库回滚:'+name+':'+str(index),db,writes,'injected',index)
                M.execute(db,writes)
                check('事务提交:'+str(item_index)+':'+name,not db.in_transaction and not db.execute('PRAGMA foreign_key_check').fetchone())
                if name!='ready':check('中间阶段不提前开放:'+str(item_index)+':'+name,candidate(db)==0)
            check('同库完整开放候选'+str(item_index),candidate(db)==1)
            check('两个方向共六帧日志'+str(item_index),db.execute('SELECT count(*) FROM ij_frame').fetchone()[0]==6)
            check('三次真实SQL写尝试及结果'+str(item_index),db.execute('SELECT count(*) FROM ij_write_attempt').fetchone()[0]==3 and db.execute('SELECT count(*) FROM ij_write_result').fetchone()[0]==3)
            check('所有消息均有领域提交'+str(item_index),db.execute('SELECT count(*) FROM ij_commit').fetchone()[0]==6)
            check('命令保持原queued记录'+str(item_index),V.M.read(db,command,V.reader(item))['record']==original and original['state']['phase']=='queued')
            after=M.current(db,c)
            check('控制权及holder不变'+str(item_index),all(after[k]==before_control[k] for k in ('control_epoch','effective_version','reserved_version','mode','holder_issuer','holder_epoch','holder_id','pending_operation_id')))
            check('原continuation正文不变'+str(item_index),bytes(db.execute('SELECT grant_body FROM cr_issue').fetchone()[0])==grant)
            check('先grant后改控制修订会失效'+str(item_index),db.execute('SELECT count(*) FROM cr_current').fetchone()[0]==0 and db.execute('SELECT count(*) FROM cn_live_command').fetchone()[0]==0)
            reject('失效历史命令不得新建attempt'+str(item_index),db,[M.I('ce_attempt',attempt_id='forbidden',command_id=command,authorization_body=M.B,attempt_body=M.B)],'continuation_command_revoked')
            check('无许可或发送冒充'+str(item_index),all(db.execute('SELECT count(*) FROM '+t).fetchone()[0]==0 for t in ('ci_issue','ce_permit','fa_seal','ce_transmission_commit')))
            check('DDL及全部守卫未改'+str(item_index),schema==tuple(tuple(row) for row in db.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name')))
            if item_index==0:saved['complete']=(fork(db),c)
        # 丢失必需的同事务领域行必须回滚；合法可分阶段保存的日志写尝试不在此混称漏写。
        for name in ('register','renew','fence_ack','fence_commit','recovery','plan','dispatch','evidence','ready'):
            base,c=saved[name];db=fork(base);writes=steps(name,db,c)
            for index in range(len(writes)):reject('必要同事务行漏写:'+name+':'+str(index),db,writes[:index]+writes[index+1:])
        # 完整closure与其close completion可独立提交，但缺completion绝不可恢复。
        base,c=saved['close_preparations'];db=fork(base);M.execute(db,M.close_preparations(c)[:-1])
        for name in ('renew','fence_write','fence_ack','fence_commit'):M.execute(db,steps(name,db,c))
        reject('空准备集合仍须关闭完成证明',db,M.recovery(db,c),'prepare_close_not_complete')
        base,c=saved['renew'];db=fork(base)
        reject('续闸前已终止会话',db,end(c)+M.renew(db,c),'journal_session_ended')
        for table,field,value in [('ij_frame','session_id','other'),('ij_frame','device_id','dev.2'),('gf_request','exit_id','other'),('gf_request','control_state_id','base.dev.1')]:
            reject('换闸身份绑定:'+table+':'+field,db,mutate(M.renew(db,c),table,**{field:value}))
        base,c=saved['fence_ack'];db=fork(base)
        for field,value in [('request_digest',M.digest('other')),('gate_token','other'),('gate_revision',M.u('2')),('reply_to','other')]:
            reject('换闸ACK错绑:'+field,db,mutate(M.fence_ack(c),'gf_ack',**{field:value}))
        base,c=saved['fence_write'];db=fork(base);reject('未有写尝试不能采用换闸ACK',db,M.fence_ack(c),'journal_reply_binding')
        base,c=saved['fence_ack'];db=fork(base);M.execute(db,M.fence_ack(c,disposition='historical'))
        reject('历史换闸ACK不得安装',db,M.fence_commit(c),'journal_adoption_not_current')
        base,c=saved['fence_commit'];db=fork(base)
        reject('换闸期限等号拒绝',db,M.fence_commit(c,30),'gate_fence_commit')
        base,c=saved['open_write'];db=fork(base);reject('OPEN未有写尝试不能收ACK',db,M.evidence(c),'journal_reply_binding')
        reject('OPEN写尝试等号到期拒绝',db,M.write(c,'open.message',80),'journal_send_not_current')
        base,c=saved['evidence'];db=fork(base)
        for field,value in [('gate_token','other'),('gate_revision',M.u('2')),('run_snapshot_ref','other'),('command_snapshot_ref','other'),('time_snapshot_ref','other'),('reply_to','other')]:
            reject('OPEN回执错绑:'+field,db,mutate(M.evidence(c),'go_evidence',**{field:value}))
        M.execute(db,M.evidence(c,disposition='historical'));reject('历史OPEN不得Ready',db,M.ready(db,c),'journal_adoption_not_current')
        base,c=saved['ready'];db=fork(base)
        reject('Ready期限等号拒绝',db,M.ready(db,c,80),'open_ready_binding')
        reject('Ready早于ACK拒绝',db,M.ready(db,c,20),'open_ready_binding')
        reject('Ready时换时钟域拒绝',db,mutate(M.ready(db,c),'ct_change',clock_domain='other'),'open_clock_order')
        reject('Ready前会话结束整组拒绝',db,end(c)+M.ready(db,c),'journal_adoption_not_current')
        for kind,obj in [('open_ack','open.ack'),('close_ack','close.ack')]:
            db=fork(base);revoke=M.I('go_revocation',kind=kind,object_id=M.key(c,obj),reason_body=M.B,audit_body=M.B)
            reject('Ready最终seal前撤回:'+kind,db,M.ready(db,c)[:-1]+[revoke]+M.ready(db,c)[-1:])
        base,c=saved['complete'];db=fork(base);M.execute(db,end(c));check('Ready后会话结束撤销候选',candidate(db)==0 and db.execute('SELECT count(*) FROM go_ready').fetchone()[0]==1)
        for kind,obj in [('open_ack','open.ack'),('close_ack','close.ack'),('fence','fence.ack')]:
            db=fork(base)
            row=M.I('gf_revocation',ack_id=M.key(c,obj),reason_body=M.B,audit_body=M.B) if kind=='fence' else M.I('go_revocation',kind=kind,object_id=M.key(c,obj),reason_body=M.B,audit_body=M.B)
            M.execute(db,[row]);check('Ready后证据撤回撤销候选:'+kind,candidate(db)==0 and db.execute('SELECT count(*) FROM go_ready').fetchone()[0]==1)
        # 仅在夹具依赖边界插入真实启动写集；不替换任何模型、SQL守卫或提供者判定。
        seed=CS.controller_seed
        def seeded(p,sql_factory):
            db,target=seed(p,sql_factory)
            for device in target['devices']:
                dev=device['device_id'];c=dict(device=dev,prefix='startup.'+dev,exit='startup.'+dev+'.exit')
                for name in STAGES:M.execute(db,steps(name,db,c))
                state=M.current(db,c)
                device['control_ref']=CS.ref(target['controller_scope'],state['change_id'],state['record_digest'],str(int(state['record_revision'])))
            return db,target
        with patch.object(CS,'controller_seed',side_effect=seeded):
            d,cds,items,_=V.fixture(controller_factory=M.G.build)
        dbs.extend([d]+[x[0] for x in cds.values()])
        for index,item in enumerate(items):
            db=item[0];check('启动先开放后签grant:'+str(index),candidate(db)==2 and db.execute('SELECT count(*) FROM cr_current').fetchone()[0]==1)
            result=V.M.decide(*item);cmd=result['command_ref']['object_id']
            check('开放后真实类型化命令受理:'+str(index),result['decision']=='accepted' and db.execute('SELECT count(*) FROM cn_live_command WHERE command_id=?',(cmd,)).fetchone()[0]==1)
            check('受理后grant及开放候选共存:'+str(index),candidate(db)==2 and db.execute('SELECT count(*) FROM cr_current').fetchone()[0]==1)
            AI.publish(db,cmd,V.reader(item),prepare=True)
            record=AI.S.read(db,cmd,V.reader(item))['record']
            check('受理后持久attempt与开放候选共存:'+str(index),record['revision']=='2' and len(record['attempts'])==1 and candidate(db)==2)
            check('prepared仍保留当前来源资格:'+str(index),db.execute('SELECT count(*) FROM cn_live_command WHERE command_id=?',(cmd,)).fetchone()[0]==1)
            check('启动正向链仍无最终许可:'+str(index),db.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==0)
        for db in dbs:assert not db.in_transaction and not db.execute('PRAGMA foreign_key_check').fetchone()
        check('全部实验连接无悬挂事务且外键完整')
        return checks
    finally:
        for db in dbs:db.close()

def inputs():return list(dict.fromkeys(V.inputs()+AI.inputs()+M.G.SOURCES+[HERE/n for n in ('final_admission_storage_model.py','final_admission_model.py','build_final_admission.py','final-admission.schema.json','typed_gate_path_model.py','check_typed_gate_path.py','TYPED_GATE_PATH.md','controller-final-admission.sql')] ))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'typed-gate-path-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=242,sql_positive_ready_path_executed=True,sql_grant_ready_prepared_path_executed=True,
            sql_positive_issue_path_executed=False,production_clearance=False,provider_evidence='synthetic',runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(V.M.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
