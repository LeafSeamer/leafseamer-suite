"""布防预算的有限原子步、边界反例和现有SQL差距检查。"""
import argparse,copy,hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
import jsonschema
import build_arm_budget as G
import arm_budget_model as M
import check_contracts as C
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE.parent/'c05-protection'))
import check_qualification as Q
INPUTS=list(dict.fromkeys(C.INPUTS+Q.INPUTS+[HERE/n for n in ('ARM_BUDGET.md','build_arm_budget.py','arm_budget_model.py','check_arm_budget.py','arm-budget.schema.json')]))
SHAPE=dict(dependencies='4',runs='1',executions='8',preparations='2',submissions='16',controller_targets='3')
H='sha256:'+'a'*64
def profile():
    return dict(contract_version=G.VERSION,profile_id='sim-arm-budget-1',revision='1',purpose='simulation',
        capacity=M.vector(logical_rows=100000,logical_bytes=2**32,queue_slots=1000,work_units=200000),
        max_shape=dict(dependencies='128',runs='16',executions='1024',preparations='128',submissions='4096',controller_targets='256'),
        max_row_bytes='16384',episodes='2',max_queue_wait_ns='500000000',validation_ref=None)
def fixture():
    w,c,p,r=C.fixture();c.update(inventory_verified=True,controller_capacity_verified=True,inventory_digest=H)
    w['protection_budget']=M.ledger(profile());return w,c,p,r
def use(w,event='fault.1'):
    t=w['protection_budget']['tickets'][w['reservation']['budget_reservation_id']]
    return dict(reservation_id=t['reservation_id'],event_id=event,event_digest=H,kind='source',binding_digest=t['binding_digest'],
        observed_shape=copy.deepcopy(SHAPE),observed_max_row_bytes='16384')
def proof(w):
    u=use(w)
    return dict(reservation_id=u['reservation_id'],binding_digest=u['binding_digest'],proof_ref=dict(scope=w['run']['scope'],id='archive.1',revision='1',digest=H),
        generation_closed=True,all_targets_accounted=True,no_unresolved_references=True,archive_durable=True)
def run():
    checks=[]
    def check(name,v,expected=True):assert v==expected,(name,v,expected);checks.append(dict(name=name,observed=v,expected=expected))
    def denied(name,call,reason):
        try:call()
        except (ValueError,jsonschema.ValidationError) as e:check(name,reason in str(e));return
        raise AssertionError(name)
    def accepted():
        w,c,p,r=fixture();w,status=M.reserve(w,r,p,c,SHAPE,H);assert status=='accepted';return w,c,p,r
    def armed():
        w,c,p,r=accepted();w,s=M.ready(w,C.receipts(w),c);assert s=='ready';return w,c,p,r
    check('Schema生成字节一致',(HERE/'arm-budget.schema.json').read_bytes()==G.raw());jsonschema.Draft202012Validator.check_schema(G.schema())
    for value in ('01','-1','1e2','1\n','１',1,'100000000000000000000'):
        bad=copy.deepcopy(SHAPE);bad['runs']=value
        denied('U20拒绝非规范值'+repr(value),lambda bad=bad:M.validate('Shape',bad),'')
    w,c,p,r=accepted();b=w['protection_budget'];t=b['tickets'][w['reservation']['budget_reservation_id']]
    for name,val in [('Profile',b['profile']),('Shape',SHAPE),('Reservation',t),('ProtectionUse',use(w)),('ReleaseProof',proof(w))]:
        M.validate(name,val);check(name+'正例',True)
        bad=copy.deepcopy(val);bad['unexpected']=1;denied(name+'拒绝额外字段',lambda name=name,bad=bad:M.validate(name,bad),'Additional properties')
    check('受理保持disarmed',(w['run']['lifecycle'],w['run']['dispatch_eligible'],w['run']['active_execution_id']),('disarmed',False,None))
    check('可靠受理占槽',w['slot']['active_run_id'],'run');check('准备有活动操作',bool(w['run']['active_operation_id']))
    check('准备先持有完整预算',b['held'],M.vector(**{k:int(v)*2 for k,v in M.cost(profile(),SHAPE).items()}))
    n,s=M.ready(w,C.receipts(w),c);check('全部回执后armed',s,'ready');check('布防可派发',M.effective_dispatch(n));check('ready不退保护额度',n['protection_budget']==b)
    same,s=M.reserve(n,r,p,c,SHAPE,H);check('原请求重查',s,'existing');check('重查零写',same==n)
    for dim in G.DIMENSIONS:
        a,ctx,pv,rq=fixture();required=int(M.cost(profile(),SHAPE)[dim])*2
        low=profile();low['capacity'][dim]=str(required-1);a['protection_budget']=M.ledger(low)
        unchanged,s=M.reserve(a,rq,pv,ctx,SHAPE,H);check(dim+'不足原子拒绝',s,'capacity_rejected');check(dim+'不占槽不消费预检',unchanged==a)
        low['capacity'][dim]=str(required);a['protection_budget']=M.ledger(low)
        check(dim+'等号可受理',M.reserve(a,rq,pv,ctx,SHAPE,H)[1],'accepted')
    a,ctx,pv,rq=fixture();ctx['budget_abort']=True
    check('预算写入后故障回滚',M.reserve(a,rq,pv,ctx,SHAPE,H),(a,'rolled_back'))
    # 上一断言避免把含set/tuple的完整世界写进JSON报告。
    checks[-1]=dict(name='预算写入后故障回滚',observed=True,expected=True)
    for field in ('inventory_verified','controller_capacity_verified'):
        a,ctx,pv,rq=fixture();ctx[field]=False;denied(field+'阻止受理',lambda:M.reserve(a,rq,pv,ctx,SHAPE,H),'unqualified_inventory')
    a,ctx,pv,rq=fixture();denied('库存摘要绑定',lambda:M.reserve(a,rq,pv,ctx,SHAPE,'sha256:'+'b'*64),'inventory_binding')
    small=copy.deepcopy(SHAPE);small['controller_targets']='0';denied('不得少报Controller集合',lambda:M.reserve(a,rq,pv,ctx,small,H),'understated_targets')
    for field in ('inventory_verified','controller_capacity_verified','authorized'):
        a,ctx,pv,rq=accepted();ctx[field]=False;n,s=M.ready(a,C.receipts(a),ctx);check(field+'就绪前失效关闭',not M.effective_dispatch(n) and n.get('volatile_closed',False))
    a,ctx,pv,rq=accepted();ctx['inventory_digest']='sha256:'+'b'*64;check('准备后库存变化',M.ready(a,C.receipts(a),ctx)[1],'inventory_changed')
    a,ctx,pv,rq=armed();old=copy.deepcopy(a);n,s=M.protect(a,use(a));check('首保护消费一份',s,'protected_committed')
    check('持有转消耗守恒',M.arithmetic(n['protection_budget']['held'],n['protection_budget']['spent']),old['protection_budget']['held'])
    check('保护后派发关闭',not M.effective_dispatch(n));check('只扣一次',next(iter(n['protection_budget']['tickets'].values()))['episodes_left'],'1')
    repeat,s=M.protect(n,use(a));check('保护精确重复',s,'existing');check('重复不扣新额度',repeat==n)
    conflict=use(a);conflict['event_digest']='sha256:'+'b'*64;denied('同事件不同内容拒绝',lambda:M.protect(n,conflict),'event_conflict')
    n,s=M.protect(n,use(a,'fault.2'));check('第二独立故障仍有预算',s,'protected_committed')
    exhausted,s=M.protect(n,use(a,'fault.3'));check('超出有限保护次数不伪造持久成功',s,'protection_budget_exhausted');check('耗尽仍关闭',not M.effective_dispatch(exhausted))
    check('耗尽不额外扣费',exhausted['protection_budget']==n['protection_budget'])
    for opt in (dict(storage_healthy=False),dict(abort=True)):
        failed,s=M.protect(a,use(a),**opt);check('存储失败状态'+str(opt),s,'protected_uncommitted');check('存储失败账本回滚'+str(opt),failed['protection_budget']==a['protection_budget']);check('回滚不重开内存门'+str(opt),not M.effective_dispatch(failed))
    for field in G.SHAPE:
        oversized=use(a);oversized['observed_shape'][field]=str(int(SHAPE[field])+1)
        n,s=M.protect(a,oversized);check(field+'增长必须重预留',s,'exposure_growth');check(field+'增长不截断而关闭',not M.effective_dispatch(n))
    oversized=use(a);oversized['observed_max_row_bytes']='16385';check('正文越界关闭',M.protect(a,oversized)[1],'row_bound')
    check('保护排队截止前可提交',M.protect(a,use(a),elapsed_wait_ns='499999999')[1],'protected_committed')
    for tick in ('500000000','500000001'):
        n,s=M.protect(a,use(a),elapsed_wait_ns=tick);check('排队截止'+tick,s,'protection_queue_expired');check('超时不退旧预算也不重开'+tick,n['protection_budget']==a['protection_budget'] and not M.effective_dispatch(n))
    denied('保护回执不能退款',lambda:M.release(a,proof(a),trusted_proof=True),'still_dispatchable')
    n,s=M.protect(a,use(a));denied('未授信归档证明拒绝',lambda:M.release(n,proof(n)),'untrusted_release')
    released,s=M.release(n,proof(n),trusted_proof=True);check('明确核对只退未使用',s,'released_unused');check('已花费及历史事件保留',released['protection_budget']['spent']==n['protection_budget']['spent'] and released['protection_budget']['events']==n['protection_budget']['events'])
    check('退款重复只查原',M.release(released,proof(n),trusted_proof=True)[1],'existing')
    denied('已退款不能再使用',lambda:M.protect(released,use(n,'fault.2')),'released_reservation')
    newer=copy.deepcopy(a);newer['run']['arm_generation']='4';before=copy.deepcopy(newer['run']);n,s=M.protect(newer,use(a));check('旧代次保护不关闭新run',n['run']==before and not n.get('volatile_closed',False))
    reduced=profile();reduced.update(revision='2',capacity=M.vector(logical_rows=1,logical_bytes=1,queue_slots=1,work_units=1),max_row_bytes='1')
    n=copy.deepcopy(a);n['protection_budget']=M.change_profile(n['protection_budget'],reduced)
    check('调低profile保留原持有和消耗',n['protection_budget']['held']==a['protection_budget']['held'] and n['protection_budget']['spent']==a['protection_budget']['spent'])
    check('新profile不夺走旧保护包络',M.protect(n,use(a))[1],'protected_committed')
    check('满额仍能查询原布防',M.reserve(n,rq,pv,ctx,SHAPE,H)[1],'existing')
    bad=profile();bad['max_row_bytes']='1';denied('同profile修订不能换正文',lambda:M.change_profile(a['protection_budget'],bad),'profile_identity_conflict')
    pending,pc,pp,pr=accepted();pending['protection_budget']=M.change_profile(pending['protection_budget'],reduced)
    check('准备过程中改profile不能旧ready',M.ready(pending,C.receipts(pending),pc)[1],'profile_changed')
    other,oc,op,oreq=fixture();other['run']['run_id']='other.run';op['run_id']='other.run';op['baseline']=C.baseline(other);C.seal(op,'preflight_digest');oreq['preflight_digest']=op['preflight_digest']
    other['protection_budget']=copy.deepcopy(a['protection_budget']);oldheld=other['protection_budget']['held']
    second,s=M.reserve(other,oreq,op,oc,SHAPE,H);check('共享池第二run可独立预留',s,'accepted')
    check('完整run绑定避免操作别名碰撞',len(second['protection_budget']['tickets']),2)
    check('共享池两run合计扣减',second['protection_budget']['held'],M.arithmetic(oldheld,oldheld))
    # 精确大整数与封顶：独立检查可计算的预算，不把数值转成浮点。
    huge=profile();huge['max_shape']['submissions']=str(2**53+1);shape=copy.deepcopy(SHAPE);shape['submissions']=str(2**53+1)
    denied('预算乘积超U20拒绝',lambda:M.cost(huge,shape),'budget_arithmetic')
    v=M.vector(logical_rows=2**53+1);check('跨53位整数无损',M.arithmetic(v,M.vector(logical_rows=1))['logical_rows'],str(2**53+2))
    invalid=profile();invalid['purpose']='release_candidate';denied('发布profile缺验证Ref拒绝',lambda:M.cost(invalid,SHAPE),'unvalidated_profile')
    zero=copy.deepcopy(SHAPE);zero.update(preparations='0',controller_targets='0');check('零设备仍预留本地保护',int(M.cost(profile(),zero)['logical_rows'])>0)
    # 对当前SQL的真实反例，不把有限模型误记成新SQL布局。
    db=sqlite3.connect(':memory:');db.executescript(Q.G.build().decode())
    db.execute("INSERT INTO storage_scope VALUES(1,'seamer','db','automation-storage/0.1.0-draft.2')")
    db.execute("INSERT INTO published_version(definition_id,version,artifact_digest,artifact_body) VALUES('d','1','artifact',x'01')")
    db.execute("INSERT INTO run(run_id,definition_id,version,revision,arm_generation,lifecycle,dispatch_eligible) VALUES('r','d','1','1','1','armed',1)")
    check('现72表可直接建armed而无准备',db.execute('SELECT dispatch_eligible FROM run').fetchone()[0],1)
    fk=[r for r in db.execute('PRAGMA foreign_key_list(run)') if r[3]=='active_operation_id']
    check('现活动操作仅引用recovery',set(r[2] for r in fk),{'recovery_operation'});checks[-1]=dict(name='现活动操作仅引用recovery',observed=['recovery_operation'],expected=['recovery_operation']);db.close()
    for kind in ('source','preparation'):
        db,rq,ctx=Q.F.fixture(layout=Q.G.build());Q.R.reserve(db,rq,ctx);Q.prepare(db,rq,ctx,start=True);Q.submission_history(db,rq)
        before=db.total_changes
        if kind=='source':Q.P.protect(db,Q.C.fault())
        else:Q.Q.withdraw(db,'registration.a',Q.withdrawal(db),Q.PROVIDER)
        check(kind+'实际72表写集含触发器未超行包络',db.total_changes-before<=int(M.cost(profile(),SHAPE)['logical_rows']))
        check(kind+'实际写集外键完整',list(db.execute('PRAGMA foreign_key_check')),[]);db.close()
    return checks
def bindings(staged=False):
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(subprocess.check_output(['git','show',':'+p.relative_to(ROOT).as_posix()],cwd=ROOT) if staged else p.read_bytes()).hexdigest() for p in INPUTS}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');p.add_argument('--staged',action='store_true');a=p.parse_args()
    target=HERE/'arm-budget-report.json'
    if a.staged and not a.check_report:p.error('--staged需--check-report')
    if a.check_report:
        data=json.loads(subprocess.check_output(['git','show',':'+target.relative_to(ROOT).as_posix()],cwd=ROOT) if a.staged else target.read_bytes());assert data['inputs']==bindings(a.staged)
        print(json.dumps(dict(all_passed=True,matched_bindings=len(INPUTS))))
    else:
        checks=run();data=dict(all_passed=True,approved=False,cases_passed=len(checks),scope='有限生命周期预算模型及现有72表反例，不是完整布防SQL实现',
            runtime_tests_executed=0,concurrency_tests_executed=0,disk_crash_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings())
        if a.report:target.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({k:v for k,v in data.items() if k not in ('checks','inputs')},ensure_ascii=False))
