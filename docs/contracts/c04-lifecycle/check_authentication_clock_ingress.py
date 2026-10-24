"""认证采集边界的故障与事务检查；不能证明真实宿主停止了写出口。"""
import copy,sqlite3,tempfile
from pathlib import Path
import final_authorization_model as M
I=M.V.I;clone=copy.deepcopy


def run(T,check,reject,db,fork,u,v):
    binding=u['binding'];sample=T.clock_sample(u)
    def read(c):return T.T.T.preview(c,lambda:M.read(c,T.use_ref(u),v))
    def stop(name,fn):
        try:fn()
        except I.ClockIngressStop:check(name)
        else:raise AssertionError('缺少必须停止出口信号:'+name)
    c=fork(db);result=I.ingest(c,binding,M.raw(sample));M.validate('ClockIngestResult',result)
    check('重复已存采样不刷新时间或制造故障',result['outcome']=='stored' and result['fault_ref'] is None and c.execute('SELECT count(*) FROM authorization_clock_record').fetchone()[0]==1)
    check('重复采样不改变最终授权投影',read(c)==read(db))
    invalid=[]
    for name,mutate in [
        ('坏profile',lambda x:x.update(profile='reference-bound/1')),
        ('错可信入口绑定',lambda x:x['binding'].update(device_id='other.device')),
        ('越过64位整数',lambda x:x.update(utc_upper_ns=str(2**64))),
        ('同采样ID变正文',lambda x:x.update(utc_upper_ns=str(int(x['utc_upper_ns'])+1))),
        ('未知字段',lambda x:x.update(unknown='not.allowed'))]:
        value=clone(sample);mutate(value);invalid.append((name,M.raw(value)))
    invalid += [('采集失败',None),('不是字节',{}),('空输入',b''),('坏JSON',b'{'),('坏UTF8',b'\xff'),
        ('重复键',b'{"revision":"0",'+M.raw(sample)[1:]),('非JCS',b' '+M.raw(sample)),('超输入容量',b' '*16777217)]
    for name,body in invalid:
        c=fork(db);result=I.ingest(c,binding,body);fault=I.fault(c,binding)
        check('坏输入持久保护:'+name,result['outcome']=='protected' and result['fault_ref']==I.fault_ref(fault) and not c.in_transaction)
        reject('坏输入后旧授权不得继续:'+name,lambda:read(c),'authorization_clock_fault_latched')
        check('故障保留旧采样原件:'+name,c.execute('SELECT count(*) FROM authorization_clock_record').fetchone()[0]==1)
        if name=='超输入容量':check('超限输入仅保存长度不计算全文摘要',fault['input_digest'] is None and fault['input_bytes']=='16777217')
        if name=='采集失败':check('采集异常不伪造有效UTC时间',fault['reason']=='acquisition_failed' and fault['input_digest'] is None)
        again=I.ingest(c,binding,M.raw(sample))
        check('好输入不解除既有故障:'+name,again['outcome']=='protected' and again['fault_ref']==result['fault_ref'])
    c=fork(db);first=I.ingest(c,binding,b'{')
    for i in range(16):I.ingest(c,binding,str(i).encode())
    check('同域首故障有界且不被新故障覆盖',c.execute('SELECT count(*) FROM authorization_clock_fault').fetchone()[0]==1 and I.fault_ref(I.fault(c,binding))==first['fault_ref'])
    for key,value in [('device_id','other.device'),('worker_boot_id','other.worker'),('ipc_session_id','other.ipc'),('descriptor_digest',M.F.digest('other.descriptor'))]:
        other=clone(binding);other[key]=value
        check('共用认证时钟域不能借换绑定绕过:'+key,I.fault_ref(I.fault(c,other))==first['fault_ref'])
        s=clone(sample);s['binding']=other;s['sample_id']='new.binding'
        reject('低层采样保存也不得绕过域故障:'+key,lambda:T.tx(c,lambda:M.V.store_clock(c,s)),'authorization_clock_fault_latched')
    for key,value in [('clock_domain_id','clock_'+'a'*64),('controller_boot_id','other.controller.boot')]:
        other=clone(binding);other[key]=value
        check('故障查找不混淆其他运行域:'+key,I.fault(c,other) is None)
    for operation in ('DELETE FROM authorization_clock_fault','UPDATE authorization_clock_fault SET digest=digest'):
        reject('首故障不可删除或覆盖:'+operation,lambda operation=operation:T.tx(c,lambda:c.execute(operation)))
    c=fork(db);bad=clone(sample);bad.update(sample_id='jump',anchor_tick_ns='51',utc_lower_ns=str(int(sample['utc_lower_ns'])+60),utc_upper_ns=str(int(sample['utc_upper_ns'])+60))
    result=I.ingest(c,binding,M.raw(bad))
    check('格式合法的跳变同事务保存采样及故障',result['outcome']=='protected' and result['record_ref'] is not None and I.fault(c,binding)['reason']=='clock_unusable')
    reject('跳变故障阻断最终使用',lambda:read(c),'authorization_clock_fault_latched')
    c=fork(db);other=clone(binding);other['scope']['database_instance_id']='other.database'
    stop('不可信目标配置要求停止而不写错库',lambda:I.ingest(c,other,b'{'))
    check('错数据库没有写入故障',c.execute('SELECT count(*) FROM authorization_clock_fault').fetchone()[0]==0)
    c.execute('BEGIN IMMEDIATE')
    stop('入口不得借用外部事务后伪称提交',lambda:I.ingest(c,binding,b'{'))
    check('拒绝嵌套不擅自回滚外部事务',c.in_transaction);c.rollback()
    c=fork(db);c.execute("CREATE TRIGGER fault_write_failure BEFORE INSERT ON authorization_clock_fault BEGIN SELECT RAISE(ABORT,'injected_failure'); END")
    stop('保护写入失败不能报告已保护',lambda:I.ingest(c,binding,b'{'))
    check('保护写入失败完整回滚',not c.in_transaction and c.execute('SELECT count(*) FROM authorization_clock_fault').fetchone()[0]==0)
    # 提交前失败与提交后回执丢失必须都要求停止，不能根据异常猜测是否落库。
    class CommitFailure:
        def __init__(self,connection,after):self.connection=connection;self.after=after
        def __getattr__(self,key):return getattr(self.connection,key)
        def commit(self):
            if self.after:self.connection.commit()
            raise sqlite3.OperationalError('injected_commit_uncertainty')
    for after in (False,True):
        c=fork(db);stop('提交失败或不确定要求停止:'+str(after),lambda:I.ingest(CommitFailure(c,after),binding,b'{'))
        check('不把异常当作落库或回滚证明:'+str(after),c.execute('SELECT count(*) FROM authorization_clock_fault').fetchone()[0]==int(after) and not c.in_transaction)
        if after:reject('已提交故障在回执丢失后仍阻断',lambda:read(c),'authorization_clock_fault_latched')
    logs=(T.ROOT/'logs').resolve();logs.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='leafseamer-clock-ingress-',dir=logs) as directory:
        assert Path(directory).resolve().parent==logs
        path=Path(directory)/'candidate.sqlite';a=sqlite3.connect(path,isolation_level=None,timeout=0);db.backup(a)
        b=sqlite3.connect(path,isolation_level=None,timeout=0)
        try:
            a.execute('BEGIN IMMEDIATE');M.read(a,T.use_ref(u),v)
            stop('已有writer时不能假报保护提交成功',lambda:I.ingest(b,binding,b'{'))
            a.commit();result=I.ingest(b,binding,b'{')
            check('writer释放后保护可可靠提交',result['outcome']=='protected')
            reject('后续writer看到已提交采集故障',lambda:T.tx(a,lambda:M.read(a,T.use_ref(u),v)),'authorization_clock_fault_latched')
        finally:a.close();b.close()
    bad=dict(format_version='clock-ingest-result/1',binding=binding,outcome='protected',record_ref=None,fault_ref=None)
    reject('成功保护结果必须引用持久故障',lambda:M.validate('ClockIngestResult',bad))
