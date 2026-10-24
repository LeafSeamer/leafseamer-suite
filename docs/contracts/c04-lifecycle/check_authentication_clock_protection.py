"""认证域保护写集的真实SQLite原子性实验；身份、时钟和物理完成来源仍为合成。"""
import copy,sqlite3
from unittest.mock import patch
from pathlib import Path
import final_authorization_model as M
import authorization_clock_protection_model as P
import check_authentication_clock_close as X
clone=copy.deepcopy
INPUTS=[Path(P.S.__file__),Path(P.S.R.__file__),*P.S.G.SOURCES]


def run(T,check,reject,db,fork,u):
    binding=u['binding'];device=binding['device_id']
    def prepare(c):
        result=P.C.I.ingest(c,binding,b'{');plan=P.C.prepare(c,binding,result['fault_ref'])
        state=M.E.one(c,'SELECT * FROM ct_current_change WHERE device_id=?',(device,))
        timing=dict(device_id=device,clock_domain_id=state['clock_domain'],descriptor_digest=state['descriptor'],selected_tick_ns=str(max(200,int(state['now_tick'])+1)),source_ref=T.T.V.ref('synthetic.protection.tick'))
        return P.C.pref(plan),[timing]
    def stop(name,fn):
        try:fn()
        except P.C.I.ClockIngressStop:check(name)
        else:raise AssertionError('缺少保护失败停止要求:'+name)
    c=fork(db);plan,timings=prepare(c);baseline=fork(c)
    before=M.E.one(c,'SELECT * FROM ct_current_state WHERE device_id=?',(device,));other=[tuple(r) for r in c.execute('SELECT * FROM ct_current_state WHERE device_id!=?',(device,))]
    value,writes=P.apply(c,plan,timings)
    check('设备保护与准备cut可靠保存',value['state']=='durable_protection' and not c.in_transaction and len(value['exits'])==1)
    after=M.E.one(c,'SELECT * FROM ct_current_state WHERE device_id=?',(device,))
    preserved=('control_epoch','effective_version','reserved_version','mode','holder_issuer','holder_epoch','holder_id','pending_operation_id')
    check('保护不移交持有人或修改控制版本',all(after[k]==before[k] for k in preserved) and after['gate_state']=='protected')
    check('其他设备控制状态保持',other==[tuple(r) for r in c.execute('SELECT * FROM ct_current_state WHERE device_id!=?',(device,))])
    T.tx(c,lambda:P.S.control(c,after['change_id']));check('新控制状态使用可核验的完整正文')
    check('非空准备进入完整关闭cut',len(value['exits'][0]['prepare_refs'])==1 and c.execute('SELECT count(*) FROM pd_member WHERE cut_id IN (SELECT prepare_cut_id FROM go_close WHERE protection_change_id=?)',(after['change_id'],)).fetchone()[0]==1)
    check('旧准备只撤回不伪造释放',c.execute('SELECT count(*) FROM ep_revocation').fetchone()[0]==1 and c.execute('SELECT count(*) FROM ep_release').fetchone()[0]==0)
    check('保留已尝试发送及返回packet事实',c.execute('SELECT count(*) FROM ep_send_attempt').fetchone()[0]==1 and c.execute('SELECT count(*) FROM ep_reply').fetchone()[0]==1)
    again,more=P.apply(c,plan,[]);check('重试只查原不刷新截止或再保护',again==value and more==[])
    bad=clone(plan);bad['digest']='sha256:'+'0'*64
    stop('已保存保护仍须匹配完整计划引用',lambda:P.apply(c,bad,[]))
    class CommitFault:
        def __init__(self,connection,committed):self.connection=connection;self.committed=committed
        def __getattr__(self,key):return getattr(self.connection,key)
        def commit(self):
            if self.committed:self.connection.commit()
            raise sqlite3.OperationalError('synthetic_commit_observation_failure')
    for committed in (False,True):
        x=fork(baseline);snapshot=T.T.T.V.SC.snapshot(x)
        stop('提交观察失败必须要求停止:'+str(committed),lambda:P.apply(CommitFault(x,committed),plan,timings))
        if committed:
            recovered,more=P.apply(x,plan,[])
            check('提交后回执丢失仅查原恢复',recovered==value and more==[])
        else:check('提交前故障无半边保护',T.T.T.V.SC.snapshot(x)==snapshot)
    x=fork(baseline);x.execute('BEGIN IMMEDIATE')
    stop('不得借用调用者外部事务',lambda:P.apply(x,plan,timings))
    check('拒绝嵌套不回滚调用者事务',x.in_transaction);x.rollback()
    for i,table in enumerate(writes):
        x=fork(baseline);snapshot=T.T.T.V.SC.snapshot(x)
        stop('逐写故障回滚:'+str(i)+':'+table,lambda:P.apply(x,plan,timings,fail_after=i))
        check('逐写失败保留原故障而无部分保护:'+str(i),T.T.T.V.SC.snapshot(x)==snapshot and P.C.I.fault(x,binding) is not None)
    class Omit:
        def __init__(self,connection,table):self.connection=connection;self.table=table;self.omitted=0
        def __getattr__(self,key):return getattr(self.connection,key)
        def execute(self,sql,args=()):
            if sql.startswith('INSERT INTO '+self.table+' ('):
                self.omitted+=1;return self.connection.execute('SELECT 1 WHERE 0')
            return self.connection.execute(sql,args)
    for table in ('go_close','pd_member','ep_revocation','pd_cut_commit','ct_audit','ct_outbox'):
        x=fork(baseline);snapshot=T.T.T.V.SC.snapshot(x)
        proxy=Omit(x,table)
        stop('遗漏必要领域行不得提交:'+table,lambda:P.apply(proxy,plan,timings))
        check('故障注入实际省略目标写入:'+table,proxy.omitted>0)
        check('遗漏写集完整回滚:'+table,T.T.T.V.SC.snapshot(x)==snapshot)
    for name,change in [('时钟域错配',lambda t:t[0].update(clock_domain_id='clock_'+'a'*64)),('过旧tick',lambda t:t[0].update(selected_tick_ns='0')),('重复设备',lambda t:t.append(clone(t[0]))),('遗漏设备',lambda t:t.clear())]:
        x=fork(baseline);t=clone(timings);change(t);stop('时序原件拒绝:'+name,lambda:P.apply(x,plan,t))
    x=fork(baseline)
    with patch.object(P,'MAX_MEMBERS',0):stop('准备或出口容量不足不可截断执行',lambda:P.apply(x,plan,timings))
    # 同一设备的健康时钟域也受整台设备闸保护，明确标记扩大范围而不冒充原域目标。
    x=fork(db);original=M.E.one(x,'SELECT * FROM ce_exit WHERE exit_id=?',(binding['writer_exit_id'],))
    T.tx(x,lambda:X.register_exit(x,original,'expanded.exit',clock_domain_id='clock_'+'a'*64))
    p,t=prepare(x);existing=[tuple(r) for r in x.execute('SELECT * FROM ep_revocation')]
    expanded,_=P.apply(x,p,t)
    check('整台设备关闭包括原故障域之外出口',len(expanded['exits'])==2 and {e['target']['binding']['writer_exit_id'] for e in expanded['exits'] if e['same_device_expansion']}=={'expanded.exit'})
    check('已有准备撤回不改写原身份',existing==[tuple(r) for r in x.execute('SELECT * FROM ep_revocation')])
    check('扩大范围不伪造退出或applied',next(e for e in expanded['exits'] if e['same_device_expansion'])['target']['required_action']=='verify_termination')
    for sql in ('DELETE FROM authorization_clock_protection','UPDATE authorization_clock_protection SET digest=digest'):
        reject('设备保护回执不可变:'+sql,lambda sql=sql:T.tx(x,lambda:x.execute(sql)))
    check('关闭ACK及准备核销未伪造',x.execute('SELECT count(*) FROM pd_close_completion').fetchone()[0]==db.execute('SELECT count(*) FROM pd_close_completion').fetchone()[0])
    check('保护后仍无最终发送许可',x.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==0)
