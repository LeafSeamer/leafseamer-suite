"""取消受理与阶段cut的持久拒绝水位；不把来源索引冒充IPC快照或发送许可。"""
import re
from pathlib import Path
import run_snapshot_model as R
M=R.M;N=R.N;P=R.P;S=R.S;need=M.need;HERE=Path(__file__).resolve().parent
MAX_COMMANDS=4096

def install(db):
    need(not db.in_transaction,'command_deny_install_transaction')
    need(db.execute('PRAGMA foreign_keys').fetchone()[0]==1 and db.execute('PRAGMA recursive_triggers').fetchone()[0]==1,'command_deny_pragmas')
    source=(HERE.parent/'c08-controller/cancel-closure.sql').read_text(encoding='utf-8')
    for name in ('cc_expected_member','cc_expected_target','cc_expected_prepare'):
        expected=re.search(r'CREATE VIEW '+name+r'\b.*?;',source,re.S).group(0).rstrip(';')
        need(M.E.one(db,'SELECT sql FROM sqlite_schema WHERE name=?',(name,))['sql']==expected,'command_deny_layout_anchor')
    # 新库候选禁止对已有取消历史猜造顺序；锁定检查与DDL处于同一事务。
    sql=(HERE/'command_deny.sql').read_text(encoding='utf-8')
    try:
        db.executescript("BEGIN IMMEDIATE; CREATE TEMP TABLE cd_install_guard(v INTEGER CHECK(v=0));\n"
          "INSERT INTO cd_install_guard SELECT count(*) FROM cv_cancel; DROP TABLE cd_install_guard;\n"+sql+'\nCOMMIT;')
    except Exception:
        if db.in_transaction:db.rollback()
        raise

def head(db,device):
    S.validate('Id',device)
    row=db.execute('SELECT revision FROM cd_head WHERE device_id=?',(device,)).fetchone()
    return str(int(row[0])) if row else '0'

def materialize(db,device,revision=None):
    need(db.in_transaction,'command_deny_transaction_required');now=head(db,device)
    revision=now if revision is None else revision;S.validate('Counter',revision)
    need(int(revision)<=int(now),'command_deny_future')
    # 同一读快照内验证来源双向覆盖；已受理、已提交cut均不能消失或凭空增加。
    columns='device_id,cancellation_id,command_id,event_kind,cut_id'
    for left,right in (('cd_expected','cd_event'),('cd_event','cd_expected')):
        need(db.execute('SELECT '+columns+' FROM '+left+' WHERE device_id=? EXCEPT SELECT '+columns+' FROM '+right+' WHERE device_id=? LIMIT 1',(device,device)).fetchone() is None,'command_deny_coverage')
    events=R.O.rows(db,'SELECT * FROM cd_event WHERE device_id=? ORDER BY snapshot_revision LIMIT 12289',(device,))
    need(len(events)<=MAX_COMMANDS*3,'command_deny_capacity')
    latest={};seen=set();previous=0
    for event in events:
        number=int(event['snapshot_revision']);need(number==previous+1,'command_deny_sequence');previous=number
        key=event['cancellation_id'];kind=event['event_kind']
        need((key,kind) not in seen,'command_deny_duplicate');seen.add((key,kind))
        if kind=='ordinary':need((key,'accepted') in seen,'command_deny_accept_required')
        if kind=='all':need((key,'ordinary') in seen,'command_deny_ordinary_required')
        if number<=int(revision):latest[event['command_id']]=event
    need(previous==int(now),'command_deny_head')
    need(len(latest)<=MAX_COMMANDS,'command_deny_capacity')
    entries=[dict(parent_command_id=e['command_id'],cancellation_id=e['cancellation_id'],
      stage='ordinary' if e['event_kind']=='accepted' else e['event_kind'],deny_revision=str(int(e['deny_revision'])),
      cut_id=e['cut_id'],cut_pending=e['event_kind']=='accepted') for _,e in sorted(latest.items())]
    return dict(device_id=device,snapshot_revision=revision,entries=entries)

def current(db,original):
    need(db.in_transaction,'command_deny_transaction_required')
    need(original==materialize(db,original['device_id'],original['snapshot_revision']),'command_deny_original')
    return original['snapshot_revision']==head(db,original['device_id'])

def complete_cut_ids(db,device):
    """只返回需要进一步核验的原件ID，绝不是已验证的cut_ref或OPEN资格。"""
    source=materialize(db,device)
    need(not any(e['cut_pending'] for e in source['entries']),'command_deny_cut_pending')
    return source,[e['cut_id'] for e in source['entries']]
