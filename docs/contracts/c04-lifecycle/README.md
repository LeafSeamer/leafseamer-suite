# C04 生命周期与管理HTTP候选

`automation-lifecycle/0.1.0-draft.1`，**待审阅、未批准**。承接[AR03—AR06](../../rebirth-c04-automation-design.md)与[程序／证明候选](../c04-program/README.md)，不改draft.4／IPC0.3，不替代已确认F07恢复规则。[唯一生成源](build_contracts.py)产生[Schema](lifecycle.schema.json)和[24操作OpenAPI](lifecycle.openapi.json)；[参考模型](reference_model.py)仅用于合成原子步，不是业务实现或持久化层。

## 1. 草稿、发布与请求身份

DraftContent包含Program、BindingSelection和policy_ref。BindingSelection仅选择精确内容引用；真实InputBinding／ActionBinding及权限由服务端解析验证。客户端不能提交CompiledProgram、proof或“已批准”标志来绕过编译。DraftRecord同时返回content_digest与selection_digest：前者覆盖整个content，后者覆盖selections数组原顺序。metadata另有修订，layout不参与执行；修改metadata不得改草稿内容修订或已发布artifact。

Publish请求固定草稿修订、content_digest和selection_digest。它不要求用户提供尚未经过服务器解析的bindings_digest，避免API循环依赖。服务端执行C04程序检查、完整权限／足迹与容量核验，分配不复用的版本，生成program／proof／artifact；最后短事务复核草稿及全部来源绑定仍当前，写PublishedVersion、不可变产物、请求结果和审计。编译期间变化返回409/412，版本空号允许；幂等重试只返回原发布，不重算新产物。发布201不布防。

PublishedVersion的artifact_ref.digest采用PublishedArtifact.manifest_digest；program_digest及bindings_digest沿上一候选。历史program与artifact可按definition_id/version单独GET，不能只保留最新草稿供审计。proof按definition所属及(id,revision)查，须指定revision；引用摘要不是权限。API返回范围内完整对象仍受definition/run对象读取权约束，参数中的secret_ref不解引用，来源快照值不随这些摘要引用泄露。

写请求Context只有context_id与idempotency_key；principal、issuer、request_epoch、service/database身份从当前认证与已签发context取得，不允许请求指定。幂等主键为`(authority,database,request_epoch,actor,operation_kind,idempotency_key)`；身份摘要覆盖具名版本、操作、路径目标与除顶层context以外的业务请求，保留所有嵌套同名键。context_id换新不创造同一epoch下第二逻辑请求，换epoch不复活旧预览。先验证当前读／操作权再查原结果；同键异内容409。同键同内容先返回原受理，再考虑当前revision与旧预览期限，不重新执行。

`lookupAutomationRequest`是有当前读取授权的只读POST，body的operation_id指API操作名，context_id用于定位原请求epoch；查询不签发新context、不重新受理或刷新结果。可以返回原Draft/Version/Run/Preflight/Preview/Operation，原预览已过期也只作为历史。当前权限不允许读取原结果时403，不能以幂等重试泄露数据。

## 2. 实例、活动槽与预检

ActivationSlot主键为`(authority_service_id,database_instance_id,definition_id)`，跨定义版本共享；空槽时active_run_id和definition_version同时null。RunCreate只创建disarmed实例；状态机初态直接记录，**不执行enter动作**。未布防实例可以并存；首次arm的可靠受理占槽，paused／未决恢复继续占槽。显式disarm且已核对后仍保留槽供同run重布防，retire完整核对后才释放，避免借换run跳过历史处理。

Run保持旧五态disarmed/armed/running/paused/completed；新active_operation_id表达准备／关闭过程，不用“armed但尚未全部准备”的混合语义。dispatch_eligible只表示Seamer当前派发资格投影，不代替Controller最终许可。last_receive_seq是本实例已处理接收序号高水位；新执行不会清零，且不按UTC排序。

DependencyBaseline固定run/slot修订、artifact、arm_generation、business_state/revision、模块绑定／组织授权／控制归属／来源／证据摘要及policy。control_digest只覆盖独立控制归属与接管代，authorization_digest覆盖组织和主体授权；本次新建执行grant的变化单独记录在PreparationTarget，不能混入全局摘要后又误认为任意变化都可吸收。任何不属于本操作预期target的变化均失效。

Preflight只观察并保存带时钟域及半开期限`[issued,expires)`的快照，不占槽、不取得设备权。checks必须准确覆盖编译计划全部Controller及设备，不能截断、遗漏或把缺项当passed。纯无设备动作的状态变更可以零目标，仍必须通过来源、身份、存储、活动槽及程序核验，不能伪造一个grant填数组。本文所有tick/revision沿用严格20位十进制词法，时钟域不同不得减法。

## 3. 布防与恢复准备

| 阶段 | 原子记录与行为 |
| --- | --- |
| arm受理 | 查原幂等结果；CAS核对run/slot、未消费preflight、当前基线／域／期限、目标完整性及权限；同事务占槽、消费预检、run/slot修订+1、arm_generation+1、保存operation与审计；run仍disarmed且dispatch_eligible=false |
| 准备 | Controller逐一取得本operation的新target grant／guard回执，含operation、execution（arm为空）、新generation及精确目标；准备阶段无设备写intent |
| arm就绪 | 全部目标applied、权威回执持久且基线未发生无关变化；同Seamer事务将operation记ready、run置armed、清active_operation_id并增加run修订。arm的ready表示此操作已达成目的，不能再回preparing |
| resume受理R2 | 仅paused；旧未决已完成资源核对，固定预览未消费且当前；同事务占用原槽、消费preview、增加run/slot与arm代、创建新operation/execution并保留prior_execution_id，run仍paused |
| 恢复准备R3 | baseline→target独立保存。全部目标准备后operation可ready，run仍paused；随后R4开始事务重新核验才能running，不能复用旧队列 |
| 失败／提交不确定 | 暂停或indeterminate，保存已准备目标并定向撤销核对；preview始终已消费。迟到applied只补历史，不自动重启原操作；缺取消ACK不表示已撤销 |

对已经不属于当前run/slot/operation代次的回执只作历史核对，不用它关闭或恢复另一个新操作。存储失败先在进程内关闭新派发，恢复后不自动继续；无法持久化时不假报已落库，跨重启仍按DF02默认关闭。参考模型用一个volatile_closed标志表示此项前提，没有运行真实进程故障。

RecoveryPreview纳入活动槽、原触发决策与prior_execution_id，plan逐步声明retain_success／execute_new／reconcile_commit。retain须原command及合格成功证据；execute_new须固定参数引用并在批准范围内创建新command；reconcile_commit只提交已证动作的业务状态，不能与新设备写混装。unknown原终态不改；资源核对引用和计划批准由权威提供者取得，用户不能勾选忽略。列表超过4096必须拒绝而非忽略尾部。

## 4. 触发、一次执行与状态提交

EvaluationSnapshot固定inbox身份、receive_seq、run修订／源状态、artifact、时钟域、来源注册／观察／年龄证据及input_snapshot_ref。rule_result与transitions互斥；状态机空候选可no_match。转换集合必须来自固定程序中from_state和trigger匹配的**全部候选**，服务端核对集合完整性；调用方不能移除高优先unknown改变胜者。快照不是跨设备物理同时或分布式锁。

按C04原三值优先级规则选择：最高true并列→ambiguous；不低于胜者的unknown→evaluation_unknown；较低unknown不改变唯一胜者，但不豁免保护门控。Decision以`(authority,database,run,inbox身份)`唯一；重复同inbox只查原决策，digest或receive_seq被换成其它内容则冲突。未见过但序号不高于已处理高水位的事件记录suppressed_obsolete；busy／inactive亦记录抑制，均不排队或在恢复后补发。

accepted时同Seamer事务写decision、execution、run/slot修订、活动执行和审计。先分配execution_id写入decision，再算decision_digest，ExecutionBinding引用它；snapshot先生成，避免摘要环。绑定核对scope/run/artifact、snapshot/inbox/receive_seq、源状态、输入快照、selected_transition的目标状态。任一失败回滚，不留“决策已接收而执行身份丢失”。读API的非accepted decision可无snapshot，但accepted/no_match/unknown/ambiguous必须有完整快照引用。

保护不通过即锁存paused；表达式true不能替代dispatch_eligible或最终出口许可。相对延迟仍占active_execution，不因为event原TTL已过自动取消，也不因恢复补旧等待；具体延迟锚点、阈值与预算机器记录仍须与C06的逐步时窗归并，本目录没有把这些缺口暗写成已完成。

R5核对active_execution、固定artifact/arm代、source_state修订、全required完成证据、门控及无未决；单事务写目标state、execution结果、run修订和固定event_id outbox。rule无business_state不伪造状态行。重复确认已提交执行只取同event，不再加修订或重发设备动作；设备全部成功但未提交须明确reconcile_commit。远端接管迟到时保留已提交历史并记录偏离，不能承诺跨服务物理原子。

## 5. 暂停、解除布防、退役与接口边界

pause/disarm/retire接受后立即本地停止新派发并进入paused，保存operation；这不等于Controller屏障生效。逐目标关闭／屏障Ref准确关联后可标protection_complete；它只证明规定覆盖的闸关闭，不证明未决命令成功或资源clear。pause可在仍有未决时完成保护并保持paused；disarm需核对所有在途／释放后disarmed且保留槽；retire再CAS释放槽并completed。任何不确定保持paused/indeterminate；新版本只能在旧run退役后显式创建／布防。

ProtectRun沿用expected_run_revision，冲突409不能伪报已暂停；系统自身的保护闭闸不依赖GUI的过时CAS。服务主体仅限本组织已授权run暂停，不能disarm/retire/resume。新run.disarm/run.retire为候选独立权限；create/update未布防草稿可human或service，publish/arm/resume只human。后续需并入DF01逐操作主体矩阵及SDK exports，不能认为现有71操作清单已经包含本批。

24操作的路径／模型以OpenAPI为准：保留原定义/运行/预检/恢复接口，新增metadata、历史program/artifact、活动槽、disarm/retire、操作/执行/决策与请求lookup。所有操作必需精确X-LeafSeamer-Contract；旧写协议不得降级回退。human写请求同时要求bearer和CSRF／Origin校验，service凭据是另一互斥认证分支；OpenAPI的两个Bearer声明不证明服务器已识别主体类别。全部响应no-store；只读POST也不建立运行许可。202是可靠受理，201发布/创建亦不表示布防。

错误：401/403身份与对象范围；404无权暴露的不存在对象；409修订/槽/同键异内容/单次消费竞争；412基线/期限失效；413线字节容量；422编译与语义非法；429运行容量；503关键存储或保护不可用。错误字段不泄参数。标准状态码只描述API语义，提交未知仍查原身份，不能凭网络超时换键重试。

## 6. 持久化映射和验证边界

Seamer实体键至少包含authority/database范围；definition_draft、metadata、published_version与artifact/proof不可变内容分开；activation_slot主键不含版本；run、execution、trigger_decision、evaluation_snapshot、preflight、recovery_preview、operation、request_result、outbox和逐目标prepared_binding由一个writer事务归属。唯一键分别覆盖定义版本、单run活动执行/恢复、inbox决策、preview单次消费和请求身份；发布CAS、arm/R2占槽与消费、decision+execution、保护受理、R5+outbox不可拆提交。

本批明确字段和事务归属，**尚无这些完整领域表的SQL迁移**。FK/触发器及证据实体映射、延迟/边沿/预算和全部来源输入、R4逐步命令映射、公共SDK及IPC同版归并继续列为设计交付，不用内存模型代替。归并期间禁止重新使用旧Request/Run字段宣称新语义已被服务支持。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_contracts.py --check-report
```

参考检查含结构/HTTP投影、三值仲裁、基线/目标关联、串行模拟的竞争和回滚、重复事件/响应丢失、迟到回执、R5及outbox。可信身份、能力、完成/释放和实际Controller目标均由夹具提供；不是HTTP、数据库并发、故障恢复或设备验收。报告绑定八份输入，可用--staged核对暂存字节，核对不重跑；EX12—EX18、EX25—EX31及AU全运行验收仍未执行。特别是完整转换候选集、发布编译事务与保护关闭的实际提供者不在参考模型覆盖内。
