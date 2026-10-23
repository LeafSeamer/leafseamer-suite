"""编码授权候选的结构、原件关联和有限顺序实验；不运行真实服务。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
import build_encoding_authority as G
import encoding_authority_model as M
import check_scoped_gate as Q
O=M.O;HERE=G.HERE;ROOT=HERE.parents[2];clone=copy.deepcopy
LOCAL=('ENCODING_AUTHORITY.md','build_encoding_authority.py','encoding_authority_model.py','check_encoding_authority.py',
       'encoding-authority.schema.json','encoding-authority-ipc.schema.json','gate-renewal-ipc.schema.json',
       'FINAL_ADMISSION.md','BARRIER_ATTEMPTS.md')

def ref(n):return dict(id=n,revision='1',digest=O.digest(n))

def fixture(frames,kind='ordinary'):
    ordinary=kind=='ordinary'
    req=clone(frames['ENCODE_PACKET' if ordinary else 'ENCODE_CANCEL_PACKET'])
    res=clone(frames['PREPARE_PACKET' if ordinary else 'PREPARE_CANCEL_PACKET'])
    b=req['body'];p=res['body']['packet']
    # 改为合成自洽原件，不沿用旧跨帧占位身份作为权威。
    binding=Q.fixture()[3]['binding']
    binding['device_session_id']='device-session'
    binding['controller_boot_id']='controller-boot';binding['worker_boot_id']='worker-boot'
    for f in (req,res):
        f['ipc_version']=G.VERSION
        for k in O.FRAME_BINDING:f[k]=binding[k]
    req['message_id']='encode.request';res['message_id']='encode.response';res['reply_to']=req['message_id']
    res['body']['prepare_id']=b['prepare_id']='prepare-'+kind
    target=dict(kind=kind,command_ref=ref('command'),proposed_attempt_id='attempt' if ordinary else None,
        cancellation_ref=None if ordinary else ref('cancel'),execution_ref=None if ordinary else ref('execution'))
    a=dict(format_version='encoding-authorization/0.1.0-draft.1',authorization_id='encoding.'+kind,revision='1',
        binding=binding,target=target,requester=dict(kind='human',issuer_id='issuer',issuer_epoch='epoch',principal_id='bob'),
        admission_source_ref=ref('admission.'+kind),authorization_snapshot_ref=ref('auth'),capability_ref=ref('capability'),
        primitive_id='primitive',primitive_plan_ref=ref('primitive-plan'),transport_profile_ref=ref('transport-profile'),
        content_digest=O.digest(b['request']) if ordinary else target['execution_ref']['digest'],encoding_reservation_ref=ref('encode.reservation'),
        max_bytes=65536,created_tick_ns='10',expires_tick_ns='40')
    O.seal(a,'authorization_digest');b.update(primitive_id='primitive',expires_tick_ns='40',encoding_authorization=clone(a))
    if ordinary:
        del b['guard_id'];del b['guard_digest']
        b.update(command_id='command',attempt_id='attempt',device_session_id=binding['device_session_id'],
          primitive_plan_ref=M.content_ref(a['primitive_plan_ref']),transport_profile_ref=M.content_ref(a['transport_profile_ref']))
        p.update(command_id='command',attempt_id='attempt',writer_exit_id=binding['writer_exit_id'],device_session_id=binding['device_session_id'],
          primitive_plan_ref=b['primitive_plan_ref'],transport_profile_ref=b['transport_profile_ref'])
    else:
        del b['guard_ref'];b['execution_ref']=clone(target['execution_ref'])
        p.update(execution_ref=target['execution_ref'],cancellation_id='cancel',parent_command_id='command',transport_profile_ref=a['transport_profile_ref'])
        p['exit']={k:binding[k] for k in binding if k!='scope'};p['exit']['socket_instance_id']='socket'
    if ordinary:p['socket_instance_id']='socket'
    p.update(primitive_id='primitive',protocol_session='protocol',byte_length=2,sha256=M.raw_digest(b'\x01\x02'))
    p['immutable_bytes_ref']['digest']=p['sha256'];O.seal(p,'packet_digest')
    res['body'].update(bytes_hex='0102',encoding_authorization_ref=M.aref(a))
    c={k:clone(a[k]) for k in ('binding','target','requester','admission_source_ref','authorization_snapshot_ref',
      'capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref')}
    c.update(authorizations={a['authorization_id']:clone(a)},revoked_refs=[],stored_request=clone(req),stored_response=clone(res),
      request_tick=11,received_tick=12,socket_instance_id='socket',protocol_session='protocol')
    return a,req,res,c

def finalization(e):
    return dict(permit_id='permit',issued_revision='1',binding=clone(e['binding']),encoding_evidence_ref=M.eref(e),
      admission_seal_ref=ref('seal'),guard_ref=ref('guard'),gate_access_ref=ref('access'),ownership_ref=ref('owner'),
      budget_charge_ref=ref('charge'),control_authority_ref=ref('control'),authorization_ref=ref('auth'),
      resource_safety_ref=ref('resource.safety'),gate_safety_ref=ref('gate.safety'),packet_ref=clone(e['packet_ref']),
      committed_tick_ns='15',send_not_before_tick_ns='16',send_before_tick_ns='30')

def current(v):return dict(binding=clone(v['binding']),**{k:clone(v[k]) for k in M.Order.CURRENT},pending_control=False,hard_protection=False)

def run(frames):
    checks=[]
    def check(n,actual,expected):
        assert actual==expected,(n,actual,expected)
        checks.append(dict(name=n,observed=clone(actual),expected=clone(expected)))
    builds=G.build();s=builds['encoding-authority.schema.json'];ipc=builds['encoding-authority-ipc.schema.json'];iv=Draft202012Validator(ipc)
    for name,value in builds.items():
        Draft202012Validator.check_schema(value);check('生成:'+name,(HERE/name).read_bytes()==G.S.encoded(value),True)
    valid=lambda name,v:Draft202012Validator({'$defs':s['$defs'],'$ref':'#/$defs/'+name}).is_valid(v)
    def evaluate(x,now=13):
        a,r,p,c=x
        if not valid('EncodingAuthorization',a) or not iv.is_valid(r) or not iv.is_valid(p):return 'schema'
        return M.encoding_error(a,r,p,c,now)
    for kind in ('ordinary','cancel'):
        x=fixture(frames,kind);a,r,p,c=x
        check(kind+'关联正例',evaluate(x),None)
        e=M.evidence(a,r,p,c['received_tick']);v=finalization(e)
        for name,obj in [('EncodingAuthorization',a),('EncodingEvidence',e),('FinalizationLink',v)]:
            check(kind+name+'形状',valid(name,obj),True)
            check(kind+name+'根不可直接校验',Draft202012Validator(s).is_valid(obj),False)
            for key in obj:
                bad=clone(obj);del bad[key];check(kind+name+'缺:'+key,valid(name,bad),False)
            bad=clone(obj);bad['extra']=True;check(kind+name+'额外字段',valid(name,bad),False)
        for key in ('ownership_ref','guard_ref','permit_id','issued_revision','gate_access_ref'):
            bad=clone(a);bad[key]=ref('future');check(kind+'编码不引用未来:'+key,valid('EncodingAuthorization',bad),False)
        for n in ('01','-1','1\n',1,str(10**20)):
            bad=clone(a);bad['expires_tick_ns']=n;check(kind+'拒计数:'+repr(n),valid('EncodingAuthorization',bad),False)
        check(kind+'到期等号',evaluate(x,40),'expired')
        check(kind+'截止前',evaluate(x,39),None)
        for field in ('admission_source_ref','authorization_snapshot_ref','capability_ref','primitive_plan_ref','transport_profile_ref','encoding_reservation_ref'):
            bad=clone(x);bad[3][field]=ref('new');check(kind+'来源变化:'+field,evaluate(bad),'current_source')
        bad=clone(x);bad[3]['revoked_refs']=[M.aref(a)];check(kind+'原件撤回',evaluate(bad),'revoked')
        bad=clone(x);bad[0]['requester']['principal_id']='other';O.seal(bad[0],'authorization_digest')
        check(kind+'重算摘要不变权威',evaluate(bad),'authorization_source')
        def received_case(name,mutate,expected):
            bad=clone(x);mutate(bad[2]);bad[3]['stored_response']=clone(bad[2]);check(kind+name,evaluate(bad),expected)
        received_case('错误响应关联',lambda p:p.update(reply_to='other'),'reply')
        received_case('错误授权回显',lambda p:p['body'].update(encoding_authorization_ref=ref('other')),'authorization_binding')
        received_case('篡改字节',lambda p:p['body'].update(bytes_hex='0103'),'packet_bytes')
        received_case('重算包摘要仍错primitive',lambda p:(p['body']['packet'].update(primitive_id='other'),O.seal(p['body']['packet'],'packet_digest')),'packet_primitive')
        received_case('重算包摘要仍错会话',lambda p:(p['body']['packet'].update(protocol_session='other'),O.seal(p['body']['packet'],'packet_digest')),'packet_session')
        received_case('重算包摘要仍错设备',lambda p:(
            p['body']['packet'].update(device_session_id='other') if kind=='ordinary' else p['body']['packet']['exit'].update(device_session_id='other'),
            O.seal(p['body']['packet'],'packet_digest')),'packet_exit')
        received_case('原字节引用错误',lambda p:(p['body']['packet']['immutable_bytes_ref'].update(digest=O.digest('other')),O.seal(p['body']['packet'],'packet_digest')),'packet_bytes')
        bad=clone(x);bad[0]['max_bytes']=1;O.seal(bad[0],'authorization_digest')
        bad[1]['body']['encoding_authorization']=clone(bad[0]);bad[2]['body']['encoding_authorization_ref']=M.aref(bad[0])
        bad[3].update(authorizations={bad[0]['authorization_id']:clone(bad[0])},stored_request=clone(bad[1]),stored_response=clone(bad[2]))
        check(kind+'实际profile字节上限',evaluate(bad),'packet_bytes')
        if kind=='ordinary':
            bad=clone(x);bad[1]['body']['request']['parameters']['scene_ref']['scene_id']='changed';bad[3]['stored_request']=clone(bad[1])
            check('普通编码不接受改后的命令内容',evaluate(bad),'request_content')
        for name in (('PACKET_ENCODING_FAILED','PREPARE_PACKET_REJECTED') if kind=='ordinary' else ('CANCEL_ENCODING_FAILED',)):
            bad=clone(x);failed=clone(frames[name]);failed['ipc_version']=G.VERSION
            for k in O.FRAME_BINDING:failed[k]=a['binding'][k]
            failed.update(message_id='encode.failure',reply_to=r['message_id'])
            failed['body'].update(prepare_id=r['body']['prepare_id'],encoding_authorization_ref=M.aref(a))
            if kind=='cancel':failed['body']['execution_ref']=clone(a['target']['execution_ref'])
            if name=='PREPARE_PACKET_REJECTED':failed['body']['packet_ref']=clone(e['packet_ref'])
            bad[2].clear();bad[2].update(failed);bad[3]['stored_response']=clone(failed)
            check('失败响应不形成成功证据:'+name,evaluate(bad),'encoding_failed')
        for k in O.FRAME_BINDING:
            def mutate(p,k=k):p[k]='clock_'+'2'*64 if k=='clock_domain_id' else O.digest('other') if k=='descriptor_digest' else 'other'
            received_case('错出口:'+k,mutate,'exit')
        # 所有待检查模型前提均是合成。此限制反证不能作为生产授权。
        forged=clone(x);forged[0]['requester']['principal_id']='forged';O.seal(forged[0],'authorization_digest')
        forged[1]['body']['encoding_authorization']=clone(forged[0]);forged[2]['body']['encoding_authorization_ref']=M.aref(forged[0])
        forged[3].update(requester=clone(forged[0]['requester']),authorizations={forged[0]['authorization_id']:clone(forged[0])},stored_request=clone(forged[1]),stored_response=clone(forged[2]))
        check(kind+'全部可信上下文伪造的限制反证',evaluate(forged),None)
        # 顺序模型不执行完整Guard语义或真正SQLite事务。
        def prepared():
            m=M.Order();assert m.prepare(e,x,13)=='prepared';return m
        m=prepared();check(kind+'编码不签发',len(m.records),0);check(kind+'编码不收费',len(m.charges),0)
        check(kind+'编码不发送',m.dispatch('permit',current(v),16),'no_commit')
        check(kind+'提交前不安装最终Guard',m.guard_ack('permit',v['guard_ref'],v['packet_ref'],current(v),16),'no_commit')
        check(kind+'最终提交',m.finalize(v,clone(v),x),'committed')
        check(kind+'无GuardACK不发',m.dispatch('permit',current(v),16),'no_guard_ack')
        check(kind+'错GuardACK',m.guard_ack('permit',ref('wrong'),v['packet_ref'],current(v),16),'guard_binding')
        check(kind+'精确GuardACK',m.guard_ack('permit',v['guard_ref'],v['packet_ref'],current(v),16),'installed')
        check(kind+'正常消费',m.dispatch('permit',current(v),16),'in_flight')
        check(kind+'重复不发',m.dispatch('permit',current(v),17),'cached_result');check(kind+'一次副作用',len(m.effects),1)
        check(kind+'一次收费',len(m.charges),1);check(kind+'重复提交仅查原',m.finalize(v,clone(v),x),'query_original')
        bad=clone(v);bad['issued_revision']='0';check(kind+'无零号签发',prepared().finalize(bad,clone(bad),x),'commit_time')
        bad=clone(v);bad['encoding_evidence_ref']=ref('wrong');check(kind+'错误准备证据',prepared().finalize(bad,clone(bad),x),'preparation_binding')
        bad=clone(e);bad['byte_length']=3;check(kind+'准备证据摘要篡改',M.Order().prepare(bad,x,13),'evidence_digest')
        O.seal(bad,'evidence_digest');check(kind+'重算证据仍须精确原件',M.Order().prepare(bad,x,13),'evidence_binding')
        m=prepared();check(kind+'重复准备只查历史',m.prepare(e,x,40),'cached_preparation')
        check(kind+'冲突准备不能替换',m.prepare(bad,x,13),'preparation_conflict')
        for tick,expected in ((39,'committed'),(40,'encoding_expired')):
            m=prepared();later=clone(v);later.update(committed_tick_ns=str(tick),send_not_before_tick_ns='40',send_before_tick_ns='50')
            check(kind+'T2编码期限:'+str(tick),m.finalize(later,clone(later),x),expected)
            check(kind+'T2截止拒绝无预算:'+str(tick),len(m.charges),1 if tick==39 else 0)
        m=prepared();revoked=clone(x);revoked[3]['revoked_refs']=[M.aref(a)]
        check(kind+'编码后T2前撤权',m.finalize(v,clone(v),revoked),'encoding_revoked')
        check(kind+'撤权不签发',len(m.records),0)
        m=prepared();later=clone(v);later['send_before_tick_ns']='50';m.finalize(later,clone(later),x)
        check(kind+'已提交历史不被编码TTL抹去',m.guard_ack('permit',later['guard_ref'],later['packet_ref'],current(later),41),'installed')
        check(kind+'最终窗口与编码TTL独立',m.dispatch('permit',current(later),41),'in_flight')
        for outcome in ('rollback','unknown'):
            m=prepared();check(kind+'提交结果:'+outcome,m.finalize(v,clone(v),x,outcome),'rolled_back' if outcome=='rollback' else 'commit_uncertain')
            check(kind+'结果后无许可:'+outcome,len(m.records),0)
            check(kind+'结果后禁止Guard:'+outcome,m.guard_ack('permit',v['guard_ref'],v['packet_ref'],current(v),16),'no_commit' if outcome=='rollback' else 'commit_uncertain')
            check(kind+'结果后不发送:'+outcome,m.dispatch('permit',current(v),16),'no_commit' if outcome=='rollback' else 'commit_uncertain')
        for field in M.Order.CURRENT:
            m=prepared();m.finalize(v,clone(v),x);m.guard_ack('permit',v['guard_ref'],v['packet_ref'],current(v),16)
            c2=current(v);c2[field]=ref('new');check(kind+'ACK后变代:'+field,m.dispatch('permit',c2,17),'changed')
        for flag in ('pending_control','hard_protection'):
            m=prepared();m.finalize(v,clone(v),x);c2=current(v);c2[flag]=True
            check(kind+'最终保护:'+flag,m.guard_ack('permit',v['guard_ref'],v['packet_ref'],c2,16),'protected')
        m=prepared();m.finalize(v,clone(v),x);m.guard_ack('permit',v['guard_ref'],v['packet_ref'],current(v),16)
        check(kind+'窗口前',m.dispatch('permit',current(v),15),'too_early')
        check(kind+'发送截止等号',m.dispatch('permit',current(v),30),'expired')
        check(kind+'消费后故障',m.dispatch('permit',current(v),17,'crash'),'unknown')
        check(kind+'未知不重发',m.dispatch('permit',current(v),18),'cached_result')
        check(kind+'未知不退款',len(m.charges),1);m.restart();check(kind+'重启不续跑',m.dispatch('permit',current(v),19),'retired')
        m=prepared();check(kind+'提交原件缺失',m.finalize(v,{},x),'seal_source')
        m.finalize(v,clone(v),x);v2=clone(v);v2.update(permit_id='permit.2',issued_revision='2')
        check(kind+'重传不可复用预算',m.finalize(v2,clone(v2),x),'charge_reuse')
        v2['budget_charge_ref']=ref('charge.2');v2['issued_revision']='1'
        check(kind+'签发序列不得复用',m.finalize(v2,clone(v2),x),'issue_reuse')
    # 手写依赖关系是设计反例，不能当实际并发或自动发现全系统依赖的证明。
    def acyclic(edges):
        remaining={n:set(deps) for n,deps in edges.items()}
        while remaining:
            ready={n for n,deps in remaining.items() if not deps}
            if not ready:return False
            remaining={n:deps-ready for n,deps in remaining.items() if n not in ready}
        return True
    check('旧编码与最终Guard依赖环',acyclic({'encode':{'guard'},'packet':{'encode'},'guard':{'packet'}}),False)
    check('新顺序无环',acyclic({'encode_authority':set(),'encode':{'encode_authority'},'packet':{'encode'},
       'final_commit':{'packet'},'guard_install':{'final_commit'},'guard_ack':{'guard_install'},'dispatch':{'guard_ack'}}),True)
    # 完整48帧保留旧形状回归，七个编码相关正文显式升级；不把旧帧结构当全语义验证。
    upgrades={k:clone(v) for k,v in frames.items()}
    for kind in ('ordinary','cancel'):
        a,r,p,c=fixture(frames,kind);upgrades[r['type']]=r;upgrades[p['type']]=p
        for n in (('PACKET_ENCODING_FAILED','PREPARE_PACKET_REJECTED') if kind=='ordinary' else ('CANCEL_ENCODING_FAILED',)):
            upgrades[n]['body']['encoding_authorization_ref']=M.aref(a)
    binding=Q.fixture()[3]['binding'];body=dict(request_id='renew',binding=binding,control_authority_ref=ref('control'),before_gate_ref=ref('gate'),
      close_ack_ref=ref('close'),target_gate_revision='2',gate_token='token',selected_tick_ns='10',expires_tick_ns='20',lease_until_tick_ns='30',request_digest=O.digest('renew'))
    for name,b,reply in [('GATE_FENCE',body,None),('GATE_FENCE_ACK',dict(request_id='renew',request_digest=body['request_digest'],binding=binding,gate_revision='2',gate_token='token',effective_tick_ns='11',state='fenced'),'renew')]:
        upgrades[name]=dict(**{k:binding[k] for k in O.FRAME_BINDING},type=name,message_id=name,reply_to=reply,seq='1',body=b)
    for name,f in upgrades.items():
        f['ipc_version']=G.VERSION
        if name=='HELLO':f['body']['supported_ipc_versions']=[G.VERSION];f['body']['supported_features']+=['fresh_gate_fence',G.FEATURE]
        if name=='HELLO_ACK':f['body']['selected_ipc_version']=G.VERSION;f['body']['selected_features']+=['fresh_gate_fence',G.FEATURE]
        check('完整帧结构:'+name,iv.is_valid(f),True)
        old=clone(f);old['ipc_version']='ipc/0.10.0-gate-renewal-draft.1';check('拒绝旧写版本:'+name,iv.is_valid(old),False)
    check('完整帧数',len(upgrades),48)
    check('最终提交投影不导出IPC','EA__FinalizationLink' in ipc['$defs'],False)
    for name,k in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        bad=clone(upgrades[name]);bad['body'][k].remove(G.FEATURE);check('必选协商:'+name,iv.is_valid(bad),False)
    for name,key in [('ENCODE_PACKET','guard_id'),('ENCODE_CANCEL_PACKET','guard_ref')]:
        bad=clone(upgrades[name]);bad['body'][key]='old' if key=='guard_id' else ref('old');check('拒绝旧编码Guard:'+name,iv.is_valid(bad),False)
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    raw_frames,inherited=Q.old_frames();frames={f['type']:f for f in Q.upgrade_frames(raw_frames)}
    inputs=list(dict.fromkeys(Q.input_paths(inherited)+[HERE/n for n in LOCAL]))
    target=HERE/'encoding-authority-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        report=json.loads(read(target));assert set(report['inputs'])=={f.relative_to(ROOT).as_posix() for f in inputs}
        for f in inputs:assert report['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest(),str(f)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(inputs))))
    else:
        checks=run(frames);report=dict(all_passed=True,approved=False,cases_passed=len(checks),ipc_messages=48,
          scope='仅编码授权、完整IPC形状及持久签发到Guard安装的有限顺序',runtime_tests_executed=0,
          sqlite_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,
          checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs})
        if a.report:target.write_bytes(G.S.encoded(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False))
