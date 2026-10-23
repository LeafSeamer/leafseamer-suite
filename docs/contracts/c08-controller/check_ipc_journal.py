"""共享日志/紧急关闭/准备覆盖的合成检查；不执行SQLite或真实服务。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
import build_ipc_journal as G
import ipc_journal_model as M
import check_encoding_release as R
O=M.O;HERE=G.HERE;ROOT=HERE.parents[2];clone=copy.deepcopy
LOCAL=('IPC_JOURNAL.md','build_ipc_journal.py','ipc_journal_model.py','check_ipc_journal.py',
 'ipc-journal.schema.json','journal-ipc.schema.json','ipc-journal-messages.json','GATE_ORDER.md',
 'ENCODING_RELEASE_STORAGE.md','encoding-release-storage.sql')

def fixtures():
    raw,inherited=R.A.Q.old_frames();frames={f['type']:f for f in R.A.Q.upgrade_frames(raw)}
    out=R.old_upgrades(frames);request,ack,_,context,_=R.fixture(frames)
    out.update(RELEASE_ENCODING=request,RELEASE_ENCODING_ACK=ack)
    for f in out.values():
        f.update(ipc_version=G.VERSION,journal_mode='durable')
        if f['type']=='HELLO':f['body']['supported_ipc_versions']=[G.VERSION];f['body']['supported_features']+=G.FEATURES
        if f['type']=='HELLO_ACK':f['body']['selected_ipc_version']=G.VERSION;f['body']['selected_features']+=G.FEATURES
    request=clone(request);r=request['body'];r['deny_id']=r.pop('release_id');O.seal(r,'request_digest')
    request.update(type='DENY_ENCODING',message_id='deny.request')
    ack=clone(ack);ack.update(type='DENY_ENCODING_ACK',message_id='deny.ack',reply_to=request['message_id'])
    ack['body']=dict(deny_ref=O.reference(r,'deny_id','request_digest'),binding=clone(r['binding']),prepare_id=r['prepare_id'],
      deny_message_id=request['message_id'],deny_frame_digest=O.digest(request),effective_tick_ns='51',state='denied',future_use_denied=True)
    out.update(DENY_ENCODING=request,DENY_ENCODING_ACK=ack)
    context['stored_deny_request']=clone(request)
    inputs=list(dict.fromkeys(R.A.Q.input_paths(inherited)+[HERE/n for n in R.A.LOCAL+R.LOCAL+LOCAL]))
    return out,context,inputs

def run(frames,context):
    checks=[]
    def check(n,a,e=True):
        assert a==e,(n,a,e);checks.append(dict(name=n,observed=clone(a),expected=clone(e)))
    builds=G.build();s=builds['journal-ipc.schema.json'];iv=Draft202012Validator(s)
    for n,v in builds.items():
        if n.endswith('schema.json'):Draft202012Validator.check_schema(v)
        check('生成:'+n,(HERE/n).read_bytes()==G.S.encoded(v))
    check('完整类型数',len(frames),52);check('无方向交集',set(G.C2W)&set(G.W2C),set())
    # 独立预期纠正最容易猜错的方向和独立通知。
    for name,direction in [('HELLO','w2c'),('HELLO_ACK','c2w'),('PREPARE_PACKET','w2c'),
      ('PREPARE_PACKET_REJECTED','c2w'),('CANCEL_PREPARE_REJECTED','c2w'),('DISPATCH_CANCEL','c2w')]:
        check('人工方向:'+name,next(m['direction'] for m in builds['ipc-journal-messages.json']['messages'] if m['type']==name),direction)
    for n,f in frames.items():
        check('结构:'+n,iv.is_valid(f))
        bad=clone(f);bad['ipc_version']=R.G.VERSION;check('拒旧版:'+n,iv.is_valid(bad),False)
        for seq in ('0','01','1\n','100000000000000000000',1):
            bad=clone(f);bad['seq']=seq;check('拒序号:'+n+':'+repr(seq),iv.is_valid(bad),False)
        bad=clone(f);bad['seq']='99999999999999999999';check('最大U20:'+n,iv.is_valid(bad))
        bad=clone(f);del bad['journal_mode'];check('必填模式:'+n,iv.is_valid(bad),False)
        bad=clone(f);bad['reply_to']=None if n in G.REPLIES else 'unexpected'
        check('响应形状与清单一致:'+n,iv.is_valid(bad),False)
        if n not in ('CLOSE_GATE','CLOSE_GATE_ACK'):
            bad=clone(f);bad.update(journal_mode='volatile_close',seq=None);check('拒非法紧急类型:'+n,iv.is_valid(bad),False)
    for kind,key in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        for feature in G.FEATURES:
            bad=clone(frames[kind]);bad['body'][key].remove(feature);check('必选特性:'+kind+feature,iv.is_valid(bad),False)
    binding={k:frames['HELLO'][k] for k in M.SESSION_KEYS};devices=['device-a','device-b']
    def make(kind,mid='message',seq=1,reply=None,device='device-a',mode='durable'):
        f=clone(frames[kind]);f.update(binding);f.update(message_id=mid,seq=str(seq) if seq is not None else None,
          reply_to=reply,device_id=device,journal_mode=mode);return f
    def accept(j,f,direction='c2w',**kw):return j.accept(f,direction,G.S.encoded(f),**kw)
    hello=make('HELLO','hello',device=None);ha=make('HELLO_ACK','hello.ack',reply='hello',device=None)
    def started(**kwargs):
        j=M.Journal(binding,devices,**kwargs);assert accept(j,hello,'w2c')=='applied';assert accept(j,ha)=='applied';return j
    j=M.Journal(binding,devices);check('C首帧不能OPEN',accept(j,make('OPEN_GATE')),'handshake_order')
    j=M.Journal(binding,devices);check('W首帧不能报告',accept(j,make('SEND_REPORT'),'w2c'),'handshake_order')
    j=M.Journal(binding,devices);accept(j,hello,'w2c')
    check('握手未齐不能报告',accept(j,make('SEND_REPORT',seq=2),'w2c'),'handshake_incomplete')
    for n in frames:
        j=started();direction='w2c' if n in G.C2W else 'c2w'
        check('拒反向发送:'+n,accept(j,make(n,mid='wrong-direction',seq=2),direction),'direction')
    j=started();check('两个方向独立水位',j.head,dict(c2w=1,w2c=1))
    request=make('CLOSE_GATE','close',2);request['body'].update(close_id='close',scope='device')
    ack=make('CLOSE_GATE_ACK','close.ack',2,'close',None);ack['body'].update(close_id='close',closed_device_ids=['device-a'])
    check('正常关闭',accept(j,request),'applied');check('正常ACK',accept(j,ack,'w2c'),'applied')
    before=clone(j.effects);check('重复原帧',accept(j,request),'duplicate');check('重复不重复效果',j.effects,before)
    bad=clone(request);bad['body']['reason']='changed';check('同ID异内容',accept(j,bad),'message_conflict')
    j=started();accept(j,request);bad=clone(request);bad['message_id']='different';check('同seq异ID',accept(j,bad),'sequence_conflict')
    j=started();bad=clone(request);bad['seq']='3';check('缺号',accept(j,bad),'sequence_gap')
    j=started();bad=clone(request);bad['device_id']='unknown';check('未登记设备',accept(j,bad),'device')
    j=started();check('方向错误',accept(j,request,'w2c'),'direction')
    for key in M.SESSION_KEYS:
        j=started();bad=clone(request);bad[key]='other';check('会话错配:'+key,accept(j,bad),'session_binding')
    j=started();accept(j,request);wire=G.S.encoded(request)+b' '
    check('同JSON不同原wire',j.accept(request,'c2w',wire),'message_conflict')
    j=started();check('无原请求ACK',accept(j,ack,'w2c'),'reply_type')
    j=started();req=make('QUERY_CANCEL_EXECUTION','q',2);accept(j,req)
    wrong=make('OPEN_GATE_ACK','wrong',2,'q');check('跨请求类型ACK',accept(j,wrong,'w2c'),'reply_type')
    j=started();f=make('SEND_REPORT','report',2,device='device-a');check('独立报告',accept(j,f,'w2c'),'applied')
    f=make('SEND_REPORT','report-b',3,device='device-b');check('多设备共享水位',accept(j,f,'w2c'),'applied')
    check('跨设备水位未拆开',j.head['w2c'],3)
    for fault in ('after_record','before_commit'):
        j=started();before=clone((j.head,j.rows,j.slots,j.effects));check('故障:'+fault,accept(j,request,fault=fault),'rolled_back')
        check('原子副本回滚:'+fault,(j.head,j.rows,j.slots,j.effects)==before)
        check('完整未提交原帧可重新摄取:'+fault,accept(j,request),'applied')
    j=started();check('提交响应未知',accept(j,request,fault='commit_unknown'),'lookup_only')
    check('未知只读原',accept(j,request),'duplicate');check('未知不新执行',accept(j,make('CLOSE_GATE','next',3)),'terminal_session')
    j=started(limit=2,reserved=1);check('普通容量满',accept(j,request),'capacity')
    check('受信保护保留槽',accept(j,request,protected=True),'applied')
    check('保护槽也有界',accept(j,make('CLOSE_GATE','next',3),protected=True),'capacity')
    # 紧急关闭允许正常预约缺口，但不推进正常水位，之后不可重新开放。
    emergency=make('CLOSE_GATE','emergency',None,device=None,mode='volatile_close')
    emergency['body'].update(close_id='emergency.close',scope='controller')
    ea=make('CLOSE_GATE_ACK','emergency.ack',None,'emergency',None,'volatile_close')
    ea['body'].update(close_id='emergency.close',closed_device_ids=devices)
    check('紧急请求Schema',iv.is_valid(emergency));check('紧急ACKSchema',iv.is_valid(ea))
    for k,v in [('seq','2'),('device_id','device-a')]:
        bad=clone(emergency);bad[k]=v;check('紧急拒错误:'+k,iv.is_valid(bad),False)
    bad=clone(emergency);bad['body']['scope']='device';check('紧急必须全worker',iv.is_valid(bad),False)
    j=started(limit=2,reserved=0);before=clone((j.head,j.rows,j.effects))
    check('DB不可写不需要持久槽',accept(j,emergency),'volatile_closed')
    check('紧急不伪造日志提交',(j.head,j.rows,j.effects)==before)
    check('紧急完整ACK',accept(j,ea,'w2c'),'volatile_ack');check('紧急重复',accept(j,emergency),'duplicate')
    check('数据库恢复也不OPEN',accept(j,make('OPEN_GATE','new.open',2)),'terminal_session')
    j=started();accept(j,emergency);bad=clone(ea);bad['body']['closed_device_ids']=['device-a']
    check('紧急ACK不能截断设备',accept(j,bad,'w2c'),'volatile_coverage')
    j=started();check('紧急ACK必须原请求',accept(j,ea,'w2c'),'volatile_reply')
    # 查询屏障的新封装可以承载旧正文；释放/拒绝的原帧保持精确身份。
    j=started();fence=make('FENCE','fence',2);accept(j,fence)
    fa=make('FENCE_ACK','fence.ack',2,'fence');accept(j,fa,'w2c')
    query=make('QUERY_BARRIER','query',3);check('查询新序号',accept(j,query),'applied')
    answer=clone(fa);answer.update(message_id='query.ack',reply_to='query',seq='3')
    check('查询新封装原正文',accept(j,answer,'w2c'),'applied');check('正文保持',answer['body']==fa['body'])
    check('完整帧摘要不同',O.digest(answer)!=O.digest(fa))
    for typ,res in [('RELEASE_ENCODING','RELEASE_ENCODING_ACK'),('DENY_ENCODING','DENY_ENCODING_ACK')]:
        j=started();rq=make(typ,'rq',2);ac=make(res,'ac',2,'rq');accept(j,rq);accept(j,ac,'w2c')
        before=clone(j.effects);check(typ+'原帧重复',accept(j,rq),'duplicate');check(res+'原帧重复',accept(j,ac,'w2c'),'duplicate')
        check(typ+'不再产生效果',j.effects,before)
    rq=frames['DENY_ENCODING'];ac=frames['DENY_ENCODING_ACK']
    check('拒绝精确绑定',M.deny_error(rq,ac,context,52),None)
    bad=clone(rq);bad['body']['selected_tick_ns']='49';O.seal(bad['body'],'request_digest')
    check('重算不得替换持久原请求',M.deny_error(bad,ac,context,52),'request_source')
    for field in ('prepare_id','encode_message_id','encode_frame_digest'):
        bad=clone(rq);bad['body'][field]='other';O.seal(bad['body'],'request_digest')
        check('重算仍错来源:'+field,M.deny_error(bad,ac,context,52),'source')
    bad=clone(ac);bad['body']['effective_tick_ns']='53';check('未来ACK',M.deny_error(rq,bad,context,52),'time')
    bad=clone(ac);bad['reply_to']='other';check('错原请求',M.deny_error(rq,bad,context,52),'reply')
    for ordering in ('deny_first','send_first'):
        p=M.Prepares();p.register({'prepare_id':'p'});p.encoding.add('p');p.borrows.add(('p','consumer'))
        if ordering=='send_first':check('先进入设备',p.send('p'),'in_flight')
        first=p.deny('p','digest',10);check(ordering+'拒绝立即生效',first['effective_tick'],10)
        check(ordering+'已借未发也拒绝',p.send('p'),'denied');check(ordering+'拒绝不等清空',p.releasable('p'),False)
        p.encoding.remove('p');check(ordering+'仍有消费者',p.releasable('p'),False)
        p.borrows.clear();check(ordering+'全部退出才可释放',p.releasable('p'))
        check(ordering+'重复不刷新tick',p.deny('p','digest',99),first)
        check(ordering+'冲突不换墓碑',p.deny('p','changed',99),'conflict')
        check(ordering+'保留已发生效果',p.effects,['p'] if ordering=='send_first' else [])
    p=M.Prepares();p.deny('unseen','digest',10);check('拒绝先于ENCODE',p.register({'prepare_id':'unseen'}),'denied')
    rows=[]
    for pid,device,kind,origin,run,tg,exit_id,attempted in [
      ('a','device-a','ordinary','automation','run-a',1,'exit-old',True),
      ('b','device-a','cancel','manual',None,None,'exit-new',True),
      ('c','device-a','ordinary','manual',None,2,'exit-new',False),
      ('d','device-b','ordinary','automation','run-a',1,'exit-b',True)]:
        rows.append(dict(prepare_id=pid,device_id=device,kind=kind,origin=origin,run_key=run,time_domain='clock-a',
          time_generation=tg,writer_exit_id=exit_id,command_id='command',attempted=attempted,
          encoding_authorization_ref=R.A.ref('auth-'+pid),auth_keys=[{'identity':'issuer/epoch/credential/one','revision':1 if pid=='a' else 2}]))
    cases=[({'kind':'control','device_id':'device-a'},['a','b','c']),({'kind':'close','device_id':None},['a','b','c','d']),
      ({'kind':'cancel','device_id':'device-a','command_id':'command','stage':'ordinary'},['a','c']),
      ({'kind':'cancel','device_id':'device-a','command_id':'command','stage':'all'},['a','b','c']),
      ({'kind':'run','device_id':'device-a','run_key':'run-a'},['a']),
      ({'kind':'time','device_id':'device-a','time_domain':'clock-a','minimum_generation':2},['a']),
      ({'kind':'auth','device_id':'device-a','identity':'issuer/epoch/credential/one','revision_floor':2},['a']),
      ({'kind':'auth','device_id':'device-a','identity':'issuer/other/credential/one','revision_floor':9},[])]
    for i,(selector,expected) in enumerate(cases):check('完整选择:'+str(i),[r['prepare_id'] for r in M.capture(rows,selector)],expected)
    members=[];proofs={}
    for r,basis in zip(rows,['deny_ack','released','never_attempted','retired']):
        rid='proof-'+r['prepare_id'];pr=R.A.ref(rid)
        members.append(dict(prepare_id=r['prepare_id'],encoding_authorization_ref=r['encoding_authorization_ref'],writer_exit_id=r['writer_exit_id'],basis=basis,proof_ref=pr))
        proofs[rid]=dict(ref=pr,basis=basis,prepare_id=r['prepare_id'],writer_exit_id=r['writer_exit_id'],committed=True,currently_valid=True)
    check('四种关闭依据',M.closure_error(rows,members,proofs),None)
    check('缺一个纯编码准备',M.closure_error(rows,members[1:],proofs),'coverage')
    check('重复成员',M.closure_error(rows,members+[members[0]],proofs),'coverage')
    check('成员顺序固定',M.closure_error(rows,list(reversed(members)),proofs),'ordering')
    for field,value,expected in [('writer_exit_id','new-exit','exit'),('encoding_authorization_ref',R.A.ref('other'),'authorization')]:
        bad=clone(members);bad[0][field]=value;check('闭合错配:'+field,M.closure_error(rows,bad,proofs),expected)
    for field in ('committed','currently_valid'):
        bad=clone(proofs);bad['proof-a'][field]=False;check('证明失效:'+field,M.closure_error(rows,members,bad),'uncommitted_or_revoked')
    bad=clone(members);pr=clone(proofs);bad[0]['basis']=pr['proof-a']['basis']='never_attempted'
    check('已尝试不能伪装未尝试',M.closure_error(rows,bad,pr),'attempted')
    # 局部持久对象不外发；这里验证结构，不冒充SQL写集。
    ds=builds['ipc-journal.schema.json']['$defs']
    closure=dict(closure_id='closure',revision='1',scope=context['binding']['scope'],operation_ref=R.A.ref('operation'),
      selector_ref=R.A.ref('selector'),registry_ref=R.A.ref('registry'),prepare_head='4',members=members,closure_digest=O.digest(members))
    cv=Draft202012Validator({'$defs':ds,'$ref':'#/$defs/PreparationClosure'})
    check('内部完整Closure结构',cv.is_valid(closure));bad=clone(closure);bad['members'][0]['basis']='timeout'
    check('超时不是关闭证明',cv.is_valid(bad),False)
    record=dict(record_id='record',session_ref=R.A.ref('session'),direction='c2w',sequence='1',message_id='id',
      message_type='HELLO_ACK',frame_digest=O.digest('frame'),wire_digest=O.digest('wire'),wire_length=20,
      frame_object_ref=R.A.ref('frame'),wire_object_ref=R.A.ref('wire'),record_digest=O.digest('record'))
    commit=dict(record_ref=R.A.ref('record'),disposition='historical',domain_commit_refs=[R.A.ref('history')],
      audit_ref=R.A.ref('audit'),reply_record_refs=[],committed_tick_ns='1')
    for n,v in [('FrameRecord',record),('EffectCommit',commit)]:
        validator=Draft202012Validator({'$defs':ds,'$ref':'#/$defs/'+n});check('持久对象结构:'+n,validator.is_valid(v))
        for key in list(v):
            bad=clone(v);del bad[key];check('持久对象必填:'+n+key,validator.is_valid(bad),False)
    bad=clone(commit);bad['domain_commit_refs']=[]
    check('不可只有Inbox而无领域提交',Draft202012Validator({'$defs':ds,'$ref':'#/$defs/EffectCommit'}).is_valid(bad),False)
    check('真实来源仍是合成前提',M.closure_error(rows,members,proofs),None)
    # 报告使用可JSON化记录；集合比较只保存结果，不序列化set。
    for c in checks:
        if isinstance(c['observed'],set):c['observed']=sorted(c['observed']);c['expected']=sorted(c['expected'])
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    frames,context,inputs=fixtures();target=HERE/'ipc-journal-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in inputs}
        for f in inputs:assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(inputs))))
    else:
        checks=run(frames,context);data=dict(all_passed=True,approved=False,cases_passed=len(checks),ipc_messages=52,
          scope='完整消息结构和有限日志/准备覆盖模型，领域权威为合成前提',sqlite_tests_executed=0,
          runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs})
        if a.report:target.write_bytes(G.S.encoded(data))
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
