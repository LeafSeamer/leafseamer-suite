"""授权撤销与最终编码来源的局部SQLite实验；身份取证均为合成。"""
import argparse,copy,hashlib,json,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import check_final_encoding_source as T
import final_authorization_model as M
G=M.G;HERE=G.HERE;ROOT=T.ROOT;clone=copy.deepcopy

def fixture():
    """在首次受理前登记合成scope/context，旧库不允许事后补写归属。"""
    original=T.T.V.M.decide
    def before(db,identity,body,auth,*args,**kwargs):
        db.executescript((HERE/'final-authorization.sql').read_text('utf-8'))
        key=identity['key'];ns=db.execute('SELECT namespace_id FROM ca_namespace WHERE issuer_id=? AND issuer_epoch=? AND principal_id=? AND request_epoch=?',tuple(key[k] for k in ('issuer_id','issuer_epoch','principal_id','request_epoch'))).fetchone()[0]
        who=dict(kind=auth['principal_kind'],**{k:key[k] for k in ('issuer_id','issuer_epoch','principal_id')})
        scope=dict(format_version='command-scope/1',scope=key['target_scope'],requester=who,credential_id='credential',permissions=['device.command'],
            targets=[{k:body[k] for k in ('device_id','action_id','capability_version')}])
        def register():
            scope_ref=M.store_scope(db,scope)
            context=M.sealed(dict(format_version='request-context-binding/1',context_id=body['context_id'],revision='1',scope=key['target_scope'],namespace_id=ns,request_epoch=key['request_epoch'],
                requester=who,credential_id='credential',session_id=None,operations=['createCommand'],original_scope_ref=scope_ref,issuance_evidence_ref=T.V.ref('fixture.context.issuance')),'context_digest')
            M.store_context(db,context)
        tx(db,register)
        return original(db,identity,body,auth,*args,**kwargs)
    with patch.object(T.T.V.M,'decide',side_effect=before):return T.fixture()

def use(v,db=None):
    identity=clone(v['identity']);p=identity['requester'];manual=identity['origin']=='manual'
    a=dict(**{k:p[k] for k in ('issuer_id','issuer_epoch','principal_id')},audience=v['binding']['scope']['authority_service_id'],principal_kind=p['kind'],origin=identity['origin'],
        session_id='session' if manual else None,credential_id='credential',subject_revision='4',session_revision='4' if manual else None,policy_revision='2',scope_digest=M.F.digest('scope'),
        grant_id=None if manual else 'grant',grant_revision=None if manual else '4',arm_generation=None if manual else '1',extension_instance_id=None,extension_approval_revision=None)
    if not manual:
        row=db.execute('SELECT k.content_body FROM ca_request_key k JOIN ca_command_initial i USING(key_id) WHERE i.command_id=?',(identity['command_ref']['id'],)).fetchone()
        run=json.loads(row[0])['run_binding']
        a.update({k:run[k] for k in ('grant_id','grant_revision','arm_generation')})
        context=json.loads(db.execute('SELECT body FROM authorization_context').fetchone()[0]);a['scope_digest']=context['original_scope_ref']['digest']
    s={k:x for k,x in a.items() if k in M.SCHEMA['$defs']['AuthorizationSnapshot']['properties']}
    s.update(snapshot_id='snapshot',issuer_revision='8',challenge_id='challenge',permissions=['device.command'],
        validity=dict(not_before='2026-01-01T00:00:00.000Z',expires_at='2026-01-01T01:00:00.000Z'),fresh_for_ms=1,state='active')
    return M.sealed(dict(format_version='authorization-use/1',use_id='use',revision='1',binding=clone(v['binding']),identity=identity,authorization_binding=a,snapshot=s,
        challenge_sent_tick_ns='1',received_tick_ns='50',local_freshness_limit_ms=1,not_before_tick_ns='49',authorization_before_tick_ns='80',
        authority_evidence_ref=T.V.ref('authority'),scope_evidence_ref=T.V.ref('scope'),validity_evidence_ref=T.V.ref('validity')),'use_digest')

def use_ref(u):return M.E.ref(u['use_id'],u['revision'],u['use_digest'])

def capture(u):
    """构造新的合成认证传输记录；不能用于把已经保存的错误来源修成正确。"""
    s=u['snapshot'];s['challenge_id']=M.F.digest(u['use_id'])[7:]
    c=M.sealed(dict(format_version='authorization-challenge/1',challenge_id=s['challenge_id'],revision='1',binding=clone(u['binding']),
        requester=dict(kind=s['principal_kind'],**{k:s[k] for k in ('issuer_id','issuer_epoch','principal_id')}),credential_id=s['credential_id'],audience=s['audience'],
        scope_digest=s['scope_digest'],requested_permission='device.command',sent_tick_ns=u['challenge_sent_tick_ns']),'challenge_digest')
    r=M.sealed(dict(format_version='authorization-response/1',response_id=u['use_id']+'.response',revision='1',scope=u['binding']['scope'],
        challenge_ref=M.reference(c,'challenge_id','challenge_digest'),snapshot=clone(s),received_tick_ns=u['received_tick_ns'],channel_evidence_ref=T.V.ref('fixture.channel')),'response_digest')
    u['authority_evidence_ref']=M.reference(r,'response_id','response_digest');u.update(M.sealed(u,'use_digest'));return c,r

def publish_use(db,u):
    c,r=capture(u);M.store_challenge(db,c);M.store_response(db,r)
    if u['identity']['origin']=='automation':u['scope_evidence_ref']=M.scope_proof_reference(M.scope_details(db,u)[3]);u.update(M.sealed(u,'use_digest'))
    M.store_use(db,u)
def floor(u,kind='principal',revision='5',eid='event',**changes):
    a=u['authorization_binding'];target={'principal':a['principal_id'],'credential':a['credential_id'],'session':a['session_id'],'grant':a['grant_id'],'trust':'trust.domain','extension':'extension'}[kind]
    s=dict(kind=kind,issuer_id=a['issuer_id'],issuer_epoch=a['issuer_epoch'],target_id=target,revision_floor=revision);s.update(changes)
    return M.sealed(dict(event_id=eid,scope=u['binding']['scope'],selector=s,operation_ref=T.V.ref('operation.'+eid)),'event_digest')

def tx(db,fn):
    db.execute('BEGIN IMMEDIATE')
    try:out=fn();db.commit();return out
    except BaseException:db.rollback();raise

def attach(v,o,authorization):
    o['authorization']=authorization
    for role in ('gate_access','permit_authority'):o[role]['body']['authorization_ref']=authorization['source_ref']
    T.V.refresh(v,o)

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def reject(n,fn,reason=None):
        try:fn()
        except (ValueError,ValidationError,sqlite3.Error) as error:
            if reason:assert reason in str(error),(n,str(error))
            check(n)
        else:raise AssertionError('未拒绝:'+n)
    def fork(db):
        c=sqlite3.connect(':memory:',isolation_level=None);db.backup(c);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON');dbs.append(c);return c
    try:
        check('Schema生成字节一致',(HERE/'final-authorization.schema.json').read_bytes()==G.raw(G.build()))
        Draft202012Validator.check_schema(M.SCHEMA);check('根拒绝实例',not Draft202012Validator(M.SCHEMA).is_valid({}))
        db,connections,cmd,auth,pid,provider,response=fixture();dbs.extend(connections)
        T.E.O.execute(db,T.T.preview(db,lambda:T.E.receive(db,pid,response,provider)))
        v,o,cut=T.T.preview(db,lambda:T.candidate(db,pid,provider));u=use(v,db)
        # 采样回执到达后才产生有效资格；此fixture接收tick为50，仍早于选取51。
        u=M.sealed(dict(u,received_tick_ns='50'),'use_digest')
        tx(db,lambda:publish_use(db,u));ur=use_ref(u);auth_projection=T.T.preview(db,lambda:M.read(db,ur,v));attach(v,o,auth_projection)
        check('248表含受理前上下文及最终授权来源',len(T.T.V.SC.snapshot(db))==248)
        check('普通自动化可规划19条附属封存写集',len(T.T.preview(db,lambda:M.planned(db,v,o,cut,pid,provider,ur)))==19)
        context=json.loads(db.execute('SELECT body FROM authorization_context').fetchone()[0])
        original_scope=T.T.preview(db,lambda:M.command_scope(db,context['original_scope_ref']))
        proof=T.T.preview(db,lambda:M.scope_details(db,u)[3])
        check('scope证明绑定实际上下文和请求',proof['context_ref']['id']==context['context_id'] and proof['request_ref']==u['identity']['source_ref'])
        keyrow=M.E.one(db,'SELECT * FROM ca_request_key WHERE key_id=?',(u['identity']['source_ref']['id'],))
        def new_request(c,context_id):
            value=dict(keyrow);transport=json.loads(value['transport_body']);key=json.loads(value['request_key_body'])
            transport.update(context_id=context_id,idempotency_key='new.request');key['idempotency_key']='new.request'
            value.update(key_id='new.key',idempotency_key='new.request',transport_body=M.raw(transport),request_key_body=M.raw(key))
            c.execute(*T.E.I('ca_request_key',**value))
        c=fork(db)
        reject('首次受理必须先有上下文',lambda:tx(c,lambda:new_request(c,'missing.context')),'request_context_not_registered')
        for name,mutate in [
            ('空动作范围',lambda s:s.update(targets=[])),
            ('缺device.command权限',lambda s:s.update(permissions=[])),
            ('仅另一动作',lambda s:s['targets'][0].update(action_id='other.action'))]:
            c=fork(db);limited=clone(original_scope);mutate(limited)
            ctx=clone(context);ctx['context_id']='limited.context'
            def register():
                ctx['original_scope_ref']=M.store_scope(c,limited);ctx.update(M.sealed(ctx,'context_digest'));M.store_context(c,ctx)
            tx(c,register)
            reject('初次受理不超出原始范围:'+name,lambda:tx(c,lambda:new_request(c,ctx['context_id'])),'request_context_scope_rejected')
        c=fork(db);ctx=clone(context);ctx.update(context_id='read.only.context',operations=['lookupCommand']);ctx=M.sealed(ctx,'context_digest')
        tx(c,lambda:M.store_context(c,ctx))
        reject('上下文操作交集不能扩为createCommand',lambda:tx(c,lambda:new_request(c,ctx['context_id'])),'request_context_scope_rejected')
        for name,mutate in [
            ('移除目标',lambda s:s.update(targets=[])),
            ('更换能力版本',lambda s:s['targets'][0].update(capability_version='other.version')),
            ('组合拆开后不允许笛卡尔积',lambda s:s.update(targets=[dict(s['targets'][0],action_id='other.action'),dict(s['targets'][0],device_id='other.device')]))]:
            c=fork(db);current=clone(original_scope);mutate(current);current['targets'].sort(key=lambda x:(x['device_id'],x['action_id'],x['capability_version']))
            sr=tx(c,lambda:M.store_scope(c,current));bad=clone(u);bad['use_id']='narrowed'
            for field in ('authorization_binding','snapshot'):bad[field]['scope_digest']=sr['digest']
            tx(c,lambda:publish_use(c,bad))
            reject('最终发送核对当前完整目标:'+name,lambda:T.T.preview(c,lambda:M.read(c,use_ref(bad),v)),'authorization_target_not_allowed')
        c=fork(db);expanded=clone(original_scope);expanded['targets'].append(dict(expanded['targets'][0],device_id='other.device'))
        sr=tx(c,lambda:M.store_scope(c,expanded));renewed=clone(u);renewed['use_id']='renewed'
        for field in ('authorization_binding','snapshot'):renewed[field]['scope_digest']=sr['digest']
        tx(c,lambda:publish_use(c,renewed));T.T.preview(c,lambda:M.read(c,use_ref(renewed),v));check('新范围增加目标不改变原上下文且原目标可用')
        check('上下文原始scope不因刷新改写',json.loads(c.execute('SELECT body FROM authorization_context').fetchone()[0])==context)
        c=fork(db);rotated=clone(original_scope);rotated['credential_id']='credential.rotated';sr=tx(c,lambda:M.store_scope(c,rotated))
        bad=clone(u);bad['use_id']='rotated'
        for field in ('authorization_binding','snapshot'):bad[field].update(credential_id='credential.rotated',scope_digest=sr['digest'])
        tx(c,lambda:publish_use(c,bad))
        reject('即使新challenge响应有效也不继承旧context凭据',lambda:T.T.preview(c,lambda:M.read(c,use_ref(bad),v)),'authorization_context_credential_chain')
        c=fork(db);bad=clone(u);bad['use_id']='scope.ref.forged';bad['scope_evidence_ref']['digest']=M.F.digest('forged');bad=M.sealed(bad,'use_digest');tx(c,lambda:M.store_use(c,bad))
        reject('scope证明必须是原件重建的完整引用',lambda:T.T.preview(c,lambda:M.read(c,use_ref(bad),v)),'authorization_scope_proof_ref')
        for table in ('authorization_context','authorization_command_scope'):
            reject('归属及范围不可事后删除:'+table,lambda table=table:tx(c,lambda:c.execute('DELETE FROM '+table)))
        changed=M.sealed(dict(context,operations=['lookupCommand']),'context_digest')
        reject('相同context不得更换操作集合',lambda:tx(c,lambda:M.store_context(c,changed)),'authorization_context_identity')
        changed=clone(context);changed['requester']['issuer_epoch']='other';changed=M.sealed(changed,'context_digest')
        reject('上下文不可跨主体世代',lambda:tx(c,lambda:M.store_context(c,changed)),'authorization_context_owner')
        wrong=clone(original_scope);wrong['targets']=[clone(original_scope['targets'][0]),clone(original_scope['targets'][0])]
        reject('动作scope不接受重复组合',lambda:tx(c,lambda:M.store_scope(c,wrong)))
        wrong=clone(original_scope);wrong['permissions']=['device.command','auth.manage']
        reject('权限集合须按规范排序',lambda:tx(c,lambda:M.store_scope(c,wrong)),'authorization_scope_permission_order')
        legacy,old_connections,*_=T.fixture();dbs.extend(old_connections);legacy.executescript((HERE/'final-authorization.sql').read_text('utf-8'))
        tx(legacy,lambda:M.store_scope(legacy,original_scope))
        reject('旧命令不能事后补造上下文归属',lambda:tx(legacy,lambda:M.store_context(legacy,context)),'authorization_context_late_registration')
        check('授权使用的grant来自实际已受理请求',u['authorization_binding']['grant_id']=='transfer.grant' and u['authorization_binding']['grant_revision']=='1' and u['authorization_binding']['arm_generation']=='2')
        for key,value in (('grant_id','another.grant'),('grant_revision','2'),('arm_generation','3')):
            c=fork(db);bad=clone(u);bad['use_id']='bad.grant.'+key;bad['authorization_binding'][key]=value;bad=M.sealed(bad,'use_digest')
            tx(c,lambda:M.store_use(c,bad))
            reject('最终绑定不得换用自报授权:'+key,lambda:T.T.preview(c,lambda:M.planned(c,v,o,cut,pid,provider,use_ref(bad))),'authorization_current_grant')
        c=fork(db);T.E.O.execute(c,[T.E.I('cr_revocation',transfer_id='transfer',proof_body=T.E.B,audit_body=T.E.B,outbox_body=T.E.B)])
        reject('转交grant原件撤销使授权使用失效',lambda:T.T.preview(c,lambda:M.read(c,ur,v)))
        challenge=json.loads(db.execute('SELECT body FROM authorization_challenge').fetchone()[0])
        response_record=json.loads(db.execute('SELECT body FROM authorization_response').fetchone()[0])
        c=fork(db);tx(c,lambda:M.store_challenge(c,challenge));tx(c,lambda:M.store_response(c,response_record))
        check('challenge及响应重复保持原记录',c.execute('SELECT count(*) FROM authorization_challenge').fetchone()[0]==c.execute('SELECT count(*) FROM authorization_response').fetchone()[0]==1)
        changed=M.sealed(dict(challenge,sent_tick_ns='2'),'challenge_digest')
        reject('重发challenge不能刷新首次发送时间',lambda:tx(c,lambda:M.store_challenge(c,changed)),'authorization_challenge_identity')
        changed=M.sealed(dict(response_record,received_tick_ns='51'),'response_digest')
        reject('同challenge不能覆盖首次响应',lambda:tx(c,lambda:M.store_response(c,changed)),'authorization_response_identity')
        for key,value in (('credential_id','credential.other'),('audience','other.controller'),('principal_id','other.principal'),('issuer_epoch','other.epoch'),('scope_digest',M.F.digest('other.scope')),('challenge_id','other.challenge')):
            changed=clone(response_record);changed['snapshot'][key]=value;changed=M.sealed(changed,'response_digest')
            reject('响应与待决请求不符:'+key,lambda changed=changed:tx(c,lambda:M.store_response(c,changed)),'authorization_response_')
        changed=clone(response_record);changed['challenge_ref']['id']='never.sent';changed=M.sealed(changed,'response_digest')
        reject('未登记challenge的响应不可保存',lambda:tx(c,lambda:M.store_response(c,changed)),'authorization_challenge_missing')
        for name,mutate,reason in [
            ('重新填写发送tick',lambda x:x.update(challenge_sent_tick_ns='2'),'authorization_capture_ticks'),
            ('重新填写接收tick',lambda x:x.update(received_tick_ns='51'),'authorization_capture_ticks'),
            ('同主体更换凭据',lambda x:(x['authorization_binding'].update(credential_id='rotated'),x['snapshot'].update(credential_id='rotated')),'authorization_response_snapshot'),
            ('更换快照challenge',lambda x:x['snapshot'].update(challenge_id='replayed'),'authorization_response_snapshot'),
            ('仅知道response ID但摘要错误',lambda x:x['authority_evidence_ref'].update(digest=M.F.digest('fake')),'authorization_response_ref'),
            ('权威原件不存在',lambda x:x['authority_evidence_ref'].update(id='missing'),'authorization_response_missing')]:
            c=fork(db);bad=clone(u);bad['use_id']='rebound';mutate(bad);bad=M.sealed(bad,'use_digest');tx(c,lambda:M.store_use(c,bad))
            reject(name,lambda:T.T.preview(c,lambda:M.read(c,use_ref(bad),v)),reason)
        c=fork(db)
        for table in ('authorization_challenge','authorization_response'):
            reject('已捕获来源禁止删除:'+table,lambda table=table:tx(c,lambda:c.execute('DELETE FROM '+table)))
        for name,body,key in [('AuthorizationChallenge',challenge,'challenge_digest'),('AuthorityResponse',response_record,'response_digest')]:
            M.decode(name,M.raw(body),body[key],key);check('来源完整Schema和摘要:'+name)
            reject('来源重复JSON键:'+name,lambda name=name,body=body,key=key:M.decode(name,b'{"revision":"0",'+M.raw(body)[1:],body[key],key),'authorization_duplicate_key')
        for nonce in ('short','A'*64,'a'*64+'\n'):
            bad=M.sealed(dict(challenge,challenge_id=nonce),'challenge_digest')
            reject('challenge须为固定256位小写hex:'+repr(nonce),lambda bad=bad:tx(db,lambda:M.store_challenge(db,bad)))
        reject('事务外读取拒绝',lambda:M.read(db,ur,v),'authorization_transaction_required')
        for kind in ('principal','grant','credential','trust'):
            c=fork(db);tx(c,lambda:M.install_floor(c,floor(u,kind)))
            reject('撤销后不能采用旧投影:'+kind,lambda:T.T.preview(c,lambda:M.planned(c,v,o,cut,pid,provider,ur)),
                'authorization_permanent_denial' if kind in ('credential','trust') else 'authorization_revision_floor')
            check('撤销保留packet与授权历史:'+kind,c.execute('SELECT count(*) FROM ep_reply').fetchone()[0]==c.execute('SELECT count(*) FROM authorization_use').fetchone()[0]==1)
        for changes in (dict(target_id='someone.else'),dict(issuer_epoch='other.epoch'),dict(issuer_id='other.issuer')):
            c=fork(db);tx(c,lambda:M.install_floor(c,floor(u,**changes)))
            check('不同撤销命名空间不命中:'+str(changes),T.T.preview(c,lambda:M.read(c,ur,v))==auth_projection)
        c=fork(db);equal=floor(u,revision='4');tx(c,lambda:M.install_floor(c,equal))
        fresh=T.T.preview(c,lambda:M.read(c,ur,v));check('等于下界仍需当前资格且产生新切点',fresh!=auth_projection)
        reject('等于下界也不能复用旧切点',lambda:T.T.preview(c,lambda:M.planned(c,v,o,cut,pid,provider,ur)),'authorization_current_projection')
        vv,oo=clone(v),clone(o);attach(vv,oo,fresh)
        check('重选新切点可规划',len(T.T.preview(c,lambda:M.planned(c,vv,oo,cut,pid,provider,ur)))==19)
        tx(c,lambda:M.install_floor(c,equal));check('同事件重传幂等',c.execute('SELECT count(*) FROM authorization_floor_event').fetchone()[0]==1)
        changed=floor(u,revision='7');reject('同事件不同内容拒绝',lambda:tx(c,lambda:M.install_floor(c,changed)),'authorization_floor_identity')
        tx(c,lambda:M.install_floor(c,floor(u,revision='5',eid='high')));tx(c,lambda:M.install_floor(c,floor(u,revision='1',eid='low')))
        reject('乱序低下界不覆盖高下界',lambda:T.T.preview(c,lambda:M.read(c,ur,v)),'authorization_revision_floor')
        for table in ('authorization_use','authorization_floor_event'):
            reject('禁止删除:'+table,lambda table=table:tx(c,lambda:c.execute('DELETE FROM '+table)))
        c=fork(db)
        def partial_floor():
            M.install_floor(c,floor(u));raise ValueError('fault_after_floor')
        reject('撤销写后事务失败回滚',lambda:tx(c,partial_floor),'fault_after_floor')
        check('失败事务不留下半个撤销',c.execute('SELECT count(*) FROM authorization_floor_event').fetchone()[0]==0 and T.T.preview(c,lambda:M.read(c,ur,v))==auth_projection)
        # 两个相邻大整数不能经float合并；下界相等与低一位必须得到不同结果。
        c=fork(db);large=clone(u);large['use_id']='large'
        for owner in ('authorization_binding','snapshot'):large[owner]['subject_revision']='9007199254740993'
        large=M.sealed(large,'use_digest');tx(c,lambda:publish_use(c,large))
        tx(c,lambda:M.install_floor(c,floor(large,revision='9007199254740993')))
        T.T.preview(c,lambda:M.read(c,use_ref(large),v));check('大整数下界精确相等可读')
        tx(c,lambda:M.install_floor(c,floor(large,revision='9007199254740994',eid='next')))
        reject('大整数低一位拒绝',lambda:T.T.preview(c,lambda:M.read(c,use_ref(large),v)),'authorization_revision_floor')
        for name,mutate,reason in [
            ('错误audience',lambda x:x['authorization_binding'].update(audience='other'),'authorization_audience'),
            ('旧epoch',lambda x:x['authorization_binding'].update(issuer_epoch='old'),'authorization_requester'),
            ('主体修订不符',lambda x:x['snapshot'].update(subject_revision='3'),'authorization_snapshot_subject_revision'),
            ('非active',lambda x:x['snapshot'].update(state='revoked'),'authorization_permission'),
            ('缺执行权限',lambda x:x['snapshot'].update(permissions=[]),'authorization_permission'),
            ('过期等号',lambda x:x.update(authorization_before_tick_ns='52'),'authorization_window'),
            ('发送challenge后才计新鲜度',lambda x:x.update(received_tick_ns='1000001',authorization_before_tick_ns='2000000'),'authorization_window'),
            ('新clockdomain不能复用',lambda x:x['binding'].update(clock_domain_id='clock_'+'9'*64),'authorization_use_binding'),
            ('委托不能降级普通入口',lambda x:x['authorization_binding'].update(extension_instance_id='extension',extension_approval_revision='1'),'authorization_delegation_not_integrated')]:
            c=fork(db);bad=clone(u);bad['use_id']='bad';mutate(bad);bad=M.sealed(bad,'use_digest');tx(c,lambda:publish_use(c,bad))
            reject(name,lambda:T.T.preview(c,lambda:M.read(c,use_ref(bad),v)),reason)
        for b,reason in [(b' '+M.raw(u),'authorization_body_digest'),(b'{"use_id":"duplicate",'+M.raw(u)[1:],'authorization_duplicate_key')]:
            reject('严格正文:'+reason,lambda b=b:M.decode('AuthorizationUse',b,u['use_digest'],'use_digest'),reason)
        c=fork(db);late=clone(u);late.update(use_id='late',authorization_before_tick_ns='2000000',received_tick_ns='999999')
        late=M.sealed(late,'use_digest');tx(c,lambda:publish_use(c,late))
        lv=clone(v);lv.update(selected_tick_ns='1000000',sealed_tick_ns='1000000');lv=M.F.seal(lv)
        actual=T.T.preview(c,lambda:M.read(c,use_ref(late),lv))
        check('慢响应仍以发送tick计算剩余新鲜度',actual['body']['before_tick_ns']=='1000001')
        lv=M.F.seal(dict(lv,sealed_tick_ns='1000001'))
        reject('新鲜度截止等号拒绝而不从接收延长',lambda:T.T.preview(c,lambda:M.read(c,use_ref(late),lv)),'authorization_window')
        c=fork(db)
        def fill():
            for i in range(4097):M.install_floor(c,floor(u,revision='4',eid='bounded.'+str(i)))
        tx(c,fill)
        reject('撤销事件超容量保护而非截断放行',lambda:T.T.preview(c,lambda:M.read(c,ur,v)),'authorization_floor_capacity')
        c=fork(db);event=floor(u,revision='4');tx(c,lambda:M.install_floor(c,event))
        reject('不可更新已有下界',lambda:tx(c,lambda:c.execute("UPDATE authorization_floor_event SET revision_floor='00000000000000000000'")))
        # 实际文件库双连接：在封存读取事务持锁期间撤销不能越过它；提交后撤销先于下次规划。
        logdir=(ROOT/'logs').resolve();logdir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='leafseamer-auth-',dir=logdir) as directory:
            assert Path(directory).resolve().parent==logdir
            a=sqlite3.connect(str(Path(directory)/'candidate.sqlite'),isolation_level=None,timeout=0);db.backup(a)
            b=sqlite3.connect(str(Path(directory)/'candidate.sqlite'),isolation_level=None,timeout=0)
            try:
                a.execute('BEGIN IMMEDIATE');M.planned(a,v,o,cut,pid,provider,ur)
                reject('另一个writer不能越过当前封存事务',lambda:b.execute('BEGIN IMMEDIATE'),'locked')
                a.commit();tx(b,lambda:M.install_floor(b,floor(u)))
                reject('提交后下一次规划必须见撤销',lambda:tx(a,lambda:M.planned(a,v,o,cut,pid,provider,ur)),'authorization_revision_floor')
            finally:
                a.close();b.close()
        # manual会话撤销独立于组织run；这里只读实际持久授权行，不声称manual完整编码已贯通。
        mv,mo,mc=T.V.fixture();mu=use(mv);mu=M.sealed(dict(mu,received_tick_ns='50'),'use_digest')
        manual=sqlite3.connect(':memory:',isolation_level=None);dbs.append(manual)
        manual.executescript('CREATE TABLE controller_scope(singleton,authority_service_id,database_instance_id); CREATE TABLE ca_namespace(namespace_id TEXT PRIMARY KEY); CREATE TABLE ca_request_key(transport_body BLOB,namespace_id TEXT); INSERT INTO controller_scope VALUES(1,\'controller\',\'database\');'+(HERE/'final-authorization.sql').read_text('utf-8'))
        tx(manual,lambda:publish_use(manual,mu));tx(manual,lambda:M.read(manual,use_ref(mu),mv));check('manual完整会话绑定可读取')
        tx(manual,lambda:M.install_floor(manual,floor(mu,'session')))
        reject('会话撤销阻断manual使用',lambda:tx(manual,lambda:M.read(manual,use_ref(mu),mv)),'authorization_revision_floor')
        check('组织自动化不依赖人员session',all(x[0]!='session' for x in M.dependencies(u['authorization_binding'])))
        check('四个最终阻断保持',db.execute("SELECT count(*) FROM sqlite_schema WHERE name IN ('cu_ce_permit_gate','cu_ci_cancel_transmission_gate','cu_ce_transmission_commit_gate','cu_ci_cancel_commit_gate')").fetchone()[0]==4)
        check('最终issue及封存未产生',db.execute('SELECT count(*) FROM ci_issue').fetchone()[0]==db.execute('SELECT count(*) FROM fa_seal').fetchone()[0]==0)
        for c in dbs:assert not c.in_transaction and not c.execute('PRAGMA foreign_key_check').fetchone()
        check('连接事务和外键完整');return checks
    finally:
        for c in dbs:c.close()

def inputs():return list(dict.fromkeys(T.inputs()+G.SOURCES+[HERE/n for n in ('final-authorization.schema.json','final-authorization.sql','final_authorization_model.py','check_final_authorization.py','FINAL_AUTHORIZATION.md')]+[ROOT/'docs/rebirth-f04-f05-design.md',ROOT/'docs/rebirth-df04-storage-design.md']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args();target=HERE/'final-authorization-report.json'
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:assert json.loads(target.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),candidate_tables=248,local_file_two_writer_order_verified=True,
            stored_challenge_response_binding_verified=True,stored_continuation_grant_binding_verified=True,
            stored_request_context_binding_verified=True,stored_command_scope_intersection_verified=True,
            authority_authenticity_verified=False,request_context_credential_chain_verified=False,scope_evidence_verified=False,utc_validity_evidence_verified=False,full_final_issue_executed=False,
            runtime_tests_executed=0,device_tests_executed=0,disk_crash_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:target.write_bytes(M.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
