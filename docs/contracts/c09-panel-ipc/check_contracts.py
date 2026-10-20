"""局部参考判定；可信账本与授权上下文为人工夹具，无实际发送出口。"""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from build_contracts import HERE, SOURCE, PANEL, BID, IID, PUBLIC, CHANNEL, VERSION, build, encoded
from build_cases import build as build_cases

ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('IPC_GUARD.md','build_contracts.py','build_cases.py','check_contracts.py','binding.schema.json','ipc.schema.json','cases.json')]
INPUTS += [SOURCE/n for n in ('public.schema.json','ipc.schema.json','fixtures.json')]
INPUTS += [PANEL/'channel-v02.schema.json']
REPORT=HERE/'reference-report.json'


def digest(value):
    return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def change(value, changes):
    for path, replacement in changes.items():
        parts=path.split('.');target=value
        for key in parts[:-1]: target=target[int(key)] if isinstance(target,list) else target[key]
        key=int(parts[-1]) if isinstance(target,list) else parts[-1]
        target[key]=copy.deepcopy(replacement)


def selector_matches(selector, panel):
    if panel is None: return False
    identity=panel['context']['request_identity']
    names=('authority_service_id','database_instance_id','issuer_id','issuer_epoch','auth_session_id','panel_session_id','document_generation')
    if any(selector[k]!=identity[k] for k in names): return False
    if selector['kind']=='panel_session': return True
    if selector['kind']=='panel_delegation':
        delegation=panel['context']['panel_delegation_ref']
        return selector['delegation_id']==delegation['delegation_id'] and int(delegation['revision'])<int(selector['revision_floor'])
    raise ValueError('参考选择器只处理本批两个分支')


def guard_errors(data):
    g,p,c=data['guard'],data['permit'],data['authority'];errors=[]
    if g['guard_digest']!=digest({k:v for k,v in g.items() if k!='guard_digest'}): errors.append('guard_digest')
    for field in ('guard_id','guard_digest','permit_id','command_id','controller_boot_id','worker_boot_id','clock_domain_id','descriptor_digest'):
        if g[field]!=p[field]: errors.append('permit_'+field)
    for field in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest'):
        if g[field]!=c['current'][field]: errors.append('current_'+field)
    if p['device_session_id']!=c['current']['device_session_id']: errors.append('device_session')
    if not c['storage_healthy']: errors.append('storage')
    if g['admission_origin']!=c['admission_origin'] or p['admission_origin']!=g['admission_origin']: errors.append('provenance')
    panel=g['panel_binding']
    if p['panel_binding_digest']!=(digest(panel) if panel else None): errors.append('panel_digest')
    if int(c['now'])>=int(g['authorization_deadline_tick_ns']): errors.append('authorization_expired')
    if panel is None: return errors
    if panel!=c['panel_binding']: errors.append('authoritative_binding')
    ctx=panel['context'];identity=ctx['request_identity'];auth=g['binding'];life=panel['lifetime']
    if any(not c[k] for k in ('active_session','approval_current','scope_current')): errors.append('authority_state')
    for key in ('panel_session_id','document_generation','auth_session_id'):
        if ctx[key]!=identity[key]: errors.append('context_'+key)
    if auth['principal_kind']!='human' or auth['origin']!='manual' or p['origin']!='manual': errors.append('human_manual')
    if auth['principal_id']!=panel['principal_id'] or auth['session_id']!=identity['auth_session_id']: errors.append('actor')
    if auth['issuer_id']!=identity['issuer_id'] or auth['issuer_epoch']!=identity['issuer_epoch'] or auth['audience']!=identity['authority_service_id']: errors.append('issuer_audience')
    if auth['extension_instance_id']!=panel['extension_instance_id'] or auth['extension_approval_revision']!=ctx['approval_ref']['revision']: errors.append('extension')
    if ctx['activation_ref']['scope_revision']!=panel['scope_ref']['revision']: errors.append('scope_revision')
    if auth['scope_digest']!='sha256:'+panel['scope_ref']['content_digest'] or auth['policy_revision']!=panel['policy_ref']['revision']: errors.append('scope_policy')
    for obj in (ctx['panel_delegation_ref'],ctx['installation_ref'],ctx['approval_ref'],panel['scope_ref'],panel['policy_ref']):
        if any(obj[k]!=identity[k] for k in ('authority_service_id','database_instance_id')): errors.append('object_authority')
    if life['domain_ref']!={k:g[k] for k in ('clock_domain_id','descriptor_digest')}: errors.append('clock_domain')
    if int(life['lease_deadline_tick'])>int(life['hard_deadline_tick']): errors.append('lease_bound')
    if int(c['now'])>=min(int(life['lease_deadline_tick']),int(life['hard_deadline_tick'])): errors.append('panel_expired')
    if any(selector_matches(s,panel) for s in c['selectors']): errors.append('revoked')
    return errors


def barrier_errors(data):
    f,a,c=data['fence'],data['ack'],data['authority'];x,y=f['body'],a['body'];errors=[]
    for field in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest'):
        if f[field]!=a[field] or f[field]!=c['current'][field]: errors.append('frame_'+field)
    if a['reply_to']!=f['message_id']: errors.append('reply')
    for field in ('operation_id','barrier_id','selector','selector_digest','target_authorization_revision','issued_cut_revision','ledger_digest'):
        if x[field]!=y[field]: errors.append('echo_'+field)
    if x['selector_digest']!=digest(x['selector']): errors.append('selector_digest')
    if int(y['applied_authorization_revision'])<int(x['target_authorization_revision']): errors.append('applied_revision')
    intents=x['open_intents'];ordered=sorted(intents,key=lambda i:i['permit_id'])
    if intents!=ordered or len({i['permit_id'] for i in intents})!=len(intents): errors.append('ledger_order_unique')
    if x['ledger_digest']!=digest(ordered): errors.append('ledger_digest')
    selected=[]
    for item in c['open_intents']:
        if item['admission_origin']=='non_panel': continue
        panel=c['bindings'].get(item['panel_binding_digest'])
        if panel is None or digest(panel)!=item['panel_binding_digest']:
            errors.append('authority_binding_missing');continue
        if selector_matches(x['selector'],panel): selected.append(item)
    if ordered!=sorted(selected,key=lambda i:i['permit_id']): errors.append('authority_cut')
    coverage=y['coverage'];covered={e['intent']['permit_id']:e for e in coverage}
    if len(covered)!=len(coverage) or set(covered)!={i['permit_id'] for i in intents}: errors.append('coverage_set')
    expected={'not_sent':set(),'in_flight':set(),'unknown':set()}
    for item in intents:
        entry=covered.get(item['permit_id'])
        if not entry: continue
        if entry['intent']!=item: errors.append('intent_binding')
        disposition=entry['disposition']
        expected[disposition].add(item['permit_id'] if disposition=='not_sent' else item['command_id'])
        old=any(item[k]!=c['current'][k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','device_session_id','clock_domain_id','descriptor_digest'))
        if old and disposition!='unknown': errors.append('old_generation')
        if item['permit_id'] in c['transport_entered'] and disposition=='not_sent': errors.append('downgrade')
    for name,group in [('invalidated_permit_ids','not_sent'),('in_flight_command_ids','in_flight'),('unresolved_command_ids','unknown')]:
        if len(y[name])!=len(set(y[name])) or set(y[name])!=expected[group]: errors.append(name)
    return errors


def trace(steps):
    closed=False;generation='original';sent=0;unknown=False;ack=False;applied=False;permit_available=True
    for action in steps:
        if action=='send' and not closed and generation=='original' and permit_available:
            sent+=1;permit_available=False
        elif action=='fence': closed=True
        elif action=='reconnect': closed=True;generation='new';unknown=True;ack=False;applied=False
        elif action=='ack': ack=closed and generation=='original'
        elif action=='store': applied=ack
        elif action=='store_fail': applied=False
    return dict(sent=sent,unknown=unknown,applied=applied)


def guard_ack_errors(install,ack,current):
    errors=[];g=install['body']['guard'];body=ack['body']
    for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest'):
        if install[k]!=ack[k] or ack[k]!=current[k]: errors.append('generation')
    if ack['reply_to']!=install['message_id']: errors.append('reply')
    for k in ('guard_id','guard_digest','permit_id','command_id'):
        if body[k]!=g[k]: errors.append('guard')
    if body['installed_authorization_revision']!=g['authorization_revision']: errors.append('revision')
    if body['content_digest']!=install['body']['content_digest']: errors.append('content')
    if body['panel_binding_digest']!=(digest(g['panel_binding']) if g['panel_binding'] else None): errors.append('panel')
    return errors


def run():
    models=build();cases=build_cases()
    for name,value in {**models,'cases.json':cases}.items(): assert (HERE/name).read_bytes()==encoded(value),name
    # 从正式JSON重读，避免生成器临时对象共享引用让变异同时污染权威快照。
    cases=json.loads((HERE/'cases.json').read_text('utf-8'))
    resources=[models['binding.schema.json'],models['ipc.schema.json'],PUBLIC,CHANNEL]
    registry=Registry().with_resources((d['$id'],Resource.from_contents(d)) for d in resources)
    for model in models.values(): Draft202012Validator.check_schema(model)
    results=[]
    def valid(ref,value):
        return Draft202012Validator({'$ref':ref},registry=registry,format_checker=FormatChecker()).is_valid(value)
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        results.append(dict(id=name,expected_valid=expected,passed=True))
    for name,frame in cases['frames'].items(): check('structure:'+name,valid(IID,frame),True)
    old=copy.deepcopy(cases['frames']['DISPATCH']);old['ipc_version']='ipc/0.3.0-draft.1'
    check('old_version_rejected',valid(IID,old),False)
    missing=copy.deepcopy(cases['frames']['HELLO_ACK']);missing['body']['selected_features'].remove('panel_scoped_fence')
    check('missing_feature',valid(IID,missing),False)
    base=cases['base']
    for case in cases['guard_cases']:
        data=copy.deepcopy(base);change(data,case['changes'])
        if case['rehash']:
            data['guard']['guard_digest']=digest({k:v for k,v in data['guard'].items() if k!='guard_digest'})
            data['permit']['guard_digest']=data['guard']['guard_digest']
            data['permit']['panel_binding_digest']=digest(data['guard']['panel_binding']) if data['guard']['panel_binding'] else None
        accepted=valid(BID+'#/$defs/ExecutionGuard',data['guard']) and valid(BID+'#/$defs/DispatchPermit',data['permit']) and not guard_errors(data)
        check(case['id'],accepted,case['valid'])
    for case in cases['barrier_cases']:
        data=copy.deepcopy(base);change(data,case['changes'])
        if case['id']=='PB14':
            data['fence']['body']['ledger_digest']=digest([]);data['ack']['body']['ledger_digest']=digest([])
        accepted=valid(IID,data['fence']) and valid(IID,data['ack']) and not barrier_errors(data)
        check(case['id'],accepted,case['valid'])
    for case in cases['selection_cases']:
        panel=copy.deepcopy(base['guard']['panel_binding']);change(panel,case['binding_changes'])
        check(case['id'],valid(BID+'#/$defs/RevocationSelector',case['selector']) and selector_matches(case['selector'],panel),case['match'])
    check('selector_non_panel',selector_matches(base['fence']['body']['selector'],None),False)
    for case in cases['traces']:
        outcome=trace(case['steps']);check(case['id'],outcome=={k:case[k] for k in ('sent','unknown','applied')},True)
    # 合法non_panel人工与组织自动化保留，但不能从原面板来源剥掉绑定。
    for origin in ('manual','automation'):
        data=copy.deepcopy(base)
        data['guard'].update(admission_origin='non_panel',panel_binding=None)
        data['authority'].update(admission_origin='non_panel',panel_binding=None)
        data['authority']['selectors']=[base['fence']['body']['selector']]
        data['permit'].update(admission_origin='non_panel',panel_binding_digest=None,origin=origin)
        if origin=='automation':
            data['guard']['binding'].update(principal_kind='service',origin='automation',principal_id='organization-service',
                session_id=None,session_revision=None,grant_id='org-grant',grant_revision='17',arm_generation='22')
            data['permit'].update(grant_revision='17',arm_generation='22')
        data['guard']['guard_digest']=digest({k:v for k,v in data['guard'].items() if k!='guard_digest'})
        data['permit']['guard_digest']=data['guard']['guard_digest']
        check('non_panel_'+origin,valid(BID+'#/$defs/ExecutionGuard',data['guard']) and valid(BID+'#/$defs/DispatchPermit',data['permit']) and not guard_errors(data),True)
    install=copy.deepcopy(cases['frames']['GUARD_INSTALL']);install['body']['guard']=base['guard']
    ack=copy.deepcopy(cases['frames']['GUARD_ACK']);ack['reply_to']=install['message_id']
    ack['body'].update({k:base['guard'][k] for k in ('guard_id','guard_digest','permit_id','command_id')})
    ack['body'].update(installed_authorization_revision=base['guard']['authorization_revision'],
        content_digest=install['body']['content_digest'],panel_binding_digest=digest(base['guard']['panel_binding']))
    check('panel_guard_install',valid(IID,install),True)
    check('panel_guard_ack',valid(IID,ack) and not guard_ack_errors(install,ack,base['authority']['current']),True)
    for field in ('panel_binding_digest','guard_digest','content_digest','permit_id','installed_authorization_revision'):
        altered=copy.deepcopy(ack)
        altered['body'][field]='sha256:'+'f'*64 if field.endswith('digest') else '999'
        check('ack_wrong_'+field,valid(IID,altered) and not guard_ack_errors(install,altered,base['authority']['current']),False)
    altered=copy.deepcopy(ack);altered['ipc_session_id']='old-ipc'
    check('guard_ack_old_connection',valid(IID,altered) and not guard_ack_errors(install,altered,base['authority']['current']),False)
    # 一条命令两个许可可同时处于in_flight和unknown，列表不能相互抵消。
    multi=copy.deepcopy(base);one=multi['fence']['body']['open_intents'][0];two=copy.deepcopy(one)
    second_guard=copy.deepcopy(base['guard']);second_guard.update(guard_id='guard-2',permit_id='permit-2',worker_boot_id='old-worker')
    second_digest=digest({k:v for k,v in second_guard.items() if k!='guard_digest'})
    two.update(permit_id='permit-2',attempt_id='attempt-2',dispatch_intent_id='intent-2',worker_boot_id='old-worker',guard_id='guard-2',guard_digest=second_digest)
    intents=[one,two];multi['authority']['open_intents']=copy.deepcopy(intents)
    multi['fence']['body'].update(open_intents=intents,ledger_digest=digest(intents))
    multi['ack']['body'].update(ledger_digest=digest(intents),coverage=[dict(intent=one,disposition='in_flight',proof='transport_entered'),
        dict(intent=two,disposition='unknown',proof='send_uncertain')],invalidated_permit_ids=[],
        in_flight_command_ids=[one['command_id']],unresolved_command_ids=[one['command_id']])
    check('same_command_two_dispositions',valid(IID,multi['fence']) and valid(IID,multi['ack']) and not barrier_errors(multi),True)
    altered=copy.deepcopy(multi);altered['ack']['body']['unresolved_command_ids']=[]
    check('must_keep_unknown_attempt',valid(IID,altered['ack']) and not barrier_errors(altered),False)
    duplicate=copy.deepcopy(base);duplicate['ack']['body']['coverage']*=2
    check('duplicate_coverage',valid(IID,duplicate['ack']) and not barrier_errors(duplicate),False)
    # 第二页面的未核销许可不在A的匹配切点；不能因为同安装而扩大selector。
    scoped=copy.deepcopy(base);other=copy.deepcopy(base['guard']['panel_binding'])
    other['context']['panel_session_id']='panel-b';other['context']['request_identity']['panel_session_id']='panel-b'
    other['context']['panel_delegation_ref']['delegation_id']='delegation-b'
    other_guard=copy.deepcopy(base['guard']);other_guard.update(guard_id='guard-b',permit_id='permit-b',panel_binding=other)
    other_digest=digest({k:v for k,v in other_guard.items() if k!='guard_digest'})
    other_intent=copy.deepcopy(scoped['authority']['open_intents'][0]);other_intent.update(permit_id='permit-b',guard_id='guard-b',guard_digest=other_digest,panel_binding_digest=digest(other))
    scoped['authority']['open_intents'].append(other_intent);scoped['authority']['bindings'][digest(other)]=other
    check('separate_page_cut',not barrier_errors(scoped),True)
    # 完整世代的单字段差异必须unknown；修正分类后可纳入覆盖但不表示未发。
    for field in ('controller_boot_id','worker_boot_id','ipc_session_id','device_session_id','clock_domain_id','descriptor_digest'):
        data=copy.deepcopy(base);item=data['fence']['body']['open_intents'][0]
        item[field]=('clock_'+'f'*64 if field=='clock_domain_id' else 'sha256:'+'f'*64 if field=='descriptor_digest' else 'old-generation')
        data['authority']['open_intents']=[copy.deepcopy(item)]
        data['fence']['body']['ledger_digest']=digest([item]);data['ack']['body']['ledger_digest']=digest([item])
        data['ack']['body']['coverage'][0]['intent']=copy.deepcopy(item)
        check('old_not_sent:'+field,valid(IID,data['ack']) and not barrier_errors(data),False)
        data['ack']['body'].update(coverage=[dict(intent=item,disposition='unknown',proof='send_uncertain')],
            invalidated_permit_ids=[],unresolved_command_ids=[item['command_id']])
        check('old_unknown:'+field,valid(IID,data['ack']) and not barrier_errors(data),True)
    return dict(approved=False,runtime_approved=False,all_passed=True,ipc_message_types=19,checks=results,
                versions={'python':sys.version.split()[0]},
                runtime_validation={'product_services':0,'worker_ipc':0,'database':0,'device':0,'supervisor':0},
                limitations=['权威账本与批准为人工前提','19帧回归只查结构，不迁移原全部语义','模型顺序不证明真实并发或传播上界','不执行既有资源占用、NTP与完整发送窗口判定'])


def check_report(staged=False):
    def read(path):
        return subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else path.read_bytes()
    report=json.loads(read(REPORT))
    assert set(report['input_sha256'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
    for p in INPUTS: assert report['input_sha256'][p.relative_to(ROOT).as_posix()]==hashlib.sha256(read(p)).hexdigest(),p
    print('11份输入字节绑定一致；未重跑用例')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    if args.check_report: check_report(args.staged)
    else:
        assert not args.staged
        report=run();report['input_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS}
        if args.report: REPORT.write_bytes(encoded(report))
        print('IPC候选参考检查通过:',len(report['checks']))
