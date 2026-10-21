"""有限有序通道参考判定；真实IPC、时钟、事务与权威提供者均未实现。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from jsonschema import Draft202012Validator
import check_contracts as old
from build_channel_v02 import build, encoded, VERSION, FEATURES

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
T=old.M.T
INPUTS=list(dict.fromkeys([HERE/n for n in ('CHANNEL_V02.md','build_channel_v02.py','check_channel_v02.py',
        'channel-v02.schema.json')]+old.INPUTS))


def ref(value, stem):
    return T.object_ref(value, stem+'_id', stem+'_digest')


def fixtures():
    context,poll,capture,receipt,stop,frames=old.fixture()
    poll['poll_ordinal']='1';T.seal(poll,'poll_digest')
    capture['poll_ref']=ref(poll,'poll');T.seal(capture,'capture_digest')
    context['verified_capture']=copy.deepcopy(capture)
    receipt.update(poll_ref=ref(poll,'poll'),capture_ref=ref(capture,'capture'));T.seal(receipt,'receipt_digest')
    stop.pop('poll_refs');stop.update(cut_sequence='1',last_poll_ordinal='1');T.seal(stop,'stop_digest')
    frames['POLL']['body']['poll']=poll
    frames['CAPTURE_REPORT']['body']['capture']=capture
    frames['REPORT_STORED']['body']['receipt']=receipt
    frames['STOP']['body']['stop']=stop
    frames['STOP']['sequence']='2'
    frames['STOP_ACK']['body']=dict(stop_ref=ref(stop,'stop'),received_through_sequence='2',
        last_poll_ordinal='1',gate_closed=True,closed_tick_ns='800000100')
    for name,frame in frames.items():
        frame['version']=VERSION
        if name in ('HELLO','ACCEPT'):
            frame['body']['version']=VERSION
            frame['body']['features']+=FEATURES
    return context,poll,capture,receipt,stop,frames


class ChannelModel:
    """假定已完成启动和配置；仅模拟本轮新增的单一串行执行队列。"""
    def __init__(self,context):
        self.context=copy.deepcopy(context)
        self.sequence=0;self.ordinal=0;self.pending={};self.last=None;self.last_result=None
        self.closed=False;self.faulted=False;self.stop_frame=None;self.stop_ack=None;self.last_consumed=None;self.sends=0

    def frame(self,frame,now):
        c=self.context
        if self.faulted:return 'retire_required'
        if not c['peer_verified'] or not c['runtime_valid'] or frame['channel']!=c['channel']:
            self.closed=True;self.faulted=True;return 'identity'
        if not Draft202012Validator(build()).is_valid(frame) or frame['direction']!='core_to_collector':
            self.closed=True;self.faulted=True;return 'shape'
        if self.stop_frame is not None and frame==self.stop_frame:
            return copy.deepcopy(self.stop_ack)
        if frame==self.last:
            return copy.deepcopy(self.last_result)
        prior=self.sequence
        if int(frame['sequence'])!=prior+1:
            self.closed=True;self.faulted=True;return 'sequence'
        self.sequence+=1
        kind=frame['type'];body=frame['body']
        if kind=='POLL':
            result=self.reserve(body['poll'],now)
        elif kind=='REPORT_STORED':
            result=self.stored(body['receipt'])
        elif kind=='STOP':
            result=self.stop(frame,prior,now)
        else:
            result='outside_model'
        self.last=copy.deepcopy(frame);self.last_result=copy.deepcopy(result)
        return result

    def reserve(self,poll,now):
        if self.closed:return 'stopped'
        c=self.context
        if old.M.configuration_error(c['config'],c) or not T.intact(poll,'poll_digest'):
            self.closed=True;self.faulted=True;return 'authority'
        ordinal=int(poll['poll_ordinal'])
        if ordinal<=self.ordinal:return 'old_poll'
        if ordinal!=self.ordinal+1:
            self.closed=True;self.faulted=True;return 'poll_gap'
        self.ordinal=ordinal
        config=c['config']
        if (poll['binding']!=config['binding'] or poll['config_ref']!=ref(config,'config') or
            poll['stop_generation']!=c['stop_generation'] or poll['endpoint_ref'] not in c['approved_endpoints']):
            return 'binding'
        if not int(poll['issued_tick_ns'])<=int(poll['not_before_tick_ns'])<=now<int(poll['expires_tick_ns']):return 'expired'
        if int(poll['expires_tick_ns'])-int(poll['issued_tick_ns'])>int(config['limits']['poll_lease_ns']):return 'expired'
        if self.pending:return 'capacity'  # 每配置仅一个Source，reported也占单飞槽。
        self.pending[poll['poll_id']]=dict(poll=copy.deepcopy(poll),state='reserved',consumed_tick=None)
        return 'reserved'

    def consume(self,poll_id,now):
        if self.closed:return 'stopped'
        if self.last_consumed is not None and now-self.last_consumed<int(self.context['config']['limits']['minimum_poll_interval_ns']):return 'interval'
        result=old.M.consume(poll_id,self.pending,self.context,now)
        if result=='io_allowed_once':
            self.last_consumed=now;self.sends+=1
        return result

    def report(self,capture):
        return old.M.record_capture(capture,self.pending,self.context)

    def stored(self,receipt):
        if receipt!=self.context.get('trusted_receipt') or not T.intact(receipt,'receipt_digest'):return 'authority'
        entry=self.pending.get(receipt['poll_ref']['id'])
        if entry is None:return 'retired_or_unknown'
        if ('capture' not in entry or receipt['poll_ref']!=ref(entry['poll'],'poll') or
            receipt['capture_ref']!=ref(entry['capture'],'capture')):return 'binding'
        del self.pending[receipt['poll_ref']['id']]
        return 'released'

    def stop(self,frame,prior,now):
        stop=frame['body']['stop'];c=self.context
        if self.stop_frame is not None:return 'stop_conflict'
        if (not T.intact(stop,'stop_digest') or stop['config_ref']!=ref(c['config'],'config') or
            int(stop['stop_generation'])!=int(c['stop_generation'])+1):
            self.closed=True;self.faulted=True;return 'stop_binding'
        self.closed=True
        if (int(stop['cut_sequence'])!=prior or int(stop['last_poll_ordinal'])!=self.ordinal or
            self.last_consumed is not None and now<self.last_consumed):
            self.faulted=True;return 'retire_required'
        self.stop_frame=copy.deepcopy(frame)
        self.stop_ack=dict(stop_ref=ref(stop,'stop'),received_through_sequence=str(self.sequence),
            last_poll_ordinal=str(self.ordinal),gate_closed=True,closed_tick_ns=str(now))
        return copy.deepcopy(self.stop_ack)


def capacity_error(request,reservations,profile):
    """核心可信完整快照的有限判定，不分配真实跨实例槽或执行SQL。"""
    active=[r for r in reservations if r['active']]
    if any(r['source_slot']==request['source_slot'] for r in active):return 'source_busy'
    if len(active)>=profile['max_outstanding']:return 'outstanding'
    sources={r['source_slot'] for r in active}|{request['source_slot']}
    if len(sources)>profile['max_sources']:return 'sources'
    if sum(r['bytes'] for r in active)+request['bytes']>profile['available_bytes']:return 'bytes'


def run():
    checks=[]
    def check(name,actual,expected):
        assert actual==expected,(name,actual,expected)
        compound=isinstance(expected,(dict,list,tuple))
        checks.append(dict(name=name,observed=True if compound else actual,expected=True if compound else expected))
    schema=build();Draft202012Validator.check_schema(schema)
    check('生成字节',(HERE/'channel-v02.schema.json').read_bytes()==encoded(schema),True)
    validator=Draft202012Validator(schema)
    c,p,cap,receipt,stop,frames=fixtures()
    for name,frame in frames.items():
        check('14帧正例'+name,validator.is_valid(frame),True)
        bad=copy.deepcopy(frame);bad['version']='time-collector/0.1.0-draft.1'
        check('拒旧帧'+name,validator.is_valid(bad),False)
    for name in ('HELLO','ACCEPT'):
        for feature in FEATURES:
            bad=copy.deepcopy(frames[name]);bad['body']['features'].remove(feature)
            check('缺新特性'+name+feature,validator.is_valid(bad),False)
    for field in ('cut_sequence','last_poll_ordinal'):
        bad=copy.deepcopy(frames['STOP']);del bad['body']['stop'][field]
        check('STOP缺字段'+field,validator.is_valid(bad),False)
    bad=copy.deepcopy(frames['STOP']);bad['body']['stop']['poll_refs']=[]
    check('拒旧集合语义',validator.is_valid(bad),False)
    # 旧模型原样复现不同观察快照和reported槽提前释放。
    oc,op,ocap,_,ost,_=old.fixture();ledger={}
    old.M.reserve(op,ledger,oc,100);old.M.consume(op['poll_id'],ledger,oc,100)
    old.M.record_capture(ocap,ledger,oc)
    check('旧STOP对reported发生集合冲突',old.M.stop(ost,ledger,oc),'coverage')
    op2=copy.deepcopy(op);op2.update(poll_id='other',correlation_ref=old.R('other'))
    T.seal(op2,'poll_digest')
    check('旧reported未持久却允许下一采样',old.M.reserve(op2,ledger,oc,100),'reserved')
    def ready():
        m=ChannelModel(c)
        check('新实例接受第一POLL',m.frame(frames['POLL'],100),'reserved')
        return m
    m=ready();check('一次消费',m.consume('poll',100),'io_allowed_once')
    check('报告',m.report(cap),'reported')
    check('报告未达核心仍能STOP',m.frame(frames['STOP'],800000100),frames['STOP_ACK']['body'])
    check('STOP后不可消费',m.consume('poll',900000100),'stopped')
    check('STOP不删除未决原件',len(m.pending),1)
    check('同STOP重复只回原ACK',m.frame(frames['STOP'],900000100),frames['STOP_ACK']['body'])
    check('重复STOP不再发送',m.sends,1)
    conflicting=copy.deepcopy(frames['STOP']);conflicting.update(sequence='3',message_id='replacement-stop')
    conflicting['body']['stop'].update(stop_id='replacement',cut_sequence='2');T.seal(conflicting['body']['stop'],'stop_digest')
    check('不能换新stop身份覆盖原ACK',m.frame(conflicting,900000100),'stop_conflict')
    check('原STOP在后续消息后仍可查',m.frame(frames['STOP'],1000000100),frames['STOP_ACK']['body'])
    m=ready();check('STOP先到',isinstance(m.frame(frames['STOP'],100),dict),True)
    check('STOP先到不发送',m.consume('poll',101),'stopped');check('发送数为零',m.sends,0)
    for mutation,error in [('sequence','sequence'),('cut','retire_required'),('ordinal','retire_required'),('config','stop_binding')]:
        m=ready();bad=copy.deepcopy(frames['STOP'])
        if mutation=='sequence':bad['sequence']='3'
        elif mutation=='cut':bad['body']['stop']['cut_sequence']='0'
        elif mutation=='ordinal':bad['body']['stop']['last_poll_ordinal']='2'
        else:bad['body']['stop']['config_ref']=old.R('other')
        T.seal(bad['body']['stop'],'stop_digest')
        check('切点错配'+mutation,m.frame(bad,100),error)
        check('错配仍关闸'+mutation,m.closed,True)
        check('协议故障不自行恢复'+mutation,m.frame(frames['STOP'],200),'retire_required')
    m=ready();m.consume('poll',100);m.report(cap)
    newpoll=copy.deepcopy(p);newpoll.update(poll_id='second',poll_ordinal='2',correlation_ref=old.R('second'))
    T.seal(newpoll,'poll_digest')
    frame=copy.deepcopy(frames['POLL']);frame.update(sequence='2',message_id='second');frame['body']['poll']=newpoll
    check('reported占单飞槽',m.frame(frame,100),'capacity')
    check('容量拒绝仍消耗ordinal',m.ordinal,2)
    m=ready();m.consume('poll',100);m.report(cap);m.context['trusted_receipt']=copy.deepcopy(receipt)
    received=copy.deepcopy(frames['REPORT_STORED']);received['sequence']='2'
    check('精确持久回执释放',m.frame(received,800000100),'released')
    check('释放后本机详情有界',len(m.pending),0)
    replay=copy.deepcopy(frames['POLL']);replay.update(sequence='3',message_id='old-replay')
    check('新帧旧ordinal不重发',m.frame(replay,900000100),'old_poll')
    frame['sequence']='4'
    check('新ordinal可保留新采样',m.frame(frame,1000000100),'reserved')
    check('保留最后m1的间隔边界',m.consume('second',1000000099),'interval')
    check('间隔等号可发送',m.consume('second',1000000100),'io_allowed_once')
    check('总发送只两次',m.sends,2)
    m=ready();m.consume('poll',100);m.report(cap)
    check('无可信回执不释放',m.frame(received,800000100),'authority')
    check('仍保留原件',len(m.pending),1)
    m=ready();bad=copy.deepcopy(frame);bad['sequence']='2';bad['body']['poll']['poll_ordinal']='3';T.seal(bad['body']['poll'],'poll_digest')
    check('poll跳号关闭',m.frame(bad,100),'poll_gap')
    check('跳号无后续发送',m.closed,True)
    for key in ('peer_verified','runtime_valid'):
        m=ChannelModel({**c,key:False});check('拒失效身份'+key,m.frame(frames['POLL'],100),'identity')
    profile=dict(max_sources=2,max_outstanding=2,available_bytes=200)
    request=dict(source_slot='s2',bytes=100)
    active=[dict(source_slot='s1',bytes=100,active=True)]
    check('容量等号允许',capacity_error(request,active,profile),None)
    check('别名源不绕过占用',capacity_error(dict(source_slot='s1',bytes=1),active,profile),'source_busy')
    check('核心全局在途限制',capacity_error(request,active,{**profile,'max_outstanding':1}),'outstanding')
    check('核心来源数量限制',capacity_error(request,active,{**profile,'max_sources':1}),'sources')
    check('核心字节不足',capacity_error({**request,'bytes':101},active,profile),'bytes')
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true')
    parser.add_argument('--check-report',action='store_true');parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    path=HERE/'channel-v02-report.json'
    if args.check_report:
        read=(lambda p:subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT)) if args.staged else Path.read_bytes
        report=json.loads(read(path));assert set(report['inputs'])=={p.relative_to(ROOT).as_posix() for p in INPUTS}
        for p in INPUTS:assert hashlib.sha256(read(p)).hexdigest()==report['inputs'][p.relative_to(ROOT).as_posix()],p
        print(f'{len(INPUTS)}项输入绑定一致，未重跑检查')
    else:
        if args.staged:parser.error('--staged需配合--check-report')
        checks=run();report=dict(approved=False,all_passed=True,cases_passed=len(checks),checks=checks,
            runtime_validation=dict(ipc=0,ntp=0,sqlite=0,cryptography=0,process_retirement=0,device=0),
            inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS})
        if args.report:path.write_bytes(encoded(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')},ensure_ascii=False))
