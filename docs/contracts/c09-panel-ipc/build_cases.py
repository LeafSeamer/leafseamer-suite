"""人工编排IPC结构、绑定、覆盖与故障轨迹；预期不调用判定器。"""
import argparse
import copy
import hashlib
import json
import rfc8785
from build_contracts import HERE, SOURCE, VERSION, FEATURES, encoded


def digest(value):
    return 'sha256:'+hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def build():
    old=json.loads((SOURCE/'fixtures.json').read_text('utf-8'))
    frames={x['frame']['type']:copy.deepcopy(x['frame']) for x in old['ipc_examples'] if x['case_id'].startswith('ipc-positive-')}
    assert len(frames)==19
    g=copy.deepcopy(frames['GUARD_INSTALL']['body']['guard'])
    permit=copy.deepcopy(frames['DISPATCH']['body']['permit'])
    auth=g['binding'];auth.update(principal_kind='human',origin='manual',grant_id=None,grant_revision=None,arm_generation=None,
                                extension_instance_id='extension-a',extension_approval_revision='5')
    identity=dict(authority_service_id=auth['audience'],database_instance_id='db-a',issuer_id=auth['issuer_id'],issuer_epoch=auth['issuer_epoch'],
                  auth_session_id=auth['session_id'],panel_session_id='panel-a',document_generation='1',request_id='request-a')
    def objref(kind,revision='1',raw='2'):
        return dict(authority_service_id=auth['audience'],database_instance_id='db-a',entity_kind=kind,entity_id=kind+'-a',
                    entity_epoch='entity-epoch',revision=revision,content_digest=raw*64)
    context=dict(panel_session_id='panel-a',document_generation='1',auth_session_id=auth['session_id'],request_identity=identity,
        panel_delegation_ref=dict(authority_service_id=auth['audience'],database_instance_id='db-a',delegation_id='delegation-a',revision='1'),
        installation_ref=objref('installation'),approval_ref=objref('approval','5'),
        activation_ref=dict(activation_id='activation-a',registry_ref=dict(revision='1',digest='3'*64),scope_revision='1',bundle_ref=None))
    panel=dict(context=context,principal_id=auth['principal_id'],extension_instance_id='extension-a',artifact_digest='4'*64,
        scope_ref=objref('scope'),policy_ref=objref('policy',auth['policy_revision']),lease_revision='1',
        lifetime=dict(domain_ref=dict(clock_domain_id=g['clock_domain_id'],descriptor_digest=g['descriptor_digest']),
                      hard_deadline_tick='3000000000',lease_deadline_tick='2000000000'))
    g.update(admission_origin='panel',panel_binding=panel)
    g['guard_digest']=digest({k:v for k,v in g.items() if k!='guard_digest'})
    permit.update(admission_origin='panel',panel_binding_digest=digest(panel),guard_digest=g['guard_digest'],origin='manual',grant_revision=None,arm_generation=None)
    selector={k:v for k,v in identity.items() if k!='request_id'};selector['kind']='panel_session'
    envelope={k:frames['GUARD_INSTALL'][k] for k in ('controller_boot_id','worker_boot_id','ipc_session_id','device_id','clock_domain_id','descriptor_digest')}
    current={**envelope,'device_session_id':permit['device_session_id']}
    intent={k:permit[k] for k in ('permit_id','command_id','attempt_id','dispatch_intent_id','worker_boot_id','device_session_id',
                                 'guard_id','guard_digest','clock_domain_id','descriptor_digest','controller_boot_id','admission_origin','panel_binding_digest')}
    intent.update(ipc_session_id=envelope['ipc_session_id'],device_id=envelope['device_id'])
    # 19个既有正例升级为非面板结构；不把它们当语义关联证明。
    def upgrade(value):
        if isinstance(value,list): return [upgrade(x) for x in value]
        if not isinstance(value,dict): return VERSION if value=='ipc/0.3.0-draft.1' else value
        out={k:upgrade(v) for k,v in value.items()}
        if 'authorization_deadline_tick_ns' in out and 'binding' in out: out.update(admission_origin='non_panel',panel_binding=None)
        if 'dispatch_intent_id' in out and 'permit_id' in out and 'guard_digest' in out:
            out.update(admission_origin='non_panel',panel_binding_digest=None)
            if 'content_digest' not in out:
                out.update({k:envelope[k] for k in ('controller_boot_id','ipc_session_id','device_id')})
        if 'selector' in out and 'ledger_digest' in out: out['selector_digest']=digest(out['selector'])
        return out
    frames={name:upgrade(frame) for name,frame in frames.items()}
    frames['GUARD_ACK']['body']['panel_binding_digest']=None
    frames['HELLO']['body']['supported_features']+=list(FEATURES)
    frames['HELLO_ACK']['body']['selected_features']+=list(FEATURES)
    fence=copy.deepcopy(frames['AUTH_FENCE']);fence.update(envelope)
    fence['body'].update(selector=selector,selector_digest=digest(selector),open_intents=[intent],ledger_digest=digest([intent]))
    ack=copy.deepcopy(frames['AUTH_FENCE_ACK']);ack.update(envelope);ack['reply_to']=fence['message_id']
    ack['body'].update({k:fence['body'][k] for k in ('operation_id','barrier_id','selector','selector_digest','target_authorization_revision','issued_cut_revision','ledger_digest')})
    ack['body'].update(coverage=[dict(intent=intent,disposition='not_sent',proof='discarded_unconsumed')],
        invalidated_permit_ids=[intent['permit_id']],in_flight_command_ids=[],unresolved_command_ids=[],
        applied_authorization_revision=fence['body']['target_authorization_revision'])
    authority=dict(current=current,admission_origin='panel',panel_binding=panel,now='1000000000',
        active_session=True,approval_current=True,scope_current=True,storage_healthy=True,
        selectors=[],open_intents=[intent],bindings={digest(panel):panel},transport_entered=[])
    base=dict(guard=g,permit=permit,fence=fence,ack=ack,authority=authority)
    guards=[
        ('PG01',{},True),
        ('PG02',{'guard.panel_binding.context.request_identity.database_instance_id':'other'},False),
        ('PG03',{'guard.panel_binding.context.auth_session_id':'other'},False),
        ('PG04',{'guard.panel_binding.context.panel_session_id':'other'},False),
        ('PG05',{'guard.panel_binding.context.document_generation':'2'},False),
        ('PG06',{'guard.panel_binding.extension_instance_id':'other'},False),
        ('PG07',{'guard.panel_binding.context.approval_ref.revision':'6'},False),
        ('PG08',{'guard.panel_binding.context.activation_ref.scope_revision':'2'},False),
        ('PG09',{'guard.panel_binding.lifetime.domain_ref.descriptor_digest':'sha256:'+'f'*64},False),
        ('PG10',{'authority.now':'2000000000'},False),
        ('PG11',{'authority.now':'1999999999'},True),
        ('PG12',{'authority.active_session':False},False),
        ('PG13',{'authority.approval_current':False},False),
        ('PG14',{'authority.scope_current':False},False),
        ('PG15',{'authority.storage_healthy':False},False),
        ('PG16',{'guard.admission_origin':'non_panel','guard.panel_binding':None,'permit.admission_origin':'non_panel','permit.panel_binding_digest':None},False),
        ('PG17',{'guard.panel_binding.lifetime.lease_deadline_tick':'2500000000'},False),
        ('PG18',{'permit.guard_id':'other'},False),
        ('PG19',{'authority.current.ipc_session_id':'new-ipc'},False),
        ('PG20',{'guard.binding.principal_id':'other'},False),
        ('PG21',{'authority.selectors':[selector]},False),
        ('PG22',{'authority.selectors':[{**selector,'panel_session_id':'panel-b'}]},True),
        ('PG23',{'authority.selectors':[{**selector,'kind':'panel_delegation','delegation_id':'delegation-a','revision_floor':'2'}]},False),
        ('PG24',{'authority.selectors':[{**selector,'kind':'panel_delegation','delegation_id':'delegation-a','revision_floor':'1'}]},True),
        ('PG25',{'guard.binding.scope_digest':'sha256:'+'f'*64},False),
    ]
    coverage=[
        ('PB01',{},True),('PB02',{'ack.reply_to':'other'},False),
        ('PB03',{'ack.body.issued_cut_revision':'999'},False),
        ('PB04',{'ack.body.coverage':[]},False),('PB05',{'ack.body.invalidated_permit_ids':[]},False),
        ('PB06',{'ack.body.selector.database_instance_id':'other'},False),
        ('PB07',{'ack.body.ledger_digest':'sha256:'+'f'*64},False),
        ('PB08',{'authority.current.ipc_session_id':'new-ipc'},False),
        ('PB09',{'authority.transport_entered':[intent['permit_id']]},False),
        ('PB10',{'ack.body.applied_authorization_revision':'0'},False),
        ('PB11',{'ack.body.applied_authorization_revision':'999'},True),
        ('PB12',{'ack.body.unresolved_command_ids':[intent['command_id']]},False),
        ('PB13',{'ack.body.coverage.0.intent.panel_binding_digest':'sha256:'+'f'*64},False),
        ('PB14',{'fence.body.open_intents':[],'ack.body.coverage':[],'ack.body.invalidated_permit_ids':[]},False),
    ]
    selections=[
        {'id':'PS01','selector':selector,'binding_changes':{},'match':True},
        {'id':'PS02','selector':selector,'binding_changes':{'context.panel_session_id':'panel-b','context.request_identity.panel_session_id':'panel-b'},'match':False},
        {'id':'PS03','selector':selector,'binding_changes':{'context.request_identity.database_instance_id':'db-b'},'match':False},
        {'id':'PS04','selector':selector,'binding_changes':{'context.request_identity.issuer_epoch':'other'},'match':False},
        {'id':'PS05','selector':{**selector,'kind':'panel_delegation','delegation_id':'delegation-a','revision_floor':'2'},'binding_changes':{},'match':True},
        {'id':'PS06','selector':{**selector,'kind':'panel_delegation','delegation_id':'delegation-a','revision_floor':'1'},'binding_changes':{},'match':False},
        {'id':'PS07','selector':{**selector,'kind':'panel_delegation','delegation_id':'other','revision_floor':'2'},'binding_changes':{},'match':False},
        {'id':'PS08','selector':selector,'binding_changes':{'context.panel_delegation_ref.revision':'999'},'match':True},
    ]
    traces=[
        {'id':'PT01','steps':['send','fence','ack','store'],'sent':1,'unknown':False,'applied':True},
        {'id':'PT02','steps':['fence','send','ack','store'],'sent':0,'unknown':False,'applied':True},
        {'id':'PT03','steps':['fence','ack','store_fail','send'],'sent':0,'unknown':False,'applied':False},
        {'id':'PT04','steps':['send','reconnect','send'],'sent':1,'unknown':True,'applied':False},
        {'id':'PT05','steps':['fence','reconnect','ack','store'],'sent':0,'unknown':True,'applied':False},
        {'id':'PT06','steps':['fence','fence','send','ack','store'],'sent':0,'unknown':False,'applied':True},
        {'id':'PT07','steps':['send','send','fence','ack','store'],'sent':1,'unknown':False,'applied':True},
    ]
    return dict(purpose='synthetic_panel_ipc_design_only',runtime_approved=False,base=base,frames=frames,
        guard_cases=[dict(id=i,changes=c,valid=v,rehash=True) for i,c,v in guards],
        barrier_cases=[dict(id=i,changes=c,valid=v) for i,c,v in coverage],selection_cases=selections,traces=traces)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    data=encoded(build());path=HERE/'cases.json'
    if args.check: assert path.read_bytes()==data
    else: path.write_bytes(data)
    print('人工用例生成物一致' if args.check else '已生成IPC人工参考用例')
