# Controller 准备与签发回执候选

状态：待审阅；`automation-preparation/0.1.0-draft.1`，仅设计与离线参考。属于 C04/C02/C05 的既有缺口，不修改 draft.4、IPC0.3、生命周期0.1或保护IPC0.5，不实现服务。

## 1. 已知冲突与推荐解法

当前[生命周期参考模型](../c04-lifecycle/reference_model.py)的 reserve 从合成上下文预先取得完整 target_grants，prepare 要求回执与之相等。[ExecutionBinding](../c04-lifecycle/lifecycle.schema.json)又包含 grants；但实际 Controller 签发的新 grant ID、revision、正文摘要没有对应的预先分配契约。这些夹具不能证明真实签发顺序。

推荐把准备前意图、签发回执和执行绑定分开，避免相互引用的摘要环：

1. Seamer 的 arm/R2 事务固定 operation、run、definition_version、arm_generation、目标全集、已批准的计划和授权意图；先登记每个 Controller 的 preparation_id，再允许发送准备请求。纯零设备动作保持零目标准备，不调用本接口。
2. PrepareRequest 的 plan_ref 指向不可变 arm_plan 或 recovery_plan。恢复计划含已分配 execution_id、完整步骤/固定参数和批准范围，但**不含未来 grant 或最终 ExecutionBinding 摘要**。arm 的 execution_id 为 null。
3. Controller 核对配对来源、当前批准、计划及目标全集，签发实际 RunGrant；将 grant、PreparationReceipt、准备记录、审计与通知在自身同一事务提交。PreparationReceipt 的 grant_ref 摘要绑定完整实际 RunGrant；receipt_digest 只排顶层自身。
4. Seamer 在同一 writer 中验证回执，然后把实际 grant_ref 一次性写入对应 PreparationTarget。原先尚未签发的 target_grant_ref 为 null；允许的变化是 **null→该准备身份的唯一真实回执引用**，不能接受任意当前 grant，更不能覆盖已绑定引用。现有局部参考模型的预填 target_grants 不是本候选的真实字段提供者。
5. 恢复 R3 的全部准备完成后，Seamer 才能持久化最终 ExecutionBinding（包含实际 grants），再由 R4 核验并开始。普通 arm 完成只到 armed；后续每次触发创建各自 ExecutionBinding，引用该代次的准备回执。Controller 的准备回执不引用最终 ExecutionBinding，消除环。

arm 准备绑定整个运行代次，供该代次合法的普通触发使用；recovery 准备仅允许绑定其 execution_id。同一 Controller、origin_scope、run_id、arm_generation 只有一个准备身份，不能换 preparation_id 绕过关闭。新恢复仍增加代次。新 RunGrant 的 origin_scope 和严格计数复用[保护协议模型](../c05-protection/protocol.schema.json)，控制范围、Predicate 和 Validity 仍用旧具名类型；旧数值词法与严格解码缺口由 DF01 最终归并，本批不宣称全部修复。

## 2. 字段与权威归属

| 字段组 | 提供者与检查 |
| --- | --- |
| contract_version、operation_id、preparation_id、origin_scope、run_id、definition_version、arm_generation、mode、execution_id | Seamer 已提交 arm/R2 记录；ID 是不可复用身份，不是授权秘密。mTLS 配对主体必须拥有 origin_scope，不能由请求字段自证 |
| controller_scope | 接收端实际 authority/database；数据库替换不沿用旧准备资格 |
| operation_ref、plan_ref、artifact_ref | Seamer 持久不可变记录；核对 kind、scope、正文摘要及完整计划，三个 Ref 都不是客户端提供即可信 |
| approval_ref、authorization_digest、source_digest | 当前组织批准与来源前提；Controller 从受信提供者读取并比对。批准变化不被新 grant 的预期变化吸收 |
| controls | 本 Controller 完整设备集及逐设备 expected_control；device_id 升序唯一，与 grant_intent.device_actions 的设备集合相等，不能遗漏没有当前命令的设备 |
| baseline_grant_ref | 既有资格的精确引用或 null，用于 CAS；不得由新回执回填为“基线”。它不授权增大新范围 |
| grant_intent | principal_id、device_actions、parameter_constraints、validity；表达所需的精确授权，不由 Seamer决定 grant_id、revision、issuer、state。当前审批不满足时拒绝，不能静默裁剪后报告成功 |
| receipt.grant、grant_ref、commit_ref | Controller 签发和持久提交；grant 与意图逐字段一致，并绑定 run/definition/generation/origin，state=active。grant_ref.kind=grant，scope=Controller，object_id/revision/digest与正文一致 |
| receipt.request_digest、receipt_digest | 对完整 PrepareRequest／完整回执的 JCS SHA-256；带 sha256: 前缀。没有通用忽略字段，不递归删 proof 或元数据 |
| close_operation_id、protection_ref | 当前有保护权的 Seamer发起关闭；Controller 对同代次发布 RUN_FENCE 并持久化回执。closed 不代表在途资源 clear |

device_actions 按 (device_id,action_id,capability_version) 排序且唯一；parameters 的范围通过明确批准的 Predicate 语义核验，不将数组摘要相等当授权。每 Controller 最多256个 device_actions/设备，超过上限在准备前拒绝完整操作，不截断；总 Controller 目标上限沿用生命周期256。持久准备、墓碑、拒绝表及保护 outbox 容量须在准入前预留，最终 P0 数值方案另行归并。

## 3. 三个内部 HTTP 操作

所有操作仅供配对服务，要求精确版本头及 mTLS，返回 no-store。响应中隐藏其他组织对象，权限检查在幂等查原之前。

| POST 路径 | 输入/输出 | 权限与重试 |
| --- | --- | --- |
| /internal/automation/preparations | PrepareRequest → PreparationRecord，首次202、原件200 | automation.prepare；只允许签发已批准范围，不代替人员 arm/resume 批准。客户端不自动重投；未知后查询原身份 |
| /internal/automation/preparations/lookup | PreparationLookup → found/record、not_found/null或indeterminate/null，200 | automation.prepare.read；只读，不创建准备或 grant |
| /internal/automation/preparations/close | PreparationClose → PreparationRecord，首次202、原件200 | automation.protect；原执行 grant 失效不阻止当前有保护权的主体收紧拒绝。允许同身份单调拒绝重投，不授设备重试 |

准备身份键：(controller_scope, origin_scope, preparation_id)。operation_id 属于请求正文，不能借同 preparation_id 改所属操作。请求摘要固定，异内容409；相同原件仍需当前读取权限，但不因旧审批/控制版本已变化重新签发。未知后 lookup=not_found 不证明准备从未受理，也不允许另起ID；采取 close，完成保护后由新预览/新代次重新准备。

close 携带完整原 PrepareRequest 及其摘要，不要求先取得 receipt；这样可以在准备响应丢失或准备请求尚在网络中时建立精确墓碑。首次 close 的身份键增加 close_operation_id；同键异内容409。多个独立关闭操作可指向同一准备身份，各自记录，均只收紧同一代次拒绝。不能覆盖原请求、回执或其他操作结果。

**close 先到：** 当前保护鉴权和请求归属成立后，在 Controller 同一事务保存原请求身份/关闭墓碑、发布该 run 的 deny_through_generation，并登记完整保护目标。后到 prepare 只能返回 closing/closed，绝不签发 grant。无需仍有效的旧动作授权，否则无法可靠关闭失效准备。

**prepare 先到：** 可靠 applied 回执固定不变；close 立即使该准备不再准入新命令，并执行完整 RUN_FENCE。旧 in_flight/unknown 保留原状态与资源证据。旧 applied 回执可以作为历史返回，不能当当前 active 资格。

## 4. 状态与命令受理衔接

PreparationRecord.state：accepted→applied/rejected/indeterminate/closing；applied→closing；indeterminate→closing；closing→closed。rejected和closed不可复活；rejected可被追加关闭审计，但仍是拒收状态。状态变更与 revision 精确加一同事务；相同幂等查原不改 revision。applied_receipt 一旦存在永不替换，closing/closed保留它；applied 必须有回执，accepted/rejected不能含回执。closed 必须有 durable protection_ref。

indeterminate是“不知道是否可靠完成”，不等于可重签。崩溃恢复先查持久原件：已有 applied 只返回原 grant；缺失或无法证明则关闭/核对，不能自动补做签发。Controller重启默认关闭，旧回执不恢复当前 worker 闸门。

Controller接收[新 CommandRequest](../c05-protection/protocol.schema.json)时，从受信 Seamer读取 execution_binding_ref 的不可变正文，验证当前执行资格、完整计划/步骤/参数和实际 grant_refs，再关联唯一 applied 准备。必须同时满足：

- origin_scope、run、定义计数、代次、grant ID/revision 与准备及当前 RunGrant 一致；
- recovery 的 execution_id 与准备精确一致；arm 的执行属于该已布防代次，不能因 arm 请求 execution_id=null 就免验执行；
- 请求 step_id/logical_action_id、设备/能力/参数与该执行固定计划一致；ExecutionBinding 的 grants 包含该准备实际 grant_ref；
- 当前准备未关闭，代次高于拒绝下界；原权限、人工接管、资源、来源、时间及最终发送门控全部成立。

上述完整可信上下文来自提供者，不能把请求中重复填写相同字段当相互证明。准备过程中不得创建 DispatchIntent、投递设备写或开放旧队列。202/applied/armed/ready/running/设备完成继续分开。公共命令查询响应、所有 grant 管理接口、最终统一 SDK 及实际提供者仍需同版归并，旧 PUT RunGrant 不能成为绕过本准备记录的自动化准入入口。

## 5. 验收与证据边界

| 编号 | 故障/输入 | 必须结果 |
| --- | --- | --- |
| PRE01 | arm 无 execution；恢复有固定 execution | 分别绑定代次/单执行；无伪造未来 grant 引用 |
| PRE02 | 同准备身份异正文，全部重新摘要 | 409，原请求与回执不变 |
| PRE03 | Controller已提交、响应丢失 | 查原取得同 grant；不重新签发 |
| PRE04 | close 先于 prepare | 先建拒绝墓碑；迟到 prepare 无签发 |
| PRE05 | applied 与 close 同时发生 | writer 串行；关闭后不准入新命令，历史回执保留 |
| PRE06 | Seamer超时/失败后收到 applied | 只补历史并关闭；不清 latch、不自动running |
| PRE07 | 改 Controller库、origin库、run/代次、plan或批准 | 即使摘要重算仍拒绝权威错配 |
| PRE08 | 目标少一项、重复、乱序或超限 | 完整拒绝，不裁剪成功 |
| PRE09 | grant多授动作、约束/期限变化或issuer不符 | 拒绝回执，暂停核对；不能覆盖首次绑定 |
| PRE10 | recovery回执用于其他execution；arm用于未批准执行 | 命令拒绝，不能仅靠相同grant放行 |
| PRE11 | 旧grant撤销后保护关闭 | 当前保护权有效则可关闭，不能以旧grant失效阻止 |
| PRE12 | 新代次或重启试图复用旧回执/准备ID | 拒绝；旧closed/unknown不复活 |

[生成器](build_contracts.py)与[参考检查器](check_contracts.py)的102项离线检查通过，覆盖固定Schema/OpenAPI、本地合成关联与串行状态快照；[报告](reference-report.json)绑定本目录5份输入及3份来源Schema的原始字节。未执行实际身份提供者、HTTP、SQL事务、并发、WAL、时钟或设备。PRE01—PRE12运行验收全部待执行，检查报告不替代这些证据；close先到的检查使用已保存的closed快照，不声称已经执行关闭事务或故障注入。

复验：`python build_contracts.py --check`、`python check_contracts.py --report`；提交前使用 `python check_contracts.py --check-report --staged` 只检查输入字节。最终字段提供者、公共命令全路由投影及最终权威迁移尚未完成；不关闭阶段0。

## 6. 准备子域物理布局

[存储契约](STORAGE.md)和[14表SQL候选](preparation.sql)给出完整请求/设备集、连续状态修订、唯一grant/receipt、关闭操作/完整保护目标、拒绝下界、完成引用与commit/审计/通知的配对写集。先关闭不能后签发；先签发再关闭保留回执，重复独立close操作不复活rejected或增加无变化的状态修订。拒绝下界的全表snapshot_revision和逐run deny_revision分别精确增长，最终必须与通用保护接口共用一个权威账本。

[独立内存检查](check_storage.py)的430项断言通过，[存储报告](storage-report.json)绑定四份输入。运行 `python check_storage.py --report` 重跑；`python check_storage.py --check-report --staged` 只核暂存字节。原102项协议检查不因此增加SQL覆盖。参考SQL不是生产迁移，BODY/完整出口提供者、共库scope/deny及执行屏障FK、P0和P1—P4归并、真实鉴权/IPC/并发/磁盘与设备运行仍须完成。
