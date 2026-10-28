"""面板回执候选账本的只读快照适配；不创建数据库或提交领域操作。"""
import copy
import json
from pathlib import Path
import sqlite3
import readset as R
import typed_validators as V

DDL=(R.ROOT/'receipt-journal.sql').read_text(encoding='utf8')
LAYOUT_QUERY="SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
_layout=sqlite3.connect(':memory:')
try:
    _layout.executescript(DDL);LAYOUT=_layout.execute(LAYOUT_QUERY).fetchall()
finally:_layout.close()


def decode(raw,limit):
    R.need(type(raw) is bytes and 0<len(raw)<=limit,'journal_budget')
    value=json.loads(raw);R.need(R.bounded(value,limit)==raw,'journal_canonical');return value


class Reader:
    def __init__(self,path,contract,identity,intent_digest,authorize):
        path=Path(path)
        R.need(path.is_absolute() and type(contract) is V.Contract and callable(authorize),'journal_reader')
        R.need(contract.validate('panel__Channel_RequestIdentity',identity),'request_identity_schema')
        R.need(type(intent_digest) is str and len(intent_digest)==64 and all(c in '0123456789abcdef' for c in intent_digest),'intent_digest')
        self._path=path;self._contract=contract;self._identity=copy.deepcopy(identity);self._digest=intent_digest;self._authorize=authorize

    def _connect(self):
        # 不使用immutable=1：必须观察WAL提交；mode=ro防止缺库时创建空库。
        db=sqlite3.connect(self._path.as_uri()+'?mode=ro',uri=True,timeout=0,isolation_level=None)
        try:
            db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF');return db
        except BaseException:
            db.close();raise

    def _snapshot(self,db):
        db.execute('BEGIN')
        try:
            R.need(db.execute('PRAGMA application_id').fetchone()[0]==1280528970 and db.execute('PRAGMA user_version').fetchone()[0]==1,'journal_version')
            R.need(db.execute(LAYOUT_QUERY).fetchall()==LAYOUT,'journal_layout')
            scope=db.execute('SELECT CASE WHEN length(body)<=4096 THEN body END FROM journal_scope WHERE singleton=1').fetchone()
            expected=dict(selection=V.FIXED_SELECTION,scope={k:self._identity[k] for k in ['authority_service_id','database_instance_id']})
            R.need(scope is not None and decode(scope[0],4096)==expected,'journal_scope')
            key=R.digest(self._identity)
            origin=db.execute('SELECT CASE WHEN length(request)<=65536 THEN request END,CASE WHEN length(invocation)<=65536 THEN invocation END FROM request_origin WHERE identity_key=?',(key,)).fetchone()
            R.need(origin is not None,'journal_record_unavailable')
            rows=db.execute('SELECT ordinal,CASE WHEN length(body)<=65536 THEN body END FROM request_receipt WHERE identity_key=? ORDER BY ordinal LIMIT 65',(key,)).fetchall()
            R.need(1<=len(rows)<=64 and all(type(row[1]) is bytes for row in rows) and sum(len(row[1]) for row in rows)<=1048576,'journal_history_budget')
            db.execute('COMMIT');return origin,rows
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise

    def __call__(self,current,request):
        R.bounded(current);R.bounded(request,65536);current=copy.deepcopy(current);request=copy.deepcopy(request)
        # 查询权先于库是否存在；读取后再次核验原件关联及当前权利。
        R.need(self._authorize(copy.deepcopy(current),copy.deepcopy(request),None) is True,'journal_authorization')
        db=self._connect()
        try:origin,rows=self._snapshot(db)
        finally:db.close()
        stored,invocation=decode(origin[0],65536),decode(origin[1],65536)
        R.need(R.bounded(stored)==R.bounded(request) and self._contract.validate('panel__Channel_Request',stored),'journal_request')
        R.need(self._contract.validate('panel__Service_Invocation',invocation),'invocation_schema')
        intent=invocation['intent'];identity=self._identity
        R.need(intent['identity']==identity and R.digest(intent)==self._digest,'journal_origin')
        R.need(current['scope']=={k:identity[k] for k in ['authority_service_id','database_instance_id']} and
            identity['request_id']==request['request_id'] and identity['panel_session_id']==request['public_binding']['panel_session_id'] and identity['document_generation']==request['public_binding']['document_generation'],'journal_identity')
        R.need(intent['method']==request['method'] and intent['normalized_arguments']==request['payload'] and intent['activation_ref']==request['activation_ref'],'journal_intent')
        for name in ['delegation_ref','target_ref']:
            if intent[name] is not None:R.need(all(intent[name][k]==identity[k] for k in ['authority_service_id','database_instance_id']),'journal_scope')
        previous=None
        for n,(ordinal,raw) in enumerate(rows,1):
            R.need(ordinal==n,'journal_sequence');receipt=decode(raw,65536)
            R.need(self._contract.validate('panel__Service_RequestReceipt',receipt),'receipt_schema')
            R.need(receipt['identity']==identity and receipt['intent_digest']==self._digest and receipt['method']==intent['method'] and receipt['activation_ref']==intent['activation_ref'],'journal_receipt_binding')
            ref=receipt['accepted_result_ref']
            if ref is not None:R.need(all(ref[k]==identity[k] for k in ['authority_service_id','database_instance_id']),'journal_scope')
            if previous is not None:
                state=previous['state'];R.need(state=='pending_confirmation' or receipt['state']==state,'journal_outcome_regression')
                if state in ['cancelled','rejected']:R.need(receipt['reason_code']==previous['reason_code'],'journal_outcome_regression')
                if state=='accepted':R.need(ref==previous['accepted_result_ref'],'journal_result_changed')
            previous=receipt
        record=dict(invocation=invocation,observation=dict(kind='receipt',receipt=previous))
        R.bounded(record)
        R.need(self._authorize(copy.deepcopy(current),copy.deepcopy(request),copy.deepcopy(record)) is True,'journal_authorization')
        return record
