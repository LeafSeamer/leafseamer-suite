"""限定取消范围的结构关联及有限顺序检查；无真实发送或生产授权。"""
import argparse,copy,hashlib,json,subprocess,sys
from pathlib import Path
from jsonschema import Draft202012Validator
import build_scoped_gate as G
import check_hold_ownership as H
import scoped_gate_model as M
O=H.O;HERE=G.HERE;ROOT=HERE.parents[2];clone=H.clone;ref=H.L.ref
LOCAL=('SCOPED_GATE.md','build_scoped_gate.py','scoped_gate_model.py','check_scoped_gate.py','scoped-gate.schema.json','scoped-gate-ipc.schema.json')
def assessment_store(e,c):
    O.seal(e,'assessment_digest');c['assessments'][e['assessment_id']]=clone(e)
    c['assessment_receipts'][e['provider_receipt_ref']['id']]=dict(ref=clone(e['provider_receipt_ref']),
        content=clone({k:v for k,v in e.items() if k not in ('assessment_digest','provider_receipt_ref')}))
    c['current_assessment_ref']=M.eref(e)
def access_store(a,c):O.seal(a,'access_digest');c['accesses'][a['access_id']]=clone(a)
def bind(a,e,u,c):
    if e is not None:assessment_store(e,c);a['initial_assessment_ref']=M.eref(e);u['protection_assessment_ref']=M.eref(e)
    access_store(a,c);u['gate_access_ref']=M.aref(a);c['use_receipts'][u['permit_id']]=clone(u)
def fixture(kind='cancel',parent=True,origin='manual'):
    owner,permit,_,c,_,_=H.fixture(kind,origin)
    c.update(accesses={},assessments={},assessment_receipts={},revoked_refs=[],hard_protection_reasons=[],
        resource_safety_ref=ref('resource.safety'),gate_safety_ref=ref('gate.safety'),resource_ref=ref('resources'),
        ordinary_ready=kind=='ordinary',policy=dict(ref=ref('policy'),approved=True,allowed_parent_states=['active','unknown','unresolved']),
        ordinary_closed=True,ordinary_closure_ref=ref('ordinary.closure'),all_closed=False,use_receipts={},
        policy_deadline_tick_ns=80,resource_deadline_tick_ns=70,access_deadline_tick_ns=80)
    common=dict(binding=c['binding'],control_authority_ref=owner['control_authority_ref'],control_epoch=owner['control_epoch'],
        effective_version=owner['effective_version'],authorization_ref=c['authorization_ref'],resource_safety_ref=c['resource_safety_ref'],gate_safety_ref=c['gate_safety_ref'])
    p=dict(identity=owner['identity'],policy_ref=c['policy']['ref'],ordinary_closure_ref=c['ordinary_closure_ref'],
        hold_ref=owner['hold_ref'],ownership_ref=permit['ownership_ref'])
    risks=[dict(hold_ref=owner['hold_ref'],ownership_ref=permit['ownership_ref'],command_ref=owner['identity']['command_ref'],
        execution_ref=owner['identity']['execution_ref'],classification='active')]
    if kind=='cancel' and parent:
        po,_,_,pc,_,_=H.fixture()
        po.update(ownership_id='parent.owner',hold_ref=ref('parent.hold'),control_authority_ref=ref('old.authority'),
            control_epoch='old.epoch',effective_version='1',source_receipt_ref=ref('parent.provider'))
        po['identity']['requester']['principal_id']='alice';O.seal(po,'ownership_digest')
        c['executions'][po['identity']['source_ref']['id']]=clone(po['identity']);c['ownerships']['parent.hold']=clone(po)
        c['ownership_receipts']['parent.provider']=dict(ref=po['source_receipt_ref'],content={k:clone(po[k]) for k in H.OWNER_FIELDS})
        risks.append(dict(hold_ref=po['hold_ref'],ownership_ref=O.reference(po,'ownership_id','ownership_digest'),
            command_ref=po['identity']['command_ref'],execution_ref=None,classification='unknown'))
    risks.sort(key=lambda r:r['hold_ref']['id']);c['risk_observations']=clone(risks);c['risk_hold_ids']=[r['hold_ref']['id'] for r in risks]
    a=dict(format_version='gate-access/0.1.0-draft.1',access_id='access.'+kind,revision='1',purpose='ordinary' if kind=='ordinary' else 'cancel_only',
        **common,protection=p if kind=='cancel' else None,initial_assessment_ref=None,selected_tick_ns='51',expires_tick_ns='80')
    e=None if kind=='ordinary' else dict(format_version='protection-assessment/0.1.0-draft.1',assessment_id='assessment',revision='1',
        **common,protection=p,resource_ref=c['resource_ref'],risks=risks,sampled_tick_ns='51',expires_tick_ns='70',provider_receipt_ref=ref('assessment.provider'))
    c['approved_protection']=clone(p)
    u=dict(permit_id='permit',kind=kind,gate_access_ref=ref('placeholder'),identity=owner['identity'],ownership_ref=permit['ownership_ref'],
        guard_ref=ref('guard'),protection_assessment_ref=None,selected_tick_ns='52',expires_tick_ns='69')
    bind(a,e,u,c);return clone([a,e,u,c])
def old_frames():
    script="import sys,json;sys.path.insert(0,sys.argv[1]);import check_contracts as C;x=C.fixture();print(json.dumps(dict(frames=x[5],inputs=[str(p) for p in C.all_inputs(x[-1])])) )"
    data=json.loads(subprocess.check_output([sys.executable,'-c',script,str(HERE.parent/'df03-service')],cwd=ROOT))
    return list(data['frames'].values()),[Path(p) for p in data['inputs']]
def input_paths(inherited):return list(dict.fromkeys(H.INPUTS+inherited+[HERE/n for n in LOCAL]))
def upgrade_frames(frames):
    a,e,u,c=fixture();oa,_,ou,_=fixture('ordinary')
    # 原46帧仅结构回归：显式识别线上对象的必需身份，不声称其合成业务来源已互相绑定。
    def visit(v):
        if isinstance(v,list):
            for x in v:visit(x)
        elif isinstance(v,dict):
            if {'permit_id','attempt_id','dispatch_intent_id','transmission','budget_revision'}<=set(v):v.update(gate_access_ref=M.aref(oa),ownership_ref=ou['ownership_ref'])
            if {'guard_id','permit_id','command_id','capacity_reservation_id'}<=set(v):
                v.update(gate_access_ref=M.aref(oa),ownership_ref=ou['ownership_ref']);O.seal(v,'guard_digest')
            if {'execution_ref','protected_hold_ref','guard_id'}<=set(v):
                v.update(gate_access_ref=M.aref(a),ownership_ref=u['ownership_ref'],protection_assessment_ref=M.eref(e));O.seal(v,'guard_digest')
            if {'transmission_id','primitive_id','permit_id','guard_ref'}<=set(v):v.update(gate_access_ref=M.aref(a),ownership_ref=u['ownership_ref'],protection_assessment_ref=M.eref(e))
            for x in list(v.values()):visit(x)
    for f in frames:
        f['ipc_version']=G.VERSION;b=f['body'];t=f['type']
        if t=='HELLO':b['supported_ipc_versions']=[G.VERSION];b['supported_features']+=G.FEATURES
        if t=='HELLO_ACK':b['selected_ipc_version']=G.VERSION;b['selected_features']+=G.FEATURES
        if t=='OPEN_GATE':b.update(gate_access=oa,protection_assessment=None)
        if t=='OPEN_GATE_ACK':b['gate_access_ref']=M.aref(oa)
        if t=='GUARD_ACK':b.update(gate_access_ref=M.aref(oa),ownership_ref=ou['ownership_ref'])
        if t=='CANCEL_GUARD':b['protection_assessment']=e
        if t=='CANCEL_GUARD_ACK':b.update(gate_access_ref=M.aref(a),ownership_ref=u['ownership_ref'],protection_assessment_ref=M.eref(e))
        visit(f)
    return frames
def run(frames):
    schemas=G.build();results=[]
    def check(name,observed,expected):
        assert observed==expected,(name,observed,expected)
        results.append(dict(name=name,observed=copy.deepcopy(observed),expected=copy.deepcopy(expected)))
    for n,s in schemas.items():check('生成:'+n,(HERE/n).read_bytes()==G.encoded(s),True);Draft202012Validator.check_schema(s)
    s=schemas['scoped-gate.schema.json'];ipc=schemas['scoped-gate-ipc.schema.json'];iv=Draft202012Validator(ipc)
    def valid(n,v):return Draft202012Validator({'$defs':s['$defs'],'$ref':'#/$defs/'+n}).is_valid(v)
    def evaluate(x,now=53):
        a,e,u,c=x
        if not valid('GateAccess',a) or not valid('GateUse',u) or (e is not None and not valid('ProtectionAssessment',e)):return 'schema'
        return M.use_error(a,u,e,c,now)
    for kind in ('ordinary','cancel'):
        x=fixture(kind);a,e,u,c=x
        check(kind+'开闸子检查',M.open_error(a,e,c,53),None);check(kind+'发送范围子检查',evaluate(x),None)
        check(kind+'根拒绝',Draft202012Validator(s).is_valid(a),False)
        for n,v in [('GateAccess',a),('GateUse',u)]+([('ProtectionAssessment',e)] if e else []):
            check(kind+n+'正例',valid(n,v),True)
            for key in v:
                bad=clone(v);del bad[key];check(kind+n+'缺字段:'+key,valid(n,bad),False)
            bad=clone(v);bad['extra']=True;check(kind+n+'额外字段',valid(n,bad),False)
    check('父未发无需普通hold',evaluate(fixture(parent=False)),None)
    a,e,u,c=fixture();e['sampled_tick_ns']='49';bind(a,e,u,c)
    check('先采样再选择开放计划',M.open_error(a,e,c,53),None)
    a,e,u,c=fixture();e['sampled_tick_ns']='52';bind(a,e,u,c)
    check('计划不得引用选择后才采样的初始评估',M.open_error(a,e,c,53),'assessment_after_selection')
    for kind in ('ordinary','cancel'):
        x=fixture(kind,origin='automation');check(kind+'服务主体独立资格',evaluate(x),None)
        check(kind+'服务来源开闸',M.open_error(x[0],x[1],x[3],53),None)
    x=fixture();check('父保持unknown',x[1]['risks'][1]['classification'],'unknown')
    check('父原owner仍alice',x[3]['ownerships']['parent.hold']['identity']['requester']['principal_id'],'alice')
    check('取消可用不改普通ready',x[3]['ordinary_ready'],False)
    def case(name,mutate,expected,now=53):
        x=fixture();mutate(*x);check(name,evaluate(x,now),expected)
    case('借普通范围',lambda a,e,u,c:u.update(kind='ordinary',identity=fixture('ordinary')[2]['identity'],protection_assessment_ref=None),'use_kind')
    for k in fixture()[0]['binding']:
        case('错域:'+k,lambda a,e,u,c,k=k:c['binding'].update({k:None}),'binding')
    for k in ('authorization_ref','resource_safety_ref','gate_safety_ref'):
        case('换代:'+k,lambda a,e,u,c,k=k:c.update({k:ref('new')}),'current_generation')
    case('接管pending',lambda a,e,u,c:c['control_projection'].update(pending_operation_id='takeover'),'pending_control')
    case('控制世代变化',lambda a,e,u,c:c['control_projection'].update(control_epoch='new'),'control')
    case('Requester issuer_epoch变化',lambda a,e,u,c:c['control_projection']['holder'].update(issuer_epoch='other'),'manual_holder')
    for reason in ('storage','runtime','authorization','time','unrelated_resource'):
        case('硬保护:'+reason,lambda a,e,u,c,r=reason:c['hard_protection_reasons'].append(r),'hard_protection')
    for field in ('policy_ref','ordinary_closure_ref','ownership_ref'):
        case('原件撤回:'+field,lambda a,e,u,c,f=field:c['revoked_refs'].append(a['protection'][f]),'revoked')
    case('初始评估撤回',lambda a,e,u,c:c['revoked_refs'].append(a['initial_assessment_ref']),'revoked')
    case('Guard撤回',lambda a,e,u,c:c['revoked_refs'].append(u['guard_ref']),'revoked')
    case('all关闭',lambda a,e,u,c:c.update(all_closed=True),'closure')
    case('ordinary未关闭',lambda a,e,u,c:c.update(ordinary_closed=False),'closure')
    case('政策未批准',lambda a,e,u,c:c['policy'].update(approved=False),'policy')
    case('政策不允许unknown',lambda a,e,u,c:c['policy'].update(allowed_parent_states=['active']),'parent_policy')
    case('缺真实风险',lambda a,e,u,c:c['risk_hold_ids'].append('hidden'),'risk_set')
    case('旧资源快照',lambda a,e,u,c:c.update(resource_ref=ref('new')),'stale_assessment')
    case('期限等号',lambda *args:None,'use_expired',now=69)
    case('Access期限等号',lambda *args:None,'access_expired',now=80)
    case('提前使用',lambda *args:None,'use_expired',now=51)
    case('越原政策期限',lambda a,e,u,c:c.update(policy_deadline_tick_ns=79),'provider_deadline')
    case('改评估重算摘要但无原件',lambda a,e,u,c:(e.update(resource_ref=ref('fake')),O.seal(e,'assessment_digest'),u.update(protection_assessment_ref=M.eref(e)),c['use_receipts'].update(permit=clone(u))),'assessment_source')
    case('改风险分类并重绑摘要但权威仍unknown',lambda a,e,u,c:(e['risks'][1].update(classification='active'),bind(a,e,u,c)),'risk_source')
    case('原件回执不符',lambda a,e,u,c:c['assessment_receipts'].clear(),'assessment_receipt')
    def parent_change(a,e,u,c,other_cancel=False):
        owner=c['ownerships']['parent.hold'];identity=owner['identity']
        if other_cancel:
            identity.update(kind='cancel',attempt_ref=None,cancellation_ref=ref('another.cancel'),execution_ref=ref('another.execution'))
        else:identity['command_ref']=ref('unrelated.command')
        c['executions'][identity['source_ref']['id']]=clone(identity);O.seal(owner,'ownership_digest')
        c['ownership_receipts']['parent.provider']['content']={k:clone(owner[k]) for k in H.OWNER_FIELDS}
        risk=e['risks'][1];risk.update(ownership_ref=O.reference(owner,'ownership_id','ownership_digest'),command_ref=identity['command_ref'],execution_ref=identity['execution_ref'])
        c['risk_observations']=clone(e['risks']);bind(a,e,u,c)
    case('真实无关命令风险不可豁免',parent_change,'unrelated_risk')
    case('同父另一个取消也不可豁免',lambda *x:parent_change(*x,other_cancel=True),'unrelated_risk')
    case('真实风险重复即使摘要更新',lambda a,e,u,c:(e['risks'].append(clone(e['risks'][0])),bind(a,e,u,c)),'risk_set')
    case('独立hold不是active',lambda a,e,u,c:(e['risks'][0].update(classification='unknown'),c.update(risk_observations=clone(e['risks'])),bind(a,e,u,c)),'protected_hold')
    case('冒用父actor',lambda a,e,u,c:(u['identity']['requester'].update(principal_id='alice'),c['use_receipts'].update(permit=clone(u))),'ownership_execution')
    case('更换唯一执行并重绑摘要',lambda a,e,u,c:(a['protection']['identity'].update(execution_ref=ref('another')),access_store(a,c),u.update(gate_access_ref=M.aref(a))),'use_source')
    # 完整当前快照更新：父风险释放保留旧原件，不沿用初始资源全集。
    a,e,u,c=fixture();old=clone(e);e['assessment_id']='assessment.next';e['provider_receipt_ref']=ref('assessment.next.provider')
    e.update(resource_ref=ref('resources',2),sampled_tick_ns='54',risks=e['risks'][:1]);c.update(resource_ref=e['resource_ref'],risk_observations=clone(e['risks']),risk_hold_ids=['hold'])
    assessment_store(e,c);u.update(protection_assessment_ref=M.eref(e),selected_tick_ns='54');c['use_receipts']['permit']=clone(u)
    check('同范围新评估允许正常父释放',M.use_error(a,u,e,c,55),None)
    check('初始证明仍为历史Ref',a['initial_assessment_ref']==M.eref(old),True)
    check('初始证明不能重作当前评估',M.assessment_error(a,old,c,55),'stale_assessment')
    c['revoked_refs'].append(M.eref(old));check('新评估不复活已撤初始证明',M.use_error(a,u,e,c,55),'revoked')
    # 真来源若被整体伪造，合成模型不能提供外部信任。
    check('全部可信前提由夹具提供的限制反证',evaluate(fixture()),None)
    for value in ('01','-1','1\n',1,str(10**20)):
        a,_,_,_=fixture();a['selected_tick_ns']=value;check('严格计数:'+repr(value),valid('GateAccess',a),False)
    a,e,u,c=fixture();sample=clone(e['risks'][0]);e['risks']=[]
    for i in range(257):
        item=clone(sample);item['hold_ref']=ref('hold.'+str(i));e['risks'].append(item)
    check('256风险结构边界',valid('ProtectionAssessment',{**e,'risks':e['risks'][:256]}),True)
    check('257风险不能截断',valid('ProtectionAssessment',e),False)
    check('完整旧帧数量',len(frames),46)
    upgraded=upgrade_frames(clone(frames));check('类型全集未丢',sorted(f['type'] for f in frames),sorted(f['type'] for f in upgraded))
    for f in upgraded:
        check('IPC正例:'+f['type'],iv.is_valid(f),True)
        bad=clone(f);bad['ipc_version']='ipc/0.8.0-reference-time-draft.1';check('拒旧版本:'+f['type'],iv.is_valid(bad),False)
    by={f['type']:f for f in upgraded}
    for t,k in [('HELLO','supported_features'),('HELLO_ACK','selected_features')]:
        for feature in G.FEATURES:
            bad=clone(by[t]);bad['body'][k].remove(feature);check(t+'必选:'+feature,iv.is_valid(bad),False)
    for t,path in [('OPEN_GATE',['gate_access']),('OPEN_GATE_ACK',['gate_access_ref']),('GUARD_INSTALL',['guard','ownership_ref']),
        ('GUARD_ACK',['gate_access_ref']),('DISPATCH',['permit','gate_access_ref']),('RESEND_DISPATCH',['permit','ownership_ref']),
        ('CANCEL_GUARD',['guard','protection_assessment_ref']),('CANCEL_GUARD_ACK',['ownership_ref']),('DISPATCH_CANCEL',['permit','gate_access_ref']),
        ('CANCEL_SEND_REPORT',['transmission','ownership_ref'])]:
        bad=clone(by[t]);node=bad['body']
        for k in path[:-1]:node=node[k]
        del node[path[-1]];check('IPC缺新绑定:'+t,iv.is_valid(bad),False)
    f=clone(by['OPEN_GATE']);a,e,_,_=fixture();f['body'].update(gate_access=a,protection_assessment=e);check('取消范围OPEN结构',iv.is_valid(f),True)
    f['body']['protection_assessment']=None;check('取消OPEN不得省评估',iv.is_valid(f),False)
    f=clone(by['OPEN_GATE']);f['body']['protection_assessment']=e;check('普通OPEN不夹取消评估',iv.is_valid(f),False)
    # 真实新增字段的ACK关联：旧快照内容继续作为独立既有检查的输入，不伪称全Guard验证。
    def ack_pair():
        a,e,u,c=fixture();q=clone(by['OPEN_GATE']);r=clone(by['OPEN_GATE_ACK'])
        for k in O.FRAME_BINDING:q[k]=c['binding'][k];r[k]=c['binding'][k]
        q['body'].update(gate_access=a,protection_assessment=e,device_session_id=c['binding']['device_session_id'],
            clock_domain_id=c['binding']['clock_domain_id'],descriptor_digest=c['binding']['descriptor_digest'],
            control_epoch=a['control_epoch'],control_version=a['effective_version'],lease_until_tick_ns='80')
        r['reply_to']=q['message_id'];r['body'].update(gate_access_ref=M.aref(a),gate_token=q['body']['gate_token'],gate_revision=q['body']['gate_revision'])
        return q,r,c
    q,r,c=ack_pair();check('ACK投影正例',M.open_ack_error(q,r,c,53),None)
    for field in O.FRAME_BINDING:
        q,r,c=ack_pair();r[field]='wrong';check('ACK错会话:'+field,M.open_ack_error(q,r,c,53),'frame_binding')
    for field,expected in [('gate_access_ref','ack_access'),('gate_token','ack_gate'),('gate_revision','ack_gate')]:
        q,r,c=ack_pair();r['body'][field]=ref('wrong') if field.endswith('_ref') else 'wrong';check('ACK错引用:'+field,M.open_ack_error(q,r,c,53),expected)
    q,r,c=ack_pair();r['reply_to']='wrong';check('ACK错请求',M.open_ack_error(q,r,c,53),'reply')
    q,r,c=ack_pair();q['body']['lease_until_tick_ns']='79';check('Scope不能长于原OPEN租约',M.open_ack_error(q,r,c,53),'open_lease')
    q,r,c=ack_pair();q['body']['control_version']='3';check('OPEN控制绑定不能不同',M.open_ack_error(q,r,c,53),'body_binding')
    q,r,c=ack_pair();c['all_closed']=True;check('all后迟到ACK不得采用',M.open_ack_error(q,r,c,53),'closure')
    # 所有新生成引用均本地可解，不访问网络。
    def refs(v):
        if isinstance(v,list):return [r for x in v for r in refs(x)]
        if not isinstance(v,dict):return []
        return ([v['$ref']] if '$ref' in v else [])+[r for k,x in v.items() if k not in ('$ref','const','enum','default','examples') for r in refs(x)]
    check('IPC所有引用本地存在',all(r.startswith('#/$defs/') and r.split('/')[-1] in ipc['$defs'] for r in refs(ipc)),True)
    results+=traces()
    return results
def traces():
    results=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected);results.append(dict(name=name,observed=clone(actual),expected=clone(expected)))
    def opened():
        a,e,u,c=fixture();g=M.Gate(c['binding']);b=c['binding']
        assert g.fence(1,b,1,'barrier')=='fenced';assert g.open(2,b,1,'barrier','token',a,e,c,53)=='opened'
        return g,a,e,u,c,b
    g,a,e,u,c,b=opened();check('取消可消费',g.dispatch(3,b,1,'token',u,e,c,54,True),'consumed_before_io')
    check('同许可不重复副作用',g.dispatch(4,b,1,'token',u,e,c,54,True),'cached_permit');check('副作用一次',g.effects,['permit'])
    u['permit_id']='resend';u['guard_ref']=ref('new.guard');c['use_receipts']['resend']=clone(u)
    check('新许可另验范围及完整Guard前提',g.dispatch(5,b,1,'token',u,e,c,55,True),'consumed_before_io')
    g,a,e,u,c,b=opened();check('完整Guard否决仍拒发',g.dispatch(3,b,1,'token',u,e,c,54,False),'complete_guard_rejected');check('无消费',g.effects,[])
    g,a,e,u,c,b=opened();check('关闭',g.close(3,b,'close',{'reason':'takeover'}),'closed')
    check('关闭后重投OPEN只回历史',g.open(4,b,1,'barrier','token',a,e,c,55),'cached_open_ack')
    check('历史OPEN不复活',g.dispatch(5,b,1,'token',u,e,c,55,True),'closed')
    check('新屏障',g.fence(6,b,2,'next'),'fenced');a['access_id']='access.next';bind(a,e,u,c)
    check('新范围不可复用token',g.open(7,b,2,'next','token',a,e,c,55),'token_reuse')
    check('新token可开放',g.open(8,b,2,'next','new.token',a,e,c,55),'opened')
    check('旧关闭重复只回历史',g.close(9,b,'close',{'reason':'takeover'}),'cached_close_ack')
    check('旧关闭不关闭新资格',g.active['access_id'],'access.next')
    g,a,e,u,c,b=opened();oa,oe,ou,oc=fixture('ordinary')
    check('原地扩大为普通拒绝',g.open(3,b,1,'barrier','token.other',oa,oe,oc,54),'scope_switch_requires_fence')
    check('取消闸拒普通许可',g.dispatch(4,b,1,'token',ou,None,oc,54,True),'access_source')
    g,a,e,u,c,b=opened();check('序号缺口',g.dispatch(4,b,1,'token',u,e,c,54,True),'session_or_sequence');check('旧会话不复活',g.fence(3,b,2,'new'),'dead_session')
    g,a,e,u,c,b=opened();check('期限边界拒发',g.dispatch(3,b,1,'token',u,e,c,69,True),'use_expired');check('期限失效撤当前范围',g.active,None)
    g,a,e,u,c,b=opened();c['all_closed']=True;check('all关闭拒发',g.dispatch(3,b,1,'token',u,e,c,54,True),'closure')
    g,a,e,u,c,b=opened();check('已入流前缀先执行',g.dispatch(3,b,1,'token',u,e,c,54,True),'consumed_before_io')
    check('后到关闭',g.close(4,b,'c',{}),'closed');check('关闭不回滚已执行',g.effects,['permit'])
    g,a,e,u,c,b=opened();c['control_projection']['pending_operation_id']='takeover';check('接管后旧候选拒发',g.dispatch(3,b,1,'token',u,e,c,54,True),'pending_control')
    g,a,e,u,c,b=opened();g.dispatch(3,b,1,'token',u,e,c,54,True);u['guard_ref']=ref('different')
    check('同ID不同许可关闭会话',g.dispatch(4,b,1,'token',u,e,c,55,True),'permit_conflict');check('冲突关会话',g.alive,False)
    a,e,u,c=fixture();g=M.Gate(c['binding']);b=clone(c['binding']);g.fence(1,b,1,'barrier')
    c['binding']['writer_exit_id']='other';a['binding']=clone(c['binding']);e['binding']=clone(c['binding']);bind(a,e,u,c)
    check('不能给当前worker安装其他出口范围',g.open(2,b,1,'barrier','token',a,e,c,53),'access_exit')
    g,a,e,u,c,b=opened();a['expires_tick_ns']='79';bind(a,e,u,c)
    check('同Access身份换内容终止会话',g.open(3,b,1,'barrier','token',a,e,c,54),'open_conflict')
    g=M.Gate(b);check('重启默认关闭不重发',g.dispatch(1,b,1,'token',u,e,c,54,True),'closed')
    return results
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    target=HERE/'scoped-gate-report.json'
    if a.check_report:
        read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        data=json.loads(read(target));_,inherited=old_frames()
        assert set(data['inputs'])=={f.relative_to(ROOT).as_posix() for f in input_paths(inherited)}
        for name,digest in data['inputs'].items():
            f=ROOT/name;assert f.resolve().is_relative_to(ROOT.resolve())
            assert hashlib.sha256(read(f)).hexdigest()==digest,name
        print(json.dumps(dict(all_passed=True,matched_bindings=len(data['inputs']))))
    else:
        frames,inherited=old_frames();checks=run(frames);inputs=input_paths(inherited)
        data=dict(all_passed=True,approved=False,cases_passed=len(checks),ipc_frame_types=46,scope='范围关联及有限单设备闸；旧帧仅形状回归',
            runtime_tests_executed=0,device_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,sqlite_tests_executed=0,
            checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs})
        if a.report:target.write_bytes(G.encoded(data))
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
