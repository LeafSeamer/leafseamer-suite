# TIME 屏障、共享签发水位与持久化归并候选

日期：2026-10-23；状态：待审阅，`time-fence-registry/0.1.0-draft.1`。沿用已确认的应用参考时钟路线，不批准新运行 profile。本目录提供内部持久投影 Schema、有限参考判定和故障验收设计；不修改 IPC0.8、旧 SQL 或业务代码。

## 1. 已知事实与本轮分析

**已知事实**：IPC0.8 TIME_FENCE 同时携带普通业务锚、普通传输及取消保护传输；现有 91 表组合的签发水位和运行保护集合只从普通 ce_permit 读取。27 表时间采集组合的 ts_invalidation.protection_ref/ts_outbox 尚无设备 TIME cut 外键。不能把两组检查通过解释为已经实现完整 TIME 屏障。（来源：[IPC0.8](../df03-service/ipc.schema.json)、[取消协议第5节](../c02-cancellation/README.md)、[执行登记](../c08-controller/fence.sql)、[时间存储](../df03-collector/storage.sql)。）

**推荐方案**：Controller 唯一数据库 writer 维护一个普通／保护共用的签发序列。UTC 失效、该序列切点、全部目标、三份清单、拒绝下界与保护 outbox 同事务提交。Seamer 的本地时间失效不能直接写 Controller 的库或下界；它通过已有来源保护关闭自己的自动化，再由 Controller 本地时间权威独立判断 TIME。运行域失效同时走整域保护，即时动作也不能绕过。

## 2. 冻结记录和提供者

`registry.schema.json` 是本轮内部投影候选，根只按具名 defs 使用；Ref 定义与完整 Domain/Binding/Invalidation 直接引用固定 IPC0.8。不是新增网络入口，不接受 GUI 上传这些记录作为权威。

| 模型 | 字段与唯一来源 |
| --- | --- |
| Issue | permit_id、kind=ordinary/cancel、issued_revision、exit_id、packet_ref、transmission_ref、initial_permit_id、business_anchor_id、time_required、time_binding、disposition、resolution；来自已提交原许可／当前 Guard 与追加证据 |
| Exit | exit_id、clock_domain_id、descriptor_digest、retired；取已持久完整 ce_exit 和监督退役原件，不用“当前 worker”替代旧出口 |
| Registry | registry_id/revision、authority_service_id/database_instance_id、issued_head、exits、issues、registry_digest；只由同一 writer 的一致读提供，两个方向共享 head |
| Cut | cut_id、operation_ref、invalidation、registry_ref、issued_cut_revision、targets、cut_digest；引用一个固定来源快照而非分别读取两个最大值 |
| Target | exit_id、business_anchor_ids、ordinary_permit_ids、cancel_permit_ids；全部按 ASCII id 升序且唯一；空清单出口仍可能必须安装下界 |
| Attempt | barrier_id、cut_ref、exit_id、ordinal、previous_barrier_id；同 cut/exit 严格后继，旧失败不改变 cut 集合 |
| Ack | ack_id、attempt_ref、invalidation_ref、minimum_time_generation、effective_tick_ns、ordinary/cancel/business_coverage、ack_digest；仅当前原端点验证后存原文及投影 |

Issue 不是可执行许可。提供者必须逐项对账：ordinary 的 permit_id/issued_revision/packet_ref/initial_permit_id 来自完整 TransmissionRef，business_anchor_id 来自该 packet 的初始 IntentRef；cancel 对应独立 Transmission，business_anchor_id 必须 null。kind 由持久来源表决定，不能从请求者自行声明。time_required 取该次实际 Guard，并核原命令或取消政策；false 要求 binding 为 null，true 要求完整 Binding。更新 Guard 不改旧 Issue，只允许合法新传输形成新行。

普通重传的初始业务锚即使已经核销，也必须在 Registry 历史中，且属于同一 packet、同一出口和 ordinary 分支；business_anchor_id 精确等于初始 IntentRef 的 permit_id。取消重传的初始许可同理，不能借父普通命令的许可。同 packet/出口/分支不能另建第二个初始许可。当前 disposition 汇合原报告及**所有已持久原 ACK**的强事实，不等被采用；resolution=never_sent 遇到可信 in_flight 后重新视为未决，never_sent/unknown 的矛盾投影拒绝。effect_resolved 仍须其独立有效证明，TIME ACK 不生成它。

投影的完整性、原件等值、当前证明未撤回及读取授权由独立提供者保证。摘要只检测内容变化，不证明来源。参考检查明确把完整 Registry/已批准 Invalidation 作为人工上下文；不实现该提供者或产品严格解码器。

## 3. 一个序列与一个冻结切点

每个 authority/database 的 issued_revision 从 1 精确递增，普通与取消各次传输共用，U20 溢出停止签发并进入维护。事务回滚不消费序号；提交结果未知先查原身份，不能靠换号重发。发行号不是发送顺序，worker 的 gate_io_seq 仍为最终互斥依据。

本候选完整 Registry 保留从 1 到 head 的签发记录；已核销行和墓碑不删。结构上限 65536 条仅用于候选校验，不是生产容量承诺；生产必须更早进入受控维护，不能截断后宣称完整。将来分段归档需独立的连续性／完整性证明与摘要边界，未定义之前不得偷偷省略历史。

固定 cut 的选择规则：

1. 核当前 authority/database、Invalidation 完整原件，next_time_generation 必须是 old_binding.time_generation 的精确后继且不溢出；operation_ref 等于原件中的 protection_operation_ref。此引用必须指向独立预分配 OperationIdentity，不能回指含本 Invalidation 的 Cut 摘要形成环。
2. 先停止新旧代 UTC 签发。取同事务的全局 issued_head；先签发再失效则该许可在切点内，先失效则旧代签发被拒。即时许可仍受全部其他控制／授权／资源门控。
3. 匹配完整旧 Domain 的 UTC 传输，time_generation 小于 next_time_generation，且当前仍未决，纳入对应 ordinary 或 cancel 集合。无需 origin=automation：使用 UTC 的人工传输同样纳入。不同来源/profile 的旧代只要属于同一 Domain 仍纳入。
4. 纳入该 clock_domain_id/descriptor_digest 下所有未可靠退役出口，以及持有上述未决许可的已退役出口。没有未决许可的活出口仍安装下界，防止旧 Guard 继续发送。另一个域的出口不由本 TIME cut 冒充整域退役。
5. 每条普通传输都加入其原初始业务锚；初始锚可已核销，但不因此重发。取消分支不塞入普通业务锚数组。每出口两类传输各最多 256、普通锚最多 256、目标最多 256；字节及保护预留由实际 profile 再收紧。任何超限整体拒绝冻结，不截断，不把没有 cut 当作已关闭设备。

当前 State 的正常重新采样修订不是 TIME 失效：旧 Bundle 不再用于新许可，已消费/未知动作不重发；是否需要新守卫仍按原精确 State 绑定。TIME floor 只单调增加，恢复样本不降低它，不清自动化失败锁存。

## 4. 物理归并约束和原子写集

以下为必须落实的表／外键与事务要求，**本轮尚未交付合并 SQL**，旧 91/27 表不得直接拼接后宣称达标。

| 持久所有者 | 必需结构与原子边界 |
| --- | --- |
| issue_sequence / issue | 单 authority/database 单 head；kind 两分支互斥，permit_id 和 revision 各全局唯一；普通 ce_permit 与独立取消 permit 分别反向延迟 FK 到同一 issue，issue 再指向对应分支，任意半边不可提交 |
| issue_time_binding | 与每个 issue 一一配对，保存完整原 Guard Ref、time_required 和 Binding 原件／投影；不可只给 UTC 行补映射，否则遗漏行会逃过选择 |
| time_operation_identity | 预分配不可变操作身份与固定版本/摘要；与本次 Invalidation 和 time_cut 同事务，用独立身份摘要解除引用环；不能先对外发布孤立身份 |
| time_cut / time_target / time_item / time_anchor | cut 唯一绑定 ts_invalidation 与共享签发切点；target/item/anchor 与真实出口/两类 issue/原业务锚复合 FK；封存对来源集合双向差集且同时核分类快照 |
| time_deny / time_cut_commit | 失效 State/head、采集 STOP、设备 cut、UTC deny、audit/outbox 必须同一业务库事务；ts_outbox 的 time_fence 引用真实 operation/cut，不再只靠非空 BODY。拒绝下界按完整 Domain 保存；本机内存保护早于持久化，但不能伪称 worker 已闭 |
| time_attempt / time_attempt_failure | 不可变固定请求、同 cut/exit 精确 ordinal、紧邻前次、audit/outbox；cache_miss/deadline_elapsed 且原出口仍合格才新尝试，channel_lost 只能退役核对 |
| time_ack / time_ack_item / time_ack_anchor | 原 ACK 和三份完整覆盖、当前端点验证回执、审计同提交；双向 FK 加封存守卫防漏项。不修改旧 ACK；迟到强事实与资源风险/必要保护同事务关联 |
| time_target_adoption | 只能采用未失败的最新尝试，或该精确旧出口的监督退役原件；采用与目标结果同事务。退役不产生有效时钟 tick，不将 unknown 降为 not_sent |
| time_application | 所有固定 target 均有采用结果才封存应用、audit/outbox；空目标也要已封存的真实空集合。只证明本 cut 阻止后续 UTC 写和覆盖归档，不清设备副作用 |
| time_gate_snapshot | OPEN_GATE 的精确 Ref、完整当前 Domain/State 和 floor 与持久开闸意图绑定；ACK 后才能标记该出口完成时间同步，其他开闸条件另验 |

同一 writer 内应顺序执行：登记失效并推进本地 deny → 冻结所有三个集合 → 写审计/outbox及采集 STOP → seal → COMMIT。封存到提交之间禁止插入改变切点集合的 issue/退役/核销事实；并发由数据库 writer 串行，不以“时间戳相近”代替事务。失效事务失败或库提交未知时禁止新 UTC 签发，走 P0 应急保护及精确查原，不能恢复旧资格。真实存储容量已坏时无法保证落盘，须保留这个限制。

所有已有以 max(ce_permit.issued_revision) 定义切点的 RUN、取消及其他屏障必须同版迁到共享 issue 水位，选择集合仍按各自语义。仅替换 TIME 的最大值会造成并行两套 authority，不接受这种局部部署。Seamer 本地 27 表的存储归并独立完成，不需要伪造设备表。

## 5. 尝试、迟到证据与恢复

Ack 的 minimum_time_generation 精确回显本次 Invalidation，不代表 worker 没有更高 floor；当前 floor 取所有已应用事实的最大值。ACK 必须回显原 attempt/cut/出口/水位和三份摘要，完整覆盖不得新增或遗漏；业务锚的归类取该锚切点原强事实及各普通传输覆盖的保守上界：in_flight 优先，随后 unknown，最后才 not_sent。取消覆盖独立处理。这里的 Ack 只是验证后的持久投影，不能替代完整 IPC0.8 原帧；原端点、seq/reply_to、三个原摘要、原件字节及 effective_tick 的可信时基／发送截止关系须由提供者先验证。参考判定器只检验投影关联，不能单独用作生产接收器。

同 barrier 原文重复只查原。新 barrier 已登记后旧 ACK 迟到：保存原文并提升强事实，但不采用旧尝试；旧失败记录不删除。若迟到 transport_entered 推翻 never_sent 核销，资源重新未决并保持相应保护，不重开命令固定终态。worker ACK 不等于 public ready、Command finished 或资源 clear。

重启默认关闭，加载共享签发历史、完整 deny、全部旧 cut/attempt/ACK 后再恢复保护投递；普通／保护设备发送 outbox 均不自动重放。新连接不能采用旧出口的 ACK，旧出口仅查原或退役；替代出口先安装完整新 GateSnapshot。恢复 UTC 发送至少需要当前合格 State、新 Guard、所需旧目标保护已完成和所有其他门控，绝不能因 application 存在而重发旧许可。

## 6. 故障验收与本轮证据

| 用例 | 必须结果 |
| --- | --- |
| 普通与取消同时获得同 revision 或许可 ID | 全局唯一冲突；不能各自表内合法就通过 |
| Registry 丢历史行或分别拼两个 head | 连续性或来源不符，拒绝 cut |
| 普通初始已核销、重传未知 | 重传与原业务锚都在集合；末次未发不能覆盖原发送 |
| 人工 UTC 取消、即时普通动作共用出口 | 前者纳入 cancel 集合，后者不被误判 UTC；活出口仍纳入安装 |
| 活但空出口被遗漏／退役但仍未知被遗漏 | 全集差集拒绝 |
| 失效与签发两种串行顺序 | 签发在先则捕获；失效在先则旧代不得签发 |
| ACK 漏取消分支／已知已发降未发 | 拒绝采用，原未知不消失 |
| 更高 floor 先到、旧 ACK 后到 | 保留更高 floor；旧回显不被误判为降级请求 |
| ACK 缓存丢失／连接丢失 | 前者只在同旧出口资格有效时重装同 cut，后者监督退役 |
| 已提交失效而 outbox 响应丢失 | 查原并继续保护；不重新采样恢复旧资格或重发设备动作 |
| 全部 ACK 落盘但 application 前崩溃 | 仅补汇总持久事务；不再次执行设备动作 |

运行 `check_contracts.py --report` 检查 Schema、共享记录与目标选择、尝试采用和合成 ACK；`--check-report [--staged]`只核原字节。本轮不执行 SQLite、IPC、NTP、真实提供者、磁盘崩溃、设备或并发。SQL 切点故障、完整报文到持久字段端到端、逐许可发送时间重评及实际容量需后续组合验收；这些不能由本有限参考模型通过替代。
