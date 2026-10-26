"""从完整存储使用原件重建拒绝切点；没有开闸或设备许可输出。"""
from jsonschema import Draft202012Validator
import build_revocation_source as G
import final_authorization_model as A
HERE=G.HERE;need=A.need;raw=A.raw;SCHEMA=G.build();MAX_SEQUENCE=2**63-1
def validate(name,value):Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(value)
def install(db):
    need(not db.in_transaction,'revocation_install_transaction')
    # BEGIN写锁后再次核空，不能依据检查前的快照安装并漏掉并发事件。
    try:
        db.execute('BEGIN IMMEDIATE')
        need(db.execute('SELECT 1 FROM authorization_floor_event LIMIT 1').fetchone() is None,'revocation_install_nonempty')
        # executescript会改变事务边界，故按sqlite3.complete_statement执行完整语句。
        import sqlite3
        pending=''
        for line in (HERE/'revocation-source.sql').read_text('utf-8').splitlines(True):
            pending+=line
            if sqlite3.complete_statement(pending):db.execute(pending);pending=''
        need(not pending.strip(),'revocation_install_incomplete');db.commit()
    except BaseException:db.rollback();raise
def source(db,use_ref):
    need(db.in_transaction,'revocation_transaction');A.validate('Ref',use_ref)
    row=db.execute('SELECT digest,body FROM authorization_use WHERE use_id=?',(use_ref['id'],)).fetchone();need(row is not None,'revocation_use_missing')
    u=A.decode('AuthorizationUse',row[1],row[0],'use_digest')
    need(A.reference(u,'use_id','use_digest')==use_ref and u['binding']['scope']==A.E.A.scope(db),'revocation_use_binding')
    a=u['authorization_binding'];s=u['snapshot'];who=u['identity']['requester']
    need(who==dict(kind=a['principal_kind'],**{k:a[k] for k in ('issuer_id','issuer_epoch','principal_id')}) and a['origin']==u['identity']['origin'],'revocation_principal')
    need(a['audience']==u['binding']['scope']['authority_service_id'],'revocation_audience')
    for k in set(a)&set(s):need(a[k]==s[k],'revocation_snapshot_binding')
    for left,right in (('session_id','session_revision'),('grant_id','grant_revision'),('extension_instance_id','extension_approval_revision')):
        need((a[left] is None)==(a[right] is None),'revocation_dependency_pair')
    need((a['grant_id'] is None)==(a['arm_generation'] is None),'revocation_arm_pair')
    need((a['principal_kind'],a['origin']) in (('human','manual'),('service','automation')),'revocation_origin')
    need(a['session_id'] is not None if a['principal_kind']=='human' else a['session_id'] is None and a['grant_id'] is not None,'revocation_required_dependency')
    A.authority_response(db,u)
    return u
def derive(db,use_ref,through=None):
    u=source(db,use_ref);a=u['authorization_binding'];scope=u['binding']['scope']
    if through is not None:need(type(through) is int and 0<=through<=MAX_SEQUENCE,'revocation_sequence')
    deps=[];members=[]
    for kind,target,revision in A.dependencies(a):
        deps.append(dict(kind=kind,target_id=target,revision=revision))
        query='SELECT o.sequence,f.event_id,f.kind,f.issuer_id,f.issuer_epoch,f.target_id,f.revision_floor,f.digest,f.body FROM authorization_floor_event f LEFT JOIN authorization_revocation_order o USING(event_id) WHERE f.kind=? AND f.issuer_id=? AND f.issuer_epoch=?'
        args=[kind,a['issuer_id'],a['issuer_epoch']]
        if target is not None:query+=' AND f.target_id=?';args.append(target)
        if through is not None:query+=' AND (o.sequence<=? OR o.sequence IS NULL)';args.append(through)
        rows=db.execute(query+' ORDER BY o.sequence LIMIT 4097',args).fetchall();need(len(rows)<=4096,'revocation_capacity')
        for row in rows:
            need(row[0] is not None,'revocation_order_missing')
            e=A.decode('FloorEvent',row[8],row[7],'event_digest');s=e['selector']
            need(e['scope']==scope and tuple(row[1:7])==(e['event_id'],s['kind'],s['issuer_id'],s['issuer_epoch'],s['target_id'],s['revision_floor'].zfill(20)),'revocation_event_columns')
            denial='credential_revoked' if kind=='credential' else 'issuer_epoch_revoked' if kind=='trust' else 'below_floor' if int(revision)<int(s['revision_floor']) else None
            members.append(dict(sequence=str(row[0]),event_ref=A.E.ref(e['event_id'],1,e['event_digest']),denial=denial))
    deps.sort(key=lambda x:x['kind']);members.sort(key=lambda x:int(x['sequence']))
    value=dict(format_version='authorization-revocation-source/0.1.0-draft.1',revision='1',source_use_ref=use_ref,binding=u['binding'],authorization_binding=a,
        dependencies=deps,observed_through=members[-1]['sequence'] if members else '0',members=members,
        observed_floor_result='denied' if any(m['denial'] for m in members) else 'no_matching_denial')
    value['snapshot_id']='revocation_cut_'+A.F.digest(value)[7:];value=A.sealed(value,'snapshot_digest');validate('Snapshot',value);return value
def reference(value):return A.reference(value,'snapshot_id','snapshot_digest')
def read(db,ref_value):
    need(db.in_transaction,'revocation_transaction');validate('Ref',ref_value)
    row=db.execute('SELECT use_id,last_sequence,digest,body FROM authorization_revocation_snapshot WHERE snapshot_id=?',(ref_value['id'],)).fetchone();need(row is not None,'revocation_snapshot_missing')
    v=A.document(row[3]);validate('Snapshot',v)
    need(reference(v)==ref_value and row[2]==v['snapshot_digest'] and row[0]==v['source_use_ref']['id'] and (row[1] or 0)==int(v['observed_through']),'revocation_snapshot_columns')
    need(derive(db,v['source_use_ref'],int(v['observed_through']))==v,'revocation_snapshot_originals');return v
def current(db,ref_value):
    A.writer(db);v=read(db,ref_value)
    need(derive(db,v['source_use_ref'])==v,'revocation_snapshot_stale');return v
def capture(db,use_ref,*,fail_after=False,omit=False,commit_fault=None):
    need(not db.in_transaction,'revocation_capture_owns_transaction');db.execute('BEGIN IMMEDIATE')
    try:
        A.writer(db);v=derive(db,use_ref);r=reference(v)
        old=db.execute('SELECT 1 FROM authorization_revocation_snapshot WHERE snapshot_id=?',(r['id'],)).fetchone()
        if old:need(read(db,r)==v,'revocation_capture_conflict')
        else:
            if not omit:db.execute('INSERT INTO authorization_revocation_snapshot VALUES(?,?,?,?,?)',(r['id'],use_ref['id'],int(v['observed_through']) or None,v['snapshot_digest'],raw(v)))
            if fail_after:raise ValueError('injected_capture_failure')
            need(read(db,r)==v,'revocation_capture_readback')
        if commit_fault=='before':raise ValueError('injected_commit_before')
        db.commit()
        if commit_fault=='after':raise ValueError('injected_commit_after')
        return v
    except BaseException:
        if db.in_transaction:db.rollback()
        raise
