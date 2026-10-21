"""有限采集器账本和来源判定；无网络、磁盘或操作系统调用。"""
import copy
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('collector_time',Path(__file__).resolve().parent.parent/'df03-reference/reference_model.py')
T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)


def channel_error(channel, context):
    if not context['peer_verified'] or channel != context['channel']:
        return 'peer'
    if not context['runtime_valid']:
        return 'runtime'


def configuration_error(config, context):
    if config != context['approved_config'] or not T.intact(config,'config_digest'):
        return 'authority'
    if config['binding']['domain'] != context['channel']['domain']:
        return 'binding'
    if config['bootstrap_receipt_ref'] != context['channel']['bootstrap_receipt_ref']:
        return 'binding'
    if config['collector_artifact_ref'] != config['profile']['collector_artifact_ref']:
        return 'artifact'
    error=T.binding_error(config['binding'],context['time_context'])
    if error:return error
    for n in ('source','profile','policy','approval'):
        if config[n] != context['time_context'][n]:return 'evidence'
    if config['limits']['max_blob_bytes'] > config['profile']['max_packet_bytes']:
        return 'capacity'


def reserve(poll, ledger, context, now):
    error=channel_error(context['channel'],context) or configuration_error(context['config'],context)
    if error:return error
    if not T.intact(poll,'poll_digest'):return 'digest'
    old=ledger.get(poll['poll_id'])
    if old is not None:
        return 'historical' if old['poll']==poll else 'identity_conflict'
    config=context['config']
    if context['stopped'] or poll['stop_generation']!=context['stop_generation']:return 'stopped'
    if (poll['binding']!=config['binding'] or poll['config_ref']!=T.object_ref(config,'config_id','config_digest')
        or poll['endpoint_ref'] not in context['approved_endpoints']):return 'binding'
    if not int(poll['issued_tick_ns'])<=int(poll['not_before_tick_ns'])<=now<int(poll['expires_tick_ns']):return 'expired'
    if int(poll['expires_tick_ns'])-int(poll['issued_tick_ns'])>int(config['limits']['poll_lease_ns']):return 'expired'
    active=[x for x in ledger.values() if x['state'] in ('reserved','consumed')]
    if len(active)>=config['limits']['max_outstanding'] or any(x['poll']['binding']['source_ref']==poll['binding']['source_ref'] for x in active):
        return 'capacity'
    if any(x['poll']['correlation_ref']==poll['correlation_ref'] for x in ledger.values()):return 'identity_conflict'
    ledger[poll['poll_id']]=dict(poll=copy.deepcopy(poll),state='reserved',consumed_tick=None)
    return 'reserved'


def consume(poll_id,ledger,context,now,fail_after_consume=False):
    if channel_error(context['channel'],context):return 'runtime'
    entry=ledger.get(poll_id)
    if entry is None:return 'cache_missing'
    if entry['state']!='reserved':return 'no_resend'
    p=entry['poll'];config=context['config']
    if context['stopped'] or p['stop_generation']!=context['stop_generation']:return 'stopped'
    if p['binding']!=config['binding'] or configuration_error(config,context):return 'binding'
    if p['endpoint_ref'] not in context['approved_endpoints']:return 'binding'
    if not int(p['not_before_tick_ns'])<=now<int(p['expires_tick_ns']):return 'expired'
    prior=[x['consumed_tick'] for x in ledger.values() if x['consumed_tick'] is not None and
           x['poll']['binding']['source_ref']==p['binding']['source_ref']]
    if prior and now-max(prior)<int(config['limits']['minimum_poll_interval_ns']):return 'interval'
    entry.update(state='consumed',consumed_tick=now)
    # 先消费，故障可在真正I/O之前发生；这里只返回模型观察，不发包。
    return 'unknown' if fail_after_consume else 'io_allowed_once'


def capture_error(capture,poll,context):
    if not T.intact(capture,'capture_digest'):return 'digest'
    if capture['poll_ref']!=T.object_ref(poll,'poll_id','poll_digest') or capture['binding']!=poll['binding']:return 'binding'
    if capture!=context['verified_capture']:return 'evidence'
    if capture['status']!='candidate':return 'not_candidate'
    request=capture['request'];exchange=capture['exchange']
    if (request['binding']!=poll['binding'] or request['correlation_ref']!=poll['correlation_ref'] or
        request['endpoint_ref']!=poll['endpoint_ref']):return 'request'
    m1,m4=int(request['send_before_tick_ns']),int(exchange['receive_after_tick_ns'])
    if not int(poll['not_before_tick_ns'])<=m1<=m4<int(poll['expires_tick_ns']):return 'expired'
    if int(capture['reported_tick_ns'])<m4:return 'order'
    if int(request['response_deadline_tick_ns'])>int(poll['expires_tick_ns']):return 'deadline'
    tc=context['time_context']
    for n in ('request','exchange','authentication','error','era'):
        if capture[n]!=tc[n]:return 'evidence'
    error=T.exchange_error(exchange,tc)
    if error:return error
    expected=[('request',request['request_bytes_ref'],request['request_size']),
              ('response',exchange['response_bytes_ref'],exchange['response_size'])]
    actual=[(b['purpose'],b['content_ref'],b['size']) for b in capture['blobs']]
    if actual!=expected:return 'blobs'
    for b in capture['blobs']:
        if (b['owner']!=poll['binding']['domain'] or not context['sealed_blobs_verified'] or
            b['size']>context['config']['limits']['max_blob_bytes']):return 'blobs'


def stop(stop_record,ledger,context):
    if stop_record!=context['approved_stop'] or not T.intact(stop_record,'stop_digest'):return 'authority'
    if stop_record['config_ref']!=T.object_ref(context['config'],'config_id','config_digest'):return 'binding'
    if context['stopped']:return 'historical' if context.get('applied_stop')==stop_record else 'conflict'
    if int(stop_record['stop_generation'])!=int(context['stop_generation'])+1:return 'generation'
    active=[T.object_ref(x['poll'],'poll_id','poll_digest') for x in ledger.values() if x['state'] in ('reserved','consumed')]
    key=lambda r:(r['id'],r['revision'],r['digest'])
    if sorted(active,key=key)!=sorted(stop_record['poll_refs'],key=key):return 'coverage'
    context.update(stopped=True,stop_generation=stop_record['stop_generation'],applied_stop=copy.deepcopy(stop_record))
    for x in ledger.values():
        if x['state']=='reserved':x['state']='closed'
    return 'closed'


def lookup_commit(capture_ref,stored,context):
    if not context['current_authorized']:return 'forbidden'
    if not context['storage_healthy']:return 'unavailable'
    receipt=stored.get(capture_ref['id'])
    if receipt is None:return 'not_found'
    if receipt['capture_ref']!=capture_ref:return 'identity_conflict'
    return copy.deepcopy(receipt)


def record_capture(capture,ledger,context):
    if capture!=context['verified_capture'] or not T.intact(capture,'capture_digest'):return 'evidence'
    key=capture['poll_ref']['id'];entry=ledger.get(key)
    if entry is None:return 'cache_missing'
    if capture['poll_ref']!=T.object_ref(entry['poll'],'poll_id','poll_digest'):return 'binding'
    if 'capture' in entry:return 'historical' if entry['capture']==capture else 'identity_conflict'
    if capture['status']=='candidate' and entry['state']!='consumed':return 'not_consumed'
    if capture['status']=='candidate' and int(capture['request']['send_before_tick_ns'])!=entry['consumed_tick']:return 'm1'
    entry.update(state='reported',capture=copy.deepcopy(capture))
    return 'reported'


def accept_envelope(frame,context,seen,sequence):
    if channel_error(frame['channel'],context):return 'peer',sequence
    key=frame['message_id'];old=seen.get(key)
    if old is not None:return ('duplicate' if old==frame else 'identity_conflict'),sequence
    value=int(frame['sequence'])
    if value!=sequence+1:return 'sequence',sequence
    seen[key]=copy.deepcopy(frame)
    return 'accepted',value


def stop_ack_error(ack,stop_record,ledger,context):
    if not context['stopped'] or context.get('applied_stop')!=stop_record:return 'not_stopped'
    if ack['stop_ref']!=T.object_ref(stop_record,'stop_id','stop_digest'):return 'binding'
    captured={r['id'] for r in stop_record['poll_refs']}
    consumed=[x for key,x in ledger.items() if key in captured and x['consumed_tick'] is not None]
    expected=[T.object_ref(x['poll'],'poll_id','poll_digest') for x in consumed]
    key=lambda r:(r['id'],r['revision'],r['digest'])
    if sorted(ack['consumed_poll_refs'],key=key)!=sorted(expected,key=key):return 'coverage'
    if any(int(ack['closed_tick_ns'])<x['consumed_tick'] for x in consumed):return 'order'
