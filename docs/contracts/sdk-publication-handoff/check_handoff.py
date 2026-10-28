"""固定两包成果并实际重跑隔离存储及动态提供者，不执行生产服务。"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parent;SUITE=ROOT.parents[2]
HELPER=ROOT.parent/'sdk-transport-handoff/check_handoff.py'
spec=importlib.util.spec_from_file_location('publication_handoff_helpers',HELPER)
H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
DESIGNS=['README.md','docs/ROADMAP.md','docs/rebirth-readiness.md','docs/rebirth-design-closure.md','docs/rebirth-df01-sdk-freeze.md','docs/rebirth-c09-extension-design.md']
NAMES=['publication-current','panel-current']
BOUNDARIES=['stage0_complete','all_provider_sources_connected','production_authorization_executed','production_database_migrated','product_business_executed','device_executed','browser_rerun']

def inputs():
    paths=[p for p in ROOT.iterdir() if p.is_file() and p.name!='report.json']+[SUITE/p for p in DESIGNS]+[HELPER]
    return {p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in sorted(paths)}

def inspect_manifest(m):
    H.require(m['format']=='sdk-publication-handoff/1' and m['approved'] is False and m['runtime_ready'] is False,'交接资格')
    H.require(m['sdk_repository']=='https://github.com/LeafSeamer/leafseamer-sdk.git','仓库目标')
    H.require(m['sdk_main_commit']=='aff5ccbb75b6140109f948f81284785c75e46d1e','固定SDK主线')
    H.require(m['historical_browser_suite_commit']=='ffbbbff196a13a9f477db9bee83ffd1066f0b815','历史浏览器身份')
    H.require(set(m['boundaries'])==set(BOUNDARIES) and all(m['boundaries'][k] is False for k in BOUNDARIES),'不能扩大完成边界')
    H.require([p['name'] for p in m['packages']]==NAMES,'成果集合')
    union={}
    for p,commit in zip(m['packages'],['ca785b21ce17a1a906c9c6d8082f65596f183f9e',m['sdk_main_commit']]):
        H.require(p['commit']==commit and p['report']=='contracts/'+p['name']+'/report.json','成果身份')
        for name,digest in p['files'].items():
            H.path_name(name);H.require(name not in union or union[name]==digest,'包间原件冲突');union[name]=digest
    H.require(union==m['snapshot_files'],'快照必须完整')

def run(sdk):
    m=H.decode((ROOT/'manifest.json').read_bytes());inspect_manifest(m);checks=[]
    def check(name,ok=True):H.require(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn):
        try:fn()
        except (ValueError,KeyError,AssertionError):check(name)
        else:raise AssertionError(name+':未拒绝')
    check('仓库归属',H.git(sdk,'remote','get-url','origin').decode().strip()==m['sdk_repository'])
    check('SDK主线包含固定提交',subprocess.run(['git','merge-base','--is-ancestor',m['sdk_main_commit'],'main'],cwd=sdk,capture_output=True).returncode==0)
    files=H.read_fixed(sdk,m['sdk_main_commit'],m['snapshot_files'])
    check('最终快照字节',all(H.sha(raw)==m['snapshot_files'][p] for p,raw in files.items()))
    check('当前完整选择',H.decode(files['contracts/panel-wire/contract/selection.json'])==m['selection'])
    for p in m['packages']:
        original=H.read_fixed(sdk,p['commit'],p['files'])
        check('成果提交字节:'+p['name'],all(original[n]==files[n] and H.sha(b)==p['files'][n] for n,b in original.items()))
        r=H.decode(original[p['report']]);expected=dict(r['inputs']);expected[p['report']]=H.sha(original[p['report']])
        check('完整报告输入:'+p['name'],expected==p['files'])
        check('成果候选资格:'+p['name'],r['all_passed'] is True and r['approved'] is False and r['runtime_ready'] is False)
    for name,mutate in [('漏包',lambda v:v['packages'].pop()),('遗漏快照',lambda v:v['snapshot_files'].pop(next(iter(v['snapshot_files'])))),
                        ('重标来源提交',lambda v:v['packages'][0].update(commit=v['sdk_main_commit'])),
                        ('虚报完整提供者',lambda v:v['boundaries'].update(all_provider_sources_connected=True)),
                        ('虚报生产迁移',lambda v:v['boundaries'].update(production_database_migrated=True)),
                        ('虚报浏览器复验',lambda v:v['boundaries'].update(browser_rerun=True)),
                        ('虚报阶段完成',lambda v:v['boundaries'].update(stage0_complete=True))]:
        bad=copy.deepcopy(m);mutate(bad);denied(name,lambda:inspect_manifest(bad))
    snapshot=SUITE/'logs'/('publication-snapshot-'+uuid.uuid4().hex)
    for name,raw in files.items():
        dest=snapshot/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    # 子进程仅用实际SDK对象库做固定git show；所有行为读写均在隔离快照内。
    env=dict(os.environ,GIT_DIR=H.git(sdk,'rev-parse','--absolute-git-dir').decode().strip(),GIT_WORK_TREE=str(snapshot))
    # Git for Windows对深层暂存快照的预解析也须支持长路径，仅影响这些子进程。
    count=int(env.get('GIT_CONFIG_COUNT','0'))
    env.update(GIT_CONFIG_COUNT=str(count+1),**{f'GIT_CONFIG_KEY_{count}':'core.longpaths',f'GIT_CONFIG_VALUE_{count}':'true'})
    reruns={}
    for package in m['packages']:
        name=package['name'];target=snapshot/package['report'];before=target.read_bytes()
        result=subprocess.run([sys.executable,'-B',str(target.parent/'check.py'),'--report'],cwd=snapshot,env=env,capture_output=True,timeout=240)
        (snapshot/(name+'.log')).write_bytes(result.stdout+b'\n'+result.stderr)
        H.require(result.returncode==0,'实际复验失败:'+name+':'+result.stderr.decode('utf8',errors='replace')[-2000:])
        check('实际报告与固定成果完全一致:'+name,target.read_bytes()==before)
        r=H.decode(target.read_bytes());check('实际基础断言完整:'+name,r['cases_passed']==len(r['checks']) and all(c['passed'] is True for c in r['checks']))
        detail=r['migration'] if name=='publication-current' else r['publication_source']
        check('实际扩展断言完整:'+name,detail['all_passed'] and detail['cases_passed']==len(detail['checks']) and all(c['passed'] is True for c in detail['checks']))
        reruns[name]=dict(report_sha256=H.sha(target.read_bytes()),cases_passed=r['cases_passed'],detail_cases_passed=detail['cases_passed'])
        if name=='panel-current':
            check('动态原件运行边界',r['validator_subprocess_calls']==30 and r['database_tests_executed']==1 and detail['journal_mode']=='WAL' and not detail['production_database_migrated'])
    check('全部SDK快照原件仍一致',all((snapshot/p).read_bytes()==b for p,b in files.items()))
    return dict(format='sdk-publication-handoff-check/1',all_passed=True,approved=False,runtime_ready=False,cases_passed=len(checks),checks=checks,
                sdk_commit=m['sdk_main_commit'],snapshot_files=len(files),package_file_bindings=sum(len(p['files']) for p in m['packages']),
                actual_reruns=reruns,python_sha256=H.sha(Path(sys.executable).read_bytes()),boundaries=m['boundaries'],input_sha256=inputs())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path);parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');args=parser.parse_args()
    if args.check_report:
        r=H.decode((ROOT/'report.json').read_bytes());H.require(r['all_passed'] and r['input_sha256']==inputs(),'报告输入漂移');print('报告输入一致；未重跑行为')
    else:
        if not args.sdk:parser.error('需要--sdk')
        r=run(args.sdk.resolve())
        if args.report:(ROOT/'report.json').write_bytes(H.encode(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ['checks','input_sha256']},ensure_ascii=False))
