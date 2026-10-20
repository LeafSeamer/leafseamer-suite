"""一次性提取六份历史文件为候选源；不调用旧生成器，不修改历史输入。"""
import argparse
import copy
from pathlib import Path
import re

from assemble_candidate import OUTPUTS, assemble, decode, encode, sha, verify_outputs


def extract(baseline, destination, commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('必须记录完整来源commit；其真实性由独立对账检查')
    originals = {name: (baseline / name).read_bytes() for name in OUTPUTS}
    values = {name: decode(raw) for name, raw in originals.items()}
    public = values['first-loop.schema.json']
    files = {'public.schema.json': public, 'ipc.schema.json': values['ipc.schema.json'],
             'fixtures.json': values['examples.json']}
    for service in ('controller', 'seamer'):
        api = copy.deepcopy(values[service + '.openapi.json'])
        del api['components']['schemas']
        files['http/' + service + '.operations.json'] = api
    files['route-projection.json'] = [
        {'service': r['service'], 'method': r['method'], 'path': r['path'],
         'primary_success_status': r['status'], 'legacy_security_label': r['security']}
        for r in values['routes.json']]
    files['schema-registry.json'] = {
        'ids': {public['$id']: 'public.schema.json', values['ipc.schema.json']['$id']: 'ipc.schema.json'},
        'legacy_openapi_component_order': list(public['$defs']),
        'component_projection_is_public_export_approval': False}
    manifest = {'purpose': 'draft4-equivalence-candidate', 'authority_switched': False,
                'source_repository': 'leafseamer-suite', 'source_commit': commit,
                'source_directory': 'docs/contracts/draft4', 'public_protocol': '1.0.0-draft.4',
                'ipc_protocol': 'ipc/0.3.0-draft.1',
                'license_provenance_paths': ['LICENSE', 'THIRD_PARTY_NOTICES.md', 'LICENSES/legacy-MIT.txt'],
                'files': [{'path': name, 'sha256': sha(encode(value))} for name, value in files.items()],
                'expected_outputs': {name: sha(raw) for name, raw in originals.items()},
                'not_extracted': ['semantic_rule_implementations', 'digest_projections', 'wire_profiles',
                                  'public_internal_export_policy', 'typescript_sdk', 'production_toolchain_lock']}
    out, _ = assemble(files)
    verify_outputs(manifest, out)
    destination.mkdir(parents=False, exist_ok=False)
    for name, value in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode(value))
    (destination / 'source-manifest.json').write_bytes(encode(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    extract(args.baseline, args.destination, args.source_commit)
    print('已提取候选源，六份输出原字节等价；未切换权威源。')


if __name__ == '__main__':
    main()
