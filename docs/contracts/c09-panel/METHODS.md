# 面板35方法的输入与结果投影候选

本稿是[C09第11节](../../rebirth-c09-extension-design.md#11-逐方法输入与结果投影)的字段规范，推荐尚未批准。`method-input.schema.json`是本批**输入**结构唯一源，`method-bindings.json`逐字段登记旧HTTP请求的来源归属；结果白名单在本稿定义，后续[结果机器候选](RESULTS.md)已提供21个View的Schema，尚无生产投影实现。不要将channel-cases中的SyntheticArguments当这些方法的产品参数。旧draft.4／IPC0.3字节保持不变。

本批输入Schema借用`df01-source/source/public.schema.json`的具名领域类型，保留其已知词法缺口；引用只在离线注册表中解析，不联网。Id／Revision最终仍须DF01严格字节解码及新版词法约束。Definition、Predicate.value、设备parameters等开放数据必须按批准DSL／能力／字段Schema二次校验，结构合法不授权调用或证明无秘密。

## 1. 共用映射与不可由面板提供的字段

校验根为`{method,arguments}`，用于离线表达方法分派；port线上仍用既有Request的`method`和`payload.value`，不新增第二层线上包络。Registry将方法绑定到本Schema的具体`$defs`，随后验证外层target_handle／resource_ref、当前权限及领域关联。所有arguments关闭额外字段。

面板输入中的path ID必须与服务解析的resource_ref和目标authority精确一致；两个path ID的方法还要验证父子关系，不能凭同库ID合法就接受。submitCommand的device_id必须与resource_ref对应。createDefinition／createRun和服务级读取使用服务目标；createRun所选定义仍校验可见性和发布版本，不能借“创建”绕对象权限。没有resource_ref的设备／命令／运行操作拒绝，不自动查找同名对象补目标。

`context_id,idempotency_key`由目标服务从原完整PanelRequestIdentity的持久绑定取得；每次重复查询使用同一绑定，不重新签context或生成幂等键。`origin`固定manual，禁止run_binding；correlation_id由宿主生成可追踪的非秘密关联，不接受面板任意指定。鉴权头、委托、request identity、target authority均不在arguments中。DraftUpdate旧模型虽没有context／幂等字段，面板请求仍在panel_request唯一登记并与草稿CAS同事务，不允许单独调用旧更新入口绕过。

所有host_confirm输入只形成intent；其业务结果在确认消费之后才可出现。`force`缺省在确认前固定false，不因权限不足自动变true。expected_control／expected_revision来自面板最后观察，服务核验，不能悄悄覆盖成当前值再执行。设备parameters需要secret_ref时只允许当前批准范围的引用；密码值及低熵秘密摘要不进入普通参数、日志、预览或结果。

分页不透传上游cursor。面板输入`page_handle?`，服务映射到固定method／过滤条件／授权视图／catalog或evidence revision／原cursor，并绑定PanelSession和document_generation；结果只返回`next_page_handle`。不接受其他会话句柄，scope变化失效；数据版本不能保持一致时明确要求重新读取，不拼接两版页面。无句柄表示第一页，不表示重发写。

## 2. Controller十九方法

表内`?`为可选；字段的基础类型来自输入Schema。`EC=expected_control`，`ER=expected_revision`只是表格缩写，线上使用完整字段名。结果的View均指下节白名单，不能通过复制原Response再删少数字段实现。

| 方法 | arguments完整顶层字段 | 结果 |
| --- | --- | --- |
| controller.getMeta | 无 | MetaView |
| controller.getClock | 无 | ClockView |
| controller.listDevices | page_handle? | DevicePageView |
| controller.getCapabilities | device_id | CapabilityView |
| controller.getDeviceState | device_id | ObservationView |
| controller.submitCommand | device_id、action_id、capability_version、parameters、EC、required_completion、preconditions、dispatch、evidence_timeout_ms | CommandView |
| controller.getCommand | command_id | CommandView |
| controller.cancelCommand | command_id、ER、reason | CancelView |
| controller.getControlOperation | operation_id | ControlOperationView |
| controller.getControl | device_id | ControlView |
| controller.acquireControl | device_id、EC、reason、force? | ControlOperationView；仅可信确认后受理 |
| controller.releaseControl | device_id、EC、reason | ControlOperationView；不自动恢复自动化 |
| controller.offerTransfer | device_id、EC、reason、target_principal_id、offer_ttl_ms | TransferView |
| controller.acceptTransfer | device_id、transfer_id、EC、reason | ControlOperationView |
| controller.revokeRunGrant | grant_id、ER、reason | MutationView |
| controller.getClockAssessment | 无 | ClockAssessmentView |
| controller.getCapacity | 无 | CapacityView |
| controller.getSceneCatalog | device_id | SceneCatalogView |
| controller.getCommandEvidence | command_id、page_handle? | EvidencePageView |

dispatch保留旧immediate／scheduled两种结构以保留API能力；实时推子手势只能使用immediate，scheduled须当前授权的固定occurrence及时间policy，不能凭合法occurrence_id制造场次。正式排期仍由Seamer管理，不给面板定时器增加组织自动化身份。OBS场景设置保持ObsSceneParameters及effect_verified要求。取消结果不回写原命令为未发送，查询不重发。

target_principal_id只从可信宿主提供的受限可选成员投影选择；面板不得用getSubject或成员遍历扩充目录。grant_id也只引用已授权运行详情暴露的非秘密对象ID，不返回grant凭据。ID存在性不是权限。

## 3. Seamer十六方法

| 方法 | arguments完整顶层字段 | 结果 |
| --- | --- | --- |
| seamer.getMeta | 无 | MetaView |
| seamer.getClock | 无 | ClockView |
| seamer.createDefinition | definition | DefinitionView |
| seamer.updateDraft | definition_id、ER、definition | DefinitionView |
| seamer.publishDefinition | definition_id、ER | DefinitionView；仅可信确认后发布 |
| seamer.createRun | definition_id、definition_version | RunView；仅创建未布防run |
| seamer.getRun | run_id | RunView |
| seamer.preflightRun | run_id、ER | PreflightView |
| seamer.armRun | run_id、ER、assessment_handle | MutationView |
| seamer.pauseRun | run_id、ER、reason | MutationView |
| seamer.previewRecovery | run_id、ER | RecoveryPlanView |
| seamer.resumeRun | run_id、ER、recovery_handle | RecoveryOperationView |
| seamer.getClockAssessment | 无 | ClockAssessmentView |
| seamer.getCapacity | 无 | CapacityView |
| seamer.getRecoveryOperation | operation_id | RecoveryOperationView |
| seamer.getIndependenceProof | definition_id、proof_id | IndependenceView |

Definition及Predicate的引用校验覆盖每个action／trigger／device／field，不只校验外层definition_id。编辑时采用完整已授权版本，若有不可读必需字段则整个编辑投影不可用，转可信宿主处理；不回传裁剪后看似完整的Definition让保存误删隐藏步骤。read_set／write_set和proof来自权威编译器，面板不能自签independence_proof；保留旧类型不表示其声明已可信。

## 4. 结果白名单及嵌套规则

公共传输wrapper的request_id由面板原请求关联，旧Response的service_boot_id／内部RequestContext不直接下发。每个View由白名单重新构造，缺字段或投影失败返回结构化unavailable，不能回退原对象。`reason_code`、`label_key`来自受控词表；显示字符串作为纯文本，来源名称仍按对象读取权处理。原始ERROR.details、异常堆栈、协议报文、路径、证书或secret value均不进入结果。

| View | 允许字段与嵌套边界 |
| --- | --- |
| MetaView | component_version、protocol_version、panel_features（Registry中当前已批准且可用方法／功能）、limits_profile_ref；不暴露后台内部feature全集 |
| ClockView | status、sampled_at、offset_ms、uncertainty_ms、sample_age_ms、policy_revision；不暴露NTP端点或source_ref。nullable与失同步原样保留，不把null变0 |
| ClockAssessmentView | eligible_for_absolute、reason_code、policy_revision、sample_age_ms、uncertainty_now_ms、utc_lower_ms、utc_upper_ms；不返回domain/tick、descriptor/time_evidence/time_profile引用；仅展示，不作面板授权事实 |
| DevicePageView | items[{device_id,device_kind,display_name,connection_state}]、catalog_revision、next_page_handle；每项先过滤对象权限，不给未授权总数；能力另查具名入口 |
| CapabilityView | device_id、catalog_revision、actions、triggers、state_schema_ref；actions仅action_id、capability_version、parameters_schema_ref、result_schema_ref、supported_completion、default_completion、cancel_mode、retry_mode、evidence_timeout_ms；triggers仅trigger_id、capability_version、payload_schema_ref、delivery_semantics、time_requirement、max_age_ms；不下发内部足迹／原生依赖／完整重试policy |
| ObservationView | device_id、observation_id、state_revision、observed_at、freshness_ms、integrity、projection_status、values；values是按批准state_schema及字段读权生成的QualifiedValue，不透Payload。projection_status为complete/filtered，表示投影是否裁剪，独立于原来源integrity的complete/gap/unavailable；values只含可见字段，不把来源完整误作面板获得全量 |
| CommandView | command_id、revision、target{device_id,action_id,capability_version}、origin、accepted_at、phase、outcome、effect_status、resource_status、required_completion、achieved_completion、cancellation_state、automation_continuation、reason_code、resolution_summary；未知终态与资源未决分别保留，不含actor/request_identity/admission/permit/attempt原文 |
| CancelView | operation_id、command_id、state、reason_code；requested/confirmed/unsupported/failed保留，不由HTTP200推断confirmed |
| ControlOperationView | operation_id、device_id、state、target{version,mode,holder}、failure_code、effective_version、ready；state保留pending/effective/rejected/indeterminate，ready由当前权威控制状态判定，effective不自动推出ready。holder为下述受限身份投影，不含barrier、worker/domain、coverage或durable证据 |
| ControlView | device_id、revision、control_epoch、effective_version、mode、holder、gate_state、pending_change、in_flight、unresolved；pending_change仅operation_id、target_version、target_mode、holder、reason_code。in_flight/unresolved各为可见command_ids和has_hidden boolean，不泄隐藏ID／数量，存在隐藏未决仍令ready=false |
| TransferView | transfer_id、device_id、from_holder、target_holder、expected_control、expires_at、state、accept_operation_id nullable；旧模型没有accept_operation_id，须下一版显式补关联，不能猜取最新operation。accepted不等于接管effective |
| MutationView | operation_id、state、entity_id、revision、visible_targets[{service_alias,status,applied_revision}]、has_hidden_targets；保留全局pending/applied/rejected/indeterminate，不因可见targets全applied就改全局applied |
| CapacityView | pressure、reason_codes、panel_budget{max_pending_requests,max_unacked_frames,max_unacked_bytes}、current_panel_usage{pending_requests,unacked_frames,unacked_bytes}；预算来自批准profile且计数仅此面板，不返回全服务used/limit。缺面板计数标unavailable，不伪装0 |
| SceneCatalogView | device_id、collection_ref、collection_generation、catalog_revision、binding_revision、status、entries[{scene_id,display_name}]；不返回obs_scene_uuid或device_session_id。提交scene_id后由服务绑定同一当前目录和具体OBS uuid |
| EvidencePageView | command_id、items[{evidence_id,kind,captured_at,predicate_result,completion_level}]、resource_release_summary{status,policy_label}、next_page_handle；只选已授权命令且归属已核验的证据，不含obs_bundle／协议request_id／时钟描述／原始状态。单条证据存在不推导命令成功或资源已释放 |
| DefinitionView | definition_id、revision、definition_version、published、definition、proof_summaries；definition明确为{schema_ref,value}，value保留完整Definition且须完整字段授权与每个嵌套参数的安全Schema，保存时取value。proof_summaries只proof_id、failed_step_id、successor_step_ids、verdict。不能把预览的脱敏占位当可保存定义 |
| RunView | run_id、definition_id、definition_version、revision、business_state、transition_summary、lifecycle、execution_summary、arm_generation、active_execution_id、grant_summaries；transition_summary只transition_id/from_state/to_state/phase，须由新投影映射，不能假定旧transition结构同名；grant_summaries仅可见controller_alias、grant_id、status及has_hidden。无凭据、摘要或授权快照 |
| PreflightView | run_id、run_revision、passed、checks[{code,passed,label_key}]、observed_at、assessment_handle；details原文不返回；只有整体及全部必需checks通过才可提出布防，handle本身不证明通过 |
| RecoveryPlanView | run_id、run_revision、recovery_handle、expires_at、items[{step_id,source_execution_id,source_command_id,decision,reason_code}]、unresolved{visible_command_ids,has_hidden}；决定保留retain_success/execute_new/reconcile_commit/stop，不返回preview_id/digest、计划摘要或原观察；不可见必需步骤使完整确认展示不可用，不能默默删项后恢复 |
| RecoveryOperationView | operation_id、run_id、previous_run_revision、committed_run_revision、recovery_generation、state、new_execution_id、visible_new_command_ids、has_hidden_commands、target_status_summary；state保留全部7值，target_status_summary只可见服务别名／状态和has_hidden。无preview_id、plan_digest、baseline_snapshot_digest，受理不等于执行完成 |
| IndependenceView | proof_id、proof_revision、definition_id、definition_version、failed_step_id、successor_step_ids、verdict、reason_codes；不返回资源图／原始footprint／bindings摘要；unknown不显示为independent，不让面板摘要参与执行许可 |

holder／from_holder／target_holder统一为`{relation:self|other|none,display_label}`；原principal_id只在允许转交选择的受限PrincipalChoice中返回，不随每条状态广播。不可读名称显示受控“其他操作员”，不暴露账户ID。相关人变动不重写历史执行身份。

动态表单不得因隐藏Schema而失去功能。CapabilityView的各schema_ref精确绑定**批准过的面板表单Schema**及digest。[SchemaBundle候选](BUNDLE.md)采用独立offer／chunk／ready／revoke交付，下一版host.active固定Bundle和Registry引用；旧0.1 Active没有附件字段，不能向它直接添加或混投0.2消息。Bundle只能包含批准的本地资源，无远程ref、脚本、执行表达式、秘密或未授权枚举。document是数据，表单渲染不联网取ref。缺依赖或超预算则该表单显示不可用并在可信宿主处理，不把输入改为任意JSON。局部消息与闭包已有参考检查；完整激活、字段授权及方法绑定仍须同版归并，尚无过滤器或完整动态表单实现。

## 5. 预检、恢复和分页展示句柄

推荐增加服务持有的`panel_view_binding`记录：handle、kind=`preflight|recovery|page`、完整PanelRequestIdentity、PanelSession／document_generation、authority/database、method、resource_ref、expected_revision、source_ref、source_digest、policy_ref、domain_ref、deadline_tick、state=`active|consumed|expired|revoked`。handle为不可猜的随机Id，**不是bearer凭据**；知道handle仍须全部身份及权限检查。原source_ref及digest只在服务内部和可信宿主确认链使用。

preflightRun将已生成的Preflight与panel请求一次登记，返回assessment_handle；armRun先解析句柄固定preflight_id和run/revision，再由可信宿主取得当前组织批准绑定approval_id。面板不能传approval_id或选择更宽批准。检查失败／过期不自动重做预检再沿用旧确认，必须得到新展示及新明确确认。预检结果本身不形成grant或布防。

previewRecovery同样返回recovery_handle；resumeRun固定原RecoveryPreview和其digest，关联PD04的PanelConfirmationPreview。后者展示的run、steps、未决影响和截止与前者一致；最早截止取两类预览、session租约／硬期限和授权边界。恢复commit在同一Seamer writer事务内消费panel确认、recovery preview、view binding，并创建唯一RecoveryOperation；不能先消费handle再跨HTTP调用恢复。两个面板分别取得句柄也不能消费同一恢复preview两次；原恢复唯一约束仍是最终依据。

分页句柄允许在原有效期内幂等重复读取同一页，state不改consumed；预检/恢复句柄只有**成功原子业务受理**时consumed。关闭/撤权/换域/换database使所有相关active失效；过期判断在受理点做，不依赖定时删除。未确认取消只取消本次panel preview，不擅自撤销其他面板的原恢复预览。提交未知按原请求身份查询，查询不到不复活handle、不换ID重试。

实验预算：沿每面板32未决和1待确认，active view binding最多64项、每项不超过当前租约和30秒，分页整组最多256页／8MiB，服务超额拒绝创建新binding，不驱逐未决确认来腾位。需要更大目录时采用批准分页profile或可信宿主入口，不能把截断页当全量完成。期限、cursor快照语义和SchemaBundle预算需与下一版服务持久表／C05共同落地，当前数值未获生产性能批准。

## 6. 验收与实际检查边界

`check_methods.py`核验35方法与现策略一致、HTTP请求每个path/query/body字段恰有来源归属、输入字段闭包，以及手写结构样本和资料变异。只借本地Schema引用，不执行宿主、权限查询、投影过滤、预检／恢复事务、浏览器或设备。报告同时绑定本稿、输入Schema、映射、用例、检查器、策略、公共Schema及两个HTTP骨架，共九输入。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_methods.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_methods.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_methods.py --check-report --staged
```

以下PMT01—PMT12为**待运行**验收，不能由本轮结构检查替代：

| ID | 正常与故障轨迹／预期 |
| --- | --- |
| PMT01 | path ID与resource一致正常；同名异authority、父子错配拒绝，零业务受理 |
| PMT02 | 普通manual受理；注入context/token/run_binding/confirmed拒绝；动态业务参数恰好叫token不靠字段名黑名单误拒，按批准Schema处理 |
| PMT03 | 草稿保存与panel_request同事务；提交回执丢失查原修订，不重复更新 |
| PMT04 | 预检通过→句柄→可信确认→布防；失败预检、修订改变、权限缩小或到期等号拒绝，不能后台重预检后自动布防 |
| PMT05 | 恢复展示→固定双预览→一次消费；跨面板/跨run/旧database句柄拒绝，两个有效面板竞争最多一个原恢复消费 |
| PMT06 | commit与关闭／撤权两种顺序；先关闭拒绝，先受理保留执行影响，unknown不重发 |
| PMT07 | 同一有效page_handle重复读一致；换scope/目录版本/会话拒绝旧页，不拼出伪全量 |
| PMT08 | 全部21个View（共35方法）从白名单构造；嵌套秘密、ERROR原文、OBS原包、隐藏target及内部证据不可达 |
| PMT09 | 存在隐藏未决命令或target时保留阻塞；可见子集完成不显示ready／全局applied |
| PMT10 | SchemaBundle完整本地闭包正常；远程ref、秘密default、未批准enum或包超限拒绝，不回退任意JSON |
| PMT11 | 同值观察、有效ACK或evidence条目不得把unknown改成功，也不自动释放资源 |
| PMT12 | 完整可编辑Definition往返无丢字段；有隐藏必需步骤时拒绝编辑投影，不保存脱敏占位；实时手势不能借scheduled绕预算 |

输入批次只证明输入结构与逐字段来源，结果/句柄原为具体设计。后续[RESULTS](RESULTS.md)已有21个View，[BUNDLE](BUNDLE.md)已有交付与引用闭包，[CHANNEL_V02](CHANNEL_V02.md)归并完整消息格式、方法联接及投影订阅。结果投影器与权限提供者、完整动态能力、HTTP错误／IPC guard／DDL仍未完成。展示句柄不是新的跨服务授权捷径，局部合成例不等于运行证明。全系统设计和C09均保持未关闭。
