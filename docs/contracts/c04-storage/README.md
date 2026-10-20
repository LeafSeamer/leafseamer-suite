# C04：恢复核心的SQLite事务候选

当前组合版本`automation-storage/0.1.0-draft.2`，**待审阅、未批准**。承接[生命周期](../c04-lifecycle/README.md)、[执行阶段](../c04-execution/README.md)及[DF04](../../rebirth-df04-storage-design.md)。[recovery.sql](recovery.sql)仍为基础16张表、恢复分类视图及约束的唯一源；新增[执行层](DISPATCH.md)在其后加载9表，合计25表。此版扩展事务phase与存储版本，不是旧库升级迁移。[恢复检查器](check_recovery.py)仍独立只加载基础16表，在`:memory:`运行固定合成事务，不是Seamer生产writer；新增执行报告独立验证25表组合。

**已知SQLite行为：**复合外键中任一子键为NULL时不强制父行存在，双向延迟外键可以等到COMMIT核对；外键须每连接在事务外开启。STRICT仍可能把整数无损转换为TEXT。错误语句不保证整事务自动回滚，应用必须判定事务状态。（来源：[外键](https://www.sqlite.org/foreignkeys.html)、[STRICT](https://www.sqlite.org/stricttables.html)、[事务](https://www.sqlite.org/lang_transaction.html)，2026-10-18核对。）

**本项目设计：**用NOT NULL、NULL配对CHECK及双向延迟FK固化恢复身份；可信writer仍负责完整语义、当前门控和整事务回滚。保留所有旧failed/unknown，恢复创建新execution。数据库约束不是当前设备许可；新runtime启动一律关闭派发。

## 1. 领域范围与字段映射

一个Seamer数据库固定一个`storage_scope(authority_id,database_id)`。本库ID在该scope内唯一，公开Ref入库前必须与其精确相等；禁止将另一scope的同名ID解释为本地对象。`external_evidence`保留远端authority/database/kind/object/revision/digest，不能对Controller命令建本地FK。单库scope并非多租户授权，组织／主体／对象权仍由writer核验。

| 表 | 映射及稳定身份 | SQL负责的边界 |
| --- | --- | --- |
| storage_scope | 数据库身份和存储候选版本 | singleton=1、禁止替换与删除 |
| published_version | PublishedVersion的definition/version；artifact完整BODY与manifest摘要 | 联合主键、不可变；BODY仍须Schema和JCS核对 |
| run | RunRecord当前revision、arm_generation、lifecycle、活动operation/execution与last_commit | 版本归属固定，修订严格单调；completed不重开 |
| activation_slot | 定义级唯一槽，不含版本的主键 | run/definition/version复合FK；paused/disarmed不能释放给新run |
| business_state | 状态机run的state/revision/last_commit | 新状态匹配同run的提交目标；rule不创建此行，由writer检查 |
| recovery_preview | RecoveryPreview完整BODY、plan摘要、run/slot修订、原执行、同域半开期限 | 内容不可改，消费一次；consumed_operation与operation双向FK |
| recovery_operation | RecoveryOperation的固定身份、模式、完整targets及resolved_latches；可变state/revision/start | 一preview、一execution、一请求身份；paused/indeterminate不回ready |
| execution | ExecutionBinding完整BODY、generation、plan及源/目标状态投影；trigger/recovery来源分支 | 恢复来源与operation双向绑定；普通触发保留完整decision引用；旧failed/unknown/paused不可在该ID重开 |
| external_evidence | 已验证后保存的远端准备／完成／释放引用与BODY | 精确远端身份+revision唯一；不能覆盖为新摘要 |
| preparation_target | (operation,controller)，完整设备和baseline→target在BODY中 | applied必须有preparation类回执；target不可改、不可删；ready后不增目标 |
| recovery_lock | 每operation的持久锁墓碑；run上release=NULL至多一个 | 锁与operation双向FK；释放须release类证据，释放一次，禁止删除 |
| pause_latch | 不可复用latch_id，run、原因及产生修订，正文保留resolution引用 | 同原因多个实例并存；仅可一次绑定同run的start |
| transaction_record | R2/R3/R4/R5、business_id、run、固定event及脱敏audit BODY | (phase,business_id)唯一，和event双向配对 |
| event_outbox | 固定event_id、tx、payload原字节和摘要 | 不可改/删，只允许通知；不放设备写任务 |
| execution_start | ExecutionStart正文及run/slot/op修订投影、mode、摘要、R4事务 | execution/op各至多一个start；与其反向start指针配对 |
| transition_commit | R5执行与状态转换、全部证据集合、固定R5事务 | 每execution一次，与execution.commit指针双向配对；rule的状态字段全NULL |

此批不是整个C04完整DDL。`execution`能保存普通触发的旧执行，使恢复预览可引用它，但普通TriggerDecision本体及其原子受理尚未建表，当前引用正文由writer核对。执行锚/步骤/CommandSubmission已由[执行层](DISPATCH.md)补充；普通触发受理、发布编译事务、草稿与metadata、delay依赖边、edge状态/决策、预算账本及C05/C06输入还须同版归并。公共draft.4／IPC0.3保持原样；不能拿本SQL启动功能缩水的Seamer。

BODY存UTF-8规范对象字节BLOB，摘要字段带不带前缀以对应SDK类型为准；本SQL不自行实现JCS，也不把BLOB当不受限制的自由数据。writer先严格解码、按具名Schema和语义规则验证、计算正确投影摘要，再核对查询列与正文一致。检查夹具的BODY和digest是明确占位，未做这些验证。SQL对Id、version、digest的完整词法也委托已冻结SDK入口，不能直接接受外部SQL参数作为权威。

U20列用严格十进制TEXT，长度加BINARY词典序比较，不经过SQLite INTEGER/REAL。SQL只保证单调和有限词法；可信writer必须在同一事务读旧值，用精确整数计算+1，检查上限，再CAS且检查影响行数=1。测试覆盖超过int64的真实SQL存取，并保留“跳到3仍能通过单调CHECK”和“INTEGER 9转成TEXT”的限制反证，不能把它们误报为原始报文已通过严格解码。

## 2. 四个事务的写集与发布点

所有事务先当前认证／授权及存储资格，再查询原请求结果；同身份同内容返回原结果，异内容冲突。过期预览在已受理请求的历史lookup中不再次消费。actor_identity是权威ActorKey按确定投影生成的规范BLOB，不能从用户任意JSON取得；请求唯一键沿C04 lifecycle：本库scope＋request_epoch＋actor＋operation_kind＋idempotency_key。运输context_id换新不产生第二请求。

| 阶段 | 事务内重新核对 | 原子写集 | 明确COMMIT后 |
| --- | --- | --- | --- |
| R2 | run paused、原槽、预览未消费与run/slot CAS、当前域和`[issued,expires)`、完整计划/旧资源、无未释放恢复锁、权限和容量 | operation、new execution、锁、全部固定targets、preview消费、run/slot/generation推进、审计/固定事件 | 返回202；run仍paused、dispatch=false；仅可开始准备 |
| R3 | operation仍preparing、完整目标集与预期grant、回执真实/持久/精确归属、当前基线 | 逐目标准备证据；全部满足后operation ready及审计/事件 | run仍paused。允许逐目标独立保存历史回执，但不能因迟到回执复活paused/indeterminate操作 |
| R4 | run/slot/op CAS、active execution、ready、当前完整目标/旧资源/计划/授权/窗口/预算、精确未清latch集合 | ExecutionStart、两侧start指针、只清批准latch、run running且清active_operation、op running或reconciling、审计/事件 | execute可进入后续步骤资格检查；reconcile_commit仍禁止设备派发 |
| R5 | 当前执行/arm代/产物、源状态CAS、全required合格证据、无未决及当前门控 | transition_commit、execution succeeded、业务state/revision（rule除外）、run修订及清活动执行、op completed、经核验的恢复锁释放、审计/事件 | 对外发布原固定事件；重复请求只读原结果，不再次运行设备 |

R3的旧表述“准备后即可running”由本批明确纠正；只有R4独立开始事务能做该转换。R4的start_tick仍是事务内观察，不是提交后ExecutionAnchor：锚必须在提交成功后另采样并可靠保存，基础SQL不包含锚，新增执行层另表承接；`dispatch_eligible`列仍不是实际可发送的完整判据。

事务内不等待HTTP/IPC/NTP/设备。R3逐目标回执允许先写不可变证据；全部ready时writer逐项对账完整target集合，并核对current control/authorization基线。参考检查为有界两目标合并事务，只验证合并写集回滚；逐目标异步接收器、receipt序号去重及完整远端来源不在本批实现范围。

R5释放的是Seamer恢复互斥锁，不直接释放Controller资源。`release_id`引用须说明本operation已终结、全部准备grant已明确转交当前run继续使用或经撤销核对、相关资源核对完成；不是要求R5撤销仍供已布防run使用的全部grant。kind='release'只做类别约束，不证明事实。无完整释放证明时可保持锁，不为了完成状态显示而填合成证明。所有本批成功路径的release真实性都是人工前提，实际来源需后续归并。

## 3. 不确定提交、接管与在途命令

| 故障切点 | 本地可确认事实 | 后续动作 |
| --- | --- | --- |
| R2写入一半、提交前失败 | 确认回滚后，预览/新执行/锁均未受理 | 仍用原身份查询；仅确定未受理且当前前提成立才重新受理 |
| R2提交后响应丢失 | 原请求、消费和锁已存在 | 返回原operation；不能换key消费同preview |
| R3部分Controller准备、另一个接管 | 已准备的目标可能仍持grant | paused/indeterminate并保留锁及完整目标；定向撤销与核对，不因迟到ready自动R4 |
| R4前又出现同reason新latch | 原批准集合不再完整 | 拒绝开始；新latch不得被按reason批量清除 |
| R4提交后、执行锚保存前崩溃 | start存在不证明任何命令已提交 | 新进程闭闸并核对；不自动补锚继续执行 |
| 命令标记后、远端受理结果未知 | 本地没有command_ref不能证明未受理 | 沿原CommandSubmission身份query_only；本批outbox不承载重传任务 |
| 设备动作成功、R5前接管或源状态变化 | 设备效果不等于业务提交 | 保留原成功证据和业务旧状态；人工新preview的reconcile_commit重新核对 |
| R5提交后、通知丢失 | commit和固定event同时存在 | 只重投同通知或查原结果；不再次加状态修订、重执行设备 |
| COMMIT未知/FULL/IOERR | 单靠RETURNING或异常不能判定未提交 | 立即关闭新派发，按原业务身份/tx查询；不能读库则保持未知 |

同一writer中的接管／撤权锁存与R4/R5按串行提交先后裁决；跨服务远端事件仍有传播窗口，不能承诺物理同时阻止。真实P0保护处理器必须主动关闭并记录latch，参考检查只是先插入latch再尝试事务，不模拟线程或网络竞争。

## 4. SQL强约束与可信writer的分工

数据库直接拒绝：预览消费无operation、operation缺新execution或锁、start缺op/execution反向绑定、commit缺execution反向绑定、事务缺event或event缺事务、错run/版本、换请求内容、墓碑删除/REPLACE、终态重开、错误证据类别、清除消费和重复清latch。外键全部开启，递归触发器开启以覆盖REPLACE触发的删除；不允许业务临时关闭这些开关。

数据库**不能独立证明**：全部目标/步骤完整、授权与时钟新鲜、真实设备完成/释放、BODY摘要一致、恰好revision+1、R4后run投影全部同步、R5所需证据实际齐全。检查器保留一个FK通过但run仍paused的错误投影，并要求局部恢复核验拒绝它。完整启动核验还须遍历所有上述来源及C04余下表，不能直接把这个局部核验器用于生产。

恢复顺序：确认旧writer退出→核对库scope/schema及结构/FK→完整领域核对→按DF02/T8关闭旧运行资格→查询原请求和全部旧targets／commands→明确资源与权限处置→重新预览及人工批准。恢复视图只有分类，无可执行动作；`lookup_committed`也不批准自动布防。SQL禁止删除墓碑是本候选保守默认，生产保留/归档须先形成引用图和不可复用身份下界方案，不能无界留存当容量设计完成。

## 5. 验证入口与剩余交付

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-storage/check_recovery.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-storage/check_recovery.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-storage/check_recovery.py --check-report --staged
```

覆盖四种rule/state_machine与execute/reconcile组合、每条写语句后及COMMIT前主动异常、半边关系直接COMMIT拒绝、已提交响应丢失、原身份重查、同reason新latch、错scope/期限/集合/修订、超过int64的U20、终态和墓碑保护。所有故障回滚比较16张表全快照，不仅比较返回码。报告绑定本README、SQL、检查器、DF04与C04主稿的原字节；staged只核字节，不重跑。

这是实际内存SQLite约束检查，**没有运行**磁盘/WAL/掉电、双连接并发、生产TS绑定、HTTP/IPC、可信证据提供者或设备。目标和latch的正文在固定夹具中简化为ID数组，检查新项及完整集合，不证明完整Ref摘要／修订或设备列表关联；这些必须由正式Schema与语义提供者另验。Python内置SQLite版本在报告中记录，不等于产品引擎批准。既有EX/AU/DB运行用例继续开放。

执行锚、步骤和单次CommandSubmission已有[25表组合及独立检查](DISPATCH.md)，不扩大本恢复报告的16表覆盖。下一批须补普通触发原子受理、原身份永久拒收的Controller契约、delay直接依赖边消费和edge/budget账本，再与C05/C06、身份和内部协议同版归并。恢复核心成文不关闭C04，也不代表全部系统方案设计已完成。
