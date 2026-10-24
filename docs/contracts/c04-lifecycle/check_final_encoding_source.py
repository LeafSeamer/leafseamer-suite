"""最终封存从实际编码原件查原的正向与对抗实验；不产生最终发送许可。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_typed_encoding_path as T
import check_final_admission as V
import final_encoding_source_model as M
E=M.E;F=M.F;HERE=E.G.HERE;ROOT=HERE.parents[2];clone=copy.deepcopy

def fixture():
    d,cds,items=T.fixture();db=items[0][0];ad=T.V.M.decide(*items[0]);command=ad['command_ref']['object_id'];auth=T.V.reader(items[0])
    T.AI.publish(db,command,auth,prepare=True);record=T.AI.S.read(db,command,auth)['record']
    aid=record['state']['attempt_ids'][0];eid='exit_'+record['target']['device_id'].replace('.','_');p=T.provider(db,command,aid,eid);pid='prepare_typed'
    E.transaction(db,lambda:E.authorize(db,command,aid,eid,p));request=E.transaction(db,lambda:E.encoding(db,pid))
    E.transaction(db,lambda:(None,E.send(db,pid)));E.O.execute(db,E.written(db,pid))
    response=E.response(request,p)
    return db,[d]+[x[0] for x in cds.values()],command,auth,pid,p,response

def candidate(db,pid,provider):
    value=M.read(db,pid,'transaction','51','52',provider)
    v,o,cut=V.fixture(origin='automation')
    for name in ('binding','identity','command_state_ref'):v[name]=clone(value[name]);cut[name]=clone(value[name])
    v['issued_revision']='1';cut['previous_issue_revision']=0
    v['packet_ref']=clone(value['encoding']['body']['packet_ref']);v['encoding_packet_ref']=clone(value['encoding']['body']['packet_record_ref'])
    for role in o:
        o[role]['scope']=clone(v['binding']['scope']);o[role]['body']['binding']=clone(v['binding']);o[role]['body']['identity']=clone(v['identity'])
    for role in ('origin','encoding'):o[role]=clone(value[role])
    o['capability']['body']['encoding_source_ref']=clone(o['encoding']['source_ref'])
    o['permit_authority']['body']['packet_ref']=clone(v['encoding_packet_ref'])
    for role in ('permit_authority','guard','budget','time'):o[role]['body']['issued_revision']='1'
    o['guard']['body']['packet_ref']=clone(v['packet_ref'])
    o['time']['body'].update(clock_domain_id=v['binding']['clock_domain_id'],descriptor_digest=v['binding']['descriptor_digest'])
    V.refresh(v,o)
    return v,o,cut

def run():
    checks=[];dbs=[]
    def check(name,value=True):assert value,name;checks.append(dict(name=name,passed=True))
    def fork(db):
        out=sqlite3.connect(':memory:',isolation_level=None);db.backup(out);out.execute('PRAGMA foreign_keys=ON');out.execute('PRAGMA recursive_triggers=ON');dbs.append(out);return out
    def read(db,pid,p,selected='51',sealed='52'):
        return T.preview(db,lambda:M.read(db,pid,'transaction',selected,sealed,p))
    def reject(name,db,fn,reason=None):
        before=T.V.SC.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError) as error:
            if reason:assert reason in str(error),(name,str(error))
            check(name,not db.in_transaction and T.V.SC.snapshot(db)==before)
        else:raise AssertionError('未拒绝:'+name)
    try:
        db,connections,cmd,auth,pid,p,response=fixture();dbs.extend(connections)
        pending=fork(db);response_rows=T.preview(db,lambda:E.receive(db,pid,response,p))
        E.O.execute(db,response_rows);before=T.V.SC.snapshot(db)
        source=read(db,pid,p);v,o,cut=T.preview(db,lambda:candidate(db,pid,p))
        planned=T.preview(db,lambda:M.planned(db,v,o,cut,pid,p))
        check('实际原件进入完整18角色封存检查',len(planned)==19 and F.verify(v,o,cut)=='cross_object_binding_valid')
        check('来源读取不写数据库',before==T.V.SC.snapshot(db))
        check('packet引用映射没有另造摘要',source['encoding']['body']['packet_record_ref']==M.ref(response['body']['packet']['packet_id'],1,response['body']['packet']['packet_digest']))
        check('证据Ref来自持久EncodingEvidence',source['encoding']['source_ref']['digest']==db.execute('SELECT evidence_digest FROM ep_reply').fetchone()[0])
        for role in ('origin','encoding'):
            check('确定性投影'+role,source[role]==read(db,pid,p)[role])
            changed=T.preview(db,lambda:M.read(db,pid,'different_transaction','51','52',p))
            check('事务变化重建投影'+role,changed[role]['ref']!=source[role]['ref'] and changed[role]['source_ref']==source[role]['source_ref'])
        check('派生请求源覆盖原请求身份',source['identity']['source_ref']['digest']==M.digest(source['source_descriptors']['request']))
        check('派生attempt源覆盖prepared修订',source['identity']['attempt_ref']['digest']==M.digest(source['source_descriptors']['attempt']))
        reject('事务外不允许查原',db,lambda:M.read(db,pid,'transaction','51','52',p),'final_encoding_transaction_required')
        for selected,sealed in [('32','52'),('53','52'),('51','70')]:
            reject('封存时间边界:'+selected+'/'+sealed,db,lambda selected=selected,sealed=sealed:read(db,pid,p,selected,sealed),'final_encoding_window')
        for flag in ('authorized','capability_verified','parameters_verified','time_verified','reservation_verified','current_transport_verified'):
            reject('最后读取重核提供者:'+flag,db,lambda flag=flag:read(db,pid,dict(p,**{flag:False})),'encoding_provider')
        for field in ('socket_instance_id','protocol_session'):
            changed=dict(p,**{field:'changed'})
            reject('传输实例切换:'+field,db,lambda changed=changed:read(db,pid,changed),'encoding_packet_session')
        for role in ('origin','encoding'):
            bad=clone(o);bad[role]['source_ref']=dict(bad[role]['source_ref'],digest=F.digest('self_asserted'));vv=clone(v)
            if role=='encoding':bad['capability']['body']['encoding_source_ref']=clone(bad[role]['source_ref'])
            V.refresh(vv,bad)
            check('纯关联可通过但不证明原件:'+role,F.verify(vv,bad,cut)=='cross_object_binding_valid')
            reject('同摘要投影仍须查原:'+role,db,lambda vv=vv,bad=bad:T.preview(db,lambda:M.planned(db,vv,bad,cut,pid,p)),'final_encoding_projection_'+role)
        bad=clone(o);bad['encoding']['body']['expires_tick_ns']='99';vv=clone(v);V.refresh(vv,bad)
        reject('调用方不能延长编码有效期',db,lambda:T.preview(db,lambda:M.planned(db,vv,bad,cut,pid,p)),'final_encoding_projection_encoding')
        # 合法追加撤回事件，不删除任何SQL守卫；已选投影不能免除最后查原。
        for name,mutation in [
            ('grant撤回',lambda c:E.O.execute(c,[E.I('cr_revocation',transfer_id='transfer',proof_body=E.B,audit_body=E.B,outbox_body=E.B)])),
            ('编码撤回',lambda c:E.O.execute(c,[T.revoke()])),
            ('会话结束',lambda c:E.O.execute(c,[E.I('ij_end',end_id='ended',session_id=c.execute('SELECT session_id FROM ij_exit WHERE exit_id=?',(source['binding']['writer_exit_id'],)).fetchone()[0],reason='peer_lost',cause_frame_id=None,observed_tick=E.u('40'),evidence_body=E.B,audit_body=E.B)])),
            ('开放ACK撤回',lambda c:E.O.execute(c,[E.I('go_revocation',kind='open_ack',object_id=c.execute('SELECT evidence_id FROM go_ready WHERE ready_id LIKE ?',('startup_dev_1%',)).fetchone()[0],reason_body=E.B,audit_body=E.B)]))]:
            c=fork(db);mutation(c)
            reject(name+'后不能封存旧投影',c,lambda c=c:T.preview(c,lambda:M.planned(c,v,o,cut,pid,p)))
            check(name+'保持packet历史',c.execute('SELECT count(*) FROM ep_reply').fetchone()[0]==1)
        c=fork(db);T.AI.publish(c,cmd,auth)
        reject('公开命令修订推进后重选前态',c,lambda:T.preview(c,lambda:M.planned(c,v,o,cut,pid,p)),'final_encoding_command_state_ref')
        fresh=read(c,pid,p);check('新命令前态仍引用原编码证据',fresh['command_state_ref']!=source['command_state_ref'] and fresh['encoding']['source_ref']==source['encoding']['source_ref'])
        # 在SQL允许的正文包络内保存错误证据；解析器必须发现，不能只信非空BLOB。
        for field in ('evidence_body','response_frame'):
            c=fork(pending);bad_rows=T.T.mutate(response_rows,'ep_reply',**{field:E.raw({'synthetic':True})});before=T.V.SC.snapshot(c)
            try:E.O.execute(c,bad_rows)
            except sqlite3.IntegrityError:
                check('SQL先拒绝损坏正文:'+field,T.V.SC.snapshot(c)==before and not c.in_transaction);continue
            reject('持久正文损坏:'+field,c,lambda c=c:read(c,pid,p))
        c=fork(pending);E.O.execute(c,response_rows[:-1])
        reject('仅响应无packet映射不满足最终来源',c,lambda:read(c,pid,p))
        for c in dbs:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        check('全部连接外键与事务完整')
        check('最终许可及封存仍未生成',db.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==db.execute('SELECT count(*) FROM fa_seal').fetchone()[0]==0)
        return checks
    finally:
        for db in dbs:db.close()

def inputs():return list(dict.fromkeys(T.inputs()+V.inputs()+[HERE/n for n in ('final_encoding_source_model.py','check_final_encoding_source.py','FINAL_ENCODING_SOURCE.md')] ))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');args=parser.parse_args();target=HERE/'final-encoding-source-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if args.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),controller_tables=242,sql_positive_issue_path_executed=False,storage_bound_roles=['origin','encoding'],
            remaining_provider_roles=16,production_clearance=False,runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if args.report:target.write_bytes(E.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
