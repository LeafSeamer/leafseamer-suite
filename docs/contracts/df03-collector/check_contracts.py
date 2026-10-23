"""采集器14帧与有限单次消费模型；人工预期，不连接NTP。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from jsonschema import Draft202012Validator
from build_contracts import HERE,BASE,VERSION,FEATURES,build,encoded
import reference_model as M

ROOT=HERE.parents[2]
INPUTS=[HERE/n for n in ('README.md','build_contracts.py','collector.schema.json','reference_model.py','check_contracts.py')]+[
    BASE/'df03-reference/build_contracts.py',BASE/'df03-reference/reference.schema.json',
    BASE/'df03-reference/reference_model.py',BASE/'df03-reference/check_contracts.py',
    BASE/'df03-service/build_contracts.py',BASE/'df02-supervisor/supervisor.schema.json',
    ROOT/'docs/rebirth-df03-time-profile-design.md']


def R(n):return dict(id=n,revision='1',digest=M.T.digest(n))
def clone(v):return copy.deepcopy(v)


def fixture():
    script='import sys,json;sys.path.insert(0,sys.argv[1]);import check_contracts as C;print(json.dumps(C.fixture()))'
    tc,anchor,assessment,guard,invalidation=json.loads(subprocess.check_output([
        sys.executable,'-c',script,str(BASE/'df03-reference')],cwd=ROOT))
    binding=clone(tc['binding']);domain=binding['domain']
    channel=dict(channel_id='collector-channel',domain=domain,core_boot_id='core-boot',
        core_runtime_binding_ref=R('core-runtime'),bootstrap_receipt_ref=R('supervised-admission'),role='time_provider')
    config=M.T.seal(dict(config_id='config',revision='1',binding=binding,
        **{n:clone(tc[n]) for n in ('source','profile','policy','approval')},
        collector_artifact_ref=tc['profile']['collector_artifact_ref'],bootstrap_receipt_ref=channel['bootstrap_receipt_ref'],
        stop_generation='1',limits=dict(max_sources=1,max_outstanding=1,max_frame_bytes=262144,max_blob_bytes=1232,
            minimum_poll_interval_ns='1000000000',poll_lease_ns='3000000000',capacity_profile_ref=R('capacity'))),'config_digest')
    poll=M.T.seal(dict(poll_id='poll',revision='1',binding=binding,
        config_ref=M.T.object_ref(config,'config_id','config_digest'),correlation_ref=tc['request']['correlation_ref'],
        endpoint_ref=tc['request']['endpoint_ref'],issued_tick_ns='0',not_before_tick_ns='0',
        expires_tick_ns='2500000000',stop_generation='1'),'poll_digest')
    blobs=[dict(content_ref=tc['request']['request_bytes_ref'],size=160,purpose='request',owner=domain,sensitive=True,sealed_ref=R('request-sealed')),
           dict(content_ref=tc['exchange']['response_bytes_ref'],size=160,purpose='response',owner=domain,sensitive=True,sealed_ref=R('response-sealed'))]
    capture=M.T.seal(dict(capture_id='capture',revision='1',poll_ref=M.T.object_ref(poll,'poll_id','poll_digest'),
        binding=binding,reported_tick_ns='700000100',status='candidate',
        **{n:clone(tc[n]) for n in ('request','exchange','authentication','error','era')},failure=None,blobs=blobs),'capture_digest')
    receipt=M.T.seal(dict(receipt_id='receipt',revision='1',capture_ref=M.T.object_ref(capture,'capture_id','capture_digest'),
        poll_ref=capture['poll_ref'],result='published',record_ref=R('publication'),
        anchor_ref=M.T.object_ref(anchor,'anchor_id','anchor_digest')),'receipt_digest')
    stop=M.T.seal(dict(stop_id='stop',revision='1',config_ref=poll['config_ref'],stop_generation='2',poll_refs=[capture['poll_ref']]),'stop_digest')
    context=dict(channel=clone(channel),peer_verified=True,runtime_valid=True,time_context=tc,
        approved_config=clone(config),config=clone(config),stopped=False,stop_generation='1',
        approved_endpoints=[poll['endpoint_ref']],verified_capture=clone(capture),sealed_blobs_verified=True,
        approved_stop=clone(stop),current_authorized=True,storage_healthy=True)
    bodies=dict(HELLO=dict(version=VERSION,features=FEATURES),ACCEPT=dict(version=VERSION,features=FEATURES),
        CONFIGURE=dict(configuration=config),CONFIG_ACK=dict(config_ref=poll['config_ref'],result='configured',reason=None),
        POLL=dict(poll=poll),POLL_ACK=dict(poll_ref=capture['poll_ref'],result='reserved',reason=None),
        CAPTURE_REPORT=dict(capture=capture),REPORT_STORED=dict(receipt=receipt),
        QUERY_CAPTURE=dict(poll_ref=capture['poll_ref']),CAPTURE_STATUS=dict(poll_ref=capture['poll_ref'],state='reported',capture=capture),
        QUERY_COMMIT=dict(capture_ref=receipt['capture_ref']),COMMIT_STATUS=dict(capture_ref=receipt['capture_ref'],state='known',receipt=receipt),
        STOP=dict(stop=stop),STOP_ACK=dict(stop_ref=M.T.object_ref(stop,'stop_id','stop_digest'),consumed_poll_refs=[capture['poll_ref']],closed_tick_ns='800000100'))
    outgoing={'ACCEPT','CONFIGURE','POLL','REPORT_STORED','QUERY_CAPTURE','COMMIT_STATUS','STOP'}
    responses={'ACCEPT','CONFIG_ACK','POLL_ACK','REPORT_STORED','CAPTURE_STATUS','COMMIT_STATUS','STOP_ACK'}
    frames={n:dict(version=VERSION,type=n,channel=clone(channel),direction='core_to_collector' if n in outgoing else 'collector_to_core',
        message_id='message-'+n,sequence='1',reply_to='request' if n in responses else None,body=clone(b)) for n,b in bodies.items()}
    return context,poll,capture,receipt,stop,frames


def run():
    checks=[]
    def check(name,actual,expected=None):
        assert actual==expected,(name,actual,expected)
        compound=isinstance(expected,(dict,list,tuple))
        checks.append(dict(name=name,actual=True if compound else actual,expected=True if compound else expected))
    schema=build();check('生成字节',(HERE/'collector.schema.json').read_bytes()==encoded(schema),True)
    Draft202012Validator.check_schema(schema);v=Draft202012Validator(schema)
    valid=lambda n,x:Draft202012Validator({**schema,'oneOf':[{'$ref':'#/$defs/'+n}]}).is_valid(x)
    c,p,cap,receipt,st,frames=fixture()
    check('完整帧数',len(frames),14)
    for n,f in frames.items():
        check('正例:'+n,v.is_valid(f),True)
        z=clone(f);z['version']='ipc/0.8.0-reference-time-draft.1';check('拒设备协议:'+n,v.is_valid(z),False)
        z=clone(f);z['direction']='collector_to_core' if f['direction']=='core_to_collector' else 'core_to_collector'
        check('拒错方向:'+n,v.is_valid(z),False)
    for n in ('HELLO','ACCEPT'):
        for feature in FEATURES:
            z=clone(frames[n]);z['body']['features'].remove(feature);check('缺特性:'+n+feature,v.is_valid(z),False)
    for n in ('Capture','PollIntent','Configuration','Channel','Limits','CommitReceipt','Stop','BlobDescriptor'):
        x={'Capture':cap,'PollIntent':p,'Configuration':c['config'],'Channel':c['channel'],
           'Limits':c['config']['limits'],'CommitReceipt':receipt,'Stop':st,'BlobDescriptor':cap['blobs'][0]}[n]
        check('具名正例:'+n,valid(n,x),True)
        z=clone(x);z['secret']='synthetic';check('拒额外字段:'+n,valid(n,z),False)
    for key in ('request','exchange','authentication','error','era'):
        z=clone(cap);z[key]=None;check('候选不可缺:'+key,valid('Capture',z),False)
    failure=M.T.seal(dict(failure_id='failure',revision='1',domain=c['channel']['domain'],request_ref=None,
        observed_tick_ns='50',reason='timeout',diagnostic_ref=None),'failure_digest')
    z=clone(cap);z.update(status='failed',request=None,exchange=None,authentication=None,error=None,era=None,failure=failure,blobs=[])
    M.T.seal(z,'capture_digest');check('失败可无Request',valid('Capture',z),True)
    z['exchange']=cap['exchange'];check('失败不可夹带合格交换',valid('Capture',z),False)
    check('配置关联',M.configuration_error(c['config'],c))
    for field in ('core_boot_id','role'):
        z=clone(c['channel']);z[field]='other';check('启动身份错配:'+field,M.channel_error(z,c),'peer')
    for field in ('bootstrap_receipt_ref','collector_artifact_ref'):
        z=clone(c['config']);z[field]=R('other');M.T.seal(z,'config_digest')
        cc=clone(c);cc['approved_config']=z
        check('重新摘要仍核配置:'+field,M.configuration_error(z,cc),'binding' if field=='bootstrap_receipt_ref' else 'artifact')
    ledger={};check('首次保留',M.reserve(p,ledger,c,100),'reserved')
    saved=clone(ledger);check('POLL重复只查原',M.reserve(p,ledger,c,100),'historical');check('重复账本不变',ledger,saved)
    check('消费后IO前故障',M.consume('poll',ledger,c,100,True),'unknown')
    check('消费不可再发',M.consume('poll',ledger,c,101),'no_resend')
    check('崩溃缓存丢失不可发',M.consume('poll',{},c,101),'cache_missing')
    check('候选证据关联',M.capture_error(cap,p,c))
    check('保存候选',M.record_capture(cap,ledger,c),'reported')
    saved=clone(ledger);check('候选重投查原',M.record_capture(cap,ledger,c),'historical');check('重投不改账本',ledger,saved)
    next_poll=clone(p);next_poll.update(poll_id='next-poll',correlation_ref=R('next-correlation'));M.T.seal(next_poll,'poll_digest')
    check('报告后可保留新poll',M.reserve(next_poll,ledger,c,200),'reserved')
    check('新poll不能绕最小间隔',M.consume('next-poll',ledger,c,200),'interval')
    check('间隔等号允许继续门控',M.consume('next-poll',ledger,c,1000000100),'io_allowed_once')
    z=clone(cap);z.update(status='indeterminate',exchange=None,authentication=None,error=None,era=None,blobs=[])
    M.T.seal(z,'capture_digest');check('未知捕获可表达',valid('Capture',z),True)
    cc=clone(c);cc['verified_capture']=z;check('未知捕获不能作候选',M.capture_error(z,p,cc),'not_candidate')
    for field in ('binding','poll_ref','request','blobs'):
        z=clone(cap)
        if field=='binding':z[field]['time_generation']='2'
        elif field=='poll_ref':z[field]['id']='other'
        elif field=='request':z[field]['endpoint_ref']=R('other');M.T.seal(z[field],'request_digest')
        else:z[field][1]['size']=159
        M.T.seal(z,'capture_digest');cc=clone(c);cc['verified_capture']=z
        check('重算摘要仍拒报告:'+field,M.capture_error(z,p,cc),
              'binding' if field in ('binding','poll_ref') else 'request' if field=='request' else 'blobs')
    cc=clone(c);cc['sealed_blobs_verified']=False;check('字节未取证拒绝',M.capture_error(cap,p,cc),'blobs')
    z=clone(p);z['expires_tick_ns']=cap['exchange']['receive_after_tick_ns'];M.T.seal(z,'poll_digest')
    zc=clone(cap);zc['poll_ref']=M.T.object_ref(z,'poll_id','poll_digest');M.T.seal(zc,'capture_digest')
    cc=clone(c);cc['verified_capture']=zc;check('m4截止等号拒绝',M.capture_error(zc,z,cc),'expired')
    ledger={};M.reserve(p,ledger,c,100)
    check('消费截止等号拒绝',M.consume('poll',ledger,c,2500000000),'expired')
    another=clone(p);another.update(poll_id='second',correlation_ref=R('second-correlation'));M.T.seal(another,'poll_digest')
    check('源单飞与容量拒绝',M.reserve(another,ledger,c,100),'capacity')
    check('STOP关闭未消费',M.stop(st,ledger,c),'closed')
    check('STOP后原poll不可发',M.consume('poll',ledger,c,101),'no_resend')
    check('迟到新poll不可开闸',M.reserve(another,ledger,c,101),'stopped')
    check('STOP重复不二次推进',M.stop(st,ledger,c),'historical')
    check('停止下界保持',c['stop_generation'],'2')
    c,p,cap,receipt,st,frames=fixture();ledger={};M.reserve(p,ledger,c,100);M.consume('poll',ledger,c,100)
    short=clone(st);short['poll_refs']=[];M.T.seal(short,'stop_digest');c['approved_stop']=short
    check('STOP漏捕获拒绝',M.stop(short,ledger,c),'coverage')
    c['approved_stop']=st;check('STOP不清消费未知',M.stop(st,ledger,c),'closed')
    check('已消费状态保持',ledger['poll']['state'],'consumed')
    ack=frames['STOP_ACK']['body'];check('停止ACK完整覆盖',M.stop_ack_error(ack,st,ledger,c))
    bad=clone(ack);bad['consumed_poll_refs']=[];check('ACK不能假报未消费',M.stop_ack_error(bad,st,ledger,c),'coverage')
    bad=clone(ack);bad['consumed_poll_refs'].append(R('other'));check('ACK不能加入无关poll',M.stop_ack_error(bad,st,ledger,c),'coverage')
    bad=clone(ack);bad['closed_tick_ns']='99';check('ACK时刻不能早于消费',M.stop_ack_error(bad,st,ledger,c),'order')
    check('未知commit不授重发',M.lookup_commit(receipt['capture_ref'],{},c),'not_found')
    stored={'capture':receipt};check('回执原文可查',M.lookup_commit(receipt['capture_ref'],stored,c),receipt)
    cc=clone(c);cc['current_authorized']=False;check('当前权优先历史',M.lookup_commit(receipt['capture_ref'],stored,cc),'forbidden')
    seen={};f=frames['HELLO'];check('首序号',M.accept_envelope(f,c,seen,0),('accepted',1))
    check('同帧不重复执行',M.accept_envelope(f,c,seen,1),('duplicate',1))
    z=clone(f);z['body']['features'].append('other');check('同id换内容',M.accept_envelope(z,c,seen,1),('identity_conflict',1))
    z=clone(f);z.update(message_id='new',sequence='3');check('序号缺口',M.accept_envelope(z,c,seen,1),('sequence',1))
    # 合法Ref只是结构，不能代替受监督身份或Blob原件提供者。
    check('合成未验证引用可过结构',valid('Channel',{**c['channel'],'bootstrap_receipt_ref':R('unverified')}),True)
    return checks


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需配合--check-report')
    if a.check_report:
        read=(lambda path:subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()],cwd=ROOT)) if a.staged else Path.read_bytes
        r=json.loads(read(HERE/'reference-report.json'))
        assert set(r['inputs'])=={x.relative_to(ROOT).as_posix() for x in INPUTS}
        for x in INPUTS:assert r['inputs'][x.relative_to(ROOT).as_posix()]==hashlib.sha256(read(x)).hexdigest(),x
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();r=dict(all_passed=True,cases_passed=len(checks),approved=False,
            runtime_tests_executed=0,ntp_tests_executed=0,sqlite_tests_executed=0,device_tests_executed=0,
            scope='14帧结构与合成身份和有限单次采样停止模型',checks=checks,
            inputs={x.relative_to(ROOT).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in INPUTS})
        if a.report:(HERE/'reference-report.json').write_bytes(encoded(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')},ensure_ascii=False))
