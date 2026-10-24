"""固定证据快照、受认证游标及历史读取的本地设计参考；没有HTTP服务。"""
import base64,hashlib,hmac,json,re
import typed_command_view_model as M
R=M.R;P=M.P;I=M.I;raw=M.raw;need=M.need;digest=M.digest
CONTRACT=M.G.C.VERSION
def counter(v):
    need(isinstance(v,str) and re.fullmatch(r'0|[1-9][0-9]{0,19}',v) is not None,'counter_format');return int(v)
def source_digest(kind,body):
    field={'decision':'evidence_digest','release':'evidence_digest','resolution':'resolution_digest'}.get(kind)
    if field:need(M.V.valid_digest(body,field),'source_digest');return body[field]
    return digest(body)
def evidence(row,scope,command):
    v=json.loads(row['view_body']);M.validate('EvidenceRecord',v)
    need(v['scope']==scope and v['command_id']==command==row['command_id'] and v['kind']==row['kind'],'evidence_owner')
    need(M.V.valid_digest(v,'view_digest') and v['view_digest']==row['view_digest'],'evidence_view_digest')
    body=json.loads(row['source_body']);need(v['body']==body,'evidence_original_body')
    sd=source_digest(v['kind'],body);need(sd==row['source_digest'],'evidence_source_digest')
    field={'observation':'evidence_id','decision':'evidence_id','release':'evidence_id','resolution':'resolution_id','invalidation':'invalidation_id'}[v['kind']]
    need(body[field]==row['evidence_id'] and body['command_id']==command,'evidence_original_owner')
    if 'scope' in body:need(body['scope']==scope,'evidence_original_scope')
    need(v['source_ref']==dict(id=row['evidence_id'],revision=str(int(row['revision'])),digest=sd),'evidence_original_ref')
    return v
def evidence_steps(db,command,revision,views,proof):
    """局部投影装配；完整生命周期事务负责先持久权威原件与State，最后cm_commit。"""
    need(db.in_transaction and proof['authorized'] and proof['originals_verified'] and proof['projection_verified'] and proof['redaction_verified'],'publication_authority')
    row=P.rows(db,'SELECT * FROM cm_revision WHERE command_id=? AND revision=?',(command,M.U(revision)))[0]
    need(not db.execute('SELECT 1 FROM cm_commit WHERE operation_id=?',(row['operation_id'],)).fetchone(),'publication_committed')
    state=json.loads(row['state_body']);need(proof['state_ref']==M.V.state_ref(state),'publication_state')
    need(proof['view_digests']==[v['view_digest'] for v in views],'publication_evidence_set')
    capacity=proof['max_snapshot_members'];need(type(capacity) is int and 1<=capacity<=65536,'snapshot_capacity_profile')
    count=db.execute('SELECT count(*) FROM cv_evidence WHERE command_id=? AND first_state_revision<=?',(command,M.U(revision))).fetchone()[0]
    need(count+len(views)<=capacity,'snapshot_capacity')
    existing=P.rows(db,'SELECT * FROM cv_evidence WHERE command_id=? AND first_state_revision<=? ORDER BY evidence_id,revision,kind',(command,M.U(revision)))
    rows=[]
    for v in views:
        M.validate('EvidenceRecord',v);kind=v['kind'];ref=v['source_ref'];body=v['body']
        subject=body['subject_ref'] if kind=='invalidation' else None
        value=dict(evidence_id=ref['id'],revision=M.U(ref['revision']),command_id=command,first_state_revision=M.U(revision),kind=kind,
            source_digest=ref['digest'],view_digest=v['view_digest'],source_body=raw(body),view_body=raw(v),validation_body=raw(proof),
            decision_id=ref['id'] if kind=='decision' else None,release_id=ref['id'] if kind=='release' else None,resolution_id=ref['id'] if kind=='resolution' else None,
            subject_id=subject['id'] if subject else None,subject_revision=M.U(subject['revision']) if subject else None,
            protection_ref_body=raw(body['protection_ref']) if subject else None)
        evidence(value,state['scope'],command);rows.append(value)
    allrows=sorted(existing+rows,key=lambda r:(r['evidence_id'],r['revision'],r['kind']))
    members=[dict(kind=r['kind'],source_ref=dict(id=r['evidence_id'],revision=str(int(r['revision'])),digest=r['source_digest']),view_digest=r['view_digest']) for r in allrows]
    manifest=dict(command_id=command,revision=revision,members=members);sid=command+'_evidence_'+revision
    metadata=json.loads(R.one(db,'cv_metadata','command_id',command)['metadata_body']);policy=json.loads(R.one(db,'cm_policy','command_id',command)['policy_body'])
    # 不从当前worker拼接历史attempt；完整可见字段由该生命周期提交的投影提供者给出。
    projection=proof['projection'];need(digest(projection)==proof['projection_digest'],'publication_projection_digest')
    v=M.record(metadata,policy,state,manifest,sid,projection['attempts'],projection['completion'],projection['cancellation'])
    cancel=P.rows(db,'SELECT cancellation_id,revision FROM cv_cancel_revision WHERE command_id=? AND state_revision<=? ORDER BY revision DESC LIMIT 1',(command,M.U(revision)))
    return [*[I('cv_evidence',**r) for r in rows],
        I('cv_snapshot',snapshot_id=sid,command_id=command,state_revision=M.U(revision),state_digest=digest(state),total=str(len(members)).zfill(20),snapshot_digest=digest(manifest),manifest_body=raw(manifest),validation_body=raw(proof)),
        *[I('cv_snapshot_member',snapshot_id=sid,ordinal=str(n).zfill(20),evidence_id=r['evidence_id'],evidence_revision=r['revision']) for n,r in enumerate(allrows)],
        I('cv_record',command_id=command,revision=M.U(revision),state_digest=digest(state),metadata_digest=digest(metadata),snapshot_id=sid,
            cancellation_id=cancel[0]['cancellation_id'] if cancel else None,cancellation_revision=cancel[0]['revision'] if cancel else None,
            record_digest=v['record_digest'],record_body=raw(v),validation_body=raw(proof))]

def auth_snapshot(db,command,auth):
    need(auth['authenticated'] and auth['authorization_current'] and 'command.evidence.read' in auth['permissions'] and auth['scope']==M.C.scope(db),'evidence_authority')
    need(auth['storage_readable'],'unavailable')
    metadata=json.loads(R.one(db,'cv_metadata','command_id',command)['metadata_body']);M.authorize(metadata,auth,'command.evidence.read');return metadata
def single(db,command,evidence_id,revision,auth):
    need(not db.in_transaction,'read_requires_committed_snapshot');M.U(revision);db.execute('BEGIN')
    try:
        m=auth_snapshot(db,command,auth)
        rows=P.rows(db,'SELECT e.* FROM cv_evidence e JOIN cm_commit c ON c.command_id=e.command_id AND c.revision=e.first_state_revision WHERE e.command_id=? AND e.evidence_id=? AND e.revision=?',(command,evidence_id,M.U(revision)))
        need(bool(rows),'not_found');v=evidence(rows[0],m['scope'],command);db.commit()
    except BaseException:db.rollback();raise
    need(auth['response_authorized'],'response_authority');return v

def sign(claims,key):
    need(type(key) is bytes and len(key)>=32,'cursor_key_unavailable')
    body=raw(claims);mac=hmac.digest(key,b'leafseamer-evidence-cursor/1\0'+body,'sha256')
    token=base64.urlsafe_b64encode(body+b'.'+mac).decode().rstrip('=');need(len(token)<=4096,'cursor_size');return token
def decode(token,keys):
    need(isinstance(token,str) and re.fullmatch(r'[A-Za-z0-9_-]{16,4096}',token) is not None,'cursor_format')
    b=base64.urlsafe_b64decode(token+'='*((-len(token))%4));need(base64.urlsafe_b64encode(b).decode().rstrip('=')==token and len(b)>33 and b[-33:-32]==b'.','cursor_encoding')
    body=b[:-33];claims=json.loads(body);need(type(claims) is dict and type(claims.get('key_id')) is str and raw(claims)==body,'cursor_canonical')
    key=keys.get(claims.get('key_id'));need(type(key) is bytes and len(key)>=32,'cursor_key_unavailable')
    need(hmac.compare_digest(b[-32:],hmac.digest(key,b'leafseamer-evidence-cursor/1\0'+body,'sha256')),'cursor_authentication')
    return claims
def page(db,command,state_revision,limit,auth,clock,keyring,cursor=None):
    need(not db.in_transaction,'read_requires_committed_snapshot');M.U(state_revision)
    need(type(limit) is int and 1<=limit<=64,'page_limit')
    subject=auth['cursor_subject'];need(type(subject) is dict and set(subject)=={'issuer_id','issuer_epoch','principal_id','session_id','authorization_revision'},'cursor_subject')
    need(all(type(v) is str and 1<=len(v)<=256 for v in subject.values()),'cursor_subject');M.U(subject['authorization_revision'])
    need(clock['verified'] and keyring['available'],'cursor_provider');now=counter(clock['now_tick']);ttl=counter(keyring['ttl_ns']);need(ttl>0 and now+ttl<10**20,'cursor_time_range')
    scope=M.C.scope(db);db.execute('BEGIN')
    try:
        auth_snapshot(db,command,auth)
        rows=P.rows(db,'SELECT * FROM cv_history WHERE command_id=? AND revision=?',(command,M.U(state_revision)));need(bool(rows),'snapshot_gone')
        row=rows[0];snapshot=R.one(db,'cv_snapshot','snapshot_id',row['snapshot_id'])
        capacity=keyring['max_snapshot_members'];need(type(capacity) is int and 1<=capacity<=65536 and int(snapshot['total'])<=capacity,'snapshot_capacity')
        record=M.complete_record(db,row);index=record['evidence_index'];total=counter(index['total'])
        binding=dict(version='evidence-cursor/1',contract_version=CONTRACT,scope=scope,command_id=command,state_ref=record['state_ref'],snapshot_ref=index['snapshot_ref'],
            subject=auth['cursor_subject'],limit=limit,clock_domain_id=clock['clock_domain_id'],descriptor_digest=clock['descriptor_digest'])
        if cursor is None:
            claims=dict(binding,key_id=keyring['active_key_id'],issued_tick=str(now),expires_tick=str(now+ttl),offset='0')
        else:
            claims=decode(cursor,keyring['keys'])
            need(set(claims)==set(binding)|{'key_id','issued_tick','expires_tick','offset'} and all(claims[k]==v for k,v in binding.items()),'cursor_binding')
            issued=counter(claims['issued_tick']);expires=counter(claims['expires_tick'])
            need(issued<=now<expires and expires>issued,'snapshot_gone')
        offset=counter(claims['offset']);need(offset<=total,'cursor_offset')
        members=P.rows(db,'SELECT e.*,m.ordinal FROM cv_snapshot_member m JOIN cv_evidence e ON e.evidence_id=m.evidence_id AND e.revision=m.evidence_revision WHERE m.snapshot_id=? AND m.ordinal>=? ORDER BY m.ordinal LIMIT ?',
            (row['snapshot_id'],str(offset).zfill(20),limit))
        need([int(x['ordinal']) for x in members]==list(range(offset,min(offset+limit,total))),'snapshot_page_gap')
        views=[evidence(x,scope,command) for x in members];next_offset=offset+len(views)
        next_cursor=sign(dict(claims,offset=str(next_offset)),keyring['keys'].get(claims['key_id'])) if next_offset<total else None
        v=dict(scope=scope,command_id=command,snapshot_ref=index['snapshot_ref'],state_ref=record['state_ref'],offset=str(offset),total=str(total),items=views,next_cursor=next_cursor)
        M.V.seal(v,'page_digest');M.validate('EvidencePage',v);db.commit()
    except BaseException:db.rollback();raise
    need(auth['response_authorized'],'response_authority');return v
