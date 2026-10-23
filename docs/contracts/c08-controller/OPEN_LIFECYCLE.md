# 开放提交前后资格与资源安全代次

状态：待审阅，`gate-open-lifecycle/0.2.0-draft.1`。定义源为[build_open_lifecycle.py](build_open_lifecycle.py)，生成[Schema](open-lifecycle.schema.json)，[参考模型](open_lifecycle_model.py)和[检查器](check_open_lifecycle.py)只处理合成对象与原子副本。本候选显式修订[旧开放计划](OPEN_PLAN.md)第6条的持续资格规则，旧文件及报告保留历史；不修改公共API、IPC0.8或已确认的SDK权威源。

## 已知事实与修订理由

已知事实：旧模型在ready判定中再次调用计划判定，要求当前四个StateRefs仍等于计划创建前态；T5又需要发布新的ControlRecord和gate记录。参考检查现已复现：T5后旧判定返回`state_changed`。此外，[面板结果](../c09-panel/RESULTS.md)已允许正常在途时显示ready，[命令生命周期](LIFECYCLE.md)又允许合格的同attempt协议重传；因此资源占用不能一律等同未解决风险。（依据：[open_plan_model.py](open_plan_model.py)、[OPEN_PLAN.md](OPEN_PLAN.md)、[RESULTS.md](../c09-panel/RESULTS.md)、[LIFECYCLE.md](LIFECYCLE.md)。）

基于这些事实的推荐：把提交前完整CAS与提交后持续资格分开，同时把资源分配修订与资源安全代次分开。正常分配仍经过完整资源仲裁；故障、撤回及恢复均推进安全代次，旧ready不能借集合再次为空而复活。先明确这两个边界再落物理表，避免把矛盾固化到DDL。

## 具体对象与摘要

| 对象 | 字段与意义 | 写入与读取所有者 |
| --- | --- | --- |
| EligibilityRefs | control_authority、resource_safety、authorization，均完整id/revision/digest | Controller单writer从同一当前一致点读取，模块和GUI不能指定 |
| ControlProjection | record_ref、authority_ref、control_epoch、effective_version、mode、完整holder、pending_operation_id、gate_state | 控制历史与当前指针；holder含issuer_id/issuer_epoch/principal_id；automatic时为null |
| GateProjection | record_ref、完整Binding、gate_revision、gate_token、barrier_id、phase、ready_activation_id、lease_until_tick_ns | 每设备出口的闸记录；phase为fenced/protected/ready；activation只存ready_id，不反向含Transition摘要 |
| OpenPlanV02 | format_version、旧plan原件、eligibility_refs、control_before、gate_before、proposal_digest | 保存完整输入前态；内部复用旧Plan不改变其plan_digest |
| ReadyTransition | format_version、旧ready原件、proposal_ref、control_after、gate_after、eligibility_refs、transition_digest | 与T5两份输出历史、当前指针、审计及通知同事务提交 |
| HoldObservation | hold_ref、owner_ref、control_authority_ref、state | 资源权威提供全量未释放占用，state为active/unknown/failed_unresolved/orphaned/proof_revoked |
| ResourceSafetyEvidence | evidence_id、revision=1、device_id、observed_resource_ref、resource_safety_ref、control_authority_ref、holds、provider_receipt_ref、evidence_digest | 当前完整资源快照的可信分类结果；最多65536项，超出不能截断成合格证据 |

所有新摘要用JCS/SHA-256，仅排除自身顶层摘要字段，保留嵌套摘要。新proposal_ref使用旧plan_id、revision=1和**proposal_digest**，不能误用plan_digest；不同对象类型仍分开存储与解析。Transition引用Proposal，内嵌Ready引用旧Plan/Dispatch/Evidence；输出gate只保存原始ready_id，因此无摘要循环。Ref摘要必须指向实际不可变原件，参考夹具的摘要不证明真实来源。

`record_ref`是公开或内部投影的完整版本；`authority_ref`是独立控制安全历史的版本，不是给公共ControlRecord偷偷加字段。候选的统一SDK归并须显式选择新类型和版本，旧客户端不得降级或混投。

## 两个安全代次的生命周期

控制安全历史由控制writer独占。每条记录至少绑定scope、device_id、control_epoch、effective_version、mode、完整holder、pending_operation_id及单调revision；同时引用导致变化的原件与前一历史Ref。接管、新pending、拒绝、unknown、控制授权变化、重启或换运行域都必须生成新安全历史；清除pending或恢复到相同holder也不能复用旧revision。T5只改变展示闸状态及完整投影修订，不改变控制权安全历史。控制epoch改变须换历史身份，计数耗尽不能回绕。

资源安全历史由同库资源writer独占，至少绑定scope、device_id、control_authority_ref、revision、状态以及导致风险或恢复的完整原件Ref集合。正常当前控制权下的合格分配与释放只推进完整资源快照；unknown、未解决失败、孤儿、证明撤回、旧控制权残留或无法证明归属均推进安全代次并保护。恢复完成再次推进代次并引用精确恢复证据，不能把锁存清零后恢复旧代次。完整资源快照和安全历史必须同事务保持一致，空Ref或非空BODY不是来源证明。

资源分类的`active`表示所有权及当前占用可证明，不表示命令已成功。取消及其父命令可以同时拥有独立hold，但只有当前控制权及各自政策允许时才合格；旧持有人的未决hold即使字段自称active也阻断。所有未释放hold必须纳入全集，包括界面隐藏的项；集合按hold_id核对并拒绝重复。owner_ref必须由资源权威关联实际命令或取消原件，参考模型没有实现这份真实来源链。

## T5与持续资格

1. 创建计划、预留发送、最终入流及采用ACK时，重核当前Binding、四StateRefs、Basis、三个完整快照及EligibilityRefs。提交前control/gate投影必须与Proposal前态完全相等，control无pending、gate为fenced且无旧activation；保留原期限及完整屏障、原ACK来源要求。
2. T5不得借开放改变holder、mode、epoch、effective_version或pending，也不得改变OPEN中的gate_revision、token、barrier或租期。两份输出record_ref保持相同id，revision精确+1并生成新摘要，U20最大值不得回绕。Gate变ready并绑定本次ready_id；控制投影gate_state变ready。Ready原来的state_refs明确记录**输入前态**，输出Ref由Transition另存。
3. `transition_error`仅验证待提交写集；复用旧ready判定时设置的`ready_transaction_committed=True`只是局部计算前提，不是COMMIT证据。真实提交是否可靠由存储提供者决定，失败或未知不能发布ready。
4. 提交后读取当前ready时，不再调用提交前CAS。必须读取可靠提交的原Transition与Proposal，核当前Binding、资格三Ref、控制安全事实、gate激活、三个完整快照、存储/运行域/权限/依据/屏障状态和期限。当前control/gate及authorization引用必须与各自提供者一致；control记录须同id且不低于输出revision，同revision不得异摘要。当前gate仍完整等于此次输出。公开控制投影后来合法修订不单独撤销控制权。
5. 每次读取或签发仍重取当前完整资源证据，不能缓存“上次无hold”。仅分配修订变化允许继续，安全代次变化使旧ready失效。新的T2、重传及独立取消发送还须各自重新检查命令身份、预期控制版本、当前授权、资源独占/兼容、完整Guard、预算及时间；ready不替代任何命令级许可。
6. 期限仍为`committed <= now < expires <= lease_until`。COMMIT后的发布时刻不得早于提交前校验时刻；单调时钟回退保护且不撤销已发生提交的历史。COMMIT跨过expires时保留历史，但调用者必须按错误结果禁止当前ready发布和派发，不能仅看存储投影中的ready字符串。

## 故障时序与持久映射

| 时序 | 历史结果与当前行为 | 必需的持久关系 |
| --- | --- | --- |
| T4完成→OPEN入流→原ACK→T5 | T4保持protected；原ACK持久且T5可靠后才有当前资格 | Proposal前态与完整控制生效、Dispatch原件、Evidence原件、Transition输出双向配对 |
| 计划创建→新pending/撤权/资源失效→迟到ACK | 迟到ACK可留历史；旧Proposal不采用 | 前态CAS与资格代次同时核验；新保护进入既有有序关闭出口 |
| T5中写任一输出失败 | 原子回滚，不能半份控制ready或半份gate ready | 两输出历史/指针、采用、审计、通知、commit封存同事务 |
| COMMIT结果未知 | 本机撤资格并紧急保护；重开后查原，不重发OPEN | 不把内存副本当持久结果；换会话规则沿用有序出口 |
| 可靠COMMIT→发布前到期或时钟回退 | 历史可查，当前不放行；时钟异常保护 | 真实单调域提供者和发布前再判定，不能回滚已提交历史 |
| ready→正常占用→同attempt重传/正常释放 | 当前资格可继续，逐传输许可仍重新核验 | 完整资源快照更新；安全代次不因正常分配改变 |
| ready→故障→完成恢复且集合再次为空 | 旧ready不复活，依据新恢复记录另建开放计划 | 安全代次锁存，恢复显式消费原关闭证据，不能复用历史ACK |

下一物理布局应一次归并`go_plan/go_dispatch/go_evidence/go_ready`对应关系、control/gate完整历史与T5输入输出CAS、控制安全及资源安全代次、控制保护关闭/恢复消费，以及activation/resource_recovery/gate_recovery三类Basis的真实原件关联。命名是设计建议，尚未建立这些表。

必须保留[161表候选](CONTROL_FENCE.md)的旧许可与强事实；新布局只有在这些写集和最终签发复核完整后才能移除当前新签发临时阻断。不得把永久拒发作为最终产品方案。新Schema本身不会解除现有SQL阻断；本轮没有新增DDL，没有运行磁盘或IPC，也没有实现业务服务。

## 验证与冻结条件

[open-lifecycle-report.json](open-lifecycle-report.json)记录103项Schema/关联与副本检查，绑定13份原字节输入。包括旧模型自失效复现、前态CAS、输出严格后继、资格变化、完整资源全集、正常父子占用、恢复不复活、未知提交、三步副本回滚、期限等号及发布回退。Schema需按具体defs校验，参考函数假定结构已验证；可信stored原件、分类、接收器及权限仍由人工上下文提供。全量伪造这些前提可通过的限制反证保留，检查通过不能证明权威提供者真实存在。

提交前运行本检查及旧开放计划68项回归，核旧控制屏障73输入报告绑定；未改旧SQL，不扩大旧报告运行覆盖。`--check-report --staged`只核原字节，不重跑。SQLite、真实并发、磁盘故障、IPC和设备执行数均为零；U20真实最大值存储与代次推进事务须在下一组合中验证。阶段0关闭仍须完成上述持久关联、当前提供者的完整来源映射和统一SDK归并，并对本候选作实质审阅。
