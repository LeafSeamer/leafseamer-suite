"""设备授权九表原子采用候选；输入来源仍为显式合成受信适配器。"""
import json
import rfc8785
import device_authorization_model as M
HERE=M.B.HERE;need=M.need
def raw(value):return rfc8785.dumps(value)
def decode(body):
    need(isinstance(body,bytes) and 0<len(body)<=16777216,'storage_body_size')
    def pairs(items):
        result={}
        for key,value in items:need(key not in result,'storage_duplicate_key');result[key]=value
        return result
    value=json.loads(body,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('storage_nonfinite')))
    need(raw(value)==body,'storage_canonical');return value
def one(db,sql,args=()):
    row=db.execute(sql,args).fetchone();need(row is not None,'storage_original_missing');return row
def install(db):
    need(not db.in_transaction and db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'storage_install_connection')
    try:db.executescript('BEGIN IMMEDIATE;\n'+(HERE/'device-authorization-storage.sql').read_text('utf-8')+'\nCOMMIT;')
    except BaseException:
        if db.in_transaction:db.rollback()
        raise
def state(db,ref):
    row=one(db,'SELECT authority_id,database_id,device_id,revision,parent_id,status,recovery_id,digest,body FROM da_state WHERE state_id=?',(ref['id'],))
    value=decode(row[8]);M.state(value);c=value['context']
    need(M.reference(value,'state')==ref and tuple(row[:8])==(c['scope']['authority_service_id'],c['scope']['database_instance_id'],c['device_id'],value['revision'].zfill(20),
        value['parent_ref']['id'] if value['parent_ref'] else None,value['status'],value['recovery_ref']['id'] if value['recovery_ref'] else None,value['state_digest']),'storage_state_columns')
    return value
def evidence(db,ref):
    row=one(db,'SELECT state_id,digest,body FROM da_evidence WHERE evidence_id=?',(ref['id'],));value=decode(row[2]);M.validate('Evidence',value)
    need(M.seal(value,'evidence_digest')==value and M.reference(value,'evidence')==ref and (row[0],row[1])==(value['state_ref']['id'],value['evidence_digest']),'storage_evidence_columns');return value
def recovery_binding(db,current,value):
    ref=current['recovery_ref'];need(ref is not None,'storage_recovery_required')
    row=one(db,'SELECT protected_state_id,digest,body FROM da_revalidation WHERE authorization_id=?',(ref['id'],));a=decode(row[2]);M.validate('RecoveryAuthorization',a)
    need(M.seal(a,'authorization_digest')==a and M.reference(a,'authorization')==ref and a['protected_state_ref']==current['parent_ref'] and
        row[0]==current['parent_ref']['id'] and row[1]==a['authorization_digest'],'storage_recovery_original')
    need(a['binding']==value['requirement']['binding'],'storage_recovery_binding')
    need(one(db,'SELECT state_id FROM da_consumption WHERE authorization_id=?',(ref['id'],))[0]==current['state_id'],'storage_recovery_consumption')
def receipt(db,operation_id):
    row=one(db,'SELECT c.parent_id,c.kind,c.state_id,c.evidence_id,c.generation,c.digest,c.body,a.body,o.body,s.body FROM da_commit c JOIN da_audit a USING(commit_id) JOIN da_outbox o USING(commit_id) JOIN da_seal s USING(commit_id) WHERE commit_id=?',(operation_id,))
    v=decode(row[6]);need(set(v)=={'format_version','operation_id','request','before','after','parent_ref','sampled_tick_ns','receipt_digest'} and v['format_version']=='device-authorization-commit/0.1.0-draft.1','storage_receipt_format')
    M.validate('Counter',v['sampled_tick_ns']);need(M.seal(v,'receipt_digest')==v and v['receipt_digest']==row[5] and v['operation_id']==operation_id,'storage_receipt_digest')
    need(row[6]==row[7]==row[8]==row[9],'storage_delivery_bodies');h=v['after']
    need(tuple(row[:5])==(v['parent_ref']['id'] if v['parent_ref'] else None,v['request']['kind'],h['state_ref']['id'],h['evidence_ref']['id'] if h['evidence_ref'] else None,h['generation'].zfill(20)),'storage_receipt_columns')
    return v
def receipt_ref(v):return dict(id=v['operation_id'],revision='1',digest=v['receipt_digest'])
def head(db,scope,device):
    need(db.in_transaction,'storage_transaction')
    row=db.execute('SELECT h.state_id,s.revision,s.digest,h.evidence_id,e.digest,h.generation,h.commit_id FROM da_head h JOIN da_state s USING(state_id) LEFT JOIN da_evidence e ON e.evidence_id=h.evidence_id WHERE h.authority_id=? AND h.database_id=? AND h.device_id=?',
        (scope['authority_service_id'],scope['database_instance_id'],device)).fetchone()
    if row is None:return None
    value=dict(state_ref=dict(id=row[0],revision=str(int(row[1])),digest=row[2]),evidence_ref=None if row[3] is None else dict(id=row[3],revision='1',digest=row[4]),generation=str(int(row[5])))
    state(db,value['state_ref'])
    if value['evidence_ref']:evidence(db,value['evidence_ref'])
    need(receipt(db,row[6])['after']==value,'storage_head_receipt');return value
def read_commit(db,operation_id):
    need(db.in_transaction,'storage_transaction');v=receipt(db,operation_id);r=v['request'];old=v['before'];after=v['after'];now=v['sampled_tick_ns']
    need(int(after['generation'])==(1 if old is None else int(old['generation'])+1),'storage_generation_step')
    if old is None:need(v['parent_ref'] is None and r['kind']=='initialize','storage_initial_receipt')
    else:
        parent=receipt(db,v['parent_ref']['id']);need(receipt_ref(parent)==v['parent_ref'] and parent['after']==old,'storage_parent_receipt')
        need(r['expected']['state_ref']==old['state_ref'] if r['kind']=='protect' else r['expected']==old,'storage_receipt_cas')
    actual=state(db,after['state_ref']);previous=state(db,old['state_ref']) if old else None
    if r['kind']=='initialize':expected=M.transition(None,r['context'],'protected',['initial'])
    elif r['kind']=='protect':expected=M.transition(previous,r['context'],'protected',r['reasons'])
    elif r['kind']=='revalidate':
        row=one(db,'SELECT protected_state_id,digest,body FROM da_revalidation WHERE authorization_id=?',(r['authorization']['authorization_id'],))
        authorization=decode(row[2]);need(authorization==r['authorization'] and row[0]==previous['state_id'] and row[1]==authorization['authorization_digest'],'storage_revalidation_original')
        expected=M.revalidate(previous,r['context'],authorization,r['binding'],now)
        need(one(db,'SELECT state_id FROM da_consumption WHERE authorization_id=?',(authorization['authorization_id'],))[0]==expected['state_id'],'storage_consumption')
    else:
        need(r['kind']=='select','storage_operation');expected=previous;ev=evidence(db,after['evidence_ref']);need(ev==r['evidence'],'storage_evidence_original');recovery_binding(db,previous,ev)
        if old['evidence_ref']:M.renewal(previous,evidence(db,old['evidence_ref']),ev,now)
        else:M.evidence(previous,ev,now)
    need(actual==expected and (r['kind']=='select' or after['evidence_ref'] is None),'storage_state_transition')
    return v
def apply(db,operation_id,request,now,*,fail_after=None,omit=None,commit_fault=None):
    need(not db.in_transaction and db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'storage_writer_connection');M.validate('Id',operation_id);M.validate('Counter',now)
    kind=request['kind'];need(kind in ('initialize','revalidate','protect','select'),'storage_operation')
    expected_keys={'initialize':{'kind','context'},'revalidate':{'kind','expected','context','authorization','binding'},'protect':{'kind','expected','context','reasons'},'select':{'kind','expected','evidence'}}
    need(set(request)==expected_keys[kind],'storage_request_fields');db.execute('BEGIN IMMEDIATE');writes=[]
    def write(label,sql,args):
        if label!=omit:db.execute(sql,args)
        writes.append(label)
        if label==fail_after:raise ValueError('injected_write_'+label)
    try:
        if db.execute('SELECT 1 FROM da_commit WHERE commit_id=?',(operation_id,)).fetchone():
            old_receipt=read_commit(db,operation_id);need(old_receipt['request']==request,'storage_request_conflict');db.commit();return old_receipt,[]
        if kind=='select':
            c=request['evidence']['requirement']['binding'];scope=c['scope'];device=c['device_id']
        else:c=request['context'];scope=c['scope'];device=c['device_id']
        before=head(db,scope,device);previous=state(db,before['state_ref']) if before else None
        if kind=='initialize':need(before is None,'storage_already_initialized');value=M.transition(None,c,'protected',['initial'])
        else:need(before is not None and (request['expected']['state_ref']==before['state_ref'] if kind=='protect' else request['expected']==before),'storage_head_cas')
        if kind=='protect':value=M.transition(previous,c,'protected',request['reasons']);need(value!=previous,'storage_noop_requires_original_key')
        if kind=='revalidate':value=M.revalidate(previous,c,request['authorization'],request['binding'],now)
        if kind=='select':
            value=previous;ev=request['evidence'];need(value['status']=='policy_selected','state_protected');recovery_binding(db,value,ev)
            if before['evidence_ref']:M.renewal(value,evidence(db,before['evidence_ref']),ev,now)
            else:M.evidence(value,ev,now)
        generation=1 if before is None else int(before['generation'])+1;need(generation<=M.MAX,'storage_generation_exhausted')
        after=dict(state_ref=M.reference(value,'state'),evidence_ref=M.reference(request['evidence'],'evidence') if kind=='select' else None,generation=str(generation))
        parent=None
        if before:
            pid=one(db,'SELECT commit_id FROM da_head WHERE authority_id=? AND database_id=? AND device_id=?',(scope['authority_service_id'],scope['database_instance_id'],device))[0];parent=receipt_ref(receipt(db,pid))
        record=M.seal(dict(format_version='device-authorization-commit/0.1.0-draft.1',operation_id=operation_id,request=request,before=before,after=after,parent_ref=parent,sampled_tick_ns=now),'receipt_digest')
        if kind=='revalidate':
            a=request['authorization'];write('authorization','INSERT INTO da_revalidation VALUES(?,?,?,?)',(a['authorization_id'],a['protected_state_ref']['id'],a['authorization_digest'],raw(a)))
        if kind!='select':
            write('state','INSERT INTO da_state VALUES(?,?,?,?,?,?,?,?,?,?,?)',(value['state_id'],scope['authority_service_id'],scope['database_instance_id'],device,value['revision'].zfill(20),value['parent_ref']['id'] if value['parent_ref'] else None,
                value['status'],value['recovery_ref']['id'] if value['recovery_ref'] else None,operation_id,value['state_digest'],raw(value)))
        else:write('evidence','INSERT INTO da_evidence VALUES(?,?,?,?,?)',(ev['evidence_id'],value['state_id'],operation_id,ev['evidence_digest'],raw(ev)))
        if kind=='revalidate':write('consume','INSERT INTO da_consumption VALUES(?,?)',(request['authorization']['authorization_id'],value['state_id']))
        args=(value['state_id'],after['evidence_ref']['id'] if after['evidence_ref'] else None,str(generation).zfill(20),operation_id,scope['authority_service_id'],scope['database_instance_id'],device)
        if before is None:write('head','INSERT INTO da_head(state_id,evidence_id,generation,commit_id,authority_id,database_id,device_id) VALUES(?,?,?,?,?,?,?)',args)
        else:write('head','UPDATE da_head SET state_id=?,evidence_id=?,generation=?,commit_id=? WHERE authority_id=? AND database_id=? AND device_id=?',args)
        body=raw(record)
        write('commit','INSERT INTO da_commit VALUES(?,?,?,?,?,?,?,?)',(operation_id,parent['id'] if parent else None,kind,value['state_id'],after['evidence_ref']['id'] if after['evidence_ref'] else None,str(generation).zfill(20),record['receipt_digest'],body))
        for label in ('audit','outbox','seal'):write(label,'INSERT INTO da_'+label+' VALUES(?,?)',(operation_id,body))
        need(read_commit(db,operation_id)==record and head(db,scope,device)==after,'storage_readback')
        if commit_fault=='before':raise ValueError('injected_commit_before')
        db.commit()
        if commit_fault=='after':raise ValueError('injected_commit_after')
        return record,writes
    except BaseException:
        if db.in_transaction:db.rollback()
        raise
