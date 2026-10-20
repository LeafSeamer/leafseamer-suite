"""本地Schema、合成可信上下文、HMAC及内存SQL探针；不创建OS进程。"""
import argparse
import base64
import copy
import hashlib
import hmac
import json
import sqlite3
import subprocess
from importlib.metadata import version
from pathlib import Path
import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from build_contracts import HERE,SID,VERSION,BOOT,build,encoded

ROOT=HERE.parents[2]
REPORT=HERE/'reference-report.json'
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','check_contracts.py','journal-probes.sql','supervisor.schema.json','bootstrap.schema.json')]
INPUTS += [HERE.parent/'c09-installation/installation-v02.schema.json',HERE.parent/'draft4/first-loop.schema.json',
    ROOT/'docs/rebirth-df02-runtime-design.md',HERE.parent/'c09-installation/LIFECYCLE_V02.md']
def digest(v): return 'sha256:'+hashlib.sha256(rfc8785.dumps(v)).hexdigest()
def b64(v): return base64.urlsafe_b64encode(v).decode().rstrip('=')
def unb64(v):
    value=base64.urlsafe_b64decode(v+'=')
    if len(value)!=32 or b64(value)!=v: raise ValueError('noncanonical_base64url')
    return value
def change(v,edit):
    v=copy.deepcopy(v);edit(v);return v
def seal(v): v['digest']=digest({k:x for k,x in v.items() if k!='digest'})
def domain(d): return {k:d[k] for k in ('clock_domain_id','descriptor_digest')}


def fixtures():
    descriptor=dict(descriptor_version='clock-domain/1',domain_kind='supervised_runtime',authority_service_id='controller.test',runtime_generation='runtime.test',
        supervisor_instance_id='supervisor.test',clock_backend_id='windows_interrupt_precise',clock_backend_revision='backend.test',tick_unit='ns',suspend_accounting='included',
        namespace_identity='namespace.test',os_boot_identity=dict(status='unavailable'),platform_profile_id='profile.test',platform_profile_revision='1')
    dh=digest(descriptor);descriptor.update(clock_domain_id='clock_'+dh[7:],descriptor_digest=dh)
    scope=dict(service_id='controller.test',database_instance_id='database.test',supervisor_instance_id='supervisor.test',domain_ref=domain(descriptor))
    def named(kind): return dict(kind=kind,authority_service_id=scope['service_id'],database_instance_id=scope['database_instance_id'],object_id=kind+'.test',revision='1',digest=digest(kind))
    binding={k+'_ref':named(k) for k in ('installation','approval','review','role_resolution','configuration','intake','platform_profile')}
    binding.update(host_installation_id='host.test',host_trust_epoch='1',manifest_digest=digest('manifest'),artifact_set_digest=digest('files'),entry_id='worker.test',permissions_digest=digest([]))
    intent=dict(launch_id='launch.test',service_id=scope['service_id'],supervisor_instance_id=scope['supervisor_instance_id'],runtime_generation='runtime.test',member_id='member.test',role='worker',
        artifact_manifest_ref=dict(manifest_id='runtime.manifest',revision='1',digest=digest('runtime')),containment_ref=dict(group_id='group.test',generation='group.generation',backend='windows_job'),
        device_ids=['device.test'],policy_revision='1',extension_binding=binding)
    key=dict(launch_id=intent['launch_id'],launch_intent_digest=digest(intent))
    fence=dict(scope=scope,revision='1',items=[dict(key,disposition='allow')]);seal(fence)
    grant=dict(authorization_ref=named('launch_authorization'),**key,supervisor_instance_id=scope['supervisor_instance_id'],fence_revision='1',
        lifetime=dict(clock=scope['domain_ref'],issued_tick='10',deadline_tick='20'),**{k:binding[k] for k in ('installation_ref','approval_ref','role_resolution_ref','permissions_digest')})
    grant['authorization_ref']['digest']=digest({k:v for k,v in grant.items() if k!='authorization_ref'})
    assignment=dict(bootstrap_version=BOOT,bootstrap_id='bootstrap.test',**key,member_id=intent['member_id'],member_boot_id='boot.test',role='worker',
        clock_domain_descriptor=descriptor,artifact_manifest_ref=intent['artifact_manifest_ref'],channel_binding_id='inherited.channel',challenge_id='challenge.test',
        challenge_nonce=b64(bytes(range(32))),issued_tick_ns='10',expires_tick_ns='20',secret=b64(bytes(range(32,64))))
    proof={k:assignment[k] for k in ('bootstrap_version','bootstrap_id','launch_id','launch_intent_digest','member_id','member_boot_id','role','artifact_manifest_ref','channel_binding_id','challenge_id')}
    proof.update(domain(descriptor));proof['proof']=sign(assignment)
    receipt={k:v for k,v in proof.items() if k not in ('bootstrap_version','challenge_id','clock_domain_id','descriptor_digest','proof')}
    receipt.update(receipt_id='receipt.test',domain_ref=domain(descriptor),containment_ref=intent['containment_ref'],os_observation_ref='observation.test',admitted_tick_ns='15',gate_state='closed')
    retirement=dict(evidence_id='retirement.test',service_id=scope['service_id'],old_domain_ref=domain(descriptor),target_scope='member_group',target_member_ids=[intent['member_id']],
        containment_ref=intent['containment_ref'],launch_intake_closed=True,os_observation_refs=['observation.exit'],result='confirmed_empty',evaluator_domain_ref=domain(descriptor),observed_tick_ns='30')
    view=dict(key=key,supervisor_instance_id=scope['supervisor_instance_id'],state='admitted_closed',creation_attempted=True,admission_receipt=receipt,retirement_evidence=None,gate_state='closed')
    return dict(scope=scope,intent=intent,key=key,fence=fence,grant=grant,assignment=assignment,proof=proof,receipt=receipt,retirement=retirement,view=view)


def transcript(a):
    v={k:x for k,x in a.items() if k not in ('secret','clock_domain_descriptor')}
    v.update(domain(a['clock_domain_descriptor']))
    return b'leafseamer-bootstrap-proof/v1\x00'+rfc8785.dumps(v)
def sign(a): return b64(hmac.new(unb64(a['secret']),transcript(a),hashlib.sha256).digest())


def proof_error(a,p,intent,c):
    # OS及加载权威均为人工前提；摘要重新计算不能替代提供者。
    if not c['peer_instance_valid'] or not c['artifact_valid']: return 'peer_or_artifact'
    if c['used']: return 'already_consumed'
    d=a['clock_domain_descriptor'];dh=digest({k:v for k,v in d.items() if k not in ('clock_domain_id','descriptor_digest')})
    if d['descriptor_digest']!=dh or d['clock_domain_id']!='clock_'+dh[7:] or domain(d)!=c['domain']: return 'domain'
    if (d['authority_service_id'],d['supervisor_instance_id'],d['runtime_generation'])!=(intent['service_id'],intent['supervisor_instance_id'],intent['runtime_generation']): return 'domain_intent'
    if a['launch_intent_digest']!=digest(intent) or any(a[k]!=intent[k] for k in ('launch_id','member_id','role','artifact_manifest_ref')): return 'intent'
    if a['channel_binding_id']!=c['channel'] or a['member_boot_id']!=c['member_boot_id']: return 'instance'
    if not 0<int(a['expires_tick_ns'])-int(a['issued_tick_ns'])<=c['max_age'] or not int(a['issued_tick_ns'])<=c['now']<int(a['expires_tick_ns']): return 'expired'
    for k,v in p.items():
        if k=='proof': continue
        if v!=(d[k] if k in ('clock_domain_id','descriptor_digest') else a[k]): return 'proof_binding'
    return None if hmac.compare_digest(unb64(p['proof']),unb64(sign(a))) else 'hmac'


def fence_error(f,current,scope,live,denied):
    if f['scope']!=scope: return 'scope'
    if f['digest']!=digest({k:v for k,v in f.items() if k!='digest'}): return 'digest'
    ids=[x['launch_id'] for x in f['items']]
    if ids!=sorted(set(ids)): return 'order_or_duplicate'
    by_id={x['launch_id']:x for x in f['items']}
    if any(k not in by_id or by_id[k]['launch_intent_digest']!=v for k,v in live.items()): return 'coverage'
    if any(x['disposition']=='allow' and x['launch_id'] in denied for x in f['items']): return 'denied'
    if current:
        if int(f['revision'])<int(current['revision']): return 'stale'
        if f['revision']==current['revision']: return 'existing' if f['digest']==current['digest'] else 'revision_conflict'
    return 'apply'


def create_error(f,c,state='registered',attempted=False):
    if not c['authenticated_core'] or not c['journal_healthy']: return 'closed'
    if state!='registered' or attempted: return 'query_only'
    if not c['synchronized'] or c['fence']['scope']!=f['scope']: return 'fence'
    if c['fence']['digest']!=digest({k:v for k,v in c['fence'].items() if k!='digest'}): return 'fence'
    if not any(x==dict(f['key'],disposition='allow') for x in c['fence']['items']): return 'fence'
    g=f['grant'];b=f['intent']['extension_binding']
    if g['fence_revision']!=c['fence']['revision'] or any(g[k]!=f['key'][k] for k in f['key']): return 'grant'
    if g['supervisor_instance_id']!=f['scope']['supervisor_instance_id'] or any(g[k]!=b[k] for k in ('installation_ref','approval_ref','role_resolution_ref','permissions_digest')): return 'grant'
    if g['authorization_ref']['digest']!=digest({k:v for k,v in g.items() if k!='authorization_ref'}): return 'grant'
    if (g['authorization_ref']['authority_service_id'],g['authorization_ref']['database_instance_id'])!=(f['scope']['service_id'],f['scope']['database_instance_id']): return 'grant'
    life=g['lifetime']
    if life['clock']!=f['scope']['domain_ref'] or not 0<int(life['deadline_tick'])-int(life['issued_tick'])<=c['max_grant_age'] or not int(life['issued_tick'])<=c['now']<int(life['deadline_tick']): return 'expired'
    if f['key']['launch_intent_digest']!=digest(f['intent']) or not c['current_authority_valid']: return 'authority'
    if c['materialization_key']!=f['key'] or not c['materialization_valid']: return 'materialization'
    return 'mark_before_os_call'


def retirement_error(e,intent,c):
    if e['service_id']!=intent['service_id'] or e['containment_ref']!=intent['containment_ref'] or e['old_domain_ref']!=c['old_domain']: return 'binding'
    if e['target_scope']!='member_group' or e['target_member_ids']!=c['members']: return 'coverage'
    if e['evaluator_domain_ref']!=c['evaluator_domain'] or int(e['observed_tick_ns'])>c['now']: return 'observer'
    if e['result']=='unproven': return 'retain_protection'
    if not e['launch_intake_closed'] or not e['os_observation_refs'] or not all(c[k] for k in ('intake_closed','group_owned','all_exited','endpoints_disposed','members_complete')): return 'unproven'
    return 'retire_only'


def receipt_error(r,a,intent,c):
    if not c['supervisor_authenticated'] or not c['journal_committed'] or not c['approval_current']: return 'authority'
    for k in ('bootstrap_id','launch_id','launch_intent_digest','member_id','member_boot_id','role','artifact_manifest_ref','channel_binding_id'):
        if r[k]!=a[k]: return 'binding'
    if r['launch_intent_digest']!=digest(intent) or r['containment_ref']!=intent['containment_ref'] or r['domain_ref']!=domain(a['clock_domain_descriptor']): return 'intent'
    if r['os_observation_ref']!=c['observation'] or not int(a['issued_tick_ns'])<=int(r['admitted_tick_ns'])<int(a['expires_tick_ns']): return 'observation'
    if c['existing_receipt'] is not None: return 'existing' if r==c['existing_receipt'] else 'receipt_conflict'
    return 'persist_core_binding_closed'


def transport_error(frame,c):
    if not c['authenticated'] or frame['scope']!=c['scope']: return 'peer'
    requests={'FENCE_PUT','LAUNCH_REGISTER','LAUNCH_CREATE','LAUNCH_QUERY','RETIRE_REQUEST'}
    if (frame['type'] in requests)!=(c['sender']=='core'): return 'direction'
    if frame['channel_id']!=c['channel'] or int(frame['sequence'])!=c['next_sequence']: return 'channel_sequence'
    if frame['type'] not in requests:
        pending=c['pending'].get(frame['reply_to'])
        if pending is None or frame['type'] not in (pending['response'],'ERROR'): return 'reply'
        if frame['type']=='LAUNCH_RESULT':
            p=frame['payload'];r=p['record']
            if p['key']!=pending['key'] or (r is not None and (r['key']!=p['key'] or r['supervisor_instance_id']!=c['scope']['supervisor_instance_id'])): return 'result_binding'
    return 'receive'


def sql_checks(check):
    db=sqlite3.connect(':memory:');db.executescript((HERE/'journal-probes.sql').read_text(encoding='utf-8'))
    db.execute('INSERT INTO run VALUES(?,?,?)',('sup',b'{}',1))
    insert="INSERT INTO launch(supervisor_id,launch_id,intent_digest,intent_json,member_id,group_id,group_generation,state,creation_attempted) VALUES('sup',?,?,?,?,?,?,'registered',0)"
    def add(l): db.execute(insert,(l,'hash',b'{}','member.'+l,'group.'+l,'generation'))
    add('one');db.commit()
    def rejected(label,sql,params=()):
        try: db.execute(sql,params)
        except sqlite3.IntegrityError: check('SQL:'+label,True,True)
        else: check('SQL:'+label,False,True)
    rejected('改变意图',"UPDATE launch SET intent_digest='other'")
    rejected('缺少attempt',"UPDATE launch SET state='creating'")
    rejected('跳过bootstrap',"UPDATE launch SET state='admitted_closed',creation_attempted=1")
    rejected('同成员重建',insert,('two','hash',b'{}','member.one','group.two','generation'))
    rejected('同组重建',insert,('two','hash',b'{}','member.two','group.one','generation'))
    db.rollback()
    # 故障切点：事务中标记和恢复预算一起回滚；未调用任何OS接口。
    db.execute("UPDATE launch SET state='creating',creation_attempted=1 WHERE launch_id='one'")
    db.execute("INSERT INTO recovery_attempt VALUES('sup','one',?,?,?)",(b'{}',b'{}','10'))
    db.rollback();check('SQL:创建前提交失败还原',db.execute('SELECT state,creation_attempted FROM launch').fetchone(),('registered',0))
    check('SQL:恢复预算同回滚',db.execute('SELECT count(*) FROM recovery_attempt').fetchone()[0],0)
    db.execute("UPDATE launch SET state='creating',creation_attempted=1 WHERE state='registered' AND creation_attempted=0")
    db.execute("INSERT INTO recovery_attempt VALUES('sup','one',?,?,?)",(b'{}',b'{}','10'));db.commit()
    check('SQL:重投不再次进入creating',db.execute("UPDATE launch SET state='creating',creation_attempted=1 WHERE state='registered' AND creation_attempted=0").rowcount,0)
    rejected('禁止清attempt',"UPDATE launch SET state='registered',creation_attempted=0")
    rejected('禁止已尝试变rejected',"UPDATE launch SET state='rejected'")
    rejected('禁止清恢复计数','DELETE FROM recovery_attempt')
    db.execute("UPDATE launch SET state='awaiting_bootstrap',bootstrap_id='bootstrap.one'")
    db.execute("UPDATE launch SET state='admitted_closed',proof_consumed=1,admission_json=?",(b'{"receipt":"one"}',));db.commit()
    check('SQL:重复proof消费为零',db.execute('UPDATE launch SET proof_consumed=1 WHERE proof_consumed=0').rowcount,0)
    rejected('换bootstrap',"UPDATE launch SET bootstrap_id='bootstrap.two'")
    rejected('改回执',"UPDATE launch SET admission_json=?",(b'{}',))
    rejected('直接变retired',"UPDATE launch SET state='retired',retirement_json=?",(b'{}',))
    db.execute("UPDATE launch SET state='retiring'")
    rejected('无证据退役',"UPDATE launch SET state='retired'")
    db.execute("UPDATE launch SET state='retired',retirement_json=?",(b'{"evidence":"one"}',));db.commit()
    rejected('退役复活',"UPDATE launch SET state='creating'")
    rejected('删除墓碑','DELETE FROM launch')
    add('crash');db.execute("UPDATE launch SET state='creating',creation_attempted=1 WHERE launch_id='crash'");db.commit()
    db.execute("UPDATE launch SET state='indeterminate' WHERE launch_id='crash'")
    rejected('未知改未创建',"UPDATE launch SET state='registered',creation_attempted=0 WHERE launch_id='crash'")
    check('SQL:跨域恢复保留原计数',db.execute('SELECT origin_tick FROM recovery_attempt').fetchone()[0],'10')
    check('SQL:外键一致',db.execute('PRAGMA foreign_key_check').fetchall(),[])
    db.close()


def run():
    docs=build();resources=list(docs.values())+[json.loads(p.read_bytes()) for p in INPUTS[6:8]]
    registry=Registry().with_resources((s['$id'],Resource.from_contents(s)) for s in resources)
    for n,s in docs.items():
        assert (HERE/n).read_bytes()==encoded(s),n
        Draft202012Validator.check_schema(s)
    schema=docs['supervisor.schema.json'];boot=docs['bootstrap.schema.json'];checks=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        checks.append(dict(name=name,expected=expected,observed=actual))
    def shape(name,model,v,expected=True): check(name,Draft202012Validator({'$ref':SID+'#/$defs/'+model},registry=registry).is_valid(v),expected)
    f=fixtures();a=f['assignment'];p=f['proof'];intent=f['intent']
    for model,key in [('ExtensionLaunchIntent','intent'),('LaunchAuthorization','grant'),('FenceSnapshot','fence'),('BootstrapAssignment','assignment'),('BootstrapProof','proof'),('AdmissionReceipt','receipt'),('RetirementEvidence','retirement'),('JournalView','view')]: shape('结构:'+model,model,f[key])
    protected={k:v for k,v in intent.items() if k!='extension_binding'};protected.update(role='core',device_ids=[])
    shape('保护配置启动core','LaunchIntent',protected)
    shape('保护配置不能绕审批启动worker','LaunchIntent',dict(protected,role='worker'),False)
    shape('扩展不能冒充core','LaunchIntent',dict(intent,role='core'),False)
    shape('core不能带设备','LaunchIntent',dict(protected,device_ids=['device.test']),False)
    shape('不能注入argv','LaunchIntent',dict(intent,argv=['x']),False)
    for v in ('01','-1','1\n',1,'100000000000000000000'): shape('拒绝tick:'+repr(v),'BootstrapAssignment',dict(a,issued_tick_ns=v),False)
    shape('秘密非规范尾位','BootstrapAssignment',dict(a,secret='A'*42+'B'),False)
    shape('秘密带padding','BootstrapAssignment',dict(a,secret=a['secret']+'='),False)
    payloads={'FENCE_PUT':f['fence'],'FENCE_RESULT':dict(revision='1',snapshot_digest=f['fence']['digest'],journal_committed=True),
        'LAUNCH_REGISTER':dict(intent=intent,authorization=f['grant']),'LAUNCH_CREATE':dict(key=f['key'],authorization=f['grant'],materialization_evidence_id='evidence.test',materialization_challenge_id='challenge.test'),
        'LAUNCH_QUERY':f['key'],'LAUNCH_RESULT':dict(key=f['key'],record=f['view']),'RETIRE_REQUEST':dict(key=f['key'],containment_ref=intent['containment_ref'],reason='revoked'),
        'RETIRE_RESULT':f['retirement'],'ERROR':dict(code='indeterminate',retry_action='query_only')}
    for kind,payload in payloads.items():
        reply='request.test' if kind in ('FENCE_RESULT','LAUNCH_RESULT','RETIRE_RESULT','ERROR') else None
        frame=dict(version=VERSION,type=kind,scope=f['scope'],channel_id='channel.test',sequence='1',message_id='message.test',reply_to=reply,payload=payload)
        validator=Draft202012Validator(schema,registry=registry)
        check('控制帧:'+kind,validator.is_valid(frame),True)
        check('版本隔离:'+kind,validator.is_valid(dict(frame,version='ipc/0.3.0-draft.1')),False)
        check('回复关联形状:'+kind,validator.is_valid(dict(frame,reply_to=None if reply else 'unexpected')),False)
        tc=dict(authenticated=True,scope=f['scope'],sender='supervisor' if reply else 'core',channel='channel.test',next_sequence=1,pending={'request.test':dict(response=kind,key=f['key'])})
        check('方向序号:'+kind,transport_error(frame,tc),'receive')
        check('错方向:'+kind,transport_error(frame,dict(tc,sender='core' if reply else 'supervisor')),'direction')
        check('重复帧:'+kind,transport_error(frame,dict(tc,next_sequence=2)),'channel_sequence')
        check('旧连接:'+kind,transport_error(dict(frame,channel_id='old'),tc),'channel_sequence')
        if reply: check('非空但无请求:'+kind,transport_error(dict(frame,reply_to='unrelated'),tc),'reply')
        if kind=='LAUNCH_RESULT':
            check('返回别的意图',transport_error(change(frame,lambda v:v['payload']['key'].update(launch_id='other')),tc),'result_binding')
    for kind,key in [('ASSIGNMENT','assignment'),('PROOF','proof'),('ADMISSION','receipt')]:
        frame=dict(version=BOOT,type=kind,payload=f[key]);check('bootstrap帧:'+kind,Draft202012Validator(boot,registry=registry).is_valid(frame),True)
        check('bootstrap不混入控制帧:'+kind,Draft202012Validator(schema,registry=registry).is_valid(frame),False)
    c=dict(peer_instance_valid=True,artifact_valid=True,used=False,domain=domain(a['clock_domain_descriptor']),channel=a['channel_binding_id'],member_boot_id=a['member_boot_id'],now=15,max_age=10)
    check('proof正常',proof_error(a,p,intent,c),None)
    for key,value,error in [('peer_instance_valid',False,'peer_or_artifact'),('artifact_valid',False,'peer_or_artifact'),('used',True,'already_consumed'),('now',20,'expired'),('now',9,'expired'),('max_age',9,'expired'),('channel','other','instance'),('member_boot_id','other','instance')]: check('proof前提:'+key+str(value),proof_error(a,p,intent,dict(c,**{key:value})),error)
    for key,value in [('role','core'),('member_id','other'),('launch_intent_digest',digest('other')),('channel_binding_id','other'),('challenge_id','other')]: check('proof错配:'+key,proof_error(a,dict(p,**{key:value}),intent,c),'proof_binding')
    check('proof错误MAC',proof_error(a,dict(p,proof=b64(bytes(32))),intent,c),'hmac')
    for key,value in [('challenge_nonce',b64(bytes(32))),('issued_tick_ns','11'),('secret',b64(bytes(32)))]: check('转录绑定:'+key,proof_error(dict(a,**{key:value}),p,intent,c),'hmac')
    changed=change(intent,lambda v:v['extension_binding'].update(entry_id='other'))
    check('不剥离扩展绑定',proof_error(a,p,changed,c),'intent')
    check('JCS不受键插入顺序影响',sign(dict(reversed(list(a.items())))),sign(a))
    ac=dict(supervisor_authenticated=True,journal_committed=True,approval_current=True,observation='observation.test',existing_receipt=None)
    check('准入后核心登记',receipt_error(f['receipt'],a,intent,ac),'persist_core_binding_closed')
    check('准入回执幂等',receipt_error(f['receipt'],a,intent,dict(ac,existing_receipt=f['receipt'])),'existing')
    for k in ('supervisor_authenticated','journal_committed','approval_current'): check('回执权威:'+k,receipt_error(f['receipt'],a,intent,dict(ac,**{k:False})),'authority')
    for k in ('bootstrap_id','member_boot_id','channel_binding_id'): check('回执错配:'+k,receipt_error(dict(f['receipt'],**{k:'other'}),a,intent,ac),'binding')
    check('回执不可信观测',receipt_error(dict(f['receipt'],os_observation_ref='other'),a,intent,ac),'observation')
    check('回执到期等号',receipt_error(dict(f['receipt'],admitted_tick_ns='20'),a,intent,ac),'observation')
    check('回执身份不可替换',receipt_error(dict(f['receipt'],receipt_id='other'),a,intent,dict(ac,existing_receipt=f['receipt'])),'receipt_conflict')
    live={intent['launch_id']:digest(intent)};fence=f['fence']
    check('首次完整fence',fence_error(fence,None,f['scope'],live,set()),'apply')
    check('相同fence查询',fence_error(fence,fence,f['scope'],live,set()),'existing')
    for name,edit,expected in [('遗漏live',lambda v:v.update(items=[]),'coverage'),('重复launch',lambda v:v['items'].append(v['items'][0]),'order_or_duplicate'),
        ('换意图',lambda v:v['items'][0].update(launch_intent_digest=digest('other')),'coverage'),('跨库',lambda v:v['scope'].update(database_instance_id='other'),'scope'),
        ('同版异内容',lambda v:v['items'][0].update(disposition='deny'),'revision_conflict')]:
        v=change(fence,edit);seal(v);check('fence:'+name,fence_error(v,fence,f['scope'],live,set()),expected)
    check('历史deny不复活',fence_error(fence,None,f['scope'],live,{intent['launch_id']}),'denied')
    denied=change(fence,lambda v:(v.update(revision='2'),v['items'][0].update(disposition='deny')));seal(denied)
    check('合法递增deny',fence_error(denied,fence,f['scope'],live,set()),'apply')
    check('旧fence回退',fence_error(fence,denied,f['scope'],live,set()),'stale')
    cc=dict(authenticated_core=True,journal_healthy=True,synchronized=True,fence=fence,now=15,max_grant_age=10,current_authority_valid=True,materialization_key=f['key'],materialization_valid=True)
    check('合法准备一次create',create_error(f,cc),'mark_before_os_call')
    for key,value,expected in [('authenticated_core',False,'closed'),('journal_healthy',False,'closed'),('synchronized',False,'fence'),('fence',denied,'fence'),('now',20,'expired'),('current_authority_valid',False,'authority'),('materialization_valid',False,'materialization')]: check('create:'+key,create_error(f,dict(cc,**{key:value})),expected)
    for state in ('creating','awaiting_bootstrap','admitted_closed','indeterminate','retiring','retired','rejected'): check('回执丢失:'+state,create_error(f,cc,state,True),'query_only')
    rc=dict(old_domain=f['scope']['domain_ref'],evaluator_domain=f['scope']['domain_ref'],members=[intent['member_id']],now=30,intake_closed=True,group_owned=True,all_exited=True,endpoints_disposed=True,members_complete=True)
    check('退出只准退役',retirement_error(f['retirement'],intent,rc),'retire_only')
    for k in ('intake_closed','group_owned','all_exited','endpoints_disposed','members_complete'): check('退役缺证据:'+k,retirement_error(f['retirement'],intent,dict(rc,**{k:False})),'unproven')
    check('明确未知保持保护',retirement_error(dict(f['retirement'],result='unproven'),intent,rc),'retain_protection')
    check('遗漏成员',retirement_error(dict(f['retirement'],target_member_ids=[]),intent,rc),'coverage')
    sql_checks(check)
    return dict(all_passed=True,approved=False,runtime_approved=False,checks=checks,versions=dict(jsonschema=version('jsonschema'),rfc8785=version('rfc8785'),sqlite=sqlite3.sqlite_version),
        runtime_validation=dict(supervisor=0,ipc=0,disk_crash=0,device=0),limitations=['OS实例、权限、实物与完整成员来源为人工前提','fence和启动及消息方向序号为局部快照，未运行实际IPC及保护队列','SQL仅内存局部约束与串行故障切点，不证明磁盘或并发','未执行原生平台加载、监督器、设备或完整SDK归并'])


def hashes(staged=False):
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()).hexdigest() for p in INPUTS}


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--report',action='store_true');g.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report: p.error('--staged仅用于报告绑定')
    if a.check_report:
        report=json.loads(subprocess.check_output(['git','show',':'+REPORT.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else REPORT.read_bytes())
        assert report['all_passed'] and not report['approved'] and not report['runtime_approved'];assert report['input_sha256']==hashes(a.staged)
        print('监督器10输入字节绑定一致，未重跑检查')
    else:
        result=run();result['input_sha256']=hashes()
        if a.report: REPORT.write_bytes(encoded(result))
        print('监督器候选参考通过:',len(result['checks']))
