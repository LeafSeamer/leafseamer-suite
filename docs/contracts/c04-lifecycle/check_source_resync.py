"""来源恢复三阶段、旧历史隔离与显式运行恢复的内存验收。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
import source_resync_model as M
import check_workload_budget as W
G=M.G;B=M.B;A=M.A;P=M.P;R=M.R;I=M.I;T=W.T;C=W.C;AT=W.AT;F=W.F;FLOW=W.FLOW;RB=W.RB
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(W.INPUTS+G.SOURCES+[HERE/n for n in ('SOURCE_RESYNC.md','source-resync.schema.json','source_resync_model.py','check_source_resync.py','seamer-source-resync.sql')]))
INPUTS+= [HERE.parent/'c04-preparation'/'README.md',HERE.parent/'c04-storage'/'README.md',ROOT/'docs/rebirth-c05-event-sync-design.md']
INPUTS=list(dict.fromkeys(INPUTS))

def ref(ident):return dict(scope=dict(authority_service_id='synthetic.provider',database_instance_id='synthetic.db'),id=ident,revision='1',digest=AT.H)

def fixture(*,fault=True,limits=(64,8),arm=True):
    d,q,c,ts=T.fixture(arm=arm,sql_factory=G.build)
    d.execute(*I('rs_limit',singleton=1,purpose='simulation',max_transitions=limits[0],max_deltas=limits[1]))
    c.update(delivery_current=True,delivery_ref=ref('delivery'),snapshot_verified=True,snapshot_ref=ref('snapshot'),continuity_verified=True,event_ref=ref('event.11'),checkpoint_verified=True,checkpoint_ref=ref('checkpoint'))
    if fault:B.protect(d,C.fault('1'),c)
    return d,q,c,ts

def request(d,c,kind='baseline',*,source='source',baseline='baseline.1',ident=None):
    s=R.one(d,'ingress_source','source_id',source);ident=ident or dict(baseline=baseline,delta='delta.1',ready='ready.1')[kind]
    q=dict(contract_version=G.VERSION,transition_id=ident,baseline_id=baseline,source_id=source,source_key_digest=P.digest(s['source_key']),fault_id='fault.1',kind=kind,
        expected_source_revision=s['revision'],delivery_ref=c['delivery_ref'],request_epoch='resync.epoch',actor=dict(principal_id='operator'),idempotency_key=ident)
    if kind=='baseline':q.update(watermark='10',snapshot_ref=c['snapshot_ref'])
    elif kind=='delta':q.update(source_sequence=P.inc(s['contiguous_sequence']),event_ref=c['event_ref'])
    else:q.update(through_sequence=s['contiguous_sequence'],last_delta_id='delta.1',checkpoint_ref=c['checkpoint_ref'])
    return q

def observe(d):
    for p in P.rows(d,'SELECT * FROM sp_target'):
        binding=json.loads(p['binding_body']);C.SP.receive(d,p['plan_id'],p['target_id'],C.observation(binding),binding['controller_scope'])

def invariant(d):
    names=('run','activation_slot','execution','pause_latch','p1_deny','p1_fault','p1_plan','p1_dependency','command_submission','pb_use','pb_commit','ib_use','sb_reservation')
    return {n:[tuple(x) for x in d.execute('SELECT * FROM '+n)] for n in names}

def run():
    checks=[];dbs=[]
    def check(n,v,e=True):assert v==e,(n,v,e);checks.append(dict(name=n,observed=v,expected=e))
    def f(**kw):
        v=fixture(**kw);dbs.append(v[0]);return v
    def denied(n,d,call,reason=None):
        old=C.snapshot(d)
        try:call()
        except (sqlite3.IntegrityError,ValueError,RuntimeError,M.jsonschema.ValidationError) as err:
            if reason:assert reason in str(err),(n,str(err),reason)
            check(n,C.snapshot(d)==old);return
        raise AssertionError(n)
    try:
        check('生成SQL字节',(HERE/'seamer-source-resync.sql').read_bytes()==G.build())
        check('生成Schema字节',(HERE/'source-resync.schema.json').read_bytes()==G.schema_bytes());M.jsonschema.Draft202012Validator.check_schema(G.schema())
        d,q,c,ts=f();check('109表来源恢复',len(C.snapshot(d)),109);stable=invariant(d)
        for kind in ('baseline','delta','ready'):
            req=request(d,c,kind);writes=AT.planned(d,lambda:M.transition_steps(d,req,c))
            for i in range(len(writes)):
                denied(kind+'漏写'+str(i),d,lambda i=i:C.execute(d,writes[:i]+writes[i+1:]))
                denied(kind+'写后故障'+str(i),d,lambda i=i:M.apply(d,req,c,fail_after=i),'injected')
            for field in req:
                bad=copy.deepcopy(req);bad.pop(field);denied(kind+'缺字段'+field,d,lambda bad=bad:M.apply(d,bad,c))
            denied(kind+'无当前授权',d,lambda:M.apply(d,req,dict(c,current=False)),'resync_authority')
            denied(kind+'换输送绑定',d,lambda:M.apply(d,dict(req,delivery_ref=ref('other')),c),'resync_delivery_binding')
            proof=dict(baseline='snapshot_ref',delta='event_ref',ready='checkpoint_ref')[kind]
            missing_ref=copy.deepcopy(req);missing_ref[proof].pop('id')
            denied(kind+'SQL不能省略证据身份',d,lambda:C.execute(d,C.mutate(writes,'rs_transition',dict(request_body=P.canonical(missing_ref)))),'resync_reference_required')
            for table,patch in [('rs_transition',dict(revision_after='999')),('rs_transition',dict(request_digest='bad')),('rs_commit',dict(request_digest='sha256:'+'0'*64)),('rs_commit',dict(notification_body=b''))]:
                denied(kind+'SQL错配'+str(patch),d,lambda table=table,patch=patch:C.execute(d,C.mutate(writes,table,patch)))
            check(kind+'提交',M.apply(d,req,c),'accepted');check(kind+'不恢复run不退款',invariant(d)==stable)
            old=C.snapshot(d);check(kind+'重复查原',M.apply(d,req,dict(c,delivery_current=False,snapshot_verified=False)),'existing');check(kind+'查原零写',C.snapshot(d)==old)
            denied(kind+'幂等身份冲突',d,lambda:M.apply(d,dict(req,transition_id='different'),c),'identity_conflict')
            if kind=='baseline':
                check('基线不直接同步',R.one(d,'ingress_source','source_id','source')['state'],'baseline_required')
                premature=request(d,c,'ready');denied('没有连续增量不能ready',d,lambda:M.apply(d,premature,c),'resync_continuity_or_capacity')
                denied('baseline期间不能live摄取',d,lambda:F.receive_event(d,W.event(11),c),'source_frontier')
            if kind=='delta':
                check('补齐不创建直播执行',d.execute('SELECT count(*) FROM execution').fetchone()[0],0)
                replay=request(d,c,'delta',ident='delta.2');denied('事件证据不能改序号重复使用',d,lambda:M.apply(d,replay,c),'UNIQUE')
                gap=dict(request(d,c,'delta',ident='delta.gap'),source_sequence='13',event_ref=ref('event.13'))
                denied('连续增量不得跳号',d,lambda:M.apply(d,gap,dict(c,event_ref=gap['event_ref'])),'resync_sequence_gap')
        check('检查点后来源同步',R.one(d,'ingress_source','source_id','source')['state'],'synchronized')
        check('旧缺口仍保留',d.execute('SELECT count(*) FROM p1_fault').fetchone()[0],1)
        check('基线拒收floor保留',R.one(d,'ingress_source','source_id','source')['reject_floor'],'10')
        denied('未曾摄取的旧历史不得live补动作',d,lambda:F.receive_event(d,W.event(10),c),'source_frontier')
        F.receive_event(d,W.event(12),c);check('source变绿仍抑制运行',d.execute('SELECT result FROM ingress_decision').fetchone()[0],'suppressed_inactive')
        # 保护证据观测合格后，显式R2/R4/R5才恢复运行；所有保护消费原件保持。
        rq,rc=W.recovery(d,c,ts);rq['resolved_latches']=[x[0] for x in d.execute('SELECT latch_id FROM pause_latch WHERE cleared_start_id IS NULL')]
        RB.M.reserve(d,rq,rc);RB.prepared(d,rq)
        denied('来源同步不代替R4的Controller保护证据',d,lambda:R.apply(d,lambda:R.start_steps(d,rq['operation_id'],rc)))
        observe(d);R.apply(d,lambda:R.start_steps(d,rq['operation_id'],rc));RB.finish(d,rq)
        check('显式恢复推进新代次',tuple(d.execute('SELECT lifecycle,arm_generation FROM run').fetchone()),('armed','2'))
        denied('恢复准备不可复用到新触发且提前拒绝',d,lambda:W.execute(d,c,13),'resync_plan_target_unprepared')
        check('缺继续运行转交时未派发部分动作',d.execute('SELECT count(*) FROM command_submission').fetchone()[0],0)
        check('来源恢复未补保护额度',d.execute("SELECT episodes_left FROM sb_balance WHERE source_id='source'").fetchone()[0],1)
        # 更大整数仍精确递增，基线与补齐均不使用double或64位整体转换。
        d,q,c,ts=f();req=request(d,c);req['watermark']='9007199254740999';M.apply(d,req,c)
        delta=request(d,c,'delta');M.apply(d,delta,c);check('跨安全整数边界精确补齐',R.one(d,'ingress_source','source_id','source')['contiguous_sequence'],'9007199254741000')
        d,q,c,ts=f();req=request(d,c);req['watermark']='9999999999';M.apply(d,req,c);M.apply(d,request(d,c,'delta'),c)
        check('跨十位分段进位精确',R.one(d,'ingress_source','source_id','source')['contiguous_sequence'],'10000000000')
        d,q,c,ts=f()
        for bad in ('01','-1','1e2',1,'99999999999999999999'):
            denied('非法或耗尽基线水位'+str(bad),d,lambda bad=bad:M.apply(d,dict(request(d,c),watermark=bad),c))
        # 零run来源仍能重新同步，但不能借此增加独享保护份数。
        d,q,c,ts=f(fault=False,arm=False);B.protect(d,C.fault('1','empty.a'),c)
        for kind in ('baseline','delta','ready'):M.apply(d,request(d,c,kind,source='empty.a'),c)
        check('零run来源同步成功',R.one(d,'ingress_source','source_id','empty.a')['state'],'synchronized')
        # 缓存写集不能越过新故障，即使其公开摘要仍合法。
        d,q,c,ts=f();req=request(d,c);writes=AT.planned(d,lambda:M.transition_steps(d,req,c));B.protect(d,C.fault('2'),c)
        denied('新故障后缓存基线拒绝',d,lambda:C.execute(d,writes),'resync_prestate_or_source')
        denied('来源额度耗尽不能重新变绿',d,lambda:M.apply(d,dict(request(d,c),fault_id='fault.2'),c),'resync_prestate_or_source')
        for state in ('quarantined','closed'):
            d,q,c,ts=f();s=R.one(d,'ingress_source','source_id','source');d.execute('UPDATE ingress_source SET revision=?,state=? WHERE source_id=?',(P.inc(s['revision']),state,'source'))
            denied(state+'不得由恢复入口解封',d,lambda:M.apply(d,request(d,c),c))
        # 单个baseline预留完整补齐+ready槽，不能先占基线后发现ready无空间。
        d,q,c,ts=f(limits=(3,1));M.apply(d,request(d,c),c);M.apply(d,request(d,c,'delta'),c)
        cc=dict(c,event_ref=ref('event.12'));denied('补齐配额超额整笔回滚',d,lambda:M.apply(d,request(d,cc,'delta',ident='delta.2'),cc),'resync_continuity_or_capacity')
        M.apply(d,request(d,c,'ready'),c);check('耗尽补齐配额仍留ready槽',d.execute('SELECT count(*) FROM rs_transition').fetchone()[0],3)
        B.protect(d,C.fault('3','empty.a'),c);other=dict(request(d,c,source='empty.a',baseline='baseline.other'),fault_id='fault.3')
        denied('普通恢复分区不能超卖新基线',d,lambda:M.apply(d,other,c),'resync_baseline_frontier_or_capacity')
        # 基线不能回退水位；直接UPDATE不能绕过事务原件。
        d,q,c,ts=f(fault=False);W.execute(d,c,1);B.protect(d,C.fault('1'),c)
        denied('基线水位不得回退',d,lambda:M.apply(d,dict(request(d,c),watermark='0'),c),'resync_baseline_frontier_or_capacity')
        s=R.one(d,'ingress_source','source_id','source')
        denied('直接source变绿拒绝',d,lambda:C.execute(d,[("UPDATE ingress_source SET state='synchronized',revision=? WHERE source_id='source'",(P.inc(s['revision']),))]),'resync_transition_required')
        before=C.snapshot(d);F.receive_event(d,W.event(1),c);check('失步后已提交事件仍查原',C.snapshot(d)==before)
        M.apply(d,request(d,c),c);M.apply(d,request(d,c,'delta'),c)
        wrong=dict(request(d,c,'ready'),last_delta_id='missing');denied('检查点必须引用最后连续delta',d,lambda:M.apply(d,wrong,c),'resync_continuity_or_capacity')
        for table in ('rs_limit','rs_transition','rs_commit'):
            denied('历史不可删除'+table,d,lambda table=table:C.execute(d,[('DELETE FROM '+table,())]),'immutable')
        for i,db in enumerate(dbs):check('外键完整'+str(i),list(db.execute('PRAGMA foreign_key_check')),[])
        return checks
    finally:
        for d in dbs:d.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    target=HERE/'source-resync-report.json'
    def bindings():return {x.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+x.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else x.read_bytes()).hexdigest() for x in INPUTS}
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings();print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),seamer_tables=109,runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')}))
