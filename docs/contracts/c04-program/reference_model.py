"""仅供合成设计用例的有限模型；无网络、设备出口、持久化或产品调用入口。"""
import hashlib
import math
import re
import rfc8785
from jsonschema import Draft202012Validator
from build_contracts import build, VERSION

SCHEMA = build()
LIMITS = dict(expression_depth=16, expression_nodes=256, total_nodes=16384,
              steps=4096, program_bytes=16777216, edges=131072, resource_comparisons=1048576)
MISSING, UNAVAILABLE = object(), object()


class Invalid(ValueError):
    def __init__(self, code, path='', budget=None):
        self.diagnostic = dict(code=code, definition_path=path, related_paths=[], budget=budget)
        super().__init__(code)


def digest(value): return 'sha256:' + hashlib.sha256(rfc8785.dumps(value)).hexdigest()
def ordered(values): return sorted(values, key=rfc8785.dumps)
def validator(model):
    return Draft202012Validator({'$defs': SCHEMA['$defs'], '$ref': '#/$defs/' + model})


def check_shape(model, value):
    if not validator(model).is_valid(value): raise Invalid('schema')


def limit(kind, observed, path=''):
    if observed > LIMITS[kind]:
        raise Invalid('budget', path, dict(kind=kind, limit=LIMITS[kind], observed=observed))


def tokens(pointer):
    if not isinstance(pointer, str) or not re.fullmatch(r'(?:/(?:[^~/]|~[01])*)*', pointer):
        raise Invalid('pointer')
    result = [] if pointer == '' else [s.replace('~1', '/').replace('~0', '~') for s in pointer[1:].split('/')]
    if any(s in ('-', '__proto__', 'prototype', 'constructor') or '${' in s for s in result):
        raise Invalid('pointer_policy')
    return result


def lookup(value, pointer):
    for token in tokens(pointer):
        if isinstance(value, dict):
            if token not in value: return MISSING
            value = value[token]
        elif isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', token): raise Invalid('array_index')
            index = int(token)
            if index >= len(value): return MISSING
            value = value[index]
        else: return MISSING
    return value


def typed(value, spec):
    kind = spec['kind']
    if kind in ('boolean', 'null', 'string', 'json') and spec['unit'] is not None: raise Invalid('unit')
    valid = {'boolean': type(value) is bool, 'null': value is None,
             'string': type(value) is str, 'json': True,
             'binary64': (type(value) is int and abs(value) <= 9007199254740991) or (type(value) is float and math.isfinite(value)),
             'integer_string': isinstance(value, str) and bool(re.fullmatch(r'(?:0|-?[1-9][0-9]{0,19})', value))}[kind]
    if not valid: raise Invalid('value_type')
    return int(value) if kind == 'integer_string' else value


def condition_nodes(root):
    stack = [(root, 1)]; nodes = []
    while stack:
        node, depth = stack.pop(); limit('expression_depth', depth)
        nodes.append(node); limit('expression_nodes', len(nodes))
        if not isinstance(node, dict): raise Invalid('schema')
        if node.get('kind') in ('all', 'any'):
            stack.extend((v, depth + 1) for v in node.get('items', []))
        elif node.get('kind') == 'not': stack.append((node.get('item'), depth + 1))
        elif node.get('kind') == 'compare':
            stack.extend((node.get(k), depth + 1) for k in ('left', 'right'))
        elif node.get('kind') in ('exists', 'is_null'): stack.append((node.get('value'), depth + 1))
        # literal.value is data, never an AST or proof, even if it has kind/step_id keys.
    return nodes


def references(root): return [n for n in condition_nodes(root) if n.get('kind') == 'ref']


def resolve(value, snapshots):
    if value['kind'] == 'literal': return value['value']
    source = snapshots.get(value['binding_id'])
    if source is None or source['status'] != 'available' or source['source'] != value['source']:
        return UNAVAILABLE
    if value['source'] == 'step_result' and not source.get('successful_evidence', False): return UNAVAILABLE
    return lookup(source['data'], value['pointer'])


def evaluate(condition, snapshots):
    """仅在结构/类型绑定检查之后调用；来源状态和证据由人工夹具提供。"""
    kind = condition['kind']
    if kind == 'literal': return 'true' if condition['value'] else 'false'
    if kind in ('exists', 'is_null'):
        value = resolve(condition['value'], snapshots)
        if value is UNAVAILABLE: return 'unknown'
        if kind == 'is_null' and value is MISSING: return 'unknown'
        answer = value is not MISSING if kind == 'exists' else value is None
        return 'true' if answer else 'false'
    if kind == 'not': return {'true': 'false', 'false': 'true', 'unknown': 'unknown'}[evaluate(condition['item'], snapshots)]
    if kind in ('all', 'any'):
        values = [evaluate(x, snapshots) for x in condition['items']]
        decisive, neutral = ('false', 'true') if kind == 'all' else ('true', 'false')
        return decisive if decisive in values else ('unknown' if 'unknown' in values else neutral)
    a, b = resolve(condition['left'], snapshots), resolve(condition['right'], snapshots)
    if any(v is MISSING or v is UNAVAILABLE for v in (a, b)): return 'unknown'
    spec, op = condition['value_type'], condition['operator']
    if spec['kind'] == 'json' or (op not in ('eq', 'ne') and spec['kind'] not in ('binary64', 'integer_string')):
        return 'unknown'
    try: a, b = typed(a, spec), typed(b, spec)
    except Invalid: return 'unknown'
    if op == 'eq': answer = a == b
    elif op == 'ne': answer = a != b
    elif op == 'lt': answer = a < b
    elif op == 'lte': answer = a <= b
    elif op == 'gt': answer = a > b
    else: answer = a >= b
    return 'true' if answer else 'false'


def prefix(a, b): return len(a) <= len(b) and a == b[:len(a)]
def overlap(a, b):
    x, y = a.split('/'), b.split('/')
    return prefix(x, y) or prefix(y, x)


def alias_resource(resource, table):
    parts = resource.split('/')
    for entry in table['entries']:
        source = entry['logical'].split('/')
        if prefix(source, parts): return '/'.join(entry['physical'].split('/') + parts[len(source):])
    return resource


def bindings_digest(compiled):
    return digest({k: compiled[k] for k in ('input_bindings', 'action_bindings', 'alias_table')})


def flatten(program):
    groups, roots = [], []
    if program['kind'] == 'rule':
        roots.append((program['condition'], '/program/condition', program['trigger_binding_id']))
        groups = [('rule', n, g, f'/program/groups/{n}') for n, g in enumerate(program['groups'])]
    else:
        states = set(program['states']); transition_ids = set()
        if program['initial_state'] not in states: raise Invalid('state_reference')
        for i, t in enumerate(program['transitions']):
            path = f'/program/transitions/{i}'
            if t['transition_id'] in transition_ids: raise Invalid('duplicate_transition', path)
            transition_ids.add(t['transition_id'])
            if t['from_state'] not in states or t['to_state'] not in states: raise Invalid('state_reference', path)
            roots.append((t['condition'], path + '/condition', t['trigger_binding_id']))
            for rank, phase in enumerate(('exit', 'transition', 'enter')):
                groups.append((t['transition_id'], rank, dict(mode='sequence', steps=t[phase]), path + '/' + phase))
    return groups, roots


def derive(compiled, check_digest=True):
    """从指定结构派生完整图；不遍历业务字面量猜测步骤或引用。"""
    raw = rfc8785.dumps(compiled); limit('program_bytes', len(raw))
    # 先有界遍历AST，再递归JSON Schema校验；原始JSON字节入口仍属于DF01。
    program = compiled['program']; groups, roots = flatten(program)
    expressions = [(c, p) for c, p, _ in roots]
    for _, _, group, path in groups:
        expressions.extend((s['guard'], path + f'/steps/{i}/guard')
                           for i, s in enumerate(group['steps']) if s['kind'] == 'action')
    total = sum(len(condition_nodes(c)) for c, _ in expressions)
    total += sum(len(s['parameter_bindings']) for _, _, g, _ in groups for s in g['steps'] if s['kind'] == 'action')
    limit('total_nodes', total)
    check_shape('CompiledProgram', compiled)
    inputs = {v['binding_id']: v for v in compiled['input_bindings']}
    actions = {v['binding_id']: v for v in compiled['action_bindings']}
    if len(inputs) != len(compiled['input_bindings']) or len(actions) != len(compiled['action_bindings']): raise Invalid('duplicate_binding')
    for b in inputs.values():
        if (b['source'] == 'step_result') != (b['producer_step_id'] is not None): raise Invalid('producer_binding')
        pointers = [v['pointer'] for v in b['projections']]
        if len(pointers) != len(set(pointers)): raise Invalid('duplicate_projection')
        for p in pointers: tokens(p)
    table = compiled['alias_table']; aliases = table['entries']
    for i, a in enumerate(aliases):
        if any(overlap(a['logical'], b['logical']) for b in aliases[:i]): raise Invalid('ambiguous_alias')
        if any(overlap(a['physical'], b['logical']) for b in aliases): raise Invalid('recursive_alias')
    if digest(aliases) != table['ref']['digest']: raise Invalid('alias_digest')
    steps, positions, paths, edges = {}, {}, {}, set()
    def add(a, b, kind):
        edges.add((a, b, kind)); limit('edges', len(edges))
    prior = {}
    for branch, rank, group, path in groups:
        front = []
        for i, step in enumerate(group['steps']):
            sid = step['step_id']
            if sid in steps: raise Invalid('duplicate_step', path)
            steps[sid], paths[sid] = step, path + f'/steps/{i}'
            positions[sid] = (branch, rank, i if group['mode'] == 'sequence' else 0)
            if group['mode'] == 'parallel' or program['kind'] == 'state_machine':
                if not step['required'] or step['failure_policy'] != 'stop': raise Invalid('required_group', paths[sid])
            if step['required'] and step['failure_policy'] != 'stop': raise Invalid('required_policy', paths[sid])
            front.append(sid)
            if group['mode'] == 'sequence' and i: add(front[i-1], sid, 'sequence')
        if not front: continue
        first = front[:1] if group['mode'] == 'sequence' else front
        for a in prior.get(branch, []):
            for b in first: add(a, b, 'sequence')
        prior[branch] = front[-1:] if group['mode'] == 'sequence' else front
    limit('steps', len(steps))
    simple = program['kind'] == 'rule' and all(g['mode'] == 'sequence' for g in program['groups'])
    def earlier(a, b): return positions[a][0] == positions[b][0] and positions[a][1:] < positions[b][1:]
    for b in inputs.values():
        if b['source'] != 'step_result': continue
        producer = steps.get(b['producer_step_id'])
        if producer is None or producer['kind'] != 'action': raise Invalid('producer_reference')
        action = actions.get(producer['action_binding_id'])
        if action is None or b['schema_ref'] != action['result_schema_ref']: raise Invalid('producer_schema')
    def resolve_binding(v, expected=None, consumer=None, edge_kind='data'):
        b = inputs.get(v['binding_id'])
        if b is None or b['source'] != v['source']: raise Invalid('input_binding')
        projection = next((p for p in b['projections'] if p['pointer'] == v['pointer']), None)
        if projection is None: raise Invalid('projection_binding')
        if expected is not None and projection['value_type'] != expected: raise Invalid('type_binding')
        producer = b['producer_step_id']
        if producer is not None:
            if consumer is None or not earlier(producer, consumer): raise Invalid('dependency_order')
            add(producer, consumer, edge_kind)
        return projection['reads']
    def check_condition(condition, consumer=None):
        reads = []
        for node in condition_nodes(condition):
            kind = node['kind']
            if kind == 'ref': reads.extend(resolve_binding(node, consumer=consumer, edge_kind='guard'))
            if kind != 'compare': continue
            spec = node['value_type']
            if spec['kind'] == 'json' or (node['operator'] not in ('eq', 'ne') and spec['kind'] not in ('binary64', 'integer_string')):
                raise Invalid('comparison_type')
            for key in ('left', 'right'):
                v = node[key]
                if v['kind'] == 'literal': typed(v['value'], spec)
                else: resolve_binding(v, spec, consumer, 'guard')
        return reads
    for condition, path, trigger in roots:
        if trigger not in inputs or inputs[trigger]['source'] != 'event': raise Invalid('trigger_binding', path)
        check_condition(condition)
    footprints, used_bindings = {}, {}
    for sid, step in steps.items():
        for predecessor in step['depends_on']:
            if predecessor not in steps: raise Invalid('dependency_reference', paths[sid])
            if not earlier(predecessor, sid): raise Invalid('dependency_order', paths[sid])
            add(predecessor, sid, 'requires_success')
        if step['failure_policy'] == 'continue_if_independent' and not simple: raise Invalid('optional_context', paths[sid])
        if step['kind'] == 'delay':
            footprints[sid] = dict(complete=True, reads=[], writes=[], failure_writes=[], resources=[], preconditions=[], target_constraints=[])
            used_bindings[sid] = set(); continue
        action = actions.get(step['action_binding_id'])
        if action is None: raise Invalid('action_binding', paths[sid])
        f = {k: list(v) if isinstance(v, list) else v for k, v in action['footprint'].items()}
        f['reads'] += check_condition(step['guard'], sid)
        slots = {p['pointer']: p['value_type'] for p in action['parameter_slots']}
        if len(slots) != len(action['parameter_slots']): raise Invalid('duplicate_slot')
        targets = []
        for p in action['parameter_slots']: tokens(p['pointer'])
        for p in step['parameter_bindings']:
            target = tokens(p['target_pointer'])
            if any(prefix(target, prev) or prefix(prev, target) for prev in targets): raise Invalid('parameter_overlap', paths[sid])
            targets.append(target)
            spec = slots.get(p['target_pointer'])
            if spec is None: raise Invalid('parameter_slot', paths[sid])
            if p['value']['kind'] == 'literal': typed(p['value']['value'], spec)
            else: f['reads'] += resolve_binding(p['value'], spec, sid)
        used = references(step['guard']) + [p['value'] for p in step['parameter_bindings'] if p['value']['kind'] == 'ref']
        used_bindings[sid] = {digest(action)} | {digest(inputs[v['binding_id']]) for v in used}
        footprints[sid] = f
    for f in footprints.values():
        for key in ('reads', 'writes', 'failure_writes', 'resources', 'preconditions', 'target_constraints'):
            f[key] = ordered(set(alias_resource(v, table) for v in f[key]))
    comparisons = 0
    def conflicts(a, b):
        nonlocal comparisons
        af, bf = footprints[a], footprints[b]
        affected = af['writes'] + af['failure_writes'] + af['resources']
        downstream = sum((bf[k] for k in ('reads', 'writes', 'failure_writes', 'resources', 'preconditions', 'target_constraints')), [])
        for x in affected:
            for y in downstream:
                comparisons += 1; limit('resource_comparisons', comparisons)
                if overlap(x, y): return True
        return False
    for i, a in enumerate(steps):
        for b in list(steps)[i+1:]:
            if positions[a][0] != positions[b][0]: continue
            if earlier(a, b):
                if conflicts(a, b): add(a, b, 'resource')
            elif earlier(b, a):
                if conflicts(b, a): add(b, a, 'resource')
            elif conflicts(a, b) or conflicts(b, a): raise Invalid('parallel_conflict')
    graph = dict(graph_version='automation-graph/1', nodes=ordered(steps),
        edges=[dict(from_step_id=a, to_step_id=b, edge_kind=k) for a, b, k in
               sorted(edges, key=lambda e: tuple(rfc8785.dumps(v) for v in e))], alias_table_ref=table['ref'])
    if check_digest and compiled['graph_digest'] != digest(graph): raise Invalid('graph_digest')
    return dict(graph=graph, steps=steps, positions=positions, footprints=footprints,
                used_bindings=used_bindings, simple_sequence=simple)


def prove(compiled, failed, trusted_digests):
    derived = derive(compiled); graph = derived['graph']; steps = derived['steps']
    if failed not in steps: raise Invalid('failed_step_reference')
    successors, pending = set(), [failed]
    adjacency = {sid: [] for sid in steps}
    for edge in graph['edges']: adjacency[edge['from_step_id']].append(edge['to_step_id'])
    while pending:
        for child in adjacency[pending.pop()]:
            if child not in successors: successors.add(child); pending.append(child)
    relevant = successors | {failed}
    required_bindings = {digest(compiled['alias_table'])}
    for sid in relevant: required_bindings |= derived['used_bindings'][sid]
    known = required_bindings <= trusted_digests and all(derived['footprints'][s]['complete'] for s in relevant)
    dependency = any(e['from_step_id'] == failed and e['edge_kind'] != 'sequence' for e in graph['edges'])
    proof = dict(proof_version=VERSION, generator_version='reference-model-1', program_digest=digest(compiled),
        bindings_digest=bindings_digest(compiled), graph_digest=compiled['graph_digest'], failed_step_id=failed,
        successor_step_ids=ordered(successors), footprint_binding_digests=ordered(required_bindings),
        verdict='unknown' if not known else ('dependent' if dependency else 'independent'))
    check_shape('IndependenceProof', proof)
    return proof


def proof_error(compiled, proof, trusted_digests):
    check_shape('IndependenceProof', proof)
    expected = prove(compiled, proof['failed_step_id'], trusted_digests)
    return None if proof == expected else 'proof_binding'


def continue_after_failure(compiled, proof, trusted, context):
    if proof_error(compiled, proof, trusted): return False
    derived = derive(compiled); step = derived['steps'][proof['failed_step_id']]
    if step['kind'] != 'action': return False
    safe = derived['footprints'][step['step_id']]['safe_failure_classes']
    return (derived['simple_sequence'] and not step['required'] and step['failure_policy'] == 'continue_if_independent'
        and proof['verdict'] == 'independent' and context['outcome'] == 'failed'
        and context['failure_class'] in safe and context['resource_status'] == 'clear'
        and context['release_proved'] and context['gates_valid'] and context['current_bindings'])


def parallel_qualified(compiled, trusted):
    result = derive(compiled)
    for _, _, group, _ in flatten(compiled['program'])[0]:
        if group['mode'] != 'parallel': continue
        for step in group['steps']:
            sid = step['step_id']
            if not result['footprints'][sid]['complete'] or not result['used_bindings'][sid] <= trusted: return False
        if digest(compiled['alias_table']) not in trusted: return False
    return True


def artifact_error(compiled, artifact, proofs, trusted):
    check_shape('PublishedArtifact', artifact)
    derived = derive(compiled)
    if not ({digest(compiled['alias_table'])} | {digest(b) for b in compiled['input_bindings'] + compiled['action_bindings']}) <= trusted:
        return 'unapproved_binding'
    if not parallel_qualified(compiled, trusted): return 'parallel_unqualified'
    if artifact['program_digest'] != digest(compiled) or artifact['bindings_digest'] != bindings_digest(compiled): return 'artifact_binding'
    if artifact['manifest_digest'] != digest({k: v for k, v in artifact.items() if k != 'manifest_digest'}): return 'manifest_digest'
    expected = {s for s, v in derived['steps'].items() if v['failure_policy'] == 'continue_if_independent'}
    seen, ref_ids = set(), set()
    for reference in artifact['proof_refs']:
        if reference['id'] in ref_ids: return 'duplicate_proof'
        ref_ids.add(reference['id']); proof = proofs.get((reference['id'], reference['revision']))
        if proof is None or reference['digest'] != digest(proof): return 'proof_ref'
        if proof_error(compiled, proof, trusted) or proof['verdict'] != 'independent': return 'proof_unqualified'
        if proof['failed_step_id'] in seen: return 'duplicate_proof'
        seen.add(proof['failed_step_id'])
    return None if seen == expected else 'proof_coverage'
