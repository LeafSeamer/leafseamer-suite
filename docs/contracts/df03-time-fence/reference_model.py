"""有限快照与历史判定，权威输入为人工前提；无服务、SQLite或设备I/O。"""
import hashlib
import rfc8785

LIMIT=10**20-1
RANK={'not_sent':0,'unknown':1,'in_flight':2}


def digest(value):return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def seal(value,key):value[key]=digest({k:v for k,v in value.items() if k!=key});return value
def intact(value,key):return value[key]==digest({k:v for k,v in value.items() if k!=key})
def reference(value,id_key,digest_key):return dict(id=value[id_key],revision=value['revision'],digest=value[digest_key])
def attempt_ref(value):return dict(id=value['barrier_id'],revision='1',digest=digest(value))
def pending(row):return row['resolution']=='unresolved' or (row['resolution']=='never_sent' and row['disposition']=='in_flight')


def registry_error(registry):
    if not intact(registry,'registry_digest'):return 'registry_digest'
    exits={e['exit_id']:e for e in registry['exits']}
    rows={r['permit_id']:r for r in registry['issues']}
    if len(exits)!=len(registry['exits']) or len(rows)!=len(registry['issues']):return 'identity_collision'
    if [e['exit_id'] for e in registry['exits']]!=sorted(exits):return 'exit_order'
    if len({(r['transmission_ref']['id'],r['transmission_ref']['revision']) for r in rows.values()})!=len(rows):return 'transmission_collision'
    initial_packets=[(r['kind'],r['exit_id'],digest(r['packet_ref'])) for r in rows.values() if r['initial_permit_id']==r['permit_id']]
    if len(set(initial_packets))!=len(initial_packets):return 'initial_collision'
    # 全历史连续性，不用两个局部max，也不按列表长度隐式补洞。
    if int(registry['issued_head'])!=len(rows) or [int(r['issued_revision']) for r in registry['issues']]!=list(range(1,len(rows)+1)):
        return 'shared_sequence'
    for r in registry['issues']:
        if r['exit_id'] not in exits:return 'exit_missing'
        if r['time_required']!=(r['time_binding'] is not None):return 'time_shape'
        if r['kind']=='cancel' and r['business_anchor_id'] is not None:return 'cancel_anchor'
        parent=rows.get(r['initial_permit_id'])
        if parent is None or any(parent[n]!=r[n] for n in ('kind','packet_ref','exit_id')) or parent['initial_permit_id']!=parent['permit_id']:
            return 'initial_binding'
        if int(parent['issued_revision'])>int(r['issued_revision']):return 'initial_future'
        if r['kind']=='ordinary' and r['business_anchor_id']!=parent['permit_id']:return 'business_anchor'
        if r['resolution']=='never_sent' and r['disposition']=='unknown':return 'resolution_contradiction'
        if r['time_required']:
            d=r['time_binding']['domain'];e=exits[r['exit_id']]
            if any(d[k]!=registry[k] for k in ('authority_service_id','database_instance_id')):return 'scope'
            if any(d[k]!=e[k] for k in ('clock_domain_id','descriptor_digest')):return 'domain'
    return None


def selected(registry,invalidation):
    domain=invalidation['old_binding']['domain'];floor=int(invalidation['next_time_generation'])
    active=[r for r in registry['issues'] if r['time_required'] and r['time_binding']['domain']==domain
            and int(r['time_binding']['time_generation'])<floor and pending(r)]
    target_ids={r['exit_id'] for r in active}
    target_ids.update(e['exit_id'] for e in registry['exits'] if not e['retired'] and
                      all(e[k]==domain[k] for k in ('clock_domain_id','descriptor_digest')))
    targets=[]
    for exit_id in sorted(target_ids):
        ordinary=[r for r in active if r['exit_id']==exit_id and r['kind']=='ordinary']
        cancel=[r for r in active if r['exit_id']==exit_id and r['kind']=='cancel']
        targets.append(dict(exit_id=exit_id,business_anchor_ids=sorted({r['business_anchor_id'] for r in ordinary}),
            ordinary_permit_ids=sorted(r['permit_id'] for r in ordinary),cancel_permit_ids=sorted(r['permit_id'] for r in cancel)))
    return targets


def cut_error(cut,registry,approved_invalidation):
    error=registry_error(registry)
    if error:return error
    i=cut['invalidation']
    if i!=approved_invalidation or not intact(i,'invalidation_digest'):return 'invalidation_authority'
    domain=i['old_binding']['domain']
    if any(domain[k]!=registry[k] for k in ('authority_service_id','database_instance_id')):return 'scope'
    old=int(i['old_binding']['time_generation'])
    if old==LIMIT or int(i['next_time_generation'])!=old+1:return 'generation'
    if cut['operation_ref']!=i['protection_operation_ref']:return 'operation'
    if cut['registry_ref']!=reference(registry,'registry_id','registry_digest'):return 'registry_ref'
    if cut['issued_cut_revision']!=registry['issued_head']:return 'cut_watermark'
    targets=selected(registry,i)
    if len(targets)>256 or any(len(t[k])>256 for t in targets for k in ('business_anchor_ids','ordinary_permit_ids','cancel_permit_ids')):
        return 'capacity'
    if cut['targets']!=targets:return 'target_set'
    if not intact(cut,'cut_digest'):return 'cut_digest'
    return None


def attempt_error(attempt,cut,history,failures,live=True,already_adopted=False):
    if attempt['cut_ref']!=reference(cut,'cut_id','cut_digest'):return 'cut_ref'
    if attempt['exit_id'] not in {t['exit_id'] for t in cut['targets']}:return 'exit'
    if not live:return 'retired'
    if already_adopted:return 'already_applied'
    if any(a['barrier_id']==attempt['barrier_id'] for a in history):return 'identity_reuse'
    old=[a for a in history if a['cut_ref']==attempt['cut_ref'] and a['exit_id']==attempt['exit_id']]
    old.sort(key=lambda a:int(a['ordinal']))
    previous=old[-1] if old else None
    if int(attempt['ordinal'])!=(int(previous['ordinal'])+1 if previous else 1):return 'attempt_ordinal'
    if attempt['previous_barrier_id']!=(previous['barrier_id'] if previous else None):return 'previous'
    if previous and failures.get(previous['barrier_id']) not in ('cache_miss','deadline_elapsed'):return 'retry_basis'
    return None


def ack_error(ack,attempt,cut,registry,verified_peer=True):
    if not verified_peer:return 'peer'
    if ack['attempt_ref']!=attempt_ref(attempt):return 'attempt'
    if attempt['cut_ref']!=reference(cut,'cut_id','cut_digest'):return 'cut_ref'
    if not intact(ack,'ack_digest'):return 'ack_digest'
    inv=cut['invalidation']
    if ack['invalidation_ref']!=reference(inv,'invalidation_id','invalidation_digest'):return 'invalidation'
    if ack['minimum_time_generation']!=inv['next_time_generation']:return 'floor_echo'
    target=next((t for t in cut['targets'] if t['exit_id']==attempt['exit_id']),None)
    if target is None:return 'exit'
    rows={r['permit_id']:r for r in registry['issues']}
    coverage={}
    for kind in ('ordinary','cancel'):
        items=ack[kind+'_coverage']
        if [r['permit_id'] for r in items]!=target[kind+'_permit_ids']:return 'coverage_set'
        for r in items:
            proofs={'not_sent':('never_received','discarded_unconsumed'),'in_flight':('transport_entered',),'unknown':('send_uncertain',)}
            if r['proof'] not in proofs[r['disposition']]:return 'proof'
            if rows[r['permit_id']]['disposition']=='in_flight' and r['disposition']!='in_flight':return 'downgrade'
            coverage[r['permit_id']]=r['disposition']
    expected=[]
    for anchor in target['business_anchor_ids']:
        original=next(r for r in registry['issues'] if r['kind']=='ordinary' and r['permit_id']==r['initial_permit_id'] and r['business_anchor_id']==anchor)
        values=[coverage[p] for p in target['ordinary_permit_ids'] if rows[p]['business_anchor_id']==anchor]
        # 原锚已经in_flight仍保持强事实；原锚的未知也不能被末次未发覆盖。
        values.append(original['disposition'])
        expected.append(dict(permit_id=anchor,disposition=max(values,key=RANK.get)))
    if ack['business_coverage']!=expected:return 'business_coverage'
    return None


def adoption_error(ack,attempt,history,failures):
    same=[a for a in history if a['cut_ref']==attempt['cut_ref'] and a['exit_id']==attempt['exit_id']]
    if not same or max(same,key=lambda a:int(a['ordinal']))!=attempt:return 'not_latest'
    if attempt['barrier_id'] in failures:return 'failed_attempt'
    if ack['attempt_ref']!=attempt_ref(attempt):return 'attempt'
    return None


def application_error(cut,adopted_exits):
    expected=[t['exit_id'] for t in cut['targets']]
    return None if adopted_exits==expected else 'incomplete_application'


def issue_after_invalidation(required,binding,domain,floor,qualified):
    # 仅时间子域；False不表示已经通过其他发送门控。
    if not required:return None if binding is None else 'unexpected_time'
    if binding is None or binding['domain']!=domain:return 'domain'
    if int(binding['time_generation'])<int(floor):return 'denied_generation'
    return None if qualified else 'unqualified'


def merge_floor(current,ack):return str(max(int(current),int(ack['minimum_time_generation'])))
