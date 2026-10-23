"""编码释放的关联与有限原子顺序模型，无真实IPC或资源提供者。"""
import copy
import open_plan_model as O
clone=copy.deepcopy
def rref(r):return O.reference(r,'release_id','request_digest')
def source_error(frame,c):
    r=frame['body']
    if not O.intact(r,'request_digest'):return 'digest'
    if frame!=c['stored_request'] or r['revocation_ref']!=c['revocation_ref']:return 'request_source'
    if r['binding']!=c['binding'] or any(frame[k]!=r['binding'][k] for k in O.FRAME_BINDING):return 'binding'
    if (r['prepare_id'],r['encoding_authorization_ref'],r['encode_message_id'],r['encode_frame_digest'])!=(
        c['prepare_id'],c['encoding_authorization_ref'],c['encode_message_id'],c['encode_frame_digest']):return 'prepare_source'
    if frame['type']!='RELEASE_ENCODING' or frame['reply_to'] is not None:return 'direction'
    return None

def ack_error(frame,request,c):
    error=source_error(request,c)
    if error:return error
    r=request['body'];a=frame['body']
    if frame!=c['stored_ack']:return 'ack_source'
    if a['binding']!=r['binding'] or any(frame[k]!=r['binding'][k] for k in O.FRAME_BINDING):return 'binding'
    if frame['type']!='RELEASE_ENCODING_ACK' or frame['reply_to']!=request['message_id']:return 'direction'
    if (a['release_ref'],a['prepare_id'],a['release_message_id'],a['release_frame_digest'])!=(rref(r),r['prepare_id'],request['message_id'],O.digest(request)):return 'ack_binding'
    if not int(r['selected_tick_ns'])<=int(a['disposed_tick_ns'])<=c['received_tick']:return 'ack_time'
    return None

class Worker:
    """模拟同一串行域里的borrow和墓碑；调用方必须先Schema与认证。"""
    def __init__(self,context,encoding=False):
        self.c=clone(context);self.encoding=encoding;self.consumers=set();self.used=set();self.bytes_live=True
        self.release=None;self.ack=None;self.closed=False;self.device_effects=[]
    def borrow(self,token):
        if self.closed:return 'session_closed'
        if self.release is not None:return 'prepare_closed'
        if token in self.used:return 'already_used'
        self.used.add(token);self.consumers.add(token);return 'borrowed'
    def device_io(self,token):
        if token not in self.consumers:return 'no_borrow'
        # 墓碑后已借用但尚未调用也不能再发；在先发生的调用记录不撤回。
        if self.closed or self.release is not None:return 'prepare_closed'
        if token in self.device_effects:return 'already_sent'
        self.device_effects.append(token);return 'in_flight'
    def return_borrow(self,token):
        if token not in self.consumers:return 'not_borrowed'
        self.consumers.remove(token);return 'returned'
    def encoding_done(self):
        if not self.encoding:return 'not_encoding'
        self.encoding=False
        return 'discarded' if self.release is not None else 'prepared'
    def request(self,frame):
        if self.closed:return 'session_closed'
        if self.release is not None:
            if self.release==frame:return 'cached_ack' if self.ack is not None else 'waiting'
            self.closed=True;return 'release_conflict'
        error=source_error(frame,self.c)
        if error:self.closed=True;return error
        self.release=clone(frame);return 'closing'
    def settle(self,now,message_id='release.ack',seq='3'):
        if self.closed:return 'session_closed'
        if self.ack is not None:return clone(self.ack)
        if self.release is None:return 'not_closing'
        if self.encoding or self.consumers:return 'waiting'
        r=self.release['body']
        if now<int(r['selected_tick_ns']):return 'clock_order'
        self.bytes_live=False
        body=dict(release_ref=rref(r),binding=clone(r['binding']),prepare_id=r['prepare_id'],
          release_message_id=self.release['message_id'],release_frame_digest=O.digest(self.release),disposed_tick_ns=str(now),
          state='released',encoder_quiescent=True,consumers_quiescent=True,cache_empty=True)
        self.ack=dict(**{k:r['binding'][k] for k in O.FRAME_BINDING},ipc_version=self.release['ipc_version'],
          type='RELEASE_ENCODING_ACK',message_id=message_id,reply_to=self.release['message_id'],seq=seq,body=body)
        return clone(self.ack)

class Ledger:
    """退款按原预留集合派生；合成原子副本不是SQLite或真实事务。"""
    def __init__(self,context,reservation,max_bytes=8,max_slots=2,metadata_slots=4):
        self.c=clone(context);self.reservations={context['prepare_id']:clone(reservation)};self.releases={};self.adoptions={}
        self.uncertain={}
        self.max_bytes=max_bytes;self.max_slots=max_slots;self.metadata_slots=metadata_slots
    def live(self):return {k:v for k,v in self.reservations.items() if k not in self.releases}
    def reserve(self,pid,reservation):
        if pid in self.reservations:return 'identity_used'
        if len(self.reservations)>=self.metadata_slots:return 'metadata_full'
        if len(self.live())>=self.max_slots or sum(v['bytes'] for v in self.live().values())+reservation['bytes']>self.max_bytes:return 'capacity'
        self.reservations[pid]=clone(reservation);return 'reserved'
    def adopt(self,v,ack,request,outcome='confirmed'):
        error=ack_error(ack,request,self.c)
        if error:return error
        pid=request['body']['prepare_id'];original=self.reservations.get(pid)
        if original is None:return 'reservation_missing'
        if not O.intact(v,'adoption_digest'):return 'adoption_digest'
        if (v['prepare_id'],v['binding'],v['release_ref'],v['ack_message_id'],v['ack_frame_digest'],v['encoding_reservation_ref'],v['reserved_bytes'])!=(
          pid,self.c['binding'],rref(request['body']),ack['message_id'],O.digest(ack),original['ref'],original['bytes']):return 'adoption_binding'
        if int(v['received_tick_ns'])!=self.c['received_tick'] or int(v['committed_tick_ns'])<int(v['received_tick_ns']):return 'adoption_time'
        if pid in self.releases:return 'query_original' if self.adoptions.get(pid)==v else 'already_released'
        if pid in self.uncertain:return 'commit_unknown'
        if outcome=='rollback':return 'rolled_back'
        if outcome=='unknown':self.uncertain[pid]=clone(v);return 'commit_unknown'
        if outcome!='confirmed':raise ValueError(outcome)
        self.releases[pid]='worker_released';self.adoptions[pid]=clone(v);return 'released'
    def query_resolution(self,pid,stored):
        if pid not in self.uncertain:return 'not_uncertain'
        if stored is None:return 'still_unknown'
        if stored!=self.uncertain[pid]:return 'stored_conflict'
        if pid not in self.releases:
            self.releases[pid]='worker_released';self.adoptions[pid]=clone(stored)
        del self.uncertain[pid];return 'history_resolved'
    def retire(self,pid,binding):
        # 只模拟可信监督提供者已证明同出口退役这一前提。
        if binding!=self.c['binding']:return 'wrong_exit'
        if pid!=self.c['prepare_id'] or pid not in self.reservations:return 'wrong_prepare'
        if pid in self.releases:return 'already_released'
        self.releases[pid]='supervisor_retired';return 'released'
