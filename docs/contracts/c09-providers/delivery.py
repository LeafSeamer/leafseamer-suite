"""当前面板结果的完整帧队列及局部单次释放；不是浏览器端口实现。"""
import copy
import hashlib
import json
import socket
import readset as R
import coordinator as G
import typed_validators as T

MAX_SEQUENCE=10**20-1
SESSION_KEYS={'selection','authority','public_binding_digest','activation_digest','installation_digest','approval_digest','authorization_digest','scope'}


class SocketSink:
    """实际非阻塞明文出口，仅用于隔离传输参考。"""
    def __init__(self,sock):
        R.need(type(sock) is socket.socket,'socket_required');self._socket=sock;sock.setblocking(False)
    def write_once(self,payload):
        R.need(self._socket.gettimeout()==0,'blocking_transport');return self._socket.send(payload)


class Delivery:
    def __init__(self,coordinator,contract,dependencies,session_context,public_binding,activation_ref,sink,*,next_sequence,max_items=16,max_bytes=262144):
        R.need(type(coordinator) is G.Coordinator and type(contract) is T.Contract,'delivery_owner')
        R.need(type(next_sequence) is str and next_sequence.isascii() and next_sequence.isdigit() and str(int(next_sequence))==next_sequence and 1<=int(next_sequence)<=MAX_SEQUENCE,'output_sequence')
        R.need(type(max_items) is int and 1<=max_items<=16 and type(max_bytes) is int and 1<=max_bytes<=262144,'output_budget')
        R.need(type(dependencies) in [list,tuple] and 1<=len(dependencies)<=16 and all(type(d) is G.Dependency for d in dependencies) and len(set(dependencies))==len(dependencies),'dependency_set')
        R.bounded(session_context);R.bounded(public_binding);R.bounded(activation_ref)
        R.need(set(session_context)==SESSION_KEYS and session_context['selection']==T.FIXED_SELECTION,'session_context')
        R.need(contract.validate('panel__Channel_PublicBinding',public_binding) and contract.validate('panel__Channel_ActivationRef',activation_ref),'channel_binding')
        R.need(R.digest(public_binding)==session_context['public_binding_digest'] and R.digest(activation_ref)==session_context['activation_digest'],'channel_digest')
        R.need(callable(getattr(sink,'write_once',None)),'output_sink')
        self._owner=coordinator;self._contract=contract;self._binding=copy.deepcopy(public_binding);self._activation=copy.deepcopy(activation_ref);self._context=copy.deepcopy(session_context)
        self._sink=sink;self._max_items=max_items;self._max_bytes=max_bytes
        self._refs={}
        for rule in contract._defs['panel__Channel_Result']['allOf']:
            condition=rule.get('if',{}).get('properties',{})
            if 'method' in condition:self._refs[condition['method']['const']]=copy.deepcopy(rule['then']['properties']['result']['properties']['schema_ref']['const'])
        R.need(set(self._refs)==set(R.BINDINGS['methods']),'result_method_registry')
        with coordinator._lock:
            R.need(not coordinator._closed and all(d in coordinator._dependencies for d in dependencies),'dependency_stale')
            R.need(len(coordinator._outputs)<64,'output_channel_budget')
            # 同一公共通道不能出现两个独立序号所有者，墓碑保留到协调器结束。
            identity=R.digest(public_binding)
            R.need(all(o['identity']!=identity for o in coordinator._outputs.values()),'output_channel_reused')
            coordinator._outputs[self]=dict(identity=identity,deps=tuple(dependencies),pending_deps=(),queue=[],closed=False,busy=False,releasing=False,next_sequence=int(next_sequence),sent_sequence=None,used={})

    def _get(self):
        o=self._owner._outputs[self];R.need(not o['closed'] and not self._owner._closed,'output_closed');return o

    def enqueue(self,reading,candidate,current_context,request,accepted_guard):
        """accepted_guard核验可信请求账本；不从结果结构推断业务已受理。"""
        R.need(callable(accepted_guard),'acceptance_guard')
        R.bounded(current_context);current_context=copy.deepcopy(current_context)
        R.bounded(request,65536);request=copy.deepcopy(request);owner=self._owner
        with owner._lock:
            o=self._get();R.need(not o['busy'],'output_preparing')
            raw=owner._get(reading);deps=owner._reads[reading][1]
            R.need(set(o['deps'])<=set(deps),'output_dependencies')
            o['busy']=True;o['pending_deps']=deps;sequence=o['next_sequence']
        try:
            with raw._lock:
                raw._current();R.need(raw._state=='sealed' and candidate is raw._candidate,'candidate_binding');value=json.loads(raw._output)
            R.need({k:current_context[k] for k in SESSION_KEYS}==self._context,'session_changed')
            R.need(self._contract.validate('panel__Channel_Request',request),'request_schema')
            R.need(request['public_binding']==self._binding and request['activation_ref']==self._activation,'request_channel')
            R.need(request['request_id']==current_context['request_id'] and request['method']==current_context['method'] and R.digest(request['payload']['value'])==current_context['input_digest'],'request_binding')
            R.need(accepted_guard(copy.deepcopy(current_context),copy.deepcopy(request)) is True,'request_not_accepted')
            frame=dict(protocol_version=self._binding['protocol_version'],type='host.result',public_binding=self._binding,activation_ref=self._activation,
                channel_sequence=str(sequence),request_id=request['request_id'],method=request['method'],status='accepted',reason_code='ok',projection_state='available',result=dict(schema_ref=self._refs[request['method']],value=value))
            R.need(self._contract.validate('panel__Channel_Result',frame),'result_frame_schema');payload=R.bounded(frame,65536)
            with owner._lock:
                o=self._get();R.need(o['busy'] and all(d in owner._dependencies for d in deps),'dependency_stale')
                identity=R.digest(request);previous=o['used'].get(request['request_id'])
                R.need(previous==identity or (previous is None and len(o['used'])<256),'result_identity')
                R.need(sequence<=MAX_SEQUENCE,'output_sequence')
                R.need(len(o['queue'])<self._max_items and sum(len(x['payload']) for x in o['queue'])+len(payload)<=self._max_bytes,'output_capacity')
                # 读集消费和队列登记之间没有解锁或外部回调。
                consumed=raw.consume(current_context,candidate);R.need(R.bounded(consumed)==R.bounded(value),'result_changed')
                token=object();o['queue'].append(dict(token=token,payload=payload,deps=deps,context=copy.deepcopy(current_context),deadline=raw._expires,last=raw._last,clock=raw._clock,sequence=sequence))
                o['next_sequence']+=1;o['used'][request['request_id']]=identity;return token
        except BaseException:
            with owner._lock:owner._close_output(owner._outputs[self])
            raise
        finally:
            with owner._lock:
                owner._drop(reading);o=owner._outputs[self];o['busy']=False;o['pending_deps']=()

    def release(self,ticket,current_reader):
        """正文资格重读在锁外；最后复核和单次非阻塞交付在同一锁内。"""
        R.need(callable(current_reader),'current_reader');owner=self._owner
        with owner._lock:
            o=self._get();R.need(not o['releasing'],'output_releasing')
            R.need(o['queue'] and o['queue'][0]['token'] is ticket,'output_head');item=o['queue'][0];o['releasing']=True
        try:
            digest=hashlib.sha256(item['payload']).hexdigest();current=current_reader(digest)
            R.need(R.bounded(current)==R.bounded(item['context']),'current_context_changed')
            with owner._lock:
                o=self._get();R.need(o['queue'] and o['queue'][0] is item and all(d in owner._dependencies for d in item['deps']),'dependency_stale')
                now=item['clock']();R.need(type(now) is int and item['last']<=now<item['deadline'],'output_expired');item['last']=now
                # 时钟读取也不能重入撤销后继续输出。
                self._get()
                try:count=self._sink.write_once(item['payload'])
                except BlockingIOError as e:
                    if getattr(e,'characters_written',0)==0:return dict(status='would_block',bytes_accepted=0)
                    owner._close_output(o);return dict(status='indeterminate',bytes_accepted=None)
                except Exception:
                    owner._close_output(o);return dict(status='indeterminate',bytes_accepted=None)
                if o['closed'] or type(count) is not int or not 0<=count<=len(item['payload']):
                    owner._close_output(o);return dict(status='indeterminate',bytes_accepted=None)
                if count!=len(item['payload']):
                    owner._close_output(o);return dict(status='partial_closed',bytes_accepted=count)
                o['queue'].pop(0);o['sent_sequence']=item['sequence'];return dict(status='handed_off',bytes_accepted=count,channel_sequence=str(item['sequence']),payload_digest=digest)
        except BaseException:
            with owner._lock:owner._close_output(owner._outputs[self])
            raise
        finally:
            with owner._lock:owner._outputs[self]['releasing']=False

    def close(self):
        with self._owner._lock:self._owner._close_output(self._owner._outputs[self])

    def state(self):
        with self._owner._lock:
            o=self._owner._outputs[self]
            return dict(closed=o['closed'],queued=len(o['queue']),queued_bytes=sum(len(x['payload']) for x in o['queue']),sent_sequence=None if o['sent_sequence'] is None else str(o['sent_sequence']))
