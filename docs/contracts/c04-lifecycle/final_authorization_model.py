"""同writer内检查持久授权绑定及撤销下界；不证明签发者、UTC或scope取证真实性。"""
import json
from jsonschema import Draft202012Validator,FormatChecker
import build_final_authorization as G
import final_encoding_source_model as E
F=E.F;need=F.need;raw=E.raw;SCHEMA=G.build()

def validate(name,value):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name},format_checker=FormatChecker()).validate(value)
def sealed(v,key):return F.seal(v,key)
def decode(name,body,digest,key):
    need(isinstance(body,bytes) and 0<len(body)<=16777216,'authorization_body_capacity')
    def pairs(items):
        out={}
        for k,v in items:need(k not in out,'authorization_duplicate_key');out[k]=v
        return out
    v=json.loads(body,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('authorization_nonfinite')))
    validate(name,v);need(raw(v)==body and sealed(v,key)==v and v[key]==digest,'authorization_body_digest');return v

def writer(db):
    need(db.in_transaction,'authorization_transaction_required')
    # 先取同库writer锁；已读过的陈旧DEFERRED快照升级失败须整事务回滚，不能继续。
    db.execute('UPDATE authorization_use SET use_id=use_id WHERE 0')

def store_use(db,value):
    writer(db);validate('AuthorizationUse',value);need(sealed(value,'use_digest')==value,'authorization_use_digest')
    need(value['binding']['scope']==E.A.scope(db),'authorization_scope')
    db.execute('INSERT INTO authorization_use VALUES(?,?,?)',(value['use_id'],value['use_digest'],raw(value)))

def install_floor(db,value):
    writer(db);validate('FloorEvent',value);need(sealed(value,'event_digest')==value,'authorization_floor_digest')
    need(value['scope']==E.A.scope(db),'authorization_floor_scope');s=value['selector']
    old=db.execute('SELECT body FROM authorization_floor_event WHERE event_id=?',(value['event_id'],)).fetchone()
    if old:need(old[0]==raw(value),'authorization_floor_identity');return
    # 乱序事件可保留；判定取所有已见事件，不以最后到达覆盖较高下界或永久撤销。
    db.execute('INSERT INTO authorization_floor_event VALUES(?,?,?,?,?,?,?,?)',
        (value['event_id'],s['kind'],s['issuer_id'],s['issuer_epoch'],s['target_id'],s['revision_floor'].zfill(20),value['event_digest'],raw(value)))

def dependencies(a):
    out=[('principal',a['principal_id'],a['subject_revision']),('credential',a['credential_id'],None),('trust',None,None)]
    if a['session_id'] is not None:out.append(('session',a['session_id'],a['session_revision']))
    if a['grant_id'] is not None:out.append(('grant',a['grant_id'],a['grant_revision']))
    if a['extension_instance_id'] is not None:out.append(('extension',a['extension_instance_id'],a['extension_approval_revision']))
    return out

def read(db,use_ref,seal):
    writer(db);validate('Ref',use_ref);E.A.candidate(db,seal)
    row=db.execute('SELECT digest,body FROM authorization_use WHERE use_id=?',(use_ref['id'],)).fetchone();need(row is not None,'authorization_use_missing')
    u=decode('AuthorizationUse',row[1],row[0],'use_digest')
    need(use_ref==E.ref(u['use_id'],u['revision'],u['use_digest']),'authorization_use_ref')
    need(u['binding']==seal['binding'] and u['binding']['scope']==E.A.scope(db) and u['identity']==seal['identity'],'authorization_use_binding')
    # 暂不开放取消及面板委托：它们的发起人/代行者和授权链另有具名契约，不借此入口降级。
    need(u['identity']['kind']=='ordinary','authorization_ordinary_only')
    a=u['authorization_binding'];s=u['snapshot'];who=u['identity']['requester']
    need(a['extension_instance_id'] is None,'authorization_delegation_not_integrated')
    need(who==dict(kind=a['principal_kind'],**{k:a[k] for k in ('issuer_id','issuer_epoch','principal_id')}),'authorization_requester')
    need(a['origin']==u['identity']['origin'] and (a['principal_kind'],a['origin']) in (('human','manual'),('service','automation')),'authorization_purpose')
    need(a['audience']==seal['binding']['scope']['authority_service_id'],'authorization_audience')
    for k in set(a)&set(s):need(a[k]==s[k],'authorization_snapshot_'+k)
    need(s['state']=='active' and 'device.command' in s['permissions'],'authorization_permission')
    sent=int(u['challenge_sent_tick_ns']);received=int(u['received_tick_ns']);selected=int(seal['selected_tick_ns']);now=int(seal['sealed_tick_ns'])
    lower=int(u['not_before_tick_ns']);upper=min(int(u['authorization_before_tick_ns']),sent+min(s['fresh_for_ms'],u['local_freshness_limit_ms'])*1000000)
    need(sent<=received<=selected<=now and lower<=received and lower<=now<upper and received<upper,'authorization_window')
    floors=[]
    for kind,target,revision in dependencies(a):
        query='SELECT event_id,kind,issuer_id,issuer_epoch,target_id,revision_floor,digest,body FROM authorization_floor_event WHERE kind=? AND issuer_id=? AND issuer_epoch=?'
        args=[kind,a['issuer_id'],a['issuer_epoch']]
        if target is not None:query+=' AND target_id=?';args.append(target)
        rows=db.execute(query+' ORDER BY event_id LIMIT 4097',args).fetchall();need(len(rows)<=4096,'authorization_floor_capacity')
        for r in rows:
            event=decode('FloorEvent',r[7],r[6],'event_digest');x=event['selector']
            need(event['scope']==E.A.scope(db) and tuple(r[:6])==(event['event_id'],x['kind'],x['issuer_id'],x['issuer_epoch'],x['target_id'],x['revision_floor'].zfill(20)),'authorization_floor_columns')
            need(kind not in ('credential','trust'),'authorization_permanent_denial')
            need(int(revision)>=int(x['revision_floor']),'authorization_revision_floor')
            floors.append(E.ref(event['event_id'],1,event['event_digest']))
    source=dict(format_version='authorization-cut/1',scope=E.A.scope(db),use_ref=use_ref,transaction_id=seal['transaction_id'],
        selected_tick_ns=seal['selected_tick_ns'],sealed_tick_ns=seal['sealed_tick_ns'],floor_refs=sorted(floors,key=lambda x:x['id']))
    validate('AuthorizationCut',source)
    source_ref=E.ref('authorization_cut_'+F.digest(source)[7:],1,F.digest(source))
    return E.original('authorization',seal['transaction_id'],seal['binding'],seal['identity'],source_ref,not_before_tick_ns=str(lower),before_tick_ns=str(upper))

def planned(db,seal,originals,cut,pid,provider,use_ref):
    current=read(db,use_ref,seal)
    need(originals['authorization']==current and seal['inputs']['authorization']==current['ref'],'authorization_current_projection')
    return E.planned(db,seal,originals,cut,pid,provider)
