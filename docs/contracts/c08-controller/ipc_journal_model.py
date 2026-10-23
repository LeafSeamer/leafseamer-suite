"""共享消息的有限事务和准备覆盖模型；无真实IPC、SQLite或设备调用。"""
import copy, hashlib
import build_ipc_journal as G
import open_plan_model as O
clone=copy.deepcopy
SESSION_KEYS=('ipc_session_id','controller_boot_id','worker_boot_id','clock_domain_id','descriptor_digest')

class Journal:
    """受信解码后合成会话的双向日志；apply参数是假定领域提交结果。"""
    def __init__(self,binding,devices,limit=128,reserved=8):
        self.binding=clone(binding);self.devices=set(devices);self.limit=limit;self.reserved=reserved
        self.head={'c2w':0,'w2c':0};self.rows={};self.slots={};self.effects=[]
        self.state='active';self.volatile={};self.protected_count=0
    def fail(self,reason):self.state='failed';return reason
    def accept(self,f,direction,wire,domain_result='applied',fault=None,protected=False):
        # Schema、重复JSON键和报文长度校验由真实入口先完成。
        if self.state=='failed':return 'session_failed'
        if f['ipc_version']!=G.VERSION or any(f[k]!=self.binding[k] for k in SESSION_KEYS):return self.fail('session_binding')
        kind=f['type'];expected='c2w' if kind in G.C2W else 'w2c' if kind in G.W2C else None
        if direction!=expected:return self.fail('direction')
        device=f['device_id']
        if device is not None and device not in self.devices:return self.fail('device')
        key=(direction,f['message_id']);identity=(O.digest(f),hashlib.sha256(wire).hexdigest(),len(wire))
        if key in self.rows:
            return 'duplicate' if self.rows[key]['identity']==identity else self.fail('message_conflict')
        mode=f['journal_mode']
        if mode=='volatile_close':
            if kind not in ('CLOSE_GATE','CLOSE_GATE_ACK') or f['seq'] is not None or device is not None:return self.fail('volatile_shape')
            if kind=='CLOSE_GATE' and f['body']['scope']!='controller':return self.fail('volatile_scope')
            if key in self.volatile:return 'duplicate' if self.volatile[key]['identity']==identity else self.fail('volatile_conflict')
            if kind=='CLOSE_GATE_ACK':
                req=self.volatile.get(('c2w',f['reply_to']))
                if req is None or req['frame']['body']['close_id']!=f['body']['close_id']:return self.fail('volatile_reply')
                if set(f['body']['closed_device_ids'])!=self.devices:return self.fail('volatile_coverage')
            elif f['reply_to'] is not None:return self.fail('volatile_reply')
            self.state='terminal_closed';self.volatile[key]={'identity':identity,'frame':clone(f)}
            return 'volatile_closed' if kind=='CLOSE_GATE' else 'volatile_ack'
        if mode!='durable':return self.fail('mode')
        if self.state!='active':return 'terminal_session'
        seq=int(f['seq']);slot=(direction,seq)
        if slot in self.slots:return self.fail('sequence_conflict')
        if seq!=self.head[direction]+1:return self.fail('sequence_gap')
        if seq==1 and kind!=('HELLO' if direction=='w2c' else 'HELLO_ACK'):return self.fail('handshake_order')
        if seq>1 and (self.head['c2w']==0 or self.head['w2c']==0):return self.fail('handshake_incomplete')
        allowed=G.REPLIES.get(kind,[]);opposite='w2c' if direction=='c2w' else 'c2w'
        req=self.rows.get((opposite,f['reply_to'])) if f['reply_to'] is not None else None
        if allowed:
            if req is None or req['frame']['type'] not in allowed:return self.fail('reply_type')
            if kind!='CLOSE_GATE_ACK' and device!=req['frame']['device_id']:return self.fail('reply_device')
        elif f['reply_to'] is not None:return self.fail('unexpected_reply')
        if len(self.rows)>=self.limit+(self.reserved if protected else 0):return 'capacity'
        # 不按消息名字自动可信化保护槽，protected须由来源/预算提供者授予。
        before=clone((self.head,self.rows,self.slots,self.effects))
        self.rows[key]={'identity':identity,'frame':clone(f),'disposition':domain_result}
        self.slots[slot]=key
        if fault=='after_record':self.head,self.rows,self.slots,self.effects=before;return 'rolled_back'
        self.effects.append((key,domain_result));self.head[direction]=seq
        if fault=='before_commit':self.head,self.rows,self.slots,self.effects=before;return 'rolled_back'
        if fault=='commit_unknown':self.state='terminal_closed';return 'lookup_only'
        return domain_result

def deny_error(request,ack,source,received):
    r=request['body'];a=ack['body']
    if not O.intact(r,'request_digest'):return 'digest'
    if any(r[k]!=source[k] for k in ('binding','prepare_id','encoding_authorization_ref','encode_message_id','encode_frame_digest','revocation_ref')):return 'source'
    if request!=source['stored_deny_request']:return 'request_source'
    if any(f[k]!=r['binding'][k] for f in (request,ack) for k in O.FRAME_BINDING):return 'frame_binding'
    if a['binding']!=r['binding'] or request['type']!='DENY_ENCODING' or ack['type']!='DENY_ENCODING_ACK':return 'binding'
    if request['reply_to'] is not None or ack['reply_to']!=request['message_id']:return 'reply'
    if (a['prepare_id'],a['deny_ref'],a['deny_message_id'],a['deny_frame_digest'])!=(r['prepare_id'],O.reference(r,'deny_id','request_digest'),request['message_id'],O.digest(request)):return 'reference'
    if not int(r['selected_tick_ns'])<=int(a['effective_tick_ns'])<=received:return 'time'
    if a['state']!='denied' or a['future_use_denied'] is not True:return 'denial'
    return None

class Prepares:
    """只模拟已由可信提供者投影的选择范围；不实现权限服务或完整发送门控。"""
    def __init__(self):self.rows={};self.denied={};self.effects=[];self.encoding=set();self.borrows=set()
    def register(self,row):
        pid=row['prepare_id']
        if pid in self.denied:return 'denied'
        if pid in self.rows:return 'duplicate' if self.rows[pid]==row else 'conflict'
        self.rows[pid]=clone(row);return 'registered'
    def deny(self,pid,request_digest,tick):
        if pid in self.denied:return clone(self.denied[pid]) if self.denied[pid]['request_digest']==request_digest else 'conflict'
        self.denied[pid]={'request_digest':request_digest,'effective_tick':tick};return clone(self.denied[pid])
    def send(self,pid):
        if pid in self.denied:return 'denied'
        if pid not in self.rows:return 'unknown'
        self.effects.append(pid);return 'in_flight'
    def releasable(self,pid):
        return pid in self.denied and pid not in self.encoding and not any(p==pid for p,_ in self.borrows)

def matches(r,s):
    if s.get('device_id') is not None and r['device_id']!=s['device_id']:return False
    kind=s['kind']
    if kind in ('control','close'):return True
    if kind=='cancel':return r['command_id']==s['command_id'] and (s['stage']=='all' or r['kind']=='ordinary')
    if kind=='run':return r['origin']=='automation' and r['run_key']==s['run_key']
    if kind=='time':return r['time_domain']==s['time_domain'] and r['time_generation'] is not None and r['time_generation']<s['minimum_generation']
    if kind=='auth':return any(k['identity']==s['identity'] and k['revision']<s['revision_floor'] for k in r['auth_keys'])
    raise ValueError('未知选择范围')

def capture(rows,selector):
    # 不按permit、prepared状态、活字节或当前设备session删减集合。
    assert len({r['prepare_id'] for r in rows})==len(rows),'准备身份重复'
    return sorted((clone(r) for r in rows if matches(r,selector)),key=lambda r:r['prepare_id'])

def closure_error(selected,members,proofs):
    expected={r['prepare_id']:r for r in selected}
    if len(members)!=len(expected) or {m['prepare_id'] for m in members}!=set(expected):return 'coverage'
    if [m['prepare_id'] for m in members]!=sorted(expected):return 'ordering'
    for m in members:
        r=expected[m['prepare_id']];p=proofs.get(m['proof_ref']['id'])
        if p is None or p['ref']!=m['proof_ref'] or p['basis']!=m['basis']:return 'proof'
        if p['prepare_id']!=r['prepare_id'] or p['writer_exit_id']!=r['writer_exit_id'] or m['writer_exit_id']!=r['writer_exit_id']:return 'exit'
        if m['encoding_authorization_ref']!=r['encoding_authorization_ref']:return 'authorization'
        if m['basis']=='never_attempted' and r['attempted']:return 'attempted'
        if not p['committed'] or not p['currently_valid']:return 'uncommitted_or_revoked'
    return None
