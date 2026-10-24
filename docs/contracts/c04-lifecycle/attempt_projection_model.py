"""公开attempt字段的独立原件映射候选；输入是固定修订的可信库存，不实现设备采集。"""
import copy,json
import typed_command_view_model as M
import build_attempt_projection as G
from jsonschema import Draft202012Validator
need=M.need;digest=M.digest;raw=M.raw
LEVEL={'sent':0,'acknowledged':1,'effect_verified':2}
EXIT_FIELDS=('exit_id','device_id','controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','clock_domain_id','descriptor_digest')

def ref(ident,body):return dict(id=ident,revision='1',digest=digest(body))
def unique(rows,key):
    ids=[r[key] for r in rows];need(len(ids)==len(set(ids)),'duplicate_original');return dict(zip(ids,rows))
def reference(rows,key,reference):
    found=[r for r in rows if r[key]==reference['id']]
    need(len(found)==1 and ref(reference['id'],found[0])==reference,'original_reference');return found[0]

def project(record,inventory,selections):
    """inventory必须由本地读取事务按固定修订提供，不能取自HTTP正文或record.attempts。"""
    M.validate('CommandRecord',record)
    need(inventory['scope']==record['scope'] and inventory['command_id']==record['command_id'] and inventory['state']==record['state'],'snapshot_owner')
    need(inventory['state_ref']==record['state_ref']==M.V.state_ref(inventory['state']),'snapshot_state')
    need(inventory['complete'] and inventory['originals_verified'] and inventory['redaction_verified'],'inventory_provider')
    state=inventory['state'];command=record['command_id'];scope=record['scope']
    attempts=inventory['attempts'];packets=unique(inventory['packets'],'packet_id');exits=unique(inventory['exits'],'exit_id')
    reports=unique(inventory['reports'],'report_id');transmissions=unique(inventory['transmissions'],'permit_id')
    need(len(attempts)<=record['policy']['max_attempts'] and len(packets)<=4096 and len(reports)<=4096,'inventory_capacity')
    need([a['attempt_id'] for a in attempts]==state['attempt_ids'] and [a['ordinal'] for a in attempts]==list(range(1,len(attempts)+1)),'attempt_set')
    need(len(set(state['attempt_ids']))==len(attempts) and set(selections)==set(state['attempt_ids']),'attempt_selection_set')
    need(set(exits)=={eid for a in attempts for eid in a['exit_ids']},'inventory_exit_set')
    need(all(p['attempt_id'] in state['attempt_ids'] for p in packets.values()),'foreign_packet')
    source_refs=[]
    def retain(kind,ident,body,revision='1'):
        item=dict(kind=kind,source_ref=dict(ref(ident,body),revision=revision))
        if item not in source_refs:source_refs.append(item)
    retain('state',command,state,state['revision'])
    evidence=inventory['evidence'];seen=set()
    for e in evidence:
        M.validate('EvidenceRecord',e);need(M.V.valid_digest(e,'view_digest'),'evidence_digest')
        need(e['command_id']==command and e['scope']==scope,'evidence_owner')
        from command_evidence_model import evidence as check_evidence
        check_evidence(dict(view_body=raw(e),source_body=raw(e['body']),command_id=command,kind=e['kind'],view_digest=e['view_digest'],
            evidence_id=e['source_ref']['id'],revision=M.U(e['source_ref']['revision']),source_digest=e['source_ref']['digest']),scope,command)
        identity=(e['source_ref']['id'],e['source_ref']['revision']);need(identity not in seen,'duplicate_evidence');seen.add(identity)
        if e['kind']=='decision':
            b=e['body'];need(M.V.valid_digest(b,'evidence_digest') and e['source_ref']['digest']==b['evidence_digest'] and b['command_id']==command and b['scope']==scope,'decision_source')
            need(e['source_ref']['id']==b['evidence_id'] and e['source_ref']['revision']=='1','decision_reference')
        retain('evidence',e['source_ref']['id'],e,e['source_ref']['revision'])
    for p in packets.values():
        M.validate('S9__TransportPacket',p);need(M.V.valid_digest(p,'packet_digest') and p['command_id']==command,'packet_source')
        need(p['writer_exit_id'] in exits,'packet_exit_missing');ex=exits[p['writer_exit_id']]
        need(set(ex)==set(EXIT_FIELDS) and ex['device_id']==record['target']['device_id'] and ex['device_session_id']==p['device_session_id'],'packet_exit_owner')
        retain('packet',p['packet_id'],p);retain('exit',ex['exit_id'],ex)
    # 传输原件只证明身份关系，不证明许可仍有效或当前可以发送。
    for t in transmissions.values():
        need(t['packet_id'] in packets,'transmission_packet_missing');p=packets[t['packet_id']]
        need(t['attempt_id']==p['attempt_id'] and t['exit_id']==p['writer_exit_id'] and type(t['ordinal']) is int and t['ordinal']>=0,'transmission_owner')
        retain('transmission',t['permit_id'],t)
    identities=[(t['packet_id'],t['ordinal']) for t in transmissions.values()]
    need(len(identities)==len(set(identities)),'duplicate_transmission_ordinal')
    for r in reports.values():
        b=r['body'];M.validate('S9__SEND_REPORTBody',b)
        need(r['report_id']==b['report_id'] and b['permit_id'] in transmissions,'report_original')
        t=transmissions[b['permit_id']];p=packets[t['packet_id']];ex=exits[t['exit_id']]
        need(b['attempt_id']==t['attempt_id'] and b['packet_ref']==dict(packet_id=p['packet_id'],packet_digest=p['packet_digest']) and b['ordinal']==str(t['ordinal']),'report_packet')
        need(b['transmission_id']==t['transmission_id'] and b['dispatch_intent_id']==t['dispatch_intent_id'],'report_transmission')
        need(r['exit_id']==ex['exit_id'] and r['worker_boot_id']==ex['worker_boot_id'] and r['ipc_session_id']==ex['ipc_session_id'] and b['device_session_id']==ex['device_session_id'],'report_session')
        retain('report',r['report_id'],r)
    # 每个UTC投影都由TIME提供者先验收；没有投影时公开null，禁止借接收墙钟补值。
    times=unique(inventory['time_projections'],'report_id')
    for ident,t in times.items():
        need(ident in reports,'time_report_missing');r=reports[ident];ex=exits[r['exit_id']];b=r['body']
        need(t['report_ref']==ref(ident,r) and b['disposition']=='in_flight' and t['entered_tick_ns']==b['transport_entered_tick_ns'],'time_report_binding')
        need(t['clock_domain_id']==ex['clock_domain_id'] and t['descriptor_digest']==ex['descriptor_digest'] and t['verified'],'time_provider')
        M.validate('V__S0_Timestamp',t['utc']);retain('time_projection',ident,t)
    result=[]
    for a in attempts:
        aid=a['attempt_id'];prepared=a['prepared_state']
        M.validate('V__S0_State',prepared)
        need(prepared['scope']==scope and prepared['command_id']==command and aid in prepared['attempt_ids'] and int(prepared['revision'])<=int(state['revision']),'prepared_original')
        need(prepared['phase']=='queued' and prepared['outcome']=='pending' and prepared['attempt_ids'][-1]==aid,'prepared_phase')
        retain('prepared_state',command,prepared,prepared['revision'])
        own=sorted((p for p in packets.values() if p['attempt_id']==aid),key=lambda p:p['packet_id'])
        exit_ids=sorted(a['exit_ids']);need(len(exit_ids)==len(set(exit_ids)) and all(e in exits for e in exit_ids),'attempt_exit_set')
        need({p['writer_exit_id'] for p in own}<=set(exit_ids),'attempt_packet_exit');public_exits=[]
        for eid in exit_ids:
            ex=exits[eid];rr=[r for r in reports.values() if r['body']['attempt_id']==aid and r['exit_id']==eid]
            need(set(ex)==set(EXIT_FIELDS) and ex['device_id']==record['target']['device_id'],'attempt_exit_owner');retain('exit',eid,ex)
            entered=[r for r in rr if r['body']['disposition']=='in_flight']
            # 同出口单调tick可比较；缺最早投影时保留null，不改选较晚报告。
            first=min(entered,key=lambda r:(int(r['body']['transport_entered_tick_ns']),r['report_id'])) if entered else None
            started=times.get(first['report_id'],{}).get('utc') if first else None
            protocol=sorted({r['body']['protocol_request_id'] for r in rr if r['body']['protocol_request_id'] is not None})
            public_exits.append(dict(exit_ref=ref(eid,ex),**{k:ex[k] for k in ('worker_boot_id','ipc_session_id','device_session_id','clock_domain_id','descriptor_digest')},send_started_at=started,protocol_request_ids=protocol))
        ee=[e for e in evidence if e['body'].get('attempt_id')==aid or aid in e['body'].get('attempt_ids',[])]
        while True:
            refs=[e['source_ref'] for e in ee]
            extra=[e for e in evidence if e not in ee and e['kind']=='invalidation' and e['body']['subject_ref'] in refs]
            if not extra:break
            ee+=extra
        selection=selections[aid];kind=selection['kind'];basis=selection['ref'];outcome='pending'
        need(set(selection)=={'kind','ref'},'outcome_selection')
        if kind=='pending':
            need(basis is None and state['phase']!='finished' and not any(e['kind']=='decision' for e in ee),'pending_unproven')
        elif kind=='unknown':
            need(basis==record['state_ref'] and state['outcome']=='unknown' and state['attempt_ids'][-1]==aid,'unknown_original');outcome='unknown'
        elif kind=='decision':
            choices=[e for e in ee if e['kind']=='decision' and e['source_ref']==basis];need(len(choices)==1,'attempt_decision')
            need(basis in inventory['valid_decision_refs'],'attempt_decision_invalid')
            need(not any(e['kind']=='invalidation' and e['body']['subject_ref']==basis for e in ee),'attempt_decision_invalidated')
            b=choices[0]['body'];need(b['policy_ref']==record['policy']['completion_policy_ref'],'attempt_policy')
            if b['kind']=='completion':
                need(LEVEL[b['achieved']]>=LEVEL[record['policy']['required_completion']],'attempt_completion_level');outcome='succeeded'
            elif b['kind']=='failure':outcome='failed'
            elif b['kind']=='cancellation':outcome='cancelled'
            else:outcome=b['resolved_outcome'];need(outcome in ('succeeded','failed','cancelled','not_sent'),'attempt_resolution')
        else:raise ValueError('outcome_kind')
        # 固定unknown的原attempt不能由迟到完成悄悄改成成功；显式Resolution另行展示。
        if state['outcome']=='unknown' and state['attempt_ids'][-1]==aid:need(outcome=='unknown','unknown_rewrite')
        v=dict(attempt_id=aid,ordinal=a['ordinal'],prepared_state_ref=M.V.state_ref(prepared),packet_refs=[dict(packet_id=p['packet_id'],packet_digest=p['packet_digest']) for p in own],
            exits=public_exits,outcome=outcome,evidence_refs=sorted([e['source_ref'] for e in ee],key=lambda r:(r['id'],int(r['revision']))))
        M.validate('V__S0_AttemptView',v);result.append(v)
    source_refs.sort(key=lambda r:(r['kind'],r['source_ref']['id'],r['source_ref']['revision']))
    projection=dict(scope=scope,command_id=command,state_ref=record['state_ref'],attempts=result,source_refs=source_refs,selections=copy.deepcopy(selections))
    M.V.seal(projection,'projection_digest');Draft202012Validator(G.build()).validate(projection);return projection

def verify(record,inventory,selections,projection):
    expected=project(record,inventory,selections)
    need(projection==expected,'projection_originals')
    need(record['attempts']==expected['attempts'],'attempt_projection_originals')
    need(M.V.valid_digest(record,'record_digest'),'record_digest');return copy.deepcopy(expected['attempts'])
