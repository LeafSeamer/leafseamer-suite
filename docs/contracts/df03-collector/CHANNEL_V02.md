# 采集器有序停止切点与有界保留候选

日期：2026-10-21。`time-collector/0.2.0-draft.1`明确替换0.1的STOP集合和reported容量规则，其余原件/发布/身份规则继续适用；旧Schema及121项检查保留历史。本文为基于当前模型的分析与推荐，未获产品批准，不改变设备IPC0.8。

## 1. 已复现的冲突

旧`reference_model.stop`只收集reserved/consumed，`record_capture`却先将本机记录变成reported。若CAPTURE_REPORT尚未被核心接收，核心STOP仍含该poll而采集器集合为空，原模型返回coverage；缺缓存更不能建立一致快照。旧`reserve`又排除reported，导致尚未收到REPORT_STORED就能启动下一采样，原件及报告保留集合可能持续增长。（来源：[旧模型](reference_model.py)、[旧协议](README.md)。）

两处属于设计模型缺口，不是已发生的设备事故。新检查保留旧模型的错误场景预期以证明修订理由，不修改旧121项预期。

## 2. 唯一有序出口与字段变化

本机专属IPC采用可靠、有序字节流；两个方向各自有一个发送队列和连续sequence，不能多writer直接写同一端点。帧严格解码、长度/方向/身份校验后按顺序处理。普通帧的sequence必须恰好+1；最近完整重复帧可只返回缓存结果，不能重执。旧序号即便内容合法也不能被重新接纳；连接丢失不在新channel恢复旧水位。

| 对象 | 0.2字段与语义 |
| --- | --- |
| 握手 | 保留三项旧特性，新增ordered_stop_cut、poll_ordinal_retention，均必需；版本不降级 |
| PollIntent | 新增poll_ordinal，配置内从1精确递增；原poll_digest覆盖该字段；原poll_id/关联值仍不可复用 |
| Stop | 删除poll_refs；保留stop_id/revision/config_ref/stop_generation/digest，增加cut_sequence、last_poll_ordinal；二者允许0表示尚无前帧/采样 |
| STOP帧 | sequence=cut_sequence+1；cut是同一核心出口在STOP之前所有完整帧的水位，不是另一个方向的序号 |
| STOP_ACK | 删除consumed_poll_refs；回显stop_ref、received_through_sequence、last_poll_ordinal、gate_closed=true及closed_tick_ns |

核心先在单writer持久关闭本机授时资格和STOP意图，停止为该配置分配新poll；随后在同一IPC出口封存切点并发送STOP。已经排入同一出口的POLL不得被STOP越过，未分配发送序号的登记可保留为未投递记录，但旧poll仍不跨重启重发。若写入中途故障导致前缀不完整，接收者不能接受越过缺口的STOP；关闭资格并使用监督退役证据，不伪造ACK。

采集器在同一串行执行队列处理配置、POLL与STOP；通过当前身份/config/代次核验后先关网络发送闸，再核本地已处理sequence和poll ordinal。任一不一致保持关闸并请求监督退役，不为了回执恢复发送。成功ACK只证明已处理该前缀且旧配置不再进入网络发送，不推断历史UDP未发、报文已撤回、在途读取结束、设备TIME屏障完成或资源clear。消费发生在STOP之前仍可能产生迟到响应；关闭后不得再消费新poll。

原STOP完整帧及其固定ACK单独保留，重复同STOP只回原ACK；不同stop_id/摘要不能替换原回执。序号、poll ordinal或stop_generation达到U20上限时进入维护/退役，禁止回绕。STOP_ACK的closed_tick不得早于最后已消费m1，域内单调时钟失效不产生成功回执。

## 3. 有界记录与全局容量

采集器最多保留max_outstanding个reserved/consumed/**reported但未收到持久回执**记录；单源单飞也覆盖这三态。reported不释放记录或Blob，只有当前核心的精确REPORT_STORED（或QUERY_COMMIT已知的同一CommitReceipt）通过poll/capture/摘要关联核验后，才删除该poll的本机详细缓存。释放保留内存不改历史结果、不清核心墓碑。

配置内另保留固定大小的最高已观察poll_ordinal、最后消费m1、原STOP及最近帧缓存。已释放poll的旧ordinal即使换message_id和新sequence也不能再采样。新ordinal不许跳号；正确顺序到达但业务拒绝的POLL仍消费ordinal，只记录固定拒绝结果，不能换参重用。core以持久唯一poll_id及correlation防止新ordinal包装旧请求；可信核心存在恶意或存储损坏不在该内存水位的证明范围内，必须先过实际持久身份提供者。

核心跨实例共享容量账本，键为authority/database、批准的稳定来源槽、channel/config、poll_id/ordinal。登记前同事务核当前Binding、旧槽未关闭、max_sources、max_outstanding、原件/诊断/密文与审计保护预留总字节。不得以不同provider或Source修订绕过稳定来源槽。bytes预算使用批准的最坏密文膨胀及固定元数据预算；实际提交仍核真实大小，不能以平均包长预约。

核心可以在Capture固定裁决与证据同事务提交后释放活动采样额度，但**该持久回执必须在同一有序出口先于下一POLL发送**。这样采集器在接纳下一poll前已可释放旧原件；若回执不可投递则关闸/退役，不改用另一个连接偷偷发送新poll。持久原件的存储额度仍按保留政策占用，释放活动采样额度不等于删除原件或退款历史存储。

拒绝、未知、cache_missing或STOP_ACK本身不能释放未知网络操作的额度。实际监督退役证明可关闭旧采集执行槽，但保留核心poll/capture未知墓碑与原件/保护pin；已发UDP仍可能迟到，其旧Domain结果不形成新资格。

间隔提供者输入为稳定来源槽、持久的最近消费/KoD退避记录、原时钟Domain与批准速率界、新核心Domain及实际监督退役回执。已知m1且同域连续时按原m1的经过量下界复核；未知m1或跨域不可可靠换算时，**以当前核心收到可信退役回执后的新域tick为起点**，等待经过量下界至少达到旧/新配置最小间隔及仍有效KoD等待的保守上界。旧进程在可信退役前最后消费，因此该起点更晚，不依赖两个域的tick数值可比较。KoD上界未知、无法证明退役、时基失效或计数溢出返回unavailable，保持关闭。输出是绑定来源槽/域/批准和原件的next-poll资格回执，不能用0或重启清空退避。具体速率/退避profile及提供者真实取证仍需验收。

## 4. 持久所有者与故障用例

核心侧在现有十四表之外需要同库追加：channel/config固定注册、每方向发送身份/序号分配、poll ordinal与容量预约、STOP固定意图/原切点/原ACK及监督退役引用。它们的发布与失效要共用原ts_commit或后续统一事务身份；此轮给出明确写集，不宣称已新增物理表。

| 切点 | 必须行为 |
| --- | --- |
| 报告在采集器为reported，核心未收到 | STOP仍关闸并返回切点ACK，不要求双方poll状态相同 |
| 持久回执丢失 | 旧原件和活动记录保留；查原不重发，回执重投先于下一POLL |
| 持久回执已收、本机详情已释放，旧POLL再到 | 旧ordinal拒绝，网络发送数不增加 |
| STOP前缺一个IPC帧 | 不跨缺口确认；关闸、无成功ACK、走监督退役 |
| STOP与consume相邻两种顺序 | STOP先到零新发送；consume先到保持未知/迟到结果，不谎报未发 |
| core重启或旧STOP来自其他channel/config | 不继承旧资格，不返回本实例成功ACK |
| 槽满、reported未收回执、存储预留不足 | 明确拒绝，不截断证据，不增加隐形队列 |
| STOP_ACK收到但无监督退出、仍有未决操作 | 本机关闸证明可保存，未决状态/额度不得凭ACK清除 |

`build_channel_v02.py`从固定旧Schema生成完整14帧0.2候选；`check_channel_v02.py`验证旧缺口复现、新形状、有限有序执行与保留/释放和容量快照。人工当前身份及持久回执权威为合成前提；无真实IPC/NTP、SQLite、加密、进程退役或设备执行。核心发送日志和STOP/容量物理表、完整SDK/严格解码与真实单调/加密提供者仍需归并。
