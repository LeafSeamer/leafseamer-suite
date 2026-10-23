# 逐传输最终准入与不可变占用归属候选

状态：设计候选，未批准部署。依据现有[开放生命周期](OPEN_LIFECYCLE.md)、[178表存储](OPEN_STORAGE.md)、[取消保护](../c02-cancellation/README.md)和[有序出口](GATE_ORDER.md)衔接；不更改旧Schema、SQL接受集或业务代码。

## 当前事实与本轮修订

已知事实：`go_hold.owner_ref`目前只要求非空，`authority_state_id`也没有外键到占用创建时的归属原件。旧SQL可让一个已在接管前存在的hold，在新快照中被标成新控制权的active，进而通过`go_valid_snapshot`。旧开放模型同样只比较当前提供者给出的标签。最终四个临时发送阻断仍阻止实际新签发，不能把此复现说成已能发送设备命令。（来源：[open-storage.sql](open-storage.sql)、[open_lifecycle_model.py](open_lifecycle_model.py)及本轮检查器。）

基于这些事实的设计修订：先冻结不可变占用归属及每个permit的主体投影，再将其接入同版最终签发写集。不能以补一个`active=true`或有非空验证BODY解除阻断。新增[Schema](hold-ownership.schema.json)及[参考判定](hold_ownership_model.py)只证明以下主体和原件关系，返回无错误不表示完整Guard通过。

## 具体字段和权威来源

| 对象 | 必需字段与约束 | 实际来源及持久要求 |
| --- | --- | --- |
| ExecutionIdentity | kind、command_ref、attempt_ref、cancellation_ref、execution_ref、requester、origin、source_ref | ordinary绑定命令受理身份及当前attempt；cancel绑定取消RequestKey及唯一ExecutionPlan。后两Ref与attempt互斥，不能借父命令actor |
| Principal | kind、issuer_id、issuer_epoch、principal_id | manual为human；automation为service。完整三元身份不能只比较显示名或principal_id |
| Ownership | ownership_id、revision=1、scope、device_id、hold_ref、identity、control_authority_ref、control_epoch、effective_version、clock_domain_id、descriptor_digest、acquired_tick_ns、source_receipt_ref、ownership_digest | 同创建hold的事务记录；关联实际cr_hold、命令namespace或取消namespace、ct_state及批准的来源回执。source_receipt独立在先，其内容包含本行业务字段，不反向包含OwnershipRef，避免摘要环 |
| PermitAuthority | permit_id、issued_revision、identity、binding、hold_ref、ownership_ref、control_authority_ref、control_epoch、effective_version、authorization_ref、guard_ref、packet_ref、ordinal、selected_tick_ns、expires_tick_ns、authority_digest | 每次初始或协议重传均新增一份；完整Binding沿用开放候选，包含scope及Controller/worker/IPC/设备/时钟各世代。Guard必须绑定这些精确字段，不能只绑定parent_command_id |

所有Ref比较id、revision和digest，摘要只排对象自身顶层摘要字段后使用JCS。Counter沿用严格U20十进制字符串，不转换为JS number。新对象均封闭且根Schema拒绝直接实例，必须选择具名defs。`PacketRef`在本候选表示可信准备记录的三元Ref；映射到旧IPC的packet_id/packet_digest和不可变字节Ref由归并时显式提供，不能直接把两种Ref当同一格式。

同一hold的Ownership只能创建一次。转交、撤权、换域和新会话不能覆盖旧行、追加“当前owner”覆盖它、或将新控制Ref填回旧行。旧占用保留其实际归属，后续只能可靠释放或核对；新主体若需要保护动作，必须创建符合当前取消操作身份和策略的独立hold。当前取消操作若已绑定旧执行，不能换actor继续原Plan。旧数据无需迁移，不设“缺归属就按当前holder补齐”的兼容入口。

普通占用与取消占用都绑定创建时的控制授权事实；gate公开投影ready/protected变化本身不改控制授权。manual发送须当前manual且完整holder相同；automation须当前automatic、holder为空，并另核当前服务凭据、精确RunGrant与执行来源链。自动化分支不能用“holder为空”省略授权。提供者须从实际RequestKey和Plan取身份，不能接受客户端自报。

`HoldObservation.owner_ref`在下一版明确引用Ownership，不能继续指向任意CommandRef。完整资源快照必须与实际风险hold集合双向相等；每个观察的hold_ref、owner_ref和control_authority_ref逐项绑定真实原件，随后才核异常分类及安全代次。原件已存在并不意味着其仍有当前发送资格。现有Schema只限制结构，回执提供者及其签发资格还须真实实现和验收。

## 最终签发写集和无环顺序

普通首次派发采用一个`BEGIN IMMEDIATE`写集：

1. 读取已提交控制和开放依据，核完整前态资源快照与真实tick；实际Guard来源、预算和授权有效性在同writer切点取得。
2. 分配本次attempt对应的hold，写来源回执及不可变Ownership；尚未提交的hold不能对外成为当前资源快照。
3. 写全局ci_issue、普通permit、传输正文/预算扣费/审计/outbox及命令dispatch修订；已有cr_hold_commit与传输commit的双向配对保持。
4. 完成hold_commit后，写包含新hold的完整**后态**资源快照及归属观察。正常分配只推进resourceRef，不推进resource_safety；旧风险不得被遗漏。
5. 写最终AdmissionSeal，绑定前态resourceRef、后态snapshot_id、OwnershipRef、ready/authority、安全代次、精确Guard与两种permit中的一条、最终采样tick。此处重核全部当前来源；反向延迟FK要求每条新ci_issue在COMMIT前存在此seal，不能先发布半边许可。
6. COMMIT确认后才供唯一发送器选择；COMMIT失败全量回滚，COMMIT未知撤本地资格并查原，绝不自动补发。选择入流前再次核实际当前时间、来源撤回、会话和更强保护；数据库提交不是设备副作用的事务边界。

步骤1使用前态ready资格；步骤5使用相同控制/安全代次及完整后态资源证据，不能用新hold反过来要求尚未存在的前态snapshot已含它，也不能在新hold已存在时仍用旧资源全集过门。建议新增Ownership及AdmissionSeal的物理表，禁止通过更新旧快照省掉前后态。其精确DDL、全Guard/预算提供者及全消息seq仍须同版联接，当前178表未做这一替换。

取消计划的独立hold在`cg_plan_commit`写集中生成Ownership并与`cr_hold_commit`封存；不要求存在父普通attempt或伪造普通permit。其后每个primitive和重传各自生成PermitAuthority及AdmissionSeal。前驱成功及全部祖先撤回、ordinary关闭、all尚未关闭、Requester当前控制/授权、packet原字节、预算、时间和完整资源仲裁都必须在最后seal及发送器重核，沿用已有语义。

## 保护取消与全局ready的冲突审阅

已知事实：当前`go_valid_snapshot`拒绝任何unknown/unresolved占用；现有取消策略允许为父命令创建独立保护hold，并要求ordinary闭合、all未闭合。若把普通`go_ready_candidate`直接作为所有取消的必要条件，父命令unknown会使保护取消永远无法开始；反过来全局放宽ready会误放普通写。（来源：[open-storage.sql](open-storage.sql)、[protected-hold.sql](protected-hold.sql)、[取消准入](../c02-cancellation/README.md)。）

推荐下一版显式区分**普通发送资格**和**限定取消执行的保护发送资格**，两者仍使用同一设备I/O闸和全局许可序列。保护资格必须绑定唯一cancellation/ExecutionPlan、当前Requester、精确设备/运行域、ordinary关闭证据、独立hold及完整风险集合；策略明确许可的父命令风险可被纳入评估，但不能清除、转移或标为正常。任何无关风险、all关闭或原件撤回仍拒绝。保护资格不使GUI显示全局ready，不授其他命令或其他取消执行权，也不自动恢复run。

这是对既有全局ready投影的必要细化候选，**本轮未批准、未编码为放行逻辑**。下一版必须明确物理闸接受的许可类别/执行范围、OPEN与ACK回显及最后校验位置，补入完整IPC；不能只在Controller跳过ready，而让worker继续只有旧布尔open。当前参考模型的cancel主体校验正例仅证明Requester归属，绝不证明这条完整保护路径已经可用。

## 故障与验收交付

| 用例 | 预期 |
| --- | --- |
| HAO01 接管后把旧hold标成当前active | 旧SQL/模型缺口被复现；新归属检查拒绝改标签，历史原件不变 |
| HAO02 改owner中的authority并重算摘要 | 与原件或独立回执内容不符拒绝；仅摘要正确不授权 |
| HAO03 同principal_id但issuer或epoch变化 | 拒绝；原请求身份及holder必须完整匹配 |
| HAO04 父命令actor不同，当前holder申请取消 | 独立取消RequestKey/Plan和hold可以通过主体子检查，不能借父actor或父普通hold |
| HAO05 接管pending、控制版本推进或授权引用换代 | 原permit主体投影失效；同holder后来取回控制也不能复活旧hold |
| HAO06 正常资源前后态及故障切点 | 实现阶段在完整DDL中逐写缺失/真实并发/崩溃验证，不能用副本或当前子检查冒充 |
| HAO07 选择后至COMMIT或入流前撤回 | seal及最终出口重核；已入流前缀仍按既有传播窗口处理，不声称撤回已发字节 |
| HAO08 取消父命令unknown而无关资源清晰 | 仅限定保护资格可评估；普通ready仍关闭，父风险不清，完整IPC轨迹待新版本实现 |
| HAO09 原运行域、设备session或原Guard错配 | 拒绝；协议重传也要新许可和新Guard，不迁移旧包到新会话 |
| HAO10 来源回执全部由不可信方伪造 | 合成模型可能通过，这是权威提供者限制反证；生产不能信任请求正文填入这些上下文 |

[检查器](check_hold_ownership.py)实际运行Schema、JCS和合成关联，并在原178表内存库复现旧归属标签缺口；没有新DDL事务实验、真实认证、发送、NTP、磁盘崩溃或设备运行。旧布局的四个签发阻断保持。剩余冻结项为上述AdmissionSeal物理联接、授权/预算/packet可信提供者、限定保护闸与完整IPC、旧保护目标统一来源及最终SDK归并；阶段0仍未关闭。
