"""人工预期的离线C04契约检查；不执行自动化任务或设备命令。"""
import argparse
import copy
import hashlib
import json
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
import rfc8785
from build_contracts import build, ROOT, VERSION
from reference_model import (Invalid, artifact_error, bindings_digest, check_shape, condition_nodes,
    continue_after_failure, derive, digest, evaluate, lookup, parallel_qualified, proof_error, prove, tokens, validator)

SUITE = ROOT.parents[2]
INPUTS = [ROOT / n for n in ('README.md', 'build_contracts.py', 'reference_model.py', 'check_contracts.py', 'program.schema.json')]
INPUTS += [SUITE / 'docs/rebirth-c04-automation-design.md']


def content_ref(name): return dict(id=name, revision='1', digest='sha256:' + 'a' * 64)
def literal(value): return dict(kind='literal', value=value)
def type_spec(kind='integer_string', unit=None): return dict(kind=kind, unit=unit)
def reference(binding='event', pointer='/value', source='event'):
    return dict(kind='ref', source=source, binding_id=binding, pointer=pointer)
def compare(left=None, right=None, op='eq', kind='integer_string', unit=None):
    return dict(kind='compare', operator=op, value_type=type_spec(kind, unit),
                left=left if left is not None else reference(), right=right if right is not None else literal('1'))
def input_binding(name='event', source='event', producer=None):
    return dict(binding_id=name, source=source, authority_id='seamer', registration_ref=content_ref('registration'),
        schema_ref=content_ref('result' if source == 'step_result' else 'schema'), producer_step_id=producer,
        projections=[dict(pointer='/value', value_type=type_spec(), reads=['device/input'])])
def action(name='action', reads=None, writes=None):
    return dict(binding_id=name, authority_id='controller', controller_id='controller', device_id='device', provider_id='fixture',
        capability_id=name, registration_ref=content_ref('reg'), catalog_ref=content_ref('catalog'), module_ref=content_ref('module'),
        parameter_schema_ref=content_ref('params'), result_schema_ref=content_ref('result'),
        parameter_slots=[dict(pointer='/value', value_type=type_spec())],
        footprint=dict(complete=True, evidence_ref=content_ref('footprint'), reads=reads or [], writes=writes or [],
            failure_writes=[], resources=[], preconditions=[], target_constraints=[], safe_failure_classes=['definite_rejection']))
def step(name, binding='action', required=True):
    return dict(step_id=name, depends_on=[], required=required, failure_policy='stop' if required else 'continue_if_independent',
        kind='action', action_binding_id=binding, parameters={'value': '1'}, parameter_bindings=[], guard=literal(True))
def fixture(count=3):
    steps = [step('s' + str(i), 'first' if i == 0 else 'action', i != 0) for i in range(count)]
    result = dict(dsl_version=VERSION, compiler_version='fixture-compiler', definition_id='rule', definition_version='1',
        policy_ref=content_ref('policy'), program=dict(kind='rule', trigger_binding_id='event', condition=literal(True),
            groups=[dict(mode='sequence', steps=steps[i:i+64]) for i in range(0, count, 64)]),
        input_bindings=[input_binding()], action_bindings=[action('first', writes=['device/a']), action()],
        alias_table=dict(ref=content_ref('aliases'), entries=[]), graph_digest='sha256:' + '0' * 64)
    return seal(result)
def seal(c):
    c['alias_table']['ref']['digest'] = digest(c['alias_table']['entries'])
    c['graph_digest'] = digest(derive(c, False)['graph'])
    return c
def trust(c): return {digest(c['alias_table'])} | {digest(b) for b in c['input_bindings'] + c['action_bindings']}
def machine():
    c = fixture(); c['program'] = dict(kind='state_machine', states=['on', 'off'], initial_state='on', transitions=[
        dict(transition_id='off', from_state='on', to_state='off', priority=1, trigger_binding_id='event', condition=literal(True),
             exit=[step('exit')], transition=[step('transition')], enter=[step('enter')]),
        dict(transition_id='on', from_state='off', to_state='on', priority=1, trigger_binding_id='event', condition=literal(True),
             exit=[], transition=[step('return')], enter=[])])
    return seal(c)
def parallel():
    c = fixture(); c['program']['groups'][0]['mode'] = 'parallel'
    for s in c['program']['groups'][0]['steps']: s.update(required=True, failure_policy='stop')
    return seal(c)
def artifact(c, proof):
    a = dict(artifact_version=VERSION, artifact_id='artifact', program_digest=digest(c), bindings_digest=bindings_digest(c),
        proof_refs=[dict(id='proof', revision='1', digest=digest(proof))], publisher_ref=content_ref('publisher'),
        review_ref=content_ref('review'), manifest_digest='sha256:' + '0' * 64)
    a['manifest_digest'] = digest({k: v for k, v in a.items() if k != 'manifest_digest'})
    return a


def run():
    checks = []
    def expect(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(id=name, expected=expected, actual=actual))
    def rejects(name, operation, expected):
        try: operation()
        except Invalid as error:
            check_shape('CompileDiagnostic', error.diagnostic); expect(name, error.diagnostic['code'], expected)
        else: raise AssertionError((name, '未拒绝'))
    subprocess.run([sys.executable, str(ROOT / 'build_contracts.py'), '--check'], check=True)
    validator('CompiledProgram').check_schema(build())
    base = fixture(); p = prove(base, 's0', trust(base)); graph = derive(base)['graph']
    expect('graph.sequence', graph['edges'], [dict(from_step_id='s0', to_step_id='s1', edge_kind='sequence'),
                                           dict(from_step_id='s1', to_step_id='s2', edge_kind='sequence')])
    expect('proof.closure', p['successor_step_ids'], ['s1', 's2'])
    expect('proof.independent', p['verdict'], 'independent')
    samples = {'CompiledProgram': base, 'Program': base['program'], 'StateMachine': machine()['program'], 'Graph': graph,
        'IndependenceProof': p, 'PublishedArtifact': artifact(base, p), 'InputBinding': base['input_bindings'][0],
        'ActionBinding': base['action_bindings'][0], 'Condition': compare(), 'AliasTable': base['alias_table']}
    for model, sample in samples.items(): expect('schema.' + model, validator(model).is_valid(sample), True)
    bad = copy.deepcopy(base); bad['dsl_version'] = '0.3'
    expect('schema.old_version', validator('CompiledProgram').is_valid(bad), False)
    bad = copy.deepcopy(base); bad['program_digest'] = digest(base)
    expect('schema.self_digest', validator('CompiledProgram').is_valid(bad), False)
    bad = copy.deepcopy(base); bad['program']['groups'][0]['steps'][0]['independence_proof'] = p
    expect('schema.embedded_proof', validator('CompiledProgram').is_valid(bad), False)
    for name, pointer, expected in [('slash', '/a~1b', ['a/b']), ('tilde', '/~01', ['~1']), ('root', '', []), ('empty', '/', [''])]:
        expect('pointer.' + name, tokens(pointer), expected)
    for name, pointer, error in [('escape', '/~2', 'pointer'), ('fragment', '#/a', 'pointer'),
            ('append', '/-', 'pointer_policy'), ('prototype', '/__proto__', 'pointer_policy'), ('dynamic', '/${x}', 'pointer_policy')]:
        rejects('pointer.' + name, lambda p=pointer: tokens(p), error)
    expect('pointer.object01', lookup({'01': 9}, '/01'), 9)
    rejects('pointer.array01', lambda: lookup([9, 8], '/01'), 'array_index')
    snapshots = {'event': dict(source='event', status='available', data={'value': '9007199254740993', 'null': None})}
    expression_cases = [
        ('big_integer', compare(right=literal('9007199254740992'), op='gt'), 'true'),
        ('string_number', compare(right=literal(900), kind='string'), 'unknown'),
        ('false_zero', compare(literal(False), literal(0), kind='boolean'), 'unknown'),
        ('invalid_ne', compare(literal('10'), literal(10), op='ne', kind='string'), 'unknown'),
        ('null_equal', compare(literal(None), literal(None), kind='null'), 'true'),
        ('object_equal', compare(literal({}), literal({}), kind='json'), 'unknown'),
        ('string_order', compare(literal('2'), literal('10'), op='gt', kind='string'), 'unknown'),
        ('unit_string', compare(literal('1'), literal('1'), kind='string', unit='dB'), 'unknown'),
        ('exists_missing', dict(kind='exists', value=reference(pointer='/missing')), 'false'),
        ('exists_null', dict(kind='exists', value=reference(pointer='/null')), 'true'),
        ('is_null', dict(kind='is_null', value=reference(pointer='/null')), 'true'),
        ('is_null_missing', dict(kind='is_null', value=reference(pointer='/missing')), 'unknown'),
        ('compare_missing', compare(left=reference(pointer='/missing')), 'unknown'),
        ('no_default', compare(left=reference('result', '/value', 'step_result')), 'unknown')]
    for name, expression, expected in expression_cases: expect('eval.' + name, evaluate(expression, snapshots), expected)
    unknown = compare(reference(pointer='/missing'))
    for name, expression, expected in [('all', dict(kind='all', items=[literal(False), unknown]), 'false'),
            ('any', dict(kind='any', items=[literal(True), unknown]), 'true'), ('not', dict(kind='not', item=unknown), 'unknown')]:
        expect('eval.' + name, evaluate(expression, snapshots), expected)
    for status in ('unavailable', 'stale', 'desynchronized'):
        s = copy.deepcopy(snapshots); s['event']['status'] = status
        expect('eval.not_exists_' + status, evaluate(dict(kind='not', item=dict(kind='exists', value=reference())), s), 'unknown')
    for value in ('-0', '01', '1e2', '1\n', '100000000000000000000'):
        expect('eval.lexeme_' + repr(value), evaluate(compare(literal(value), literal(value)), {}), 'unknown')
    for expression, error in [(dict(kind='all', items=[]), 'schema'), (dict(kind='literal', value=1), 'schema')]:
        rejects('condition.reject_' + str(len(checks)), lambda e=expression: check_shape('Condition', e), error)
    nested = literal(True)
    for _ in range(16): nested = dict(kind='not', item=nested)
    rejects('budget.depth', lambda: condition_nodes(nested), 'budget')
    wide = dict(kind='all', items=[literal(True)] * 256)
    rejects('budget.nodes', lambda: condition_nodes(wide), 'budget')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][1]['guard'] = compare()
    c['input_bindings'][0]['projections'][0]['reads'] = ['device/a']; seal(c)
    expect('proof.implicit_guard_read', prove(c, 's0', trust(c))['verdict'], 'dependent')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][1]['guard'] = dict(kind='any', items=[literal(True), compare()])
    c['input_bindings'][0]['projections'][0]['reads'] = ['device/a']; seal(c)
    expect('proof.no_short_circuit_omission', prove(c, 's0', trust(c))['verdict'], 'dependent')
    c = copy.deepcopy(base); c['input_bindings'].append(input_binding('result', 'step_result', 's0'))
    c['program']['groups'][0]['steps'][2]['parameter_bindings'] = [dict(target_pointer='/value', value=reference('result', '/value', 'step_result'))]; seal(c)
    expect('proof.result_dependency', prove(c, 's0', trust(c))['verdict'], 'dependent')
    c['input_bindings'][-1]['schema_ref']['revision'] = '2'
    rejects('proof.result_schema_mismatch', lambda: seal(c), 'producer_schema')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][2]['depends_on'] = ['s0']; seal(c)
    expect('proof.success_dependency', prove(c, 's0', trust(c))['verdict'], 'dependent')
    for field in ('reads', 'writes', 'failure_writes', 'resources', 'preconditions', 'target_constraints'):
        c = copy.deepcopy(base); c['action_bindings'][1]['footprint'][field] = ['device/a/child']; seal(c)
        expect('proof.overlap_' + field, prove(c, 's0', trust(c))['verdict'], 'dependent')
    c = copy.deepcopy(base); c['action_bindings'][1]['footprint']['reads'] = ['device/ab']; seal(c)
    expect('proof.segment_boundary', prove(c, 's0', trust(c))['verdict'], 'independent')
    c = copy.deepcopy(base); c['action_bindings'][0]['footprint']['writes'] = []
    c['action_bindings'][0]['footprint']['failure_writes'] = ['device/a']; c['action_bindings'][1]['footprint']['reads'] = ['device/a']; seal(c)
    expect('proof.failure_write', prove(c, 's0', trust(c))['verdict'], 'dependent')
    c = copy.deepcopy(base); c['alias_table']['entries'] = [dict(logical='alias/channel', physical='device/a')]
    c['action_bindings'][1]['footprint']['reads'] = ['alias/channel']; seal(c)
    expect('proof.physical_alias', prove(c, 's0', trust(c))['verdict'], 'dependent')
    c['alias_table']['entries'].append(dict(logical='alias/channel/fader', physical='device/b'))
    rejects('alias.ambiguous', lambda: seal(c), 'ambiguous_alias')
    c = copy.deepcopy(base); c['alias_table']['entries'] = [dict(logical='alias', physical='alias/a')]
    rejects('alias.recursive', lambda: seal(c), 'recursive_alias')
    expect('proof.untrusted', prove(base, 's0', set())['verdict'], 'unknown')
    for index in (0, 1):
        c = copy.deepcopy(base); c['action_bindings'][index]['footprint']['complete'] = False; seal(c)
        expect('proof.incomplete_' + str(index), prove(c, 's0', trust(c))['verdict'], 'unknown')
    for name, edit, error in [
        ('duplicate', lambda s: s[1].update(step_id='s0'), 'duplicate_step'),
        ('missing', lambda s: s[0].update(depends_on=['absent']), 'dependency_reference'),
        ('self', lambda s: s[0].update(depends_on=['s0']), 'dependency_order'),
        ('forward', lambda s: s[0].update(depends_on=['s2']), 'dependency_order'),
        ('cycle', lambda s: (s[0].update(depends_on=['s2']), s[2].update(depends_on=['s0'])), 'dependency_order')]:
        c = copy.deepcopy(base); edit(c['program']['groups'][0]['steps']); rejects('graph.' + name, lambda: seal(c), error)
    c = machine(); expect('graph.state_loop', len(derive(c)['steps']), 4)
    c['program']['transitions'][1]['transition'][0]['depends_on'] = ['exit']
    rejects('graph.exclusive_transition', lambda: seal(c), 'dependency_order')
    c = parallel(); expect('graph.parallel', derive(c)['graph']['edges'], [])
    expect('parallel.qualified', parallel_qualified(c, trust(c)), True)
    expect('parallel.untrusted', parallel_qualified(c, set()), False)
    incomplete = copy.deepcopy(c); incomplete['action_bindings'][1]['footprint']['complete'] = False; seal(incomplete)
    expect('parallel.incomplete', parallel_qualified(incomplete, trust(incomplete)), False)
    c['program']['groups'][0]['steps'][1]['depends_on'] = ['s0']
    rejects('graph.parallel_wait', lambda: seal(c), 'dependency_order')
    c = parallel(); c['action_bindings'][1]['footprint']['reads'] = ['device/a']
    rejects('graph.parallel_conflict', lambda: seal(c), 'parallel_conflict')
    c = parallel(); c['program']['groups'][0]['steps'][0].update(required=False, failure_policy='continue_if_independent')
    rejects('graph.parallel_optional', lambda: seal(c), 'required_group')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][1]['parameter_bindings'] = [
        dict(target_pointer='/value', value=literal('1')), dict(target_pointer='/value/child', value=literal('2'))]
    rejects('parameters.overlap', lambda: seal(c), 'parameter_overlap')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][1]['guard'] = compare(kind='binary64', right=literal(1))
    rejects('parameters.type_binding', lambda: seal(c), 'type_binding')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][1]['guard'] = compare(left=reference(pointer='/no_such_field'))
    rejects('parameters.projection', lambda: seal(c), 'projection_binding')
    c = copy.deepcopy(base); c['program']['groups'][0]['steps'][1]['parameters'] = {'nested': {'step_id': 'data', 'independence_proof': 'a', 'kind': 'ref'}}; seal(c)
    before = digest(c); c['program']['groups'][0]['steps'][1]['parameters']['nested']['independence_proof'] = 'b'
    expect('digest.business_data_retained', digest(c) == before, False)
    expect('graph.business_data_opaque', derive(c)['graph'], graph)
    c = fixture(301); c['action_bindings'].append(action('last', reads=['device/a']))
    c['program']['groups'][-1]['steps'][-1]['action_binding_id'] = 'last'; seal(c)
    large = prove(c, 's0', trust(c)); expect('proof.300_successors', len(large['successor_step_ids']), 300)
    expect('proof.late_dependency', large['verdict'], 'dependent')
    bad = copy.deepcopy(large); bad['successor_step_ids'] = bad['successor_step_ids'][:256]
    expect('proof.truncated', proof_error(c, bad, trust(c)), 'proof_binding')
    c = fixture(4096); expect('graph.4096_steps', len(derive(c)['graph']['nodes']), 4096)
    expect('proof.4095_successors', len(prove(c, 's0', trust(c))['successor_step_ids']), 4095)
    c['program']['groups'].append(dict(mode='sequence', steps=[step('overflow')]))
    rejects('budget.group_limit', lambda: seal(c), 'schema')
    bad = copy.deepcopy(p); bad['verdict'] = 'dependent'
    expect('proof.claim_not_trusted', proof_error(base, bad, trust(base)), 'proof_binding')
    c = copy.deepcopy(base); c['action_bindings'][1]['catalog_ref']['revision'] = '2'; seal(c)
    expect('proof.binding_changed', proof_error(c, p, trust(c)), 'proof_binding')
    context = dict(outcome='failed', failure_class='definite_rejection', resource_status='clear',
        release_proved=True, gates_valid=True, current_bindings=True)
    expect('continue.safe', continue_after_failure(base, p, trust(base), context), True)
    for field, value in [('outcome', 'unknown'), ('outcome', 'blocked'), ('outcome', 'expired'), ('outcome', 'cancelled'),
            ('failure_class', 'transport_timeout'), ('resource_status', 'uncertain'), ('release_proved', False),
            ('gates_valid', False), ('current_bindings', False)]:
        ctx = dict(context); ctx[field] = value
        expect('continue.reject_' + field + '_' + str(value), continue_after_failure(base, p, trust(base), ctx), False)
    a = artifact(base, p); records = {('proof', '1'): p}
    expect('artifact.valid', artifact_error(base, a, records, trust(base)), None)
    bad = copy.deepcopy(a); bad['proof_refs'] = []; bad['manifest_digest'] = digest({k: v for k, v in bad.items() if k != 'manifest_digest'})
    expect('artifact.missing_proof', artifact_error(base, bad, {}, trust(base)), 'proof_coverage')
    bad = copy.deepcopy(a); bad['proof_refs'][0]['digest'] = digest({'wrong': True}); bad['manifest_digest'] = digest({k: v for k, v in bad.items() if k != 'manifest_digest'})
    expect('artifact.rehashed_wrong_proof', artifact_error(base, bad, records, trust(base)), 'proof_ref')
    bad = copy.deepcopy(a); bad['proof_refs'][0]['revision'] = '2'; bad['manifest_digest'] = digest({k: v for k, v in bad.items() if k != 'manifest_digest'})
    expect('artifact.wrong_proof_revision', artifact_error(base, bad, records, trust(base)), 'proof_ref')
    expect('artifact.unapproved', artifact_error(base, a, records, set()), 'unapproved_binding')
    expect('checks.unique', len({v['id'] for v in checks}), len(checks))
    return dict(contract=VERSION, approved=False, scope='合成程序与有限AST求值、结构派生图及证明和发布关联；非业务引擎或权威提供者',
        checks_passed=len(checks), all_passed=True, checks=checks,
        runtime_validation=dict(services=0, sqlite=0, concurrent_execution=0, devices=0, full_parameter_schema_validation=0),
        versions=dict(python=platform.python_version(), jsonschema=version('jsonschema'), rfc8785=version('rfc8785')),
        input_sha256={p.relative_to(SUITE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})


def main():
    p = argparse.ArgumentParser(); p.add_argument('--report', action='store_true'); p.add_argument('--check-report', action='store_true')
    p.add_argument('--staged', action='store_true'); a = p.parse_args(); report_path = ROOT / 'reference-report.json'
    if a.staged and not a.check_report: p.error('--staged只配合--check-report')
    if a.check_report:
        def read(path):
            relative = path.relative_to(SUITE).as_posix()
            return subprocess.check_output(['git', 'show', ':' + relative], cwd=SUITE) if a.staged else path.read_bytes()
        report = json.loads(read(report_path)); expected = {p.relative_to(SUITE).as_posix() for p in INPUTS}
        assert set(report['input_sha256']) == expected
        for path in INPUTS: assert hashlib.sha256(read(path)).hexdigest() == report['input_sha256'][path.relative_to(SUITE).as_posix()], path
        print(json.dumps(dict(report_bindings_passed=len(expected), staged=a.staged))); return
    report = run()
    if a.report: report_path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({k: v for k, v in report.items() if k not in ('checks', 'input_sha256')}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
