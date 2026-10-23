"""面板会话候选的离线参考检查；不执行浏览器、真实授权或数据库事务。"""
import argparse
import copy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = [ROOT / n for n in ('CHANNEL.md', 'channel.schema.json', 'channel-cases.json',
                            'check_channel.py', 'operation-policy.json')]
INPUTS += [REPO / 'docs/rebirth-c09-extension-design.md']


def load(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result: raise ValueError('重复JSON键')
            result[k] = v
        return result
    def invalid(value): raise ValueError('非法常量：' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def preview_projection(preview):
    return {k: v for k, v in preview.items()
            if k not in ('preview_digest', 'state', 'accepted_result_ref')}


def seal(preview):
    preview['intent_digest'] = digest(preview['intent'])
    preview['preview_digest'] = digest(preview_projection(preview))


def validator(schema, name):
    return Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': schema['$defs']},
                               format_checker=FormatChecker())


def mutate(value, changes):
    for change in changes:
        node = value
        for part in change['path'][:-1]: node = node[part]
        node[change['path'][-1]] = copy.deepcopy(change['value'])


def lifetime_errors(c):
    errors = set()
    life = c['lifetime']
    if life['domain_ref'] != c['current_domain']: errors.add('domain')
    if int(c['now_tick']) >= min(int(life['hard_deadline_tick']), int(life['lease_deadline_tick'])):
        errors.add('deadline')
    if not c['authorized']: errors.add('authority')
    return errors


def handshake_errors(reply, c, schema):
    if not validator(schema, 'Reply').is_valid(reply): return {'structure'}
    errors = lifetime_errors(c)
    # 这些值模拟浏览器event属性，不从reply数据中读取。
    if c['event_origin'] != c['session']['panel_origin'] or not c['source_matches']:
        errors.add('window_identity')
    if c['transfer_count'] != 0: errors.add('transport')
    if c['session']['state'] != 'handshaking': errors.add('inactive')
    if c['handshake_consumed'] or any(reply[k] != c['challenge'][k] for k in (
            'protocol_version', 'handshake_id', 'nonce', 'panel_instance_id', 'document_generation')):
        errors.add('challenge')
    if reply['artifact_digest'] != c['session']['artifact_digest']: errors.add('artifact')
    if int(c['now_tick']) >= int(c['handshake_deadline_tick']): errors.add('deadline')
    return errors


def payload_errors(method, value, c):
    descriptor = c['method_registry'].get(method)
    if descriptor is None: return {'method'}
    if value['schema_ref'] != descriptor['input_schema_ref']: return {'payload'}
    definition = c['dynamic_schemas'].get(value['schema_ref']['definition'])
    if definition is None or not Draft202012Validator(definition).is_valid(value['value']):
        return {'payload'}
    return set()


def request_decision(request, c, schema, policy):
    if not validator(schema, 'Request').is_valid(request): return {'structure'}, None
    errors = lifetime_errors(c)
    if not c['port_matches'] or c['transfer_count'] != 0: errors.add('transport')
    if c['session']['state'] != 'active' or not c['channel_active']: errors.add('inactive')
    if request['public_binding'] != c['public_binding']: errors.add('binding')
    if request['channel_sequence'] != c['expected_sequence']: errors.add('sequence')
    if request['target_handle'] != c['target_handle']: errors.add('target')
    if request['method'].split('.', 1)[0] != c['target_service_kind']: errors.add('target')
    resource = request['resource_ref']
    if resource is not None and any(resource[k] != c['session'][k] for k in ('authority_service_id', 'database_instance_id')):
        errors.add('target')
    errors |= payload_errors(request['method'], request['payload'], c)
    row = policy['operations'].get(request['method'].replace('.', ':', 1))
    descriptor = c['method_registry'].get(request['method'])
    if (row is None or descriptor is None or row['method_name'] != request['method']
            or row['mode'] not in ('panel_read', 'panel_write', 'host_confirm')
            or row['mode'] != descriptor['mode']):
        errors.add('method')
    if errors: return errors, None
    return set(), {'panel_read': 'proxy_read', 'panel_write': 'proxy_write',
                   'host_confirm': 'needs_host_confirmation'}[row['mode']]


def preview_decision(p, commit, c, schema, policy):
    if not validator(schema, 'Preview').is_valid(p) or not validator(schema, 'ConfirmationCommit').is_valid(commit):
        return {'structure'}, None
    errors = lifetime_errors(c)
    intent = p['intent']
    if not c['trusted_host']: errors.add('authority')
    if c['session']['state'] != 'active': errors.add('inactive')
    if p['state'] != 'offered' or p['accepted_result_ref'] is not None: errors.add('preview_state')
    if p['preview_ref'] != c['expected_preview_ref']: errors.add('identity')
    if intent['method'].split('.', 1)[0] != c['target_service_kind']: errors.add('target')
    if (intent['identity'] != c['expected_identity'] or commit['identity'] != intent['identity']
            or any(intent['identity'][k] != c['session'][k] for k in (
                'authority_service_id', 'database_instance_id', 'issuer_id', 'issuer_epoch',
                'auth_session_id', 'panel_session_id', 'document_generation'))):
        errors.add('identity')
    if intent['delegation_ref'] != c['delegation_ref'] or commit['delegation_ref'] != intent['delegation_ref']:
        errors.add('delegation')
    if intent['target_ref'] != c['expected_target']: errors.add('target')
    if intent['policy_ref'] != c['policy_ref']: errors.add('policy')
    if p['expected_object_revisions'] != c['expected_revisions']: errors.add('revisions')
    if p['recovery_preview_ref'] != c['recovery_preview_ref']: errors.add('recovery')
    if (intent['method'] == 'seamer.resumeRun') != (p['recovery_preview_ref'] is not None): errors.add('recovery')
    if p['domain_ref'] != c['current_domain']: errors.add('domain')
    if (int(c['now_tick']) >= int(p['deadline_tick'])
            or int(p['deadline_tick']) > int(p['lease_deadline_at_creation'])
            or int(p['deadline_tick']) > int(c['lifetime']['hard_deadline_tick'])
            or int(p['deadline_tick']) > int(c['lifetime']['lease_deadline_tick'])):
        errors.add('deadline')
    if p['intent_digest'] != digest(intent) or p['preview_digest'] != digest(preview_projection(p)):
        errors.add('digest')
    if (commit['preview_ref'] != p['preview_ref'] or commit['intent_digest'] != p['intent_digest']
            or commit['preview_digest'] != p['preview_digest']):
        errors.add('commit_binding')
    errors |= payload_errors(intent['method'], intent['normalized_arguments'], c)
    row = policy['operations'].get(intent['method'].replace('.', ':', 1))
    if row is None or row['mode'] != 'host_confirm': errors.add('method')
    return errors, None if errors else 'accept_once'


def trace_reference(events):
    """只枚举手工原子步；uncertain不假设真实提交是否发生。"""
    active, preview, known_acceptances = False, None, 0
    results = []
    for event in events:
        if event == 'activate' and preview is None:
            active = True; result = 'active'
        elif event == 'close':
            active = False; result = 'closing'
        elif event == 'expire':
            active = False; result = 'expired'
        elif event == 'query':
            result = 'original' if preview == 'consumed' else 'query_required'
        elif not active:
            result = 'denied'
        elif event == 'offer' and preview is None:
            preview = 'offered'; result = 'offered'
        elif event == 'commit' and preview == 'offered':
            preview = 'consumed'; known_acceptances += 1; result = 'accepted'
        elif event == 'commit' and preview == 'consumed':
            result = 'original'
        elif event == 'cancel' and preview == 'offered':
            preview = 'cancelled'; result = 'cancelled'
        elif event == 'uncertain_commit' and preview == 'offered':
            preview = 'uncertain'; active = False; result = 'uncertain'
        else: result = 'conflict'
        results.append(result)
    return results, known_acceptances


def hashes(staged=False):
    return {p.relative_to(REPO).as_posix(): hashlib.sha256(
        subprocess.check_output(['git', 'show', ':' + p.relative_to(REPO).as_posix()], cwd=REPO)
        if staged else p.read_bytes()).hexdigest() for p in INPUTS}


def run():
    schema = load((ROOT / 'channel.schema.json').read_bytes())
    data = load((ROOT / 'channel-cases.json').read_bytes())
    policy = load((ROOT / 'operation-policy.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    assert data['purpose'] == 'synthetic_panel_channel_design_only' and not data['runtime_approved']
    results = []
    for case in data['structure_cases']:
        value = copy.deepcopy(data['fixtures'][case.get('fixture', case['model'])]); mutate(value, case['changes'])
        actual = validator(schema, case['model']).is_valid(value)
        assert actual == case['valid'], case['id']
        results.append(dict(id=case['id'],passed=True,valid=actual))
    for group in ('handshake_cases', 'request_cases', 'preview_cases'):
        for case in data[group]:
            packet = dict(context=copy.deepcopy(data['context']),reply=copy.deepcopy(data['fixtures']['Reply']),
                          request=copy.deepcopy(data['fixtures']['Request']),preview=copy.deepcopy(data['fixtures']['Preview']))
            if group == 'handshake_cases': packet['context']['session']['state'] = 'handshaking'
            mutate(packet, case['changes'])
            if group == 'handshake_cases':
                errors = handshake_errors(packet['reply'],packet['context'],schema); outcome = 'valid' if not errors else None
            elif group == 'request_cases':
                errors,outcome = request_decision(packet['request'],packet['context'],schema,policy)
            else:
                p = packet['preview']; seal(p)
                commit = copy.deepcopy(data['fixtures']['ConfirmationCommit'])
                commit['intent_digest'] = p['intent_digest']; commit['preview_digest'] = p['preview_digest']
                mutate(p, case.get('after_seal', []))
                errors,outcome = preview_decision(p,commit,packet['context'],schema,policy)
            assert case['expected'] == outcome or case['expected'] in errors, (case['id'], errors, outcome)
            results.append(dict(id=case['id'],passed=True,errors=sorted(errors),outcome=outcome))
    for case in data['traces']:
        actual, count = trace_reference(case['events'])
        assert actual == case['expected'] and count == case['known_acceptances'], (case['id'],actual,count)
        results.append(dict(id=case['id'],passed=True,observed=actual,known_acceptances=count))
    assert len(set(r['id'] for r in results)) == len(results)
    return dict(all_passed=True,approved=False,runtime_approved=False,scope='会话与调用信封及合成握手授权前提和有限原子步；不执行生产代理',
                counts={k:len(data[k]) for k in ('structure_cases','handshake_cases','request_cases','preview_cases','traces')},
                browser_tests_executed=0,database_tests_executed=0,device_tests_executed=0,
                tools={n:version(n) for n in ('jsonschema','rfc8785')},results=results,input_sha256=hashes())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group();group.add_argument('--report',action='store_true');group.add_argument('--check-report',action='store_true')
    p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged仅配合--check-report')
    report_path=ROOT/'channel-report.json'
    if a.check_report:
        report=load(subprocess.check_output(['git','show',':'+report_path.relative_to(REPO).as_posix()],cwd=REPO) if a.staged else report_path.read_bytes())
        assert report['all_passed'] and not report['approved'] and not report['runtime_approved']
        assert report['input_sha256']==hashes(a.staged),'报告输入变化'
        print(json.dumps(dict(bindings_matched=len(INPUTS),staged=a.staged,tests_rerun=False)));return
    report=run()
    if a.report:report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('results','input_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
