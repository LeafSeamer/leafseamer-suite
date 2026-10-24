"""最终授权检查器调用的时窗故障用例；只使用合成认证来源。"""
import copy,json
import final_authorization_model as M
V=M.V;clone=copy.deepcopy


def run(T,check,reject,db,fork,u,v,o,cut,pid,provider):
    def read(c,use=u,seal=v):return T.T.T.preview(c,lambda:M.read(c,T.use_ref(use),seal))
    evidence=json.loads(db.execute('SELECT body FROM authorization_validity').fetchone()[0])
    original=V.clock(db,evidence['clock_ref']);sample=original['sample'];base=int(sample['utc_lower_ns'])
    def edit_evidence(c,mutate):
        value=clone(evidence);value['validity_id']='changed.validity';mutate(value);value=M.sealed(value,'validity_digest')
        T.tx(c,lambda:V.store_validity(c,value));use=clone(u);use['use_id']='changed.use'
        use['validity_evidence_ref']=M.reference(value,'validity_id','validity_digest');use=M.sealed(use,'use_digest')
        T.tx(c,lambda:M.store_use(c,use));return use
    check('UTC纳秒解析不经过浮点',V.utc('2026-01-01T00:00:00.001Z')-V.utc('2026-01-01T00:00:00.000Z')==1000000)
    for value in ('2026-01-01T00:00:00Z','2026-01-01T00:00:00.000+00:00','2026-01-01T00:00:00.000Z\n','1969-12-31T23:59:59.999Z'):
        reject('非规范或负UTC拒绝:'+repr(value),lambda value=value:V.utc(value))
    # 独立枚举离散tick，核对上下界取整；涵盖相邻>2^53整数和正漂移。
    for rate in (0,1,999999,1000000):
        rec=clone(original);rec['sample'].update(anchor_tick_ns='0',drift_ppb=rate,valid_before_tick_ns='100')
        rec.update(effective_lower_ns=str(2**53+1),effective_upper_ns=str(2**53+3))
        for start in range(0,8):
            for end in range(start+1,12):
                lower,upper=V.window(rec,2**53+1+start,2**53+3+end)
                for tick in range(20):
                    lo,hi=V.interval(rec,tick)
                    assert (lower<=tick<upper)==(2**53+1+start<=lo and hi<2**53+3+end),(rate,start,end,tick)
        check('整数窗口与独立逐tick区间一致:'+str(rate))
    for name,mutate,reason in [
        ('缺grant期限',lambda x:x['components'].pop(),'authorization_validity_components'),
        ('重复credential',lambda x:x['components'].__setitem__(1,clone(x['components'][0])),'authorization_validity_components'),
        ('期限属于其他grant',lambda x:x['components'][1].update(target_id='other.grant'),'authorization_validity_components'),
        ('期限不属于原响应',lambda x:x['authority_response_ref'].update(id='other.response'),'authorization_validity_binding'),
        ('令牌有效期已截止',lambda x:x['components'][0]['validity'].update(not_before='2025-12-31T23:59:59.000Z',expires_at='2026-01-01T00:00:00.000Z'),'authorization_utc_window'),
        ('grant尚未生效',lambda x:x['components'][1]['validity'].update(not_before='2026-01-01T00:00:00.001Z'),'authorization_utc_window')]:
        c=fork(db);changed=edit_evidence(c,mutate);reject(name,lambda:read(c,changed),reason)
    for field,value,reason in [('id','missing','authorization_validity_missing'),('digest',M.F.digest('forged'),'authorization_validity_ref')]:
        c=fork(db);use=clone(u);use['use_id']='bad.ref';use['validity_evidence_ref'][field]=value;use=M.sealed(use,'use_digest')
        T.tx(c,lambda:M.store_use(c,use));reject('有效期Ref逐字段核原件:'+field,lambda:read(c,use),reason)
    c=fork(db);changed=clone(sample);changed['utc_upper_ns']=str(base+1)
    reject('同采样ID不能重写时间',lambda:T.tx(c,lambda:V.store_clock(c,changed)),'authorization_clock_identity')
    changed=clone(sample);changed['business_ntp_offset_ns']='1000000'
    reject('认证采样不接受业务NTP偏移字段',lambda:T.tx(c,lambda:V.store_clock(c,changed)))
    changed=clone(sample);changed['profile']='reference-bound/1'
    reject('业务参考时钟profile不能替代认证profile',lambda:T.tx(c,lambda:V.store_clock(c,changed)))
    def next_sample(tick=51):
        s=clone(sample);s.update(sample_id='next.clock',anchor_tick_ns=str(tick),utc_lower_ns=str(base+tick),utc_upper_ns=str(base+tick));return s
    c=fork(db);new=next_sample();T.tx(c,lambda:V.store_clock(c,new))
    fresh=read(c);check('合法后续采样产生新的最终切点',fresh!=read(db))
    reject('新时钟切点禁止复用旧投影',lambda:T.T.T.preview(c,lambda:M.planned(c,v,o,cut,pid,provider,T.use_ref(u))),'authorization_current_projection')
    vv,oo=clone(v),clone(o);T.attach(vv,oo,fresh)
    check('重新绑定合法时钟切点可规划',len(T.T.T.preview(c,lambda:M.planned(c,vv,oo,cut,pid,provider,T.use_ref(u))))==19)
    c=fork(db);future=next_sample(52);T.tx(c,lambda:V.store_clock(c,future))
    reject('选取时刻不能早于当前采样',lambda:read(c),'authorization_clock_selected_order')
    for name,mutate in [
        ('系统时间前跳',lambda s:s.update(utc_lower_ns=str(base+52),utc_upper_ns=str(base+52))),
        ('系统时间回拨',lambda s:s.update(utc_lower_ns=str(base+50),utc_upper_ns=str(base+50))),
        ('采集失信',lambda s:s.update(quality='untrusted')),
        ('单调tick回退或重复',lambda s:s.update(anchor_tick_ns='0')),
        ('采样间隔越过有效期',lambda s:s.update(anchor_tick_ns='10000000')),
        ('策略切换未建新运行绑定',lambda s:s['policy_ref'].update(id='new.policy')),
        ('漂移预算改变',lambda s:s.update(drift_ppb=1)),
        ('采样区间倒置',lambda s:s.update(utc_lower_ns=str(base+52),utc_upper_ns=str(base+51)))]:
        c=fork(db);s=next_sample();mutate(s);T.tx(c,lambda:V.store_clock(c,s))
        check('异常锁存:'+name,V.current(c,u['binding'])['protected'])
        reject('异常阻断最终使用:'+name,lambda:read(c),'authorization_clock_unusable')
        s=next_sample(52);s['sample_id']='apparently.recovered';T.tx(c,lambda:V.store_clock(c,s))
        reject('正常采样不得自动解锁:'+name,lambda:read(c),'authorization_clock_unusable')
    # 后续误差缩小时上界保留先前保守预测，不能因上界降低复活已过期资格。
    c=fork(db);s=next_sample();s['binding']['worker_boot_id']='isolated.clock';s['sample_id']='wide.clock'
    s.update(anchor_tick_ns='0',utc_lower_ns=str(base),utc_upper_ns=str(base+20));T.tx(c,lambda:V.store_clock(c,s))
    s=clone(s);s.update(sample_id='narrow.clock',anchor_tick_ns='1',utc_lower_ns=str(base+1),utc_upper_ns=str(base+10))
    T.tx(c,lambda:V.store_clock(c,s));record=V.current(c,s['binding'])
    check('较低后续上界不放宽旧期限',not record['protected'] and record['effective_upper_ns']==str(base+21))
    check('纳秒上界等于exp时不再有效',V.window(record,base,base+21)[1]<=1)
    c=fork(db);use=clone(u);use.update(use_id='extended',authorization_before_tick_ns='20000000');use=M.sealed(use,'use_digest')
    T.tx(c,lambda:M.store_use(c,use));projected=read(c,use)
    check('自报更长截止不能越过新鲜度与时钟证据',projected['body']['before_tick_ns']=='1000001')
    for table in ('authorization_clock_record','authorization_validity'):
        reject('时窗原件禁止删除:'+table,lambda table=table:T.tx(c,lambda:c.execute('DELETE FROM '+table)))
        reject('时窗原件禁止更新:'+table,lambda table=table:T.tx(c,lambda:c.execute('UPDATE '+table+' SET digest=digest')))
    c=fork(db)
    def abort():V.store_clock(c,next_sample());raise ValueError('clock_transaction_fault')
    reject('时钟追加事务失败',lambda:T.tx(c,abort),'clock_transaction_fault')
    check('失败追加不留下半个切点',read(c)==read(db))
