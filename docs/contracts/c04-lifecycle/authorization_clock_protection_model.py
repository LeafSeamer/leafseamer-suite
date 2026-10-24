"""认证故障到设备保护及完整准备cut的SQLite参考写集；不发送IPC或确认物理关闭。"""
import final_authorization_model as M
import authorization_clock_close_model as C
import final_source_bodies_model as S
I=M.E.E.I
MAX_MEMBERS=4096


def rows(db,sql,args=()):
    c=db.execute(sql,args);names=[x[0] for x in c.description];return [dict(zip(names,r)) for r in c.fetchall()]

def u(value):
    M.validate('Counter',str(value));n=int(value);M.need(0<=n<10**20,'authentication_protection_counter');return str(n).zfill(20)

def identity(prefix,value):return prefix+'_'+M.F.digest(value)[7:]

def apply(db,plan_ref,timings,fail_after=None):
    if db.in_transaction:raise C.I.ClockIngressStop('authentication_protection_nested_transaction')
    writes=[]
    def write(table,**value):
        db.execute(*I(table,**value));writes.append(table)
        if fail_after==len(writes)-1:raise RuntimeError('injected_protection_write')
    try:
        db.execute('BEGIN IMMEDIATE');M.validate('Ref',plan_ref)
        old=db.execute('SELECT digest,body,protection_id FROM authorization_clock_protection WHERE plan_id=?',(plan_ref['id'],)).fetchone()
        if old:
            value=M.decode('ClockProtectionCommit',old[1],old[0],'protection_digest');M.need(value['plan_ref']==plan_ref and value['protection_id']==old[2],'authentication_protection_plan_ref')
            db.commit();return value,[]
        row=M.E.one(db,'SELECT digest,body FROM authorization_clock_close_plan WHERE plan_id=?',(plan_ref['id'],))
        plan=M.decode('ClockClosePlan',row['body'],row['digest'],'plan_digest');M.need(C.pref(plan)==plan_ref,'authentication_protection_plan_ref')
        fault=C.I.fault(db,plan['targets'][0]['binding']);M.need(fault is not None and C.I.fault_ref(fault)==plan['fault_ref'],'authentication_protection_fault')
        # 当前故障域库存必须仍与固定计划一致；同设备扩展库存另外显式列出。
        current=C.inventory(db,fault)
        M.need([t['binding'] for t in current]==[t['binding'] for t in plan['targets']],'authentication_protection_inventory')
        devices=sorted({t['binding']['device_id'] for t in current});seed={t['binding']['writer_exit_id'] for t in current}
        for timing in timings:M.validate('ClockProtectionTiming',timing)
        M.need(sorted(t['device_id'] for t in timings)==devices,'authentication_protection_timing_set')
        timing_by_device={t['device_id']:t for t in timings};all_exits=[]
        for device in devices:
            all_exits+=rows(db,'SELECT * FROM ce_exit WHERE device_id=? ORDER BY exit_id LIMIT ?',(device,MAX_MEMBERS+1))
        M.need(0<len(all_exits)<=MAX_MEMBERS,'authentication_protection_exit_capacity')
        result=dict(format_version='authentication-clock-protection/1',protection_id=identity('clock_protection',plan_ref),revision='1',
            plan_ref=plan_ref,fault_ref=plan['fault_ref'],state='durable_protection',devices=[],exits=[])
        head=db.execute("SELECT coalesce(max(sequence),'00000000000000000000') FROM pd_registration").fetchone()[0]
        total_prepares=0
        for device in devices:
            before=M.E.one(db,'SELECT * FROM ct_current_state WHERE device_id=?',(device,))
            previous=M.E.one(db,'SELECT * FROM ct_current_change WHERE device_id=?',(device,));timing=timing_by_device[device];tick=u(timing['selected_tick_ns'])
            M.need(timing['clock_domain_id']==previous['clock_domain'] and timing['descriptor_digest']==previous['descriptor'] and tick>=previous['now_tick'],'authentication_protection_clock_binding')
            cid=identity('clock_device',dict(plan_ref=plan_ref,device_id=device))
            change=dict(previous,change_id=cid,sequence=u(int(previous['sequence'])+1),previous_id=previous['change_id'],kind='gate_protect',state_id=cid,
                operation_id=None,offer_id=None,request_id=None,now_tick=tick)
            write('ct_change',**change)
            after={k:v for k,v in before.items() if k!='device_id'}
            after.update(change_id=cid,record_revision=u(int(before['record_revision'])+1),gate_state='protected')
            body=S.control_body(db,after);S.validate('ControlStorageRecord',body);after.update(record_digest=body['record_digest'],record_body=M.raw(body));write('ct_state',**after)
            result['devices'].append(dict(device_id=device,before_control_ref=C.source_ref('clock_control',C.columns(before)),after_control_ref=S.control_ref(body),timing=timing))
            for exit_row in [e for e in all_exits if e['device_id']==device]:
                target=C.route_target(db,exit_row,plan['fault_ref']);eid=exit_row['exit_id']
                close_id=identity('clock_close',dict(fault_ref=plan['fault_ref'],binding=target['binding']))
                cut_id=identity('clock_cut',dict(plan_ref=plan_ref,exit_id=eid))
                rev=int(db.execute("SELECT coalesce(max(revision),'0') FROM go_close WHERE exit_id=?",(eid,)).fetchone()[0])+1
                gate=db.execute('SELECT gate_id FROM go_current_gate WHERE exit_id=?',(eid,)).fetchone()
                provenance=dict(kind='authentication_clock_protection',plan_ref=plan_ref,fault_ref=plan['fault_ref'],target=target,
                    close_id=close_id,prepare_cut_id=cut_id,same_device_expansion=eid not in seed)
                encoded=M.raw(provenance)
                write('go_close',prepare_cut_id=cut_id,close_id=close_id,device_id=device,exit_id=eid,revision=u(rev),protection_change_id=cid,
                    gate_id=gate[0] if gate else None,reason_ref=fault['fault_id'],body=encoded,outbox_body=encoded,audit_body=encoded)
                selector=dict(kind='device_exit_close',scope=M.E.A.scope(db),device_id=device,exit_ref=target['exit_source_ref'],fault_ref=plan['fault_ref'],plan_ref=plan_ref)
                write('pd_cut',cut_id=cut_id,kind='close',prepare_head=head,selected_tick=tick,selector_digest=M.F.digest(selector),selector_body=M.raw(selector),
                    control_id=None,cancel_id=None,run_id=None,close_id=close_id)
                members=rows(db,'SELECT prepare_id,exit_id,authorization_id,authorization_digest FROM pd_expected WHERE cut_id=? ORDER BY prepare_id LIMIT ?',(cut_id,MAX_MEMBERS+1))
                total_prepares+=len(members);M.need(total_prepares<=MAX_MEMBERS,'authentication_protection_prepare_capacity')
                refs=[]
                for member in members:
                    pid=member['prepare_id'];write('pd_member',cut_id=cut_id,**member)
                    refs.append(C.source_ref('clock_prepare',member))
                    if not db.execute('SELECT 1 FROM ep_revocation WHERE prepare_id=?',(pid,)).fetchone():
                        rid=identity('clock_revoke',dict(plan_ref=plan_ref,prepare_id=pid))
                        event=dict(revocation_id=rid,revision='1',prepare_ref=refs[-1],fault_ref=plan['fault_ref'],plan_ref=plan_ref,revoked_tick_ns=str(int(tick)))
                        raw=M.raw(event)
                        write('ep_revocation',prepare_id=pid,revocation_id=rid,revocation_revision=u(1),revocation_digest=M.F.digest(event),revoked_tick=tick,
                            reason_body=raw,audit_body=raw,outbox_id=rid,outbox_body=raw)
                write('pd_cut_commit',cut_id=cut_id,committed_tick=tick,audit_body=encoded,outbox_body=encoded)
                cut=C.source_ref('clock_cut_source',dict(cut_id=cut_id,selector=selector,prepare_head=str(int(head)),selected_tick_ns=str(int(tick)),prepare_refs=refs))
                result['exits'].append(dict(target=target,same_device_expansion=eid not in seed,close_id=close_id,cut_ref=cut,prepare_refs=refs))
            evidence=M.raw(dict(kind='authentication_clock_device_protected',fault_ref=plan['fault_ref'],plan_ref=plan_ref,device=result['devices'][-1]))
            write('ct_audit',change_id=cid,body=evidence);write('ct_outbox',change_id=cid,event_id=cid,body=evidence);write('ct_commit',change_id=cid)
            S.control(db,cid)
        value=M.sealed(result,'protection_digest');M.validate('ClockProtectionCommit',value);M.need(len(M.raw(value))<=16777216,'authentication_protection_body_capacity')
        write('authorization_clock_protection',protection_id=value['protection_id'],plan_id=plan_ref['id'],digest=value['protection_digest'],body=M.raw(value))
        db.commit();return value,writes
    except Exception as error:
        try:
            if db.in_transaction:db.rollback()
        except Exception:pass
        raise C.I.ClockIngressStop('authentication_protection_exit_required') from error
