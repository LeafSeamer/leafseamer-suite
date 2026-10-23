"""控制权HTTP及有限状态参考检查；所有权威前提人工给定。"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from openapi_spec_validator import validate_spec
import build_control_authority as G
import control_authority_model as M
HERE=G.HERE;ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('CONTROL_AUTHORITY.md','build_control_authority.py','control_authority_model.py','check_control_authority.py',
 'control-authority.schema.json','control-authority.openapi.json','OPEN_PLAN.md')]+[ROOT/n for n in
 ('docs/rebirth-f02-f03-design.md','docs/rebirth-df04-storage-design.md','docs/rebirth-c10-gui-design.md',
  'docs/contracts/draft4/first-loop.schema.json','docs/contracts/draft4/controller.openapi.json','docs/contracts/df01-source/authorization-candidate.json')]
def principal(name):return dict(issuer_id='issuer',issuer_epoch='issuer.epoch',principal_id=name)
def fixture(actor='a'):
 scope=dict(authority_service_id='controller',database_instance_id='database')
 domain=dict(clock_domain_id='clock_1',descriptor_digest=M.digest('descriptor'))
 record=M.sealed(dict(record_id='control.device',scope=scope,device_id='device',revision='1',control_epoch='epoch',effective_version='1',
  reserved_version='1',holder=principal('a'),mode='manual',pending_change=None,gate_state='protected',in_flight_command_ids=[],unresolved_command_ids=[]),'record_digest')
 store=dict(record=record,control_history={'1':copy.deepcopy(record)},offers={},operations={},requests={},latest_attempt={},attempt_history=[],barrier_intents=[],journal=[],audit=[],outbox=[])
 c=dict(actor=principal(actor),scope=scope,device_id='device',request_epoch='request.epoch',now=100,domain=domain,
  authenticated=True,human=True,read_allowed=True,write_allowed=True,origin_valid=True,csrf_valid=True,namespace_open=True,context_current=True,
  storage_healthy=True,domain_current=True,force_allowed=True,target_authorized=True,from_authorized=True)
 return json.loads(json.dumps([store,c]))
def body(key='key',**extra):return dict(context_id='context',idempotency_key=key,expected_control={'epoch':'epoch','version':'1'},reason='交接',**extra)
def offer():
 s,c=fixture();s,r=M.invoke(s,'offerTransfer',body(target_principal=principal('b'),offer_ttl_ms=100),c)
 return s,r,r['initial_result_ref']['id']
def accepted():
 s,receipt,tid=offer();_,c=fixture('b');s,r=M.invoke(s,'acceptTransfer',body('accept'),c,tid)
 return s,r,tid,r['initial_result_ref']['id']
def evidence(s,oid):
 op=s['operations'][oid];r=s['record']
 return dict(storage_healthy=True,target_authorized=True,authorized_principal=op['target']['holder'] or op['requester'],barrier_verified=True,rejection_verified=True,
  barrier=dict(operation_id=oid,scope=r['scope'],device_id=r['device_id'],control_epoch=r['control_epoch'],target_version=op['target']['version'],
   attempt_id=s['latest_attempt'][oid],selection_ref=dict(id='selection',revision='1',digest=M.digest('selection'))))
def run():
 for name,data in G.encoded().items():assert (HERE/name).read_bytes()==data,'生成漂移'
 schema=G.schema();api=G.build()['control-authority.openapi.json'];Draft202012Validator.check_schema(schema);validate_spec(api)
 registry=Registry().with_resource(G.SID,Resource.from_contents(schema));checks=[]
 def check(name,actual,expected=True):
  assert actual==expected,(name,actual,expected)
  if len(json.dumps([actual,expected],ensure_ascii=False))>512:
   checks.append(dict(name=name,comparison='完整对象等价',expected=True,observed=actual==expected))
  else:checks.append(dict(name=name,expected=copy.deepcopy(expected),observed=copy.deepcopy(actual)))
 def valid(name,value):return Draft202012Validator({'$ref':G.SID+'#/$defs/'+name},registry=registry).is_valid(value)
 def denied(name,fn,code):
  try:fn()
  except M.Rejected as e:check(name,str(e),code)
  else:raise AssertionError(name+': 未拒绝')
 def outputs(s):
  check('控制结构:'+s['record']['revision'],valid('ControlRecord',s['record']))
  for o in s['offers'].values():check('邀请结构:'+o['state'],valid('TransferOffer',o))
  for o in s['operations'].values():check('操作结构:'+o['state'],valid('ControlOperation',o))
  for r in s['requests'].values():check('裁决结构',valid('RequestReceipt',r))
 s,c=fixture();before=copy.deepcopy(s);s,receipt,tid=offer();outputs(s)
 check('邀请不改控制权或关闸',s['record'],before['record'])
 s,receipt,tid,oid=accepted();outputs(s)
 check('accepted不是effective',[s['offers'][tid]['state'],s['operations'][oid]['state'],s['record']['holder']['principal_id'],s['record']['gate_state']],['accepted','pending','a','fencing'])
 check('预留版本独立于生效',[s['record']['effective_version'],s['record']['reserved_version']],['1','2'])
 _,b=fixture('b');again,rr=M.invoke(s,'acceptTransfer',body('accept'),b,tid);check('同键只查原裁决',[again,rr],[s,receipt])
 changed=body('accept');changed['reason']='不同内容';denied('同键异内容',lambda:M.invoke(s,'acceptTransfer',changed,b,tid),'identity_conflict')
 b['csrf_valid']=False;denied('查原不免CSRF',lambda:M.invoke(s,'acceptTransfer',body('accept'),b,tid),'request_origin')
 _,b=fixture('b');b['context_current']=False;b['namespace_open']=False;b['write_allowed']=False
 check('当前可读时旧结果先于新写门控',M.invoke(s,'acceptTransfer',body('accept'),b,tid)[1],receipt)
 b['read_allowed']=False;denied('旧裁决仍需当前读取权',lambda:M.invoke(s,'acceptTransfer',body('accept'),b,tid),'identity')
 _,b=fixture('b');denied('另一键不创建第二pending',lambda:M.invoke(s,'acceptTransfer',body('other'),b,tid),'control_busy')
 _,other=fixture('c');denied('紧急接管不越未决槽',lambda:M.invoke(s,'acquireControl',body(force=True),other),'control_busy')
 context=evidence(s,oid)
 final,result=M.settle(s,oid,context);outputs(final)
 check('T4只生效不ready',[result['state'],final['record']['holder']['principal_id'],final['record']['gate_state']],['effective','b','protected'])
 check('生效历史Ref精确',result['effective_control_ref'],M.ref(final['record'],'record_id','record_digest'))
 check('生效完整历史持久映射',final['control_history'][result['effective_control_ref']['revision']],final['record'])
 check('初始裁决不随操作修订改变',M.invoke(final,'acceptTransfer',body('accept'),b,tid)[1],receipt)
 check('接受后TTL不改邀请',M.expire_offers(final,b['domain'],10**12)['offers'][tid]['state'],'accepted')
 denied('effective不二次转交',lambda:M.settle(final,oid,context),'terminal')
 uncertain,_=M.settle(s,oid,context,uncertain=True);outputs(uncertain)
 check('未知保留pending和版本',[uncertain['record']['pending_change']['operation_id'],uncertain['record']['reserved_version'],uncertain['record']['gate_state']],[oid,'2','protected'])
 recovered=M.new_attempt(uncertain,oid,'recovery.2')
 check('恢复不另预留',[recovered['record']['reserved_version'],recovered['operations'][oid]['target']['version']],['2','2'])
 denied('旧尝试不能采用',lambda:M.settle(recovered,oid,context),'barrier_binding')
 denied('历史attempt不得复用',lambda:M.new_attempt(recovered,oid,s['latest_attempt'][oid]),'attempt_reuse')
 check('新完整尝试核对未知',M.settle(recovered,oid,evidence(recovered,oid))[1]['state'],'effective')
 for field,value in [('device_id','other'),('control_epoch','other'),('target_version','3'),('operation_id','other')]:
  bad=copy.deepcopy(context);bad['barrier'][field]=value
  denied('屏障原件错配:'+field,lambda v=bad:M.settle(s,oid,v),'barrier_binding')
 for field in ('target_authorized','storage_healthy','barrier_verified'):
  bad=copy.deepcopy(context);bad[field]=False
  denied('T4缺可信前提:'+field,lambda v=bad:M.settle(s,oid,v),'barrier_unverified' if field=='barrier_verified' else 'unavailable')
 bad=copy.deepcopy(context);bad['authorized_principal']=principal('c');denied('目标权限不能借他人',lambda:M.settle(s,oid,bad),'unavailable')
 rejected,_=M.settle(s,oid,context,reject=True);outputs(rejected)
 check('拒绝不回收版本也不恢复写',[rejected['record']['reserved_version'],rejected['record']['effective_version'],rejected['record']['gate_state'],rejected['record']['pending_change']],['2','1','protected',None])
 nextstate,nextreceipt=M.invoke(rejected,'acquireControl',body('next',force=True),other)
 check('新操作跳过已安装可能版本',nextstate['operations'][nextreceipt['initial_result_ref']['id']]['target']['version'],'3')
 for mutate,code,name in [
  (lambda c:c['actor'].update(issuer_id='other'),'not_target','同名异issuer'),
  (lambda c:c['actor'].update(issuer_epoch='other'),'not_target','同名异issuer代次'),
  (lambda c:c.update(from_authorized=False),'transfer_permission','原持有人撤权'),
  (lambda c:c.update(target_authorized=False),'transfer_permission','接受者撤权'),
  (lambda c:c.update(now=100000100),'offer_expired','TTL等号'),
  (lambda c:c.update(now=99),'offer_expired','创建之前'),
  (lambda c:c['domain'].update(clock_domain_id='other'),'offer_clock','不可比较域')]:
  offered,_,tid=offer();_,ctx=fixture('b');mutate(ctx)
  denied(name,lambda:M.invoke(offered,'acceptTransfer',body('accept'),ctx,tid),code)
 offered,_,tid=offer();_,b=fixture('b');b['now']=100000099
 check('TTL前最后一tick接受',M.invoke(offered,'acceptTransfer',body('accept'),b,tid)[0]['offers'][tid]['state'],'accepted')
 expired=M.expire_offers(offered,b['domain'],100000100);outputs(expired)
 check('邀请到期不释放',expired['record'],offered['record'])
 _,a=fixture();cancel=dict(context_id='context',idempotency_key='cancel',expected_offer=M.ref(offered['offers'][tid],'transfer_id','offer_digest'),reason='取消')
 cancelled,cr=M.invoke(offered,'cancelTransfer',cancel,a,tid);outputs(cancelled)
 check('取消不改持有人',cancelled['record'],offered['record'])
 denied('取消后不能接受',lambda:M.invoke(cancelled,'acceptTransfer',body('accept'),b,tid),'offer_consumed')
 forced,fr=M.invoke(offered,'acquireControl',body('force',force=True),other);foid=fr['initial_result_ref']['id']
 forced,_=M.settle(forced,foid,evidence(forced,foid));b['now']=101
 denied('紧急接管后旧邀请版本拒绝',lambda:M.invoke(forced,'acceptTransfer',body('accept'),b,tid),'control_cas')
 previously_ready=copy.deepcopy(final);previously_ready['record']['gate_state']='ready';M.sealed(previously_ready['record'],'record_digest')
 restart=M.restart(previously_ready,dict(clock_domain_id='new.clock',descriptor_digest=M.digest('new')),0)
 check('普通重启保留控制限制',[restart['record']['holder'],restart['record']['control_epoch'],restart['record']['effective_version']],[principal('b'),'epoch','2'])
 check('普通重启不继承ready',restart['record']['gate_state'],'protected')
 stale=M.restart(offered,dict(clock_domain_id='new.clock',descriptor_digest=M.digest('new')),0)
 check('换域旧邀请不能续期',[stale['offers'][tid]['state'],stale['offers'][tid]['closed_reason']],['expired','clock_domain_changed'])
 _,b=fixture('b');release=body('release');release['expected_control']['version']='2'
 released,rr=M.invoke(final,'releaseControl',release,b);rid=rr['initial_result_ref']['id'];released,_=M.settle(released,rid,evidence(released,rid));outputs(released)
 check('释放仅切automatic仍protected',[released['record']['mode'],released['record']['holder'],released['record']['gate_state']],['automatic',None,'protected'])
 check('后续控制不覆盖旧生效历史',released['control_history'][result['effective_control_ref']['revision']],final['record'])
 for field in ('force_allowed','human'):
  original,ctx=fixture('c');ctx[field]=False
  denied('控制身份限制:'+field,lambda:M.invoke(original,'acquireControl',body(force=True),ctx),'identity' if field=='human' else 'force_required')
 exhausted,ctx=fixture('c');exhausted['record']['reserved_version']=str(M.MAX)
 denied('U20不回绕',lambda:M.invoke(exhausted,'acquireControl',body(force=True),ctx),'counter_exhausted')
 # 每个列出的副本写入边界故障只证明模型回滚，不证明真实SQL写集已齐。
 offered,_,tid=offer();_,b=fixture('b')
 for step in ('reserve','operation','pending','offer','barrier_intent','receipt','audit','outbox','history','commit'):
  before=copy.deepcopy(offered)
  try:M.invoke(offered,'acceptTransfer',body('accept'),b,tid,fault_at=step)
  except M.Injected:check('接受故障副本不泄漏:'+step,offered,before)
  else:raise AssertionError(step)
 for step in ('control','result','audit','outbox','history','commit'):
  before=copy.deepcopy(s)
  try:M.settle(s,oid,context,fault_at=step)
  except M.Injected:check('生效故障副本不泄漏:'+step,s,before)
  else:raise AssertionError(step)
 inputs={'AcquireRequest':body(force=True),'ReleaseRequest':body(),'OfferRequest':body(target_principal=principal('b'),offer_ttl_ms=86400000),
  'AcceptRequest':body(),'CancelRequest':cancel,'LookupRequest':dict(key=receipt['identity']['key'],request_digest=receipt['identity']['request_digest'])}
 for name,value in inputs.items():
  check('输入结构:'+name,valid(name,value));bad=copy.deepcopy(value);bad['durable']=True;check('拒绝自填结果:'+name,valid(name,bad),False)
 check('force缺省允许',valid('AcquireRequest',body()))
 auto,ctx=fixture('b');auto['record']['holder']=None;auto['record']['mode']='automatic';M.sealed(auto['record'],'record_digest')
 first,default_receipt=M.invoke(auto,'acquireControl',body(),ctx)
 check('force缺省false规范身份相同',M.invoke(first,'acquireControl',body(force=False),ctx)[1],default_receipt)
 ctx['force_allowed']=False
 denied('自动模式也不能绕紧急权限',lambda:M.invoke(auto,'acquireControl',body(force=True),ctx),'force_required')
 ctx['force_allowed']=True;empty_reason=body(force=True);empty_reason['reason']='  '
 denied('紧急接管须实质理由',lambda:M.invoke(auto,'acquireControl',empty_reason,ctx),'force_required')
 check('紧急权限元数据',api['paths']['/devices/{device_id}/control/acquire']['post']['x-force-permission'],'control.emergency')
 bad=copy.deepcopy(result);bad['kind']='release';check('释放不得携人工目标',valid('ControlOperation',bad),False)
 for value in ('01','1\n',str(10**20)):
  bad=copy.deepcopy(final['record']);bad['reserved_version']=value;check('严格控制计数:'+repr(value),valid('ControlRecord',bad),False)
 bad=copy.deepcopy(final['offers'][next(iter(final['offers']))]);bad['accepted_operation_id']=None;check('接受必须关联operation',valid('TransferOffer',bad),False)
 check('九接口',[len(G.ROUTES),len({r[2] for r in G.ROUTES})],[9,9])
 old=json.loads((ROOT/'docs/contracts/draft4/controller.openapi.json').read_bytes())
 oldcontrol={(m,p,x['operationId']) for p,v in old['paths'].items() if '/control' in p for m,x in v.items() if isinstance(x,dict) and 'operationId' in x}
 selected={(m,'/api/v1'+p,n) for m,p,n,_,_ in G.ROUTES}
 check('六旧操作完整替换',oldcontrol<=selected);check('三新增操作',len(selected-oldcontrol),3)
 for method,path,name,_,_ in G.ROUTES:
  op=api['paths'][path][method]
  legacy=old['paths'].get('/api/v1'+path,{}).get(method)
  if legacy:check('旧权限保留:'+name,op['x-permission'],legacy['x-permission'])
  check('仅人员主体:'+name,op['x-principal-profiles'],['human'])
  check('版本与身份:'+name,[op['parameters'][0]['schema']['const'],op['security']],[G.VERSION,[{'humanBearer':[],**({'csrf':[]} if method=='post' else {})}]])
  check('全响应禁止缓存:'+name,all(v['headers']['Cache-Control']['schema']['const']=='no-store' for v in op['responses'].values()))
 check('合成屏障前提非真实取证限制',M.settle(s,oid,context)[1]['state'],'effective')
 return checks
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
 if a.staged and not a.check_report:p.error('--staged需配合--check-report')
 path=HERE/'control-authority-report.json'
 if a.check_report:
  read=(lambda f:subprocess.check_output(['git','show',':'+f.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
  report=json.loads(read(path));assert set(report['inputs'])=={f.relative_to(ROOT).as_posix() for f in INPUTS}
  for f in INPUTS:assert report['inputs'][f.relative_to(ROOT).as_posix()]==hashlib.sha256(read(f)).hexdigest()
  print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
 else:
  checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),scope='控制权与转交HTTP及有限状态候选',
   runtime_tests_executed=0,sqlite_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,
   checks=checks,inputs={f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in INPUTS})
  if a.report:path.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
  print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False))
