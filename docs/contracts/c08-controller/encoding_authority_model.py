"""仅编码与持久签发的关联和顺序参考；无网络、数据库或真实权威。"""
import copy, hashlib
import open_plan_model as O

def aref(a):return O.reference(a,'authorization_id','authorization_digest')
def eref(e):return O.reference(e,'evidence_id','evidence_digest')
def raw_digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def content_ref(r):return dict(object_id=r['id'],digest=r['digest'])

def encoding_error(a,request,response,c,now):
    """调用前须Schema；store由可信提供者给定，不能来自客户端自报。"""
    if not O.intact(a,'authorization_digest') or c['authorizations'].get(a['authorization_id'])!=a:return 'authorization_source'
    if aref(a) in c['revoked_refs']:return 'revoked'
    if a['binding']!=c['binding']:return 'binding'
    if any(a[k]!=c[k] or a[k] in c['revoked_refs'] for k in ('admission_source_ref','authorization_snapshot_ref',
            'capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref')):return 'current_source'
    if a['target']!=c['target'] or a['requester']!=c['requester']:return 'requester_or_target'
    if not int(a['created_tick_ns'])<=c['request_tick']<=c['received_tick']<=now<int(a['expires_tick_ns']):return 'expired'
    if request!=c['stored_request'] or response!=c['stored_response']:return 'message_source'
    if any(f[k]!=a['binding'][k] for f in (request,response) for k in O.FRAME_BINDING):return 'exit'
    if response['reply_to']!=request['message_id'] or response['body']['prepare_id']!=request['body']['prepare_id']:return 'reply'
    b=request['body'];out=response['body'];t=a['target']
    if b['encoding_authorization']!=a or out['encoding_authorization_ref']!=aref(a):return 'authorization_binding'
    if b['primitive_id']!=a['primitive_id'] or b['expires_tick_ns']!=a['expires_tick_ns']:return 'request_binding'
    ordinary=t['kind']=='ordinary'
    if request['type']!=('ENCODE_PACKET' if ordinary else 'ENCODE_CANCEL_PACKET'):return 'request_kind'
    if ordinary:
        if (b['command_id'],b['attempt_id'],b['device_session_id'])!=(t['command_ref']['id'],t['proposed_attempt_id'],a['binding']['device_session_id']):return 'request_target'
        if (b['primitive_plan_ref'],b['transport_profile_ref'])!=(content_ref(a['primitive_plan_ref']),content_ref(a['transport_profile_ref'])):return 'request_profile'
        if O.digest(b['request'])!=a['content_digest']:return 'request_content'
    elif b['execution_ref']!=t['execution_ref'] or a['content_digest']!=t['execution_ref']['digest']:return 'request_target'
    if response['type']!=('PREPARE_PACKET' if ordinary else 'PREPARE_CANCEL_PACKET'):return 'encoding_failed'
    p=out['packet'];raw=bytes.fromhex(out['bytes_hex'])
    if p['packet_digest']!=O.digest({k:v for k,v in p.items() if k!='packet_digest'}):return 'packet_digest'
    if p['byte_length']!=len(raw) or not 0<len(raw)<=a['max_bytes'] or p['sha256']!=raw_digest(raw) or p['immutable_bytes_ref']['digest']!=p['sha256']:return 'packet_bytes'
    if p['primitive_id']!=a['primitive_id']:return 'packet_primitive'
    if ordinary:
        if any(p[k]!=a['binding'][k] for k in ('writer_exit_id','device_session_id')):return 'packet_exit'
        if (p['command_id'],p['attempt_id'],p['primitive_plan_ref'],p['transport_profile_ref'])!=(t['command_ref']['id'],t['proposed_attempt_id'],content_ref(a['primitive_plan_ref']),content_ref(a['transport_profile_ref'])):return 'packet_target'
    else:
        if (p['execution_ref'],p['cancellation_id'],p['parent_command_id'],p['transport_profile_ref'])!=(t['execution_ref'],t['cancellation_ref']['id'],t['command_ref']['id'],a['transport_profile_ref']):return 'packet_target'
        if any(p['exit'][k]!=a['binding'][k] for k in p['exit'] if k!='socket_instance_id'):return 'packet_exit'
    # 只能使用登记的当前socket/protocol；字节正确不证明适配器或参数资格。
    if (p['socket_instance_id'] if ordinary else p['exit']['socket_instance_id'])!=c['socket_instance_id'] or p['protocol_session']!=c['protocol_session']:return 'packet_session'
    return None

def evidence(a,request,response,received):
    p=response['body']['packet']
    return O.seal(dict(evidence_id='evidence.'+request['body']['prepare_id'],revision='1',authorization_ref=aref(a),
      binding=copy.deepcopy(a['binding']),prepare_id=request['body']['prepare_id'],request_message_id=request['message_id'],
      response_message_id=response['message_id'],request_digest=O.digest(request),response_digest=O.digest(response),
      packet_ref={k:p[k] for k in ('packet_id','packet_digest')},bytes_digest=p['sha256'],byte_length=p['byte_length'],
      received_tick_ns=str(received)),'evidence_digest')

class Order:
    """每步是合成原子动作；FinalizationLink需外部完整AdmissionSeal支持。"""
    CURRENT=('gate_access_ref','control_authority_ref','authorization_ref','resource_safety_ref','gate_safety_ref')
    def __init__(self):
        self.prepared={};self.records={};self.installed={};self.consumed={};self.charges={}
        self.uncertain=set();self.retired=False;self.effects=[]
    def prepare(self,e,encoding,now):
        if self.retired:return 'retired'
        if not O.intact(e,'evidence_digest'):return 'evidence_digest'
        old=self.prepared.get(e['evidence_id'])
        if old is not None:return 'cached_preparation' if old==e else 'preparation_conflict'
        error=encoding_error(*encoding,now)
        if error:return 'encoding_'+error
        if e!=evidence(*encoding[:3],encoding[3]['received_tick']):return 'evidence_binding'
        self.prepared[e['evidence_id']]=copy.deepcopy(e);return 'prepared'
    def finalize(self,v,source,encoding,outcome='confirmed'):
        if self.retired:return 'retired'
        pid=v['permit_id']
        if pid in self.uncertain:return 'commit_uncertain'
        old=self.records.get(pid)
        if old is not None:return 'query_original' if old==v else 'permit_conflict'
        e=self.prepared.get(v['encoding_evidence_ref']['id'])
        if e is None or eref(e)!=v['encoding_evidence_ref'] or e['binding']!=v['binding'] or e['packet_ref']!=v['packet_ref']:return 'preparation_binding'
        if source!=v:return 'seal_source'
        error=encoding_error(*encoding,int(v['committed_tick_ns']))
        if error:return 'encoding_'+error
        if e!=evidence(*encoding[:3],encoding[3]['received_tick']):return 'evidence_binding'
        if int(v['issued_revision'])<1 or not int(e['received_tick_ns'])<=int(v['committed_tick_ns'])<int(v['send_before_tick_ns']):return 'commit_time'
        if not int(v['send_not_before_tick_ns'])<int(v['send_before_tick_ns']):return 'send_window'
        if v['budget_charge_ref']['id'] in self.charges:return 'charge_reuse'
        if any(x['issued_revision']==v['issued_revision'] for x in self.records.values()):return 'issue_reuse'
        if outcome=='rollback':return 'rolled_back'
        if outcome=='unknown':self.uncertain.add(pid);return 'commit_uncertain'
        if outcome!='confirmed':raise ValueError(outcome)
        self.records[pid]=copy.deepcopy(v);self.charges[v['budget_charge_ref']['id']]=pid;return 'committed'
    def current_error(self,v,c,now):
        if self.retired:return 'retired'
        if c['binding']!=v['binding'] or any(c[k]!=v[k] for k in self.CURRENT):return 'changed'
        if c['pending_control'] or c['hard_protection']:return 'protected'
        if not int(v['committed_tick_ns'])<=now<int(v['send_before_tick_ns']):return 'expired'
        return None
    def guard_ack(self,pid,guard,packet,c,now):
        if pid in self.uncertain:return 'commit_uncertain'
        v=self.records.get(pid)
        if v is None:return 'no_commit'
        error=self.current_error(v,c,now)
        if error:return error
        if (guard,packet)!=(v['guard_ref'],v['packet_ref']):return 'guard_binding'
        self.installed[pid]=(copy.deepcopy(guard),copy.deepcopy(packet));return 'installed'
    def dispatch(self,pid,c,now,io='sent'):
        if self.retired:return 'retired'
        if pid in self.uncertain:return 'commit_uncertain'
        if pid in self.consumed:return 'cached_result'
        v=self.records.get(pid)
        if v is None:return 'no_commit'
        error=self.current_error(v,c,now)
        if error:return error
        if now<int(v['send_not_before_tick_ns']):return 'too_early'
        if self.installed.get(pid)!=(v['guard_ref'],v['packet_ref']):return 'no_guard_ack'
        # 真实系统在设备串行出口先消费；异常不退还许可或预算。
        self.consumed[pid]='unknown'
        if io=='sent':self.effects.append(pid);self.consumed[pid]='in_flight'
        elif io!='crash':raise ValueError(io)
        return self.consumed[pid]
    def restart(self):
        self.retired=True;self.installed.clear() # 仅模型终止资格，不冒充监督器已证进程退出。
