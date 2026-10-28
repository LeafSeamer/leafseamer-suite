"""固定SDK成果与阶段状态交接；读取Git原件不等于重跑历史运行检查。"""
import argparse
import copy
import importlib.util
from pathlib import Path
import subprocess
import uuid
import rfc8785

ROOT=Path(__file__).resolve().parent;SUITE=ROOT.parents[2]
HELPER=ROOT.parent/'sdk-transport-handoff/check_handoff.py'
spec=importlib.util.spec_from_file_location('fixed_handoff_helpers',HELPER)
H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
NAMES=['scope-release','scope-recovery','channel-release','snapshot-consumer','projection-delta','event-integration','wire-json','wire-js','wire-static','wire-routing','wire-browser','http-envelope','typed-client','authorization','panel-methods','panel-results','panel-integration']
DESIGNS=['README.md','docs/ROADMAP.md','docs/rebirth-design-closure.md','docs/rebirth-readiness.md','docs/rebirth-df01-sdk-freeze.md','docs/rebirth-c05-event-sync-design.md','docs/rebirth-df04-storage-design.md','docs/rebirth-c09-extension-design.md']

def package_report(package,files):
    H.require(set(files)==set(package['files']),'固定文件集合不完整')
    for p,h in package['files'].items():H.require(H.sha(files[p])==h,'固定文件字节漂移')
    report=H.decode(files[package['report']])
    H.require(report['all_passed'] is True and report['approved'] is False and report['runtime_ready'] is False,'资格或结果被改写')
    if package['name']=='typed-client':
        H.require(len(report['checks'])==223 and all(isinstance(c,str) and c for c in report['checks']),'类型检查明细不一致')
    else:H.require(report['cases_passed']==len(report['checks']) and all(c['passed'] is True for c in report['checks']),'检查明细不一致')
    external={p:h for p,h in report['inputs'].items() if '/node_modules/' in p}
    fixed={p:h for p,h in report['inputs'].items() if p not in external}
    H.require(dict(fixed,**{package['report']:H.sha(files[package['report']])})==package['files'],'报告输入与原件集合不一致')
    if package.get('dependency_manifest'):
        dep_path=package['dependency_manifest'];dep=H.decode(files[dep_path]);base=dep_path.rsplit('/',1)[0]
        recorded={base+'/node_modules/'+H.path_name(p):h for p,h in dep['files'].items()}
        H.require(len(recorded)==package['dependency_files_recorded'] and dep['approved'] is False,'依赖记录集合')
        H.require(H.sha(files[base+'/package-lock.json'])==dep['lock_sha256'],'依赖锁漂移')
        H.require('ignore-scripts' in dep['installation_flags'] and all(p['lifecycle_executed'] is False for p in dep['packages']),'依赖脚本资格')
        H.require(external==(recorded if package['name']=='http-envelope' else {}),'外部依赖记录不符')
    else:H.require(not external,'未绑定外部依赖')
    H.require(all(report[k]==v for k,v in package['expected'].items()),'证据类型或数值不符')
    for key in ['product_runtime_tests_executed','product_network_tests_executed','authentication_tests_executed','device_tests_executed','power_loss_tests_executed']:
        H.require(report.get(key,0)==0,'未经验证的产品验收')
    return report

def inspect_http(report,inventory):
    r=report['static_runtime'];loop=report['loopback_http']
    H.require(r['all_passed'] and r['dynamic_codegen_blocked'] and r['cases_passed']==len(r['checks'])==12076 and all(c['passed'] for c in r['checks']),'HTTP运行明细')
    H.require(loop['all_passed'] and loop['loopback_http_exchanges']==10,'HTTP回环记录')
    H.require(len(inventory['operations'])==201 and sum(len(o['responses']) for o in inventory['operations'])==2148,'HTTP绑定覆盖')
    H.require(report['parameter_definitions']==58 and report['independent_binding_checks']==9159 and report['parameter_variants']==2204,'HTTP参数记录')

def inspect_typed(report,bindings,inventory):
    r=report['runtime'];loop=report['loopback_http']
    H.require(r['all_passed'] and r['dynamic_codegen_blocked'] and r['cases_passed']==len(r['checks'])==862 and all(isinstance(c,str) and c for c in r['checks']),'客户端运行明细')
    H.require(loop['all_passed'] and loop['loopback_http_exchanges']==2,'客户端回环记录')
    H.require(report['type_negative_cases']==20 and sorted(set(d['line'] for d in report['type_negative_diagnostics']))==list(range(4,24)),'逐行编译负例')
    H.require(report['production_authentication_executed'] is False and report['browser_executed'] is False and report['device_executed'] is False,'客户端运行范围伪标')
    expected=[dict(authority=o['authority'],operation_id=o['operation_id'],method=o['method'],path=o['path'],transport=o['transport'],callable=o['transport']!='websocket-subprotocol',responses=list(o['responses'])) for o in inventory['operations']]
    H.require(bindings['approved'] is False and bindings['runtime_ready'] is False and bindings['operations']==expected,'客户端操作绑定')
    H.require(sum(o['callable'] for o in expected)==report['http_callable']==197 and report['websocket_metadata_only']==4,'客户端传输边界')
    H.require(report['operations']==201 and report['response_bindings']==2148 and report['schemas_per_authority']==1351,'客户端类型覆盖')

def inspect_authorization(report,bindings,inventory):
    H.require(bindings['approved'] is False and bindings['runtime_ready'] is False and bindings['selection']==inventory['selection'],'授权候选资格或选择')
    rows={o['key']:o for o in bindings['operations']};expected={o['authority']+':'+o['operation_id']:o for o in inventory['operations']}
    H.require(len(rows)==len(bindings['operations'])==201 and set(rows)==set(expected),'授权操作覆盖')
    for key,row in rows.items():
        source=expected[key]
        H.require(all(row[k]==source[k] for k in ['authority','operation_id','method','path','transport','security']),'授权调用身份')
        H.require(row['authorization_granted'] is False and row['branches'],'授权许可伪标')
        for branch in row['branches']:
            H.require(set(branch['guards'])<=set(bindings['guards']) and set(branch['providers'])<=set(bindings['providers']),'守卫或提供者缺失')
    H.require(sum(len(o['branches']) for o in rows.values())==report['branches']==245 and len(bindings['guards'])==62 and len(bindings['providers'])==12,'授权登记统计')
    H.require(len({g for o in rows.values() for b in o['branches'] for g in b['guards']})==report['active_guards']==61,'活跃守卫统计')
    H.require(set(bindings['guard_changes'])=={'ticket_issue'} and 'subscription' in bindings['guard_changes']['ticket_issue']['current'],'票据迁移缺失')
    H.require(report['cases_passed']==655 and all(report[k]==0 for k in ['runtime_authorization_tests_executed','network_tests_executed','device_tests_executed']),'授权证据范围')

def inspect_panel(report,bindings,schema,authorization,models,apis):
    H.require(bindings['approved'] is False and bindings['runtime_ready'] is False and bindings['installed'] is False and bindings['requires_new_complete_selection'] is True,'面板候选伪安装')
    H.require(bindings['source_selection']==authorization['selection'],'面板来源选择')
    methods=bindings['methods'];expected=set(models['$defs']['panel__Channel_Method']['enum']);auth={o['key']:o for o in authorization['operations']}
    H.require(set(methods)==expected and len(methods)==35 and len(bindings['semantic_rules'])==28,'面板方法或规则覆盖')
    H.require(sum(r['mode']=='host_confirm' for r in methods.values())==8,'确认用途缺失')
    for method,row in methods.items():
        key=method.replace('.',':',1);op=auth[key];H.require(row['operation_key']==key and row['authority']==op['authority'],'面板跨权威')
        H.require(row['human_branch']==next(b for b in op['branches'] if b['profile']=='human') and row['permission']==op['permission'],'面板领域授权不符')
        H.require(row['installed'] is False and row['authorization_granted'] is False and row['raw_response_allowed'] is False,'面板许可或原响应泄漏')
        H.require(row['semantic_rule'] in bindings['semantic_rules'] and row['input_definition'] in schema['$defs'],'领域规则或输入遗漏')
        api=apis[row['authority']];source=api['paths'][op['path']][op['method'].lower()]
        H.require(row['path']==op['path'] and row['http_method'].upper()==op['method'],'面板调用位置改变')
        fields={p['in']+'.'+p['name'] for p in source.get('parameters',[])}
        body=source.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
        while body and set(body)=={'$ref'}:body=api['components']['schemas'][body['$ref'].rsplit('/',1)[-1]]
        if body:fields|={'body.'+n for n in body['properties']}
        H.require(set(row['source_fields'])==fields,'面板字段覆盖遗漏')
    H.require(report['cases_passed']==771 and report['synthetic_http_mappings']==35 and all(report[k]==0 for k in ['real_handle_tests_executed','authorization_tests_executed','result_projection_tests_executed','browser_tests_executed','network_tests_executed','device_tests_executed']),'面板证据范围')

def inspect_new_sources(sdk,package,files):
    source=H.decode(files['contracts/'+package['name']+'/sources.json'])
    raw=H.read_fixed(sdk,source.get('sdk_source_commit',source.get('source_commit')),source['inputs'])
    H.require(all(H.sha(raw[p])==h and raw[p]==files[p] for p,h in source['inputs'].items()),'SDK来源提交原件')
    for p,item in source['copied_sources'].items():
        H.require(item['repository']=='https://github.com/LeafSeamer/leafseamer-suite','副本来源仓库')
        original=H.read_fixed(SUITE,item['commit'],{item['path']:item['sha256']})
        H.require(original[item['path']]==files[p],'Suite副本原件')

def inspect_results(report,bindings,schema,methods):
    H.require(all(bindings[k] is False for k in ['approved','runtime_ready','installed']) and bindings['requires_new_complete_selection'],'结果候选资格')
    H.require(set(bindings['methods'])==set(methods['methods']) and len(bindings['views'])==21 and len(bindings['plans'])==23,'结果覆盖')
    H.require(bindings['coverage_unit']=='variant_top_level_output_field' and sum(len(p['fields']) for p in bindings['plans'].values())==bindings['output_field_count']==181,'顶层来源计数')
    for name,plan in bindings['plans'].items():
        H.require(set(plan['fields'])==set(schema['$defs'][name]['properties']),'结果字段遗漏')
        for item in plan['fields'].values():
            H.require(item['kind'] in ['source','provider'],'未知来源类型')
            if item['kind']=='provider':H.require(item['provider'] in bindings['providers'],'结果提供者遗漏')
    for method,row in bindings['methods'].items():
        H.require(row['view']==methods['methods'][method]['result_view'] and row['variant'] in bindings['plans'],'结果方法变体')
        H.require(row['ready_for_installation'] is False and row['raw_response_allowed'] is False,'结果不得自动安装或透传')
    H.require(report['cases_passed']==652 and report['providers']==len(bindings['providers'])==14,'结果报告范围')
    H.require(all(report[k]==0 for k in ['runtime_projection_tests_executed','authority_provider_tests_executed','database_tests_executed','browser_tests_executed','network_tests_executed','device_tests_executed']),'结果实测伪标')

def inspect_panel_integration(report,files,methods,results):
    base='contracts/panel-integration/preview/'
    read=lambda n:H.decode(files[base+n])
    manifest=read('manifest.json');selection=read('selection.json');registry=read('method-registry.json');mapping=read('binding-map.json');graph=read('models.schema.json');defs=graph['$defs']
    H.require(selection['contract_id']=='leafseamer.api.v1.panel3' and selection['contract_digest']=='sha256:'+H.sha(rfc8785.dumps(manifest)),'panel3选择身份')
    H.require(all(manifest[k] is False for k in ['approved','runtime_ready','advertisable']),'panel3资格伪标')
    expected={p.removeprefix(base) for p in files if p.startswith(base)}-{'selection.json','manifest.json'}|{'PROTOCOL.md'}
    H.require(set(manifest['artifacts'])==expected,'panel3制品覆盖')
    for n,h in manifest['artifacts'].items():H.require(H.sha(files[('contracts/panel-integration/' if n=='PROTOCOL.md' else base)+n])==h,'panel3制品字节')
    H.require(registry['registry_ref']==dict(revision=registry['registry']['revision'],digest=H.sha(rfc8785.dumps(registry['registry']))),'Registry摘要')
    rows={r['method']:r for r in registry['registry']['methods']}
    H.require(rows==mapping['methods'] and set(rows)==set(methods['methods']) and len(rows)==35,'Registry完整方法')
    for method,row in rows.items():
        H.require(row['mode']==methods['methods'][method]['mode'],'方法用途变更')
        for kind,name in [('input',methods['methods'][method]['input_definition']),('result',results['methods'][method]['variant'])]:
            doc=read(kind+'.schema.json');binding=dict(schema_id=doc['$id'],definition=name,schema_digest=H.sha(rfc8785.dumps(doc)))
            H.require(row[kind+'_schema_ref']==binding and name in doc['$defs'],'SchemaRef文档闭包绑定')
        branch=next(c for c in defs['panel__Service_BoundIntent']['allOf'] if c.get('if',{}).get('properties',{}).get('method',{}).get('const')==method)
        H.require(branch['then']['properties']['normalized_arguments']['properties']['schema_ref']=={'const':row['input_schema_ref']},'服务Intent旧绑定')
        branch=next(c for c in defs['panel__Service_RequestReceipt']['allOf'] if c.get('if',{}).get('properties',{}).get('method',{}).get('const')==method)
        H.require(branch['then']['properties']['projection']['properties']['schema_ref']=={'const':row['result_schema_ref']},'服务结果旧绑定')
    H.require(sum(r['subscription_mode']=='projection' for r in rows.values())==17 and sum(r['subscription_mode']=='invalidation' for r in rows.values())==2,'订阅用途改变')
    for name,key in [('panel__Channel_ActivationRef','registry_ref'),('panel__Service_PrepareActivation','expected_registry_ref'),('panel__Bundle_Manifest','registry_ref')]:H.require(defs[name]['properties'][key]=={'const':registry['registry_ref']},'激活Registry未固定')
    H.require(set(defs['panel__Channel_Result']['properties']['projection_state']['enum'])=={'available','unavailable','not_applicable'},'受理与投影未分离')
    operations=0
    for authority in ['controller','seamer']:
        api=read(authority+'.openapi.json');H.require(api['info']['version']==selection['contract_id'] and len(api['components']['schemas'])==len(defs),'完整API版本')
        operations+=sum(len(v) for v in api['paths'].values())
    H.require(report['selection']==selection and report['models']==len(defs)==1463 and report['operations']==operations==201 and report['cases_passed']==5972,'panel3报告覆盖')
    H.require(all(report[k]==0 for k in ['runtime_projection_tests_executed','authority_provider_tests_executed','database_tests_executed','browser_tests_executed','network_tests_executed','device_tests_executed']),'panel3实测伪标')
    return selection

def consumer_files(manifest):
    files={}
    for package in manifest['packages']:
        if package['name'] not in ['wire-routing','http-envelope','typed-client']:continue
        for p,h in package['files'].items():
            H.require(p not in files or files[p]==h,'客户端固定快照版本冲突');files[p]=h
    return files

def record_consumer_probe(sdk,node):
    manifest=H.decode((ROOT/'manifest.json').read_bytes());expected=consumer_files(manifest)
    files=H.read_fixed(sdk,manifest['sdk_main_commit'],expected)
    H.require(all(H.sha(raw)==expected[p] for p,raw in files.items()),'消费者当前提交原件漂移')
    root=SUITE/'logs'/('consumer-check-'+uuid.uuid4().hex);root.mkdir(parents=True)
    for p,raw in files.items():
        path=root/H.path_name(p);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    inputs=dict(previous=manifest['runtime_artifact_selection'],current=manifest['selection'])
    path=root/'selections.json';path.write_bytes(H.encode(inputs))
    result=subprocess.run([str(node),'--disallow-code-generation-from-strings',str(ROOT/'check_consumers.mjs'),str(root),str(path)],capture_output=True)
    H.require(result.returncode==0,result.stderr.decode('utf8',errors='replace'))
    receipt=H.decode(result.stdout)
    receipt.update(format='sdk-consumer-selection-check/1',approved=False,runtime_ready=False,sdk_commit=manifest['sdk_main_commit'],previous=inputs['previous'],current=inputs['current'],snapshot_files=expected,node_sha256=H.sha(node.read_bytes()),probe_sha256=H.sha((ROOT/'check_consumers.mjs').read_bytes()))
    (ROOT/'consumer-report.json').write_bytes(H.encode(receipt))

def inspect_consumers(manifest,receipt,http):
    previous=manifest['runtime_artifact_selection'];current=manifest['selection']
    H.require(previous==http['selection'] and current!=previous,'客户端选择未区分')
    expected=[dict(package=n,selection=previous,compatible_with_current=False,rebuild_required=True) for n in ['wire-routing','http-envelope','typed-client']]
    H.require(manifest['consumer_compatibility']==expected,'消费者兼容范围伪标')
    H.require(receipt['format']=='sdk-consumer-selection-check/1' and receipt['all_passed'] and receipt['approved'] is False and receipt['runtime_ready'] is False,'消费者探针资格')
    H.require(receipt['sdk_commit']==manifest['sdk_main_commit'] and receipt['previous']==previous and receipt['current']==current and receipt['snapshot_files']==consumer_files(manifest),'消费者原件绑定')
    H.require(receipt['probe_sha256']==H.sha((ROOT/'check_consumers.mjs').read_bytes()) and len(receipt['node_sha256'])==64,'探针制品绑定')
    names=['动态代码生成被禁用']+[n+':'+label for n in ['wire-routing','http-envelope','typed-client'] for label in ['原选择可构造','新选择拒绝','原ID错摘要拒绝','新ID原摘要拒绝','原ID新摘要拒绝']]+['未发生传输调用']
    H.require(receipt['checks']==[dict(name=n,passed=True) for n in names] and receipt['cases_passed']==17 and receipt['dynamic_codegen_blocked'] and receipt['transport_calls']==0,'消费者真实构造记录')

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
    check('历史运行制品选择',selection==manifest['runtime_artifact_selection'] and selection['contract_digest']=='sha256:'+H.sha(rfc8785.dumps(event)))
    check('模型集合',len(read('event-integration','preview/models.schema.json')['$defs'])==1351)
    inv=read('wire-routing','preview/inventory.json')
    check('201API及52消息与281根',len(inv['operations'])==201 and len(inv['messages'])==52 and len(inv['schemas'])==281)
    runtime=reports['wire-routing']['static_runtime'];check('静态运行明细',runtime['all_passed'] and runtime['dynamic_codegen_blocked'] and runtime['cases_passed']==len(runtime['checks'])==7861 and all(c['passed'] for c in runtime['checks']))
    count=inspect_browser(read('wire-browser','browser-report.json'),snapshots['wire-browser'],reports['wire-routing']);check('四浏览器上下文完整断言',count==31268)
    http=read('http-envelope','preview/inventory.json');inspect_http(reports['http-envelope'],http);check('完整HTTP参数与响应记录',True)
    inspect_typed(reports['typed-client'],read('typed-client','preview/bindings.json'),http);check('完整客户端类型与状态记录',True)
    authorization=read('authorization','bindings.json');inspect_authorization(reports['authorization'],authorization,http);check('完整外层授权与证据边界',True)
    panel=read('panel-methods','bindings.json');panel_schema=read('panel-methods','input.schema.json')
    panel_models=read('event-integration','preview/models.schema.json');panel_apis={a:read('event-integration','preview/'+a+'.openapi.json') for a in ['controller','seamer']}
    inspect_panel(reports['panel-methods'],panel,panel_schema,authorization,panel_models,panel_apis);check('面板35方法当前字段与授权交叉绑定',True)
    results=read('panel-results','bindings.json');result_schema=read('panel-results','result.schema.json')
    inspect_results(reports['panel-results'],results,result_schema,panel);check('21视图及181字段来源绑定',True)
    current=inspect_panel_integration(reports['panel-integration'],snapshots['panel-integration'],panel,results)
    check('当前完整选择',current==manifest['selection'])
    consumers=H.decode((ROOT/'consumer-report.json').read_bytes());inspect_consumers(manifest,consumers,http);check('客户端选择实际构造记录',True)
    for p in manifest['packages'][-4:]:inspect_new_sources(sdk,p,snapshots[p['name']]);check('固定双仓来源:'+p['name'],True)
    check('HTTP选择一致',http['selection']==selection)
    artifacts=read('typed-client','preview/manifest.json')['artifacts']
    check('类型生成产物集合',set(artifacts)=={'controller.d.ts','seamer.d.ts','operations.d.ts','bindings.json'})
    for p,h in artifacts.items():check('类型生成产物摘要:'+p,H.sha(snapshots['typed-client']['contracts/typed-client/preview/'+H.path_name(p)])==h)
    check('阶段未自动关闭',manifest['boundaries']==dict(stage0_complete=False,business_implementation_started=False,production_sdk_ready=False,runtime_protocol_frozen=False))
    check('当前三轮归属',manifest['cycle']==dict(rounds=[dict(round=1,repository='leafseamer-sdk',commit=manifest['packages'][-2]['commit']),dict(round=2,repository='leafseamer-sdk',commit=manifest['packages'][-1]['commit']),dict(round=3,repository='leafseamer-suite',commit='containing-commit')],push_order=['leafseamer-sdk','leafseamer-suite']))
    def denied(name,fn):
        try:fn()
        except (ValueError,KeyError,AssertionError):check(name,True)
        else:raise AssertionError(name+':未拒绝')
    p=next(p for p in manifest['packages'] if p['name']=='wire-browser');original=snapshots['wire-browser']
    bad=dict(original);bad[p['report']]+=b' ';denied('报告原件漂移',lambda:package_report(p,bad))
    wrong=copy.deepcopy(p);wrong['expected']['recorded_checks_total']+=1;denied('记录数漂移',lambda:package_report(wrong,original))
    for label,change in [('漏模式',lambda r:r['reports'].pop('plain')),('跳过伪通过',lambda r:r['reports']['plain']['report']['page'].update(skipped_shared_buffer_checks=0)),('Worker失败',lambda r:r['reports']['isolated']['report']['worker'].update(all_passed=False)),('明细摘要漂移',lambda r:r['reports']['plain']['report']['page'].update(checks_sha256='0'*64)),('资产漂移',lambda r:r['artifacts'].update({next(iter(r['artifacts'])):'0'*64}))]:
        r=read('wire-browser','browser-report.json');change(r);denied(label,lambda r=r:inspect_browser(r,original,reports['wire-routing']))
    for name in ['../escape','/absolute','C:/absolute','a//b','a\\b']:denied('非法路径:'+name,lambda name=name:H.path_name(name))
    denied('浮动提交',lambda:H.read_fixed(sdk,'main',['README.md']))
    for label,change in [('运行断言数',lambda r:r['runtime'].update(cases_passed=863)),('编译负例漏行',lambda r:r['type_negative_diagnostics'].pop()),('动态代码生成',lambda r:r['runtime'].update(dynamic_codegen_blocked=False)),('设备伪通过',lambda r:r.update(device_executed=True)),('浏览器伪通过',lambda r:r.update(browser_executed=True)),('回环计数',lambda r:r['loopback_http'].update(loopback_http_exchanges=3))]:
        r=copy.deepcopy(reports['typed-client']);change(r);denied('客户端:'+label,lambda r=r:inspect_typed(r,read('typed-client','preview/bindings.json'),http))
    b=read('typed-client','preview/bindings.json');next(o for o in b['operations'] if not o['callable'])['callable']=True
    denied('WS不得伪标普通HTTP',lambda:inspect_typed(reports['typed-client'],b,http))
    p=next(p for p in manifest['packages'] if p['name']=='http-envelope');bad=copy.deepcopy(p);bad['dependency_files_recorded']-=1
    denied('依赖记录遗漏',lambda:package_report(bad,snapshots['http-envelope']))
    for label,change in [('伪授权',lambda b:b['operations'][0].update(authorization_granted=True)),('漏操作',lambda b:b['operations'].pop()),('错认证',lambda b:b['operations'][0].update(security=[])),('丢票据迁移',lambda b:b['guard_changes'].clear())]:
        b=copy.deepcopy(authorization);change(b);denied('授权:'+label,lambda b=b:inspect_authorization(reports['authorization'],b,http))
    for label,change in [('伪安装',lambda b:b.update(installed=True)),('漏方法',lambda b:b['methods'].pop('controller.getMeta')),('降领域权限',lambda b:b['methods']['controller.submitCommand'].update(permission='status.read')),('漏当前字段',lambda b:b['methods']['controller.cancelCommand']['source_fields'].pop('body.expected_state_ref')),('透传原响应',lambda b:b['methods']['seamer.getRun'].update(raw_response_allowed=True))]:
        b=copy.deepcopy(panel);change(b);denied('面板:'+label,lambda b=b:inspect_panel(reports['panel-methods'],b,panel_schema,authorization,panel_models,panel_apis))
    for label,change in [('伪安装',lambda b:b.update(installed=True)),('漏字段',lambda b:next(iter(b['plans'].values()))['fields'].pop(next(iter(next(iter(b['plans'].values()))['fields'])))),('未知提供者',lambda b:next(v for p in b['plans'].values() for v in p['fields'].values() if v['kind']=='provider').update(provider='missing'))]:
        b=copy.deepcopy(results);change(b);denied('结果:'+label,lambda b=b:inspect_results(reports['panel-results'],b,result_schema,panel))
    for label,change in [('选择混用',lambda m:m.update(selection=m['runtime_artifact_selection'])),('伪兼容',lambda m:m['consumer_compatibility'][0].update(compatible_with_current=True))]:
        m=copy.deepcopy(manifest);change(m);denied('消费者:'+label,lambda m=m:inspect_consumers(m,consumers,http))
    for label,change in [('漏断言',lambda r:r['checks'].pop()),('传输调用',lambda r:r.update(transport_calls=1)),('探针漂移',lambda r:r.update(probe_sha256='0'*64))]:
        r=copy.deepcopy(consumers);change(r);denied('构造记录:'+label,lambda r=r:inspect_consumers(manifest,r,http))
    return dict(format='sdk-wire-handoff-report/1',all_passed=True,cases_passed=len(checks),checks=checks,sdk_main_commit=previous,
      packages=len(reports),fixed_sdk_file_bindings=sum(len(p['files']) for p in manifest['packages']),browser_checks_recorded=count,
      dependency_file_bindings_recorded=sum(p.get('dependency_files_recorded',0) for p in manifest['packages']),http_envelope_runtime_checks_recorded=12076,typed_client_runtime_checks_recorded=862,
      authorization_static_checks_recorded=655,panel_format_checks_recorded=771,panel_methods_installed=False,real_authorization_tests_executed=0,
      panel_result_checks_recorded=652,panel_integration_checks_recorded=5972,current_selection=current,runtime_artifact_selection=selection,selection_consumer_checks_recorded=17,selection_consumer_probe_rerun=False,
      stage0_complete=False,historical_behavior_rerun=False,browser_rerun=False,dependency_installation_rerun=False,device_tests_executed=0,input_sha256=local_inputs())

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sdk',type=Path);parser.add_argument('--node',type=Path,help='显式运行固定消费者构造检查并更新独立记录')
    group=parser.add_mutually_exclusive_group();group.add_argument('--report',action='store_true');group.add_argument('--check-report',action='store_true');args=parser.parse_args()
    if args.check_report:
        if args.node:parser.error('--node不能与--check-report同时使用')
        r=H.decode((ROOT/'report.json').read_bytes());H.require(r['all_passed'] and r['input_sha256']==local_inputs(),'本仓输入漂移');print(H.json.dumps(dict(all_passed=True,bindings=len(r['input_sha256']),behavior_rerun=False)))
    else:
        if not args.sdk:parser.error('需要--sdk指定SDK仓库')
        if args.node:record_consumer_probe(args.sdk.resolve(),args.node.resolve())
        r=run(args.sdk.resolve())
        if args.report:(ROOT/'report.json').write_bytes(H.encode(r))
        print(H.json.dumps({k:v for k,v in r.items() if k not in ('checks','input_sha256')},ensure_ascii=False))
