"""范围准入与单设备有序闸参考模型。先Schema；可信来源为人工上下文，无I/O。"""
import copy
import hold_ownership_model as H
O=H.O
COMMON=('binding','control_authority_ref','control_epoch','effective_version','authorization_ref','resource_safety_ref','gate_safety_ref')
def aref(a):return O.reference(a,'access_id','access_digest')
def eref(e):return O.reference(e,'assessment_id','assessment_digest')
def revoked(ref,c):return ref in c['revoked_refs']
def current_error(a,c,now):
    if not O.intact(a,'access_digest') or c['accesses'].get(a['access_id'])!=a:return 'access_source'
    if revoked(aref(a),c) or revoked(a['control_authority_ref'],c):return 'revoked'
    if a['binding']!=c['binding']:return 'binding'
    control=c['control_projection']
    if control['pending_operation_id'] is not None:return 'pending_control'
    if (a['control_authority_ref'],a['control_epoch'],a['effective_version'])!=(control['authority_ref'],control['control_epoch'],control['effective_version']):return 'control'
    for k in ('authorization_ref','resource_safety_ref','gate_safety_ref'):
        if a[k]!=c[k] or revoked(a[k],c):return 'current_generation'
    if c['hard_protection_reasons']:return 'hard_protection'
    if a['initial_assessment_ref'] is not None and revoked(a['initial_assessment_ref'],c):return 'revoked'
    if int(a['expires_tick_ns'])>c['access_deadline_tick_ns']:return 'provider_deadline'
    if not int(a['selected_tick_ns'])<=now<int(a['expires_tick_ns']):return 'access_expired'
    return None
def assessment_error(a,e,c,now):
    if not O.intact(e,'assessment_digest') or c['assessments'].get(e['assessment_id'])!=e:return 'assessment_source'
    if revoked(eref(e),c):return 'revoked'
    for k in COMMON:
        if a[k]!=e[k]:return 'assessment_binding'
    if e['protection']!=a['protection']:return 'protection_scope'
    expected={k:v for k,v in e.items() if k not in ('assessment_digest','provider_receipt_ref')}
    receipt=c['assessment_receipts'].get(e['provider_receipt_ref']['id'])
    if receipt is None or receipt!=dict(ref=e['provider_receipt_ref'],content=expected) or revoked(e['provider_receipt_ref'],c):return 'assessment_receipt'
    if eref(e)!=c['current_assessment_ref'] or e['resource_ref']!=c['resource_ref']:return 'stale_assessment'
    initial=c['assessments'].get(a['initial_assessment_ref']['id'])
    if initial is None or not O.intact(initial,'assessment_digest') or eref(initial)!=a['initial_assessment_ref'] or int(initial['sampled_tick_ns'])>int(a['selected_tick_ns']):return 'initial_assessment'
    if not int(initial['sampled_tick_ns'])<=int(e['sampled_tick_ns'])<=now<min(int(e['expires_tick_ns']),int(a['expires_tick_ns'])):return 'assessment_expired'
    p=e['protection'];identity=p['identity']
    if p!=c['approved_protection']:return 'protection_source'
    error=H.identity_error(identity,c)
    if error:return error
    for k in ('policy_ref','ordinary_closure_ref'):
        if revoked(p[k],c):return 'revoked'
    if p['policy_ref']!=c['policy']['ref'] or not c['policy']['approved']:return 'policy'
    if int(a['expires_tick_ns'])>c['policy_deadline_tick_ns'] or int(e['expires_tick_ns'])>c['resource_deadline_tick_ns']:return 'provider_deadline'
    if p['ordinary_closure_ref']!=c['ordinary_closure_ref'] or not c['ordinary_closed'] or c['all_closed']:return 'closure'
    ids=[x['hold_ref']['id'] for x in e['risks']]
    if len(set(ids))!=len(ids) or ids!=sorted(ids) or set(ids)!=set(c['risk_hold_ids']):return 'risk_set'
    if e['risks']!=c['risk_observations']:return 'risk_source'
    if p['hold_ref']['id'] not in ids:return 'protected_hold_missing'
    for risk in e['risks']:
        owner=c['ownerships'].get(risk['hold_ref']['id'])
        if owner is None:return 'owner_missing'
        error=H.ownership_error(owner,c)
        if error:return error
        if (risk['hold_ref'],risk['ownership_ref'],risk['command_ref'],risk['execution_ref'])!=(owner['hold_ref'],
            O.reference(owner,'ownership_id','ownership_digest'),owner['identity']['command_ref'],owner['identity']['execution_ref']):return 'risk_owner'
        if revoked(risk['ownership_ref'],c):return 'revoked'
        if risk['hold_ref']==p['hold_ref']:
            if risk['ownership_ref']!=p['ownership_ref'] or risk['classification']!='active':return 'protected_hold'
            error=H.authority_error(identity,owner,c)
            if error:return error
        elif owner['identity']['kind']!='ordinary' or risk['command_ref']!=identity['command_ref']:return 'unrelated_risk'
        elif risk['classification'] not in c['policy']['allowed_parent_states']:return 'parent_policy'
        # 父占用只核不可变来源，不迁给当前Requester，也不要求父命令重新取得发送权。
    return None
def open_error(a,e,c,now):
    error=current_error(a,c,now)
    if error:return error
    if a['purpose']=='ordinary':return None if c['ordinary_ready'] and e is None else 'ordinary_not_ready'
    if e is None or a['initial_assessment_ref']!=eref(e):return 'initial_assessment'
    if int(e['sampled_tick_ns'])>int(a['selected_tick_ns']):return 'assessment_after_selection'
    return assessment_error(a,e,c,now)
def use_error(a,u,e,c,now):
    error=current_error(a,c,now)
    if error:return error
    if u['gate_access_ref']!=aref(a):return 'use_access'
    if (a['purpose']=='ordinary')!=(u['kind']=='ordinary'):return 'use_kind'
    if not int(a['selected_tick_ns'])<=int(u['selected_tick_ns'])<=now<int(u['expires_tick_ns'])<=int(a['expires_tick_ns']):return 'use_expired'
    owner=next((v for v in c['ownerships'].values() if O.reference(v,'ownership_id','ownership_digest')==u['ownership_ref']),None)
    if owner is None:return 'owner_missing'
    error=H.ownership_error(owner,c) or H.authority_error(u['identity'],owner,c)
    if error:return error
    if revoked(u['ownership_ref'],c) or revoked(u['guard_ref'],c):return 'revoked'
    receipt=c['use_receipts'].get(u['permit_id'])
    if receipt!=u:return 'use_source'
    if u['kind']=='ordinary':return None if c['ordinary_ready'] and e is None else 'ordinary_not_ready'
    if u['identity']!=a['protection']['identity'] or u['ownership_ref']!=a['protection']['ownership_ref']:return 'use_scope'
    if e is None or u['protection_assessment_ref']!=eref(e):return 'use_assessment'
    return assessment_error(a,e,c,now)

def open_ack_error(request,ack,c,now):
    """新增范围与实际OPEN/ACK的投影关联；旧三快照原件语义仍由完整开放提供者核验。"""
    b=request['body'];a=b['gate_access'];binding=a['binding'];out=ack['body']
    for k in O.FRAME_BINDING:
        if request[k]!=binding[k] or ack[k]!=binding[k]:return 'frame_binding'
    if ack['reply_to']!=request['message_id']:return 'reply'
    for k in ('gate_token','gate_revision'):
        if out[k]!=b[k]:return 'ack_gate'
    if out['gate_access_ref']!=aref(a):return 'ack_access'
    if (b['device_session_id'],b['clock_domain_id'],b['descriptor_digest'],b['control_epoch'],b['control_version'])!=(
        binding['device_session_id'],binding['clock_domain_id'],binding['descriptor_digest'],a['control_epoch'],a['effective_version']):return 'body_binding'
    if int(a['expires_tick_ns'])>int(b['lease_until_tick_ns']):return 'open_lease'
    return open_error(a,b['protection_assessment'],c,now)

class Gate:
    """单设备单会话：每个方法代表一帧处理原子步，不模拟真实线程或持久化。"""
    def __init__(self,binding):
        self.binding=copy.deepcopy(binding);self.seq=0;self.revision=0;self.barrier=None;self.token=None
        self.active=None;self.alive=True;self.opens={};self.used={};self.closes={};self.effects=[];self.tokens=set()
    def receive(self,seq,binding):
        if not self.alive:return 'dead_session'
        if binding!=self.binding or seq!=self.seq+1:
            self.active=None;self.alive=False;return 'session_or_sequence'
        self.seq=seq;return None
    def fence(self,seq,binding,revision,barrier):
        error=self.receive(seq,binding)
        if error:return error
        if revision<=self.revision:self.active=None;self.alive=False;return 'revision'
        self.active=None;self.token=None;self.revision=revision;self.barrier=barrier;return 'fenced'
    def close(self,seq,binding,close_id,content):
        error=self.receive(seq,binding)
        if error:return error
        if close_id in self.closes:
            if self.closes[close_id]!=content:self.active=None;self.alive=False;return 'close_conflict'
            return 'cached_close_ack'
        self.closes[close_id]=copy.deepcopy(content);self.active=None;self.barrier=None;self.token=None;return 'closed'
    def open(self,seq,binding,revision,barrier,token,a,e,c,now):
        error=self.receive(seq,binding)
        if error:return error
        key=(a['access_id'],a['revision']);content=O.digest([revision,barrier,token,a,e])
        if key in self.opens:
            if self.opens[key]!=content:self.active=None;self.alive=False;return 'open_conflict'
            return 'cached_open_ack' # 历史ACK不重新赋active，不续租，不复活关闭后的资格。
        if self.active is not None:return 'scope_switch_requires_fence'
        if self.barrier is None or (revision,barrier)!=(self.revision,self.barrier):return 'barrier'
        if a['binding']!=binding:return 'access_exit'
        if token in self.tokens:return 'token_reuse'
        error=open_error(a,e,c,now)
        if error:return error
        self.opens[key]=content;self.active=copy.deepcopy(a);self.token=token;self.tokens.add(token);return 'opened'
    def dispatch(self,seq,binding,revision,token,u,e,c,now,complete_guard):
        error=self.receive(seq,binding)
        if error:return error
        digest=O.digest(u)
        if u['permit_id'] in self.used:
            if self.used[u['permit_id']]!=digest:self.active=None;self.alive=False;return 'permit_conflict'
            return 'cached_permit'
        if self.active is None or (revision,token)!=(self.revision,self.token):return 'closed'
        error=use_error(self.active,u,e,c,now)
        if error:self.active=None;self.barrier=None;return error
        if not complete_guard:return 'complete_guard_rejected'
        self.used[u['permit_id']]=digest;self.effects.append(u['permit_id']);return 'consumed_before_io'
