"""合成权威输入下的结构、跨原件关系与故障顺序；不证明数据库或设备路径。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema.exceptions import ValidationError
import continuation_model as M

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('build_arm_budget.py','build_continuation.py','continuation.schema.json',
    'continuation_model.py','check_continuation.py','CONTINUATION.md')]
INPUTS+=[HERE.parent/'c04-preparation/README.md',HERE.parent/'c04-storage/README.md',
    HERE/'source-resync.sql',HERE/'SOURCE_RESYNC.md']

def scope(name):return dict(authority_service_id=name,database_instance_id=name+'.db')
def ref(name,issuer='seamer'):return dict(scope=scope(issuer),id=name,revision='1',digest=M.digest(name))
def sealed(q):return M.seal(q,'request_digest')

def fixture():
    targets=[]
    for name in ('controller.a','controller.b'):
        targets.append(dict(controller_scope=scope(name),preparation_ref=ref('preparation',name),
            recovery_grant_ref=ref('recovery.grant',name),devices=[dict(device_id='device',
            control_ref=ref('control',name),authorization_ref=ref('authorization',name),action_set_ref=ref('actions',name))]))
    q=sealed(dict(contract_version=M.G.VERSION,origin_scope=scope('seamer'),run_id='run',generation='2',transfer_id='transfer',
        recovery_operation_id='recovery',recovery_execution_id='recovery.execution',continuation_plan_ref=ref('plan'),
        request_epoch='epoch',actor=dict(issuer_id='controller.a',principal_id='operator'),idempotency_key='key',
        approval_ref=ref('approval'),targets=targets))
    s=dict(read_authorized=True,write_authorized=True,binding={k:q[k] for k in
        ('origin_scope','run_id','generation','recovery_operation_id','recovery_execution_id','continuation_plan_ref')},
        required_targets=copy.deepcopy(targets),approval_ref=q['approval_ref'],approval_subject=M.approval_subject(q),
        approval_current=True,approval_human=True,run_state='running',operation_state='reconciling',execution_state='running',
        recovery_steps_complete=True,recovery_resources_clear=True,recovery_lock_held=True,source_current=True,
        time_current=True,budget_reserved=True,pause_latched=False,run_revision='5',slot_revision='3',operation_revision='4')
    receipts=[];controllers={}
    for t in targets:
        name=t['controller_scope']['authority_service_id'];qual=ref('qualification',name);grant_ref=ref('continuation.grant',name)
        r=M.seal(dict(**{k:q[k] for k in M.COMMON},request_digest=q['request_digest'],controller_scope=t['controller_scope'],
            receipt_id='receipt',revision='1',target_digest=M.digest(t),preparation_ref=t['preparation_ref'],
            recovery_grant_ref=t['recovery_grant_ref'],continuation_grant_ref=grant_ref,qualification_ref=qual),'receipt_digest')
        c=dict(scope=t['controller_scope'],origin_scope=q['origin_scope'],run_id=q['run_id'],generation=q['generation'],
            recovery_execution_id=q['recovery_execution_id'],preparation_ref=t['preparation_ref'],recovery_grant_ref=t['recovery_grant_ref'],
            mode='recovery',devices=copy.deepcopy(t['devices']),preparation_state='applied',deny_through_generation='1',closed=False,
            authorization_current=True,automatic_control=True,pending_takeover=False,runtime_current=True,time_current=True,
            capacity_reserved=True,plan_ref=q['continuation_plan_ref'],plan_verified=True,durable_receipt=copy.deepcopy(r),
            qualification_ref=qual,grant=dict(ref=grant_ref,scope='run_generation',request_digest=q['request_digest'],
                target_digest=M.digest(t),plan_ref=q['continuation_plan_ref'],parent_preparation_ref=t['preparation_ref'],activation='adoption_and_r5'),
            write_authorized=True,approval_verified=True,approval_ref=q['approval_ref'],approval_subject=M.approval_subject(q),same_generation_transfer_id=None)
        controllers[M.scope_key(t['controller_scope'])]=c;receipts.append(r)
    a=M.seal(dict(**{k:q[k] for k in M.COMMON},request_digest=q['request_digest'],adoption_id='adoption',revision='1',
        expected_run_revision=s['run_revision'],expected_slot_revision=s['slot_revision'],expected_operation_revision=s['operation_revision'],
        receipt_refs=[M.receipt_ref(r) for r in receipts],release_proof_ref=ref('release','supervisor')),'adoption_digest')
    s['release_proof']=dict(ref=a['release_proof_ref'],operation_id=q['recovery_operation_id'],execution_id=q['recovery_execution_id'],
        request_digest=q['request_digest'],receipt_refs=a['receipt_refs'],resources_clear=True,
        retained_parent_refs=[t['preparation_ref'] for t in targets])
    s.update(adopted=copy.deepcopy(a),adopted_request=copy.deepcopy(q),r5_adoption_digest=a['adoption_digest'],
        armed_generation='2',execution_current=True,plan_current=True)
    command=dict(origin_scope=q['origin_scope'],run_id=q['run_id'],generation='2',plan_ref=q['continuation_plan_ref'],
        execution_id='ordinary.execution',step_verified=True,device_id='device',action_verified=True,parameters_verified=True,
        final_exit_verified=True,continuation_grant_ref=receipts[0]['continuation_grant_ref'],adoption_digest=a['adoption_digest'])
    return q,a,receipts,s,controllers,command

def run():
    checks=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def reject(n,fn):
        try:fn()
        except (ValueError,ValidationError):check(n);return
        raise AssertionError(n+': 应拒绝')
    q,a,rs,s,cs,cmd=fixture();key=M.scope_key(rs[0]['controller_scope']);c=cs[key]
    check('生成字节',(HERE/'continuation.schema.json').read_bytes()==M.G.raw())
    for name,v in [('Request',q),('Receipt',rs[0]),('Adoption',a)]:
        M.validate(name,v);check(name+'正例')
        for field in v:
            bad=copy.deepcopy(v);del bad[field];reject(name+'缺字段'+field,lambda bad=bad:M.validate(name,bad))
        reject(name+'未知字段',lambda:M.validate(name,dict(v,unknown=True)))
        reject(name+'根入口禁止公共误用',lambda v=v:M.Draft202012Validator(M.G.schema()).validate(v))
    M.request_eligible(q,s);check('持续运行审批合格')
    for t,r in zip(q['targets'],rs):
        cc=cs[M.scope_key(t['controller_scope'])]
        check('新签发资格'+t['controller_scope']['authority_service_id'],M.issue_decision(q,t,cc,None,True)=='eligible')
        M.receipt_eligible(q,r,cc);check('独立回执资格'+t['controller_scope']['authority_service_id'])
    M.adoption_eligible(q,a,rs,s,cs);check('完整采用资格')
    M.command_eligible(q,a,rs,c,cmd,s);check('R5后新execution使用新grant的关系正例')
    for field in ('generation',):
        for val in ('0','01','-1','1e2','1\n',2,'1'*21):
            reject('U20拒绝'+repr(val),lambda val=val:M.request_shape(sealed(dict(q,**{field:val}))))
    for val in ('9007199254740993','99999999999999999999'):
        M.request_shape(sealed(dict(q,generation=val)));check('大整数结构精确'+val)
    for field in ('read_authorized','write_authorized','approval_current','approval_human','recovery_steps_complete',
                  'recovery_resources_clear','recovery_lock_held','source_current','time_current','budget_reserved'):
        reject('Seamer门槛'+field,lambda field=field:M.request_eligible(q,dict(s,**{field:False})))
    for field,value in [('pause_latched',True),('run_state','armed'),('operation_state','completed'),('execution_state','succeeded'),
                        ('approval_subject',M.digest('other')),('required_targets',q['targets'][:1])]:
        reject('恢复快照'+field,lambda field=field,value=value:M.request_eligible(q,dict(s,**{field:value})))
    for field in ('origin_scope','run_id','generation','recovery_operation_id','recovery_execution_id','continuation_plan_ref'):
        bad=copy.deepcopy(s);bad['binding'][field]='wrong'
        reject('运行绑定'+field,lambda bad=bad:M.request_eligible(q,bad))
    for field,value in [('authorization_current',False),('automatic_control',False),('pending_takeover',True),('runtime_current',False),
        ('time_current',False),('capacity_reserved',False),('closed',True),('preparation_state','closing'),('deny_through_generation','2'),
        ('plan_verified',False),('mode','arm'),('generation','3'),('recovery_execution_id','other')]:
        bad=dict(c,**{field:value});changed=dict(cs);changed[key]=bad
        reject('签发前失效'+field,lambda bad=bad:M.issue_decision(q,q['targets'][0],bad,None,True))
        reject('采用前失效'+field,lambda changed=changed:M.adoption_eligible(q,a,rs,s,changed))
        reject('R5后失效'+field,lambda bad=bad:M.command_eligible(q,a,rs,bad,cmd,s))
        check('失效后同请求只查历史'+field,M.issue_decision(q,q['targets'][0],bad,{'request':q},True)=='existing')
    reject('查原仍需读取授权',lambda:M.issue_decision(q,q['targets'][0],c,{'request':q},False))
    reject('同代不能换转交身份',lambda:M.issue_decision(q,q['targets'][0],dict(c,same_generation_transfer_id='other'),None,True))
    reject('同身份异内容查原冲突',lambda:M.issue_decision(sealed(dict(q,transfer_id='other')),q['targets'][0],c,{'request':q},True))
    for field in ('write_authorized','approval_verified'):
        reject('Controller签发权限'+field,lambda field=field:M.issue_decision(q,q['targets'][0],dict(c,**{field:False}),None,True))
    for field in ('approval_ref','approval_subject'):
        reject('Controller审批错绑'+field,lambda field=field:M.issue_decision(q,q['targets'][0],dict(c,**{field:None}),None,True))
    for targets in (q['targets'][::-1],q['targets']+[q['targets'][0]]):
        reject('Controller顺序唯一'+str(len(targets)),lambda targets=targets:M.request_shape(sealed(dict(q,targets=targets))))
    bad=copy.deepcopy(q);bad['targets'][0]['devices']*=2
    reject('设备重复',lambda:M.request_shape(sealed(bad)))
    bad=copy.deepcopy(q);bad['targets'][0]['preparation_ref']['scope']=scope('other')
    reject('准备跨库',lambda:M.request_shape(sealed(bad)))
    bad=copy.deepcopy(q)
    for i,t in enumerate(bad['targets']):
        original=t['devices'][0];t['devices']=[dict(original,device_id=f'device.{n:03}') for n in range(129)]
    reject('总设备超过256',lambda:M.request_shape(sealed(bad)))
    bad=copy.deepcopy(q)
    for t in bad['targets']:
        original=t['devices'][0];t['devices']=[copy.deepcopy(dict(original,device_id=f'device.{n:03}')) for n in range(128)]
        for device in t['devices']:
            for name in ('control_ref','authorization_ref','action_set_ref'):
                device[name]['id']='x'*128
                device[name]['scope']=dict(authority_service_id='a'*128,database_instance_id='b'*128)
    require_size=len(M.rfc8785.dumps(sealed(bad)))
    check('超字节夹具仍满足数量和结构上限',require_size>262144 and len(bad['targets'])==2 and
        M.Draft202012Validator({'$ref':'#/$defs/Request','$defs':M.G.schema()['$defs']}).is_valid(sealed(bad)))
    reject('结构合法但正文超过字节上限',lambda:M.validate('Request',sealed(bad)))
    bad=copy.deepcopy(q['targets'][0]);bad['preparation_ref']=ref('other','controller.a')
    reject('签发不得使用请求之外的目标',lambda:M.issue_decision(q,bad,c,None,True))
    for field in ('control_ref','authorization_ref','action_set_ref'):
        cc=copy.deepcopy(c);cc['devices'][0][field]=ref('changed','controller.a')
        reject('设备当前资格改变'+field,lambda cc=cc:M.receipt_eligible(q,rs[0],cc))
    for field,value in [('durable_receipt',None),('qualification_ref',ref('other','controller.a')),
        ('scope',scope('controller.c')),('plan_ref',ref('other')),('origin_scope',scope('other'))]:
        reject('权威原件与签发者'+field,lambda field=field,value=value:M.receipt_eligible(q,rs[0],dict(c,**{field:value})))
    # 语义改动均重新封装摘要；不得仅因为摘要没重算而通过负向测试。
    for field,value in [('target_digest',M.digest('other')),('preparation_ref',ref('other','controller.a')),
        ('request_digest',M.digest('other')),('generation','3'),('continuation_grant_ref',rs[0]['recovery_grant_ref'])]:
        r=M.seal(dict(rs[0],**{field:value}),'receipt_digest');cc=copy.deepcopy(c);cc['durable_receipt']=r
        reject('重摘要回执错配'+field,lambda r=r,cc=cc:M.receipt_eligible(q,r,cc))
    for field in c['grant']:
        cc=copy.deepcopy(c);cc['grant'][field]=None
        reject('真实grant原件错配'+field,lambda cc=cc:M.receipt_eligible(q,rs[0],cc))
    for field in ('expected_run_revision','expected_slot_revision','expected_operation_revision'):
        aa=M.seal(dict(a,**{field:'999'}),'adoption_digest')
        reject('采用CAS'+field,lambda aa=aa:M.adoption_eligible(q,aa,rs,s,cs))
    for values in (rs[:1],rs[::-1],rs+[rs[0]]):
        reject('部分重复乱序回执'+str(len(values)),lambda values=values:M.adoption_eligible(q,a,values,s,cs))
    for field in s['release_proof']:
        ss=copy.deepcopy(s);ss['release_proof'][field]=None
        reject('释放证明错配'+field,lambda ss=ss:M.adoption_eligible(q,a,rs,ss,cs))
    for field,value in [('adopted',None),('adopted_request',None),('r5_adoption_digest',None),('armed_generation','3'),
        ('execution_current',False),('plan_current',False),('source_current',False),('time_current',False),('pause_latched',True)]:
        reject('采用R5及当前执行'+field,lambda field=field,value=value:M.command_eligible(q,a,rs,c,cmd,dict(s,**{field:value})))
    for field,value in [('continuation_grant_ref',rs[0]['recovery_grant_ref']),('adoption_digest',M.digest('other')),
        ('execution_id',q['recovery_execution_id']),('device_id','other'),('generation','1'),('origin_scope',scope('other')),
        ('run_id','other'),('plan_ref',ref('other')),('step_verified',False),('action_verified',False),
        ('parameters_verified',False),('final_exit_verified',False)]:
        reject('新触发拒绝'+field,lambda field=field,value=value:M.command_eligible(q,a,rs,c,dict(cmd,**{field:value}),s))
    check('所有检查未修改权威夹具',fixture()==(q,a,rs,s,cs,cmd))
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'continuation-report.json'
    def read(path):return subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else path.read_bytes()
    bindings={x.relative_to(ROOT).as_posix():hashlib.sha256(read(x)).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(read(target));assert data['inputs']==bindings;print(json.dumps(dict(all_passed=True,matched_bindings=len(bindings))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),sql_tests_executed=0,
            integrated_recovery_trigger_tests_executed=0,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings)
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
