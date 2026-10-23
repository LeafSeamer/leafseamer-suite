# 取消动作图与完成原件候选

状态：待审阅。以[119表关闭布局](CANCEL_CLOSURE.md)为底座，增加十表，形成129表离线组合。旧SQL和IPC0.8原样保留；本稿不生成可部署迁移，不修改业务代码，不批准真实动作。

已知事实：现有`ExecutionPlan`已定义有序primitives、after、独立protected_hold_ref和完整resource_keys；`plan_error`检查拓扑与批准原件，`send_error`依赖合成completed集合。119表的准备/传输已保存execution身份和摘要，却没有完整图及前驱完成原件的外键。（来源：[领域模型](../c02-cancellation/build_contracts.py)、[参考判定](../c02-cancellation/reference_model.py)、[关闭SQL](cancel-closure.sql)。）

基于上述事实，本轮推荐把图、完成裁决和每次发送实际采用的证据写入同一Controller库。本文的succeeded/failed/unknown是**取消primitive的内部裁决**，不替换父命令终态，也不直接产生公开CancellationOperation.confirmed。

## 1. 固定字段与所有者

| 对象 | 固定字段及约束 |
| --- | --- |
| cg_plan | execution_id主键、cancellation_id唯一、execution_digest、ordinary_closure_id、policy_ref_body、protected_hold_ref_body、三个集合数量及完整plan_body；与plan_commit双向延迟FK |
| cg_resource | execution/resource_key唯一；完整动作所需足迹，不按当前已发送动作裁剪 |
| cg_primitive | execution/primitive唯一、连续position、action_ref、parameters_schema_ref、parameters及completion_policy_ref的原字节投影 |
| cg_dependency | execution/primitive/predecessor唯一，两端真实primitive外键，前驱position严格较小；拒绝自环、逆边及不存在的前驱 |
| cg_plan_commit | 计划提供者引用、完整投影核验回执及审计；封存后资源、动作和边均不可追加 |
| cg_result | result_id、execution/primitive唯一、disposition、evidence_kind/digest/body、精确completion_policy_ref及共享issued_revision；与result_commit双向配对 |
| cg_result_member | 完整该primitive取消传输历史，含全部重传、已核销或未决许可，外键指已提交ci_cancel_commit |
| cg_result_commit | 证据提供者引用、验证、审计、outbox_id/body；失败/未知时outbox必须通知锁存并请求all关闭 |
| cg_revocation | 精确result_id、撤回原因、审计和保护outbox；不删除旧结果，不产生新的可执行成功 |
| cg_dispatch_dependency | 每个新permit采用的全部直接前驱及其result_id；与原图和结果复合FK，且与发送提交配对；发送后不可补写 |

Ref正文须保存完整id/revision/digest规范投影，不只保存id。SQL目前将Ref和参数作为非空BLOB保存；可信提供者须核验其Schema、JCS、当前资格、完整对象身份及与完整原件的逐字段相等。SQL只验证本稿列出的关系，**数量相等不能证明没有把一条必需边换成另一条边**，不能以占位BODY或客户端自报validation代替提供者。结果提供者还须证明证据覆盖全部传输，且符合该动作的completion_policy；transport ACK不属于本候选的成功证据种类。

资源和primitive各最多256，边最多32640（256节点全部前向边），是沿用领域数组上限后的关系上界，不是吞吐批准。共享U20水位包含普通与取消所有签发，结果建立及封存时均对当前水位核验；不得只取本primitive的max。图的position从1连续到primitive_count，wire中after仍按原ID排序，SQL不把插入顺序当wire顺序。

## 2. 状态、事务及故障时序

1. **计划固定**：有效ordinary关闭、取消仍requested且尚无all切点时，写Plan→全部资源与primitive→全部边→提供者回执/审计封存，一个事务。每次取消至多一份计划；重启查原，不另建执行ID。准备记录必须引用这份已封存的计划、原摘要、primitive和ordinary关闭。
2. **动作结果**：写Result→全部传输成员→验证/审计/通知，一次提交；成功必须至少有一次真实已登记的取消传输。可在未发送时记录确定失败或未知；这不把不存在的发送伪造为not_sent。裁决不可改写，迟到事实仍通过原报告账本记录，不将unknown改成可放行的succeeded。
3. **后继发送**：共享签发→取消传输→原packet关联→全部直接前驱的当前有效成功→发送commit，沿既有原子写集提交。签发与最终commit均检查执行锁存；commit核对全部依赖及原件未撤回。缺边、缺结果、错primitive或仅有ACK均不放行。不能用同事务先预写空选择、再封存结果或撤回来绕过最后检查。
4. **失败、未知或撤回**：提交原结果或撤回及其通知后，`cg_stopped`永久可见，禁止该执行的后续新准备/传输及协议重传；并行已发动作保留其真实历史，迟到结果仍可记录。任意祖先撤回均锁住整个执行，故即使直接前驱仍成功，后继也不能继续。这里不应用Q72的普通简单规则可选步骤继续政策。
5. **关闭与资源**：锁存触发的保护outbox应驱动既有all切点及逐出口屏障，随后再进行效果核对和资源释放。SQL中的禁签发不代表worker已关闸；锁存前已持久许可可能在保护传播窗口进入传输。已发动作不回滚，不因撤回旧证明而补发或退款预算。

计划、成员、结果、采用和撤回全部只增；UPDATE、DELETE和REPLACE被拒绝。缺写由延迟FK或封存守卫拒绝，事务回滚同时撤销依赖选择及签发水位。COMMIT结果未知只查原身份；查不到不自动创建第二计划或重发设备动作。

## 3. 独立保护占用与剩余归并

**当前不能直接将protected_hold_ref指向父命令cr_hold。** 普通hold绑定普通attempt和普通T2发送，而取消可能发生在父命令从未派发时。候选下一步须在同一设备资源权威中登记取消自己的保护占用：完整足迹和独立身份、允许与被保护父命令的占用关联共存、仍排斥无关新命令；晚到强事实允许多风险占用并存，不能用唯一锁拒收事实。释放须覆盖该取消所有传输及all关闭，失败和重启不能自动释放。不得为满足FK临时制造普通attempt，也不能把缺少独立hold变成禁止cooperative的最终产品方案。

本轮`protected_hold_ref_body`仍是待联接字段，**尚未证明独立占用、完整保护outbox、权限/时间/预算提供者或证据撤回到已释放资源的传播**。尤其结果撤回已锁住后续签发，但尚未将其因果链绑定cr_release的证明依赖；已释放资源的重新保护必须在后续同版归并中完成，不能部署此中间布局。普通逐出口prepare、DecisionEvidence及取消整体效果、其他屏障/TIME、最终SDK/IPC的字段归并仍待完成。primitive成功不等于all已关闭、不等于整体取消confirmed，也不释放设备资源。

## 4. 离线验收与复验

运行`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_cancel_plan.py --check`及同目录`check_cancel_plan.py --report`。`--check-report`仅核输入原字节；暂存区另加`--staged`。准确数量和版本见[cancel-plan-report.json](cancel-plan-report.json)。

- 正例：三动作依赖链、有效前驱放行、全部重传历史核对、发送前确定失败仍可持久化。
- 反例：未登记图、错计划摘要/动作、缺资源/动作/边/封存、自环逆边、结果漏重传、ACK冒充成功、错完成政策或水位、失败未知后继续、成功后重传、祖先撤回后绕过、签发中撤回、all切点后新计划、冻结成员追加及不可变历史修改。
- 故障：计划、完成原件和后继发送逐条缺写及主动异常，全129表快照回滚；撤回通知的同事务回滚；所有内存库foreign_key_check及integrity_check。

仅内存SQLite和人工权威夹具；不执行网络、真实writer并发、进程崩溃、fsync、提供者或设备。SQLite实际引擎由报告记录，不构成产品驱动/引擎批准。约束验证通过不证明可避免所有直播事故。
