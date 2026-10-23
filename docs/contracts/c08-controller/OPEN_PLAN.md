# 开放计划、原ACK与ready提交契约

状态：待审阅，`gate-open-plan/0.1.0-draft.1`。本候选为内部持久对象和提供者关联，不新增HTTP端点，不改变IPC0.8线上消息。定义源为[build_open_plan.py](build_open_plan.py)，[Schema](open-plan.schema.json)仅接受具名defs，根不可直接校验。

已知事实：现有OPEN正文已包含完整控制/gate/授权字段与运行拒绝、取消拒绝和参考时间快照；ACK回显token、gate修订和三快照身份。[有序出口设计](GATE_ORDER.md)已要求相关状态改变使旧开放计划失效。现有137表主要覆盖命令、取消和资源保护，没有完整控制权/open/ready物理表。（来源：[IPC0.8](../df03-service/ipc.schema.json)、[保护通知布局](controller-protection-outbox.sql)。）

基于这些事实，本轮推荐冻结以下四类不可变对象和字段提供者。原ACK证明曾应用该次OPEN；当前ready必须持续满足当前状态与租期，不能把历史ACK当成持久可写权。

## 字段、摘要与所有者

| 对象 | 具体字段 | 提供者及绑定 |
| --- | --- | --- |
| OpenPlan | plan_id、revision=1、binding、state_refs、basis、body、selected_tick_ns、expires_tick_ns、plan_digest | Controller单writer在当前一致点创建；body直接引用原OPEN_GATEBody，不复制另一套线上结构 |
| Binding | scope(authority_service_id/database_instance_id)、controller_boot_id、worker_boot_id、writer_exit_id、ipc_session_id、device_id、device_session_id、clock_domain_id、descriptor_digest | 已纳管出口和当前运行域记录；来源端不能自选exit或用同名设备替换旧连接 |
| StateRefs | control、gate、authorization、resource，均为id/revision/digest | 同库当前控制/闸、授权策略及设备资源投影；这里是完整设备资源状态引用，不只是某条释放记录 |
| Basis | kind=activation/resource_recovery/gate_recovery，record_ref | 初次生效、资源故障恢复、仅闸恢复分别取对应已提交记录；不强迫正常首次开闸伪造资源事故，不重复转交已effective持有人 |
| OpenDispatch | dispatch_id、revision=1、plan_ref、frame、reserved_tick_ns、dispatch_digest | 唯一会话发送器预留完整OPEN信封；完整正文必须与计划完全相等。这里只证明已持久选择，不声称已经写到socket |
| OpenAckEvidence | evidence_id、revision=1、plan_ref、dispatch_ref、frame、received_tick_ns、observer_receipt_ref、evidence_digest | 可信接收器保存原OPEN_ACK及来源收据；reply_to精确指本次OPEN的message_id |
| ReadyCommit | ready_id、revision=1、plan_ref、dispatch_ref、evidence_ref、state_refs、committed_tick_ns、ready_digest | 单writer在再次核对当前条件后，同事务保存采用、审计、状态投影及事件通知；返回结果不能先于可靠COMMIT |

各自摘要为整对象仅排除其自身顶层摘要字段后的JCS/SHA-256，带sha256前缀。嵌套摘要保留，不能递归删除同名字段。引用单向：Plan→现有状态及依据；Dispatch→Plan；Evidence→Dispatch/Plan；Ready→三者。无反向自引用摘要环。revision=1的不可变对象需要新内容时创建新id；当前状态指针另增修订。计划与信封分开，因此计划不预分配IPC seq。

新候选计数使用0或无前导零的至多20位十进制字符串，尾换行拒绝；不是uint64承诺。旧IPC借用模型的完整词法修正仍由SDK统一归并，本检查不宣称实现严格原始JSON解码。所有Ref须按完整三元组比较，不只比id。摘要验证只能证明内容一致，不证明授权或来源。

## 取证与准入规则

1. **计划创建/入流**：真实当前Binding、四StateRefs、Basis均需精确相等；关键存储、运行域、basis、完整屏障、资源和当前权限有效，设备无保护。body的device_session/clock/descriptor须等于Binding，control_epoch/control_version/gate_revision/authorization_revision/token/barrier须匹配当前控制记录。三份快照既验证自身摘要，也与当前完整批准快照逐对象相等，不能只验证摘要正确。
2. **来源隔离**：运行拒绝controller_scope、取消拒绝scope和参考时间domain的authority/database均等于Binding.scope；取消快照device等于目标设备；参考时间domain的clock/descriptor匹配当前受监督单调域。时间provider_boot可以不同于设备worker_boot，不能误要求同一进程。参考时间是否合格及每个动作是否需要UTC仍由原时间Guard判断，展示/闸快照不授设备动作时间资格。
3. **期限**：`selected <= now < expires <= lease_until <= 当前批准的最大租期终点`；预留发送满足`selected <= reserved <= now`，ACK满足`reserved <= received <= now`，ready提交满足`received <= committed <= now`。全部tick在同一绑定域，等号到期拒绝。若真实COMMIT跨过期限，历史记录可保留但不得发布当前ready或派发；发布和最终发送均重新判定。
4. **信封**：两个方向seq各由独立接收/发送账本提供，不互相比大小；message_id、seq、reply_to、会话、两进程、设备和clock/descriptor逐项匹配。ACK没有writer_exit字段不能省略exit验证：通过鉴权会话注册表和observer收据映射到计划exit。重算一个跨会话ACK的摘要不改变身份。
5. **ACK采用**：可信observer必须证明实际鉴权对端、方向、当前会话完整序号处理、原始字节到解析对象的一致性和本域接收时刻；提供精确原件与收据Ref。ACK精确回显token/gate及运行、取消快照revision/digest，以及参考时间snapshot三元组。结构可解析或模块自填verified/durable均不满足此条件。
6. **ready**：实际持久Evidence和Ready须与本次对象完全相等，采用引用不变，四StateRefs仍当前，计划仍有效且全部前提继续成立。新保护、换出口、撤权、租期届满、相关快照或资源修订变化立即使当前ready投影失效，历史Ready不删改；不自动回退到先前有效计划。

## 持久映射与失败路径

拟由Controller库独占保存`gate_open_plan`、`gate_open_dispatch`、`gate_open_ack_evidence`、`gate_ready_commit`及对应提交/审计关系；表名是映射建议，尚未创建这些物理表。完整control/gate状态与屏障原件表须先具备，不能用非空BODY代替以下外键和全集核对：

- Plan：scope/exit/设备连接、四状态修订及类型正确的basis到已提交原件；同scope/exit/gate_revision与gate_token只能对应一个开放计划。资源恢复basis链接137表`cr_recovery_commit`及其完整关闭选择，activation/gate_recovery链接对应控制生效/恢复记录。
- Dispatch：Plan与出站message_id唯一，`(ipc_session_id, direction, seq)`唯一，完整编码前逻辑帧不可改。预留记录必须先于写调用；预留后进程崩溃或提交未知不复用该seq继续原会话，而是关闸并结束会话，避免线上缺号。不得为追求连续seq而在无持久记录时发送OPEN。
- Evidence：接收去重身份和observer收据、原字节引用与Dispatch关联；重复只返回已存原件，同身份异内容属于协议故障。陈旧但真实ACK可留历史，不采用为ready；不会因为数据库不可写而凭内存ACK放行。
- Ready：与状态投影、审计和通知同事务，四当前状态修订用CAS，证据不能跨Plan借用；逐设备当前ready只能选一条记录。事务失败/不确定撤本地ready并紧急关闭；查原用于确认历史，不能重新发送原OPEN。

这份映射明确了未来DDL必须表达的关联，尚未证明实际外键/唯一性或事务完整性。下一步将它与完整控制/gate/屏障原件归并后再运行SQL缺写、逐写回滚及竞争验证，不能将本轮对象Schema直接称为完整数据库实现。

## 正反例与验收边界

[check_open_plan.py](check_open_plan.py)用独立本地Registry校验四模型并运行关联判定，固定预期覆盖错scope/域/会话/exit、相关状态变化、三快照、两个方向序号、重算摘要后的错配、到期等号和不确定COMMIT。正例人工构造为同一完整场景，不沿用旧结构夹具的松散reply_to或混合scope；旧文件和旧预期保持原样。

报告[open-plan-report.json](open-plan-report.json)绑定8份输入，`--check-report --staged`只核字节，不重跑。参考判定里的stored_*、observer_verified及当前资源/授权状态是合成前提，限制反例明确展示伪造全部前提仍可通过；真实提供者必须从上述可信入口取得事实。没有运行真实鉴权、时钟采样、数据库、并发、IPC或设备，也没有将本候选切为SDK权威源。
