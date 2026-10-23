# 取消保护、独立执行与完整屏障候选

状态：待审阅，领域候选`command-cancellation/0.1.0-draft.1`，完整设备IPC候选`ipc/0.7.0-cancellation-draft.1`。由[唯一生成源](build_contracts.py)输出[领域Schema](cancellation.schema.json)和[46帧IPC](ipc.schema.json)。继承[IPC0.6](../c08-controller/BARRIER_ATTEMPTS.md)的30帧，新增16帧，不改旧文件，不切换SDK权威，不实现服务或设备发送。

已知事实：[命令HTTP](../c02-command-view/README.md)已经区分取消回执、进度与原命令终态；[91表候选](../c02-command-view/STORAGE.md)保存永久deny及完整普通许可cut，但closure/result仅为BODY，还没有协作取消的专属发送分支。原普通许可禁止终态后发送，不能直接用于取消已unknown的动作。（来源：上述两稿及[命令SQL](../c08-controller/command.sql)。）

基于这些约束，本轮明确两个关闭阶段，避免“已公开关闭，又发送取消指令”的矛盾：`ordinary`只关闭父命令普通动作；`all`同时关闭普通动作及该取消操作的保护动作。**仅all关闭可令公开future_writes=closed**。取消效果和资源释放仍另证；任何关闭ACK都不能直接生成confirmed。

## 1. 固定对象与摘要

| 模型 | 具体字段与约束 |
| --- | --- |
| CancellationBinding | scope、cancellation_id、parent_command_id、initial_operation_ref、完整CancelIdentity、mode、policy_ref；绑定首次取消，不随查询或接管变化 |
| Policy | policy_id/revision/digest、mode、procedure_ref、completion/release_policy_ref、完整resource_keys、max_transmissions、allow_protocol_resend；application_attempts固定1 |
| Exit | writer_exit_id、controller/worker_boot_id、ipc_session_id、device_id/device_session_id、socket_instance_id、clock_domain_id、descriptor_digest |
| CutTarget | 完整Exit、ordinary_attempt_ids、ordinary_transmissions、cancel_prepare_ids、cancel_transmissions及target_digest |
| Cut | cut_id、binding、stage、previous_cut_ref、全局issued_revision、deny_revision、全部targets及cut_digest；ordinary没有前序或保护许可，all必须指初始ordinary切点 |
| DenyEntry/Snapshot | 每父命令唯一cancellation/stage/deny_revision/cut_ref；快照绑定scope/device/revision及完整有序entries/digest |
| TargetClosure / ClosureEvidence | 每目标原target摘要、barrier_ack或supervisor_retired原件Ref及验证Ref；汇总绑定完整cut、stage和provider_receipt_ref |
| Requester | 当前取消执行的actor_ref、authorization_ref、origin、admission_origin及精确panel/automation来源Ref；不是父命令原actor的替身 |
| ExecutionPlan | 唯一execution_id、binding/requester/device、ordinary_closure_ref、policy_ref、protected_hold_ref、完整resource_keys、拓扑有序primitives及execution_digest |
| Primitive | primitive_id、action_ref、parameters_schema_ref、parameters、全部after依赖、completion_policy_ref；参数须当前批准Schema二次验证 |
| Guard | execution_ref/requester/Exit、当前control_epoch/version、gate/authorization_revision、time_required、可空time_evidence/policy_ref、guard_provider_ref、protected_hold_ref、deny_revision、SendWindow及guard_digest |
| Packet | packet_id/digest、execution/cancellation/parent/primitive、完整Exit、protocol_session/wire_packet_id/tracking_ids、不可变字节Ref、长度/sha256和transport_profile_ref |
| Transmission | 独立permit/transmission_id、execution/cancellation/parent/primitive、packet_ref/Exit/requester/guard_ref、ordinal、initial_permit_id、issued_revision、kind、触发观察、预算回执和SendWindow |
| DecisionEvidence | decision_id/revision、binding、原command_state_ref、all_closure_ref、execution_ref、outcome、完整evidence_refs/provider_receipt_ref及decision_digest |

全部内部Ref指向所属authority的固定原件，不是授权凭据。摘要采用既有JCS/SHA-256，带sha256前缀，只删除对象自身digest字段，不递归删业务同名字段。target_digest覆盖完整CutTarget；cut_digest覆盖完整Cut；closure/plan/guard/packet/decision/snapshot各自独立。取消回执仍只引用初始操作；本批内部执行对象不反向写入初始操作摘要，不引入摘要循环。

targets按writer_exit_id排序，attempt/prepare ID按字典序唯一，ordinary_transmissions按intent.permit_id、cancel_transmissions按permit_id排序，证据与成员不可截断。Policy和Plan的资源key完整、唯一且排序；primitive按确定拓扑序，after只能引用已出现primitive，无环且不可重复。ExecutionPlan中开放parameters与证据payload只保留承载能力，不代表已批准Schema、脱敏或可信设备事实。

## 2. ordinary、all与启动拒绝

取消受理沿91表写集，原子保存父命令永久ordinary deny、全部历史尝试/许可及所有已登记出口世代。即使原许可已核销，也保留其引用。202只表示可靠受理；网络中旧许可在worker实际安装屏障前仍可能发送，ACK必须保守报告，不能追溯改为未发。

ordinary屏障在每个目标的同一串行发送出口安装精确deny，阻止父命令新的普通发送和编码结果取得许可；已进入传输的事实保留。ACK回显完整ordinary准备集合和许可覆盖。只有全部目标原ACK或可信监督退役原件齐全，Controller才能封存ordinary ClosureEvidence；监督组空只证明后续旧出口无写，不能证明设备未执行。

before_dispatch_only不创建ExecutionPlan。在ordinary关闭后，writer仍须永久关闭保护许可签发，并封存all切点与all ClosureEvidence，才能报告future_writes=closed。两切点可共享没有保护传输的目标内容，但原件身份及stage不同。全部普通历史明确未发时才可confirmed；已经发送则按固定政策unsupported，未知消费不能假装not_sent。

cooperative只有ordinary ClosureEvidence可靠、当前有权主体及资源/时间/控制守卫全部满足时，才能创建唯一ExecutionPlan。不能因“保护动作”跳过当前持有人、权限、时间或完整资源足迹；其发送可具有新的有界保护期限，不借延长父命令原期限重发原业务动作。

时间要求由批准动作／保护政策确定，不能由请求方自行改为false。`time_required=true`必须绑定当前UTC证据及政策；false时两引用必须null，即时手动保护不单因NTP不可用而拒绝。两分支始终要求有效受监督运行域、共享单调时钟和有界SendWindow；false不豁免期限、接管或授权。2026-10-20已选的[DF03 reference-bound/1](../../rebirth-df03-time-profile-design.md)将在下一同版公共Schema／IPC归并中落实；本候选的Ref槽位不证明新模型已完成，不允许把新锚点伪装成旧system-bound证据。

取消效果确定、失败、不确定或执行被接管/撤权时，先永久关闭该execution的新许可签发，再冻结all cut；保留原ordinary切点，纳入全部保护编码准备、全部已发/未决/已核销保护许可及新增出口。all屏障拒绝两个分支。没有全部目标关闭证据时future_writes保持pending/indeterminate；all关闭后也可能取消效果未知和资源未决。

OPEN_GATE新增command_deny_snapshot，ACK回显revision/digest。worker先核完整scope/device快照并合并单调deny，再开闸；同父命令不能换cancellation_id，all不能降为ordinary，旧快照不能擦掉之后收到的保护。允许快照外新收到更强deny继续保留，但对应开闸流程须重新核对当前权威，不能用过时快照声明已同步。重启恢复完整deny后才接收许可；新worker不能证明旧出口未消费。

快照结构最多4096条，每目标两类许可各最多256条，单包字节最多65536；这些是候选格式上限，不是生产容量承诺。真实profile还约束总字节、目标数、缓存和保护预留；超限整体保持关闭，不丢墓碑或截断全集。持久保留/归档和GC仍需与统一存储方案归并。

## 3. 新增16帧及方向

全部帧继承受监督域、peer、方向、seq和当前IPC连接校验；表内响应必须reply_to原请求，其他帧reply_to为null。DISPATCH_CANCEL作为独立可靠意图投递，初发/重传均为非响应帧，重传通过正文resend_request_id关联。

| 帧 | 方向 | 正文及行为 |
| --- | --- | --- |
| CANCEL_FENCE | C→W | binding/stage/cut_ref、完整目标、deny_revision、operation/barrier_id及BarrierAttemptBinding；只安装关闭，不发送设备动作 |
| CANCEL_FENCE_ACK | W→C响应 | 原绑定及目标摘要、完整准备ID与两类coverage、effective_tick_ns、gate_io_seq、ack_digest |
| CANCEL_GUARD | C→W | 完整Plan及Guard；注册当前已验证的专属执行上下文，不能产生设备写 |
| CANCEL_GUARD_ACK | W→C响应 | execution_ref、guard_ref、installed/rejected；不是发送或效果证明 |
| ENCODE_CANCEL_PACKET | C→W | prepare_id、execution/primitive、guard_ref及过期tick；只编码 |
| PREPARE_CANCEL_PACKET | W→C响应 | 原prepare_id、完整Packet、bytes_hex；同prepare身份只回原提案，不重新分配wire ID |
| CANCEL_ENCODING_FAILED | W→C响应 | prepare/execution及失败原因，不认定设备动作失败 |
| CANCEL_PREPARE_REJECTED | C→W响应 | 拒绝提案；不得改包换协议后私自发送 |
| DISPATCH_CANCEL | C→W | 原prepare、固定Packet、独立Transmission及可空resend_request_id；持久意图提交后才投递 |
| CANCEL_RESEND_REQUEST | W→C | 原packet/execution、request_id、timeout/peer_request及可信观察Ref；不携带新payload |
| CANCEL_RESEND_REJECTED | C→W响应 | 关联原请求与拒绝原因，不退款或刷新期限 |
| CANCEL_SEND_REPORT | W→C | 完整Transmission、not_sent/in_flight/unknown、gate_io_seq、可空transport_entered_tick_ns及observation_ref |
| CANCEL_REPORT_STORED | C→W | 原report_id/body摘要及持久record_ref；事务提交后才确认，不能用它当设备效果 |
| CANCEL_EVIDENCE_CANDIDATE | W→C | execution/primitive、原packet_refs、批准evidence_schema_ref和结构化payload；真实提供者验来源、时序和二次Schema |
| QUERY_CANCEL_EXECUTION | C→W | 固定execution_ref；只查缓存，不重新安装/编码/发送 |
| CANCEL_EXECUTION_STATUS | W→C响应 | 原execution_ref、known/cache_missing、已存报告Ref；cache_missing的列表必须为空，表示未知而非未执行 |

原QUERY_BARRIER/BARRIER_UNAVAILABLE/BARRIER_STORED也适用于CANCEL_FENCE：同cut/exit的attempt首次1，后继精确加一；有可靠失败依据才创建新barrier，旧原ACK正文不重算。只丢屏障ACK缓存时可重新安装同cut；进程或连接换代时旧出口走退休核对，新出口先装完整deny。失败旧attempt的迟到ACK仍保存强事实，不采用为新attempt。

HELLO与ACK新增三项必选能力：command_cancel_deny、separate_cancel_execution、complete_cancel_transmission_fence；缺任一项保持关闭，不能剥字段退到0.6。

## 4. 唯一发送出口、重传和其他屏障

ExecutionPlan属于一个父命令/取消操作/设备，最多一个应用执行；每primitive只有一个原packet和初始许可。需要多primitive的模块必须事前声明完整依赖与足迹，后继只在前序完成证据满足时发；出现unknown则冻结后继，不把它当failed继续。协作取消的政策必须能解释父命令正常完成与取消并发的可观察结果，否则保持indeterminate，不用后来状态倒推本次取消有效。

worker的普通和保护发送共用**同一个串行门控与I/O顺序**。保护permit有独立模型和消费账本，不能伪装普通ce_permit、复用旧permit或对终态禁发做例外。最后门控核对完整已持久DISPATCH正文、当前guard与live Exit、当前取消主体、控制版本、授权/来源、时间区间、资源和预算、ordinary已闭/all未闭。服务端一个“已持久”布尔值不足以授权客户端自造许可。

持久签发与worker消费分开：Controller先保存完整编码字节、独立permit、预算计费、审计和投递意图；worker在唯一出口先标记一次消费，再调用设备I/O。消费之后报告前崩溃保持unknown，重投同许可只返回原消费状态。不同内容复用permit拒绝并关闭，不能因新连接、换ID或换context重复执行。

协议重传只允许固定Policy明确批准、同packet/同bytes/同Exit、已知原发送进入传输且无ACK/未决许可、预算和原保护期限仍满足的情况；每次新ordinal/new permit重新过当前guard。消费未知、会话变化、取消执行终结或all关闭时禁止重传。应用级重试仍为零；同取消不能换execution_id或新primitive重做未知动作。

manual取消的Requester可不同于父命令原actor，必须具备当前取消权限和控制资格；其执行不继承父automation旧grant。service仍限自身automation来源，并验证当前服务/运行/授权链；运行暂停或权限失效后不得继续借旧授权发送协作动作。关闭普通出口、保存原报告和核对不要求旧业务grant仍有效。人工转交不迁移旧保护permit，旧执行若被关闭只能核对，不能自动换执行者续跑。

原FENCE、AUTH_FENCE、TIME_FENCE、RUN_FENCE及ACK均新增cancel_transmissions/cancel_coverage和cancel_ledger_digest；cut_digest涵盖新增完整集合。选择对象依据**取消执行Requester的当前控制/授权/时间/来源**，不把父命令actor当执行者。RUN_FENCE只覆盖匹配automation来源；人工针对旧automation的保护操作仍受其人工接管/授权/时间屏障。每条新许可都在同一个全局签发水位中，与普通许可同writer冻结；不能使用两个独立max值声称完整cut。

接管与发送竞争时，以同一出口的真实gate_io_seq为界：先消费并进入I/O的保护传输记in_flight；先安装屏障则未消费许可拒绝。关闭ACK不得把更强已发送或消费未知降为not_sent；末次重传未发不能覆盖原发送。ACK只能证明随后不会新增对应写，不撤回已传输字节。

## 5. 关闭/结果提供者与事务归并

ClosureEvidence验证完整Cut及每个目标原件。barrier_ack验证原peer/Exit、cut/target摘要、attempt、完整两类coverage、关闭顺序和原单调时钟边界；supervisor_retired验证该精确旧出口的纳管/退休身份。汇总不得把不同阶段或不同cut的目标拼成全集；all还需同writer的永久签发关闭事实。

DecisionEvidence单独验证模块完成政策：confirmed必须all关闭，加全部历史明确未发或协作取消效果证据；too_late须父命令已有确定完成，finished/unknown不满足；unsupported仅用于固定before_dispatch_only政策。failed与indeterminate按原件区分，超时不自动failed。原Command的finished/outcome/terminal、暂停锁存和独立资源释放规则不变。

| 事务/持久所有者 | 必须内容与既有映射 |
| --- | --- |
| 取消受理 | 91表cv_cancel系列仍为固定初始ordinary切点，原receipt不变 |
| 每个屏障尝试/ACK/采用 | 同cut/Exit精确attempt、原请求与原ACK/两类coverage、失败和采用记录、审计/outbox；复用0.6纪律，新增取消物理表仍需落实 |
| ordinary/all Closure | 完整Cut/成员/类型化TargetClosure原件Ref及provider receipt，同事务封存；all包含永久签发关闭 |
| 唯一ExecutionPlan | 对cancellation_id唯一，绑定固定政策/当前Requester/ordinary Closure/完整保护资源占用；同事务审计及准备outbox |
| 编码/逐传输 | 固定prepare/packet字节；共享全局签发水位、独立取消permit、预算、发送outbox原子提交；不可写普通ce_permit冒充 |
| 原报告/决定/公开修订 | 原报告身份与摘要、验证原件、Decision/Closure引用、新CancelOperation及State/公开record/snapshot同提交；成功才STORED和通知 |

本轮是IPC与提供者字段冻结候选，**没有执行上述新表迁移**。91表的cut高水位目前只从普通ce_permit读取，后续持久化归并必须换为普通/保护共用分配器；不能在现有91表旁直接新增孤立取消表后称水位已统一。closure_validation_body/result_validation_body需替换或关联具名原件FK，Command public evidence映射继续保留原件与view摘要分离。其他屏障原件和通用保护outbox也须使用同一发送登记来源。

## 6. 故障时序与验证范围

| 故障或竞争 | 验收结果 |
| --- | --- |
| 普通已关闭但保护执行尚有未决许可 | 只有ordinary Closure；公开future_writes不能closed |
| 取消受理提交丢响应 | 查原回执；不新建execution或重发设备动作 |
| 编码完成但许可未提交就崩溃 | 不发送；原prepare身份只查，不重新分配wire ID |
| permit提交后消息送达未知 | 查持久原意图/worker消费，不能换许可重新初发 |
| 消费标记后I/O结果未知 | 原执行indeterminate，关闭新增签发并作all屏障，保持资源未决 |
| 接管/撤权与保护发送并发 | 同一闸序确定已发或拒绝；新持有人不能消除旧在途事实 |
| 新屏障尝试登记后旧ACK迟到 | 保留旧原文和强事实；不得采用旧attempt代替当前目标 |
| 旧worker退出、新worker启动 | 旧Exit退休核对，新Exit完整deny先于开闸；未知不降未发 |
| 全部出口关闭但没有取消效果证据 | future_writes可closed，state仍indeterminate，原unknown不改 |
| 收到原协议ACK后申请重传 | 拒绝，不当作动作effect_verified；效果仍按完成政策查询 |
| 关闭/结果原件撤回 | 追加失效与保护，隐藏旧当前clear；不删除历史、不复活许可 |

[check_contracts.py](check_contracts.py)验证生成字节、46帧形状/拒绝降级、必选特性及新增关联；[reference_model.py](reference_model.py)在合成权威上下文核验cut/ACK/关闭/发送/重传/四类屏障/查询及结果，并以有限内存字典模拟一次消费。30个继承帧仅升级结构，未声称把旧全部语义逐项重测。开放参数/证据、原件可信性、权威全集、动态Schema和提供者事实仍需实现验证；模型不执行网络、设备或SQLite。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-cancellation/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-cancellation/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-cancellation/check_contracts.py --check-report --staged
```

剩余冻结项集中于本节已列持久写集、共享签发分配器、完整SDK及权限/面板字段归并和真实provider输入输出的最终统一版本。当前候选需审阅；IPC成文不等于可启用cooperative，更不等于全系统设计结束。
