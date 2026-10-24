"""当前continuation、完整编码帧、packet和固定库存的同库正向及故障实验。"""
import argparse,copy,hashlib,json,sqlite3
from unittest.mock import patch
from jsonschema.exceptions import ValidationError
import check_typed_gate_path as T
import typed_encoding_path_model as M
V=T.V;O=M.O;G=M.G;AI=T.AI;HERE=G.HERE;ROOT=HERE.parents[2]

def fixture():
    seed=T.CS.controller_seed;bootstrap=T.CS.U.bootstrap;session=O.session
    def clocked(*args,**kw):
        rows=bootstrap(*args,**kw)
        for table,row in rows:
            if table=='ct_change':row.update(clock_domain='clock_'+'1'*64,descriptor=M.digest('synthetic_clock'))
        return rows
    def versioned(db,c):return T.mutate(session(db,c),'ij_session',protocol_version='ipc/0.14.0-continuation-draft.1')
    def seeded(p,sql_factory):
        db,target=seed(p,sql_factory)
        for device in target['devices']:
            dev=device['device_id'];tag=dev.replace('.','_');c=dict(device=dev,prefix='startup_'+tag,exit='exit_'+tag)
            for name in T.STAGES:
                rows=T.steps(name,db,c)
                if name=='register':rows=T.mutate(rows,'ce_exit',controller_boot_id='controller_'+tag,worker_boot_id='worker_'+tag,ipc_session_id='ipc_'+tag,device_session_id='device_'+tag)
                O.execute(db,rows)
            state=O.current(db,c);device['control_ref']=T.CS.ref(target['controller_scope'],state['change_id'],state['record_digest'],str(int(state['record_revision'])))
        O.execute(db,[M.I('ep_limit',singleton=1,profile_id='synthetic.encoding',profile_revision=M.u('1'),profile_digest=M.digest('profile'),max_live_prepares=4,max_metadata_prepares=8,max_live_bytes=1024,profile_body=M.B)])
        return db,target
    with patch.object(T.CS.U,'bootstrap',side_effect=clocked),patch.object(O,'session',side_effect=versioned),patch.object(T.CS,'controller_seed',side_effect=seeded):
        d,cds,items,_=V.fixture(controller_factory=G.build)
    return d,cds,items

def provider(db,command,attempt,exit_id):
    db.execute('BEGIN')
    try:s=M.source(db,command,attempt,exit_id)
    finally:db.rollback()
    p=dict(binding=s['binding'],primitive_id='synthetic_primitive',max_bytes=64,expires_tick_ns='70',socket_instance_id='synthetic_socket',protocol_session='synthetic_protocol')
    p.update({k:M.ref('synthetic_'+k) for k in ('authorization_snapshot_ref','capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref')})
    p.update({k:True for k in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified')})
    return p

def preview(db,fn):
    db.execute('BEGIN IMMEDIATE')
    try:return fn()
    finally:db.rollback()

def revoke(pid='prepare_typed',tick=34):
    return M.I('ep_revocation',prepare_id=pid,revocation_id=pid+'.revoke',revocation_revision=M.u('1'),revocation_digest=M.digest('revoke'),revoked_tick=M.u(str(tick)),reason_body=M.B,audit_body=M.B,outbox_id=pid+'.revoke',outbox_body=M.B)

def run():
    checks=[];dbs=[];saved={};pid='prepare_typed'
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fork(db):
        out=sqlite3.connect(':memory:',isolation_level=None);db.backup(out);out.execute('PRAGMA foreign_keys=ON');out.execute('PRAGMA recursive_triggers=ON');dbs.append(out);return out
    def reject(n,db,fn,reason=None):
        before=V.SC.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,not db.in_transaction and V.SC.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+n)
    def atomic(n,db,writes):
        for i in range(len(writes)):
            reject(n+'逐写异常'+str(i),db,lambda i=i:O.execute(db,writes,fail_after=i),'injected')
            reject(n+'必要行漏写'+str(i),db,lambda i=i:O.execute(db,writes[:i]+writes[i+1:]))
    try:
        check('生成SQL字节一致',(HERE/'controller-typed-encoding.sql').read_bytes()==G.build())
        baseline=sqlite3.connect(':memory:');baseline.executescript(G.B.build().decode());dbs.append(baseline)
        d,cds,items=fixture();dbs.extend([d]+[x[0] for x in cds.values()])
        changed={'ij_session','ep_open_request','te_base_ep_open_request','te_request_current','te_request_seal','te_reply_packet'}
        original={r[0]:r[1] for r in baseline.execute('SELECT name,sql FROM sqlite_schema') if r[0] not in changed}
        actual={r[0]:r[1] for r in items[0][0].execute('SELECT name,sql FROM sqlite_schema') if r[0] not in changed}
        check('除明确版本及编码收紧外全部DDL保持',actual==original)
        for idx,item in enumerate(items):
            db=item[0];ad=V.M.decide(*item);cmd=ad['command_ref']['object_id'];auth=V.reader(item);AI.publish(db,cmd,auth,prepare=True)
            before=AI.S.read(db,cmd,auth);attempt=before['record']['state']['attempt_ids'][0];eid='exit_'+before['record']['target']['device_id'].replace('.','_');p=provider(db,cmd,attempt,eid)
            oldschema=tuple(tuple(r) for r in db.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name'));check('完整242表'+str(idx),len(V.SC.snapshot(db))==242)
            a,rows=preview(db,lambda:M.authorize(db,cmd,attempt,eid,p))
            if idx==0:saved['base']=(fork(db),cmd,attempt,eid,p);atomic('编码授权登记',db,rows)
            M.transaction(db,lambda:M.authorize(db,cmd,attempt,eid,p))
            check('授权摘要使用已受理内容'+str(idx),a['content_digest']==item[1]['request_digest'] and a['content_digest']!=M.digest(item[2]))
            request,rows=preview(db,lambda:M.encoding(db,pid))
            if idx==0:saved['registered']=(fork(db),cmd,attempt,eid,p);atomic('编码日志出站',db,rows)
            M.transaction(db,lambda:M.encoding(db,pid));rows=preview(db,lambda:M.send(db,pid))
            if idx==0:saved['reserved']=(fork(db),cmd,attempt,eid,p)
            # ep_send_attempt需配日志attempt；日志write_result允许独立保存，不把缺结果判为事务失败。
            if idx==0:atomic('编码写尝试',db,rows)
            M.transaction(db,lambda:(None,M.send(db,pid)));O.execute(db,M.written(db,pid))
            response=M.response(request,p);rows=preview(db,lambda:M.receive(db,pid,response,p))
            if idx==0:saved['sent']=(fork(db),cmd,attempt,eid,p,request,response)
            if idx==0:
                for i in range(len(rows)):reject('编码响应逐写异常'+str(i),db,lambda i=i:O.execute(db,rows,fail_after=i),'injected')
                # ce_packet是本地映射，可延迟提交；其缺失不代表领域响应不完整。
                for i in range(len(rows)-1):reject('响应必需行漏写'+str(i),db,lambda i=i:O.execute(db,rows[:i]+rows[i+1:]))
            M.transaction(db,lambda:(None,M.receive(db,pid,response,p)))
            check('完整响应Schema'+str(idx),M.FRAME.is_valid(request) and M.FRAME.is_valid(response))
            check('原始packet字节与摘要一致'+str(idx),bytes(db.execute('SELECT packet_bytes FROM ep_reply').fetchone()[0])==b'\x01\x02' and json.loads(db.execute('SELECT packet_body FROM ce_packet').fetchone()[0])==response['body']['packet'])
            for row in db.execute("SELECT frame_body,wire_body,wire_digest FROM ij_frame WHERE domain_kind IN ('encoding_request','encoding_reply')"):
                f=bytes(row[0]);wire=bytes(row[1]);check('长度前缀及真实帧字节'+str(idx)+M.byte_digest(f),wire==len(f).to_bytes(4,'big')+f and M.byte_digest(wire)==row[2])
            check('旧公开库存不借新packet'+str(idx),AI.S.read(db,cmd,auth,'2')['record']==before['record'])
            AI.publish(db,cmd,auth);after=AI.S.read(db,cmd,auth)['record']
            check('新固定库存展示真实packet与出口'+str(idx),after['revision']=='3' and after['attempts'][0]['packet_refs']==[{k:response['body']['packet'][k] for k in ('packet_id','packet_digest')}] and len(after['attempts'][0]['exits'])==1)
            check('准备不冒充已发送'+str(idx),after['state']['effect_status']=='not_sent' and after['attempts'][0]['exits'][0]['send_started_at'] is None)
            check('grant开放与编码同时有效'+str(idx),db.execute('SELECT count(*) FROM cr_current').fetchone()[0]==1 and db.execute('SELECT count(*) FROM go_ready_candidate').fetchone()[0]==2 and db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0]==1)
            check('没有最终许可'+str(idx),db.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==0)
            check('运行中未改DDL'+str(idx),oldschema==tuple(tuple(r) for r in db.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name')))
            if idx==0:saved['prepared']=(fork(db),cmd,attempt,eid,p,request,response)
        base,cmd,attempt,eid,p=saved['base'];db=fork(base)
        for flag in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified'):
            reject('授权缺提供者:'+flag,db,lambda flag=flag:M.transaction(db,lambda:M.authorize(db,cmd,attempt,eid,dict(p,**{flag:False}))),'encoding_provider')
        _,rows=preview(db,lambda:M.authorize(db,cmd,attempt,eid,p))
        reject('编码保留字节超过总额度',db,lambda:M.transaction(db,lambda:M.authorize(db,cmd,attempt,eid,dict(p,max_bytes=1025))),'encoding_capacity')
        withdrawn=M.I('cr_revocation',transfer_id='transfer',proof_body=M.B,audit_body=M.B,outbox_body=M.B)
        reject('登记最后commit前撤回来源',db,lambda:O.execute(db,rows[:-1]+[withdrawn]+rows[-1:]),'typed_encoding_origin_revoked')
        for field,value in [('authorization_digest',M.digest('wrong')),('max_bytes',65),('reservation_id','wrong'),('request_digest',M.digest('wrong')),('proposed_attempt_id','other')]:
            reject('SQL授权列错配:'+field,db,lambda field=field,value=value:O.execute(db,T.mutate(rows,'ep_request',**{field:value})),'typed_encoding_authorization_columns')
        for level in ('base','registered','reserved','sent','prepared'):
            entry=saved[level];db=fork(entry[0]);p=entry[4]
            O.execute(db,[M.I('cr_revocation',transfer_id='transfer',proof_body=M.B,audit_body=M.B,outbox_body=M.B)])
            if level=='base':reject('grant撤回拒绝授权',db,lambda:M.transaction(db,lambda:M.authorize(db,cmd,attempt,eid,p)),'encoding_origin')
            elif level=='registered':reject('grant撤回拒绝编码入队',db,lambda:M.transaction(db,lambda:M.encoding(db,pid)))
            elif level=='reserved':reject('grant撤回拒绝首次写尝试',db,lambda:M.transaction(db,lambda:(None,M.send(db,pid))))
            elif level=='sent':reject('grant撤回拒绝响应采用',db,lambda:M.transaction(db,lambda:(None,M.receive(db,pid,entry[6],p))))
            else:check('grant撤回移除prepared但保留原件',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0]==0 and db.execute('SELECT count(*) FROM ep_reply').fetchone()[0]==1)
        base,cmd,attempt,eid,p,req,res=saved['sent'];db=fork(base)
        for flag in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified'):
            reject('采用前重核:'+flag,db,lambda flag=flag:M.transaction(db,lambda:(None,M.receive(db,pid,res,dict(p,**{flag:False})))),'encoding_provider')
        reject('编码到期等号拒绝采用',db,lambda:M.transaction(db,lambda:(None,M.receive(db,pid,res,p,70))),'encoding_expired')
        for field in ('socket_instance_id','protocol_session'):
            reject('实际传输会话变化:'+field,db,lambda field=field:M.transaction(db,lambda:(None,M.receive(db,pid,res,dict(p,**{field:'changed'})))),'encoding_packet_session')
        for field in ('authorization_snapshot_ref','capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref'):
            reject('采用前来源变化:'+field,db,lambda field=field:M.transaction(db,lambda:(None,M.receive(db,pid,res,dict(p,**{field:M.ref('changed')})))),'encoding_source_changed')
        for field,value in [('command_id','other'),('attempt_id','other'),('writer_exit_id','other'),('device_session_id','other'),('primitive_id','other'),('byte_length',3),('sha256',M.digest('other'))]:
            bad=copy.deepcopy(res);bad['body']['packet'][field]=value;bad['body']['packet']=M.seal(bad['body']['packet'],'packet_digest')
            reject('重新摘要仍拒错packet:'+field,db,lambda bad=bad:M.transaction(db,lambda:(None,M.receive(db,pid,bad,p))))
        bad=copy.deepcopy(res);bad['body']['bytes_hex']='0103';reject('同长度字节变化',db,lambda:M.transaction(db,lambda:(None,M.receive(db,pid,bad,p))),'encoding_packet_bytes')
        for field in ('ipc_session_id','controller_boot_id','worker_boot_id','reply_to'):
            bad=copy.deepcopy(res);bad[field]='other';reject('完整帧错绑:'+field,db,lambda bad=bad:M.transaction(db,lambda:(None,M.receive(db,pid,bad,p))))
        rows=preview(db,lambda:M.receive(db,pid,res,p));reject('SQL响应正文长度错配',db,lambda:O.execute(db,T.mutate(rows,'ep_reply',packet_bytes=b'123')),'typed_packet_columns')
        reject('采用seal前撤回来源',db,lambda:O.execute(db,rows[:2]+[withdrawn]+rows[2:]),'encoding_not_adoptable')
        reject('响应seq不能跳号',db,lambda:O.execute(db,T.mutate(rows,'ij_frame',seq=M.u('5'))),'journal_sequence')
        reject('响应必须指向原日志帧',db,lambda:O.execute(db,T.mutate(rows,'ij_frame',reply_frame_id='missing')),'journal_reply_binding')
        base,cmd,attempt,eid,p=saved['reserved'];db=fork(base);rows=preview(db,lambda:M.send(db,pid,70));reject('发送尝试截止等号',db,lambda:O.execute(db,rows),'encoding_attempt_not_current')
        base,cmd,attempt,eid,p,req,res=saved['sent'];db=fork(base);O.execute(db,[revoke()]);reject('编码撤回后不得采用',db,lambda:M.transaction(db,lambda:(None,M.receive(db,pid,res,p))))
        base,cmd,attempt,eid,p,req,res=saved['prepared'];db=fork(base);O.execute(db,[revoke()])
        check('撤回保持字节历史与额度',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0]==0 and db.execute('SELECT count(*) FROM ep_live_reservation').fetchone()[0]==1 and bytes(db.execute('SELECT packet_bytes FROM ep_reply').fetchone()[0])==b'\x01\x02')
        db=fork(base);check('恢复只查已经保存的编码结果',db.execute('SELECT recovery_action FROM ep_recovery WHERE prepare_id=?',(pid,)).fetchone()[0]=='query_recorded_result')
        reject('重试不能重复编码写尝试',db,lambda:M.transaction(db,lambda:(None,M.send(db,pid))))
        reject('重放响应不能新增packet',db,lambda:M.transaction(db,lambda:(None,M.receive(db,pid,res,p))))
        for level in ('reserved','sent','prepared'):
            entry=saved[level];db=fork(entry[0]);sid=db.execute('SELECT session_id FROM ij_exit WHERE exit_id=?',(eid,)).fetchone()[0]
            O.execute(db,[M.I('ij_end',end_id='closed',session_id=sid,reason='peer_lost',cause_frame_id=None,observed_tick=M.u('34'),evidence_body=M.B,audit_body=M.B)])
            if level=='reserved':reject('会话关闭不再写编码',db,lambda:M.transaction(db,lambda:(None,M.send(db,pid))))
            elif level=='sent':reject('会话关闭不采用响应',db,lambda:M.transaction(db,lambda:(None,M.receive(db,pid,res,p))))
            else:check('会话关闭隐藏prepared保留字节',db.execute('SELECT count(*) FROM ep_prepared_candidate').fetchone()[0]==0 and db.execute('SELECT count(*) FROM ep_reply').fetchone()[0]==1)
        for db in dbs:assert not db.in_transaction and not db.execute('PRAGMA foreign_key_check').fetchone()
        check('全部连接外键与事务完整')
        return checks
    finally:
        for db in dbs:db.close()

def inputs():return list(dict.fromkeys(T.inputs()+G.SOURCES+[HERE.parent/'c08-controller/encoding-authority.schema.json']+[HERE/n for n in ('typed_encoding_path_model.py','check_typed_encoding_path.py','controller-typed-encoding.sql','TYPED_ENCODING_PATH.md','continuation-binding-ipc.schema.json')] ))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'typed-encoding-path-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=242,sql_positive_encoding_path_executed=True,sql_positive_issue_path_executed=False,
            production_clearance=False,provider_evidence='synthetic',runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(V.M.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
