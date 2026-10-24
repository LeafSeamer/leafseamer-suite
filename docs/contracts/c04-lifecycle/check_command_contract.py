"""公共命令类型、IPC同源与实际SQLite字段差异验收；不发送业务命令。"""
import argparse,copy,hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry,Resource
from openapi_spec_validator import validate as validate_openapi
import build_command_contract as G
import command_storage_mapping as S
import check_continuation_binding as P
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];clone=copy.deepcopy
LOCAL=['build_command_contract.py','command_storage_mapping.py','check_command_contract.py','COMMAND_CONTRACT.md',*G.build()]
def inputs():
    old=json.loads((HERE/'continuation-binding-report.json').read_bytes())
    return list(dict.fromkeys([ROOT/p for p in old['inputs']]+G.SOURCES+[HERE/'continuation-binding-report.json']+[HERE/n for n in LOCAL]))
def run():
    checks=[];dbs=[]
    def check(name,ok=True):assert ok,name;checks.append(dict(name=name,passed=True))
    def denied(name,fn):
        try:fn()
        except (ValueError,ValidationError):check(name);return
        raise AssertionError(name)
    try:
        outputs=G.build();catalog=outputs['command-contract.schema.json'];api=outputs['command-contract.openapi.json'];wire=outputs['command-contract-ipc.schema.json']
        for name,value in outputs.items():check('生成一致'+name,(HERE/name).read_bytes()==G.raw(value))
        Draft202012Validator.check_schema(catalog);Draft202012Validator.check_schema(wire);validate_openapi(api);check('Schema和OpenAPI有效')
        check('顶层字段映射完整',sum(len(v['fields']) for v in S.coverage().values())==39)
        check('公共操作完整',len(api['paths'])==10 and len(outputs['command-contract-manifest.json']['operations'])==10)
        actual={op['operationId'] for item in api['paths'].values() for op in item.values()}
        # 操作身份来自旧契约原件，下面精确检查每个入口及其认证/方法，不重命名既有操作。
        originals=[json.loads(p.read_bytes()) for p in G.SOURCES[-2:]]
        check('全部原操作保留',actual=={op['operationId'] for s in originals for item in s['paths'].values() for op in item.values()})
        for source in originals:
            for path,item in source['paths'].items():
                for method,old in item.items():
                    new=api['paths'][path][method]
                    check('认证分支保留'+old['operationId'],new['security']==old['security'])
                    check('响应码保留'+old['operationId'],set(new['responses'])==set(old['responses']))
                    check('统一版本头'+old['operationId'],any(p.get('name')=='X-LeafSeamer-Contract' and p['required'] and p['schema']=={'const':G.VERSION} for p in new['parameters']))
        for name,value in api['components']['schemas'].items():
            normalized=G.B.walk(value,lambda uri:'#/$defs/'+uri.split('/')[-1])
            check('API类型同源'+name,normalized==catalog['$defs'][name])
        registry=Registry().with_resource(G.SID,Resource.from_contents(catalog));validator=Draft202012Validator(wire,registry=registry)
        old,_,_=P.J.fixtures();frames=P.upgraded(old)
        for name,frame in frames.items():validator.validate(frame);check('IPC同源'+name)
        sd,cds,sub,chain,body=P.fixture(frames);dbs=[sd]+[x[0] for x in cds.values()]
        req=chain[1];S.validate('CommandRequest',req)
        av=Draft202012Validator({'$ref':'#/components/schemas/A__S0_CommandRequest','components':api['components']})
        av.validate(req);check('新转交请求可经公共入口')
        old_request=clone(req)
        for field in ('binding_version','authorization_mode','continuation'):old_request['automation_binding'].pop(field)
        denied('新版入口拒绝旧绑定',lambda:av.validate(old_request))
        v=clone(req);v['automation_binding']['continuation']=None;denied('新版入口拒绝丢失转交',lambda:av.validate(v))
        v=clone(req);v.update(origin='manual',automation_binding=None);v.pop('run_binding');av.validate(v);check('手动分支保留')
        v=clone(req);v['automation_binding'].update(authorization_mode='preparation',continuation=None);av.validate(v);check('准备分支保留')
        differences=S.findings(sd,sub);check('旧SQL六类差异被识别',len(differences)==6)
        check('缺持久issuer_epoch',any(x['code']=='issuer_epoch_not_persisted' for x in differences))
        er=P.M.P.R.one(sd,'execution','execution_id',chain[0]['execution_id']);sr=P.M.P.R.one(sd,'command_submission','submission_id',sub)
        denied('旧执行正文不能直接出网',lambda:S.validate('ExecutionBinding',json.loads(er['binding_body'])))
        denied('旧请求正文不能直接出网',lambda:S.validate('CommandRequest',json.loads(sr['request_body'])))
        # 新写集的合成完整原件：在持久化前构造，绝不覆盖实际库中的旧不可变正文。
        decision=P.M.P.R.one(sd,'ingress_decision','execution_id',er['execution_id']);plan=P.M.P.R.one(sd,'execution_plan_set','execution_id',er['execution_id'])
        e=clone(chain[0]);e.update(origin=dict(kind='trigger',decision_id=decision['decision_id'],decision_digest=decision['digest']),plan_digest=er['plan_digest'])
        e=P.Q.seal(e,'binding_digest');typed_er=dict(er,binding_body=P.M.C.raw(e),binding_digest=e['binding_digest'])
        r=clone(req);r['automation_binding']['execution_binding_ref']=P.M.eref(e)
        r['idempotency_key']='cmd_'+P.Q.digest(dict(execution_id=e['execution_id'],step_id=sr['step_id'])).split(':')[1]
        typed_sr=dict(sr,issuer_id='synthetic-issuer',issuer_epoch='synthetic-epoch',request_epoch='synthetic-request-epoch',idempotency_key=r['idempotency_key'],request_body=P.M.C.raw(r),request_digest=P.Q.digest(P.M.content(r)))
        key=dict(target_scope=dict(authority_service_id=sr['target_authority'],database_instance_id=sr['target_database']),**{k:typed_sr[k] for k in S.KEY if k!='target_scope'})
        old_api=originals[0]
        ov=Draft202012Validator({'$ref':'#/components/schemas/S0_RequestKey','components':old_api['components']})
        denied('旧API范围拒绝实际带点库名',lambda:ov.validate(key))
        S.validate('RequestKey',key);check('新版API范围承载实际库名')
        bad=clone(key);bad['idempotency_key']=sr['idempotency_key'];denied('旧摘要格式键不能作为新请求键',lambda:S.validate('RequestKey',bad))
        for invalid in ('bad\n','x/y','x'*129):
            bad=clone(key);bad['target_scope']['database_instance_id']=invalid
            denied('新版scope仍拒非法值'+repr(invalid),lambda bad=bad:S.validate('RequestKey',bad))
        rows=dict(execution=typed_er,submission=typed_sr,scope=e['scope'],decision=decision,plan=plan,
            transfer=clone(chain[6]['request']),adoption=clone(chain[6]['adoption']),receipts=clone(chain[6]['receipts']))
        check('完整新写集列正文一致',S.verify_originals(e,r,key,rows)=='typed_projection_valid')
        bad=clone(rows);bad['execution']=er;denied('禁止将合成正文嫁接旧执行行',lambda:S.verify_originals(e,r,key,bad))
        bad=clone(rows);bad['submission']=sr;denied('禁止将合成请求嫁接旧提交行',lambda:S.verify_originals(e,r,key,bad))
        for field in S.KEY:
            if field=='target_scope':continue
            bad=clone(rows);bad['submission'][field]='wrong'
            denied('请求身份错列'+field,lambda bad=bad:S.verify_originals(e,r,key,bad))
        for field in ('execution_id','run_id','arm_generation','plan_digest','binding_digest'):
            bad=clone(rows);bad['execution'][field]='wrong';denied('执行错列'+field,lambda bad=bad:S.verify_originals(e,r,key,bad))
        for field in ('binding_digest','plan_digest'):
            bad=clone(e);bad[field]=chain[0][field];denied('不可借用旧合成摘要'+field,lambda bad=bad:S.verify_originals(bad,r,key,rows))
        bad=clone(rows);bad['decision']['digest']=P.Q.digest('wrong');denied('决定原件错绑',lambda:S.verify_originals(e,r,key,bad))
        bad=clone(rows);bad['plan']['plan_body']=b'{}';denied('完整计划正文错绑',lambda:S.verify_originals(e,r,key,bad))
        for field in r['automation_binding']['continuation']:
            wrong=clone(r);wrong['automation_binding']['continuation'][field]['digest']=P.Q.digest('forged')
            bad=clone(rows);bad['submission'].update(request_body=P.M.C.raw(wrong),request_digest=P.Q.digest(P.M.content(wrong)))
            denied('请求与SQL同改摘要仍拒错原件'+field,lambda wrong=wrong,bad=bad:S.verify_originals(e,wrong,key,bad))
        changed=clone(r);changed['correlation_id']='another';check('运输字段不入内容摘要',P.Q.digest(P.M.content(changed))==typed_sr['request_digest'])
        changed['parameters']['correlation_id']='business';check('嵌套同名字段仍入摘要',P.Q.digest(P.M.content(changed))!=typed_sr['request_digest'])
        check('旧库保持原字节',P.M.P.R.one(sd,'execution','execution_id',er['execution_id'])==er and P.M.P.R.one(sd,'command_submission','submission_id',sub)==sr)
        for db in dbs:check('外键完整'+str(len(checks)),not db.execute('PRAGMA foreign_key_check').fetchall())
        return checks,differences
    finally:
        for db in dbs:db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');p.add_argument('--check-report',action='store_true');a=p.parse_args()
    path=HERE/'command-contract-report.json';hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs()}
    if a.check_report:
        assert json.loads(path.read_bytes())['inputs']==hashes
        print(json.dumps(dict(all_passed=True,matched_bindings=len(hashes))))
    else:
        checks,differences=run();report=dict(all_passed=True,approved=False,cases_passed=len(checks),public_operations=10,ipc_frames=52,
            storage_migrated=False,sdk_runtime_generated=False,runtime_tests_executed=0,device_tests_executed=0,
            checks=checks,storage_findings=differences,field_mapping=S.coverage(),inputs=hashes)
        if a.report:path.write_bytes(G.raw(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('checks','inputs','field_mapping','storage_findings')}))
