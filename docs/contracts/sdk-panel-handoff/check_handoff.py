"""固定提交交接与当前浏览器记录核验；历史报告不是重跑证明。"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid
import rfc8785

ROOT=Path(__file__).resolve().parent;SUITE=ROOT.parents[2]
HELPER=ROOT.parent/'sdk-transport-handoff/check_handoff.py'
spec=importlib.util.spec_from_file_location('handoff_helpers',HELPER);H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
DESIGNS=['README.md','docs/ROADMAP.md','docs/rebirth-readiness.md','docs/rebirth-design-closure.md','docs/rebirth-df01-sdk-freeze.md','docs/rebirth-c09-extension-design.md']
LINE="      await reject('空正文拒共享缓冲:'+i,()=>decoder.assertEmpty(new Uint8Array(new SharedArrayBuffer(0)),b.handle),'shared_buffer');"
CSP="default-src 'none'; script-src 'self'; worker-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"

def materialize(sdk,m):
    files=H.read_fixed(sdk,m['sdk_main_commit'],m['snapshot_files'])
    H.require(all(H.sha(raw)==m['snapshot_files'][p] for p,raw in files.items()),'快照漂移')
    target=SUITE/'logs'/('panel-snapshot-'+uuid.uuid4().hex)
    for p,raw in files.items():
        dest=target/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    return target

def inspect_manifest(m):
    H.require(m['format']=='sdk-panel-handoff/1' and m['approved'] is False and m['runtime_ready'] is False,'交接资格')
    H.require([p['name'] for p in m['packages']]==['panel-wire','panel-http','panel-client'],'交接包集合')
    H.require([p['name'] for p in m['provider_sources']]==['publication-source','panel-dynamic'],'提供者集合')
    H.require(m['provider_selection']==m['previous_selection']!=m['selection'] and m['provider_migration_complete'] is False,'提供者不可自动迁移')
    H.require(m['selection']['contract_id']=='leafseamer.api.v1.panel4' and m['previous_selection']['contract_id']=='leafseamer.api.v1.panel3' and m['legacy_selection']['contract_id']=='leafseamer.api.v1.events2','版本边界')
    union={}
    for p in m['packages']+m['provider_sources']:
        for name,h in p['files'].items():
            H.path_name(name);H.require(name not in union or union[name]==h,'快照版本冲突');union[name]=h
    H.require(union==m['snapshot_files'],'快照集合')
    H.require(m['boundaries']==dict(stage0_complete=False,business_implementation_started=False,production_sdk_ready=False,runtime_protocol_frozen=False),'阶段边界')
    H.require(m['cycle']==dict(rounds=[dict(round=1,repository='leafseamer-sdk',commit=m['packages'][0]['commit']),dict(round=2,repository='leafseamer-sdk',commit=m['sdk_main_commit']),dict(round=3,repository='leafseamer-suite',commit='containing-commit')],push_order=['leafseamer-sdk','leafseamer-suite']),'提交周期')
    H.require(m['packages'][1]['commit']==m['packages'][2]['commit']==m['sdk_main_commit'],'本轮同提交消费者')

def inspect_browser(m,b,files):
    H.require(b['format']=='sdk-panel-browser/1' and b['all_passed'] is True and b['approved'] is False and b['runtime_ready'] is False,'浏览器结果资格')
    H.require(b['sdk_commit']==m['sdk_main_commit'] and b['selection']==m['selection'],'浏览器固定选择')
    names=['run-browser.mjs','browser.html','browser.mjs','worker.mjs','suite.mjs','manifest.json']
    H.require(b['own_inputs']=={n:H.sha((ROOT/n).read_bytes()) for n in names},'浏览器探针字节')
    H.require(set(b['reports'])=={'plain','isolated'},'浏览器模式完整')
    used=set()
    for mode,r in b['reports'].items():
        isolated=mode=='isolated';report=r['report'];used.update(r['requests'])
        H.require(report['all_passed'] and report['eval_blocked'] and report['inline_blocked'] and report['worker_eval_blocked'],'浏览器CSP')
        H.require(r['headers']['Content-Security-Policy']==CSP,'CSP头')
        H.require(('Cross-Origin-Opener-Policy' in r['headers'])==isolated and ('Cross-Origin-Embedder-Policy' in r['headers'])==isolated,'实际隔离头')
        if isolated:H.require(r['headers']['Cross-Origin-Opener-Policy']=='same-origin' and r['headers']['Cross-Origin-Embedder-Policy']=='require-corp','隔离头值')
        H.require(r['http_exchanges']==dict(page=105,worker=105),'服务端实际收发')
        for context in ['page','worker']:
            v=report[context]
            expected=dict(all_passed=True,cases_passed=8855 if isolated else 8755,base_checks=8070 if isolated else 7970,panel_cases=460,frame_types=19,methods=35,http_exchanges=105,cross_origin_isolated=isolated,shared_array_buffer_available=isolated,skipped_shared_buffer_checks=0 if isolated else 100,production_authorization_executed=False,product_business_executed=False)
            H.require({k:v[k] for k in expected}==expected and len(v['checks_sha256'])==64,'浏览器上下文完整范围')
        H.require(report['page']['checks_sha256']==report['worker']['checks_sha256'],'页面Worker断言同集')
    H.require(set(b['served_artifacts'])==used and len(used)==33,'实际资源集合')
    H.require(b['source_artifacts']=={p:m['snapshot_files'][p] for p in used if p.startswith('contracts/')},'浏览器资源Git绑定')
    for p,h in b['served_artifacts'].items():
        raw=files[p] if p.startswith('contracts/') else (ROOT/H.path_name(p)).read_bytes()
        if p=='contracts/panel-wire/runtime-tests.mjs':
            text=raw.decode();H.require(text.count(LINE)==1,'转换边界');raw=text.replace(LINE,"      if(typeof SharedArrayBuffer!=='undefined')"+LINE.strip()).encode()
        H.require(H.sha(raw)==h,'浏览器实际制品:'+p)
    H.require(b['http_exchanges']==420 and all(b[k] is False for k in ['production_authorization_executed','product_business_executed','device_executed']),'浏览器业务边界')
    H.require(b['browser']['product'] and len(b['browser']['executable_sha256'])==64 and len(b['node']['executable_sha256'])==64,'工具身份')

def inputs():
    paths=[p for p in ROOT.iterdir() if p.is_file() and p.name!='report.json']+[SUITE/p for p in DESIGNS]+[HELPER]
    return {p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in sorted(paths)}

def run(sdk):
    m=H.decode((ROOT/'manifest.json').read_bytes());inspect_manifest(m);checks=[]
    def check(name,value):H.require(value,name);checks.append(dict(name=name,passed=True))
    check('仓库归属',H.git(sdk,'remote','get-url','origin').decode().strip()==m['sdk_repository'])
    check('SDK主线包含固定提交',subprocess.run(['git','merge-base','--is-ancestor',m['sdk_main_commit'],'main'],cwd=sdk,capture_output=True).returncode==0)
    files=H.read_fixed(sdk,m['sdk_main_commit'],m['snapshot_files']);check('最终快照摘要',all(H.sha(raw)==m['snapshot_files'][p] for p,raw in files.items()))
    reports={}
    for package in m['packages']+m['provider_sources']:
        fixed=H.read_fixed(sdk,package['commit'],package['files']);check('固定提交:'+package['name'],all(H.sha(raw)==package['files'][p] for p,raw in fixed.items()))
        r=H.decode(fixed[package['report']]);reports[package['name']]=r
        expected={p:h for p,h in r['inputs'].items() if '/node_modules/' not in p};expected[package['report']]=H.sha(fixed[package['report']])
        check('报告完整输入:'+package['name'],expected==package['files'])
        check('候选资格:'+package['name'],r['all_passed'] is True and r['approved'] is False and r['runtime_ready'] is False)
        check('断言记录:'+package['name'],all(isinstance(c,str) and c for c in r['checks']) if package['name']=='panel-client' else r['cases_passed']==len(r['checks']) and all(c['passed'] for c in r['checks']))
    wire=reports['panel-wire'];http=reports['panel-http'];client=reports['panel-client']
    complete=H.decode(files['contracts/panel-wire/contract/manifest.json'])
    check('新选择与完整清单',H.decode(files['contracts/panel-wire/contract/selection.json'])==m['selection'] and m['selection']['contract_digest']=='sha256:'+H.sha(rfc8785.dumps(complete)))
    check('模型与消息根',len(H.decode(files['contracts/panel-wire/contract/models.schema.json'])['$defs'])==1463 and wire['static_runtime']['cases_passed']==8775 and wire['contract']['cases_passed']==233)
    check('HTTP完整覆盖',http['operations']==201 and http['response_bindings']==2148 and http['static_runtime']['cases_passed']==12076 and http['panel_runtime']['cases_passed']==218 and http['loopback_http']['loopback_http_exchanges']==10)
    check('客户端完整覆盖',client['schemas_per_authority']==1463 and client['http_callable']==197 and client['websocket_metadata_only']==4 and client['runtime']['cases_passed']==862 and client['type_negative_cases']==26)
    check('客户端面板回环',client['panel_loopback_http']['loopback_http_exchanges']==105 and client['panel_loopback_http']['methods']==35 and client['loopback_http']['loopback_http_exchanges']==2)
    check('历史浏览器证据不改写',wire['browser_tests_executed']==http['browser_tests_executed']==0 and client['browser_executed'] is False)
    b=H.decode((ROOT/'browser-report.json').read_bytes());inspect_browser(m,b,files);check('当前四浏览器上下文验证',True)
    provider=H.decode((ROOT/'provider-report.json').read_bytes())
    check('提供者探针身份',provider['sdk_commit']==m['sdk_main_commit'] and provider['probe_sha256']==H.sha((ROOT/'check_providers.py').read_bytes()) and len(provider['python_sha256'])==64)
    result=provider['result'];check('提供者实际拒绝',result['all_passed'] and result['cases_passed']==len(result['checks'])==6 and all(c['passed'] for c in result['checks']) and result['provider_selection']==m['previous_selection'] and result['current_selection']==m['selection'] and result['provider_migration_complete'] is False and result['validator_subprocess_calls']==0)
    def denied(name,fn):
        try:fn()
        except (ValueError,KeyError,AssertionError):check(name,True)
        else:raise AssertionError(name+':未拒绝')
    for name,mutate in [('漏包',lambda v:v['packages'].pop()),('误标提供者迁移',lambda v:v.update(provider_migration_complete=True)),('关闭阶段',lambda v:v['boundaries'].update(stage0_complete=True)),('遗漏快照',lambda v:v['snapshot_files'].pop(next(iter(v['snapshot_files']))))]:
        bad=copy.deepcopy(m);mutate(bad);denied(name,lambda:inspect_manifest(bad))
    for name,mutate in [('漏隔离模式',lambda v:v['reports'].pop('isolated')),('伪共享缓冲覆盖',lambda v:v['reports']['plain']['report']['page'].update(skipped_shared_buffer_checks=0)),('漏服务请求',lambda v:v['reports']['isolated']['http_exchanges'].update(worker=104)),('漂移资源',lambda v:v['served_artifacts'].update({'suite.mjs':'0'*64})),('伪生产授权',lambda v:v.update(production_authorization_executed=True))]:
        bad=copy.deepcopy(b);mutate(bad);denied(name,lambda:inspect_browser(m,bad,files))
    return dict(format='sdk-panel-handoff-check/1',all_passed=True,approved=False,runtime_ready=False,cases_passed=len(checks),checks=checks,sdk_commit=m['sdk_main_commit'],snapshot_files=len(files),recorded_browser_checks=35220,browser_http_exchanges=420,provider_boundary_checks=6,historical_behavior_rerun=False,production_authorization_executed=False,device_executed=False,input_sha256=inputs())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path);parser.add_argument('--snapshot',action='store_true');parser.add_argument('--probe-providers',action='store_true');parser.add_argument('--report',action='store_true');parser.add_argument('--check-report',action='store_true');args=parser.parse_args()
    if args.check_report:
        r=H.decode((ROOT/'report.json').read_bytes());H.require(r['all_passed'] and r['input_sha256']==inputs(),'报告输入漂移');print('报告输入一致；未重跑行为')
    else:
        if not args.sdk:parser.error('需要--sdk')
        m=H.decode((ROOT/'manifest.json').read_bytes());inspect_manifest(m)
        if args.snapshot or args.probe_providers:
            snapshot=materialize(args.sdk.resolve(),m)
            if args.snapshot:print(snapshot);sys.exit(0)
            result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'check_providers.py'),str(snapshot)],capture_output=True,check=True)
            (ROOT/'provider-report.json').write_bytes(H.encode(dict(sdk_commit=m['sdk_main_commit'],probe_sha256=H.sha((ROOT/'check_providers.py').read_bytes()),python_sha256=H.sha(Path(sys.executable).read_bytes()),result=H.decode(result.stdout))))
        r=run(args.sdk.resolve())
        if args.report:(ROOT/'report.json').write_bytes(H.encode(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ['checks','input_sha256']},ensure_ascii=False))
