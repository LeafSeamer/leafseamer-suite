"""认证采集入口的本地事务参考；不执行系统采样或真实出口终止。"""
import hashlib
from jsonschema.exceptions import ValidationError
import final_authorization_model as M


class ClockIngressStop(RuntimeError):
    """没有可确认的保护提交；集成端必须阻止后续写入并终止受影响出口。"""

def fault_ref(value):return M.reference(value,'fault_id','fault_digest')

def domain(binding):return {k:binding[k] for k in ('scope','controller_boot_id','clock_domain_id')}

def fault(db,binding):
    target=domain(binding);key=M.F.digest(target)
    row=db.execute('SELECT domain_digest,fault_id,digest,body FROM authorization_clock_fault WHERE domain_digest=?',(key,)).fetchone()
    if row is None:return None
    value=M.decode('AuthenticationClockFault',row[3],row[2],'fault_digest')
    M.need(value['domain']==target==domain(value['binding']) and row[0]==key and row[1]==value['fault_id'],'authorization_clock_fault_columns');return value

def store_fault(db,binding,reason,body):
    M.writer(db);M.validate('Binding',binding)
    M.need(binding['scope']==M.E.A.scope(db),'authorization_clock_fault_scope')
    old=fault(db,binding)
    if old:return fault_ref(old)
    # 不保存坏输入正文或异常消息；只在有界原始字节上计算摘要。
    bounded=isinstance(body,bytes) and len(body)<=16777216
    fields=dict(format_version='authentication-clock-fault/1',revision='1',domain=domain(binding),binding=binding,reason=reason,
        input_digest='sha256:'+hashlib.sha256(body).hexdigest() if bounded else None,
        input_bytes=str(len(body)) if isinstance(body,bytes) else None)
    value=M.sealed(dict(fields,fault_id='clock_fault_'+M.F.digest(fields)[7:]),'fault_digest');M.validate('AuthenticationClockFault',value)
    db.execute('INSERT INTO authorization_clock_fault VALUES(?,?,?,?)',(M.F.digest(domain(binding)),value['fault_id'],value['fault_digest'],M.raw(value)))
    return fault_ref(value)

def ingest(db,binding,body):
    """binding来自已认证的本地入口，绝不从坏输入推断。None表示采集失败。拥有整个事务。"""
    if db.in_transaction:raise ClockIngressStop('authorization_clock_ingress_nested_transaction')
    try:
        M.validate('Binding',binding)
        db.execute('BEGIN IMMEDIATE');M.need(binding['scope']==M.E.A.scope(db),'authorization_clock_ingress_scope')
        record_ref=None;old=fault(db,binding)
        if old:fr=fault_ref(old)
        else:
            db.execute('SAVEPOINT clock_capture')
            try:
                M.need(body is not None,'authorization_clock_acquisition_failed')
                sample=M.document(body);M.validate('AuthenticationClockSample',sample)
                M.need(sample['binding']==binding,'authorization_clock_ingress_binding')
                record_ref=M.V.store_clock(db,sample)
                current=M.V.current(db,binding)
                reason='clock_unusable' if current['protected'] else None
            except (ValueError,ValidationError):
                db.execute('ROLLBACK TO clock_capture');record_ref=None
                reason='acquisition_failed' if body is None else 'invalid_sample'
            db.execute('RELEASE clock_capture')
            fr=store_fault(db,binding,reason,body) if reason else None
        result=dict(format_version='clock-ingest-result/1',binding=binding,outcome='protected' if fr else 'stored',record_ref=record_ref,fault_ref=fr)
        M.validate('ClockIngestResult',result);db.commit();return result
    except Exception as error:
        # 数据库错误、提交不确定及配置/程序错误均不伪装成持久保护成功。
        # 只在还能确定连接持有事务时回滚；回滚失败也必须传播停止信号。
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise ClockIngressStop('authorization_clock_ingress_exit_required') from error
