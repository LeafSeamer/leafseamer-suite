"""声明完整字段来源并核对当前SQL原件；不补造缺失字段，不迁移旧行。"""
import json
from jsonschema import Draft202012Validator
import build_command_contract as G
import continuation_binding_model as B
SCHEMA=G.build()['command-contract.schema.json'];need=B.need
# 每个顶层字段均指定持久化位置或明确的新提供者。嵌套对象必须整份保留并通过原Schema。
EXECUTION={
 'scope':'storage_scope.authority_id/database_id',
 'execution_id':'execution.execution_id','run_id':'execution.run_id',
 'artifact_ref':'新编译产物原件；ingress_listener.artifact_digest不足以提供完整Ref',
 'origin':'execution.origin_kind + trigger_decision_ref_body；恢复沿recovery_operation原件',
 'arm_generation':'execution.arm_generation','source_state':'execution.source_state_id/source_state_revision',
 'target_state_id':'execution.target_state_id',
 'input_snapshot_ref':'ingress_decision.snapshot_id + ingress_snapshot.digest + storage_scope',
 'resolved_parameters_ref':'新完整参数快照原件；逐步骤parameters_ref_body不能代替执行全集',
 'grants':'rc_receipt.receipt_body.continuation_grant_ref；非原recovery grant',
 'clock':'新计划时受监督时钟原件；不得使用更晚anchor的当前时间补写',
 'plan_digest':'execution.plan_digest = execution_plan_set.plan_digest；不是continuation_plan_ref.digest',
 'binding_digest':'JCS完整正文仅去顶层binding_digest，写execution.binding_digest',
 'binding_version':'固定continuation-execution/0.1.0-draft.1',
 'authorization_mode':'完整新执行类型，不能由是否缺字段推断',
 'continuations':'rc_request/rc_target/rc_receipt/rc_adoption完整原件全集'}
REQUEST={
 'context_id':'受信提交上下文原件；不进入内容摘要',
 'idempotency_key':'新请求生成cmd_加确定性SHA-256十六进制；原样存command_submission.idempotency_key；已受理旧键不得改写',
 'device_id':'execution_step_plan.plan_body.request.device_id',
 'action_id':'execution_step_plan.plan_body.request.action_id',
 'capability_version':'新固定能力快照；禁止默认当前版本',
 'parameters':'新完整固定参数对象；禁止无类型地把旧value包装成parameters',
 'expected_control':'新固定控制版本原件；不得换成当前控制版本',
 'origin':'固定automation或manual；可信调用路径决定',
 'run_binding':'execution、cn_step、新grant及固定逻辑步骤',
 'required_completion':'新能力与批准计划固定完成标准',
 'preconditions':'新固定条件全集；缺失不视为空数组',
 'dispatch':'新批准时间政策及截止原件；不得默认立即执行',
 'evidence_timeout_ms':'新固定超时政策；禁止默认值',
 'correlation_id':'可选运输字段，原样保留但不进入内容摘要',
 'automation_binding':'ExecutionBinding固定Ref及完整ContinuationSelection；不使用旧局部continuation字典'}
KEY={
 'target_scope':'command_submission.target_authority/target_database',
 'issuer_id':'command_submission.issuer_id','issuer_epoch':'新增持久列，来自受信命名空间原件',
 'principal_id':'command_submission.principal_id','request_epoch':'command_submission.request_epoch',
 'operation_id':'command_submission.operation_id，固定createCommand','idempotency_key':'command_submission.idempotency_key'}
def validate(name,value):Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).validate(value)
def resolved(name):
    s=SCHEMA['$defs'][name]
    while '$ref' in s:s=SCHEMA['$defs'][s['$ref'].split('/')[-1]]
    return s
def coverage():
    for name,mapping in [('ExecutionBinding',EXECUTION),('CommandRequest',REQUEST),('RequestKey',KEY)]:
        need(set(mapping)==set(resolved(name)['properties']),'mapping_coverage_'+name)
    return {name:dict(fields=mapping,required=resolved(name)['required']) for name,mapping in [('ExecutionBinding',EXECUTION),('CommandRequest',REQUEST),('RequestKey',KEY)]}
def findings(db,submission):
    """对实际候选库做只读诊断；结果不是运行准入。"""
    sub=B.P.R.one(db,'command_submission','submission_id',submission);e=B.P.R.one(db,'execution','execution_id',sub['execution_id'])
    result=[]
    for name,blob in [('ExecutionBinding',e['binding_body']),('CommandRequest',sub['request_body'])]:
        value=json.loads(blob);props=resolved(name);missing=sorted(set(props['required'])-set(value));extra=sorted(set(value)-set(props['properties']))
        errors=list(Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).iter_errors(value))
        if errors:result.append(dict(object=name,code='stored_body_not_typed',missing=missing,extra=extra))
    columns={r[1] for r in db.execute('PRAGMA table_info(command_submission)')}
    if 'issuer_epoch' not in columns:result.append(dict(object='RequestKey',code='issuer_epoch_not_persisted'))
    key_schema=resolved('RequestKey')['properties']['idempotency_key']
    if list(Draft202012Validator(dict(key_schema,**{'$defs':SCHEMA['$defs']})).iter_errors(sub['idempotency_key'])):
        result.append(dict(object='RequestKey',code='stored_key_lexically_invalid'))
    bad_namespace=[]
    for field in ('issuer_id','principal_id','request_epoch'):
        schema=dict(resolved('RequestKey')['properties'][field],**{'$defs':SCHEMA['$defs']})
        if list(Draft202012Validator(schema).iter_errors(sub[field])):bad_namespace.append(field)
    if bad_namespace:result.append(dict(object='RequestKey',code='stored_namespace_lexically_invalid',fields=bad_namespace))
    body=json.loads(sub['request_body'])
    if 'parameters' not in body and 'value' in body:result.append(dict(object='CommandContent',code='untyped_value_not_parameters'))
    return result
def verify_originals(e,request,key,rows):
    """验证新版写集的完整输入与列投影。调用者仍须在同一事务提供可信原件。"""
    for name,value in [('ExecutionBinding',e),('CommandRequest',request),('RequestKey',key)]:validate(name,value)
    er,sr=rows['execution'],rows['submission'];scope=rows['scope'];decision=rows['decision'];plan=rows['plan']
    B.validate_execution(e,rows['transfer'],rows['adoption'],rows['receipts'])
    need(e['scope']==scope,'scope')
    for field in ('execution_id','run_id','arm_generation','plan_digest','binding_digest'):need(e[field]==er[field],'execution_'+field)
    need(B.M.seal({k:v for k,v in e.items() if k!='binding_digest'},'binding_digest')==e,'execution_jcs')
    need(B.C.raw(e)==er['binding_body'],'execution_body')
    need(e['origin']==dict(kind='trigger',decision_id=decision['decision_id'],decision_digest=decision['digest']),'decision')
    need(decision['execution_id']==e['execution_id'] and decision['run_id']==e['run_id'],'decision_owner')
    source=None if er['kind']=='rule' else dict(state_id=er['source_state_id'],revision=er['source_state_revision'])
    need(e['source_state']==source and e['target_state_id']==er['target_state_id'],'business_state')
    need(plan['execution_id']==e['execution_id'] and plan['plan_digest']==e['plan_digest']==B.M.digest(json.loads(plan['plan_body'])),'plan_original')
    ab=request['automation_binding'];need(ab is not None and ab['execution_binding_ref']==B.eref(e),'execution_reference')
    need(request['origin']=='automation' and ab['authorization_mode']=='continuation','continuation_mode')
    need(ab['origin_scope']==e['scope'] and ab['run_id']==e['run_id'] and ab['arm_generation']==e['arm_generation'] and ab['execution_id']==e['execution_id'],'automation_owner')
    targets=[t for t in e['continuations'] if t['controller_scope']==key['target_scope']];need(len(targets)==1,'controller_selection')
    target=targets[0];need(ab['continuation']==target['selection'] and request['device_id'] in target['device_ids'],'selected_originals')
    grant=target['selection']['grant_ref'];rb=request['run_binding']
    need(rb==dict(run_id=e['run_id'],definition_version=ab['definition_version'],grant_id=grant['id'],grant_revision=grant['revision'],
        arm_generation=e['arm_generation'],step_id=ab['step_id'],logical_action_id=ab['logical_action_id']),'run_binding')
    need((sr['execution_id'],sr['run_id'],sr['step_id'])==(e['execution_id'],e['run_id'],ab['step_id']),'submission_owner')
    need(B.C.raw(request)==sr['request_body'] and sr['request_digest']==B.M.digest(B.content(request)),'request_original')
    need(key['target_scope']==dict(authority_service_id=sr['target_authority'],database_instance_id=sr['target_database']),'target')
    for field in KEY:
        if field!='target_scope':need(field in sr and key[field]==sr[field],'key_'+field)
    need(request['idempotency_key']==key['idempotency_key'],'request_key')
    # 完整原件信任、Schema/JCS和列等价必须同时成立；本函数不替代最终准入。
    return 'typed_projection_valid'
