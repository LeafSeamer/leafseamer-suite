"""文件SQLite与只读回执适配的隔离验证；身份认证和领域写入为显式合成。"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import receipt_journal as J
import receipt_delivery as Q
import delivery as D
import coordinator as G
import readset as R
import typed_validators as V
import check_readset as C

ROOT=R.ROOT;H=C.H;SUITE=C.SUITE


def fixed(sdk):
    src=json.loads((ROOT/'delivery-sources.json').read_bytes());raws=H.read_fixed(sdk,src['sdk_commit'],src['inputs'])
    R.need(all(H.sha(b)==src['inputs'][p] for p,b in raws.items()),'fixed_cases')
    mp='contracts/panel-wire/contract/models.schema.json';model=H.read_fixed(sdk,src['sdk_commit'],[mp])[mp]
    return V.Contract(model,R.SELECTION),json.loads(raws['contracts/panel-http/panel-cases.json'])['cases'],src,{**src['inputs'],mp:H.sha(model)}


def run(sdk):
    contract,cases,src,inputs=fixed(sdk);checks=[];database_scenarios=0
    base=SUITE/'logs/c09-receipt-journal';base.mkdir(parents=True,exist_ok=True)
    def check(name,ok=True):R.need(ok,name);checks.append(dict(name=name,passed=True))
    def denied(name,fn,reason=None):
        try:fn()
        except (ValueError,KeyError,TypeError,sqlite3.Error) as e:check(name,reason is None or str(e)==reason)
        else:raise AssertionError(name+':未拒绝')
    with tempfile.TemporaryDirectory(prefix='db-',dir=base) as temporary:
        root=Path(temporary);writers=[];owners=[]
        def fixture(case=None,status='accepted'):
            nonlocal database_scenarios
            database_scenarios+=1;case=copy.deepcopy(case or cases[0]);intent=case['request']['intent'];identity=intent['identity'];context=C.fixture(case['method'])['context']
            binding=dict(panel_session_id=identity['panel_session_id'],panel_instance_id='panel.synthetic',document_generation=identity['document_generation'],channel_id='channel.synthetic',protocol_version='panel-channel/0.3.0-draft.1')
            request=dict(protocol_version=binding['protocol_version'],type='panel.request',public_binding=binding,channel_sequence='3',request_id=identity['request_id'],method=case['method'],target_handle='target.synthetic',resource_ref=None,payload=copy.deepcopy(intent['normalized_arguments']),activation_ref=copy.deepcopy(intent['activation_ref']))
            scope={k:identity[k] for k in ['authority_service_id','database_instance_id']}
            context.update(request_id=request['request_id'],public_binding_digest=R.digest(binding),activation_digest=R.digest(request['activation_ref']),input_digest=R.digest(request['payload']['value']),scope=scope)
            receipt=copy.deepcopy(case['unavailable']);receipt['intent_digest']=R.digest(intent)
            if status!='accepted':receipt.update(state=status,reason_code={'pending_confirmation':'needs_host_confirmation','rejected':'authority_denied','cancelled':'user_cancelled'}[status],accepted_result_ref=None,projection=None,projection_state='not_applicable')
            path=root/(str(database_scenarios)+'.db');db=sqlite3.connect(path,isolation_level=None);writers.append(db)
            db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.executescript(J.DDL)
            db.execute('INSERT INTO journal_scope VALUES(1,?)',(R.bounded(dict(selection=R.SELECTION,scope=scope)),));key=R.digest(identity)
            db.execute('BEGIN');db.execute('INSERT INTO request_origin VALUES(?,?,?)',(key,R.bounded(request),R.bounded(case['request'])));db.execute('INSERT INTO request_receipt VALUES(?,1,?)',(key,R.bounded(receipt)));db.execute('COMMIT')
            def authorize(c,r,record):return c==context and r==request and (record is None or record['invocation']==case['request'])
            reader=J.Reader(path,contract,identity,R.digest(intent),authorize)
            owner=G.Coordinator();owners.append(owner);session=owner.register(lambda:None);ledger=owner.register(lambda:None);sent=[]
            class Sink:
                def write_once(self,payload):sent.append(payload);return len(payload)
            delivery=D.Delivery(owner,contract,[session],{k:context[k] for k in D.SESSION_KEYS},binding,request['activation_ref'],Sink(),next_sequence='7')
            f=dict(db=db,path=path,reader=reader,case=case,request=request,context=context,identity=identity,receipt=receipt,key=key,authorize=authorize,owner=owner,delivery=delivery,session=session,ledger=ledger,sent=sent)
            f['read']=lambda:reader(context,request)
            f['enqueue']=lambda source=reader:Q.enqueue_status(delivery,[session,ledger],context,request,identity,source)
            f['release']=lambda ticket:delivery.release(ticket,lambda _:copy.deepcopy(context))
            return f
        def append(f,receipt):
            n=f['db'].execute('SELECT MAX(ordinal)+1 FROM request_receipt WHERE identity_key=?',(f['key'],)).fetchone()[0]
            f['db'].execute('INSERT INTO request_receipt VALUES(?,?,?)',(f['key'],n,R.bounded(receipt)))
        try:
            for case in cases:
                f=fixture(case);before=f['db'].total_changes;record=f['read']()
                check('文件原件:'+case['method'],record['invocation']==case['request'] and record['observation']['receipt']==f['receipt'])
                f['release'](f['enqueue']());frame=json.loads(f['sent'][-1]);check('真实账本进入回执出口:'+case['method'],frame['status']=='accepted' and frame['result'] is None and contract.validate('panel__Channel_Result',frame))
                check('查询没有业务写入:'+case['method'],f['db'].total_changes==before);f['owner'].close()
            confirm=next(c for c in cases if c['method']=='seamer.armRun')
            for state in ['pending_confirmation','rejected','cancelled']:
                f=fixture(confirm,state);check('持久服务状态:'+state,f['read']()['observation']['receipt']['state']==state)
            f=fixture(confirm,'pending_confirmation');old=copy.deepcopy(f['receipt']);accepted=copy.deepcopy(f['case']['unavailable']);accepted['intent_digest']=R.digest(f['case']['request']['intent'])
            db=f['reader']._connect();fired=[]
            def between(sql):
                if sql.startswith('SELECT ordinal,') and not fired:fired.append(True);append(f,accepted)
            db.set_trace_callback(between)
            try:_,rows=f['reader']._snapshot(db)
            finally:db.close()
            check('WAL并发提交不混入旧快照',fired==[True] and len(rows)==1 and J.decode(rows[0][1],65536)==old)
            check('下一次新快照观察已提交受理',f['read']()['observation']['receipt']==accepted)
            # 子进程重新打开数据库并运行同一完整Reader，非仅校验文件存在。
            probe=root/'probe.json';probe.write_bytes(H.encode(dict(path=str(f['path']),identity=f['identity'],digest=R.digest(f['case']['request']['intent']),context=f['context'],request=f['request'],expected=accepted)))
            completed=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--sdk',str(sdk),'--probe',str(probe)],capture_output=True,timeout=30)
            check('新进程读取原意图与最新回执',completed.returncode==0 and completed.stdout.strip()==b'probe_passed')
            for table in ['journal_scope','request_origin','request_receipt']:
                f=fixture();denied('禁止更新:'+table,lambda t=table:f['db'].execute('UPDATE '+t+' SET '+('body=body' if t!='request_origin' else 'invocation=invocation')))
                denied('禁止删除:'+table,lambda t=table:f['db'].execute('DELETE FROM '+t))
            f=fixture();denied('同完整身份不替换原意图',lambda:f['db'].execute('INSERT INTO request_origin VALUES(?,?,?)',(f['key'],R.bounded(f['request']),R.bounded(f['case']['request']))))
            f['db'].execute('PRAGMA recursive_triggers=OFF')
            denied('关闭递归触发器也不能REPLACE原意图',lambda:f['db'].execute('INSERT OR REPLACE INTO request_origin VALUES(?,?,?)',(f['key'],R.bounded(f['request']),R.bounded(f['case']['request']))))
            denied('关闭递归触发器也不能REPLACE作用域',lambda:f['db'].execute('INSERT OR REPLACE INTO journal_scope VALUES(1,?)',(b'{}',)))
            denied('回执序号必须连续',lambda:f['db'].execute('INSERT INTO request_receipt VALUES(?,3,?)',(f['key'],R.bounded(f['receipt']))))
            db=f['reader']._connect()
            try:denied('实际只读连接拒绝写入',lambda:db.execute('INSERT INTO request_receipt VALUES(?,2,?)',(f['key'],R.bounded(f['receipt']))))
            finally:db.close()
            missing=root/'absent.db';reader=J.Reader(missing,contract,f['identity'],R.digest(f['case']['request']['intent']),f['authorize'])
            denied('缺库不创建空账本',lambda:reader(f['context'],f['request']));check('缺库后仍不存在',not missing.exists())
            called=[];reader=J.Reader(missing,contract,f['identity'],R.digest(f['case']['request']['intent']),lambda c,r,v:called.append(v) or False)
            denied('查库前拒绝无权主体',lambda:reader(f['context'],f['request']),'journal_authorization');check('拒权未读取库或原件',called==[None] and not missing.exists())
            for label,change in [('原意图摘要',lambda x:x.update(_digest='0'*64)),('完整身份',lambda x:x['_identity'].update(issuer_epoch='other.synthetic'))]:
                f=fixture();change(f['reader'].__dict__);denied('重建读取器不能换'+label,f['read'])
            for status in ['rejected','cancelled','pending_confirmation']:
                f=fixture(confirm);r=copy.deepcopy(f['receipt']);r.update(state=status,reason_code={'rejected':'authority_denied','cancelled':'user_cancelled','pending_confirmation':'needs_host_confirmation'}[status],accepted_result_ref=None,projection_state='not_applicable');append(f,r)
                denied('重启后仍拒绝受理状态倒退:'+status,f['read'],'journal_outcome_regression')
            f=fixture();r=copy.deepcopy(f['receipt']);r['accepted_result_ref']['revision']='2';append(f,r);denied('持久受理引用不可替换',f['read'],'journal_result_changed')
            for field in ['identity','intent_digest','method','activation_ref']:
                f=fixture();r=copy.deepcopy(f['receipt'])
                if field=='identity':r[field]['issuer_epoch']='other.synthetic'
                elif field=='intent_digest':r[field]='0'*64
                elif field=='method':r[field]='seamer.getMeta' if r[field]!='seamer.getMeta' else 'controller.getMeta'
                else:r[field]['activation_id']='other.synthetic'
                append(f,r);denied('持久回执错绑:'+field,f['read'])
            for label,sql in [('版本','PRAGMA user_version=2'),('布局','CREATE TABLE extra(x INTEGER)'),('缺不可变触发器','DROP TRIGGER origin_update')]:
                f=fixture();f['db'].execute(sql);denied('未知数据库拒绝:'+label,f['read'])
            f=fixture();f['db'].execute('BEGIN EXCLUSIVE');f['db'].execute('PRAGMA user_version=2')
            try:check('未提交版本不进入读快照',f['read']()['observation']['receipt']==f['receipt'])
            finally:f['db'].execute('ROLLBACK')
            f=fixture();key='0'*64;f['db'].execute('INSERT INTO request_origin VALUES(?,?,?)',(key,R.bounded(f['request']),R.bounded(f['case']['request'])))
            f['reader']._identity['request_id']='missing.synthetic';denied('缺原身份不回显其他请求',f['read'],'journal_record_unavailable')
            f=fixture();f['reader']._authorize=lambda c,r,v:v is None
            denied('读后权限拒绝不产生回执',f['enqueue'],'journal_authorization');check('读后拒权没有输出',not f['sent'])
            f=fixture();f['db'].execute('INSERT INTO request_receipt VALUES(?,2,?)',(f['key'],b' '+R.bounded(f['receipt'])));denied('非规范原字节拒绝',f['read'],'journal_canonical')
            f=fixture()
            for _ in range(63):append(f,f['receipt'])
            check('64条历史上限可读',f['read']()['observation']['receipt']==f['receipt']);denied('第65条不可插入',lambda:append(f,f['receipt']))
            f=fixture()
            for n in range(2,65):f['db'].execute('INSERT INTO request_receipt VALUES(?,?,?)',(f['key'],n,b'x'*17000))
            denied('历史累计字节有界',f['read'],'journal_history_budget')
            f=fixture();f['db'].execute('BEGIN');append(f,f['receipt']);f['db'].execute('ROLLBACK');check('回滚不生成新回执',f['db'].execute('SELECT COUNT(*) FROM request_receipt').fetchone()[0]==1)
            f=fixture();entered=threading.Event();resume=threading.Event();result=[]
            def slow(c,r,record):
                if record is not None:entered.set();R.need(resume.wait(10),'thread_timeout')
                return f['authorize'](c,r,record)
            reader=J.Reader(f['path'],contract,f['identity'],R.digest(f['case']['request']['intent']),slow)
            def work():
                try:result.append(('ok',f['enqueue'](reader)))
                except BaseException as e:result.append(('error',str(e)))
            thread=threading.Thread(target=work);thread.start()
            try:
                R.need(entered.wait(10),'thread_timeout');f['owner'].revoke(f['ledger']);check('数据库关闭后权限核验不持有写锁',f['db'].execute('BEGIN IMMEDIATE') is not None);f['db'].execute('ROLLBACK')
            finally:resume.set()
            thread.join(15);check('实际数据库读取后撤权拒绝迟到入队',not thread.is_alive() and result==[('error','output_closed')] and not f['sent'])
            f=fixture();ticket=f['enqueue']();f['owner'].revoke(f['ledger']);denied('实际账本结果排队后撤权',lambda:f['release'](ticket),'output_closed');check('撤权没有泄漏帧',not f['sent'])
        finally:
            for owner in owners:owner.close()
            for db in writers:db.close()
    names=['receipt_journal.py','receipt-journal.sql','check_journal.py','JOURNAL.md','receipt_delivery.py','delivery.py','coordinator.py','readset.py','typed_validators.py','delivery-sources.json','check_readset.py','source/bindings.json','source/selection.json']
    paths=[ROOT/n for n in names]+[C.HELPER,SUITE/'docs/rebirth-c09-extension-design.md']
    return dict(format='panel-receipt-journal-check/1',approved=False,runtime_ready=False,all_passed=True,cases_passed=len(checks),checks=checks,database_scenarios=database_scenarios,real_process_reopen_scenarios=1,real_thread_scenarios=1,wal_snapshot_scenarios=1,methods=35,explicit_synthetic_authentication_and_domain_writer=True,production_authorization_tests_executed=0,production_output_gate_tests_executed=0,network_tests_executed=0,browser_tests_executed=0,device_tests_executed=0,domain_operation_submissions=0,sdk_commit=src['sdk_commit'],fixed_sdk_inputs=inputs,inputs={p.relative_to(SUITE).as_posix():H.sha(p.read_bytes()) for p in paths})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--report',action='store_true');parser.add_argument('--probe',type=Path);args=parser.parse_args()
    if args.probe:
        p=json.loads(args.probe.read_bytes());contract,_,_,_=fixed(args.sdk)
        def authorize(c,r,v):return c==p['context'] and r==p['request'] and (v is None or R.digest(v['invocation']['intent'])==p['digest'])
        record=J.Reader(Path(p['path']),contract,p['identity'],p['digest'],authorize)(p['context'],p['request'])
        R.need(record['observation']['receipt']==p['expected'],'probe_receipt');print('probe_passed')
    else:
        report=run(args.sdk.resolve())
        if args.report:(ROOT/'journal-report.json').write_bytes(H.encode(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ['checks','inputs','fixed_sdk_inputs']},ensure_ascii=False))
