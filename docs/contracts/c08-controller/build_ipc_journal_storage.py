"""共享日志与既有领域写集的固定组合；不是业务迁移或通用SQL转换器。"""
import argparse
import build_encoding_release_storage as E
import build_ipc_journal as J
import build_layout as L

HERE=E.HERE
TABLES=('ij_type','ij_reply_type','ij_session','ij_exit','ij_frame','ij_commit','ij_write_attempt',
        'ij_end','ij_write_result','ij_rejection','ij_handshake','ij_encoding_frame')
SOURCES=E.SOURCES+[HERE/'build_ipc_journal.py',HERE/'build_ipc_journal_storage.py',HERE/'ipc-journal-storage.sql']
# 类型策略来自受信协议配置；调用者不能自行把普通消息提升为保护消息。
PROTECTED=set(('HELLO HELLO_ACK FENCE FENCE_ACK AUTH_FENCE AUTH_FENCE_ACK TIME_FENCE TIME_FENCE_ACK '
 'RUN_FENCE RUN_FENCE_ACK CANCEL_FENCE CANCEL_FENCE_ACK CLOSE_GATE CLOSE_GATE_ACK QUERY_BARRIER '
 'BARRIER_UNAVAILABLE BARRIER_STORED SEND_REPORT REPORT_STORED CANCEL_SEND_REPORT CANCEL_REPORT_STORED '
 'RELEASE_ENCODING RELEASE_ENCODING_ACK DENY_ENCODING DENY_ENCODING_ACK').split())
# table, domain kind, key, direction, types, seq, message, frame/body column, digest column, tick
MAPS=(
 ('ij_encoding_frame','encoding_request','prepare_id','c2w',('ENCODE_PACKET','ENCODE_CANCEL_PACKET'),'request_seq',None,'request_frame','request_frame_digest',None),
 ('ep_reply','encoding_reply','prepare_id','w2c',('PREPARE_PACKET','PACKET_ENCODING_FAILED','PREPARE_CANCEL_PACKET','CANCEL_ENCODING_FAILED'),'response_seq','response_message_id','response_frame','response_frame_digest','received_tick'),
 ('er_request','release_request','release_id','c2w',('RELEASE_ENCODING',),'outbound_seq','message_id','frame_body','frame_digest','selected_tick'),
 ('er_ack','release_ack','ack_id','w2c',('RELEASE_ENCODING_ACK',),'inbound_seq','message_id','frame_body','frame_digest','received_tick'),
 ('go_dispatch','open_request','dispatch_id','c2w',('OPEN_GATE',),'outbound_seq','message_id','frame_body','frame_digest','reserved_tick'),
 ('go_evidence','open_ack','evidence_id','w2c',('OPEN_GATE_ACK',),'inbound_seq','message_id','frame_body',None,'received_tick'),
 ('gf_request','renewal_request','request_id','c2w',('GATE_FENCE',),'outbound_seq','message_id','body',None,'selected_tick'),
 ('gf_ack','renewal_ack','ack_id','w2c',('GATE_FENCE_ACK',),'inbound_seq','message_id','body',None,'received_tick'))

def quoted(values):return ','.join("'"+v+"'" for v in values)

def build():
    text=E.build().decode()
    text=L.replace(text,"request_message_id TEXT NOT NULL, request_seq TEXT NOT NULL CHECK(length(request_seq)=20 AND request_seq NOT GLOB '*[^0-9]*' AND request_seq>'00000000000000000000'),\n request_frame_digest TEXT NOT NULL, request_frame BLOB NOT NULL CHECK(length(request_frame)>0),","request_message_id TEXT NOT NULL,",1)
    text=L.replace(text,' UNIQUE(exit_id,request_seq),','',1)
    text=L.replace(text,'CREATE TABLE ep_send_attempt(\n', 'CREATE TABLE ep_send_attempt(\n journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_write_attempt(frame_id) DEFERRABLE INITIALLY DEFERRED,\n',1)
    text=L.replace(text,'FROM ep_open_request r JOIN ep_request_commit k USING(prepare_id)',
                   'FROM ep_open_request r JOIN ep_request_commit k USING(prepare_id) JOIN ij_encoding_frame j USING(prepare_id)',1)
    text=L.replace(text,'r.request_frame_digest=NEW.request_frame_digest','j.request_frame_digest=NEW.request_frame_digest',1)
    text=L.replace(text,'JOIN ep_send_attempt s USING(prepare_id) JOIN ep_revocation v USING(prepare_id)',
                   'JOIN ep_send_attempt s USING(prepare_id) JOIN ep_revocation v USING(prepare_id) JOIN ij_encoding_frame j USING(prepare_id)',1)
    text=L.replace(text,'r.request_frame_digest=NEW.encode_frame_digest','j.request_frame_digest=NEW.encode_frame_digest',1)
    for fragment in (
      " SELECT CASE WHEN EXISTS(SELECT 1 FROM ep_request WHERE exit_id=NEW.exit_id AND (request_message_id=NEW.message_id OR request_seq=NEW.outbound_seq))\n THEN RAISE(ABORT,'encoding_release_outbound_collision') END;\n",
      " SELECT CASE WHEN EXISTS(SELECT 1 FROM ep_reply WHERE exit_id=NEW.exit_id AND (response_message_id=NEW.message_id OR response_seq=NEW.inbound_seq))\n THEN RAISE(ABORT,'encoding_release_inbound_collision') END;\n"):
        text=L.replace(text,fragment,'',1)
    text=L.remove(text,'TRIGGER','er_encoding_inbound')
    text=L.remove(text,'TRIGGER','er_encoding_outbound')
    text+='\n'+(HERE/'ipc-journal-storage.sql').read_text(encoding='utf-8')
    text+="\nCREATE TRIGGER ij_metadata_guard BEFORE INSERT ON ep_request BEGIN\n SELECT CASE WHEN (SELECT count(*) FROM ep_request WHERE exit_id=NEW.exit_id)>=(SELECT max_metadata_prepares FROM ep_limit WHERE singleton=NEW.scope_id) THEN RAISE(ABORT,'encoding_metadata_capacity') END;\nEND;\n"
    for table,kind,key,direction,types,seq,msg,body,digest,tick in MAPS:
        if table!='ij_encoding_frame':
            text=L.replace(text,f'CREATE TABLE {table}(\n',f'CREATE TABLE {table}(\n journal_frame_id TEXT NOT NULL UNIQUE REFERENCES ij_frame(frame_id),\n',1)
        predicates=[f"f.domain_kind='{kind}'",f'f.domain_id=NEW.{key}',f"f.direction='{direction}'",
                    f'f.message_type IN ({quoted(types)})',f'f.seq=NEW.{seq}']
        if table=='ij_encoding_frame':
            predicates += ["EXISTS(SELECT 1 FROM ep_open_request r JOIN ep_request_commit k USING(prepare_id) WHERE r.prepare_id=NEW.prepare_id AND r.exit_id=f.exit_id AND r.request_message_id=f.message_id AND k.committed_tick<=f.observed_tick AND f.observed_tick<r.expires_tick AND f.message_type=CASE r.kind WHEN 'ordinary' THEN 'ENCODE_PACKET' ELSE 'ENCODE_CANCEL_PACKET' END)"]
        else:predicates += ['f.exit_id=NEW.exit_id',f'f.message_id=NEW.{msg}']
        if direction=='w2c':predicates+=['f.reply_to=NEW.reply_to']
        predicates += [f"f.{'body_body' if body=='body' else 'frame_body'}=NEW.{body}"]
        if digest:predicates += [f'f.frame_digest=NEW.{digest}']
        if tick:predicates += [f'f.observed_tick=NEW.{tick}']
        if table=='ep_reply':
            predicates += ["EXISTS(SELECT 1 FROM ep_request r WHERE r.prepare_id=NEW.prepare_id AND NEW.outcome IN ('prepared','failed') AND f.message_type=CASE WHEN r.kind='ordinary' AND NEW.outcome='prepared' THEN 'PREPARE_PACKET' WHEN r.kind='ordinary' THEN 'PACKET_ENCODING_FAILED' WHEN NEW.outcome='prepared' THEN 'PREPARE_CANCEL_PACKET' ELSE 'CANCEL_ENCODING_FAILED' END)"]
        text+=f"\nCREATE TRIGGER ij_bind_{table} BEFORE INSERT ON {table} BEGIN\n SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.journal_frame_id AND {' AND '.join(predicates)} AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;\nEND;\n"
    # 最后seal必须看到精确领域原件及其原封存；generic body不可替代领域事务。
    conditions=[]
    for table,kind,key,direction,types,*_ in MAPS:
        extra="NEW.disposition='applied'"
        if table=='ep_reply':extra="EXISTS(SELECT 1 FROM ep_receive_commit c WHERE c.prepare_id=d.prepare_id AND c.committed_tick=NEW.committed_tick AND NEW.disposition=CASE c.disposition WHEN 'historical' THEN 'historical' ELSE 'applied' END)"
        if table=='er_request':extra+=" AND EXISTS(SELECT 1 FROM er_request_commit c WHERE c.release_id=d.release_id AND c.committed_tick=NEW.committed_tick)"
        if table=='er_ack':extra="EXISTS(SELECT 1 FROM er_ack_commit c WHERE c.ack_id=d.ack_id AND c.committed_tick=NEW.committed_tick AND NEW.disposition=CASE c.disposition WHEN 'historical' THEN 'historical' ELSE 'applied' END)"
        if table in ('go_evidence','gf_ack'):extra="NEW.disposition IN ('applied','historical')"
        conditions.append(f"(f.domain_kind='{kind}' AND EXISTS(SELECT 1 FROM {table} d WHERE d.{key}=f.domain_id AND d.journal_frame_id=f.frame_id AND {extra}))")
    conditions += ["(f.domain_kind='handshake' AND NEW.disposition='applied' AND EXISTS(SELECT 1 FROM ij_handshake d WHERE d.handshake_id=f.domain_id AND d.frame_id=f.frame_id AND d.kind=f.message_type))",
      "(f.domain_kind='rejection' AND f.direction='w2c' AND NEW.disposition='rejected' AND EXISTS(SELECT 1 FROM ij_rejection d WHERE d.rejection_id=f.domain_id AND d.frame_id=f.frame_id))"]
    text+="\nCREATE TRIGGER ij_domain_seal BEFORE INSERT ON ij_commit BEGIN\n SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND ("+' OR\n '.join(conditions)+")) THEN RAISE(ABORT,'journal_missing_domain_commit') END;\nEND;\n"
    for table,key,kind in [('ij_handshake','handshake_id','handshake'),('ij_rejection','rejection_id','rejection')]:
        extra=" AND f.message_type=NEW.kind" if kind=='handshake' else " AND f.direction='w2c'"
        text+=f"\nCREATE TRIGGER ij_bind_{table} BEFORE INSERT ON {table} BEGIN\n SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM ij_frame f WHERE f.frame_id=NEW.frame_id AND f.domain_kind='{kind}' AND f.domain_id=NEW.{key}{extra} AND NOT EXISTS(SELECT 1 FROM ij_commit c WHERE c.frame_id=f.frame_id)) THEN RAISE(ABORT,'journal_domain_binding') END;\nEND;\n"
    # 接收历史ACK与重新开放分开。终止与采用在任意提交顺序下均不留下可用候选。
    for table,evidence,foreign in [('go_ready','go_evidence','evidence_id'),('gs_scope_commit','go_evidence','evidence_id'),('gf_commit','gf_ack','ack_id')]:
        text+=f"\nCREATE TRIGGER ij_current_{table} BEFORE INSERT ON {table} BEGIN\n SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM {evidence} a JOIN ij_frame f ON f.frame_id=a.journal_frame_id JOIN ij_commit c USING(frame_id) WHERE a.{foreign}=NEW.{foreign} AND c.disposition='applied' AND NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=f.session_id)) THEN RAISE(ABORT,'journal_adoption_not_current') END;\nEND;\n"
    for view in ('go_ready_candidate','gs_scope_candidate','gf_valid_fence','ep_open_request'):
        # 原视图条件保留，以只读外层收紧会话资格。
        text=L.replace(text,f'CREATE VIEW {view} AS',f'CREATE VIEW ij_base_{view} AS',1)
        text+=f"\nCREATE VIEW {view} AS SELECT b.* FROM ij_base_{view} b JOIN ij_exit x ON x.exit_id=b.exit_id WHERE NOT EXISTS(SELECT 1 FROM ij_end e WHERE e.session_id=x.session_id);\n"
    for name in J.C2W+J.W2C:
        text+=f"INSERT INTO ij_type VALUES('{name}','{'c2w' if name in J.C2W else 'w2c'}',{int(name in J.REPLIES)},{int(name in PROTECTED)});\n"
    for response,requests in J.REPLIES.items():
        for request in requests:text+=f"INSERT INTO ij_reply_type VALUES('{response}','{request}');\n"
    for table in TABLES:
        for action,suffix in [('UPDATE','u'),('DELETE','d')]:
            text+=f"CREATE TRIGGER {table}_{suffix} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_journal'); END;\n"
    for table in ('ij_type','ij_reply_type'):
        text+=f"CREATE TRIGGER {table}_i BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'immutable_journal_policy'); END;\n"
    return text.encode()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    raw=build();target=HERE/'controller-ipc-journal.sql'
    if a.check:assert target.read_bytes()==raw,'生成漂移'
    else:target.write_bytes(raw)
