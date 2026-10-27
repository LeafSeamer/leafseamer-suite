"""固定SDK成果与阶段状态交接；读取Git原件不等于重跑历史运行检查。"""
import argparse
import copy
import importlib.util
from pathlib import Path
import subprocess
import rfc8785

ROOT=Path(__file__).resolve().parent;SUITE=ROOT.parents[2]
HELPER=ROOT.parent/'sdk-transport-handoff/check_handoff.py'
spec=importlib.util.spec_from_file_location('fixed_handoff_helpers',HELPER)
H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
NAMES=['scope-release','scope-recovery','channel-release','snapshot-consumer','projection-delta','event-integration','wire-json','wire-js','wire-static','wire-routing','wire-browser']
DESIGNS=['README.md','docs/ROADMAP.md','docs/rebirth-design-closure.md','docs/rebirth-readiness.md','docs/rebirth-df01-sdk-freeze.md','docs/rebirth-c05-event-sync-design.md','docs/rebirth-df04-storage-design.md']

def package_report(package,files):
    H.require(set(files)==set(package['files']),'固定文件集合不完整')
    for p,h in package['files'].items():H.require(H.sha(files[p])==h,'固定文件字节漂移')
    report=H.decode(files[package['report']])
    H.require(report['all_passed'] is True and report['approved'] is False and report['runtime_ready'] is False,'资格或结果被改写')
    H.require(report['cases_passed']==len(report['checks']) and all(c['passed'] is True for c in report['checks']),'检查明细不一致')
    H.require(dict(report['inputs'],**{package['report']:H.sha(files[package['report']])})==package['files'],'报告输入与原件集合不一致')
    H.require(all(report[k]==v for k,v in package['expected'].items()),'证据类型或数值不符')
    for key in ['product_runtime_tests_executed','product_network_tests_executed','authentication_tests_executed','device_tests_executed','power_loss_tests_executed']:
        H.require(report.get(key,0)==0,'未经验证的产品验收')
    return report

def inspect_browser(receipt,files,routing):
    H.require(receipt['format']=='wire-browser-receipt/1' and receipt['approved'] is False and receipt['runtime_ready'] is False,'浏览器收据资格')
    H.require(set(receipt['reports'])=={'plain','isolated'},'浏览器模式缺失')
    H.require(len(receipt['artifacts'])==17,'验收资产缺失')
    for p,h in receipt['artifacts'].items():H.require(H.sha(files[H.path_name(p)])==h,'浏览器验收资产漂移')
    extra=['隔离模式与实际环境一致','共享缓冲能力与隔离一致','执行数与跳过项对账','输入缓冲确实转移','首await前复制抵抗转移','浏览器UTF8不替换坏字节']
    totals=0
    for mode,item in receipt['reports'].items():
        isolated=mode=='isolated';r=item['report'];headers=item['headers']
        H.require(r['all_passed'] and r['eval_blocked'] and r['inline_blocked'] and r['mode']==mode,'页面CSP或结果')
        H.require(r['worker']['all_passed'] and r['worker']['eval_blocked'],'Worker失败')
        H.require(headers['Content-Security-Policy']=="default-src 'none'; script-src 'self'; worker-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'",'CSP改变')
        H.require(headers.get('Cross-Origin-Opener-Policy')==('same-origin' if isolated else None) and headers.get('Cross-Origin-Embedder-Policy')==('require-corp' if isolated else None),'隔离响应头改变')
        for blocked in ['eval','inline']:H.require(any(v['blocked_uri']==blocked and v['directive'].startswith('script-src') for v in r['csp_violations']),'拦截证据缺失')
        expected=[c for c in routing['static_runtime']['checks'] if isolated or not c['name'].startswith('空正文拒共享缓冲:')]+[dict(name=n,passed=True) for n in extra]
        # JS JSON.stringify的UTF8紧凑表示；不将业务JCS摘要算法用于运行断言记录。
        raw=H.json.dumps(expected,ensure_ascii=False,separators=(',',':')).encode('utf8')
        for context in [r['page'],r['worker']['result']]:
            H.require(context['all_passed'] and context['cases_passed']==context['checks_count']==len(expected) and context['checks_all_passed'],'断言数改变')
            H.require(context['checks_sha256']==H.sha(raw),'完整断言身份漂移')
            H.require(context['cross_origin_isolated']==isolated and context['skipped_shared_buffer_checks']==(0 if isolated else 100),'跳过项或隔离伪标')
            totals+=context['cases_passed']
    H.require(totals==31268,'浏览器累计计数改变')
    return totals

def local_inputs():
    files=[p for p in ROOT.iterdir() if p.is_file() and p.name!='report.json']+[HELPER]+[SUITE/p for p in DESIGNS]
    return {p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in sorted(files)}

def run(sdk):
    manifest=H.decode((ROOT/'manifest.json').read_bytes());checks=[]
    def check(name,value):H.require(value,name);checks.append(dict(name=name,passed=True))
    check('交接格式',manifest['format']=='sdk-wire-handoff/1')
    check('交接范围',[p['name'] for p in manifest['packages']]==NAMES)
    for repo,key in [(sdk,'sdk_repository'),(SUITE,'suite_repository')]:check('仓库归属:'+key,H.git(repo,'remote','get-url','origin').decode().strip()==manifest[key])
    reports={};snapshots={};previous=None
    for p in manifest['packages']:
        files=H.read_fixed(sdk,p['commit'],p['files']);reports[p['name']]=package_report(p,files);snapshots[p['name']]=files
        check('固定报告及全部输入:'+p['name'],True)
        check('main包含:'+p['name'],subprocess.run(['git','merge-base','--is-ancestor',p['commit'],'main'],cwd=sdk,capture_output=True).returncode==0)
        if previous:check('提交顺序:'+p['name'],subprocess.run(['git','merge-base','--is-ancestor',previous,p['commit']],cwd=sdk,capture_output=True).returncode==0)
        previous=p['commit']
    check('最终SDK提交',previous==manifest['sdk_main_commit'])
    read=lambda group,p:H.decode(snapshots[group]['contracts/'+group+'/'+p])
    event=read('event-integration','preview/manifest.json');selection=read('event-integration','preview/selection.json')
    check('新完整选择',selection==manifest['selection'] and selection['contract_digest']=='sha256:'+H.sha(rfc8785.dumps(event)))
    check('模型集合',len(read('event-integration','preview/models.schema.json')['$defs'])==1351)
    inv=read('wire-routing','preview/inventory.json')
    check('201API及52消息与281根',len(inv['operations'])==201 and len(inv['messages'])==52 and len(inv['schemas'])==281)
    runtime=reports['wire-routing']['static_runtime'];check('静态运行明细',runtime['all_passed'] and runtime['dynamic_codegen_blocked'] and runtime['cases_passed']==len(runtime['checks'])==7861 and all(c['passed'] for c in runtime['checks']))
    count=inspect_browser(read('wire-browser','browser-report.json'),snapshots['wire-browser'],reports['wire-routing']);check('四浏览器上下文完整断言',count==31268)
    check('阶段未自动关闭',manifest['boundaries']==dict(stage0_complete=False,business_implementation_started=False,production_sdk_ready=False,runtime_protocol_frozen=False))
    check('当前三轮归属',manifest['cycle']==dict(rounds=[dict(round=1,repository='leafseamer-sdk',commit=manifest['packages'][-2]['commit']),dict(round=2,repository='leafseamer-sdk',commit=manifest['packages'][-1]['commit']),dict(round=3,repository='leafseamer-suite',commit='containing-commit')],push_order=['leafseamer-sdk','leafseamer-suite']))
    def denied(name,fn):
        try:fn()
        except (ValueError,KeyError,AssertionError):check(name,True)
        else:raise AssertionError(name+':未拒绝')
    p=manifest['packages'][-1];original=snapshots['wire-browser']
    bad=dict(original);bad[p['report']]+=b' ';denied('报告原件漂移',lambda:package_report(p,bad))
    wrong=copy.deepcopy(p);wrong['expected']['recorded_checks_total']+=1;denied('记录数漂移',lambda:package_report(wrong,original))
    for label,change in [('漏模式',lambda r:r['reports'].pop('plain')),('跳过伪通过',lambda r:r['reports']['plain']['report']['page'].update(skipped_shared_buffer_checks=0)),('Worker失败',lambda r:r['reports']['isolated']['report']['worker'].update(all_passed=False)),('明细摘要漂移',lambda r:r['reports']['plain']['report']['page'].update(checks_sha256='0'*64)),('资产漂移',lambda r:r['artifacts'].update({next(iter(r['artifacts'])):'0'*64}))]:
        r=read('wire-browser','browser-report.json');change(r);denied(label,lambda r=r:inspect_browser(r,original,reports['wire-routing']))
    for name in ['../escape','/absolute','C:/absolute','a//b','a\\b']:denied('非法路径:'+name,lambda name=name:H.path_name(name))
    denied('浮动提交',lambda:H.read_fixed(sdk,'main',['README.md']))
    return dict(format='sdk-wire-handoff-report/1',all_passed=True,cases_passed=len(checks),checks=checks,sdk_main_commit=previous,
      packages=len(reports),fixed_sdk_file_bindings=sum(len(p['files']) for p in manifest['packages']),browser_checks_recorded=count,
      stage0_complete=False,historical_behavior_rerun=False,browser_rerun=False,device_tests_executed=0,input_sha256=local_inputs())

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sdk',type=Path)
    group=parser.add_mutually_exclusive_group();group.add_argument('--report',action='store_true');group.add_argument('--check-report',action='store_true');args=parser.parse_args()
    if args.check_report:
        r=H.decode((ROOT/'report.json').read_bytes());H.require(r['all_passed'] and r['input_sha256']==local_inputs(),'本仓输入漂移');print(H.json.dumps(dict(all_passed=True,bindings=len(r['input_sha256']),behavior_rerun=False)))
    else:
        if not args.sdk:parser.error('需要--sdk指定SDK仓库')
        r=run(args.sdk.resolve())
        if args.report:(ROOT/'report.json').write_bytes(H.encode(r))
        print(H.json.dumps({k:v for k,v in r.items() if k not in ('checks','input_sha256')},ensure_ascii=False))
