# C04：执行锚、逐步提交与未知结果持久化

本批为**待审阅候选**，存储组合版本提升为`automation-storage/0.1.0-draft.2`。以[recovery.sql](recovery.sql)的16表为基础，再加载[dispatch.sql](dispatch.sql)的9表，共25表；不是升级迁移脚本，不直接作用于已有数据库。保留[执行契约](../c04-execution/README.md)的字段和状态含义，不修改公共draft.4／IPC0.3，也不声称SDK已支持该存储组合。

**已知事实与本批边界：**原CommandSubmission候选已要求发送前持久标记、原请求查询及accepted/rejected持久回执；本批把关系落实为SQL与有限事务检查。外键只核对存在与关联，不能证明COMMIT已返回、时钟采样顺序、授权来源或远端拒收事实。（依据：[执行模型](../c04-execution/execution.schema.json)、[SQLite外键说明](https://www.sqlite.org/foreignkeys.html)。）

**推荐：**把“可以形成一个新的提交”“当前活路径可调用一次”“Controller已受理”“步骤有合格完成证据”分为四个发布点，任何一个阶段的记录都不能代替后一个阶段。

## 1. 表与SDK对象的映射

| 新表 | 内容及身份 | 约束 |
| --- | --- | --- |
| execution_plan_set | execution/run、完整选中计划BODY及digest、expected_steps、sealed、PLAN事务 | 与ExecutionBinding的plan_digest绑定；封存前数量及step_state覆盖匹配；封存后不增删改；reconcile_commit不得含action |
| execution_step_plan | (execution,step)、kind、ordinal、required、StepPlan BODY及digest | 固定参数/能力/完成政策/依赖在正文；只在计划未封存时插入；不以相同step_id覆盖另一execution |
| execution_anchor | ExecutionAnchor及origin_kind、start_id或完整TriggerDecisionRef、clock/tick、ANCHOR事务 | 每execution一次；必须running且计划已封存；恢复来源匹配本执行start，普通触发不虚构operation/start |
| step_ready | StepReady及plan_digest、anchor、clock/tick、完整依赖BODY/digest、READY事务 | 每步一次；与step_state.ready_id双向FK；同域且tick不早于anchor，重复唤醒不重新起算 |
| step_state | StepRecord的revision/state/outcome，以及ready/submission/terminal引用 | 允许转换图封闭；终态不重开；outcome与terminal配对，U20严格单调 |
| command_submission | CommandSubmission固定请求身份、请求BODY、parameters_ref、状态、attempt/adjudication指针、SUBMISSION事务 | 每步至多一个submission；整个远端身份唯一；只能action创建；与step_state反向绑定 |
| submission_attempt | 不复用attempt_id、submission、run、RuntimeBindingRef、clock/tick、ATTEMPT事务 | 每submission一个；与其attempt指针成对提交；绑定原ready同域和不倒退tick；禁止删除/修改 |
| submission_adjudication | RequestAdjudication的完整引用和受限正文、固定身份摘要、accepted/rejected、可空CommandRef、ADJUDICATION事务 | 同submission至多一个最终裁决；accepted才有command；完整target scope及request_digest匹配，两侧最终状态成对提交 |
| step_terminal | 一次终态、合格证据集合、可空结果Ref、STEP_TERMINAL事务 | 与step_state的终态/结果配对；只有成功可有result；action成功至少已有accepted，真实完成仍另验 |

单库scope仍来自storage_scope。远端请求唯一键为`target_authority,target_database,issuer_id,principal_id,request_epoch,operation_id,idempotency_key`，request_digest不进入唯一键：同键换摘要必须冲突，不建立另一请求。库列不是客户端自报权威；issuer/principal/epoch及target来自当前受信上下文。context/token等运输秘密不进入request_body、audit或event。

submission摘要由读取投影按当前状态、原identity、参数、attempt和adjudication重算；固定request_digest始终不变。CommandRef来自最终裁决，不把本地submission_id当远端command_id。完整Ref的revision/digest、BODY Schema及摘要、物理目标与批准参数由writer核验；SQL未实现JCS、完整JSON词法或设备权限。

计划完整性不能只检查expected_steps。writer必须由固定CompiledProgram和恢复计划重建完整选中路径，按step_id双向差集、phase/group/ordinal、required、能力/参数、所有依赖与窗口逐项核对，再一次封存。本SQL只检查数量、主键覆盖和reconcile的无写分支；同数量换掉一个步骤仍可能通过SQL，不能由此授予派发权。

## 2. 提交顺序与状态转换

| 阶段 | 短事务及前提 | 提交后的含义 |
| --- | --- | --- |
| PLAN | 当前执行绑定/完整计划合格，保存集合、所有StepPlan和waiting状态、封存、审计/事件 | R4或普通执行running前必须存在封存计划；不是开始设备写 |
| ANCHOR | 原触发受理或R4已明确提交；提交返回后采样，事务再核当前执行/域并保存一次锚和审计/事件 | 可以计算后续步骤的相对时窗；不能将事务内start_tick当提交后锚 |
| READY | 当前依赖已满足、完整来源/窗口及执行资格有效，保存不可变ready和step_state及审计/事件 | 该步骤首次可开始；等待动作仍不占设备写许可 |
| SUBMISSION | 仅action；固定参数经当前能力Schema二次验证，当前预算/窗口和执行成立，保存planned请求与step.submission_pending及审计/事件 | 已固定原请求身份，尚未承诺已经调用网络 |
| ATTEMPT | 原submission仍planned；当前run/执行/域/ready/授权/参数/预算/窗口重新核验；保存标记、submission状态、审计/事件 | 只有拥有该事务提交结果的当前活路径可调用一次；标记本身不是可重放任务 |
| ADJUDICATION | 可信Controller对精确原身份返回持久accepted或永久rejected；保存完整裁决与submission最终状态，必要时step accepted，同事务审计/事件 | accepted只表示受理，rejected只表示原身份已最终拒绝；均不表示设备动作成功 |
| STEP_TERMINAL | 精确原command与完成政策、证据/结果Schema或未知判定合格；保存终态与step状态及审计/事件 | 成功结果才可供后继使用；unknown保留，迟到裁决不将其重开 |

StepRecord保持`waiting → ready → submission_pending → accepted → awaiting_evidence → finished`的正常路径；可从允许的前态转cancelled/indeterminate/finished。retained成功没有新submission；delay和reconcile_commit也不能创建设备提交。单次成功、未知、失败和取消均为不可变终态，资源是否clear单独取证。先后顺序受完整DAG约束，SQL状态图不是执行调度器。

步骤只能从waiting/pending开始，submission只能从planned开始；进入accepted或awaiting_evidence之前必须已有该步骤的accepted submission，最终裁决与其双向延迟FK在COMMIT验证。已受理步骤只有取得原命令的合格取消终态才可cancelled，接管、取消请求和本地超时本身不构成该证据；取消也不能通过R5或清除资源未决。检查器的terminal_evidence_verified只是这个可信提供者的合成前提。

`planned → attempt_recorded → accepted|rejected|indeterminate`；indeterminate只允许继续原身份查询，最终可信裁决可补accepted/rejected。它是“提交归属尚不明确”，与原Command或StepRecord已确定的unknown终态不是同一个状态域。步骤已unknown时，迟到accepted仍记录原command归属供核对，但不把步骤改回pending或成功。

当前活路径在ATTEMPT提交后、进入HTTP客户端前仍检查本地保护关闭和运行域；不通过就不调用，原标记保留并走query_only。实际最终设备出口仍由Controller的T2/guard/fence承担，不能承诺Seamer数据库与远端设备物理原子。HTTP客户端、代理、负载均衡不得隐式重试写请求；此次SQL不能证明网络最多投递一次。

## 3. 崩溃、查询与永久拒收

| 观察 | 允许的恢复动作 | 禁止的推断 |
| --- | --- | --- |
| planned且无attempt，进程重启 | 新域先保护核对；重新取得当前资格后才可能建立唯一新attempt | 不能仅扫描planned行自动发送 |
| attempt提交前事务确认回滚 | 原标记不存在；同原身份查询并按当前前提重新判断 | 不将存储错误一概当已回滚 |
| attempt提交后、HTTP调用前崩溃 | 仅查询原请求；即使研究者知道切点在调用前，恢复程序也不重发 | 不由“command_ref为空”证明尚未受理 |
| 请求已发、响应丢失／lookup not_found | 持久记录indeterminate及观察事件；继续原身份查询 | not_found只是此刻没找到，不是永久拒绝或允许新key |
| 非持久拒绝、代理错误、普通4xx/5xx | 保持未决，取得权威原身份裁决 | 不把HTTP状态码当永久拒收证据 |
| 可信accepted | 绑定原CommandRef，查询原command结果与资源 | ACK不是完成，不能直接R5 |
| 可信永久rejected | 保留原身份拒绝墓碑；新执行需按F07重新预览和批准 | 不回退planned，不在原step换key重做 |
| StepRecord已unknown，后到accepted | 补submission裁决，原step unknown不变 | 不恢复旧执行，也不把设备当前同值当原command成功 |

永久拒收必须由拥有原请求命名空间的Controller，在与其受理唯一性相同的writer和持久身份账本中裁决：原请求已accepted则只能返回其command；否则原完整身份+摘要写入不可逆拒绝墓碑，随后任何迟到原请求均拒绝。Controller备份恢复不得删除该拒绝依据或复活旧request_epoch。撤销发送方context、关闭连接或等待TTL都不能替代该记录。完整拒收请求/回执Schema、HTTP或IPC端点及Controller侧事务尚需下一版归并，本批只保存经过可信提供者验证的引用，不把`durable=true`布尔值当实际证明。

用户重新做动作时仍分别核对原身份拒收/传输退役、原command resolution及资源clear，建立新preview、新execution、新command并保存supersedes；不能从submission.rejected单独推导全部资源已安全。没有最终证据时可以持续查询和显示未决，不能靠删行腾出唯一键。

## 4. R5与恢复库存衔接

加载执行层后，R4 start和execution running要求计划封存；R5 SQL拒绝计划未封存、步骤仍pending/unknown/blocked/expired/cancelled、required未成功。optional明确failed仍需Q72完整独立依赖证明、批准错误类及资源释放；SQL放过该形状不证明这些语义。原恢复检查器只加载基础16表，新增检查器加载25表并实际验证“已有accepted但无完成证据”的R5回滚。

submission_recovery视图只返回`fresh_gates_required / query_original_identity_only / observe_original_command / retain_final_rejection`四类读侧建议，没有“重发设备命令”分类。启动仍先按DF02/T8关闭旧资格；数据库恢复分类不能授予权限或清除pause latch。

所有新事务沿用transaction_record/event_outbox成对持久审计与通知。观察not_found等使用SUBMISSION_OBSERVATION，只有最终裁决用ADJUDICATION；通知可重复投递同event，命令请求不进入outbox。事件流epoch/sequence、完整来源去重及归档下界仍需C05及容量设计归并，不能把当前固定事件ID表当最终事件总线。

## 5. 复验与剩余工作

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-storage/check_dispatch.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-storage/check_dispatch.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-storage/check_dispatch.py --check-report --staged
```

实际检查包括：恢复与普通触发两种锚来源，当前门控与时钟域，plan/ready/submission/attempt/receipt/terminal不可逆关系，每条写语句后及COMMIT前主动中断的25表全快照回滚，半边关系直接COMMIT拒绝，响应丢失及重复查询，not_found／非永久拒绝不重发，迟到accepted不重开unknown，核对提交无新动作，ACK不能过R5；另覆盖不得自造accepted、awaiting_evidence正常完成、取消请求非终态证据及合格取消不提交业务成功。报告绑定两份SQL、两检查器、本稿、执行Schema和两份主稿共8输入，staged仅核字节。

证据限制：所有授权、当前采样、参数Schema、完整计划、预算/窗口、完成与拒收来源均为人工夹具；BODY/digest是合成占位，未执行JCS或完整对象关联。普通触发用人工构造的已受理前态，不包含TriggerDecision/inbox的真实原子事务。没有运行HTTP、IPC、网络发送、磁盘/WAL、真实并发或设备。离线通过不关闭C04或阶段0。

仍待落实：普通触发/发布完整事务、delay直接依赖边消费及最终Guard、edge/budget持久化、完整参数/结果提供者、Controller原身份拒收接口与恢复下界、C05/C06及SDK同版归并。上述功能范围保持不变，先补齐系统方案再业务实现。
