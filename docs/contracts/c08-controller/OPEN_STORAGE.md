# 开放记录、关闭恢复与安全代次的SQLite候选

状态：待审阅，178表组合。定义源为[open-storage.sql](open-storage.sql)与[生成器](build_open_storage.py)，生成[controller-open.sql](controller-open.sql)。在[161表控制屏障](CONTROL_FENCE.md)之后增加17表，按[开放生命周期0.2](OPEN_LIFECYCLE.md)区分T5前态CAS和提交后资格。本文件不是生产迁移或部署批准。

## 事实与设计选择

已知事实：原库已有完整控制历史、T3/T4、两类签发、资源核销和关闭通知；`cr_risk_hold`表示未可靠释放的占用，包含正常在途。上轮参考模型已复现T5更新投影后旧ready自失效的问题。本轮实际运行内存SQLite，检查完整组合的事务约束；没有运行产品writer、磁盘、IPC或设备。（依据：[控制屏障](CONTROL_FENCE.md)、[资源布局](resource.sql)、[上轮契约](OPEN_LIFECYCLE.md)、[本轮报告](open-storage-report.json)。）

基于这些事实的设计：复用同库控制历史作为控制安全身份的来源，`go_authority`选择最新非ready、非gate_protect的控制状态。纯闸展示变更不转交控制权；接管、拒绝、unknown和重启仍产生新来源。资源安全代次使用只增事件账本，关闭、撤回和恢复都留新事件，不能通过删除风险或清空集合复活旧ready。

## 字段、所有者与映射

| 表/视图 | 具体责任与关联 |
| --- | --- |
| go_hazard | device_id、20位revision、source_kind/source_id；恢复事件另有recovery_id到提交的延迟FK。真实来源插入触发新代次，事件不改删，不能凭无来源字符串制造记录 |
| go_snapshot / go_hold / go_snapshot_commit | 当前exit、完整控制前态、控制安全来源、安全水位、授权/完整资源/三快照Ref、采样与截止、提供者原件；hold全集关联真实cr_hold并保留owner_ref、控制安全来源和分类；快照封存核完整集合 |
| go_gate | 单出口不可变闸历史、精确record_revision后继、线上gate_revision/token/barrier/lease；ready只存原始ready_id防摘要环；fenced行表示已选择的新开放前态，不单独证明worker执行 |
| go_plan / go_plan_commit | snapshot及两个前态、activation/resource_recovery/gate_recovery依据、期限、原Plan和新Proposal摘要；一个前态gate只创建一个Plan，恢复记录只消费一次 |
| go_dispatch | 原Plan、出口、message_id、独立出站seq、预留时刻及原帧、outbox、审计；只表示选择，不表示写到socket |
| go_evidence | 原Dispatch、出口、reply_to、独立入站seq、可信接收时刻、原ACK及提供者验证、gate与三快照回显；过期真实ACK可保留历史 |
| go_ready | Plan、原ACK、输出ct_state/go_gate、提交时刻、Ready与Transition摘要及完整原件；与ct_commit双向配对，不能半边提交 |
| go_close / go_close_ack | 保护控制变更、逐出口连续关闭修订、原因、关闭outbox及原ACK；尚无gate的新增出口允许gate_id=null，不能借其他出口或旧闸记录 |
| go_recovery / go_recovery_target / go_recovery_commit | 指向同事务新快照、恢复时刻及原件；完整采用每个出口最新关闭与精确ACK；ACK唯一消费，封存后不可增补 |
| go_revocation | 原开放或关闭ACK的永久撤回，保存原因与审计，不删除原件；撤回同事务推进安全代次 |
| go_exit_obligation | 已受控制设备的新出口与`registration.<exit_id>`关闭记录双向身份绑定；缺关闭登记不能提交出口 |

所有表由Controller单writer持有，设备模块和GUI不能直写。库内计数为补零20位十进制TEXT，线上继续使用无前导零U20；生成器用两段整数计算后继，避免SQLite有符号64位溢出。SQL中的`*_ref`文本字段应保存提供者确定的完整Ref编码，BODY保存具名Schema的完整不可变原件。当前夹具仍用合成短文本；SQL外键和非空约束不证明Ref/JCS、线帧解码或提供者真实性，不能据此跳过统一SDK的严格验证。

控制安全Ref的完整摘要投影仍由提供者从绑定控制历史计算；`authority_state_id`是其不可变来源关联，不是把完整公开ControlRecord摘要直接冒充安全摘要。完整资源快照Ref及分类同理；正常占用的owner必须由命令/取消归属提供者证明，SQL目前只核真实hold全集、给定归属和已知unknown/unresolved状态。

## 原子写集与状态转换

1. **快照封存**：当前control/authority/exit同设备，控制时钟域及描述符与出口相同；采样不早于控制记录，同设备采样次序前进；安全水位等当前事件最大修订。`go_hold`与全部`cr_risk_hold`双向差集相等，隐藏占用也必须包含。原件、成员和审计同事务。
2. **计划封存**：当前控制无pending，当前gate为fenced；四前态及快照仍当前，`sampled <= selected < expires <= snapshot.expires`且`expires <= lease_until`。activation必须关联仍有效的T4，已有关闭历史则必须显式恢复。资源恢复同时关联原cr_recovery及新gate恢复；首次开放不伪造资源事故。
3. **发送与接收**：Dispatch只有一个，先可靠保存原帧/outbox再进入有序发送器。ACK按独立方向去重，reply_to、出口、gate及三快照精确回显；`reserved <= received`。接收晚于计划截止不丢历史，但T5仍拒绝。完整会话序号与实际字节真实性须可信接收器证明。
4. **T5**：新增ct_change.kind=ready与ct_state、输出go_gate、go_ready、ct_audit/outbox/commit同事务。输出仅变gate展示与完整投影修订，不改变holder、effective_version、预留版本或pending。最后ct_commit再次核当前前态、快照、安全水位、原件和`received <= committed < expires`；版本后继及新摘要也检查。
5. **当前候选**：`go_ready_candidate`持续核控制安全来源、三个拒绝/时间快照、授权、安全水位、完整资源全集、当前闸和撤回。正常新快照可维持资格；异常或恢复后水位改变，旧ready不复活。该视图**不含实际当前tick**，不能直接用作当前ready响应或发送许可；读取方必须在绑定时钟域重核计划/快照/lease期限、运行域、权限及完整Guard。
6. **关闭保护**：新增ct_change.kind=gate_protect，与控制protected投影、全部当前活出口的go_close/outbox和审计同事务。有效退役可排除，退役证明撤回后仍需覆盖。新出口通过延迟FK强制同事务登记关闭；存在其他活出口时也必须完成全量关闭写集，不能只补新出口。
7. **恢复**：先写go_recovery并自动推进安全事件水位，再写同事务新快照、完整目标选择与提交。快照精确采用此次恢复的新水位，旧快照不能借恢复提交。逐出口选择最新关闭，已有原ACK只能消费一次；第二次恢复须重新关闭并取得新原ACK。原关闭记录、消费和旧恢复永久保留，不覆盖历史。

关闭ACK不早于其控制保护请求；ready及gate_protect不能相对同控制链回退单调时刻或偷换时钟描述符。跨运行域重建须走监督恢复，不把这类字段变化当普通T5。COMMIT未知继续按既有规则撤本地资格并紧急关闭，重新打开只查原历史，不重放旧OPEN。上述时间检查依赖提供者传入真实tick，SQL不会自己采集时钟。

## 安全事件与故障边界

安全水位的实际来源包括资源释放失效、资源验证撤回、已采用控制屏障证明撤回、命令unknown/unresolved提交、两类unknown报告、关闭、开放/关闭ACK撤回、恢复及新出口。来源触发器与原记录同事务，`go_hazard`额外校验确实存在相应设备来源；任一写失败回滚全部事实和水位。派生保护与当前资格不依赖事件消费者最终赶上。

| 故障时序 | 必须结果 |
| --- | --- |
| T5写了输出gate但缺控制commit/审计/通知 | 延迟FK或封存拒绝，全部输出回滚 |
| T5选择之后、最终ct_commit之前撤回T4原件 | 最后复核失败，原件撤回及T5尝试同事务时全部回滚 |
| 已ready后新增完整资源快照，授权和安全水位未变 | 当前候选继续；每次新命令仍做资源仲裁 |
| 已ready后来源撤回或出现unknown | 同事务推进安全水位；旧候选不可见，历史ready保留 |
| 注册新出口却未登记关闭 | 外键拒绝提交；完整关闭写集才可注册 |
| 关闭后恢复目标遗漏新增出口或使用撤回ACK | 恢复封存失败，安全代次、新快照和选择均回滚 |
| 恢复提交前才发生关闭ACK撤回 | 不允许利用早先选择，最后重新核验 |
| 再次故障后试图复用上次ACK | 唯一消费/最新关闭检查拒绝；新关闭新ACK可完成第二次恢复 |
| 时刻回退、ACK早于请求、期限等号 | 拒绝；历史到期ACK可存，但不生成新ready |

原恢复可能已允许开闸，不能把原关闭ACK再次当成当前闸状态。`go_latest_close`保留完整历史但选择每出口最新一条；不同出口的旧ACK已被消费时，需要再次关闭该出口，不能只为一个出口生成新ACK便声称全域恢复。

## 已运行验证与剩余冻结边界

[检查器](check_open_storage.py)实际加载178表到内存SQLite，199项检查覆盖六写集的逐写缺失和主动异常全库回滚、T5前后资格、真实旧hold遗漏及旧归属、来源撤回、完整新出口关闭、两轮恢复、迟到ACK、到期及单调域边界。17张新表均用实际非空数据验证UPDATE/DELETE拒绝；所有实验库运行外键和integrity_check。预期手写，比较全库快照的结果只保存布尔，避免报告复制整库。

这不是真实并发、进程崩溃或磁盘故障；报告记录实际SQLite版本，不据此批准产品驱动。合成BODY与provider能满足SQL是已保留的限制反证。来源钩子及声明的全部平台组合仍需后续实施验收，199项不代表每个SQL条件分支全覆盖。

下一归并必须完成以下关联，不能以“已有开放表”替代：

- 新开放记录与逐传输最终许可、实际当前tick、正常hold归属原件、授权和预算提供者的完整绑定；目前**仍保留161表的普通/取消新签发临时阻断**，即使存在go_ready候选也不放行。必须在同版完成后解除，不能当最终产品方案。
- `cu_protection`、`ro_target`与本轮关闭记录之间的单一投递权威和精确来源关联；当前go_close已保证自身完整写集，但没有把所有旧保护目标自动转换为此类记录。退休无ACK恢复、换出口首次fenced依据也须统一，不能通过伪造ACK填补。
- 唯一会话发送器的全消息seq登记、原始帧与Schema/JCS原件的验证和完整字段映射；本轮出入站唯一性只覆盖开放消息，不能宣称已经覆盖全部46帧。
- 统一SDK、其余屏障/TIME及全业务库。阶段0未关闭；本候选和其报告不能部署，也没有修改业务代码。
