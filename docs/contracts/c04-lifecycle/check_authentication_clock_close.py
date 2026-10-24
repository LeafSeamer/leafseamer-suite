"""认证域故障的全出口关闭计划与派发前路由复核；无IPC发送和设备效果。"""
import copy
from unittest.mock import patch
import final_authorization_model as M
import authorization_clock_close_model as C
import check_attempt_inventory as AI
import check_prepare_deny_storage as PD
clone=copy.deepcopy


def register_exit(c,original,identity,**changes):
    # 沿用现有登记关闭义务及准备cut，不能为测试出口库存跳过延迟外键。
    names={'inventory_registration':'clock.registration.'+identity,'unassigned_exit':identity,
        'registration.unassigned_exit':'registration.'+identity,'inventory_registration_cut':'clock.registration.cut.'+identity}
    steps=[];now=max(100,int(c.execute('SELECT now_tick FROM ct_current_change WHERE device_id=?',(original['device_id'],)).fetchone()[0])+1)
    for step in AI.register_exit(c,original['device_id']):
        table,row=AI.M.data(step);row={k:names.get(x,x) if isinstance(x,str) else x for k,x in row.items()}
        if table=='ce_exit':row=dict(original,exit_id=identity,device_session_id=identity+'.device');row.update(changes)
        if table=='ct_change':row['now_tick']=str(now).zfill(20)
        if table=='pd_cut':row['selected_tick']=str(now).zfill(20)
        if table=='pd_cut_commit':row['committed_tick']=str(now).zfill(20)
        steps.append((table,row))
    # 同设备已有出口也必须同批关闭，准备cut包含它们的全部历史准备。
    head=int(c.execute("SELECT coalesce(max(sequence),'0') FROM pd_registration").fetchone()[0])
    for old in c.execute('SELECT exit_id FROM ce_exit WHERE device_id=? ORDER BY exit_id',(original['device_id'],)).fetchall():
        oldid=old[0];close='clock.registration.'+identity+'.'+oldid
        gate=c.execute('SELECT gate_id FROM go_current_gate WHERE exit_id=?',(oldid,)).fetchone()
        rev=int(c.execute("SELECT coalesce(max(revision),'0') FROM go_close WHERE exit_id=?",(oldid,)).fetchone()[0])+1
        row=dict(prepare_cut_id='pending',close_id=close,device_id=original['device_id'],exit_id=oldid,revision=str(rev).zfill(20),
            protection_change_id=names['inventory_registration'],gate_id=gate[0] if gate else None,reason_ref='new_exit',body=PD.B,outbox_body=PD.B,audit_body=PD.B)
        steps.insert(-1,('go_close',row))
        pids=[r[0] for r in c.execute('SELECT prepare_id FROM ep_request WHERE exit_id=? ORDER BY prepare_id',(oldid,))]
        steps=PD.capture(c,steps,'close',close,pids,head,now)
    for table,row in steps:c.execute(*AI.I(table,**row))

def run(T,check,reject,db,fork,u):
    binding=u['binding'];eid=binding['writer_exit_id']
    original=M.E.one(db,'SELECT * FROM ce_exit WHERE exit_id=?',(eid,))
    session=M.E.one(db,'SELECT s.* FROM ij_session s JOIN ij_exit e USING(session_id) WHERE e.exit_id=?',(eid,))
    def add_exit(c,identity,**changes):register_exit(c,original,identity,**changes)
    def fail(c):return C.I.ingest(c,binding,b'{')
    def plan(c):return T.tx(c,lambda:C.plan(c,binding))
    def recheck(c,p,target=eid):return T.tx(c,lambda:C.recheck(c,C.pref(p),target))
    def stop(name,fn):
        try:fn()
        except C.I.ClockIngressStop:check(name)
        else:raise AssertionError('缺少出口停止要求:'+name)
    c=fork(db)
    reject('无故障不得构造认证关闭计划',lambda:plan(c),'authorization_close_fault_missing')
    T.tx(c,lambda:add_exit(c,'additional.exit'))
    T.tx(c,lambda:add_exit(c,'other.domain',clock_domain_id='clock_'+'a'*64))
    T.tx(c,lambda:add_exit(c,'other.boot',controller_boot_id='other.controller.boot'))
    result=fail(c);p=C.prepare(c,binding,result['fault_ref']);targets={x['binding']['writer_exit_id']:x for x in p['targets']}
    check('采集故障到关闭计划使用同一持久故障',p['fault_ref']==result['fault_ref'] and not c.in_transaction)
    check('从实际登记表选出同域全部出口',set(targets)=={eid,'additional.exit'})
    check('无IPC路由的出口保留待确认终止',targets['additional.exit']['required_action']=='verify_termination' and targets['additional.exit']['close_body'] is None)
    check('可路由出口只形成CLOSE_GATE请求正文',targets[eid]['required_action']=='close_gate' and targets[eid]['close_body']['scope']=='device' and targets[eid]['close_body']['reason']=='authentication_clock_untrusted')
    check('计划重复读取精确原件不另建关闭ID',plan(c)==p and c.execute('SELECT count(*) FROM authorization_clock_close_plan').fetchone()[0]==1)
    check('当前有效路由可复核',recheck(c,p)==targets[eid])
    reject('未知出口不允许临时补入目标',lambda:recheck(c,p,'not.selected'),'authorization_close_target_missing')
    wrong=C.pref(p);wrong['digest']=M.F.digest('wrong')
    reject('关闭计划完整Ref必须核原件',lambda:T.tx(c,lambda:C.recheck(c,wrong,eid)),'authorization_close_plan_ref')
    for sql in ('DELETE FROM authorization_clock_close_plan','UPDATE authorization_clock_close_plan SET digest=digest'):
        reject('关闭计划不可覆盖或删除:'+sql,lambda sql=sql:T.tx(c,lambda:c.execute(sql)))
    reject('故障后新出口不能绕过固定目标集',lambda:T.tx(c,lambda:add_exit(c,'late.exit')),'authentication_clock_domain_closed')
    def new_session():
        row=dict(session,session_id='late.session',worker_boot_id='late.worker',ipc_session_id='late.ipc')
        c.execute(*T.T.E.I('ij_session',**row))
    reject('故障后新IPC会话不能进入原域',lambda:T.tx(c,new_session),'authentication_clock_domain_closed')
    reject('故障后既有无路由出口不能补绑会话',lambda:T.tx(c,lambda:c.execute(*T.T.E.I('ij_exit',exit_id='additional.exit',session_id=session['session_id']))),'authentication_clock_domain_closed')
    T.tx(c,lambda:add_exit(c,'unaffected.new.exit',clock_domain_id='clock_'+'a'*64))
    check('其他已区分域的登记不污染故障计划',recheck(c,p)==targets[eid])
    def end(connection):
        body=M.raw(dict(synthetic=True))
        connection.execute(*T.T.E.I('ij_end',end_id='ended.clock.session',session_id=session['session_id'],reason='shutdown',cause_frame_id=None,
            observed_tick='60'.zfill(20),evidence_body=body,audit_body=body))
    T.tx(c,lambda:end(c));after=recheck(c,p)
    check('冻结后失联升级为待确认终止',after['required_action']=='verify_termination' and after['close_body'] is None)
    check('派发前复核不改写原关闭计划',plan(c)==p)
    c=fork(db);T.tx(c,lambda:end(c));fail(c);ended_plan=plan(c)
    check('原本已结束会话仍列入完整清单',len(ended_plan['targets'])==1 and ended_plan['targets'][0]['required_action']=='verify_termination')
    c=fork(db);missing=clone(binding);missing['controller_boot_id']='unregistered.controller'
    C.I.ingest(c,missing,b'{')
    reject('空登记不能伪报全域已关闭',lambda:T.tx(c,lambda:C.plan(c,missing)),'authorization_close_inventory_capacity')
    c=fork(db);fail(c)
    def aborted():C.plan(c,binding);raise ValueError('close_plan_transaction_fault')
    reject('计划追加失败回滚',lambda:T.tx(c,aborted),'close_plan_transaction_fault')
    check('计划失败保留已持久域故障',c.execute('SELECT count(*) FROM authorization_clock_close_plan').fetchone()[0]==0 and C.I.fault(c,binding) is not None)
    check('重新规划只补保护工作不恢复资格',plan(c)['state']=='planned')
    c=fork(db);T.tx(c,lambda:add_exit(c,'capacity.extra'));fail(c)
    check('候选声明的默认出口容量为4096',C.MAX_EXITS==4096)
    # 缩小本地测试预算，实际SQL取上限加一；不构造数百万条无关登记关闭历史。
    with patch.object(C,'MAX_EXITS',1):
        reject('实际库存超过测试预算拒绝而非截断',lambda:plan(c),'authorization_close_inventory_capacity')
        stop('接线入口遇到超容量要求停止出口',lambda:C.prepare(c,binding,C.I.fault_ref(C.I.fault(c,binding))))
    check('超容量不留下部分关闭计划',c.execute('SELECT count(*) FROM authorization_clock_close_plan').fetchone()[0]==0)
    c=fork(db);result=fail(c);wrong=clone(result['fault_ref']);wrong['digest']=M.F.digest('other.fault')
    stop('错误故障Ref不能返回关闭计划成功',lambda:C.prepare(c,binding,wrong))
    check('错误Ref回滚新计划但保留故障',c.execute('SELECT count(*) FROM authorization_clock_close_plan').fetchone()[0]==0 and C.I.fault(c,binding) is not None)
    check('候选只有planned态不能自报applied',M.SCHEMA['$defs']['ClockClosePlan']['properties']['state']=={'const':'planned'})
