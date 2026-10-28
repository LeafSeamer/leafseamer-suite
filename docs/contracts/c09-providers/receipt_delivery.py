"""可信账本的有限回执投影；不提交业务操作，不从异常猜测受理结果。"""
import copy
import time
import readset as R
import coordinator as G
import delivery as D

UNAVAILABLE_REASONS={'conflict','not_found_or_invisible','source_unavailable','capacity_exceeded','expired','unknown_outcome','protocol_error'}


def enqueue_status(delivery,dependencies,current_context,request,expected_identity,status_reader,*,ttl_ms=2000,clock=time.monotonic_ns):
    """status_reader由可信宿主独占，返回精确原意图及当前有权查询的账本观察。"""
    R.need(type(delivery) is D.Delivery and callable(status_reader) and callable(clock),'status_reader')
    R.need(type(dependencies) in [list,tuple] and 1<=len(dependencies)<=16 and all(type(d) is G.Dependency for d in dependencies) and len(set(dependencies))==len(dependencies),'dependency_set')
    R.need(type(ttl_ms) is int and 1<=ttl_ms<=2000,'deadline_budget')
    R.bounded(current_context);R.bounded(request,65536);R.bounded(expected_identity)
    current=copy.deepcopy(current_context);request=copy.deepcopy(request);expected=copy.deepcopy(expected_identity);deps=tuple(dependencies)
    start=clock();R.need(type(start) is int and start>=0,'clock');deadline=start+ttl_ms*1000000
    owner=delivery._owner;contract=delivery._contract
    with owner._lock:
        o=delivery._get();R.need(not o['busy'],'output_preparing')
        R.need(set(o['deps'])<=set(deps) and all(d in owner._dependencies for d in deps),'output_dependencies')
        o['busy']=True;o['pending_deps']=deps;sequence=o['next_sequence']
    try:
        delivery._check_request(current,request)
        R.need(contract.validate('panel__Channel_RequestIdentity',expected),'request_identity_schema')
        R.need(all(expected[k]==current['scope'][k] for k in ['authority_service_id','database_instance_id']) and
            expected['panel_session_id']==request['public_binding']['panel_session_id'] and expected['document_generation']==request['public_binding']['document_generation'] and expected['request_id']==request['request_id'],'request_identity')
        record=status_reader(copy.deepcopy(current),copy.deepcopy(request))
        R.bounded(record);record=copy.deepcopy(record)
        R.need(type(record) is dict and set(record)=={'invocation','observation'},'status_record')
        invocation=record['invocation'];R.need(contract.validate('panel__Service_Invocation',invocation),'invocation_schema');intent=invocation['intent']
        R.need(R.bounded(intent['identity'])==R.bounded(expected),'invocation_identity')
        R.need(intent['method']==request['method'] and R.bounded(intent['normalized_arguments'])==R.bounded(request['payload']) and intent['activation_ref']==request['activation_ref'],'invocation_binding')
        # target_handle到原target_ref及当前主体权限的权威映射仍由可信reader核验。
        for name in ['delegation_ref','target_ref']:
            if intent[name] is not None:R.need(all(intent[name][k]==current['scope'][k] for k in ['authority_service_id','database_instance_id']),'invocation_scope')
        observation=record['observation'];R.need(type(observation) is dict,'status_observation')
        accepted_ref=None
        if observation.get('kind')=='receipt':
            R.need(set(observation)=={'kind','receipt'},'status_observation')
            receipt=observation['receipt'];R.need(contract.validate('panel__Service_RequestReceipt',receipt),'receipt_schema')
            R.need(R.bounded(receipt['identity'])==R.bounded(expected) and receipt['intent_digest']==R.digest(intent) and receipt['method']==request['method'] and receipt['activation_ref']==intent['activation_ref'],'receipt_binding')
            R.need(receipt['projection_state']!='available' and receipt['projection'] is None,'projection_requires_readset')
            status=receipt['state'];reason=receipt['reason_code'];projection=receipt['projection_state'];accepted_ref=receipt['accepted_result_ref']
            if accepted_ref is not None:R.need(all(accepted_ref[k]==current['scope'][k] for k in ['authority_service_id','database_instance_id']),'receipt_scope')
        else:
            R.need(set(observation)=={'kind','reason_code'} and observation['kind']=='unavailable' and observation['reason_code'] in UNAVAILABLE_REASONS,'status_observation')
            status='unavailable';reason=observation['reason_code'];projection='not_applicable'
        frame=dict(protocol_version=delivery._binding['protocol_version'],type='host.result',public_binding=delivery._binding,activation_ref=delivery._activation,
            channel_sequence=str(sequence),request_id=request['request_id'],method=request['method'],status=status,reason_code=reason,projection_state=projection,result=None)
        R.need(contract.validate('panel__Channel_Result',frame),'result_frame_schema');payload=R.bounded(frame,65536)
        with owner._lock:
            o=delivery._get();R.need(o['busy'] and all(d in owner._dependencies for d in deps),'dependency_stale')
            now=clock();R.need(type(now) is int and start<=now<deadline,'status_expired');delivery._get()
            identity=delivery._capacity(o,request,payload,sequence);outcome=delivery._outcome(o,request['request_id'],status,reason,accepted_ref)
            intent_digest=R.digest(intent);previous=o['receipt_bindings'].get(request['request_id'])
            R.need(previous is None or previous==intent_digest,'original_intent_changed')
            token=object();o['queue'].append(dict(token=token,payload=payload,deps=deps,context=current,deadline=deadline,last=now,clock=clock,sequence=sequence))
            o['next_sequence']+=1;o['used'][request['request_id']]=identity;o['receipt_bindings'][request['request_id']]=intent_digest
            if outcome is not None:o['outcomes'][request['request_id']]=outcome
            return token
    except BaseException:
        with owner._lock:owner._close_output(owner._outputs[delivery])
        raise
    finally:
        with owner._lock:
            o=owner._outputs[delivery];o['busy']=False;o['pending_deps']=()
