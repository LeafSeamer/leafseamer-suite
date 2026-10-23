"""协议结构、真实内存SQL投影及撤回对接；没有HTTP或真实身份提供者。"""
import argparse,copy,hashlib,json,sqlite3,subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from openapi_spec_validator import validate as validate_openapi
import continuation_protocol_model as M
import check_continuation_trigger as T
G=M.G;C=M.C;Q=M.M;R=M.R;SC=T.SC
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
INPUTS=list(dict.fromkeys(T.INPUTS+[HERE/n for n in ('build_continuation_protocol.py','continuation_protocol_model.py','check_continuation_protocol.py',
    'CONTINUATION_PROTOCOL.md',*G.build())]+[HERE.parent/p for p in ('c04-preparation/preparation.schema.json','c02-admission/admission.schema.json','c05-protection/protocol.schema.json')]))
def auth(q,target,peer=None):
    return dict(mtls_verified=True,pairing_current=True,server_scope=target,allowed_origins=[q['origin_scope']],peer_scope=peer or q['origin_scope'],
        permissions=[r[5] for r in G.ROUTES],read_authorized=True,response_authorized=True,storage_readable=True,namespace_current=True,approval_current=True,
        namespace_binding=dict(request_epoch=q['request_epoch'],**q['actor'],issuer_epoch='issuer.1'),approval_actor=dict(**q['actor'],issuer_epoch='issuer.1'))
def key(q,target):return dict(protocol_version=G.VERSION,identity=M.identity(q,target))

def run():
    checks=[];dbs=[]
    def check(n,value=True):assert value,n;checks.append(dict(name=n,passed=True))
    def denied(n,fn):
        try:fn()
        except (ValueError,ValidationError,sqlite3.IntegrityError):check(n);return
        raise AssertionError(n+':应拒绝')
    def track(values):dbs.append(values[0]);dbs.extend(cd for cd,_ in values[3].values());return values
    try:
        outputs=G.build();d=outputs['continuation-protocol.schema.json']['$defs']
        for n in ('Request','Receipt','Adoption','Scope','Ref'):check('旧原件形状不变'+n,d[n]==G.B.schema()['$defs'][n])
        for name,value in outputs.items():
            check('生成一致'+name,(HERE/name).read_bytes()==G.raw(value))
            if name.endswith('openapi.json'):
                validate_openapi(value);check('OpenAPI完整校验'+name)
                for path,item in value['paths'].items():
                    op=item['post'];check('mTLS及版本头'+op['operationId'],op['security']==[{'InternalMTLS':[]}] and op['parameters'][0]['schema']['const']==G.VERSION)
                    check('禁止缓存'+op['operationId'],all(r['headers']['Cache-Control']['schema']['const']=='no-store' for r in op['responses'].values()))
                    for status,response in op['responses'].items():
                        target=response['content']['application/json']['schema']['$ref'].split('/')[-1]
                        check('响应Schema存在'+op['operationId']+status,target in value['components']['schemas'])
            else:Draft202012Validator.check_schema(value);check('具名Schema有效')
        sd,q,s,cds,ctx=track(T.T.fixture(seamer_factory=T.G.seamer_sql,controller_factory=T.G.controller_sql))
        cd,cc=next(iter(cds.values()));target=q['targets'][0]['controller_scope'];sa=auth(q,q['origin_scope']);ca=auth(q,target)
        body=dict(protocol_version=G.VERSION,target_scope=target,request=q)
        check('配对Seamer可请求签发',M.validate_issue(body,ca,'controller')==q)
        sb=dict(body,target_scope=q['origin_scope']);check('同源生命周期可登记',M.validate_issue(sb,sa,'seamer')==q)
        for field,value in [('mtls_verified',False),('pairing_current',False),('permissions',[]),('read_authorized',False),('response_authorized',False),
            ('peer_scope',dict(authority_service_id='other',database_instance_id='other')),('allowed_origins',[]),('namespace_current',False),('approval_current',False)]:
            denied('签发身份失败'+field,lambda field=field,value=value:M.validate_issue(body,dict(ca,**{field:value}),'controller'))
        bad=copy.deepcopy(ca);bad['approval_actor']['issuer_epoch']='issuer.2'
        denied('同名人员不同issuer_epoch不得混用',lambda:M.validate_issue(body,bad,'controller'))
        bad=copy.deepcopy(ca);bad['namespace_binding']['request_epoch']='other'
        denied('旧请求域不能猜配',lambda:M.validate_issue(body,bad,'controller'))
        before=SC.snapshot(sd);empty=M.lookup(sd,'Seamer',key(q,q['origin_scope']),sa)
        check('未登记查原无写',empty==dict(state='not_found',record=None) and before==SC.snapshot(sd))
        C.register(sd,q,s);registered=M.lookup(sd,'Seamer',key(q,q['origin_scope']),sa)['record']
        check('登记后回执与采用为空',registered['receipts']==[] and registered['adoption'] is None and registered['finish'] is None)
        a,receipts=T.T.issued(sd,q,s,cds)
        cr=M.lookup(cd,'Controller',key(q,target),ca)['record'];sr=M.lookup(sd,'Seamer',key(q,q['origin_scope']),sa)['record']
        check('两Controller收齐但未采用',len(sr['receipts'])==2 and sr['adoption'] is None and sr['finish'] is None)
        C.adopt(sd,q,a,s,cds);ad=M.lookup(sd,'Seamer',key(q,q['origin_scope']),sa)['record']
        check('采用不冒充R5',ad['adoption']==a and ad['finish'] is None)
        C.finish(sd,q,s,cds);finished=M.lookup(sd,'Seamer',key(q,q['origin_scope']),sa)['record']
        check('R5来自实际seal原件',finished['finish']['commit_id']==q['transfer_id']+'.r5' and finished['qualification']=='not_asserted')
        values={'IssueInput':body,'LookupInput':key(q,target),'ReceiptInput':dict(protocol_version=G.VERSION,target_scope=q['origin_scope'],receipt=receipts[0]),
            'AdoptionInput':dict(protocol_version=G.VERSION,target_scope=q['origin_scope'],adoption=a),
            'FinishInput':dict(protocol_version=G.VERSION,identity=M.identity(q,q['origin_scope']),adoption_ref=M.adoption_ref(a)),
            'ControllerRecord':cr,'SeamerRecord':finished,'ControllerLookup':dict(state='found',record=cr),'SeamerLookup':dict(state='found',record=finished)}
        values['ReceiptAck']=M.receipt_ack(q,receipts[0])
        check('Controller回执ACK不携完整运行记录',set(values['ReceiptAck'])=={'protocol_version','identity','controller_scope','receipt_ref','receipt_state','activation'})
        for op,kind in [('observeContinuationReceipt','ReceiptInput'),('adoptContinuation','AdoptionInput'),('finishContinuation','FinishInput')]:
            caller=auth(q,q['origin_scope'],target) if kind=='ReceiptInput' else sa
            check('写输入实际原件绑定'+kind,M.validate_seamer_input(sd,op,values[kind],caller,cd)==q)
            bad=copy.deepcopy(values[kind])
            if kind=='FinishInput':bad['adoption_ref']['digest']=Q.digest('other')
            elif kind=='AdoptionInput':bad['adoption']['receipt_refs'].pop();bad['adoption']=Q.seal(bad['adoption'],'adoption_digest')
            else:bad['receipt']['receipt_id']='forged';bad['receipt']=Q.seal(bad['receipt'],'receipt_digest')
            denied('写输入重摘要错绑'+kind,lambda op=op,bad=bad,caller=caller:M.validate_seamer_input(sd,op,bad,caller,cd))
        for name,value in values.items():
            M.validate(name,value);check('正常形状'+name)
            for field in value:
                bad={k:v for k,v in value.items() if k!=field};denied('缺必需字段'+name+'.'+field,lambda name=name,bad=bad:M.validate(name,bad))
            denied('拒绝多余可信标志'+name,lambda name=name,value=value:M.validate(name,dict(value,authorized=True)))
        for state in ('not_found','indeterminate'):
            denied('未知结果不得携原件'+state,lambda state=state:M.validate('SeamerLookup',dict(state=state,record=finished)))
        bad=copy.deepcopy(finished);bad['adoption']=None;denied('R5无采用',lambda:M.validate_record('Seamer',bad))
        denied('请求协议版本不降级',lambda:M.validate('IssueInput',dict(body,protocol_version='old')))
        denied('非法目标scope不被接受',lambda:M.validate_issue(dict(body,target_scope=dict(target,database_instance_id='other')),ca,'controller'))
        for field in ('execution_id','adoption_digest','commit_body_digest'):
            bad=copy.deepcopy(finished);bad['finish'][field]='wrong' if field=='execution_id' else Q.digest('wrong')
            denied('R5错绑'+field,lambda bad=bad:M.validate_record('Seamer',bad))
        bad=copy.deepcopy(finished);bad['receipts'].pop();denied('采用后少一回执',lambda:M.validate_record('Seamer',bad))
        bad=copy.deepcopy(finished);bad['receipts'].reverse();denied('回执顺序',lambda:M.validate_record('Seamer',bad))
        before=SC.snapshot(cd);bad=key(q,target);bad['identity']['request_digest']=Q.digest('other')
        denied('同transfer错摘要冲突',lambda:M.lookup(cd,'Controller',bad,ca));check('冲突查询无写',before==SC.snapshot(cd))
        check('存储不可读只返回不确定',M.lookup(cd,'Controller',key(q,target),dict(ca,storage_readable=False))==dict(state='indeterminate',record=None))
        denied('历史读取仍要求当前权限',lambda:M.lookup(cd,'Controller',key(q,target),dict(ca,permissions=[])))
        SC.execute(cd,[T.I('cr_revocation',transfer_id=q['transfer_id'],proof_body=T.AT.B,audit_body=T.AT.B,outbox_body=T.AT.B)])
        check('撤回仍可查询完全相同历史',M.lookup(cd,'Controller',key(q,target),ca)['record']==cr)
        notice=M.notice(sd,cd,q['transfer_id']);na=auth(q,q['origin_scope'],target);M.validate('WithdrawalNotice',notice)
        before=SC.snapshot(sd)
        denied('其他Controller不能代报撤回',lambda:M.receive_withdrawal(sd,cd,notice,dict(na,peer_scope=q['targets'][1]['controller_scope']),ctx))
        bad=copy.deepcopy(notice);bad['revocation_ref']['digest']=Q.digest('forged');bad=Q.seal(bad,'notice_digest')
        denied('重新摘要的伪造撤回不得采用',lambda:M.receive_withdrawal(sd,cd,bad,na,ctx));check('拒绝撤回无写',before==SC.snapshot(sd))
        ack=M.receive_withdrawal(sd,cd,notice,na,ctx);check('撤回ack不冒充保护完成',ack['protection_completion']=='not_asserted')
        before=SC.snapshot(sd);check('重复通知同ack且无额外扣账',M.receive_withdrawal(sd,cd,notice,na,ctx)==ack and before==SC.snapshot(sd))
        check('撤回后历史R5不变',M.lookup(sd,'Seamer',key(q,q['origin_scope']),sa)['record']==finished)
        # 普通命令绑定从上一轮完整参考链的实际原件产生，不能把内部registration当公共授权。
        sd,q,s,cds,ctx=track(T.fixture());ex=T.start(sd,ctx);sub=T.submitted(sd,ex,'step.0',ctx);binding=M.command_binding(sd,sub)
        check('新命令绑定旧恢复之外execution',binding['execution_id']!=q['recovery_execution_id'])
        check('公共投影不泄露内部registration', 'registration_id' not in binding)
        check('grant引用显式转换',M.public_ref(binding['grant_ref'],'grant')['object_id']==binding['grant_ref']['id'])
        denied('不能猜引用类型',lambda:M.public_ref(binding['grant_ref'],'command'))
        for name,value in [('CommandGrantBinding',binding),('WithdrawalNotice',notice),('WithdrawalAck',ack)]:
            M.validate(name,value);check('新增引用正常'+name)
            for field in value:
                bad={k:v for k,v in value.items() if k!=field};denied('新增引用缺字段'+name+field,lambda name=name,bad=bad:M.validate(name,bad))
        check('旧公共命令尚未冒充已归并','continuation' not in json.loads((HERE.parent/'c05-protection/protocol.schema.json').read_bytes())['$defs']['CommandRequest']['properties'])
        for i,db in enumerate(dbs):check('外键完整'+str(i),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks
    finally:
        for db in dbs:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    path=HERE/'continuation-protocol-report.json';bindings={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in INPUTS}
    if a.check_report:assert json.loads(path.read_bytes())['inputs']==bindings;print(json.dumps(dict(all_passed=True,matched_bindings=len(bindings))))
    else:
        checks=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),http_tests_executed=0,real_auth_tests_executed=0,device_tests_executed=0,checks=checks,inputs=bindings)
        if a.report:path.write_bytes(G.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs')}))
