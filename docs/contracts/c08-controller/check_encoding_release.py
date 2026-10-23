"""编码释放契约和有限消费者实验；不运行网络、SQLite或设备。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
import build_encoding_release as G
import encoding_release_model as M
import check_encoding_authority as A
O=M.O;clone=copy.deepcopy;HERE=G.HERE;ROOT=HERE.parents[2]
LOCAL=('ENCODING_RELEASE.md','build_encoding_release.py','encoding_release_model.py','check_encoding_release.py',
 'encoding-release.schema.json','encoding-release-ipc.schema.json','ENCODING_STORAGE.md','encoding-storage.sql')

def frame(kind,body,binding,reply=None,mid='release.request',seq='2'):
    return dict(**{k:binding[k] for k in O.FRAME_BINDING},ipc_version=G.VERSION,type=kind,message_id=mid,reply_to=reply,seq=seq,body=body)

def fixture(frames,kind='ordinary'):
    a,encode,_,_=A.fixture(frames,kind);encode['ipc_version']=G.VERSION
    r=O.seal(dict(release_id='release.'+kind,revision='1',binding=clone(a['binding']),prepare_id=encode['body']['prepare_id'],
      encoding_authorization_ref=A.M.aref(a),encode_message_id=encode['message_id'],encode_frame_digest=O.digest(encode),
      revocation_ref=A.ref('revocation'),selected_tick_ns='50'),'request_digest')
    request=frame('RELEASE_ENCODING',r,a['binding'])
    c={k:clone(r[k]) for k in ('binding','prepare_id','encoding_authorization_ref','encode_message_id','encode_frame_digest','revocation_ref')}
    c['stored_request']=clone(request);c['received_tick']=52
    worker=M.Worker(c);assert worker.request(request)=='closing';ack=worker.settle(51);c['stored_ack']=clone(ack)
    reservation=dict(ref=clone(a['encoding_reservation_ref']),bytes=4)
    adoption=O.seal(dict(adoption_id='adoption.'+kind,revision='1',binding=clone(r['binding']),prepare_id=r['prepare_id'],
      release_ref=M.rref(r),ack_message_id=ack['message_id'],ack_frame_digest=O.digest(ack),
      encoding_reservation_ref=clone(reservation['ref']),reserved_bytes=4,received_tick_ns='52',committed_tick_ns='53'),'adoption_digest')
    return request,ack,adoption,c,reservation

def old_upgrades(frames):
    out=clone(frames)
    for kind in ('ordinary','cancel'):
        a,r,p,_=A.fixture(frames,kind);out[r['type']]=r;out[p['type']]=p
        for n in (('PACKET_ENCODING_FAILED','PREPARE_PACKET_REJECTED') if kind=='ordinary' else ('CANCEL_ENCODING_FAILED',)):
            out[n]['body']['encoding_authorization_ref']=A.M.aref(a)
    b=A.Q.fixture()[3]['binding'];r=dict(request_id='renew',binding=b,control_authority_ref=A.ref('control'),before_gate_ref=A.ref('gate'),
      close_ack_ref=A.ref('close'),target_gate_revision='2',gate_token='token',selected_tick_ns='10',expires_tick_ns='20',lease_until_tick_ns='30',request_digest=O.digest('renew'))
    ack=dict(request_id='renew',request_digest=r['request_digest'],binding=b,gate_revision='2',gate_token='token',effective_tick_ns='11',state='fenced')
    out['GATE_FENCE']=frame('GATE_FENCE',r,b,mid='renew')
    out['GATE_FENCE_ACK']=frame('GATE_FENCE_ACK',ack,b,reply='renew',mid='renew.ack')
    for n,f in out.items():
        f['ipc_version']=G.VERSION
        if n=='HELLO':f['body']['supported_ipc_versions']=[G.VERSION];f['body']['supported_features']+=['fresh_gate_fence',A.G.FEATURE,G.FEATURE]
        if n=='HELLO_ACK':f['body']['selected_ipc_version']=G.VERSION;f['body']['selected_features']+=['fresh_gate_fence',A.G.FEATURE,G.FEATURE]
    return out

def run(frames):
    checks=[]
    def check(n,a,e=True):
        assert a==e,(n,a,e);checks.append(dict(name=n,observed=clone(a),expected=clone(e)))
    builds=G.build();s=builds['encoding-release.schema.json'];ipc=builds['encoding-release-ipc.schema.json'];iv=Draft202012Validator(ipc)
    valid=lambda n,v:Draft202012Validator({'$defs':s['$defs'],'$ref':'#/$defs/'+n}).is_valid(v)
    for n,v in builds.items():Draft202012Validator.check_schema(v);check('生成:'+n,(HERE/n).read_bytes()==G.S.encoded(v))
    old=old_upgrades(frames);check('保留全部旧帧',len(old),48)
    for n,f in old.items():
        check('旧帧新版本结构:'+n,iv.is_valid(f));bad=clone(f);bad['ipc_version']=A.G.VERSION;check('拒旧版本:'+n,iv.is_valid(bad),False)
    for n,k in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        bad=clone(old[n]);bad['body'][k].remove(G.FEATURE);check('必选释放协商:'+n,iv.is_valid(bad),False)
    check('完整帧数',len(ipc['oneOf']),50);check('采用不导出IPC','ER__ReleaseAdoption' in ipc['$defs'],False)
    types=[ipc['$defs'][b['$ref'].split('/')[-1]]['properties']['type']['const'] for b in ipc['oneOf']]
    check('完整消息集合无替换',sorted(types),sorted(list(old)+['RELEASE_ENCODING','RELEASE_ENCODING_ACK']))
    for kind in ('ordinary','cancel'):
        request,ack,v,c,reservation=fixture(frames,kind);pid=c['prepare_id'];r=request['body']
        for n,value in [('ReleaseRequest',r),('ReleaseAck',ack['body']),('ReleaseAdoption',v)]:
            check(kind+n+'正例',valid(n,value));check(kind+n+'根拒绝',Draft202012Validator(s).is_valid(value),False)
            for k in value:
                bad=clone(value);del bad[k];check(kind+n+'缺:'+k,valid(n,bad),False)
            bad=clone(value);bad['extra']=True;check(kind+n+'额外字段',valid(n,bad),False)
        for f in (request,ack):
            check(kind+f['type']+'帧',iv.is_valid(f))
            for seq in ('0','01','1\n',str(10**20),1):
                bad=clone(f);bad['seq']=seq;check(kind+f['type']+'非法seq:'+repr(seq),iv.is_valid(bad),False)
        for k in ('encoder_quiescent','consumers_quiescent','cache_empty'):
            bad=clone(ack['body']);bad[k]=False;check(kind+'未清空不可ACK:'+k,valid('ReleaseAck',bad),False)
        check(kind+'原请求关联',M.source_error(request,c),None)
        check(kind+'原ACK关联',M.ack_error(ack,request,c),None)
        for k,value in [('prepare_id','other'),('encoding_authorization_ref',A.ref('other')),('encode_message_id','other'),('encode_frame_digest',O.digest('other'))]:
            bad=clone(request);bad['body'][k]=value;O.seal(bad['body'],'request_digest');cc=clone(c);cc['stored_request']=clone(bad)
            check(kind+'重算请求仍错来源:'+k,M.source_error(bad,cc),'prepare_source')
        bad=clone(request);bad['body']['revocation_ref']=A.ref('other');O.seal(bad['body'],'request_digest')
        cc=clone(c);cc['stored_request']=clone(bad);check(kind+'撤回原件错配',M.source_error(bad,cc),'request_source')
        bad=clone(request);bad['body']['binding']['device_session_id']='other';O.seal(bad['body'],'request_digest')
        cc=clone(c);cc['stored_request']=clone(bad);check(kind+'请求跨设备会话',M.source_error(bad,cc),'binding')
        for k,value in [('release_ref',A.ref('other')),('prepare_id','other'),('release_message_id','other'),('release_frame_digest',O.digest('other'))]:
            bad=clone(ack);bad['body'][k]=value;cc=clone(c);cc['stored_ack']=clone(bad)
            check(kind+'ACK错配:'+k,M.ack_error(bad,request,cc),'ack_binding')
        for tick in ('49','53'):
            bad=clone(ack);bad['body']['disposed_tick_ns']=tick;cc=clone(c);cc['stored_ack']=clone(bad)
            check(kind+'ACK时间:'+tick,M.ack_error(bad,request,cc),'ack_time')
        bad=clone(ack);bad['reply_to']='other';cc=clone(c);cc['stored_ack']=clone(bad)
        check(kind+'ACK错误reply',M.ack_error(bad,request,cc),'direction')
        bad=clone(ack);bad['body']['binding']['worker_boot_id']='other';cc=clone(c);cc['stored_ack']=clone(bad)
        check(kind+'ACK跨进程',M.ack_error(bad,request,cc),'binding')
        worker=M.Worker(c,encoding=True)
        check(kind+'消费者一借用',worker.borrow('transport'),'borrowed');check(kind+'消费者二借用',worker.borrow('retry'),'borrowed')
        check(kind+'释放前已入流',worker.device_io('transport'),'in_flight')
        check(kind+'释放安装墓碑',worker.request(request),'closing');check(kind+'晚借用拒绝',worker.borrow('late'),'prepare_closed')
        check(kind+'等待时重投仍等待',worker.request(request),'waiting')
        check(kind+'已借未发也阻止',worker.device_io('retry'),'prepare_closed');check(kind+'编码和双借用未清',worker.settle(51),'waiting')
        check(kind+'编码完成丢弃',worker.encoding_done(),'discarded');check(kind+'仍有消费者',worker.settle(51),'waiting')
        check(kind+'归还首消费者',worker.return_borrow('transport'),'returned');check(kind+'第二消费者仍阻ACK',worker.settle(51),'waiting')
        check(kind+'归还末消费者',worker.return_borrow('retry'),'returned');check(kind+'全部清空原ACK',worker.settle(51),ack)
        check(kind+'活字节已清',worker.bytes_live,False);check(kind+'在途设备效果仍保留',worker.device_effects,['transport'])
        check(kind+'重复释放只查',worker.request(request),'cached_ack');check(kind+'重复ACK不改tick',worker.settle(100),ack)
        check(kind+'释放后永久拒借用',worker.borrow('after'),'prepare_closed')
        conflict=clone(request);conflict['message_id']='other';check(kind+'换释放原帧冲突',worker.request(conflict),'release_conflict')
        check(kind+'冲突关闭通道',worker.closed)
        worker=M.Worker(c);check(kind+'无释放不能清空',worker.settle(51),'not_closing')
        check(kind+'墓碑先到',worker.request(request),'closing');check(kind+'后到设备调用无借用',worker.device_io('none'),'no_borrow')
        check(kind+'过去tick拒绝',worker.settle(49),'clock_order');check(kind+'截止后仍能清理',isinstance(worker.settle(100),dict))
        lost=clone(c);lost['stored_request']=None;worker=M.Worker(lost)
        check(kind+'原缓存丢失不能清理证明',worker.request(request),'request_source')
        check(kind+'缓存丢失后不造ACK',worker.settle(100),'session_closed')
        # 采用前缺失可信原件不能退款；完整布尔字段不能自己获得权威。
        cc=clone(c);cc['stored_ack']=None;ledger=M.Ledger(cc,reservation)
        check(kind+'无可信ACK拒退款',ledger.adopt(v,ack,request),'ack_source');check(kind+'无ACK保留额度',len(ledger.live()),1)
        ledger=M.Ledger(c,reservation,max_bytes=4,max_slots=1)
        check(kind+'先满额度',ledger.reserve('next',reservation),'capacity')
        before=clone(ledger.__dict__);check(kind+'采用回滚',ledger.adopt(v,ack,request,'rollback'),'rolled_back')
        check(kind+'回滚全状态不变',ledger.__dict__==before)
        check(kind+'采用未知',ledger.adopt(v,ack,request,'unknown'),'commit_unknown')
        check(kind+'未知仍保留额度',len(ledger.live()),1);check(kind+'未知不可重新提交',ledger.adopt(v,ack,request),'commit_unknown')
        check(kind+'not_found不证明已退款',ledger.query_resolution(pid,None),'still_unknown')
        wrong=clone(v);wrong['adoption_id']='other';O.seal(wrong,'adoption_digest')
        check(kind+'查原错记录不解未知',ledger.query_resolution(pid,wrong),'stored_conflict')
        check(kind+'错记录仍保留额度',len(ledger.live()),1)
        check(kind+'查原恢复既有提交',ledger.query_resolution(pid,v),'history_resolved');check(kind+'已退款活集合为空',len(ledger.live()),0)
        check(kind+'原ID不能复用',ledger.reserve(pid,reservation),'identity_used');check(kind+'正常会话复用额度',ledger.reserve('next',reservation),'reserved')
        check(kind+'重复采用仅历史',ledger.adopt(v,ack,request),'query_original');check(kind+'旧ACK不退款新准备',list(ledger.live()),['next'])
        check(kind+'ACK后退役不二次退款',ledger.retire(pid,c['binding']),'already_released')
        ledger=M.Ledger(c,reservation);check(kind+'正常确认采用',ledger.adopt(v,ack,request),'released')
        ledger=M.Ledger(c,reservation);check(kind+'退役先到',ledger.retire(pid,c['binding']),'released')
        check(kind+'退役后迟到ACK',ledger.adopt(v,ack,request),'already_released')
        for k,value in [('prepare_id','next'),('reserved_bytes',3),('encoding_reservation_ref',A.ref('other')),('ack_frame_digest',O.digest('other'))]:
            bad=clone(v);bad[k]=value;O.seal(bad,'adoption_digest');ledger=M.Ledger(c,reservation)
            check(kind+'重算采用仍错绑定:'+k,ledger.adopt(bad,ack,request),'adoption_binding')
        ledger=M.Ledger(c,reservation,metadata_slots=1);check(kind+'元数据释放前登记',ledger.adopt(v,ack,request),'released')
        check(kind+'活字节退款不扩元数据',ledger.reserve('next',reservation),'metadata_full')
        check(kind+'可信上下文全为合成的限制',M.ack_error(ack,request,c),None)
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    raw,inherited=A.Q.old_frames();frames={f['type']:f for f in A.Q.upgrade_frames(raw)}
    inputs=list(dict.fromkeys(A.Q.input_paths(inherited)+[HERE/n for n in A.LOCAL+LOCAL]))
    target=HERE/'encoding-release-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in inputs}
        for f in inputs:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(inputs))))
    else:
        checks=run(frames);data=dict(all_passed=True,approved=False,cases_passed=len(checks),ipc_messages=50,
          scope='释放原件关联和有限消费者及退款集合模型，不运行SQLite或真实服务',runtime_tests_executed=0,sqlite_tests_executed=0,
          concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,
          inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs})
        if a.report:target.write_bytes(G.S.encoded(data))
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
