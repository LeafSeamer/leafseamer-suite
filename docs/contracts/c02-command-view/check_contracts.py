"""离线Schema/OpenAPI与人工权威快照检查；无网络或业务运行。"""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import jsonschema
from referencing import Registry, Resource
from openapi_spec_validator import validate
import build_contracts as B
import reference_model as M

HERE=B.HERE
ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','reference_model.py','check_contracts.py',
                        'command.schema.json','command.openapi.json')]+B.SOURCES
INPUTS += [HERE.parent/'c08-controller'/n for n in ('command.sql','COMMAND_STORAGE.md')]
D='sha256:'+'a'*64
S=dict(authority_service_id='controller',database_instance_id='database')


def ref(name, revision='1'):
    return dict(id=name,revision=revision,digest=D)


def fixture():
    state=dict(command_id='command',scope=S,revision='1',phase='queued',outcome='pending',
        effect_status='not_sent',resource_status='clear',automation_continuation='eligible',
        reason_code=None,terminal_revision=None,resolution_ref=None,
        completion_evidence_refs=[],resource_evidence_refs=[],attempt_ids=[])
    policy=dict(command_id='command',scope=S,device_id='device',admission_ref=ref('adjudication'),
        required_completion='effect_verified',completion_policy_ref=ref('completion-policy'),
        release_policy_ref=ref('release-policy'),retry_policy_ref=None,max_attempts=1,
        original_deadline_ref=ref('deadline'),conflict_scope='whole_device')
    request_key=dict(target_scope=S,issuer_id='issuer',issuer_epoch='issuer-epoch',principal_id='operator',
                     request_epoch='request-epoch',operation_id='createCommand',idempotency_key='create-key')
    actor=dict(principal_id='operator',session_id='session',authorization_revision='1',
               issuer_id='issuer',issuer_epoch='issuer-epoch',local_subject_id='local')
    record=dict(command_id='command',scope=S,revision='1',
        initial_command_ref=dict(kind='command',scope=S,object_id='command',revision='1',digest=D),
        request_identity=dict(key=request_key,request_digest=D),
        target=dict(device_id='device',action_id='obs.program_scene.set',capability_version='1.0.0'),
        actor=actor,origin='manual',run_binding=None,automation_binding=None,accepted_at='2026-10-20T00:00:00.000Z',
        dispatch=dict(mode='immediate',max_queue_ms=1000),control_binding=dict(epoch='control',version='1'),
        policy=policy,state_ref=M.state_ref(state),state=state,
        completion=dict(required='effect_verified',achieved=None,policy_ref=ref('completion-policy'),evidence_refs=[]),
        attempts=[],cancellation=None,
        evidence_index=dict(snapshot_ref=ref('evidence-snapshot'),state_ref=M.state_ref(state),total='0'),
        record_digest='')
    M.seal(record,'record_digest')
    context=dict(scope=copy.deepcopy(S),command_id='command',device_id='device',origin='manual',
        authenticated=True,permissions=['command.read','command.cancel','command.evidence.read'],
        allowed_devices=['device'],subject_kind='human',paired=False,service_id='',
        originating_service_id=None,csrf_valid=True,namespace_owned=True,context_live=True,
        capacity_available=True,storage_available=True,current_publishable=True,
        new_cancellation_id='cancel',cancel_mode='before_dispatch_only',
        observed_state_ref=M.state_ref(dict(state,revision='2')),
        owned_namespaces=[['issuer','issuer-epoch','operator','request-epoch']],
        context=dict(context_id='context',issuer_id='issuer',issuer_epoch='issuer-epoch',
                     principal_id='operator',context_epoch='request-epoch'))
    for k in ('state','policy','initial_command_ref','request_identity','attempts','completion','cancellation','evidence_index'):
        context[k]=copy.deepcopy(record[k])
    context['immutable']={k:copy.deepcopy(record[k]) for k in
        ('target','actor','origin','run_binding','automation_binding','accepted_at','dispatch','control_binding')}
    return record,context


def run():
    generated=B.build()
    for name,value in generated.items():
        assert (HERE/name).read_bytes()==B.encoded(value),name
    schema=generated['command.schema.json']
    sources=[schema]+[json.loads(p.read_bytes()) for p in B.SOURCES]
    registry=Registry().with_resources((s['$id'],Resource.from_contents(s)) for s in sources)
    jsonschema.Draft202012Validator.check_schema(schema)
    validate(generated['command.openapi.json'])
    checks=[]
    def check(name,actual,expected=True):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,actual=actual))
    def valid(name,value):
        return jsonschema.Draft202012Validator({'$ref':B.SID+'#/$defs/'+name},registry=registry,
            format_checker=jsonschema.FormatChecker()).is_valid(value)
    def projection(name,value):
        api=generated['command.openapi.json']
        return jsonschema.Draft202012Validator({'$ref':'#/components/schemas/S0_'+name,
            'components':api['components']},format_checker=jsonschema.FormatChecker()).is_valid(value)
    record,c=fixture()
    request=dict(context_id='context',idempotency_key='cancel-key',expected_state_ref=record['state_ref'],reason='停止旧动作')
    operation=M.seal(dict(cancellation_id='cancel',scope=S,command_id='command',revision='1',
        identity=M.cancel_identity(request,c),state='requested',mode='before_dispatch_only',future_writes='pending',
        command_state_ref=M.state_ref(dict(c['state'],revision='2')),evidence_refs=[],reason_code=None,
        operation_digest=''),'operation_digest')
    ledger={}
    status,receipt=M.cancel_step(request,c,ledger)
    check('新取消受理',status,'accepted')
    check('回执只单向引用完整初始操作',receipt['initial_operation_ref'],
          dict(id='cancel',revision='1',digest=operation['operation_digest']))
    lookup=dict(state='found',receipt=receipt)
    decision=M.seal(dict(evidence_id='decision',command_id='command',scope=S,kind='failure',
        policy_ref=ref('completion-policy'),retry_policy_ref=None,attempt_ids=[],
        achieved=None,effect_status='not_sent',resolved_outcome=None,evidence_digest=''),'evidence_digest')
    evidence=M.seal(dict(scope=S,command_id='command',
        source_ref=dict(id='decision',revision='1',digest=decision['evidence_digest']),
        kind='decision',body=decision,view_digest=''),'view_digest')
    page=M.seal(dict(scope=S,command_id='command',snapshot_ref=ref('snapshot'),state_ref=record['state_ref'],
        offset='0',total='1',items=[evidence],next_cursor=None,page_digest=''),'page_digest')
    samples={'CommandRecord':record,'CommandRead':dict(view='current',record=record),
        'CancelRequest':request,'CancelIdentity':receipt['identity'],'CancelReceipt':receipt,
        'CancelOperation':operation,'CancelLookup':lookup,'EvidenceRecord':evidence,'EvidencePage':page,
        'Error':dict(code='state_projection_pending',request_id='request',retry_action='read_current')}
    for name,value in samples.items():
        check(name+'局部正例',valid(name,value))
        check(name+'OpenAPI投影正例',projection(name,value))
        bad=copy.deepcopy(value);bad['unexpected']=True
        check(name+'拒额外字段',valid(name,bad),False)
        check(name+'投影拒额外字段',projection(name,bad),False)
    check('完整命令关联',M.record_error(record,c),None)
    check('当前读取',M.read_command(record,c)[1]['view'],'current')
    for label,edit,expected in [
        ('原受理引用不能变当前版本',lambda v:v['initial_command_ref'].update(revision='2'),'admission_binding'),
        ('跨库重算摘要仍拒绝',lambda v:v['scope'].update(database_instance_id='other'),'record_owner'),
        ('旧attempt不能遗漏',lambda v:v['state']['attempt_ids'].append('missing'),'record_digest'),
        ('固定政策不能换',lambda v:v['policy'].update(max_attempts=2),'authoritative_state'),
        ('取消状态不能随意投影',lambda v:v.update(cancellation=dict(operation_ref=ref('c'),state='confirmed',
            future_writes='closed',reason_code=None)),'cancellation_binding'),
        ('证据清单不能临时换',lambda v:v['evidence_index'].update(total='99'),'evidence_snapshot'),
        ('原控制版本不能换当前持有人',lambda v:v['control_binding'].update(version='2'),'immutable_metadata')]:
        bad=copy.deepcopy(record);edit(bad);M.seal(bad,'record_digest')
        check(label,M.record_error(bad,c),expected)
    stale=copy.deepcopy(c);stale['current_publishable']=False
    check('投影不可发不回旧clear',M.read_command(record,stale),('state_projection_pending',None))
    check('历史读取显式historical',M.read_command(record,stale,True)[1]['view'],'historical')
    for change,result in [({'authenticated':False},'unauthenticated'),({'permissions':[]},'forbidden'),
        ({'allowed_devices':[]},'forbidden'),({'subject_kind':'service','paired':True,'origin':'manual'},'forbidden'),
        ({'subject_kind':'service','paired':False,'origin':'automation'},'forbidden')]:
        denied=copy.deepcopy(stale);denied.update(change)
        check('先鉴权不泄漏投影状态'+str(change),M.read_command(record,denied)[0],result)
    service=copy.deepcopy(c);service.update(subject_kind='service',paired=True,origin='automation',
        service_id='seamer',originating_service_id='seamer',csrf_valid=False)
    check('已配对服务限自身自动化',M.authorize(service,'command.read'),None)
    service['originating_service_id']='other'
    check('同组织不同来源不能借权',M.authorize(service,'command.cancel'),'forbidden')
    for name,val in [('revision','01'),('revision','1\n')]:
        bad=copy.deepcopy(record);bad[name]=val
        check('严格修订'+repr(val),valid('CommandRecord',bad),False)
    bad=copy.deepcopy(record);bad['state'].update(phase='finished',outcome='unknown',
        effect_status='possible',automation_continuation='paused_latched',reason_code='timeout',
        terminal_revision='1')
    check('unknown无Resolution不能clear',valid('CommandRecord',bad),False)
    bad=copy.deepcopy(operation);bad['state']='cancelled'
    check('取消操作状态不混命令outcome',valid('CancelOperation',bad),False)
    bad=copy.deepcopy(receipt['identity']);bad['key']['operation_id']='createCommand'
    check('取消身份不借创建命名空间',valid('CancelIdentity',bad),False)
    for change,expected in [({'context_live':False},'existing'),({'capacity_available':False},'existing'),
        ({'state':dict(c['state'],revision='2')},'existing'),({'current_publishable':False},'existing'),
        ({'permissions':[]},'forbidden'),({'csrf_valid':False},'forbidden'),({'namespace_owned':False},'forbidden')]:
        cc=copy.deepcopy(c);cc.update(change);before=copy.deepcopy(ledger)
        check('查原先于新期限和CAS'+str(change),M.cancel_step(request,cc,ledger)[0],expected)
        check('查原不新增'+str(change),ledger==before)
    changed=copy.deepcopy(request);changed['reason']='changed'
    check('同键异内容冲突',M.cancel_step(changed,c,ledger)[0],'identity_conflict')
    changed=copy.deepcopy(request);changed['expected_state_ref']=ref('other-command')
    check('CAS内容参与请求摘要',M.cancel_step(changed,c,ledger)[0],'identity_conflict')
    for change,expected in [({'context_live':False},'context_expired'),({'capacity_available':False},'capacity'),
        ({'storage_available':False},'unavailable'),({'state':dict(c['state'],revision='2')},'state_conflict')]:
        cc=copy.deepcopy(c);cc.update(change);empty={}
        check('新请求门控'+str(change),M.cancel_step(request,cc,empty)[0],expected)
        check('拒绝不占身份'+str(change),len(empty),0)
    newer=copy.deepcopy(c);newer['context']['issuer_epoch']='next-issuer'
    newer['owned_namespaces'].append(['issuer','next-issuer','operator','request-epoch'])
    check('issuer_epoch进入唯一键',M.cancel_identity(request,newer)['key']!=M.cancel_identity(request,c)['key'])
    check('换身份不重复同命令的物理取消',M.cancel_step(request,newer,ledger)[0],'cancellation_exists')
    before=copy.deepcopy(ledger)
    check('旧请求lookup',M.lookup_cancel(receipt['identity'],c,ledger)[1],lookup)
    missing=copy.deepcopy(receipt['identity']);missing['key']['idempotency_key']='missing'
    check('not_found不变更账本',M.lookup_cancel(missing,c,ledger)[1],dict(state='not_found',receipt=None))
    check('全部lookup只读',ledger==before)
    stolen=copy.deepcopy(c);stolen['owned_namespaces']=[['issuer','issuer-epoch','other','request-epoch']]
    check('知道完整身份不授查原权',M.lookup_cancel(receipt['identity'],stolen,ledger)[0],'forbidden')
    cc=copy.deepcopy(c);cc['storage_available']=False
    check('查原故障为indeterminate',M.lookup_cancel(missing,cc,ledger)[1],dict(state='indeterminate',receipt=None))
    terminal=dict(c['state'],revision='5',phase='finished',outcome='unknown',effect_status='possible',
        resource_status='unresolved',automation_continuation='paused_latched',reason_code='timeout',terminal_revision='5')
    after=dict(terminal,revision='6')
    oc=dict(command_id='command',scope=S,identity=receipt['identity'],before_state=terminal,after_state=after,
        closure_proven=True,cancellation_proven=True,prior_completion_proven=False,resource_clear_proven=False,
        previous_operation=None)
    confirmed=copy.deepcopy(operation);confirmed.update(state='confirmed',future_writes='closed',
        command_state_ref=M.state_ref(after));M.seal(confirmed,'operation_digest')
    check('取消确认不改原unknown且仍未决',M.cancellation_error(confirmed,oc),None)
    for change,expected in [({'closure_proven':False},'closure_unproven'),
        ({'cancellation_proven':False},'cancellation_unproven'),
        ({'after_state':dict(after,outcome='cancelled')},'terminal_immutable'),
        ({'after_state':dict(after,automation_continuation='eligible')},'latch_immutable'),
        ({'after_state':dict(after,resource_status='clear')},'release_unproven')]:
        cc=copy.deepcopy(oc);cc.update(change);v=copy.deepcopy(confirmed)
        v['command_state_ref']=M.state_ref(cc['after_state']);M.seal(v,'operation_digest')
        check('取消与终态资源独立'+str(change),M.cancellation_error(v,cc),expected)
    late=copy.deepcopy(confirmed);late['state']='too_late';M.seal(late,'operation_digest')
    check('too_late必须已有确定完成',M.cancellation_error(late,oc),'completion_unproven')
    uncertain=copy.deepcopy(operation);uncertain['state']='indeterminate';M.seal(uncertain,'operation_digest')
    follow=copy.deepcopy(confirmed);follow['revision']='2';M.seal(follow,'operation_digest')
    cc=copy.deepcopy(oc);cc['previous_operation']=uncertain
    check('不确定取消可凭新证据确认',M.cancellation_error(follow,cc),None)
    reopen=copy.deepcopy(follow);reopen.update(state='requested',future_writes='pending');M.seal(reopen,'operation_digest')
    check('不确定取消禁止重开requested',M.cancellation_error(reopen,cc),'cancel_reopen')
    cc['previous_operation']=confirmed
    check('确定取消禁止重开requested',M.cancellation_error(reopen,cc),'cancel_final')
    # 独立核对future_writes单调性，保持其他取消判据成立。
    old_requested=copy.deepcopy(operation);old_requested['future_writes']='closed'
    pending=copy.deepcopy(operation);pending['revision']='2'
    pending['command_state_ref']=M.state_ref(after);M.seal(pending,'operation_digest')
    cc['previous_operation']=M.seal(old_requested,'operation_digest')
    check('可靠关闭不得回退pending',M.cancellation_error(pending,cc),'closure_rewrite')
    pc=copy.deepcopy(c);pc.update(snapshot_ref=ref('snapshot'),snapshot_state_ref=record['state_ref'],
        cursor_bound=True,cursor_expired=False,limit=1,expected_offset=0,ordered_evidence=[evidence],
        evidence={('decision','decision','1'):evidence})
    check('固定证据页',M.page_error(page,pc),None)
    for label,edit,expected in [('换快照',lambda p:p.update(snapshot_ref=ref('other')),'snapshot_binding'),
        ('遗漏最后证据',lambda p:p.update(items=[]),'page_members'),
        ('伪造总数',lambda p:p.update(total='2'),'page_members'),
        ('多发下一页游标',lambda p:p.update(next_cursor='a'*16),'page_continuation'),
        ('旧页冒新offset',lambda p:p.update(offset='1'),'page_members')]:
        bad=copy.deepcopy(page);edit(bad);M.seal(bad,'page_digest')
        check(label,M.page_error(bad,pc),expected)
    for change,expected in [({'cursor_bound':False},'cursor_binding'),({'cursor_expired':True},'snapshot_gone'),
        ({'permissions':['command.read']},'forbidden')]:
        cc=copy.deepcopy(pc);cc.update(change)
        check('分页读取边界'+str(change),M.page_error(page,cc),expected)
    bad=copy.deepcopy(evidence);bad['body']['effect_status']='verified';M.seal(bad['body'],'evidence_digest')
    bad['source_ref']['digest']=bad['body']['evidence_digest'];M.seal(bad,'view_digest')
    check('重算证据摘要不成为权威',M.evidence_error(bad,pc),'evidence_source')
    bad=copy.deepcopy(evidence);bad['body']['provider_receipt']={'accepted':True}
    check('公共证据不接纳权威原件',valid('EvidenceRecord',bad),False)
    resolution=dict(resolution_id='z',command_id='command',scope=S,original_terminal_revision='5',revision='1',
        resolved_outcome='not_sent',evidence_refs=[ref('e')],resolver_ref=ref('resolver'),resolution_digest=D)
    check('核对not_sent保持',valid('Resolution',resolution))
    resolution['resolved_outcome']='unknown'
    check('未知观察不是确定核对',valid('Resolution',resolution),False)
    resolution['resolved_outcome']='not_sent';M.seal(resolution,'resolution_digest')
    release=M.seal(dict(evidence_id='release',command_id='command',scope=S,device_id='device',hold_id='hold',
        cut_ref=ref('cut'),kind='never_sent',policy_ref=ref('release-policy'),
        future_writes_closed_ref=ref('closed'),settlement_proof_ref=None,evidence_digest=''),'evidence_digest')
    invalidation=dict(invalidation_id='invalid',scope=S,command_id='command',subject_ref=ref('release'),
                      reason_code='late_fact',protection_ref=ref('protection'))
    for kind,body,identity,dgst in [('release',release,'release',release['evidence_digest']),
        ('resolution',resolution,'z',resolution['resolution_digest']),
        ('invalidation',invalidation,'invalid',M.digest(invalidation))]:
        ev=M.seal(dict(scope=S,command_id='command',source_ref=dict(id=identity,revision='1',digest=dgst),
                      kind=kind,body=body,view_digest=''),'view_digest')
        ec=copy.deepcopy(pc);ec['evidence'][(kind,identity,'1')]=copy.deepcopy(ev)
        check(kind+'证据结构',valid('EvidenceRecord',ev))
        check(kind+'证据投影',projection('EvidenceRecord',ev))
        check(kind+'原件绑定',M.evidence_error(ev,ec),None)
        ev['body']['command_id']='other';M.seal(ev,'view_digest')
        check(kind+'正文错所有者',M.evidence_error(ev,ec),'evidence_body_owner')
    multi=copy.deepcopy(pc)
    second=copy.deepcopy(evidence);second['body']['evidence_id']='decision2'
    M.seal(second['body'],'evidence_digest')
    second['source_ref']=dict(id='decision2',revision='1',digest=second['body']['evidence_digest'])
    M.seal(second,'view_digest')
    multi['evidence'][('decision','decision2','1')]=second
    multi['ordered_evidence']=[evidence,second]
    first=copy.deepcopy(page);first.update(total='2',next_cursor='a'*16);M.seal(first,'page_digest')
    check('未完快照必须有游标',M.page_error(first,multi),None)
    multi['expected_offset']=1
    last=copy.deepcopy(first);last.update(offset='1',items=[second],next_cursor=None);M.seal(last,'page_digest')
    check('后页保留原快照并正确结束',M.page_error(last,multi),None)
    empty=copy.deepcopy(pc);empty.update(ordered_evidence=[],evidence={})
    empty_page=copy.deepcopy(page);empty_page.update(total='0',items=[]);M.seal(empty_page,'page_digest')
    check('空快照不伪造下一页',M.page_error(empty_page,empty),None)
    api=generated['command.openapi.json']
    operations={op['operationId']:op for path in api['paths'].values() for op in path.values()}
    check('七接口完整',sorted(operations),sorted(['getCommand','getCommandRevision','cancelCommand',
        'lookupCommandCancellation','getCommandCancellation','getCommandEvidence','getCommandEvidenceRevision']))
    check('取消人类要求CSRF且服务单独分支',operations['cancelCommand']['security'],
          [{'humanBearer':[],'csrfToken':[]},{'serviceBearer':[]}])
    for name,op in operations.items():
        check(name+'no-store',all(v['headers']['Cache-Control']['schema']=={'const':'no-store'} for v in op['responses'].values()))
        check(name+'精确版本',op['parameters'][0]['schema'],{'const':B.VERSION})
    get_error=api['paths']['/api/v1/commands/{command_id}']['get']['responses']['503']['content']['application/json']['schema']
    check('503显式投影未就绪',get_error['allOf'][1]['properties']['code']['enum'],['unavailable','state_projection_pending'])
    def response_valid(op,code,value):
        root=copy.deepcopy(operations[op]['responses'][code]['content']['application/json']['schema'])
        root['components']=api['components']
        return jsonschema.Draft202012Validator(root,format_checker=jsonschema.FormatChecker()).is_valid(value)
    check('当前操作接受current',response_valid('getCommand','200',dict(view='current',record=record)))
    check('当前操作拒history冒充',response_valid('getCommand','200',dict(view='historical',record=record)),False)
    check('历史操作接受historical',response_valid('getCommandRevision','200',dict(view='historical',record=record)))
    check('历史操作拒current冒充',response_valid('getCommandRevision','200',dict(view='current',record=record)),False)
    check('503错误结构',response_valid('getCommand','503',samples['Error']))
    check('503不混403错误',response_valid('getCommand','403',samples['Error']),False)
    err=dict(samples['Error'],retry_action='none')
    check('投影未就绪明确查询动作',valid('Error',err),False)
    check('公开闭包不含权威原件',not any(n.endswith(('_ProviderReceipt','_TimeBoundEvidence',
        '_BootstrapAssignment','_InternalReadAuthorization')) for n in api['components']['schemas']))
    return checks


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true')
    p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true')
    args=p.parse_args()
    if args.staged and not args.check_report:
        p.error('--staged需配合--check-report')
    if args.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        data=json.loads(read(HERE/'reference-report.json'))
        assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
        for f in INPUTS:
            assert data['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run()
        data=dict(all_passed=True,cases_passed=len(checks),approved=False,
            scope='七个命令读取取消证据HTTP的结构投影与合成关联',
            runtime_tests_executed=0,device_tests_executed=0,sqlite_tests_executed=0,
            checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
        if args.report:
            (HERE/'reference-report.json').write_bytes(B.encoded(data))
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
