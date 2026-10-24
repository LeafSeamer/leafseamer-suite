"""认证区间的局部整数参考模型；不采集系统时间，不使用业务NTP，不验证身份签发。"""
import re
from datetime import datetime,timezone
import final_authorization_model as M
import authorization_clock_ingress_model as I
N=1000000000
MAX=2**64-1


def ceildiv(a,b):return -(-a//b)

def utc(value):
    # 内部候选只接受既有规范UTC毫秒串，不使用浮点timestamp或隐式本地时区。
    M.need(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z',value) is not None,'authorization_utc_format')
    delta=datetime.fromisoformat(value[:-1]+'+00:00')-datetime(1970,1,1,tzinfo=timezone.utc)
    result=(delta.days*86400+delta.seconds)*N+delta.microseconds*1000
    M.need(0<=result<=MAX,'authorization_utc_range');return result

def cref(value):return M.reference(value,'record_id','record_digest')

def checked_clock(row):
    M.need(row is not None,'authorization_clock_missing')
    value=M.decode('AuthenticationClockRecord',row[4],row[3],'record_digest')
    M.need((value['record_id'],M.F.digest(value['sample']['binding']),value['sequence'].zfill(20))==tuple(row[:3]),'authorization_clock_columns')
    return value

def clock(db,ref_value):
    value=checked_clock(db.execute('SELECT * FROM authorization_clock_record WHERE record_id=?',(ref_value['id'],)).fetchone())
    M.need(cref(value)==ref_value,'authorization_clock_ref');return value

def current(db,binding):
    row=db.execute('SELECT * FROM authorization_clock_record WHERE binding_digest=? ORDER BY sequence DESC LIMIT 1',(M.F.digest(binding),)).fetchone()
    return checked_clock(row) if row else None

def interval(record,tick):
    s=record['sample'];dt=tick-int(s['anchor_tick_ns']);rate=s['drift_ppb']
    M.need(not record['protected'] and dt>=0 and tick<int(s['valid_before_tick_ns']),'authorization_clock_unusable')
    lower=int(record['effective_lower_ns'])+dt*(N-rate)//N
    upper=int(record['effective_upper_ns'])+ceildiv(dt*(N+rate),N)
    M.need(0<=lower<=upper<=MAX,'authorization_clock_range');return lower,upper

def store_clock(db,sample):
    """由采集端登记，保护由本地历史推导；相同运行绑定没有自动解锁入口。"""
    M.writer(db);M.validate('AuthenticationClockSample',sample)
    M.need(sample['binding']['scope']==M.E.A.scope(db),'authorization_clock_scope')
    M.need(I.fault(db,sample['binding']) is None,'authorization_clock_fault_latched')
    old=db.execute('SELECT * FROM authorization_clock_record WHERE record_id=?',(sample['sample_id'],)).fetchone()
    if old:
        value=checked_clock(old);M.need(value['sample']==sample,'authorization_clock_identity');return cref(value)
    previous=current(db,sample['binding']);tick=int(sample['anchor_tick_ns'])
    lower=int(sample['utc_lower_ns']);upper=int(sample['utc_upper_ns']);before=int(sample['valid_before_tick_ns'])
    M.need(max(tick,lower,upper,before)<=MAX,'authorization_clock_range')
    protected=sample['quality']!='trusted' or lower>upper or before<=tick
    if previous:
        ps=previous['sample']
        protected=protected or previous['protected'] or tick<=int(ps['anchor_tick_ns']) or tick>=int(ps['valid_before_tick_ns'])
        protected=protected or sample['policy_ref']!=ps['policy_ref'] or sample['drift_ppb']!=ps['drift_ppb']
        if not protected:
            pl,pu=interval(previous,tick)
            protected=upper<pl or lower>pu
            # 上界不因后续较低采样收窄，避免前跳造成的过期被回拨复活。
            lower=max(lower,pl);upper=max(upper,pu)
    value=M.sealed(dict(format_version='authentication-clock-record/1',record_id=sample['sample_id'],revision='1',
        sequence=str(int(previous['sequence'])+1 if previous else 1),sample=sample,parent_ref=cref(previous) if previous else None,
        effective_lower_ns=str(lower),effective_upper_ns=str(upper),protected=protected),'record_digest')
    M.validate('AuthenticationClockRecord',value)
    db.execute('INSERT INTO authorization_clock_record VALUES(?,?,?,?,?)',(value['record_id'],M.F.digest(sample['binding']),value['sequence'].zfill(20),value['record_digest'],M.raw(value)))
    return cref(value)

def store_validity(db,value):
    M.writer(db);M.validate('AuthorizationValidity',value)
    M.need(M.sealed(value,'validity_digest')==value and value['binding']['scope']==M.E.A.scope(db),'authorization_validity_body')
    c=clock(db,value['clock_ref']);M.need(c['sample']['binding']==value['binding'],'authorization_validity_clock_binding')
    old=db.execute('SELECT body FROM authorization_validity WHERE validity_id=?',(value['validity_id'],)).fetchone()
    if old:M.need(old[0]==M.raw(value),'authorization_validity_identity');return
    db.execute('INSERT INTO authorization_validity VALUES(?,?,?)',(value['validity_id'],value['validity_digest'],M.raw(value)))

def window(record,not_before,expires):
    s=record['sample'];anchor=int(s['anchor_tick_ns']);lo,hi=interval(record,anchor);rate=s['drift_ppb']
    M.need(not_before<expires,'authorization_validity_empty')
    lower=anchor+max(0,ceildiv((not_before-lo)*N,N-rate))
    # upperUTC=hi+ceil(dt*rate/N)必须严格小于exp；先减一后floor才能保持严格整数边界。
    upper=anchor+((expires-1-hi)*N//(N+rate))+1
    return lower,min(upper,int(s['valid_before_tick_ns']))

def resolve(db,u,seal):
    M.need(I.fault(db,u['binding']) is None,'authorization_clock_fault_latched')
    ref_value=u['validity_evidence_ref']
    row=db.execute('SELECT digest,body FROM authorization_validity WHERE validity_id=?',(ref_value['id'],)).fetchone()
    M.need(row is not None,'authorization_validity_missing');v=M.decode('AuthorizationValidity',row[1],row[0],'validity_digest')
    M.need(M.reference(v,'validity_id','validity_digest')==ref_value,'authorization_validity_ref')
    M.need(all(v[k]==u[k] for k in ('binding','identity','authorization_binding')) and v['authority_response_ref']==u['authority_evidence_ref'],'authorization_validity_binding')
    a=u['authorization_binding'];expected=[(k,a[k+'_id']) for k in ('credential','session','grant') if a[k+'_id'] is not None]
    M.need([(x['kind'],x['target_id']) for x in v['components']]==expected,'authorization_validity_components')
    ranges=[u['snapshot']['validity']]+[x['validity'] for x in v['components']]
    lower_utc=max(utc(x['not_before']) for x in ranges);upper_utc=min(utc(x['expires_at']) for x in ranges)
    origin=clock(db,v['clock_ref']);latest=current(db,u['binding']);M.need(latest is not None,'authorization_clock_missing')
    M.need(origin['sample']['binding']==u['binding'] and int(origin['sequence'])<=int(latest['sequence']),'authorization_validity_clock_binding')
    received=int(u['received_tick_ns']);now=int(seal['sealed_tick_ns'])
    for record,tick in ((origin,received),(origin,now),(latest,now)):
        lo,hi=interval(record,tick);M.need(lower_utc<=lo and hi<upper_utc,'authorization_utc_window')
    M.need(int(latest['sample']['anchor_tick_ns'])<=int(seal['selected_tick_ns']),'authorization_clock_selected_order')
    lower,upper=window(origin,lower_utc,upper_utc)
    _,current_upper=window(latest,lower_utc,upper_utc);upper=min(upper,current_upper)
    lower=max(lower,int(u['not_before_tick_ns']))
    upper=min(upper,int(u['authorization_before_tick_ns']),int(u['challenge_sent_tick_ns'])+min(u['snapshot']['fresh_for_ms'],u['local_freshness_limit_ms'])*1000000)
    M.need(lower<=received<=now<upper,'authorization_validity_window')
    result=dict(format_version='authorization-time-cut/1',validity_ref=ref_value,origin_clock_ref=cref(origin),current_clock_ref=cref(latest),not_before_tick_ns=str(lower),before_tick_ns=str(upper))
    M.validate('AuthorizationTimeCut',result);return result
