"""认证域故障到完整出口关闭目标的持久投影；不发送IPC，不把关闭计划当作完成回执。"""
import json
from jsonschema import Draft202012Validator
import final_authorization_model as M
I=M.V.I
IPC=json.loads(M.G.IPC.read_bytes())
MAX_EXITS=4096


def pref(value):return M.reference(value,'plan_id','plan_digest')

def source_ref(kind,value):
    digest=M.F.digest(value);return M.E.ref(kind+'_'+digest[7:],1,digest)

def columns(row):return {k:(M.document(v) if isinstance(v,bytes) else v) for k,v in row.items()}

def target(db,exit_row,fault):
    # 绑定来自ce_exit实际列；原runtime正文被纳入摘要但不宣称其来源可信。
    binding=dict(scope=M.E.A.scope(db),writer_exit_id=exit_row['exit_id'],**{k:exit_row[k] for k in
        ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest')})
    M.validate('Binding',binding);M.need(I.domain(binding)==fault['domain'],'authorization_close_exit_domain')
    sessions=db.execute('SELECT session_id FROM ij_exit WHERE exit_id=?',(exit_row['exit_id'],)).fetchall()
    M.need(len(sessions)<=1,'authorization_close_ambiguous_route')
    sid=sessions[0][0] if sessions else None;sr=None;action='verify_termination';body=None
    if sid is not None:
        session=M.E.one(db,'SELECT * FROM ij_session WHERE session_id=?',(sid,))
        M.need(all(session[k]==binding[k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','clock_domain_id','descriptor_digest')),'authorization_close_session_binding')
        M.need(session['protocol_version']=='ipc/0.14.0-continuation-draft.1','authorization_close_protocol')
        sr=source_ref('clock_session',columns(session))
        if not db.execute('SELECT 1 FROM ij_end WHERE session_id=?',(sid,)).fetchone():
            action='close_gate';body=dict(close_id='clock_close_'+M.F.digest(dict(fault_ref=I.fault_ref(fault),binding=binding))[7:],reason='authentication_clock_untrusted',scope='device')
            Draft202012Validator({'$defs':IPC['$defs'],'$ref':'#/$defs/S9__CLOSE_GATEBody'}).validate(body)
    value=dict(binding=binding,exit_source_ref=source_ref('clock_exit',columns(exit_row)),session_id=sid,session_source_ref=sr,required_action=action,close_body=body)
    M.validate('ClockCloseTarget',value);return value

def inventory(db,fault):
    M.need(fault['domain']['scope']==M.E.A.scope(db),'authorization_close_scope')
    cursor=db.execute('SELECT * FROM ce_exit WHERE controller_boot_id=? AND clock_domain_id=? ORDER BY exit_id LIMIT ?',
        (fault['domain']['controller_boot_id'],fault['domain']['clock_domain_id'],MAX_EXITS+1))
    names=[x[0] for x in cursor.description];rows=[dict(zip(names,r)) for r in cursor.fetchall()]
    M.need(0<len(rows)<=MAX_EXITS,'authorization_close_inventory_capacity')
    return [target(db,row,fault) for row in rows]

def plan(db,binding):
    M.writer(db);M.validate('Binding',binding);fault=I.fault(db,binding);M.need(fault is not None,'authorization_close_fault_missing')
    old=db.execute('SELECT plan_id,fault_id,digest,body FROM authorization_clock_close_plan WHERE fault_id=?',(fault['fault_id'],)).fetchone()
    if old:
        value=M.decode('ClockClosePlan',old[3],old[2],'plan_digest')
        M.need(value['plan_id']==old[0] and value['fault_ref']==I.fault_ref(fault) and old[1]==fault['fault_id'] and value['domain']==fault['domain'],'authorization_close_plan_columns')
        return value
    value=M.sealed(dict(format_version='authentication-clock-close-plan/1',plan_id='clock_plan_'+M.F.digest(I.fault_ref(fault))[7:],revision='1',
        fault_ref=I.fault_ref(fault),domain=fault['domain'],state='planned',targets=inventory(db,fault)),'plan_digest')
    M.validate('ClockClosePlan',value);M.need(len(M.raw(value))<=16777216,'authorization_close_plan_capacity')
    db.execute('INSERT INTO authorization_clock_close_plan VALUES(?,?,?,?)',(value['plan_id'],fault['fault_id'],value['plan_digest'],M.raw(value)))
    return value

def prepare(db,binding,fault_ref):
    """入口保护提交后的下一步；只有可靠保存计划才返回，失败仍要求停止出口。"""
    if db.in_transaction:raise I.ClockIngressStop('authorization_close_nested_transaction')
    try:
        M.validate('Ref',fault_ref);db.execute('BEGIN IMMEDIATE');value=plan(db,binding)
        M.need(value['fault_ref']==fault_ref,'authorization_close_requested_fault')
        db.commit();return value
    except Exception as error:
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise I.ClockIngressStop('authorization_close_exit_required') from error

def recheck(db,plan_ref,exit_id):
    """派发前重读路由；会话已结束时只能升级为待确认终止，不改写原计划。"""
    M.writer(db);M.validate('Ref',plan_ref)
    row=db.execute('SELECT digest,body FROM authorization_clock_close_plan WHERE plan_id=?',(plan_ref['id'],)).fetchone()
    M.need(row is not None,'authorization_close_plan_missing');value=M.decode('ClockClosePlan',row[1],row[0],'plan_digest')
    M.need(pref(value)==plan_ref,'authorization_close_plan_ref')
    matches=[t for t in value['targets'] if t['binding']['writer_exit_id']==exit_id];M.need(len(matches)==1,'authorization_close_target_missing');selected=matches[0]
    fault=I.fault(db,selected['binding']);M.need(fault is not None and I.fault_ref(fault)==value['fault_ref'],'authorization_close_fault_binding')
    current=inventory(db,fault)
    M.need([t['binding']['writer_exit_id'] for t in current]==[t['binding']['writer_exit_id'] for t in value['targets']],'authorization_close_inventory_changed')
    now=next(t for t in current if t['binding']['writer_exit_id']==exit_id)
    M.need(all(now[k]==selected[k] for k in ('binding','exit_source_ref','session_id','session_source_ref')),'authorization_close_target_changed')
    M.need(selected['required_action']!='verify_termination' or now['required_action']=='verify_termination','authorization_close_no_reactivation')
    return now
