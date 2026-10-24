"""完整Controller裁决接收与失败保护同事务；没有网络查询或重发设备调用。"""
import json
from jsonschema import Draft202012Validator
import build_adjudication_receive as G
import typed_seamer_model as T
import instance_budget_model as IB
import failure_protection_model as F
S=T.S;B=T.B;R=T.R;P=T.P;I=T.I;raw=T.raw;need=T.need;digest=B.M.digest
SCHEMA=G.schema()

def validate(db,o,evidence,ctx):
    Draft202012Validator(SCHEMA).validate(o)
    need(ctx['observer_authorized'] and evidence['trusted_provider'],'observer_authority')
    s=R.one(db,'command_submission','submission_id',o['submission_id'])
    identity=dict(key=json.loads(s['request_key_body']),request_digest=s['request_digest'])
    need(o['identity']==identity and evidence['identity']==identity,'observation_identity')
    need(s['attempt_id'] is not None and evidence['attempt_id']==s['attempt_id'],'attempt_original')
    need(evidence['observation_digest']==digest(o),'observation_digest')
    if o['source'] in ('create_response','lookup'):
        need(evidence['authenticated'] and evidence['controller_scope']==identity['key']['target_scope'],'controller_provider')
    result=o['result'];a=result['adjudication'] if result and result['state']=='found' else None
    if a:
        need(evidence['durable_record_verified'] and evidence['record_digest']==a['adjudication_digest'],'durable_adjudication')
        need(a['identity']==identity,'adjudication_identity')
        need(digest({k:v for k,v in a.items() if k!='adjudication_digest'})==a['adjudication_digest'],'adjudication_digest')
        for ref in [a['commit_ref']]+([a['command_ref']] if a['command_ref'] else []):
            need(ref['scope']==identity['key']['target_scope'] and ref['revision']=='1','adjudication_scope_revision')
    return s,a

def steps(db,o,evidence,ctx):
    need(db.in_transaction,'transaction_required');s,a=validate(db,o,evidence,ctx)
    prior=P.rows(db,'SELECT * FROM sa_observation WHERE observation_id=?',(o['observation_id'],))
    if prior:
        need(prior[0]['observation_body']==raw(o),'observation_conflict');R.one(db,'sa_commit','observation_id',o['observation_id']);return [],None
    st=F.F.step(db,s['execution_id'],s['step_id']);old=P.rows(db,'SELECT * FROM submission_adjudication WHERE submission_id=?',(s['submission_id'],))
    if a and old:need(old[0]['receipt_body']==raw(a),'adjudication_conflict')
    local=old[0]['adjudication_id'] if old else ('receipt_'+digest(s['submission_id']).split(':')[1] if a else None)
    outcome=a['decision'] if a else 'uncertain';after=a['decision'] if a else s['state'] if old else 'indeterminate'
    terminal=None
    if st['outcome']=='pending' and not old and outcome!='accepted':terminal='failed' if outcome=='rejected' else 'unknown'
    promote=st['outcome']=='pending' and st['state']=='submission_pending' and outcome=='accepted'
    rev=P.inc(st['revision']) if terminal or promote else st['revision']
    state='indeterminate' if terminal=='unknown' else 'finished' if terminal else 'accepted' if promote else st['state']
    tid=s['execution_id']+'.'+s['step_id']+'.terminal' if terminal else st['terminal_id']
    writes=[I('sa_observation',observation_id=o['observation_id'],submission_id=s['submission_id'],attempt_id=s['attempt_id'],observation_digest=digest(o),observation_body=raw(o),evidence_body=raw(evidence),result=outcome,
      submission_before=s['state'],submission_after=after,step_revision_before=st['revision'],step_revision_after=rev,step_state_before=st['state'],step_state_after=state,
      step_outcome_before=st['outcome'],step_outcome_after=terminal or st['outcome'],adjudication_id=local,terminal_id=tid)]
    if a and not old:
        need(s['state'] in ('attempt_recorded','indeterminate'),'adjudication_prestate')
        ref=T.ref('request_adjudication',o['identity']['key']['target_scope'],a['adjudication_id'],a['adjudication_digest'])
        writes+=F.F.event(db,s['run_id'],'ADJUDICATION',local)+[
          I('submission_adjudication',observation_id=o['observation_id'],adjudication_id=local,submission_id=s['submission_id'],run_id=s['run_id'],target_authority=s['target_authority'],target_database=s['target_database'],request_digest=s['request_digest'],outcome=a['decision'],command_ref_body=raw(a['command_ref']) if a['command_ref'] else None,receipt_ref_body=raw(ref),receipt_body=raw(a),tx_id=local+'.ADJUDICATION'),
          ('UPDATE command_submission SET state=?,adjudication_id=? WHERE submission_id=?',(after,local,s['submission_id']))]
    elif not old and s['state']!='indeterminate':writes.append(("UPDATE command_submission SET state='indeterminate' WHERE submission_id=?",(s['submission_id'],)))
    if promote:writes.append(("UPDATE step_state SET revision=?,state='accepted' WHERE execution_id=? AND step_id=?",(rev,s['execution_id'],s['step_id'])))
    if terminal:
        terminal_ctx=dict(ctx,terminal_evidence_verified=True);terminal_ctx.pop('completion_command_ref',None)
        writes+=F.terminal_steps(db,s['execution_id'],s['step_id'],terminal,terminal_ctx)
    seal=I('sa_commit',observation_id=o['observation_id'],audit_body=raw(dict(result=outcome,submission_id=s['submission_id'])),notification_body=raw(dict(kind='submission_observed',observation_id=o['observation_id'])))
    return writes,seal

def receive(db,o,evidence,ctx,fail_after=None,preview=False):
    need(db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'foreign_keys_required')
    writes=[];db.execute('BEGIN IMMEDIATE')
    try:
        before=IB.C.snapshot(db);old={r[0] for r in db.execute('SELECT plan_id FROM protection_plan_registry')}
        parts,seal=steps(db,o,evidence,ctx)
        if any(sql.startswith('INSERT INTO sf_plan(') for sql,args in parts):ctx['protection_confirmation']='unconfirmed'
        def execute(items):
            for sql,args in items:
                db.execute(sql,args);writes.append((sql,args))
                if fail_after==len(writes)-1:raise RuntimeError('injected')
        execute(parts);plans=sorted({r[0] for r in db.execute('SELECT plan_id FROM protection_plan_registry')}-old)
        if seal:execute([seal])
        if plans:
            execute(IB.charge_steps(db,plans,before,ctx));execute(IB.C.charge_steps(db,plans,before,ctx))
        need(not db.execute('PRAGMA foreign_key_check').fetchone(),'foreign_key_check_failed')
        if preview:db.rollback();return writes
        db.commit()
        if plans:ctx['protection_confirmation']='durable'
        return 'recorded' if seal else 'existing'
    except BaseException:db.rollback();raise
