"""离线检查快照候选、合成摘要和关联；不实现数据库、网络或运行授权。"""
import argparse
from collections import Counter
import copy
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
VERSION = 'snapshot-projection/0.1.0-draft.1'
INPUTS = [ROOT / n for n in ('README.md', 'snapshot.schema.json', 'cases.json', 'check_snapshot.py')]
INPUTS += [REPO / 'docs/rebirth-c05-event-sync-design.md']
CONTROLLER = {'devices', 'catalogs', 'commands', 'controls', 'observations', 'sources'}
SEAMER = {'definitions', 'runs', 'business_states', 'executions', 'schedule_activations', 'occurrences', 'sources'}


def pairs(items):
    value = {}
    for k, v in items:
        if k in value:
            raise ValueError('重复JSON键')
        value[k] = v
    return value


def load(path):
    def reject(value):
        raise ValueError('非法JSON常量: ' + value)
    return json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=reject)


def canonical(value):
    return rfc8785.dumps(value)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validator(schema, name):
    return Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': schema['$defs']}, format_checker=FormatChecker())


def key(record):
    return tuple(record[n] for n in ('entity_kind', 'entity_id', 'entity_epoch'))


def seal(packet):
    """只生成合成摘要；不产生预期答案，不签名或声明内容权威。"""
    m = packet['manifest']
    m['pages'] = [dict(page_index=p['content']['page_index'], content_bytes=len(canonical(p['content'])),
                       content_digest=digest(p['content'])) for p in packet['pages']]
    m['page_count'] = len(m['pages'])
    m['total_content_bytes'] = sum(p['content_bytes'] for p in m['pages'])
    counts = Counter(r['entity_kind'] for p in packet['pages'] for r in p['content']['records'])
    for c in m['collections']:
        c['count'] = str(counts[c['entity_kind']])
    m['manifest_digest'] = digest({k: v for k, v in m.items() if k != 'manifest_digest'})
    for p, descriptor in zip(packet['pages'], m['pages']):
        p['content_digest'] = descriptor['content_digest']
        p['manifest_digest'] = m['manifest_digest']


def make_packet(data, mode):
    kinds = sorted(CONTROLLER if mode == 'controller' else SEAMER if mode == 'seamer' else {'devices'})
    records = [copy.deepcopy(data['records'][k]) for k in kinds] if mode != 'empty' else []
    b = dict(snapshot_id='snapshot_1', subscription_id='subscription_1', publisher_service_id='publisher_1',
             publisher_database_instance_id='publisher_db', stream_id='stream_1', stream_epoch='stream_epoch',
             scope_digest='1' * 64, authorization_revision='1',
             projection_profile_ref=copy.deepcopy(data['records']['sources']['view']['binding_ref']),
             publisher_domain_ref=dict(clock_domain_id='clock_' + '2' * 64, descriptor_digest='sha256:' + '3' * 64))
    b['projection_profile_ref']['entity_kind'] = 'projection_profile'
    delivery = {k: v for k, v in b.items() if k not in ('snapshot_id', 'projection_profile_ref', 'publisher_domain_ref')}
    delivery['connection_generation'] = '1'
    collections = [dict(entity_kind=k, count='0', view_schema_ref=dict(schema_id='urn:leafseamer:design:' + VERSION,
                    definition=data['view_names'][k], schema_digest='b' * 64)) for k in kinds]
    source = data['records']['sources']['view']
    watermarks = [dict(source_key=copy.deepcopy(source['source_key']), binding_ref=copy.deepcopy(source['binding_ref']),
        baseline_sequence=source['contiguous_sequence'], source_state_revision='1', baseline_ref=copy.deepcopy(source['baseline_ref']),
        gap_summary=copy.deepcopy(source['gaps']))] if mode == 'controller' else []
    m = dict(format_version=VERSION, binding=b, snapshot_cursor='0', collections=collections, source_watermarks=watermarks,
             pages=[], page_count=1, total_content_bytes=0, created_at='2026-10-18T00:00:00Z',
             expires_at='2026-10-18T00:00:30Z', manifest_digest='0' * 64)
    page = dict(manifest_digest='0' * 64, content_digest='0' * 64,
                content=dict(format_version=VERSION, binding=copy.deepcopy(b), page_index=0, next_page_index=None, records=records),
                delivery_binding=delivery)
    context = dict(expected_binding=copy.deepcopy(b), expected_delivery=copy.deepcopy(delivery), authorized=True,
                   domain_current=True, now_tick='10', deadline_tick='30', kinds=kinds,
                   purpose='canonical_trigger' if mode == 'controller' else 'status_projection',
                   required_refs=[], expected_schemas={k: copy.deepcopy(c['view_schema_ref']) for k, c in zip(kinds, collections)},
                   approved_dynamic_schemas=copy.deepcopy(data['dynamic_schemas']))
    packet = dict(manifest=m, pages=[page], context=context)
    seal(packet)
    return packet


def record_errors(record, context):
    errors = set()
    k, v = record['entity_kind'], record['view']
    if k == 'commands':
        levels = {'sent': 0, 'acknowledged': 1, 'effect_verified': 2}
        if ((v['phase'] == 'finished') == (v['outcome'] == 'pending')
                or (v['cancellation_state'] == 'none') != (v['cancellation_operation_ref'] is None)
                or v['outcome'] == 'succeeded' and (v['completion_achieved'] is None
                    or levels[v['completion_achieved']] < levels[v['completion_required']])):
            errors.add('command_state')
    if k == 'controls':
        if ((v['mode'] == 'manual') != (v['effective_holder_id'] is not None)
                or (v['gate_state'] == 'ready' and v['pending_change'] is not None)
                or (v['gate_state'] == 'fencing' and v['pending_change'] is None)):
            errors.add('control_state')
    if k == 'sources':
        if int(v['contiguous_sequence']) > int(v['highest_seen_sequence']):
            errors.add('source_state')
        for gap in v['gaps']:
            a, b = gap['first_missing'], gap['last_missing']
            if (gap['loss_extent'] == 'unknown' and (a is not None or b is not None)
                    or gap['loss_extent'] == 'known' and (a is None or b is None or int(a) > int(b))):
                errors.add('source_state')
    if k == 'executions' and len({s['step_id'] for s in v['steps']}) != len(v['steps']):
        errors.add('execution_state')
    if k == 'occurrences':
        accepted = v['admission_state'] == 'accepted'
        if (accepted != (v['admission_ref'] is not None) or accepted != (v['execution_ref'] is not None)
                or datetime.fromisoformat(v['window']['earliest']) >= datetime.fromisoformat(v['window']['latest'])):
            errors.add('occurrence_state')
    if k == 'observations':
        qualified = v['values']
        name = qualified['schema_ref']['definition']
        approved = context['approved_dynamic_schemas'].get(name)
        expected = dict(schema_id='urn:leafseamer:design:' + VERSION, definition=name, schema_digest='b' * 64)
        if approved is None or qualified['schema_ref'] != expected:
            errors.add('dynamic_schema')
        elif not Draft202012Validator(approved, format_checker=FormatChecker()).is_valid(qualified['value']):
            errors.add('dynamic_value')
    return errors


def packet_errors(packet, schema):
    m, pages, c = packet['manifest'], packet['pages'], packet['context']
    if not validator(schema, 'Manifest').is_valid(m) or not all(validator(schema, 'PageResponse').is_valid(p) for p in pages):
        return {'structure'}
    errors = set()
    if not c['authorized'] or not c['domain_current']:
        errors.add('authority')
    if m['binding'] != c['expected_binding'] or any(p['content']['binding'] != m['binding'] for p in pages):
        errors.add('content_binding')
    if any(p['delivery_binding'] != c['expected_delivery'] for p in pages):
        errors.add('delivery_binding')
    # 输入允许下载乱序及完全相同的重复页；只在核验当代绑定后归并。
    indexed = {}
    for page in pages:
        index = page['content']['page_index']
        if index in indexed and canonical(indexed[index]) != canonical(page):
            return errors | {'page_conflict'}
        indexed[index] = page
    pages = [indexed[i] for i in sorted(indexed)]
    if (int(c['now_tick']) >= int(c['deadline_tick'])
            or datetime.fromisoformat(m['created_at']) >= datetime.fromisoformat(m['expires_at'])):
        errors.add('deadline')
    if (m['page_count'] != len(pages) or len(m['pages']) != len(pages)
            or [p['page_index'] for p in m['pages']] != list(range(len(pages)))):
        errors.add('page_layout')
    records = []
    total = 0
    for index, page in enumerate(pages):
        content = page['content']; records.extend(content['records'])
        if content['page_index'] != index or content['next_page_index'] != (index + 1 if index + 1 < len(pages) else None):
            errors.add('page_layout')
        size, h = len(canonical(content)), digest(content)
        total += size
        if (index >= len(m['pages']) or m['pages'][index]['content_bytes'] != size
                or m['pages'][index]['content_digest'] != h or page['content_digest'] != h):
            errors.add('page_digest')
        if page['manifest_digest'] != m['manifest_digest']:
            errors.add('manifest_digest')
        if size > 245760 or len(canonical(page)) > 262144:
            errors.add('capacity')
    if total != m['total_content_bytes']:
        errors.add('total_bytes')
    if len(canonical(m)) + sum(len(canonical(p)) for p in pages) > 8388608:
        errors.add('capacity')
    if digest({k: v for k, v in m.items() if k != 'manifest_digest'}) != m['manifest_digest']:
        errors.add('manifest_digest')
    keys = [key(r) for r in records]
    if len(set(keys)) != len(keys): errors.add('entity_identity')
    if keys != sorted(keys): errors.add('entity_order')
    counts = Counter(r['entity_kind'] for r in records)
    if ([x['entity_kind'] for x in m['collections']] != c['kinds']
            or set(counts) - set(c['kinds'])):
        errors.add('collection_coverage')
    for collection in m['collections']:
        kind = collection['entity_kind']
        if (int(collection['count']) != counts[kind]
                or collection['view_schema_ref'] != c['expected_schemas'].get(kind)):
            errors.add('collection_coverage')
    for r in records:
        errors |= record_errors(r, c)
    identities = {key(r) + (r['entity_revision'],) for r in records}
    for required in c['required_refs']:
        if (required['authority_service_id'] != m['binding']['publisher_service_id']
                or required['database_instance_id'] != m['binding']['publisher_database_instance_id']
                or key(required) + (required['revision'],) not in identities):
            errors.add('reference_closure')
    sources = [r for r in records if r['entity_kind'] == 'sources']
    if len({canonical(r['view']['source_key']) for r in sources}) != len(sources):
        errors.add('source_identity')
    expected_watermarks = [dict(source_key=r['view']['source_key'], binding_ref=r['view']['binding_ref'],
        baseline_sequence=r['view']['contiguous_sequence'], source_state_revision=r['entity_revision'],
        baseline_ref=r['view']['baseline_ref'], gap_summary=r['view']['gaps']) for r in sources]
    if m['source_watermarks'] != (expected_watermarks if c['purpose'] == 'canonical_trigger' else []):
        errors.add('watermark')
    return errors


def packet_operation(packet, operation):
    if operation == 'oversize_content':
        observation = next(r for r in packet['pages'][0]['content']['records'] if r['entity_kind']=='observations')
        observation['view']['values']['value']['padding'] = 'x' * 262144
        dynamic = packet['context']['approved_dynamic_schemas']['SyntheticState']
        dynamic['properties']['padding'] = {'type':'string','maxLength':300000}
    elif operation in ('split_pages','reverse_download','missing_page'):
        first = packet['pages'][0]
        second = copy.deepcopy(first)
        records = first['content']['records']
        second['content']['records'] = records[3:]
        first['content']['records'] = records[:3]
        first['content']['next_page_index'] = 1
        second['content']['page_index'] = 1
        packet['pages'].append(second)
        seal(packet)
        if operation == 'reverse_download': packet['pages'].reverse()
        if operation == 'missing_page': packet['pages'].pop()
    elif operation in ('duplicate_page','conflicting_page'):
        packet['pages'].append(copy.deepcopy(packet['pages'][0]))
        if operation == 'conflicting_page':
            packet['pages'][1]['content']['records'][0]['entity_revision'] = '2'
    else: raise ValueError(operation)


def make_data(data, variant, context):
    if variant == 'remove':
        entry = dict(entry_kind='entity.remove', payload=dict(entity_kind='commands',entity_id='command_1',entity_epoch='epoch_1',entity_revision='2',reason='left_scope'))
    elif variant == 'event':
        source = copy.deepcopy(data['records']['sources']['view']['source_key'])
        entry = dict(entry_kind='source.event',payload=dict(source_key=source,event_id='event_1',source_sequence='8',trigger_id='scene_changed',capability_version='1.0.0',occurred_at=None,observed_at='2026-10-18T00:00:00Z',origin_digest='a'*64,age_evidence_ref=copy.deepcopy(data['records']['sources']['view']['binding_ref']),payload=copy.deepcopy(data['records']['observations']['view']['values'])))
    else:
        entry = dict(entry_kind='entity.upsert',payload=copy.deepcopy(data['records'][variant]))
    return dict(format_version=VERSION,type='server.data',binding=copy.deepcopy(context['expected_delivery']),cursor='1',previous_cursor='0',delivery_mode='reconcile',entry=entry,payload_digest=digest(entry))


def data_errors(frame, schema, context):
    if not validator(schema,'Data').is_valid(frame):return {'structure'}
    errors=set()
    if frame['binding']!=context['expected_delivery']:errors.add('delivery_binding')
    if int(frame['cursor'])<=int(frame['previous_cursor']):errors.add('cursor_order')
    if digest(frame['entry'])!=frame['payload_digest']:errors.add('payload_digest')
    if frame['entry']['entry_kind']=='entity.upsert':errors |= record_errors(frame['entry']['payload'],context)
    if frame['entry']['entry_kind']=='source.event':
        errors |= record_errors(dict(entity_kind='observations',view=dict(values=frame['entry']['payload']['payload'])),context)
    return errors


def apply_changes(value, changes):
    for change in changes:
        node = value
        for segment in change['path'][:-1]: node = node[segment]
        k = change['path'][-1]
        if change.get('delete'): del node[k]
        else: node[k] = copy.deepcopy(change['value'])


def mutate_resealed(packet, name):
    records = packet['pages'][0]['content']['records']
    views = {r['entity_kind']: r['view'] for r in records}
    if name == 'duplicate_entity': records.insert(1, copy.deepcopy(records[0]))
    elif name == 'reverse_records': records.reverse()
    elif name == 'command_pending_terminal': views['commands']['outcome'] = 'pending'
    elif name == 'succeeded_without_completion': views['commands']['outcome'] = 'succeeded'
    elif name == 'cancellation_without_operation': views['commands']['cancellation_state'] = 'requested'
    elif name == 'manual_without_holder': views['controls']['effective_holder_id'] = None
    elif name == 'source_frontier_inverted': views['sources']['contiguous_sequence'] = '8'
    elif name == 'invalid_dynamic_value': views['observations']['values']['value']['active'] = 'true'
    elif name == 'accepted_without_execution': views['occurrences']['execution_ref'] = None
    elif name == 'duplicate_step': views['executions']['steps'].append(copy.deepcopy(views['executions']['steps'][0]))
    elif name == 'watermark_missing': packet['manifest']['source_watermarks'] = []
    elif name == 'wrong_view_schema': packet['manifest']['collections'][0]['view_schema_ref']['definition'] = 'RunSnapshotView'
    elif name == 'unknown_gap_with_range': views['sources']['gaps'].append(dict(gap_id='gap_1',loss_extent='unknown',first_missing='1',last_missing='2',resolution_state='open'))
    elif name == 'duplicate_source_identity':
        row = copy.deepcopy(next(r for r in records if r['entity_kind']=='sources'))
        row['entity_id']='sources_2';records.append(row)
    elif name == 'same_entity_next_page':
        page = copy.deepcopy(packet['pages'][0]); page['content']['page_index'] = 1
        page['content']['records'] = [copy.deepcopy(records[-1])]
        packet['pages'][0]['content']['next_page_index'] = 1
        packet['pages'].append(page)
    else: raise ValueError(name)
    seal(packet)


def input_hashes(staged=False):
    result = {}
    for p in INPUTS:
        name = p.relative_to(REPO).as_posix()
        raw = subprocess.check_output(['git','show',':'+name],cwd=REPO) if staged else p.read_bytes()
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


def run():
    schema, data = load(ROOT/'snapshot.schema.json'), load(ROOT/'cases.json')
    Draft202012Validator.check_schema(schema)
    assert data['purpose'] == 'synthetic_snapshot_design_only' and data['runtime_approved'] is False
    assert set(data['records']) == CONTROLLER | SEAMER
    results = []
    for case in data['structure_cases']:
        value = copy.deepcopy(data['records'][case['kind']]); apply_changes(value,case['changes'])
        valid = validator(schema,'Record').is_valid(value)
        assert valid == case['expected_valid'],case['id']
        results.append(dict(id=case['id'],passed=True,structure_valid=valid))
    for case in data['bundle_cases'] + data['resealed_cases']:
        p=make_packet(data,case['mode'])
        if 'mutation' in case: mutate_resealed(p,case['mutation'])
        else:
            if 'operation' in case: packet_operation(p,case['operation'])
            apply_changes(p,case['changes'])
        errors=packet_errors(p,schema)
        assert (not errors if case['expected']=='valid' else case['expected'] in errors),(case['id'],errors)
        results.append(dict(id=case['id'],passed=True,errors=sorted(errors)))
    for case in data['data_cases']:
        context=make_packet(data,'controller')['context']
        frame=make_data(data,case['variant'],context);apply_changes(frame,case['changes'])
        errors=data_errors(frame,schema,context)
        assert (not errors if case['expected']=='valid' else case['expected'] in errors),(case['id'],errors)
        results.append(dict(id=case['id'],passed=True,errors=sorted(errors)))
    assert len({r['id'] for r in results})==len(results)
    return dict(all_passed=True,approved=False,runtime_approved=False,scope='十二类投影结构与合成快照摘要关联；不证明完整生产语义或权威',
                entity_kinds=12,structure_cases=len(data['structure_cases']),bundle_cases=len(data['bundle_cases']),resealed_cases=len(data['resealed_cases']),data_cases=len(data['data_cases']),
                runtime_tests_executed=0,device_tests_executed=0,network_tests_executed=0,
                tools={n:version(n) for n in ('jsonschema','rfc8785')},results=results,input_sha256=input_hashes())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group();g.add_argument('--report',action='store_true');g.add_argument('--check-report',action='store_true')
    p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged仅配合--check-report')
    path=ROOT/'reference-report.json'
    if a.check_report:
        report=json.loads(subprocess.check_output(['git','show',':'+path.relative_to(REPO).as_posix()],cwd=REPO)) if a.staged else load(path)
        assert report['all_passed'] and not report['approved'] and not report['runtime_approved']
        assert report['input_sha256']==input_hashes(a.staged),'报告输入已变化'
        print(json.dumps(dict(bindings_matched=len(INPUTS),staged=a.staged,tests_rerun=False)));return
    report=run()
    if a.report:path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('results','input_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
