# 共享消息日志与准备拒绝覆盖

状态：设计候选，未批准部署。配套[完整52帧IPC0.13](journal-ipc.schema.json)、[方向清单](ipc-journal-messages.json)、[局部持久对象](ipc-journal.schema.json)及[有限模型](ipc_journal_model.py)。保留旧0.12和207表；本轮未实现业务服务或新的SQL组合，四个最终准入阻断保持。

## 已知事实及修订依据

已知事实：[F02/F03](../../rebirth-f02-f03-design.md)要求数据库完全不可写时仍能发CLOSE_GATE；[有序发送](GATE_ORDER.md)禁止另一条未排序设备写通道。该稿曾将所有原帧重复归为会话错误，而F02允许查原；[屏障尝试](BARRIER_ATTEMPTS.md)允许QUERY使用新封装返回原ACK正文，[编码释放](ENCODING_RELEASE.md)固定完整原帧。现有[207表](ENCODING_RELEASE_STORAGE.md)只检查编码/释放子域的序号碰撞，尚未约束其他48类消息。编码请求可能还没有任何设备permit，不能从permit账本反推全部prepare。（来源：上述本仓契约及[编码存储](encoding-storage.sql)。）

基于这些事实，本候选统一双向消息规则，并用新版本显式处理两项旧约束冲突：正常流采用持久序号日志；紧急关闭不声称持久、并永久结束当前会话的执行资格。准备拒绝与缓存释放分离，拒绝ACK不用等待编码或设备库归还buffer。旧版本不被静默改写，Schema通过不等于候选获准。

## 1. 52类消息、信封及响应

`ipc/0.13.0-journal-draft.1`保留50类原消息，增加`DENY_ENCODING`及`DENY_ENCODING_ACK`。全部信封新增必填`journal_mode`；握手新增三项必选特性`shared_direction_journal / terminal_volatile_close / prepare_deny_before_release`。缺一项保持关闭，不剥字段降级。

普通模式为`durable`，全部52帧seq统一为无前导零的正U20字符串，范围1至99999999999999999999，溢出停止当前会话；这是对旧帧无位数上限/宽松尾锚的显式接受集修订。每方向从1连续递增，HELLO为W→C的首帧，HELLO_ACK为C→W首帧。身份由受监督启动和可信本机端点绑定，JSON里声称某个boot不产生认证。

[方向清单](ipc-journal-messages.json)逐一列出52类消息的方向、具名Schema、允许的reply_to对象及紧急模式资格。特别保留PREPARE_PACKET为W→C、PREPARE_PACKET_REJECTED为C→W、DISPATCH_CANCEL不是响应；SEND_REPORT/EVIDENCE_CANDIDATE及STORED通知仍通过领域ID关联且reply_to=null。响应必须关联相反方向的原请求；允许的type只是一层检查，还须核精确operation/barrier/attempt、prepare/packet、设备及正文来源。QUERY_BARRIER的ACK不能因为类型允许就冒用其他屏障的旧正文。

## 2. 单一日志与原子写集

作用域键为`authority_service_id/database_instance_id/controller_boot_id/worker_boot_id/ipc_session_id`，由一条持久SessionRef绑定；同会话多设备共用方向序列。设备session和writer_exit在领域原件里继续精确关联，不用它们另开seq空间。一个message_id在同方向会话内永久唯一，两个方向可同名；reply_to必须查相反方向。各子域不得分别分配seq。

| 持久对象/阶段 | 具体字段及原子性 |
| --- | --- |
| Session | SessionRef、scope、两boot、时钟域/descriptor、受监督成员与端点身份、协议版本、设备集合版本、容量profile；创建先于握手，失效不可复活 |
| FrameRecord | record_id、session_ref、direction、sequence、message_id、message_type、frame_digest、wire_digest、wire_length、frame_object_ref、wire_object_ref、record_digest；JSON摘要与含长度前缀的实际wire摘要分开保存，不用JCS掩盖不同原字节 |
| Outbox选择 | 领域不可变正文/身份/审计先提交；进入唯一发送器后串行选定精确seq和完整frame并持久化。原子关联领域授权提交、FrameRecord和发送预约，不跨网络持有写事务 |
| WriteAttempt | 精确record_ref、一次attempt_id、可信起始tick；先可靠提交再开始写。partial/unknown不能自动重发余下字节，关闭会话并核对；完整写成功只证明本机入流 |
| Inbox/EffectCommit | 受信解码的FrameRecord、disposition=applied/historical/rejected、非空domain_commit_refs、audit_ref、reply_record_refs、committed_tick_ns；与领域原件/投影变化和必要STORED应答outbox同事务，反向延迟FK防只存消息或只改领域 |
| 关闭/崩溃 | 会话墓碑、原消息与领域历史保留；新boot/session只用于新工作。原outbox/OPEN/DISPATCH不在重启后自动续发，未知效果按既有核对处理 |

普通序号预约一旦持久不可退款；尚未分配seq的候选可以丢弃而不留缺号。已分配的帧在最终重核失效时不能发旧动作，也不能跳过该号继续后续正常帧，终止旧会话、监督退役后建立新会话。缩短预约到入流的窗口，不能用占位设备动作补号。中间尚未开始的帧不允许让后继越过。

COMMIT未知时查询原完整身份与写集：查到原结果只确认历史，查不到不是重发设备动作许可；所有正常发送停止。收到完整帧后事务回滚，水位、消息和领域效果一同回滚，不能发送STORED；在可信会话仍可用且完整字节已知的情形才允许同帧重新摄取。数据库写失败同时触发下节保护，不能让回滚实验被解释为运行时继续发送。

同ID同seq且**原wire和解码对象均完全相同**：返回已存处理结论，领域效果次数不增加。若应答已准备，按该类型的缓存规则交付；不能再次运行处理器以生成新ACK。相同ID异字节/相同seq异ID、首次帧缺号或乱序均终止会话。重复帧与当前权限、boot绑定的校验先后固定：先验当前通道身份，再查原日志；不能在新session查到旧记录后作为合法重放。

业务逻辑身份另有墓碑：以新message_id/seq包装相同业务ID，只能按类型查原逻辑结果，不增加效果。完整缓存语义如下。

| 类型 | 缓存与查询要求 |
| --- | --- |
| FENCE/AUTH/TIME/RUN/CANCEL的QUERY_BARRIER | 新请求序号和新响应封装，reply_to指QUERY；ACK正文及effective_tick原样，正文摘要身份不含新封装 |
| RELEASE_ENCODING及DENY_ENCODING原请求重投 | 完整原帧重复，精确返回原ACK帧；不新增seq、不重装、不改变生效/清空tick。只能在原帧已完整入流且原会话仍存活时使用；partial/unknown不适用 |
| CLOSE_GATE同逻辑重投 | 正常模式可新信封关联同close_id原正文，返回原关闭正文；历史ACK不重新关闭后来OPEN，也不证明当前仍闭合 |
| ENCODE/PREPARE、OPEN、GUARD、许可和报告 | 领域唯一身份仍必须核原内容。已消费许可不再I/O，缓存结果不是重做。编码响应、报告持久化与查询沿各自原规则；本轮日志不替代领域处理器 |

## 3. 数据库故障时的关闭

仅CLOSE_GATE和对应ACK允许`journal_mode=volatile_close`且`seq=null`。请求必须scope=controller、device_id=null，关闭当前worker的全部已登记设备；ACK也device_id=null并完整回显设备集合。close_id/message_id在会话内唯一，使用预留RAM与预留保护写缓冲；不能把null序号用于OPEN、许可、单设备关闭或任何其他消息。ACK精确关联该紧急请求，不可用普通close冒充。

仍由**同一个**会话发送器在完整帧边界写入同一字节流，排在已开始帧之后；不建立第二个socket或绕过worker设备仲裁器。正常序号存在持久预约缺口时，紧急帧仍可处理，因为它不推进或伪造正常日志水位。已发生部分写且不能安全完成、流阻塞超出profile、剩余保护缓冲不足时，不能把紧急帧插入半帧：断开流并请求监督退役。真实监督退役失败仍保留unknown，绝不声称关闸完成。

Controller发起紧急关闭前永久锁存当前会话停止正常发送；worker接受它时同样进入`terminal_closed`，关闭全部物理闸并作废所有旧开放资格。此后正常消息不产生新效果，允许精确紧急请求重复和原ACK。紧急ACK证明真实退出前的关闸事实，不证明SQLite提交、许可未发、缓存清空、资源释放或接管已持久生效。

数据库恢复后可将RAM中仍完整的紧急原件存作历史并请求退役，**不能**转为普通序号帧、插进旧seq缺口、恢复原session或立即ready；RAM丢失时记录未知并走监督证据。通过新监督会话重取完整状态、拒绝快照、屏障和开放资格。该限制只适用于异常路径，正常单设备关闭/恢复保持原能力。

## 4. 准备拒绝及完整覆盖

DENY_ENCODING正文为deny_id/revision=1、完整Binding、prepare_id、encoding_authorization_ref、encode_message_id/encode_frame_digest、revocation_ref、selected_tick_ns、request_digest。Controller单writer先永久撤回未来使用，并提交原请求/审计/outbox。worker可对尚未见到ENCODE的prepare安装墓碑：请求仍须来自当前受信Controller且绑定精确授权身份，不需要伪造编码结果。

DENY_ENCODING_ACK为deny_ref、完整Binding、prepare_id、deny_message_id/deny_frame_digest、effective_tick_ns、state=denied、future_use_denied=true。摘要只排自身顶层摘要；ACK绑定完整原请求帧，时间满足selected≤effective≤可信received。在与permit消费相同的设备串行域安装墓碑后即可ACK，不等编码或buffer结束；新ENCODE、新借用、已有借用但尚未发出的I/O和旧Guard/重传全部拒绝。已进入设备调用的效果不回滚，仍保留in_flight/unknown。后台编码完成后丢弃新字节；真实消费者退出仍由独立RELEASE_ENCODING负责。

拒绝不是退款：DENY_ACK没有cache_empty字段，不得转换为ReleaseAck、ep_release、not_sent或clear。相同prepare不同拒绝内容不得覆盖原墓碑；多个关闭操作引用同一个不可变prepare撤回和原ACK，避免给同prepare反复分配不同拒绝身份。metadata满前预留每个prepare的拒绝/释放槽；未知prepare拒绝也须从Controller已持久准备预留取得预算，不能接受无限任意ID。

Controller在与新准备登记/最终T2相同writer顺序中，固定selector_ref、registry_ref及prepare_head，取得**匹配的全部已提交准备**，包含尚未编码、编码中、失败、响应未知、旧出口和已释放历史。选择依据原准备的请求来源与用途，不能取当前持有人覆盖旧Owner。

| 关闭来源 | Controller准备选择依据 |
| --- | --- |
| 控制接管FENCE | 同设备cut以前的全部准备，包括普通和取消；新的持有人使用新身份 |
| AUTH_FENCE | 原授权绑定的issuer/epoch、精确session/principal/credential/grant/extension/trust范围及revision下界；不是当前用户的所有准备 |
| RUN_FENCE | 原自动化run/arm generation/来源绑定；手动取消不借父命令run身份 |
| TIME_FENCE | 同时钟域且低于新floor的time-required准备；无UTC要求的即时准备不因它被撤回 |
| CANCEL_FENCE | ordinary阶段选择父命令普通准备；all阶段再纳入对应取消执行准备；保留既有CutTarget清单并对账，不能替换其许可覆盖 |
| 正常保护CLOSE_GATE | 本次device/controller范围内cut以前的准备；关闭ACK独自不能完成准备核销 |

本轮模型用受信提供者的有限来源投影验证这些选择；真实授权selector和时间/来源提供者仍须与C08统一绑定，合成标签不证明权限。

每项只能由四种依据关闭：①从未尝试且已永久撤回；②精确原ReleaseAck已采用；③同writer_exit真实监督退役；④原DenyAck可靠提交。已经尝试但编码回复未知不能走①。每个成员核原prepare/授权Ref/出口/证据当前有效性；有任何缺项、重复、错出口、未提交或撤回证明，汇总不完成。内存中的拒绝先保护；公共effective/applied仍需完整原屏障覆盖与PreparationClosure在同事务封存。

PreparationClosure为**内部存储对象**，含closure_id/revision、scope、operation_ref、selector_ref、registry_ref、prepare_head、排序唯一members、closure_digest；成员含prepare_id、encoding_authorization_ref、writer_exit_id、basis、proof_ref。不作为巨大IPC数组发送。逐prepare的小帧和ACK可以分批，最多允许固定profile的在途清理窗口；所有成员完成后才汇总，不截断集合。内部结构上限65536须与会话metadata及实际数据库字节预算共同验证，不是生产容量批准。

新准备与cut竞争：先提交的必须进入匹配全集；后提交仍核已生效拒绝范围，不能在关闭事务外凭旧权限偷偷排入队列。普通接管后以新控制与身份提交的新准备不被旧cut误选。GATE_FENCE只是物理闸换代，不能假造上述授权撤回或清理全部无关准备。已有在途许可继续由原三类清单取证，准备墓碑不能替代许可的发送分类。

## 5. 故障验收与未完成联接

J01：52类消息逐类方向和reply_to对账；所有帧拒绝0、前导零、尾换行和21位seq，20位最大值保持可表示；旧0.12拒绝。

J02：两个方向和多设备共享会话分别连续计数；相同原wire只查原，重算摘要后改内容/同号换ID仍失败；缺口停止，不跳号。

J03：Inbox写入、领域变化、EffectCommit和应答outbox任一缺写/异常不能部分提交；COMMIT响应丢失查原不再执行。当前仅有限副本实验，物理SQL和真实故障注入后续验收。

J04：存储不可写及正常预约缺口时可发送完整紧急关闭；部分帧不可插入、阻塞转监督退役；紧急ACK覆盖全部设备，恢复不得复活原会话。

J05：query新封装保留旧ACK正文，release/deny返回原帧；不同缓存语义不得通过统一重试函数替换。

J06：纯编码无permit、未知结果、旧出口、已退款准备均参与选择；AUTH/RUN/TIME精确范围不误杀无关手动准备；两阶段取消分别验证。

J07：拒绝前已进入I/O保留事实；拒绝后已borrow未发送也拒绝；编码和borrow未退出时DenyAck可用但ReleaseAck禁止，退款仍为零。

J08：缺项/重复/错域错授权/证明撤回使汇总失败；与已提交原控制屏障及公开effective的原子联接不得省略，巨大集合分批而不截断。

本轮机器资料和有限模型不等于上述全部运行验收。下一轮在207表组合中实现共享Session/FrameRecord/Attempt/Inbox/EffectCommit，消除各子域独立seq分配；接入prepare登记水位/撤回/deny原ACK/完整Closure，并与现有控制、RUN和取消seal作反向配对，补AUTH/TIME完整同库关系。需要逐子域显式迁移，不能仅添加一个无人引用的journal表就宣告全消息持久化完成。正常出站两阶段预约与旧ep_request内嵌frame的分层必须一起改，旧布局目前仍保留。

完整AdmissionSeal、Guard/预算/时间提供者、SDK统一版本、真实序列入口及平台/设备证明继续按收敛清单完成。复验：`python docs/contracts/c08-controller/build_ipc_journal.py --check`；`python docs/contracts/c08-controller/check_ipc_journal.py --report`。报告绑定检查不重跑用例。SQLite、真实IPC、并发、磁盘和设备在本轮均未执行，阶段0保持未关闭。
