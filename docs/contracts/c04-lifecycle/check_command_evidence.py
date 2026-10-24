"""已持久固定证据集合与实际HMAC游标检查；提供者和时间为合成输入。"""
import argparse,copy,hashlib,json,sqlite3
from jsonschema.exceptions import ValidationError
import check_typed_command_view as T
import command_evidence_model as E
M=E.M;R=M.R;P=M.P;I=M.I;SC=T.SC;HERE=T.HERE;ROOT=T.ROOT

def fixture():
    d,cds,items,c=T.fixture();item=items[0];cd=item[0];a=M.decide(*item);command=a['command_ref']['object_id']
    auth=T.reader(item);auth['permissions']=['command.evidence.read'];auth['cursor_subject']=dict(issuer_id='viewer',issuer_epoch='viewer.epoch',principal_id='viewer.subject',session_id='viewer.session',authorization_revision='1')
    clock=dict(verified=True,now_tick='100',clock_domain_id='synthetic.clock',descriptor_digest=M.digest('synthetic.clock'))
    keys=dict(available=True,active_key_id='synthetic_1',keys={'synthetic_1':bytes(range(32))},ttl_ns='50',max_snapshot_members=32)
    return d,cds,item,command,auth,clock,keys

def decision(command,scope,policy,name):
    body=dict(evidence_id='decision.'+name,command_id=command,scope=scope,kind='failure',policy_ref=policy['completion_policy_ref'],retry_policy_ref=None,
        attempt_ids=[],achieved=None,effect_status='not_sent',resolved_outcome=None)
    M.V.seal(body,'evidence_digest')
    view=dict(scope=scope,command_id=command,kind='decision',source_ref=dict(id=body['evidence_id'],revision='1',digest=body['evidence_digest']),body=body)
    return M.V.seal(view,'view_digest')

def append(db,command,names,*,fail_after=None,omit=None,preview=False,proof_patch=None):
    """合成生命周期生产者夹具；只证明投影装配，不把采样当作动作失败判定。"""
    db.execute('BEGIN IMMEDIATE');writes=[]
    try:
        current=R.one(db,'cm_latest','command_id',command);before=json.loads(current['state_body']);revision=str(int(before['revision'])+1)
        policy=json.loads(R.one(db,'cm_policy','command_id',command)['policy_body']);state=dict(before,revision=revision);op=command+'_observe_'+revision
        views=[decision(command,M.C.scope(db),policy,n) for n in names];sd=M.digest(state)
        prior=json.loads(P.rows(db,'SELECT record_body FROM cv_history WHERE command_id=? ORDER BY revision DESC LIMIT 1',(command,))[0]['record_body'])
        projection={k:prior[k] for k in ('attempts','completion','cancellation')}
        proof=dict(authorized=True,originals_verified=True,projection_verified=True,redaction_verified=True,provider_ref='synthetic_projection',state_ref=M.V.state_ref(state),
            view_digests=[v['view_digest'] for v in views],projection=projection,projection_digest=M.digest(projection),max_snapshot_members=32)
        proof.update(proof_patch or {})
        def execute(parts):
            for sql,args in parts:
                idx=len(writes);writes.append((sql,args))
                if idx!=omit:db.execute(sql,args)
                if idx==fail_after:raise RuntimeError('injected')
        for v in views:
            b=v['body'];vid=b['evidence_id']+'_validation'
            execute([I('cm_validation',validation_id=vid,command_id=command,purpose=b['kind'],subject_id=b['evidence_id'],subject_digest=b['evidence_digest'],policy_ref=policy['completion_policy_ref']['id'],provider_ref='synthetic_decision',source_body=M.raw(b),receipt_body=b'{"synthetic":true}'),
                I('cm_decision',evidence_id=b['evidence_id'],command_id=command,kind=b['kind'],achieved=None,effect_status=b['effect_status'],retry_policy_ref=None,resolved_outcome=None,validation_id=vid,evidence_digest=b['evidence_digest'],evidence_body=M.raw(b))])
        execute([I('cm_validation',validation_id=op+'_validation',command_id=command,purpose='transition',subject_id=op,subject_digest=sd,policy_ref=policy['completion_policy_ref']['id'],provider_ref='synthetic_state',source_body=M.raw(state),receipt_body=M.raw(proof)),
            I('cm_revision',command_id=command,revision=M.U(revision),operation_id=op,kind='observe',previous_revision=current['revision'],previous_digest=current['state_digest'],state_digest=sd,transition_digest=sd,
                phase=state['phase'],outcome=state['outcome'],effect_status=state['effect_status'],resource_status=state['resource_status'],paused_latched=0,terminal_revision=None,resolution_id=None,decision_id=None,validation_id=op+'_validation',state_body=M.raw(state))])
        execute(E.evidence_steps(db,command,revision,views,proof))
        # 内部验证可读未提交完整投影，公共reader仍禁止使用writer事务输出。
        M.complete_record(db,P.rows(db,'SELECT * FROM cv_record WHERE command_id=? AND revision=?',(command,M.U(revision)))[0])
        execute([I('cm_commit',operation_id=op,command_id=command,revision=M.U(revision),audit_body=b'{}',outbox_id=op+'_event',outbox_body=b'{}')])
        assert not db.execute('PRAGMA foreign_key_check').fetchone()
        if preview:db.rollback();return writes
        db.commit();return views
    except BaseException:db.rollback();raise

def run():
    checks=[];dbs=[]
    def check(n,v=True):assert v,n;checks.append(dict(name=n,passed=True))
    def fresh():
        d,cds,item,cmd,a,c,k=fixture();dbs.extend([d]+[v[0] for v in cds.values()]);return item[0],cmd,a,c,k
    def denied(n,db,fn,reason=None):
        before=SC.snapshot(db)
        try:fn()
        except (ValueError,RuntimeError,sqlite3.IntegrityError,ValidationError,IndexError) as err:
            if reason:assert reason in str(err),(n,str(err))
            check(n,SC.snapshot(db)==before and not db.in_transaction);return
        raise AssertionError(n)
    try:
        d,cmd,a,c,k=fresh();before=SC.snapshot(d);empty=E.page(d,cmd,'1',2,a,c,k)
        check('空快照不发游标',empty['total']=='0' and empty['items']==[] and empty['next_cursor'] is None and SC.snapshot(d)==before)
        writes=append(d,cmd,['c','a','b'],preview=True)
        for i in range(len(writes)):
            denied('证据发布逐写异常'+str(i),d,lambda i=i:append(d,cmd,['c','a','b'],fail_after=i),'injected')
            denied('证据发布漏写'+str(i),d,lambda i=i:SC.execute(d,writes[:i]+writes[i+1:]))
        for flag in ('authorized','originals_verified','projection_verified','redaction_verified'):
            denied('缺提供者资格'+flag,d,lambda flag=flag:append(d,cmd,['a'],proof_patch={flag:False}),'publication_authority')
        denied('投影准入超额不截断',d,lambda:append(d,cmd,['a','b','c'],proof_patch=dict(max_snapshot_members=2)),'snapshot_capacity')
        views=append(d,cmd,['c','a','b']);before=SC.snapshot(d);first=E.page(d,cmd,'2',2,a,c,k)
        check('按持久清单排序',first['total']=='3' and [v['source_ref']['id'] for v in first['items']]==['decision.a','decision.b'])
        check('页摘要与Schema',M.V.valid_digest(first,'page_digest'));M.validate('EvidencePage',first)
        check('首屏只读',SC.snapshot(d)==before);token=first['next_cursor'];claims=E.decode(token,k['keys'])
        check('游标无密钥及原始提供者正文',set(claims)=={'version','contract_version','scope','command_id','state_ref','snapshot_ref','subject','limit','clock_domain_id','descriptor_digest','key_id','issued_tick','expires_tick','offset'})
        # 两页之间又有新提交，旧游标仍固定旧修订，不混入新证据。
        append(d,cmd,['d']);later=E.page(d,cmd,'2',2,a,dict(c,now_tick='125'),k,token)
        check('旧末页不混新事实',later['total']=='3' and [v['source_ref']['id'] for v in later['items']]==['decision.c'] and later['next_cursor'] is None)
        freshpage=E.page(d,cmd,'3',64,a,c,k);check('新修订包含完整集合',freshpage['total']=='4' and len(freshpage['items'])==4)
        check('旧空快照不被补写',E.page(d,cmd,'1',2,a,c,k)==empty)
        check('单条原件读取',E.single(d,cmd,'decision.a','1',a)==next(v for v in views if v['source_ref']['id']=='decision.a'))
        before=SC.snapshot(d);check('重读旧页零写',E.page(d,cmd,'2',2,a,c,k,token)==later and SC.snapshot(d)==before)
        for patch,label in [(dict(permissions=['command.read']),'仅命令读权不足'),(dict(authenticated=False),'认证撤销'),(dict(authorization_current=False),'授权撤销'),(dict(response_authorized=False),'响应前失权'),(dict(paired=False),'服务配对撤销')]:
            denied(label,d,lambda patch=patch:E.page(d,cmd,'2',2,dict(a,**patch),c,k,token))
        for field in a['cursor_subject']:
            other=copy.deepcopy(a);other['cursor_subject'][field]='2' if field=='authorization_revision' else 'other'
            denied('游标主体错绑'+field,d,lambda other=other:E.page(d,cmd,'2',2,other,c,k,token),'cursor_binding')
        denied('错State修订不能拼页',d,lambda:E.page(d,cmd,'3',2,a,c,k,token),'cursor_binding')
        denied('错limit不能续页',d,lambda:E.page(d,cmd,'2',1,a,c,k,token),'cursor_binding')
        for field in ('clock_domain_id','descriptor_digest'):
            denied('换时钟域'+field,d,lambda field=field:E.page(d,cmd,'2',2,a,dict(c,**{field:'other'}),k,token),'cursor_binding')
        for now in ('99','150','151'):
            denied('游标时间边界'+now,d,lambda now=now:E.page(d,cmd,'2',2,a,dict(c,now_tick=now),k,token),'snapshot_gone')
        for bad in (token[:-2]+'AA','not.valid','a'*4097):
            denied('游标格式或认证损坏'+str(len(bad)),d,lambda bad=bad:E.page(d,cmd,'2',2,a,c,k,bad))
        forged=E.sign(dict(claims,offset='999'),k['keys']['synthetic_1'])
        denied('即使签名有效也拒越界offset',d,lambda:E.page(d,cmd,'2',2,a,c,k,forged),'cursor_offset')
        rotated=dict(k,active_key_id='synthetic_2',keys=dict(k['keys'],synthetic_2=bytes(range(32,64))))
        check('轮换保留旧验证键',E.page(d,cmd,'2',2,a,c,rotated,token)==later)
        denied('撤掉旧键不降级匿名游标',d,lambda:E.page(d,cmd,'2',2,a,c,dict(rotated,keys={'synthetic_2':bytes(range(32,64))}),token),'cursor_key_unavailable')
        short=E.page(d,cmd,'3',1,a,c,k);nextpage=E.page(d,cmd,'3',1,a,dict(c,now_tick='140'),k,short['next_cursor'])
        check('逐页不延长有效期',E.decode(nextpage['next_cursor'],k['keys'])['expires_tick']=='150')
        for limit in (0,65,True,1.0):denied('limit严格范围'+str(limit),d,lambda limit=limit:E.page(d,cmd,'2',limit,a,c,k),'page_limit')
        denied('读取总集超额不截尾',d,lambda:E.page(d,cmd,'2',2,a,c,dict(k,max_snapshot_members=2)),'snapshot_capacity')
        denied('未知证据不跨命令查找',d,lambda:E.single(d,cmd,'decision.missing','1',a),'not_found')
        row=R.one(d,'cv_evidence','evidence_id','decision.a')
        for key,value in [('source_digest',M.digest('wrong')),('view_digest',M.digest('wrong')),('source_body',b'{}')]:
            try:E.evidence(dict(row,**{key:value}),a['scope'],cmd)
            except ValueError:check('原件损坏拒绝'+key)
            else:raise AssertionError(key)
        big=dict(c,now_tick='9007199254740993');large=E.page(d,cmd,'3',1,a,big,k)
        check('时间超过double精度仍精确',E.decode(large['next_cursor'],k['keys'])['expires_tick']=='9007199254741043')
        for n,db in enumerate(dbs):check('外键完整'+str(n),not db.execute('PRAGMA foreign_key_check').fetchone())
        return checks
    finally:
        for d in dbs:d.close()

def inputs():return list(dict.fromkeys(T.inputs()+[HERE/n for n in ('typed-command-view-report.json','command_evidence_model.py','check_command_evidence.py','COMMAND_EVIDENCE.md')]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()};path=HERE/'command-evidence-report.json'
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==hashes;print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks=run();r=dict(all_passed=True,approved=False,cases_passed=len(checks),production_clearance=False,synthetic_lifecycle_producer=True,runtime_tests_executed=0,device_tests_executed=0,checks=checks,inputs=hashes)
        if a.report:path.write_bytes(T.G.C.raw(r))
        print(json.dumps({k:v for k,v in r.items() if k not in ('checks','inputs')}))
