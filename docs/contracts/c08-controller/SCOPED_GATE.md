# 限定取消执行的发送范围候选

状态：设计候选，未批准部署；只细化[最终准入](FINAL_ADMISSION.md)已发现的冲突，不修改已确认draft.4或旧IPC0.8、178表及四个新签发阻断。完整46帧新投影为[IPC0.9](scoped-gate-ipc.schema.json)，[定义源](build_scoped_gate.py)和[局部模型](scoped-gate.schema.json)独立版本化。

## 已知事实与方案边界

已知事实：普通ready要求完整资源风险清晰，取消却可能正是为父命令unknown而执行；现有OPEN/ACK没有表示“只允许这一份取消ExecutionPlan”的字段。普通及取消已有共享issue水位、独立hold和两阶段关闭；关闭ACK的closed_device_ids是多设备集合。（来源：[开放存储](OPEN_STORAGE.md)、[取消契约](../c02-cancellation/README.md)、[IPC0.8](../df03-service/ipc.schema.json)。）

基于这些事实的推荐：单设备物理写闸始终只有一个当前GateAccess，purpose只能为ordinary或cancel_only。ordinary仍走完整普通资格；cancel_only只允许指定取消的全部批准primitive及政策许可的协议重传，不能发送普通动作或另一取消。即使父风险后来解除，cancel_only也不会自动升级。GUI保持protected，另显示“取消保护执行可用”和准确范围，不标全局ready，不恢复run，不改父命令终态。

## 字段与来源

| 对象 | 精确字段 | 提供者及持久所有者 |
| --- | --- | --- |
| GateAccess | access_id、revision=1、purpose、binding、control_authority_ref、control_epoch、effective_version、authorization_ref、resource_safety_ref、gate_safety_ref、protection、initial_assessment_ref、selected_tick_ns、expires_tick_ns、access_digest | Controller单writer在开放计划事务封存，关联ct_state、当前授权及两安全代次；binding含scope和全部出口/设备/时钟世代 |
| ProtectionScope | identity、policy_ref、ordinary_closure_ref、hold_ref、ownership_ref | identity必须是独立取消RequestKey对应的ExecutionIdentity及唯一ExecutionPlan；当前Requester取取消受理原件；策略取批准能力/Plan，closure取同取消当前有效ordinary原件，hold及Ownership取计划封存原件 |
| ProtectionAssessment | assessment_id、revision=1、上述完整共同域、protection、resource_ref、risks、sampled_tick_ns、expires_tick_ns、provider_receipt_ref、assessment_digest | 资源/授权联合提供者在同writer快照获取完整风险；回执先封存对应业务内容，不含AssessmentRef，避免摘要环；评估与其引用只追加，不覆盖 |
| Risk | hold_ref、ownership_ref、command_ref、execution_ref或null、classification | 完整当前风险全集，按hold_id升序且不得重复；每项与不可变Ownership及资源事实逐项比对，不接受客户端重标active |
| GateUse | permit_id、kind、gate_access_ref、identity、ownership_ref、guard_ref、protection_assessment_ref或null、selected_tick_ns、expires_tick_ns | 每次许可新增的范围子投影，取实际Guard/PermitAuthority及最终AdmissionSeal；不是第二套完整设备许可，不作为线上独立消息 |

对象封闭，计数为严格U20字符串，Ref精确比较id/revision/digest。摘要使用JCS，只排自身顶层摘要字段；不递归删除业务同名字段。旧wire PacketRef的双字段与准备记录三元Ref的映射仍沿用最终准入设计，不在此混用。固定历史源不被修改；生成器只投影具名模型，实例常量不重写。

保护评估须同时满足：当前无pending接管；Requester仍有当前控制及授权；ordinary已经可靠关闭，all尚未开始关闭；独立hold归当前Requester且active；来源回执、原Plan、政策、授权和运行域均未撤回。人工接管优先并不允许迁移旧hold或借用父actor。

父命令的旧ordinary hold可保留其真实旧owner及unknown/unresolved状态，由该能力批准政策逐项允许；这些项只获得“可以共存地执行本取消”的评估，不获得任何发送权或资源clear。相同父命令下的另一个取消hold也不是父ordinary风险，不自动被豁免。无关风险、stale、缺失原件、未批准分类、集合缺项/额外项或超过256项均拒绝，不截断集合。256仅当前候选结构上限，不是生产容量批准。

必须区分保护原因：可评估的父资源风险由完整Risk和政策决定；存储异常、监督/会话故障、当前授权撤销、接管pending、时间要求不满足、all关闭及无关设备风险仍是硬拒绝。不能把旧全局protected布尔整体忽略。所有来源须有明确分类及原件归属，无法分类按硬拒绝。候选参考模型的hard_protection_reasons及ordinary_ready由合成上下文提供，不证明已实现这些提供者。

## IPC同版联接

| 原消息/类型 | IPC0.9新增必需字段及含义 |
| --- | --- |
| HELLO / HELLO_ACK | 固定新版本，新增scoped_gate_access和immutable_hold_ownership两项必选特性；拒绝旧版本降级 |
| OPEN_GATE | gate_access完整对象；protection_assessment在ordinary为null，在cancel_only为完整初始评估；与initial_assessment_ref精确对应 |
| OPEN_GATE_ACK | gate_access_ref精确回显；原gate_token、revision及三个快照回显保持，state=open只表示该范围物理开放 |
| 普通ExecutionGuard / TransmissionPermit / GUARD_ACK | gate_access_ref、ownership_ref；不得指向cancel_only范围 |
| 取消Guard / Transmission / CANCEL_GUARD_ACK | gate_access_ref、ownership_ref、protection_assessment_ref；必须同一范围和当前完整评估 |
| CANCEL_GUARD | 另携完整protection_assessment，worker安装时核摘要与Scope/Guard引用，ACK回显原请求绑定；rejected回显也不代表已安装 |
| CLOSE_GATE / ACK | 维持原设备或Controller范围与closed_device_ids；每个已确认设备关闭其全部Access，不允许只关闭ordinary而留下cancel_only |

Guard摘要自然覆盖新字段；ACK本身不提供权威，必须关联原消息、方向、会话、原字节和可信接收tick。新Transmission也用于取消报告及四类屏障的覆盖成员，其新增引用随原件保留；不能在ACK覆盖中丢弃。其余46帧原条件、时间证据、面板来源和RUN/授权拒绝快照保留。Schema只约束形状，引用与当前性必须语义验证。

初始评估必须是OPEN处理时的当前完整评估。之后正常父hold释放不要求每个primitive重新OPEN：每次CANCEL_GUARD重新获取完整当前资源集合并绑定新评估；GateAccess保留初始Ref作为历史依据，发送使用当前Guard的评估Ref。两者必须保持相同ProtectionScope、控制/授权/安全代次及出口；任何新异常或恢复推进安全代次，原Access立即失效。初始证明被撤回仍撤销Access，后来的有效评估不复活它。

期限上界取原政策截止、控制/授权/运行域租约及OPEN原租约的最小值。评估另受资源快照有效期限制，每次发送仍重核当前tick；所有等号到期拒绝。新评估或重复OPEN不延长GateAccess期限。time_required=false只免参考UTC子条件，不免单调期限、域和其他保护。取消不继承父命令排期。

## 状态与故障顺序

1. 默认closed。新关闭证据确认、控制/拒绝快照完整安装及新的屏障代次形成fenced；新token、revision及唯一Access封存后才发送OPEN。
2. worker在同一设备串行闸核完整绑定和当前评估，安装后回复精确ACK；Controller可靠采用后才允许选择匹配范围的许可。取消采用记录与普通ReadyCommit分型，绝不伪造普通ready。
3. ordinary与cancel_only互换、换取消ExecutionPlan、换Requester或换运行域，均先关闭，再新屏障、新revision/token和新Access；不允许原OPEN原地扩大范围，也不同时保留两个写口。
4. 同access_id/revision和原内容重投只返回历史ACK，不重新开闸或续租；不同内容是协议冲突并关闭会话。CLOSE重复也只回原ACK，不重新关闭后来合法开放。历史ACK不能作为当前状态读取。
5. AUTH/CONTROL/TIME/RUN及CANCEL屏障仍按精确主体/时间要求/Requester来源选择；ordinary关闭仅永久拒父普通许可，all关闭永久拒该取消。命中当前范围时撤销其全部资格和已安装Guard，非匹配范围仍保持原精确选择语义。存储/监督故障及CLOSE_GATE关闭整个目标设备的所有范围。
6. 唯一发送器的候选保存AccessRef和本地安全代次，入流前再次核当前原件、同scope和完整Guard。保护后尚未入流的旧候选丢弃；已入流前缀保留传播窗口。worker在实际设备写闸再次核Scope、token、revision、域、当前Guard与期限，再消费唯一permit；消费后崩溃记unknown，不自动重发。
7. 任何COMMIT不确定撤本地资格，只查原事务；进程恢复先证明旧出口退役，新会话默认closed。不恢复旧Access缓存、Guard或许可执行。SQLite不能原子回滚已交给设备的字节。

AdmissionSeal下一布局须将GateAccess、完整当前Assessment/Ownership、普通ReadyCommit或取消ScopeCommit（二选一）及精确Guard/许可绑定为同事务最终准入。不能仅存一个passed布尔。采用对象、风险清单和全消息seq的物理外键，以及旧cu_protection/ro_target与go_close统一来源，仍需同版归并；旧四个签发阻断保留，不能把中间布局当最终产品功能。

## 验收和实际证据范围

| 场景 | 预期 |
| --- | --- |
| 父unknown、当前Requester独立hold、批准政策及ordinary关闭 | 只允许该取消Scope；普通派发拒绝，父hold保持原owner和unknown |
| 父从未发出、只有独立取消hold | 不要求伪造普通attempt；完整全集只有独立hold仍可评估 |
| 隐藏无关hold、父风险重标active、伪造回执并重算JCS | 精确原件/完整集合/批准Scope不匹配拒绝；全可信上下文被一起伪造可通过是模型限制反证 |
| 同display id而issuer_epoch不同、接管pending或授权换代 | 原范围失效；新主体不能借旧取消执行 |
| 父hold正常释放，下一Guard使用新评估 | 相同安全代次和范围可继续；旧评估拒绝，不提高GUIready |
| all关闭、政策/ownership/评估撤回、资源新异常 | 拒绝后继，已执行效果不回滚；同旧OPEN不复活 |
| 先OPEN后关闭后重复OPEN；先关闭后迟到OPEN ACK | 只返回历史证据，不能重新开闸或采用为当前发送资格 |
| 切换范围或复用token/revision；会话断开或序号缺口 | 必须新屏障，错会话或缺号终止会话；重启不重放 |
| 同permit重投及同ID换内容；新protocol_resend | 前者只查历史，冲突关会话；后者另取新许可/Guard且同包同执行，完整预算与重传政策仍必验 |
| 选择到入流及设备写之间接管 | 尚未入流淘汰；已入流按真实顺序处理，不能承诺瞬时撤回 |

[检查器](check_scoped_gate.py)验证生成一致性、完整46帧形状、新字段缺失与错引用、范围关联及单设备有限时序。旧46帧夹具只升级新增结构，不声称逐帧端到端语义已验证；完整Guard由显式合成前提代表。没有运行新SQLite布局、真实鉴权、网络IPC、OS监督、并发、磁盘故障或设备。产品实现前仍须完成上节列出的持久联接及统一SDK；运行验收留给实现阶段，不能无限追加同义设计来代替实现。

复验：`python docs/contracts/c08-controller/build_scoped_gate.py --check`，`python docs/contracts/c08-controller/check_scoped_gate.py --report`；`--check-report --staged`仅核暂存输入字节。
