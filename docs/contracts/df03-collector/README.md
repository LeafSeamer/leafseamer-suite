# 时间采集器专属通道候选

2026-10-21后续修订：[0.2有序停止切点](CHANNEL_V02.md)明确修复报告在途造成STOP集合不一致、reported提前释放容量的边界。旧0.1机器文件与121项检查保留历史；下一版采集器归并以0.2为输入。另有[十四表时间存储候选](STORAGE.md)，两批检查分别记账，不将后续覆盖并入旧报告。

日期：2026-10-21。依据已确认reference-bound/1路线及[参考时间字段](../df03-reference/README.md)、[监督启动](../df02-supervisor/README.md)，本文补充采集组件与核心的身份、采样、候选上报和停止协议。`time-collector/0.1.0-draft.1`待审阅；不改变设备IPC0.8，不实现采集器或操作网络/系统时间。

## 1. 信任与所有权

采集器必须以监督器ProtectedLaunchIntent的time_provider角色启动，device_ids为空。Bootstrap证明成功只产生监督AdmissionReceipt；核心核验并持久RuntimeBinding后才创建CollectorChannel。Channel固定authority/database、core_boot_id/core_runtime_binding_ref、provider_id/provider_boot_id/runtime_binding_ref、监督准入回执Ref及独立channel_id。Domain中的runtime_binding_ref属于采集器；core_runtime_binding_ref另列，二者不得互换。

传输只使用监督启动绑定的本机专属端点，操作系统对端身份和继承通道与AdmissionReceipt一致。不能靠载荷内自报角色、路径名、PID或合法digest建立权威；bootstrap秘密不进入普通IPC消息、日志或证据正文。连接丢失立即关闭本机授时资格，之后走TIME保护outbox及监督退役。新core/provider启动身份不得接管旧通道或旧采样许可。专属通道不是公开HTTP、第三方扩展通道或设备worker通道。

核心拥有配置批准、poll受理记录、原件持久库、请求消费墓碑、Anchor/State/Invalidation和设备TIME保护；采集器拥有同域m1/m4读取、网络请求和受限暂存。采集器不能修改系统时间、写业务库、批准profile或向设备发命令。网络来源、认证、parser、时代与误差方法仍须核心指定的可信提供者验证，不能因采集器受到监督而把它提交的Ref当作真实权威。

## 2. 独立14帧及字段

所有信封固定version、type、完整Channel、direction、message_id、sequence、reply_to、body。sequence为每方向严格递增U20，从1开始；相同消息重投仅允许同id和同完整正文，不能借重连重置水位。未知版本/角色/方向/额外字段拒绝并关闭连接；业务查询重投使用新消息序号，但poll/capture原身份不变。HELLO/ACCEPT协商唯一版本及三项必需特性：one_shot_poll、candidate_only、monotonic_stop。

| 帧 | 方向及正文 |
| --- | --- |
| HELLO / ACCEPT | 采集器→核心 / 核心→采集器；完整启动绑定，精确版本及特性 |
| CONFIGURE / CONFIG_ACK | 核心→采集器 / 反向；不可变Configuration及精确config_ref、configured/rejected与原因 |
| POLL / POLL_ACK | 核心→采集器 / 反向；PollIntent及原poll_ref、reserved/rejected；ACK不表示已发送或已授时 |
| CAPTURE_REPORT / REPORT_STORED | 采集器→核心 / 反向；完整Capture候选或失败；核心回固定CommitReceipt，回执不重新发布历史锚点 |
| QUERY_CAPTURE / CAPTURE_STATUS | 核心→采集器 / 反向；精确poll_ref，reserved/consumed/reported/cache_missing及可空完整Capture |
| QUERY_COMMIT / COMMIT_STATUS | 采集器→核心 / 反向；精确capture_ref，known/not_found/unavailable及可空CommitReceipt |
| STOP / STOP_ACK | 核心→采集器 / 反向；原config_ref、精确递增stop_generation、完整在途poll集合及stop_ref；ACK含已消费poll集合和closed_tick_ns |

Configuration含time Binding及原Source/Profile/Policy/Approval、独立revision/digest、collector_artifact_ref、bootstrap_receipt_ref、stop_generation，以及Limits。Limits固定max_sources、max_outstanding、max_frame_bytes、max_blob_bytes、minimum_poll_interval_ns和poll_lease_ns，必须由批准容量profile给定；本候选只限定格式上限，不给生产默认。两个单飞约束同时成立：每源最多一个未关闭poll，全局不超过max_outstanding。不得截断集合使其看似满足容量。

一份Configuration只绑定一个Source；max_sources是核心跨实例的总护栏，不能据此让单实例任意选择其他来源。单源间隔在最终消费时复核，最小间隔等号可继续其他门控；poll截止等号拒绝。候选格式中的四源/四在途上限是实验接受集，实际批准可以更小，核心跨实例容量提供者必须独立验证。

PollIntent固定poll_id/revision=1、完整time Binding、config_ref、correlation_ref、endpoint_ref、issued_tick_ns、not_before_tick_ns、expires_tick_ns、stop_generation及摘要。核心先持久登记，再发POLL。endpoint须属于Source.endpoint_set_ref的批准集合，所有网络超时都受原expires及profile最大交换跨度约束；解析DNS后不能偷偷换端点。间隔按同源上次已消费poll的m1保守约束，重试和失败不退款；KoD更严格间隔或停止策略仍优先。真实解析/KoD实现留给协议库资格验收。

Capture固定capture_id/revision=1、poll_ref、Binding、reported_tick_ns、candidate/failed/indeterminate、可空Request/Exchange/认证/误差/时代/Failure、Blob清单及摘要。candidate必须具备全部采样原件且Failure为空；failed必须有Failure且不得夹带合格Exchange；indeterminate仅记录未知，不形成Anchor。Request仅在实际消费时取m1后生成，不能把核心issued_tick当m1。实际m4必须早于原请求及poll截止；reported_tick不刷新m1/m4。Capture不包含Anchor、Assessment或State，这些由核心根据可信原件生成。

BlobDescriptor固定content_ref、size、request/response/diagnostic用途、owner Domain、敏感性和sealed回执Ref。所有原始字节按敏感材料处理，只通过受限不可变暂存传递；核心必须在发布事务前取到、复核长度/摘要、独立解析并持久化，不能仅存一个会随采集器退出消失的路径。sealed_ref不是任意路径或由不可信端点指定的下载地址；专属内容提供者负责受保护句柄/只读映射和真实不可变性。格式不证明OS权限和字节耐久。

CommitReceipt固定capture_ref/poll_ref、published/rejected/failure_recorded、record_ref、可空anchor_ref和receipt_digest。仅published带Anchor；published是当时已经提交的历史事实，不意味着查询时仍可用于执行。回执没有反向进入Capture摘要，避免循环；REPORT_STORED丢失可查原，not_found也不能授权同poll再发送。

## 3. 状态、单次消费与停止

采集器通道：bootstrapped → negotiated → configured → stopping → stopped；状态倒退或重新配置同一已停止实例拒绝。换源/profile/批准或核心身份须先让旧实例停止/退役并关闭旧时间代次，再创建新绑定，不能就地改已有PollIntent。

每poll：reserved → consumed → reported；或reserved → rejected/closed。consumed在唯一网络发送出口、最后一轮当前配置/端点/时间/stop门控通过后先记录于采集器内存账本，再进入网络I/O。这里没有声称与socket原子提交：进程在消费后崩溃，核心按未知处理，旧poll永不再次进入I/O；新进程不恢复旧poll。采集器单次记录丢失不是重新发送授权。后续新poll是新的采样身份，必须在旧实例已退役、时间资格关闭及容量/间隔重新核定后受理，不是重试原poll。

核心对capture提交：当前通道身份/对象权先查；同poll已有同capture摘要时返回原回执，不更新State/年龄；不同capture冲突拒绝。新candidate再次核验Binding、批准、Request关联、Blob真实原件、m1/m4和全部预算，计算Anchor并在提交时重评。原件、消费、Anchor、State及审计/outbox同事务发布；失败或提交未知不返回伪成功。失效事务先关闭新UTC资格，TIME设备屏障完成另行记账。完整物理DDL仍待落实，本文仅确定写集所有者及调用顺序。

STOP与采集器网络发送共用串行出口。stop_generation必须比配置当前代次精确加一；核心先关闭新授时资格并捕获全部reserved/consumed poll，再发送STOP。ACK只证明采集器以后不再进入该配置的网络发送，不证明已经发出的UDP被撤回、设备屏障完成或资源释放。ACK已消费集合必须恰好等于该切点下实际consumed集合，并包含在完整捕获集合中；未知/缺缓存时不能编造ACK，改走监督退役。较新停止下界不能被旧配置或迟到POLL覆盖。

普通采样失败不自动延长或立即否定仍有充分证据的旧锚点：核心按既有当前Binding和年龄重评；认证/信任撤销、运行域失效、存储故障或连接丢失必须关闭资格。失效后新合格样本不解除自动化锁存、不补旧场次、不复活旧设备许可。

## 4. 故障验收与剩余项

| 故障 | 预期 |
| --- | --- |
| worker冒充time_provider、旧boot/通道、凭载荷换端点 | 在任何网络发送前拒绝 |
| POLL重复或ACK丢失 | 查原reserved/consumed，不二次网络发送 |
| 消费后进程崩溃、cache_missing、查不到commit | 旧poll未知且不得重发；关闭资格，退役后新实例新poll |
| 报告摘要合法但原Request/Blob/端点/代次不符 | 不发布Anchor；不能靠重算摘要取得权威 |
| m4或消费tick等于截止、提交时证据过期 | 拒绝；reported_tick不刷新年龄 |
| STOP先于POLL或处于消费/I/O之间 | 无新发送；已消费保持未知/在途，不谎报未发 |
| 源单飞或全局容量满 | 明确拒绝，不排入无界隐形队列 |
| 提交成功后丢REPORT_STORED | QUERY_COMMIT返回原回执，旧State不重放 |
| 暂存字节丢失或受保护句柄无法读取 | 不提交资格；不把hash当持久证明 |

`build_contracts.py --check`验证生成一致；`check_contracts.py --report`验证14帧、关联、有限单次消费/停止与查原快照。权威/端点/字节真实性为合成上下文；无实际网络、NTP、OS身份、IPC、SQLite或设备测试。`--check-report [--staged]`只核输入字节。

剩余冻结：时间物理表/事务/失效outbox与Blob生命周期、核心验证提供者映射及采集器加载制品、完整SDK授权与严格解码调用点、跨服务年龄和精确协议库/引导信任/平台误差profile。不得把本候选通过当作全部系统设计或采集器运行已完成。
