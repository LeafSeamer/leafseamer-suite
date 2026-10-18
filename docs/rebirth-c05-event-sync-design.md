# C05：事件、快照同步与容量保护

日期：2026-10-17。状态：**ES01—ES06为待审阅推荐**。已确认依据是Q48、Q50、Q63、Q64及F04—F07；DF04／DF06和C04候选的依赖仍须共同审阅。本稿只补设计，不修改公共draft.4／IPC 0.3，不实现服务或离线自治。

SDK负责事件及同步协议；Controller负责设备来源注册、采集和权威命令／控制事实；Seamer负责规范摄取、观测、触发决定及相关运行保护；GUI维护可丢弃的显示投影；Suite验证版本组合、容量及故障。事件完整性保护不等于替用户设计断网期间继续直播的自动化。

## 1. 已知事实与分析

事实来源：[draft.4 Schema](contracts/draft4/first-loop.schema.json)、[Seamer OpenAPI](contracts/draft4/seamer.openapi.json)、[首契约第7节](rebirth-first-loop-contract.md#7-快照增量及服务到服务边界)、[DF04](rebirth-df04-storage-design.md)、[DF06](rebirth-df06-internal-trust-design.md)。

| 当前已存在的内容 | 工程缺口／冲突 |
| --- | --- |
| EventEnvelope有来源boot、sequence、年龄证据及可选因果命令；EventReceipt有receive_sequence及duplicate | 尚无DF06完整来源命名空间及origin_digest；可靠摄取与触发资格需要分开返回 |
| Subscription与Snapshot已有snapshot_id及水位；WsEvent已有previous_cursor | 已有原子交接意图，但缺少可校验的快照应用、ACK、连接代际和切换状态模型 |
| 旧文字把stream_id解释为持久日志世代；DF04另有stream_epoch | 下一版须明确两者含义，旧数字cursor不能在新流继续 |
| Snapshot只含commands、controls、observations；WsEvent还允许run.updated | 运行页面重同步缺runs；定义／来源同步状态及删除语义也需配套 |
| WS票据绑定scope与client_instance_id，未绑定subscription_id；WsFrame只有服务端数据／resync | 缺客户端attach／应用确认／ACK模型；不能用scope相同替代具体订阅授权 |
| 共用订阅与快照路由标status.read | 还须逐资源权限、固定授权投影和撤销边界，status.read不能授予全部命令／运行数据 |
| DF04有去重inbox、outbox及游标CAS，DF06要求两传输共用身份 | 需明确持久受理点、乱序及重放资格、保留floor与GC，以及存储失败时的保护 |

WebSocket提供连接、帧、关闭及Ping/Pong机制；应用持久摄取、快照完成和动作成功须由本项目协议另行证明。Ping/Pong不作为下面的业务ACK。（来源：[RFC 6455第5—7节](https://www.rfc-editor.org/rfc/rfc6455.html)。）

## 2. ES01：五种序号与规范来源身份

推荐下一版明确以下相互独立的身份域。所有计数均用DF01候选规范非负十进制串，以精确整数比较；耗尽上限时保护并显式换代，不回绕、不转成浮点。

| 身份／序号 | 作用域与含义 |
| --- | --- |
| SourceStreamKey | authority_service_id、database_instance_id、registration_id、source_stream_id、source_epoch；引用完整SourceBindingRef及固定registration_revision |
| source_sequence | 在一个SourceStreamKey内，从1开始严格递增；0仅作尚无事件的基线。原始设备包序号单独保存，不冒充此计数 |
| receive_sequence | Seamer本库摄取世代内的提交顺序，跨来源只按这个序号仲裁；重新投递不分配新序号 |
| journal_sequence | 单服务持久通知日志(stream_id,stream_epoch)内的提交顺序；不对外泄漏未授权对象的事件数量 |
| subscription cursor | 单(subscription_id,stream_id,stream_epoch)的有界交付链序号；previous_cursor指已交付链前驱，不是journal_sequence加1 |
| entity_revision | 一对象在明确authority／对象身份／对象代际内的版本；不证明来源完整、连接存活或设备实际状态 |

stream_id推荐表示稳定逻辑通知流，stream_epoch表示持久日志世代；与旧首契约措辞不同，必须在下一公共版本显式修订。普通进程重启可保留日志世代但所有连接及未完成快照失效；数据库恢复、日志不可证明连续或身份重建必须换新epoch。来源provider重启或注册绑定变化则换source_epoch并重新建基线，不能仅清零source_sequence。新epoch不删除旧epoch的拒绝／审计依据。

规范inbox唯一键为(SourceStreamKey,event_id)，另UNIQUE(SourceStreamKey,source_sequence)。同ID／序号同原始内容返回原摄取身份及已记录决定；同ID异内容、同序号异事件或重用关闭epoch是协议故障，隔离来源、保留原记录、暂停依赖运行，不覆盖旧值。origin_digest沿DF06固定投影；新source_stream_id/source_epoch要显式纳入新版投影，不能改变旧摘要。接收方age_proof不参与来源摘要，但不得因重传刷新原首次接收tick／年龄或新分配触发身份。

离散触发、可靠状态更新及关键结果不得与允许丢弃的展示遥测共用“必需连续”的序列；采样来源必须声明sampled及实际采样／丢失语义。自动化规范订阅必须完整覆盖所选SourceStreamKey的所有序列记录；经过类型过滤而省略该源部分序列的视图首期只供展示，不能作为规范trigger流。订阅previous_cursor连续不等于来源source_sequence完整。采集模块接收到的事实与真实设备物理世界分开：连续source_sequence只证明在该声明采集边界之后无已知记录缺口，不证明设备没有发生未上报变化。无设备序号的协议不能虚构端到端完整性。

## 3. ES02：持久摄取、顺序与失步锁存

候选SourceState字段：source_key、binding_ref、revision、state=`baseline_required|synchronized|desynchronized|quarantined|closed`、contiguous_sequence、highest_seen_sequence、baseline_ref、gap_refs、health_revision。gap记录缺失范围或`loss_extent=unknown`、发现原因、证据和处置；不能把unknown伪写成0条。

| 接收情况 | 记录／保护行为 |
| --- | --- |
| 当前规范通道收到expected_next，身份／内容／年龄合格 | 同事务保存inbox、去重身份、receive_sequence、相关触发决定与execution创建及容量预留，再返回可靠受理 |
| 规范有序通道收到高于expected_next | 记录缺口并进入desynchronized；当前及后续只作观测／核对，不产生新执行；缺号不能用最近快照掩盖 |
| 低序号且仍有原身份／摘要 | 同内容重查原结果，不再次触发；异内容隔离 |
| 低序号且详情已清理但有拒绝floor／墓碑 | 返回历史已关闭／不可再执行，不将“查不到正文”视为新事件 |
| 低序号且完整性不可证明 | 失步或协议冲突；不猜成功、不接受为新触发 |
| 换boot、注册或source_epoch | baseline_required，暂停依赖；新快照只建立状态和新起点 |
| 入口队列溢出、模块已知丢包、采集断档 | 即使尚未分配序号也标丢失并保护，禁止靠连续已保存序号掩盖接收前丢失 |

验证和受理分两阶段：先做有界解析、主体／来源／能力校验及必要证据查询；短writer事务内复核绑定与门控修订、身份、连续性和额度，再原子提交。inbox、规范决定、C04活动槽／execution及关键审计的原子边界不变。规则匹配数量和编译成本必须有限；不能先202，再在无限内存队列中决定是否丢弃触发。容量不足的新身份在可靠受理前429／503；对已存在身份先按独立查询预算返回原结果，不再占新执行额度。

候选EventReceipt扩充`source_key,origin_digest,receipt_revision,ingest_state=committed,trigger_disposition,decision_refs`。trigger_disposition为`eligible_decision_recorded|observed_only|suppressed|rejected`。eligible_decision_recorded只说明触发判定已落盘，不代表设备已发送或执行成功。可靠结果绑定固定决定，重复HTTP提交本身不得重新判定。公开provider事件入口202/200只返回已committed的规范摄取结果；侧通道pending证据通过CaptureReceipt或受限查询展示，不能冒充该成功响应。拒绝状态仅指已记录的不可执行决定；身份非法／内容冲突／未受理仍返回相应错误。

规范顺序必须由注册绑定`canonical_delivery=ordered_subscription|serialized_http`指定，不能哪个通道先到就选哪个。Controller实时来源优先有序订阅；外部提供者HTTP模式必须按source_sequence串行提交／确认，失败后不能跳号。HTTP查询的capture结果可能早于订阅通知到达：可以在同一规范inbox存`pending_canonical`并保存证据，但不推进连续前沿、不创建触发决定、也不仅凭侧通道超前就宣告规范流已经丢失。规范通知到达后只对该pending行做一次CAS升级；超时、规范通道发现缺号、任一保护失效或年龄过期则锁存observed_only，后来重传不升级为可执行。pending预算和等待期限独立有界。这样既共用DF06身份，也不因正常双通道先后顺序误造两次触发。

HTTP与订阅携带同事件但内容不同仍立即隔离，不以pending解释冲突。规范摄取完成后迟到的capture响应仅追加核对引用，不替换已记录决定或刷新年龄；未取得所需连续性及来源证明的capture不能用于时间敏感触发。

失步保护是Seamer本地运行门控，并对已投递未发送的相关命令撤销对应执行绑定／请求出口关闭及核对；不能只停止生成下一命令。已越最终出口的动作继续观察，不自动回滚。未收到远端保护确认保留传播窗口和未决状态，不能把本地pause说成全目标已停止。与接管相同，关键持久化失败时先保护拒绝新写，不能因此宣称暂停操作已经可靠完成。

来源重同步以可信当前快照的source watermark建立新baseline，保存该操作和未补齐的旧gap；只有之后的连续规范增量可恢复synchronized。该状态仅证明从新baseline起的连续性，不能把旧缺失改写为已完整。推进旧序号拒绝floor与新baseline同事务，旧事件即使后来出现也只供审计。来源同步完成与运行恢复分开：依赖run保持paused，显式预检／恢复建立新资格，不能因source变绿自动armed。

## 4. ES03：固定快照、水位与增量切换

推荐快照覆盖与授权scope逐项一致。Controller投影包括设备／能力目录引用、commands、controls、observations及source同步状态；Seamer还包括runs、定义发布引用／激活状态、source状态及相关排期投影。各对象类型需在SDK显式声明，不能用任意Payload冒充完整快照。不可变大定义及原始证据只返回精确授权引用，另取指定revision；不是读当前最新版来补旧快照。

候选SnapshotManifest：snapshot_id、subscription_id、stream_id/epoch、scope_digest、authorization_revision、snapshot_cursor、对象类型清单与各自count、page_count、每页固定digest、manifest_digest、有效期及服务运行域引用。每页含同一绑定、page_index、稳定next_cursor或null。分页cursor与事件cursor采用不同具名类型，禁止互换。next_cursor=null仅说明该页为末页；客户端必须核对全部页数／摘要和覆盖类型才可声明完成。空集合也显式列出。

推荐生成顺序：

1. 鉴权、检查请求scope不超允许范围、预留快照字节／读时长／增量保留额度。在短writer事务中建立订阅和journal保留pin，记录起点J0。
2. 在有界SQLite只读快照中读取同一一致点的状态投影与journal水位J（J≥J0），生成有界暂存页；网络发送不持有读事务。所有设备查询均在该事务外，缓存记录保留真实采样时间，不能刷新observed_at。
3. 短事务复核订阅／授权修订、保留pin与构建期限；发布不可变manifest和页，把有效pin推进到J，状态变snapshot_ready。任何变动、超限或失去日志覆盖均丢弃本次候选并明确失败，不能交付半份成功快照。
4. 客户端在隔离投影中应用所有页；完整校验后原子替换该scope的本地投影并发snapshot.applied。换scope／权限后的旧对象从新scope投影移除，不能把历史缓存显示成当前授权数据。
5. 服务核对确认绑定后从J之后投递有界增量；在同一有序通知链插入sync.ready检查点。客户端处理到该检查点后才标同步完成，之后的新数据沿链继续。构建、下载、追赶期间任一缓冲溢出均resync.required，不跳过中间数据伪报ready。

SQLite WAL读取能提供一致的事务快照，但长读会影响检查点进展；因此限制读事务时间并在网络下载前结束它。跨服务快照是多个独立一致点，不是物理全局快照。（来源：[SQLite Isolation](https://www.sqlite.org/isolation.html)；跨服务边界沿DF04。）

对象增量候选分为upsert（完整授权投影）与delete tombstone，含entity_kind/id/epoch/revision。同修订不同内容是协议故障；低修订不得覆盖高修订。delete保留版本墓碑防迟到复活；对象ID不复用，重新创建用新身份。新完整快照替换其声明scope的对象集合，其他scope不清空。观察到“未出现在部分页”不能提前删除。

过滤后链由服务生成：内部扫描journal，只有允许的对象进入订阅；下一个可见消息的previous_cursor指上一个可见消息。无匹配数据时可发送无对象内容的checkpoint推进保留水位，不暴露隐藏类型／计数。若journal中缺了尚未扫描的一段，即使可能全是被过滤事件，也不能猜无关，必须resync。单订阅交付链保存有界cursor→journal位置及payload digest映射；重复发送使用原cursor、原前驱及原内容，不重分配事件身份。

## 5. ES04：连接、ACK与授权生命周期

推荐首期一个WS连接绑定一个subscription，减少复用后的顺序／授权歧义；多scope可放在同一已批准订阅。浏览器沿F04单次票据和Origin，票据新增精确subscription_id及scope_digest，绑定client_instance_id。服务到服务走DF06 mTLS及单独事件订阅权限，不伪装浏览器Origin、不转用用户Cookie。公开入口不接收自报内部优先级。

候选状态：`building → snapshot_ready → catching_up → live`；任一阶段可到`resync_required|revoked|expired|closed`。新连接附着由服务分配connection_generation并原子废止旧连接代际；旧连接ACK和未释放响应拒绝，已交给传输层的字节不能收回。重复连接不能同时推进同一订阅游标。

| 候选帧 | 字段与约束 |
| --- | --- |
| client.attach | subscription_id、scope_digest、可选resume_binding；只能附着当前主体拥有且当前权限有效的订阅 |
| server.attached | subscription_id、stream_id/epoch、connection_generation、state、预期快照／ACK水位；不授予设备权限 |
| client.snapshot.applied | 完整绑定、snapshot_id、manifest_digest、snapshot_cursor；不能确认其他订阅、旧授权或不完整页集合 |
| server.data／checkpoint | 完整绑定、cursor、previous_cursor、payload_digest、delivery_mode=`live|reconcile`及类型化载荷；客户端不能自行标live |
| client.ack | 完整绑定、cursor、payload_digest、ack_kind=`projection_applied|durable_ingest`；必须覆盖连续已交付前缀且不超过服务last_sent |
| server.sync.ready | 同链检查点、snapshot_id／当前基线引用；仅证明同步链追赶到此，不解除运行暂停锁存 |
| server.resync.required | 原绑定、reason_code、已确认cursor、可公开的失效原因；不含未授权journal范围 |

客户端ACK与服务器游标CAS都只处理单调前进；旧ACK可幂等忽略，相同cursor不同digest或越过未发送cursor拒绝。GUI的projection_applied仅证明当前内存投影完成，页面重载若不能证明保留投影必须重取快照；不能凭localStorage里的cursor跳过状态恢复。Seamer的durable_ingest必须在inbox／来源状态／决定的事务可靠提交后发送；无法落库就不ACK，不在收到socket字节时提前确认。ACK只影响传输保留与客户端进度，不证明设备完成，不解除source失步或run暂停。

重新连接允许有界重传用于显示和审计，但统一标reconcile。原已提交事件仍查原决定；此前没摄取的历史事件仅补观测／记录，不创建直播动作。即便断连很短、TTL尚未过，也不复活失去资格的动作。首次新订阅的快照与追赶同样reconcile；同步完成后再显式布防，边沿检测重新建立baseline。正常同一live连接的ACK丢失重发则保留原live资格和原事件身份，去重保证不重复执行；不是每次传输重试都强制重新触发或暂停。

resume_binding明确含subscription_id、stream_id、stream_epoch、scope_digest、cursor；服务还核对主体／授权修订、保留窗口、确认映射和当前状态。旧draft.4仅数字resume_cursor的请求不能在下一版被猜成当前流。权限改变使原订阅失效，重新订阅和快照，不能原链中静默删除敏感字段后继续。每次页／帧释放前复核授权拒绝下界，关闭连接是清理动作；旧票据不能因scope相同附着新subscription。普通人类退出只撤其GUI订阅，不隐式撤组织自动化服务订阅，沿Q57。

## 6. ES05：分层容量、保留与故障事务

P0保护应用、P1已受理关键证据、P2普通新工作、P3展示遥测沿F04。Seamer必需采样／离散触发使用独立有界入口预算，不放入P3可丢队列，也不能由提供者自报P0。按已受理命令预留的关键结果字节／处理槽优先于新触发和慢GUI；储存不了关键证据时按F03保护，不先丢结果后报成功。

容量须同时限制主体、来源、订阅、全服务的字节、条数、帧深度、构建时长、未确认链、pending canonical、事件匹配扇出及保留pin；仅单个请求限额不够。已受理触发不能因后续压力被丢掉，决定应已可靠提交；尚未受理入口溢出标已知丢失、暂停依赖，而不是背压硬件直到假装没有事件。GUI慢消费只使该订阅resync／关闭，不能拖住设备outbox或其他订阅。

以下`sim-c05-v1`数值只作为候选故障测试输入，**不是生产profile或SLA**；与F04／DF06等同时适用时取更严格上限，不用新名字扩大已有约束。

| 维度 | 候选实验值／失败处理 |
| --- | --- |
| 事件／WS数据消息 | 64 KiB、JSON深度32；重组后总消息与单帧同时限制；首期不协商压缩 |
| 快照 | 页256 KiB、最多128页且总量8 MiB；构建5 s、下载／应用30 s；超限明确失败 |
| 待交付／触发入口 | 每订阅或来源256条／1 MiB；全服务16 MiB；任一先到即保护或resync，不合并离散触发 |
| 订阅 | 每主体8、全服务64；每主体同时构建1、全服务4；超限受理前拒绝 |
| pending canonical | 每来源8、全服务64、最长2 s；超限／超时observed_only并核对规范通道，不执行超前事件 |
| 通知重传窗口 | 最多120 s或10000条，取先达到者；必要历史审计／命令正文保留另算 |
| 活性检测 | 心跳间隔2 s、6 s无有效响应判失联；只用于实验，不承诺真实停发时延 |

心跳存活不刷新任何事件年龄、来源采样年龄或snapshot有效期。状态数据过期与连接活性独立；有心跳仍可能无新鲜观测。检测失联后保护需要测量从发现到Controller最终出口的真实传播窗口，不能用心跳参数冒充撤销时限保证。

| 持久对象／事务 | 必须保存或核对的内容 |
| --- | --- |
| source_state／trigger_inbox | ES01完整复合身份、内容摘要、连续前沿、health revision、pending/committed及资格锁存；关闭epoch拒新 |
| ingress受理 | 同事务去重、额度、源状态、receive_sequence、trigger_decision、C04执行创建及关键审计；pending证据入库不等于触发受理完成 |
| notification outbox | 与权威状态／revision同事务，固定event_id和内容；只通知，不装设备写命令 |
| subscription／snapshot | 主体、scope／授权修订、逻辑流／epoch、状态、固定manifest／页、预算和有界journal pin |
| delivery_cursor／delivery map | 订阅／epoch／代际、last_sent/ack、cursor前驱及对应journal位置／内容摘要；ACK CAS不得跨代 |
| gap／source baseline | 已知缺口及恢复证据、旧gap保留、当前连续起点；新快照不能删除缺失历史 |

ACK不授权删除权威命令、未决证据或去重依据。通知重传窗口的GC与业务审计／防重放GC分开；慢订阅超过窗口先失效／释放pin，不无限拖住全局日志。活动source_epoch保留可拒绝所有旧序号的持久floor；缺口未处理的记录不越过floor删除。无法保存精确旧内容时拒绝旧请求为历史已关闭，不谎称duplicate成功；预算不足停止新受理。旧epoch仅在可靠关闭且永不再受理后归档，DF06 challenge消费墓碑另有约束，不能以订阅ACK清理。

若gap／拒绝记录因磁盘满不能落库，立即本地保护受影响来源和运行，阻止相关新写；不返回“已可靠隔离／已受理”。重启默认未布防并重新核对来源，不能因丢失RAM告警重新运行。已有关键结果无法持久化保持unknown／待核对，不删除证据来换取貌似连续的流。

## 7. ES06：下一版接口与验收交付

保留公开`POST /api/v1/subscriptions`、`GET /api/v1/subscriptions/{id}/snapshot`和`GET /api/v1/events`升级入口，扩充请求／响应及双向帧；新增`GET /api/v1/subscriptions/{id}`查询状态、`DELETE /api/v1/subscriptions/{id}`显式关闭。关闭只释放该订阅，不释放设备控制权、不停止播出。逐资源授权在status.read之外强制实施；请求超范围整体403，不静默缩窄后声称完整scope。

内部服务对应候选`POST /internal/subscriptions`、`GET /internal/subscriptions/{id}/snapshot`、`GET /internal/events`（WS升级）走mTLS及`event.internal.subscribe`、精确来源scope；DF06已有`POST /internal/events`仍为事件摄取，两方法职责分开。机器帧ACK只操作摄取进度，不能取得设备command权限。所有路由与错误尚待下一版OpenAPI归并，当前未实现这些新增路由。

候选错误：401/403身份或范围；409身份／内容／源序号冲突；410订阅／快照／游标保留已结束；412绑定／授权修订／域失效；413请求或单消息过大；422未知类型／非法引用；429可恢复容量拒绝；503关键存储或保护不可用。握手前用HTTP错误，升级后用类型化错误／resync并按协议关闭；WS close code不承载完整领域结果。错误中不放令牌、cursor秘密或未授权对象。

以下**EV01—EV36均为待执行验收规范**，对应A08、A10、A13、A14、A16；不是测试报告。

| ID | 输入／故障 | 必须观察的结果 |
| --- | --- | --- |
| EV01 | 两Controller同名provider／boot／event_id | 来源命名空间隔离，无串账或错误duplicate |
| EV02 | 同ID同内容重传、同ID异内容 | 原身份原决定／来源隔离；均不新建第二执行 |
| EV03 | 同source_sequence不同event_id | 409及隔离，旧inbox不可被覆盖 |
| EV04 | 计数上限、source重启、旧epoch迟到 | 不回绕；新基线；旧epoch拒绝执行 |
| EV05 | HTTP capture响应先于规范流 | pending共用身份，不推进连续前沿；规范到达最多一次决定 |
| EV06 | pending超时或期间撤权，随后规范通知到达 | observed_only锁存，不能升级执行；原年龄不刷新 |
| EV07 | 有序规范流缺序号、后来补齐 | 暂停依赖；历史补齐不自动恢复或补动作 |
| EV08 | 模块入口丢失但已存sequence连续 | 标已知丢失，不以连续日志证明采集完整 |
| EV09 | inbox提交后响应丢失／提交失败 | 重试原结果／无可靠受理ACK，不能重复执行 |
| EV10 | 已可靠受理时busy，通知消费者时已idle | 保持原抑制决定，不能排队成迟到触发 |
| EV11 | 多来源UTC倒序、重传插入 | receive_sequence仲裁稳定，duplicate不分配新顺序 |
| EV12 | snapshot构建同时状态更新 | 状态及水位同一一致点，更新出现在快照或后续增量且不遗漏 |
| EV13 | 分页重复、缺页、换snapshot、错误摘要 | 不发送完成确认；不混合替换当前投影 |
| EV14 | 最后一页为空且next_cursor=null但缺中间页 | 不视为完整快照 |
| EV15 | 构建／下载／catchup溢出或超时 | 明确失效／resync，不报live，不无限保留pin |
| EV16 | run.updated订阅重同步 | runs及所需引用能完整重建，不能只恢复设备状态 |
| EV17 | 同scope完整新快照少了已删除对象 | 完成后替换集合；其他scope保留，部分页不提前删 |
| EV18 | tombstone后迟到旧upsert、同revision异内容 | 不复活／协议故障；对象ID不复用 |
| EV19 | 权限过滤造成journal跳号 | 可见previous_cursor链仍连续，不泄漏隐藏事件数 |
| EV20 | 过滤扫描区间发生真实journal缺口 | resync，不猜缺失事件都不可见 |
| EV21 | 假票据同scope但不同subscription | 拒绝附着；不借scope相同横向访问 |
| EV22 | 双连接附着、旧连接迟到ACK | 仅当前generation推进；旧释放拒绝，承认已交TLS字节边界 |
| EV23 | ACK超过last_sent、错误digest、旧ACK | 拒绝前两者；旧ACK幂等，不推进错误水位 |
| EV24 | GUI收到但未应用、Seamer收到但未落库 | 各自不得发相应ACK；Ping/Pong不代替业务ACK |
| EV25 | 同live连接ACK丢失重发 | 原cursor及事件身份，既有执行最多一次 |
| EV26 | 重连cursor仍有效且历史事件TTL未过 | reconcile补观测，不自动补直播动作 |
| EV27 | 无本地投影的GUI只保留cursor | 强制快照，不能从空页面假装增量连续 |
| EV28 | 撤权发生在快照构建后、帧释放前 | 停止交付，旧scope订阅失效；不按旧缓存授权 |
| EV29 | 人员退出但组织自动化授权仍有效 | 人员订阅失效，组织服务订阅不被误撤 |
| EV30 | 慢GUI、另一GUI和Seamer正常 | 仅慢GUI失步，不阻塞其他消费者或控制出口 |
| EV31 | 普通触发洪峰与已受理命令结果并发 | 预留结果路径可用；新工作受理前限流，不能丢关键结果 |
| EV32 | 单订阅未超限但全服务总量超限 | 全局拒新／有界保护，不能靠开更多订阅绕限额 |
| EV33 | 磁盘满且gap记录失败 | 本地保护、无可靠成功响应；重启不自动布防 |
| EV34 | GC碰到旧请求、未决证据、活跃challenge墓碑 | 保留必要拒绝／证据；旧事件不变新事件，ACK不授权删除 |
| EV35 | 有心跳但来源采样过期 | 时间敏感依赖不合格；心跳不刷新年龄 |
| EV36 | snapshot替换后恢复armed、源值已跨阈值 | 先建baseline并按C04 reset条件建立新边沿，不伪造触发 |

实际验证顺序：候选Schema／原始帧正反例→受控乱序与重复传输→SQLite提交点故障及WAL读时长→浏览器快照替换／撤权→跨服务最终出口和各设备采集边界。证据至少含版本／profile、固定来源及连接身份、注入点、ACK时点、inbox／decision／执行记录、设备写计数及明确未决项。不得用“HTTP 202／WS连接成功”作为完整验收。

## 8. 剩余冻结事项

- ES01—ES06待审阅；源命名空间、stream_id／epoch、投影及双向帧须统一进入下一版SDK／OpenAPI。DF06局部Schema不原地改成完整事件协议。
- [C06候选设计](rebirth-c06-schedule-design.md)已补场次身份、资格／执行投影和独立字段观察绑定，仍须审阅并共同归并；C09／C11逐模块采样与离散事件保证、NodeCG回流去重须按实际协议确认，不借本稿证明任意设备无丢失。
- C04／C05共同冻结“受理时决定”事务、输入扇出预算和失步至出口保护时序；生产容量／最长传播时延由实现后的两平台故障测试批准。
- 本轮仅文档设计；EV01—EV36未运行，未新增机器Schema、数据库DDL或业务代码，未提交／推送。
