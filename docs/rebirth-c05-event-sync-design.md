# C05：事件、快照同步与容量保护

2026-10-27最新注册交接：[投影注册与持久化](contracts/sdk-scope-handoff/README.md)补齐SP01的Profile／Selector正文、12类视图映射、有限谓词、完整规范来源及窗口外未决覆盖，并接入旧订阅授权模型。7表同事务写集保存注册／撤销及查原；207／226项检查复验通过。真实WAL旧快照仍可见撤销前资格，因此下一步必须完成本机撤权门与页／帧最终释放排序。其余十一类当前领域、完整消费者、订阅DDL及新选择仍缺；原integration1不变。

日期：2026-10-17。状态：**ES01—ES06为待审阅推荐**。已确认依据是Q48、Q50、Q63、Q64及F04—F07；DF04／DF06和C04候选的依赖仍须共同审阅。本稿只补设计，不修改公共draft.4／IPC 0.3，不实现服务或离线自治。

SDK负责事件及同步协议；Controller负责设备来源注册、采集和权威命令／控制事实；Seamer负责规范摄取、观测、触发决定及相关运行保护；GUI维护可丢弃的显示投影；Suite验证版本组合、容量及故障。事件完整性保护不等于替用户设计断网期间继续直播的自动化。

## 1. 已知事实与分析

上一周期SDK交接（以下缺口按当时状态记录）：[命令投影与订阅同源候选](contracts/sdk-event-handoff/README.md)已保留当前取消状态、unknown清资源锁存与原件Ref，并具体化人员／服务owner、15项HTTP操作、双向帧、Ready／附着／基线／ACK及重连边界。86个快照定义完整嵌入122模型图，134／294项离线检查复验通过；不证明完整页面消费者、真实身份、SQLite或网络。其余十一类当前投影、selector／profile注册、持久发送映射及完整新选择仍须联合交付；不得将新帧投到原integration1。

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

## 9. 服务订阅细化与局部机器候选

2026-10-18补充。SS01—SS06为ES04／ES06的待审阅细化，继续采用内部mTLS路线；不改变既有人员票据链或71操作接受集。上节“仅文档”是原轮记录，本节新增[有限候选资料](contracts/c05-subscription/README.md)，不是完整下一版事件Schema／OpenAPI。以下是项目设计推荐；事实依据为本稿第1节、[身份生命周期](rebirth-df06-internal-trust-design.md#9-身份生命周期细化注销组织服务与配对)及[主体矩阵](contracts/df01-source/AUTHORIZATION.md)。

### 9.1 SS01：所有者与凭据分层

`ServiceSubscriptionOwner`固定`issuer_id,issuer_epoch,principal_id,consumer_service_id,consumer_database_instance_id,consumer_id,pairing_id`。这些字段共同构成持久消费身份；不能仅按principal_id或客户端随填consumer_id鉴权。consumer服务及库实例身份从已批准配对／部署登记核对，consumer_id是同服务内有界注册的消费用途槽，不作为秘密。更换库实例必须新订阅及基线，不能把恢复前游标直接借给恢复后的消费者。

本节只接收principal_kind=service、session=null的真实mTLS对端；配对的TLS凭据与组织服务opaque凭据是两条不同用途链。内部订阅不接收bearer替代mTLS，也不要求先获取人员WS票据。第三方服务可通过明确配对和event.internal.subscribe使用允许的状态用途；不因接入订阅就获得Seamer角色或device.command。规范触发用途`canonical_trigger`仅开放给已批准的Seamer消费链，且完整包含所选SourceStreamKey，不能按event类型过滤后仍声称连续。

consumer槽采用ServiceApproval.object_scope下新增具名`consumer_slots`投影：每项`publisher_service_id,consumer_id,purpose,allowed_scope_ref,max_subscriptions`，整体随IL03管理批准接口审阅／减权；接收方仍另有本地交集。每槽首期max_subscriptions=1，旧订阅可靠进入终态并关闭释放资格后才可新建。resync_required／revoked／expired／closed均为该订阅不可复活终态，释放活跃槽而保留拒绝墓碑及必要映射；不能要求已撤权客户先成功调用DELETE才能释放槽。不新增匿名槽登记接口；减少／删除槽先停止对应订阅释放并按来源失步规则保护依赖run，不能因这是订阅管理而遗漏执行链撤销。

`ServiceSubscriptionView`保存owner、publisher_service_id／database_instance_id、stream_id／epoch、scope_digest、authorization_revision、purpose=`status_projection|canonical_trigger`、state、connection_generation、ack_cursor／ack_payload_digest、snapshot_ref|null。owner和scope不可原地改写。authorization_revision指发布者对本订阅授权投影的修订，包含本地批准、peer用途及来源授权；不是证书轮换计数，也不是两个服务共同revision。当前可用证书从配对实时记录核验，不固化成subscription owner。

单纯opaque凭据轮换不改变mTLS订阅；证书轮换也不隐式改订阅scope，但新证书必须已完成DF06双端证明／批准。更换连接仍按SS03新generation和reconcile处理，不能把“同一主体”当继续live的充分条件。权限、来源集合、主体／库身份或配对授权范围改变使旧订阅revoked／resync_required，重新订阅并完整快照。正常运行的短期授权复核只在同范围和同修订下更新有界有效截止，不能复活失效订阅。

### 9.2 SS02：独立服务接口与签发边界

以下均是新增内部候选接口，发布者为Controller或Seamer自己的权威库。访问先核对实际peer和用途；有用途但对象不存在或不归该owner统一404。任何帧及页释放前继续复核当前授权、配对和截止。

| 入口 | 请求／响应与权限 |
| --- | --- |
| `POST /internal/subscriptions` | event.internal.subscribe；已认证peer请求consumer_id、purpose、明确scope及request_id。服务按权威映射构造owner，持久登记请求唯一身份和预算后202返回building的ServiceSubscriptionView。body不能提交owner或active |
| `GET /internal/subscriptions/{id}` | 同一owner当前用途；200返回脱敏view及当前恢复要求。返回只含允许的stream与游标，不含内部journal位置／隐藏事件数 |
| `GET /internal/subscriptions/{id}/connections/{attempt_id}` | 同一owner当前用途；查询非秘密附着结果及是否仍为当前代际，供响应丢失核对，不返回可接管socket的令牌 |
| `DELETE /internal/subscriptions/{id}` | 同一owner当前用途；精确expected_revision，关闭仅此订阅、释放可释放pin，200返回closed状态；不能解除设备控制或删除inbox／命令证据 |
| `GET /internal/subscriptions/{id}/snapshot` | 返回固定manifest；分页使用该manifest下的具名page_cursor，全部页核对owner／scope／授权及发布运行域。任何缺页／过期不以当前数据拼补 |
| `GET /internal/events` | mTLS升级，event.internal.subscribe；101仅建立待attach通道。第一条client.attach绑定精确subscription与owner，之前不交付任何订阅内容；不用URL查询串传token或把Origin当服务身份 |

HTTP创建的request_id以`(publisher,owner,purpose,request_id)`唯一，保存scope请求摘要；同ID异内容409，同内容返回原订阅当前状态，已closed／expired也不创建新订阅。请求没有有效权威不能通过猜旧request_id读取结果。并发创建同一consumer用途按明确的消费槽限制拒绝，不能无限开槽绕过每主体／全局限额；槽注册和目的范围由管理批准，不由首次请求自动增加。

升级前沿ES06 HTTP错误集；升级后只使用本版具名控制帧及有界关闭原因。尚未attach时没有可信subscription绑定，失败仅关闭连接，不伪造一个server.resync.required对象；成功attached后才能带真实绑定报告失步。退出和撤权路径有独立调度预算，不能排在普通数据队列后等待永久阻塞。

### 9.3 SS03：附着、连接代际与恢复资格

`client.attach`包含connection_attempt_id、subscription_id、owner、stream_id／epoch、scope_digest、authorization_revision、expected_connection_generation、replace_existing、resume或null。owner仅是请求绑定，服务必须与真实peer和持久subscription三方精确核对，不能因为结构合法便信任它。初始generation为0，服务成功CAS后递增；已有连接仍登记为当前时，replace_existing=false拒绝，true也必须匹配精确旧generation，防止两个并发实例都声称成功。代际上限保护，不回绕。

`(subscription_id,connection_attempt_id)`唯一并绑定完整attach摘要与服务端实际transport_connection_id。同内容重试仅在原连接仍为当前时重发原attached；同ID异内容或换socket重用该ID拒绝，不能靠幂等响应让两个连接共享generation。新连接先核对原attempt／当前view，再以新attempt和当前预期generation请求替换；历史结果的current=false不得当作新连接成功。attempt墓碑保留到订阅永久关闭，不以通知日志窗口清理。

短writer事务中核对订阅当前状态／授权、预期generation、预算及resume映射，写新generation和attached记录，同时废止旧连接释放资格；提交后才发送server.attached。提交结果不明不发送成功，按connection attempt身份核对；旧连接已交TLS的字节仍不可回收。首期没有“断开后原连接恢复”的状态，所有新连接重新attach，旧generation的ACK、snapshot.applied及数据应用必须拒绝。

状态机区分**内容构建**和**传输恢复**：building／snapshot_ready允许附着并等待完整快照；snapshot.applied匹配当前不可变manifest后才catching_up。合法resume必须有本地持久投影／inbox及已确认映射，发布者将新连接置catching_up，不能直接live。canonical_trigger只接受durable_ingest；服务状态投影可声明projection_applied，但丢失内存投影后resume必须为null并重建快照。服务重启、publisher运行域改变或无法证明manifest仍有效使未完成快照失效，不从旧页继续。

`resume={cursor,payload_digest,ack_kind}`仅允许发布者仍保存的**已确认**水位；客户端先落库而ACK丢失时，服务器水位落后，消费者必须使用服务端已确认点并接受去重重放，不能把客户端较大cursor当作服务器已确认。无法证明保留映射、epoch／scope／权限不符时resync_required并新订阅／基线，不从当前尾部跳过缺口。重复请求不能延长原保留窗口。

到达server.sync.ready后，传输可live；规范来源同步和依赖run的恢复仍各有锁存。重新attach期间交付一律reconcile，既有事件查原决定，未摄取历史只作观测，均不新增直播动作。证书轮换若需要换连接也遵循这个边界，运维需安排预检／恢复，不能承诺无缝自动继续。正常同一generation的ACK重传保留原live资格，避免把ACK丢失误判成新的业务执行。

### 9.4 SS04：确认链及跨代重放

`DeliveryBinding={subscription_id,publisher_service_id,publisher_database_instance_id,stream_id,stream_epoch,scope_digest,authorization_revision,connection_generation}`存在于所有attached后的控制消息。客户端ACK绑定精确cursor、payload_digest和ack_kind。cursor为U20字符串，不能转换Number；ACK必须在当前generation已提交发送的有界映射中，且所确认链的previous_cursor连续、未超过last_sent。小于当前ACK的旧确认只有保留原摘要证明时可幂等忽略；摘要已清理则返回明确失步，不能只按数字大小接受。

服务端payload_digest的候选投影是`SHA-256(JCS({entry_kind,payload}))`，不含连接envelope；payload是具名完整业务投影或具名checkpoint内容，不能以任意JSON代替。跨连接重放保留原entry身份／payload／digest及cursor映射，重新包裹当前DeliveryBinding和delivery_mode=reconcile。因此新envelope不必逐字节等于旧帧；它也不能靠payload_digest证明当前owner、mode或generation有效，这些由受认证通道和当前状态另行核对。source origin_digest仍是另一投影，不能互换。

`client.snapshot.applied`绑定snapshot_id／manifest_digest／snapshot_cursor及DeliveryBinding；发布者核对的是客户端对指定快照的确认声明，不能仅凭该帧证明远端真的应用全部页。可信Seamer实现必须在同一可靠事务完成投影／baseline／拒绝floor后再确认；GUI或普通投影服务按相应投影语义完成。实验中伪造的“已持久化”布尔值不能进入真实API。

`server.sync.ready`是有cursor和payload_digest的同链检查点，包含baseline_snapshot_id；只有追赶所需前缀已交付且客户端已连续处理到它才显示同步。它不授予run恢复权。控制帧没有device.write／permission字段；未知type、额外字段、缺绑定均拒绝。附属机器资料只描述owner／view／attach／ACK及有限控制帧，完整manifest分页、类型化server.data和checkpoint载荷仍需同版归并，不能以本批Schema通过宣告整个事件协议可用。

### 9.5 SS05：撤销、持久事务及有限预算

权限关闭与连接换代在同一释放门排序：先关闭则未释放帧不可再发，先释放则记录不可撤回。收到F04 selector按实际owner／credential／pairing／授权映射作用，人员session注销不得命中service owner。撤TLS credential使该连接立即失去新释放资格；仍有已批准新credential也只能重新attach，不借旧socket延长。普通token过期不被误解成无关mTLS断权，mTLS自己的身份／用途截止独立检查。

持久化补充subscription_owner复合键、consumer_slot、connection_attempt及delivery_mapping。创建事务同时登记幂等身份、owner／scope、预算及journal pin；attach事务CAS generation并写尝试结果；snapshot.applied事务绑定当前manifest与确认；ACK事务验证当前generation及完整映射后单调推进持久ack，才能释放该订阅的相应保留pin。网络发送在事务外：先持久准备delivery entry，再在当前释放门验证并写入传输；只有已提交传输且仍为当前generation的映射才能接受ACK。崩溃后无法证明发送点时重新attach走reconcile，不用未发送记录伪造last_sent。

Seamer消费事务仍采用ES02的inbox／source_state／trigger_decision／execution和审计原子边界，提交后才允许durable_ingest。提交结果未知先查原inbox，不提前ACK、不重新触发。ACK响应丢失可重发同绑定／cursor／digest，绝不重做设备动作。真正并发、磁盘故障和传输层时序要在实现后验证；纯Python顺序检查不证明这些条件。

沿sim-c05-v1所有限制，附加实验值：未attach连接每peer最多2、全服务8、5秒截止；每订阅同时最多1个attach事务；控制消息上限16KiB／深度16；canonical_trigger不使用丢弃式遥测队列。每owner的consumer槽必须管理登记且计入每主体8订阅上限。resume映射超窗直接失步，不为单个长期离线消费无限保留。实验数值不是生产默认或故障传播上界。

### 9.6 SS06：正反例与交付边界

正常轨迹：登记consumer槽／配对授权→创建building订阅→attach分配代际→完整manifest与页→可靠应用→snapshot.applied→reconcile追赶→sync.ready→规范源建立新baseline→人员按原流程恢复run。失败轨迹：Seamer落库后ACK丢失→旧确认点重连→新代际reconcile→inbox去重→保留原触发决定，不重放设备动作。撤权轨迹：帧排队→credential撤销先于释放→旧帧不发送→固定目标receipt；已交TLS帧不谎称收回。

新增运行用例SST01—SST12（均未执行）：①真实peer／owner／consumer库实例错配拒绝；②pending配对不能订阅；③同request_id异scope拒绝；④两个attach竞争只有一个generation成功；⑤旧连接迟到ACK／页确认拒绝；⑥ACK超last_sent／链缺口／摘要错拒绝；⑦落库后ACK丢失重连无第二执行；⑧进程／库恢复失去本地投影时必须完整快照；⑨证书轮换与人员注销分别只关闭匹配链；⑩权限变更发生在manifest构建后／帧释放前阻止旧scope；⑪未attach洪泛与慢消费者不占保护槽；⑫sync.ready不自动resume、filtered来源不能canonical_trigger。

本批附属Schema、手工结构反例和有限关联判定仅验证候选资料；TLS、真实权限、SQLite CAS、网络发送和设备写次数均未验证。完整SDK源归并还需精确HTTP操作、状态/错误集合、完整data／manifest模型、摘要投影注册及consumer_slots管理投影；这些是明确剩余交付，不以局部检查取代。SS01—SS06与ES、IL及C09共同审阅后才能作为实施基线。

## 10. 完整快照交接的字段与事务细化

2026-10-18补充，SP01—SP06为ES03／SS04的待审阅细化。本文的SP编号属于C05，区别于DF01语义迁移的同名探针。下述完整快照指**固定授权scope内的完整投影**，不是全部历史数据库，也不是跨服务、数据库与真实设备在同一物理瞬间的快照。现有七模型Schema尚未包含本节新对象，不能将它们描述为已归并。

**官方事实。** SQLite WAL读事务保持它读取时的一致视图；同一连接正在读取时插入其他写操作可能导致后续读取结果不确定。长读会限制checkpoint推进，多个数据库不提供整体原子快照。（来源：[SQLite隔离说明](https://www.sqlite.org/isolation.html)、[WAL并发及限制](https://www.sqlite.org/wal.html)。）**设计分析。** 因而采用独立只读连接、同事务读取状态与通知水位、完成有界内存构建后结束事务；不跨分页HTTP请求持有SQLite事务，也不把实时设备查询塞进数据库快照。

### 10.1 SP01：授权集合与十二类投影

`SnapshotScopeSpec={scope_id,scope_revision,projection_profile_ref,collections}`由服务核验并固定。每个collection声明`entity_kind,selector_ref,relation_policy,history_policy`；selector_ref指服务端批准的具名选择器及其参数，不接收SQL／脚本／任意表达式。history_policy明确当前状态、全部未决对象和限定历史窗口；窗口排序与截断规则由profile固定，不能在下载时重新计算。scope_digest使用具名完整投影，不包含访问令牌／身份凭据；安装、人员或服务owner另按订阅绑定核验。

| entity_kind | authority与必须表达的状态 | 下一版具名投影及引用规则 |
| --- | --- | --- |
| devices | Controller；逻辑身份、型号／连接与观察质量、当前目录引用 | DeviceSnapshotView；DeviceDescriptor仅作旧源，需独立脱敏投影，不暴露端点秘密或驱动配置 |
| catalogs | Controller；当前已批准目录revision／digest及不可用状态 | CatalogSnapshotView；允许动作／trigger摘要及精确CatalogRef，完整目录按权限另读，不冒充已验证效果 |
| commands | Controller；scope内全部未终结／资源未释放／unknown及明确历史窗口 | CommandSnapshotView；保留phase／outcome／resource状态、控制及证据引用、原设备和请求关联；秘密参数仅给已批准脱敏字段 |
| controls | Controller；持有人、epoch／effective_version、gate、pending与在途／未决引用 | ControlSnapshotView；含有限PendingControlOperationView和TransferOfferView，不靠另取“当前”控制记录补足快照；不能仅显示manual布尔 |
| observations | Controller；每来源的当前有效或已过期观测 | ObservationSnapshotView；值按能力输出Schema和读权投影，保留原采样身份／时间／质量，不用快照生成时间刷新新鲜度 |
| sources | 两服务各自权威；来源绑定、epoch、连续前沿、gap与baseline、资格锁存 | SourceSnapshotView；SourceStreamKey完整，CanonicalSourceWatermark另见下节；丢失范围unknown不能写为0 |
| definitions | Seamer；定义身份、当前发布引用、激活及有权查看的草稿revision | DefinitionSnapshotView；不可变内容给精确DefinitionVersionRef，草稿只表示本快照revision，不隐式取得后续草稿内容 |
| runs | Seamer；定义绑定、arm_generation、状态／暂停原因、当前execution及恢复operation | RunSnapshotView；包含有限RecoveryOperationView和授权状态投影，不暴露凭据；已armed的显示不授权客户端重新布防 |
| business_states | Seamer；状态机ID、当前state、revision及最后transition关联 | BusinessStateSnapshotView；与run／execution同一致点，不从设备observations反推或覆盖业务状态 |
| executions | Seamer；scope内全部活跃／待核对执行及限定历史，步骤和远端command链接 | ExecutionSnapshotView；保存固定plan／generation、required与结果，不把缺失远端详情当作failed或成功 |
| schedule_activations | Seamer；排期版本、激活revision／时间边界、CalendarProfile和资格 | ScheduleActivationSnapshotView；引用固定版本，不因当前配置改变重算已受理场次 |
| occurrences | Seamer；明确窗口内场次及窗口外仍有未决执行的场次 | OccurrenceSnapshotView；occurrence身份、计划时刻／区间、受理或抑制决定、execution关联；展示不补触发已过场次 |

每个scope只列批准的collection；未选择与已选择但count=0不同。前六类属于Controller组合，Seamer组合为sources和后六类；跨authority由GUI维护多个独立快照，不把两库manifest拼成一个强一致证明。同一来源在Controller与Seamer分别表示发布和摄取状态，必须保留authority／source完整身份，不能互相覆盖。

`relation_policy`区分required_in_scope和authorized_reference：前者在同一快照必须存在对应投影，后者给`{authority_service_id,database_instance_id,entity_kind,entity_id,entity_epoch,revision,content_digest}`并按明确接口取指定不可变版本。引用不可见或已过保留期时显示unavailable，不能回退最新版冒充旧版本。跨服务command链接只能是引用，不能声明本库快照已包含远端同一时点的事实。身份／秘密字段不因依赖闭包而自动扩大授权。

十二类下一版模型均须封闭字段；动态观测值只能在已绑定的能力Schema位置开放。不能用`body: any`、任意Payload或直接复用完整管理响应代替这些投影。上表是完整类型与最低字段责任清单，逐字段Schema和公开／内部视图仍是同版归并交付，不能仅靠名称完成C05冻结。

### 10.2 SP02：稳定内容绑定与非循环摘要

`SnapshotContentBinding={snapshot_id,subscription_id,publisher_service_id,publisher_database_instance_id,stream_id,stream_epoch,scope_digest,authorization_revision,projection_profile_ref,publisher_domain_ref}`；其中domain引用受监督运行域的精确ID及摘要，不包含原始NTP内部证据。此绑定**不含connection_generation**；连接身份在HTTP释放上下文和WS DeliveryBinding独立核验。

`SnapshotManifest`具体字段：`format_version,binding,snapshot_cursor,collections,source_watermarks,pages,page_count,total_content_bytes,created_at,expires_at,manifest_digest`。collections按entity_kind固定排序，每项`entity_kind,count,view_schema_ref`；view_schema_ref必须来自固定projection_profile，不是客户端可下载执行的任意URL。pages按page_index排序，每项`page_index,content_bytes,content_digest`；页索引为安全小整数0—127，count及各业务revision／cursor仍按U20十进制串。page_count为1—128；全空scope也有一页空records，不采用0页特殊完成捷径。

`SnapshotPageContent={format_version,binding,page_index,next_page_index,records}`；next_page_index为下一页小整数或末页null，替代旧文字中含混的分页next_cursor。每个record是具名discriminated union，外层`entity_kind,entity_id,entity_epoch,entity_revision,view`；view严格匹配该kind的SnapshotView，不允许自报其他schema。记录按(entity_kind,entity_id,entity_epoch)的固定ASCII身份字节序排列；每实体恰好一条，revision不参与去重键，不能把同一实体两个版本分在不同页。

页的`content_digest=SHA-256(JCS(SnapshotPageContent))`，content_bytes为该JCS UTF-8长度。manifest_digest对**除自身manifest_digest外的完整manifest对象**做JCS＋SHA-256；pages描述已含页摘要，因此不在PageContent中反向包含manifest_digest，避免自引用摘要。`SnapshotPageResponse={manifest_digest,content_digest,content,delivery_binding}`在内容之外附带当前连接绑定，重连后可重新包裹而不改变固定页内容。通道真实性、当前授权和domain另验，hash相等不证明发送者可信或拥有权限。

`source_watermarks`只在canonical_trigger用途携带，完整覆盖所选SourceStreamKey且每项`source_key,binding_ref,baseline_sequence,source_state_revision,baseline_ref,gap_summary`。这些值必须与同一读快照中的SourceSnapshotView相等；不以最高seen替代连续／已核对起点，不删除旧gap。没有完整来源覆盖的过滤展示scope没有canonical资格，不能以空数组声明无缺口。一般展示快照该数组为空，不泄漏未授权来源及journal计数。

数据库一致点不证明设备采样新鲜或来源健康。失步／过期来源仍可如实进入快照，但apply不能据此把它改成synchronized；重建baseline资格还须既有批准的采样／来源证据和ES02恢复规则。snapshot生成本身不主动查询设备、不生成新采样时间，也不生成“缺口已修复”证据。来源不健康不是丢弃整个GUI显示的理由，却必须阻止相关执行资格。

snapshot_cursor为本订阅快照基线的交付链位置，首建为字符串0，内部另保存该位置→journal J映射，公开manifest不含J／J0或全局日志数量。manifest摘要用于snapshot.applied，不能冒充SS04的payload_digest；内部保存具名`baseline_marker={entry_kind:snapshot.baseline,payload:{snapshot_id,manifest_digest,snapshot_cursor}}`的SS04摘要，接受snapshot.applied后才建立已确认baseline映射。之后第一条可见增量previous_cursor=0；没有增量也发送新的sync.ready检查点，不能把baseline确认直接当live。

### 10.3 SP03：构建、发布、下载与重连

构建状态`reserved→reading→sealed→published`或`invalidated`，区别于订阅building／snapshot_ready／catching_up。J0的pin是应用通知日志保留记录，不是SQLite WAL读锁，二者预算独立。独立只读连接禁shared-cache/read_uncommitted，不在同连接遍历时插入构建状态；首次读取journal水位J即固定快照，再在同读事务读取所有投影和来源watermark。所有领域写必须与journal序号／通知同事务，若某类状态未遵守此约束，该类不能获准参与此profile。

按已保留的有界内存构建序列化页，读完并完成集合校验后结束读事务；writer随后复核授权、domain、pin、构建期限、字节和collection覆盖，在短事务保存manifest及**全部页的原字节**、J映射、发布状态和订阅snapshot_ref。首期暂存不跨进程恢复，不使用尚未证明文件／数据库原子关系的外部临时文件。发布事务前进程退出只留下未发布构建记录，恢复使其失效并释放允许的配额；已published原字节缺页或损坏也必须失效，不重新查当前状态修补。

HTTP保留ES06公开／SS02内部manifest入口；具体页面入口分别为`GET /api/v1/subscriptions/{id}/snapshots/{snapshot_id}/pages/{page_index}`与`GET /internal/subscriptions/{id}/snapshots/{snapshot_id}/pages/{page_index}`。需要已attached的当前generation，作为具名expected_connection_generation请求参数核验；它不是secret，不能提供任意文件路径。响应no-store、不返回可跨身份复用的304；读页重复返回同内容，不能推进ACK或延长期限。旧SS02的page_cursor概念在此细化为snapshot_id＋page_index，事件cursor保持另一类型，下一版OpenAPI须一致替换。

每次释放manifest／页前经过与撤销共用的门：目标owner、当前scope／authorization_revision、publisher domain、snapshot有效期、当前generation必须匹配。撤销先于释放则拒绝；已交TLS的字节不能收回。客户端也核验当前上下文，失效时清理相应当前投影，不宣称已送出的数据可撤回。权限变化整体废止旧scope，不在原manifest上原地删字段重新计算hash。

同publisher domain、scope和manifest仍有效的新连接可使用该**固定manifest**重新下载，但消费者丢弃所有旧generation的未完成页，必须在新generation从头验证完整集合；不延长原下载截止，旧snapshot.applied拒绝。publisher重启／运行域变化或manifest过期直接resync_required，按SS01新订阅；已完成且持久投影保留时才可走SS03已确认游标resume。单纯保存一张manifest或部分页不能作为resume证明。

### 10.4 SP04：原子替换、增量与删除语义

客户端先校验manifest版本／权威／scope／domain／期限及摘要，再下载全部页到独立暂存投影。每页核验当前DeliveryBinding、manifest引用、页序、内容摘要与bytes；最后核对全页集合、总bytes、每类count、跨页唯一性／顺序、必需引用闭包、全部具名view Schema及语义、canonical水位与sources一致。重复完全相同页只作重复读取，不累加count；同index不同内容拒绝。任一步失败不得替换当前投影或发送snapshot.applied。

GUI先把旧scope标stale／不可用于操作前提，完整校验后在内存一次切换投影根，再发projection_applied语义的snapshot.applied。Seamer在同一本地writer事务完成新投影generation切换、来源baseline／拒绝floor更新、未补齐gap保留和审计，可靠提交后才发durable_ingest语义确认；分块写入staging可以提前进行，但staging不参与规则匹配，只有最终事务切换active generation。失败或提交未知先查本地apply记录，不提前确认，也不重复消费事件。

服务端接受snapshot.applied时，以`(subscription_id,snapshot_id,manifest_digest)`及当前generation核对；同绑定重复只返回原确认状态。短事务创建baseline映射、ack水位及catching_up状态，之后才释放J之后的增量。snapshot.applied仅是受信客户端的声明，服务不能凭一帧证明远端真正持久化；禁止增加client_durable=true自证字段。确认响应丢失走原确认查询／幂等重发，不能创建第二份快照并拼接。

现有局部SnapshotApplied没有ack_kind字段：应用语义从订阅的已批准用途推导，canonical_trigger要求durable_ingest，普通GUI／状态投影按projection_applied；客户端不能自选较弱承诺。baseline确认后GET订阅view须返回snapshot_ref、ack_cursor及baseline_marker的ack_payload_digest，客户端核对后才能将它作为SS03 resume依据，不能把manifest_digest填入payload_digest位置。

增量`server.data`固定entry_kind=`entity.upsert|entity.remove|source.event`，使用SS04完整envelope；upsert含完整对应SnapshotView，entity.remove含实体身份／epoch／revision和reason=`deleted|left_scope`。deleted表示权威删除，left_scope表示离开该固定selector／历史窗口，不把它当设备消失、命令失败或领域终态；两者均在本scope维护版本下界以挡迟到旧投影，同revision异内容是故障。权限变化仍整体撤scope，不用left_scope继续旧授权链。每种delta的最低version、view及摘要投影与快照使用同一profile，不将补丁路径操作当完整upsert。

source.event承载完整具名规范事件和原origin_digest／年龄／source_sequence；只在规范来源订阅交付，不能用entity.upsert的观测同值变化重新制造trigger。应用快照和reconcile增量只重建投影／基线；不调用C04事件匹配，不新建execution，不重放设备命令。sync.ready进入live只表示该交付链已追赶，来源gap处理、运行暂停和显式恢复仍独立；下一个合法live事件也要重新满足完整执行资格。

### 10.5 SP05：存储键、预算与失败关闭

DF04联合归并增加以下逻辑约束，不在本轮发布DDL：snapshot_build以build_id唯一绑定订阅／scope／domain／J0及额度；snapshot_manifest以snapshot_id唯一且published后不可更新；snapshot_page主键(snapshot_id,page_index)，以外键及页摘要绑定manifest；snapshot_apply以(owner,subscription_id,snapshot_id)唯一保存manifest_digest、投影generation和事务回执；snapshot_baseline以(subscription_id,snapshot_cursor)唯一绑定manifest、J及baseline_marker摘要。public cursor与内部journal位置不使用同列或同类型别名。

发布事务必须同时写齐全部页、manifest和状态；客户端提交事务必须同时写active投影选择与source baseline／floor，不用先ACK再异步补source_state。ACK只释放可释放日志pin，不能删除命令、gap、inbox去重或未决引用。snapshot过期后允许清理页，但保存必要apply／baseline和拒绝墓碑；细粒度GC沿DF04引用感知规则执行。

沿sim-c05-v1：每页**完整响应**≤256KiB、最多128页、manifest与所有页的总响应字节≤8MiB；每页内容JCS另限240KiB，为envelope留空间但仍独立检查完整响应，不能按余量假定必合格。构建5秒、发布后下载／应用30秒，均不因分页重试／重连／ACK重发延长；实际有效期取租约／授权／运行域更早边界。单条投影不能跨页拆开；超单页时显式拒绝，不能删关键字段或拆散unknown清单通过检查。

构建／下载期限在发布者同一受监督时钟域按固定起始tick加预算判定，达到截止即失效；公开created_at／expires_at用于展示，不把可跳变UTC当唯一租期依据。内部build和manifest记录同时保存域引用及deadline_tick，换域不继承旧deadline。客户端无法证明剩余有效期时停止应用并查询当前服务状态，不靠本机墙钟回拨延寿；DF03时间模型选择仍按原复审边界处理。

每主体同时构建1、全服务4继续适用；还须计入总内存及存储预算，先预留再构建。已受理未决状态超过快照容量时保留原证据，拒绝新建过大scope或新工作并进入明确保护／维护；可将展示拆成获准的独立scope，但规范来源订阅不得拆到漏序、删来源或过滤必要事件。此处数字为实验profile，运行测量及生产取值尚未批准。

### 10.6 SP06：关键时序与验收判据

正常时序：writer保存pin(J0)→reader固定J及全投影→结束reader→writer发布全部页／manifest→attach当前连接／下载全页→客户端可靠切换→snapshot.applied→服务baseline ACK→reconcile增量→sync.ready。若attach在构建之前完成，仍只能等待published；下载不允许未附着状态绕过当前generation。

| 用例 | 故障／反例 | 必须证明的结果 |
| --- | --- | --- |
| SNP01 | 在J读出前／后分别提交对象更新 | 每次更新恰落在快照视图或J后的日志，不能两边遗漏；以事务记录核对，非只比较最终同值 |
| SNP02 | 前页旧revision、后页新revision且重新计算摘要 | 跨页唯一性／固定快照证据拒绝混合；hash自洽不足以通过 |
| SNP03 | 缺页、重复页、乱序下载、同index不同内容 | 相同页去重后核对完整集合；缺失或冲突不apply，下载顺序不改变规范记录顺序 |
| SNP04 | collection遗漏runs或count=0与缺collection混淆 | scope／profile精确覆盖失败；空集合有效但不能代表未获取集合 |
| SNP05 | PageContent反向含manifest_digest或任意payload | Schema拒绝未知字段／类型；摘要投影无循环，不用宽松忽略字段修补 |
| SNP06 | 页面gen1在gen2附着后到达 | 当前交付校验拒绝旧代；新代从头核验，不能拼接旧暂存页 |
| SNP07 | 相同页内容用于另一owner／scope／domain | 当前权威和完整绑定拒绝，即使重新计算hash也不能取得授权 |
| SNP08 | 构建pin丢失、读事务超时、发布前存储错误 | 无published成功；不泄漏半份manifest；失效记录与清理有界 |
| SNP09 | 发布提交后响应丢失／原页缺损 | 查同snapshot固定原结果／缺损则resync，不查询当前状态补页 |
| SNP10 | Seamer分块暂存后崩溃或最终COMMIT未知 | staging不触发；核对apply回执，无提前ACK、无第二execution |
| SNP11 | source水位用highest_seen替换连续前沿或漏gap | 完整关联拒绝，不把缺失历史抹掉；run继续暂停 |
| SNP12 | 快照显示armed／值越阈值、reconcile含旧事件 | 只重建显示与基线，设备写计数不增加；sync.ready不自动恢复 |
| SNP13 | remove(left_scope)后迟到旧upsert | 不复活旧投影，不把窗口离开解释为命令失败；其他scope不受影响 |
| SNP14 | 最后页／确认时恰好到期、重复下载试图延寿 | 截止等号拒绝；重复不变expires_at及日志保留期限 |
| SNP15 | 未授权引用／秘密字段／隐藏journal计数 | 逐模型投影与错误响应均不泄漏；缺引用不回退最新版 |
| SNP16 | 单scope／全局容量不足但关键未决状态仍存在 | 不删unknown或gap，不静默缩scope；保护处理及其他订阅不被无限阻塞 |

SNP01—SNP16均是待运行规格；下一版先产生十二类投影、manifest／page／delta的完整Schema与HTTP／WS，再以人工正反例验证字段、摘要和关联，最后验证SQLite／网络／浏览器真实时序。本轮仅具体化设计并复验已有72项服务订阅参考用例，不能把旧检查器计数用于证明本节新对象已校验。SP与ES／SS共同审阅，C05仍未关闭。

## 11. 十二类投影及分页增量的机器候选

2026-10-18后续补充：[快照候选目录](contracts/c05-snapshot/README.md)新增唯一`snapshot.schema.json`，具体化第10节十二类SnapshotView、Manifest、PageContent／PageResponse及Data。版本snapshot-projection/0.1.0-draft.1尚未批准，与现有service-subscription局部模型分别保留；完整公共Schema、HTTP／WS／IPC及SDK权威尚未切换。

机器字段明确以下分界：CommandSnapshotView保留现有八字段RequestIdentity关联，completion_required与completion_achieved分开，取消沿none／requested／confirmed／unsupported／failed词表并绑定operation；PendingControl沿pending／effective／rejected／indeterminate，不能将控制操作effective混作写闸ready。Transfer保留accept_operation_ref，Run内Recovery保留消费及新execution引用。Occurrence将admission_state、qualification_latch和execution_summary分开，accepted后blocked仍保留实际unknown执行，不合成一个掩盖已发效果的状态。

记录外层承载entity身份／epoch／revision，各view不另复制一组可能冲突的同名身份；字段内的对象引用仍需逐字段kind／authority／授权和版本关联验证。SourceKey保持原来源authority，可与发布快照的服务不同；跨服务引用不是本地原子记录。所有固定对象封闭，动态值只在QualifiedValue.value出现并必须通过批准Schema引用的二次校验。当前检查器使用合成批准registry验证该分支，不通过Schema引用联网下载或执行任意代码。

Data信封以`entry={entry_kind,payload}`承载entity.upsert／entity.remove／source.event，SS04的payload_digest正好对entry做JCS＋SHA-256；连接binding／delivery_mode单独检查。source.event的age_evidence_ref是局部候选引用，不替代完整DF06 AgeProof及origin_digest投影；实际来源证据、保留资格、公开／内部视图与新运行域模型须联合归并。不能因字段都有而认为年龄已被验证。

本批107项参考检查包括32结构例、34集合／关联例、15重算摘要后的反例及26增量例。覆盖十二类正例、嵌入控制／转交／恢复、空集合、多页、乱序下载、相同重复页去重、冲突页、跨页重复实体、缺collection／水位、错代、错域、截止等号、大于JS安全整数的游标，以及错误动态值。页及manifest／data的JCS摘要实际计算；授权、domain_current、deadline和必需引用集合仍为人工前提，不取真实服务权威。required_refs检查仅核对明确给定的本地身份／revision，不自动推导完整关系图或验证外部对象摘要。

报告独立绑定五输入；旧72项服务订阅检查只按原范围复验。剩余冻结交付是：所有字段到实际领域记录的逐项投影与脱敏规则、Profile允许的每字段引用／关系闭包、完整语义注册及真实权威提供者、source.event来源／年龄机器衔接、HTTP与WS一致版本和DDL映射。SNP01—SNP16的运行故障规格未执行，未实现数据库、浏览器或服务端状态机，不关闭C05或全系统设计。

## 12. 规范摄取的完整扇出与原子受理

2026-10-20补充。**已知事实：**本稿第2／3节已要求摄取世代、来源去重及决定同事务；[生命周期候选](contracts/c04-lifecycle/lifecycle.schema.json)的RunRecord、EvaluationSnapshot和TriggerDecision仍只有`last_receive_seq`／`receive_seq`，没有摄取世代。其参考模型一次只处理一个run。[恢复核心](contracts/c04-storage/recovery.sql)的transaction_record要求非空run_id，普通trigger_ref尚无inbox／decision本体外键。因此现有局部SQL与299项生命周期检查不能证明一个来源事件的完整扇出原子受理。

**推荐方案：**下面EN01—EN24对应的字段、写集与失败政策一起归并到下一候选版本；本轮仅定具体设计，不暗改原Schema／OpenAPI／SQL，不批准新版本。范围是普通离散事件的摄取；边沿、排期、执行提交和GUI投影仍分别遵循原契约。

### 12.1 摄取游标、首次观察与不可变身份

| 候选对象／字段 | 精确语义 |
| --- | --- |
| ReceiveCursor | `{scope:{authority_service_id,database_instance_id},ingest_epoch,receive_sequence}`；epoch为不可复用不透明ID，sequence为规范U20十进制串。仅同scope且同epoch可比较大小；不同epoch不是“大”或“小” |
| IngestEpoch | `scope,ingest_epoch,revision,state=open/closed,next_sequence,predecessor_ref,close_reason`；同库至多一个open。0仅用于初始水位，事件从1开始；计数到上限前关闭受理并维护换代，禁止回绕 |
| IngressRecord | 固定`inbox_id,source_key,event_id,source_sequence,origin_digest,origin_body,first_observation_ref`；可变`revision,state=pending_canonical/canonical_committed/observed_closed,qualification_latch_refs,canonical_commit_ref`。规范内容一旦确定不可覆盖 |
| FirstObservation | 首次受信接收的`clock_ref,receive_tick_ns,delivery_binding_ref,age_evidence_ref`；可能来自较早capture。重传不替换；换clock域而无法证明年龄时只可降级，不用新tick延寿 |
| IngressCommit | `commit_id,inbox_ref,receive_cursor,source_revision_before/after,match_set_ref,decision_set_digest,trigger_disposition,notification_ref,commit_digest`；只发布已提交记录，pending没有此对象 |
| TriggerMatchSet | `match_set_id,source_key,registry_revision,targets,targets_digest`；targets按run_id的JCS字节排序且无重复，逐项绑定run、definition/version、artifact、匹配触发binding及其修订；全集由Seamer权威匹配索引计算，不接受provider自报run集合 |

SourceStreamKey的source_epoch、ReceiveCursor的ingest_epoch、通知stream_epoch和连接generation互不替代。ReceiveCursor不使用NTP或源设备包序号排序；同一个inbox规范身份至多分配一次游标。pending捕获和重复查询不分配游标；规范消息将pending升级为committed时才分配。已因超时等锁存observed_closed的行，规范消息后来到达仍可记录唯一规范摄取及游标，但其不可执行锁存不解除。

同一来源身份的不同传输绑定只追加受限核对记录，不能把它们当不同事件。原inbox已提交则读取其固定决策集，绝不按当前新注册run补决策；身份正文已GC但拒绝floor仍覆盖时返回历史关闭，不能返回虚构的完整duplicate回执。来源关闭墓碑、first-observation及pending失效下界不因重连、备份恢复或换摄取epoch消失。

### 12.2 完整匹配集合与求值一致点

匹配索引由发布／激活／退役事务维护，按来源绑定和触发种类找出**所有当前登记监听的run**，含busy、paused和disarmed；retired／completed且已注销监听的run不进入集合。状态机内部则由固定CompiledProgram展开全部from_state匹配的转换，包括unknown和并列候选。不得先按当前“可运行”过滤run，也不得只取第一个true转换。无匹配也是合法空集合，仍受理来源身份并保存零决定的摄取账本。

推荐以取得writer并完成前置复核后的数据库一致点作为普通事件仲裁点；不把socket到达时刻或设备墙钟描述为事务顺序。“busy期间不补执行”保证已在该仲裁点判为busy的事件永久抑制，不能扩称能识别所有尚在外部传输中的物理旧事件。失步、reconcile和来源年龄政策继续阻止已知历史消息；无法证明来源资格的消息不作为新触发。

事务外只做有界解码、认证、来源内容校验和必要远端证据取得，缓存固定编译程序。短writer内核对来源／授权／时钟门控、编译产物和匹配索引修订，取得全体run前态及同一数据库一致点的观察引用，再执行无I/O的有限AST。任何远端查询、等待新采样、任意插件调用、编译和网络发送均不得占用writer。预先取得的外部证据只代表其真实采样时刻，当前修订与年龄仍要复核。

容量profile除事件尺寸，还必须分别绑定`max_target_runs,max_total_ast_nodes,max_total_plan_steps,max_total_snapshot_bytes,max_total_outbox_bytes,writer_deadline_ms`；这些是一次完整批次总量，不能把每run上限简单相乘当作已通过。精确生产数值随全系统预算冻结，本节不另造生产默认。准入核对可采用所有候选路径的保守上界；不足则在决定发布前整批拒绝，不截取前N个run或把后半批丢进队列。发布／布防也应预检扇出预算，运行时仍复核。

一个run判为no_match、suppressed_busy／inactive、protected、evaluation_unknown或ambiguous，是完整决定集中的正常可保存结果；不要求所有run都accepted。权限／来源完整性或原子写集无法成立则是整批受理失败。局部run保护不阻止其他独立且合格的run形成决定，但两个accepted执行若争用同一设备，仍由Controller的资源／接管和最终出口仲裁，摄取事务不授双重设备许可。

### 12.3 一次规范受理的写集与返回

正常时序：有界校验／取证 → 短writer检查原身份 → 固定当前匹配全集及容量 → 分配游标和全部决定身份 → 全集求值／封存 → 原子COMMIT → 返回固定摄取引用／发送durable_ingest ACK → 各accepted执行独立建立提交后锚。事件可靠受理与实际执行完成是两个不同事实。

| writer步骤 | 必须一起提交的内容／拒绝条件 |
| --- | --- |
| 1. 身份与前态 | 当前调用者先鉴权；查两组来源唯一键。已提交相同身份直接查原结果，不重新分配或占额度；冲突转来源隔离处理。新身份核对规范通道、expected_next、pending锁存和first-observation |
| 2. 全集与预算 | 固定TriggerMatchSet，复核索引revision；读取全部run/slot/业务状态、观察和当前门控。核对整个批次字节、节点、步骤及writer期限；不得以missing run视为“不匹配” |
| 3. 来源与决定 | 预分配ReceiveCursor、commit_id和各decision_id／可能的execution_id；保存来源前沿／inbox规范状态、匹配全集、所需完整EvaluationSnapshot及每run的唯一TriggerDecision |
| 4. 运行投影 | 每个目标保存受理游标和所需revision变化；accepted同时写ExecutionBinding、完整选中计划、全部StepPlan及初始StepRecord并封存，run/slot指针成对更新；非accepted不得创建execution |
| 5. 审计与发布 | 保存决策集合摘要、容量预留、批次审计和全部通知outbox／逐run审计；封存检查完整target与decision双向集合相等。COMMIT成功后才有EventReceipt或durable_ingest ACK |

决定集摘要覆盖按run_id排序的`{run_id,decision_id,decision_digest}`；inbox固定内容不反向包含commit_digest；snapshot引用固定inbox身份／内容摘要而不是含canonical_commit_ref的可变整行。按“固定inbox → snapshot → decision（预分配execution_id）→ execution／计划 → commit清单”计算摘要，禁止互相包含摘要形成环。最终notification_ref先分配身份，通知内容引用commit_id而不反向嵌入commit_digest；完整payload摘要另存。

trigger_disposition使用确定汇总：有任一accepted／no_match／evaluation_unknown／ambiguous则eligible_decision_recorded；否则有任何run抑制／protected则suppressed；来源资格仅允许观测或没有监听目标时为observed_only；rejected仅用于已持久、明确不可执行的来源政策判定。明细仍以固定TriggerDecision为准，eligible不表示存在新execution。来源身份非法、冲突或未提交不伪造committed receipt。

内部账本保留全部决定；provider只得到本事件的受理身份、去重状态和被授权的投影。provider没有run读取权限时不返回run ID、隐藏决定数量、全局receive_sequence或其决定集合摘要；内部ReceiveCursor及完整decision_refs供受限Seamer接口。旧EventReceipt公开receive_sequence／decision_refs的形状必须在新版本拆为ProviderReceipt与内部IngressCommitView，不能在原字段里伪填0或悄悄删项。拥有run权限的GUI通过该run原授权查询读决定，而非由来源凭据越权读取全扇出。

### 12.4 故障、重复与恢复

| 故障切点／竞争 | 规定结果 |
| --- | --- |
| 两个live通道携同一来源身份 | 仅注册的canonical通道可提交；侧通道只能capture／核对。相同规范重投返回原commit，异内容进入隔离 |
| 目标列表取得后发布／arm／retire修改索引 | writer前置revision不符，丢弃旧准备；只有在尚未形成任何决定、仍证明live且期限有效时才允许有界重取。不按旧列表做部分受理 |
| 任意第N个run写后或COMMIT前失败 | inbox升级、前沿、游标分配、全决定、执行、计划、槽、容量与outbox整体回滚；不可ACK前N项 |
| 已开始形成决定后回滚／资格不可证明 | 不把同一事件自动重做为新live触发。关闭该摄取路径的live资格，按独立保护事务记录失步／受影响run锁存；后续仅reconcile或查原。存储不可写时先关闭入口及请求出口保护，不能假称保护已落盘 |
| COMMIT返回结果未知／响应丢失 | 查原SourceStreamKey与event_id／origin_digest；查到完整commit返回原结果；未能确认则保持未知并保护，不把not_found或超时当允许重新触发 |
| COMMIT成功后、执行锚保存前崩溃 | 已受理决定和execution保留；新进程先保护旧执行，不能用新时间补锚继续。恢复需C04显式新预览／新execution |
| gap／内容冲突／来源关闭 | 原已提交内容不覆盖；独立保护集合覆盖所有依赖该来源的run及未清执行，而不只是当前事件的匹配run。P0保护预算独立且不可截断，持久关闭与远端完成分别显示 |
| epoch切换或旧备份恢复 | 关闭旧摄取epoch，旧run资格失效并暂停；新epoch基线事务不触发动作。原来源身份去重／拒绝下界仍有效，不能靠新epoch使旧事件变新 |

回滚后的保护事务不是原摄取“部分成功”：原事件没有committed receipt；保护是另外的可靠安全事实。失败若发生在鉴权／解码阶段且未建立可信source身份，只拒绝请求，不让未认证攻击者任意暂停其自报来源。已知可信来源丢失、失步和存储故障则沿第3节保护，不等下一条事件才处理。正常SQL锁等待尚未求值时可在固定入口预算内等待；超限失去资格必须保护，不能无限延后到设备空闲再补发。

### 12.5 待运行的原子受理验收

以下是独立人工预期，**本轮未执行EN01—EN24**。后续SQL／参考模型应把每条写语句后及COMMIT前列为切点，对全部受影响表进行前后快照比较；真实磁盘、并发、网络及权威提供者另验，不能用旧1378项局部回归代替。

| 编号 | 输入／时序 | 必须验证的结果 |
| --- | --- | --- |
| EN01 | 无监听run，连续有效新事件 | 一个规范commit和游标、零决定／执行，来源前沿推进且可查原 |
| EN02 | 三run分别accepted、busy、no_match | 一批三决定、仅一个execution；busy事件以后恢复仍返回原抑制 |
| EN03 | 两run accepted，第二个写集失败 | 全批回滚，第一run没有残留execution／槽／扣额／通知，转保护路径 |
| EN04 | 全集超限或末目标快照超字节预算 | 整批拒绝并按来源丢失政策保护，无“前N个成功” |
| EN05 | 同live连接ACK丢失，同内容重投 | 返回原commit／决定；无新游标、额度、锚或execution |
| EN06 | 同ID改内容／同seq换ID | 原账本不改，来源隔离及依赖保护，不只取消当前匹配run |
| EN07 | capture先到，canonical后到 | first-observation不变，单次升级、单次决定；capture不提前ACK规范摄取 |
| EN08 | pending超时／保护后canonical到达 | observed_only锁存；即使当前重新armed也不执行 |
| EN09 | 原决定后新建／激活run，再重投原事件 | 固定旧匹配全集，不给新run补决定 |
| EN10 | 取得匹配集后并发retire或改触发绑定 | 旧revision前置拒绝，不能漏掉新增目标或使用旧artifact |
| EN11 | 同数目但删一个高优先unknown转换换为其他转换 | 全集/产物校验拒绝，不能靠count相同宣称唯一胜者 |
| EN12 | 低优先unknown且唯一高优先true | 在独立保护合格时按既有三值规则接受；不扩大暂停条件 |
| EN13 | 不同epoch均为seq=1；旧epoch大seq迟到 | 不跨epoch比较整数，不覆盖run水位，不产生新动作 |
| EN14 | epoch换代与显式恢复／布防竞争 | 单writer固定基线和新资格；旧预检/CAS失败，不自动armed |
| EN15 | sequence接近U20上限或大于JS安全整数 | 精确比较／递增，到上限维护关闭，不浮点、不回绕 |
| EN16 | 提交后响应丢失／提交结果未知 | 查原完整账本；查不到时不换key或重新触发 |
| EN17 | 提交后锚前崩溃／锚后派发前保护 | 前者新域暂停不补锚，后者旧决定保留但禁止新派发 |
| EN18 | 原身份GC但floor覆盖，或恢复旧库 | 返回历史关闭／恢复保护，不能把缺正文当全新事件 |
| EN19 | provider没有run读取权 | 不泄露隐藏run、数量、全局序号或集合摘要；内部账本仍完整 |
| EN20 | 多runaccepted争用相同设备 | 摄取可记录两个执行，但无绕过Controller仲裁的双重许可 |
| EN21 | 形成busy决定后事务失败，run随后空闲 | 不在下一尝试升级accepted；live资格关闭，保护／reconcile可追溯 |
| EN22 | source失步但本事件零匹配，另有相关在途执行 | 依赖保护仍覆盖在途；远端未确认前不得宣称全部停止 |
| EN23 | 决定集少一项／多一项或同count换run，重算所有摘要 | 封存双向集合和绑定校验拒绝，不以hash自洽替代权威 |
| EN24 | AST求值耗尽writer时限或外部证据已过期 | 不提交半批；关闭本次live资格并保护，无事务内等待远端取证 |

剩余机器交付：ReceiveCursor与ProviderReceipt的新版本接受集、匹配索引／授权投影的权威提供者、完整来源和摄取DDL、原子批次检查器、与edge/budget及C06场次受理的同writer顺序，以及SDK／HTTP／WS／IPC统一归并。EN是验收设计，不是新增运行证据；阶段0保持未关闭。


## 13. 普通摄取机器候选与原子写集检查

2026-10-20补充。**已知事实：**[摄取候选](contracts/c05-ingress/README.md)已将第12节的ReceiveCursor、固定InboxContent、MatchSet、EvaluationSnapshot、TriggerDecision、ExecutionPlanBinding、IngressCommit及ProviderReceipt落实为独立Schema和三接口OpenAPI。原draft.4／IPC0.3及旧生命周期机器文件不改。附属SQL新增15表，与恢复和执行层组成40表；局部连续摄取、pending升级、完整目标集合、逐写回滚和重复查原已有内存检查。

本轮190项离线检查通过（96项结构／关联／接口及94项内存SQL）。重算所有摘要后仍拒绝换来源、换世代、同数目换目标／转换、前态或执行绑定错误；保留低优先unknown不阻唯一高优先true。三run的accepted／busy／no_match可同批保存；busy结果是人工夹具，不等于实际仲裁已实现。每个accepted的PLAN同受理事务，执行锚在之后独立事务保存。

**推荐衔接：**固定回执以当前来源授权查询，provider响应不暴露全局游标、隐藏run或决定集合；内部读采用独立mTLS和对象scope授权。SQL封存显式验证通知／容量记录／逐run审计覆盖，不仅依赖延迟FK；实验曾出现COMMIT成功后foreign_key_check报告缺通知的情况，修正后遗漏在seal被拒绝。此事实限于本组合与参考引擎，不声称所有SQLite版本相同。

EN01—EN24仍是完整验收规格。本候选只覆盖其中部分结构／串行／SQL层，来源gap、冲突、GC/floor、完整保护事务和时限传播未实现；BODY与权威、年龄、真实预算由夹具占位，JSON与SQL未做端到端writer联接。新接口的认证中间件、固定ProviderReceipt持久布局、完整快照/订阅投递、SDK/WS/IPC同版归并继续待落实。参考SQLite3.50.4不构成产品依赖批准；生产并发、磁盘、网络及设备验收未运行，阶段0不关闭。

## 14. 来源失效、完整依赖保护与恢复门槛

2026-10-20补充。**已知事实：**第13节候选只有普通规范受理；其ingress_listener按本条事件的匹配run建集合，不能代表完整来源依赖。当前[draft.4 RevocationSelector](contracts/draft4/first-loop.schema.json)只有session/principal/credential/grant/extension/trust；AuthorizationBinding虽有grant及arm_generation，但没有Seamer scope／run_id。因此直接把source失效转成现有AUTH_FENCE，无法仅凭消息证明精确的运行代次范围。[C04恢复SQL](contracts/c04-storage/recovery.sql)又要求完整未清latch集合匹配；source恢复不能只改一项state为绿。

**推荐方案：**增加独立的运行代次屏障和来源保护账本；下面是版本化候选，未批准、不修改旧公共或IPC接受集。机器字段及有限关联检查见[来源保护候选](contracts/c05-protection/README.md)。不新增自动重试、自动补动作或断网自治。

### 14.1 来源保护集合不是触发匹配集合

权威`SourceDependencyIndex`至少保留三类边，且与产生/退役边的业务事务一起更新：

| 边 | 何时建立／何时允许清理 |
| --- | --- |
| 当前运行的trigger、guard、parameter、edge、schedule来源依赖 | 从固定编译产物、解析后的输入绑定和布防/恢复基线提取；取完整允许路径，不只取本次true分支。解除该运行资格并完成相应保护后才可删除 |
| execution及recovery的固定输入依赖 | execution/预留恢复写入同事务固定；生命周期终态不等于资源或远端提交已清理，须无未决发送/资源/恢复引用才能删除 |
| 运行代次及Controller准备/提交目标 | 在任何可发出的prepare或command意图之前先登记；包括已准备、准备结果未知、命令提交未知、旧Controller/worker世代及未核销目标，不因当前计划不再使用它就删除 |

依赖项绑定完整SourceStreamKey和SourceBindingRef；另保留注册级输入槽绑定。更换source_epoch时，旧槽依赖必须失效并保护，不能把旧边从索引删掉后声称零依赖。未知/动态来源不得发布“完整依赖图”；需先解析出有界可信集合，无法证明时拒绝布防。历史execution边独立于当前监听表，retire新版本不抹去旧事实。

一次保护集合取上述边的并集：所有当前依赖run、相关旧execution/recovery，以及它们所有尚可能接受旧代次命令的Controller目标。每个目标保留来源边证据。即便本事件无匹配规则，source失步仍可能影响其他guard或在途命令。按完整身份排序、去重、双向集合核对；count和自洽摘要都不能替代权威全集。

目标Controller集合来自“可能被该run代次使用”的持久准备登记，不来自已收到的命令ACK列表。准备发送前必须有登记；准备响应丢失不允许遗漏该Controller。旧库无法证明登记完整时不能报告精确保护完成，应关闭相关受监督写域并进入维护核对，明确扩大影响。

### 14.2 记录、身份与单调拒绝

| 候选对象 | 字段与约束 |
| --- | --- |
| SourceFault | `scope,fault_id,detector_domain_ref,detector_sequence,source_key,reason,source_revision_at_detection,observed_event_ref?,gap,evidence_refs,fault_digest`；只从已认证来源或可信本地检测产生。gap为`known{first,last}`或`unknown`或`none`，不把未知缺失写0 |
| SourceProtectionPlan | `scope,protection_id,fault_ref,dependency_index_revision,source_state_before/after,source_revision_before/after,targets,targets_digest,plan_digest`；targets为完整RunProtectionTarget，含run前后revision、当前arm_generation、依赖/旧执行引用及Controller目标 |
| SourceProtectionRecord | `plan_ref,revision,local_state=committed,remote_state=pending/applying/applied/indeterminate,receipt_refs,unresolved_target_ids`；本地可靠提交与远端完整生效分开 |
| SourcePauseLatch | `scope,latch_id,run_id,protection_ref,source_key,blocked_through_generation,created_run_revision,latch_digest`；不可改写/删除。新故障新latch；重复原fault查原，不重复扣预算或增加latch |
| AutomationOriginBinding | `origin_scope,run_id,definition_version,arm_generation,execution_id,execution_binding_ref,step_id,logical_action_id`；Controller从受信Seamer、固定RunGrant和准备记录核对，不能只信客户端自报 |
| RunGenerationSelector | `kind=run_generation,origin_scope,run_id,deny_through_generation`；拒绝generation **≤**下界，scope含Seamer authority和database身份；不复用旧revision_floor的比较语义 |
| ControllerRunFenceReceipt | `controller_scope,operation_id,selector,selector_digest,cut_revision,target_set_digest,barrier_ref,applied_deny_through_generation,coverage_ref,status,receipt_digest`；applied须完整最终出口覆盖及Controller关键事务持久，Receipt不是资源释放证明 |
| SourceRebaselineReceipt | `source_key,old_source_revision,new_source_revision,baseline_ref,baseline_sequence,reject_floor,unresolved_gap_refs,protection_refs,receipt_digest`；状态恢复不删除旧gap或保护账本 |
| SourcePauseResolution | `latch_ref,rebaseline_ref,fence_receipt_refs,resource_resolution_refs,new_arm_generation,preflight_ref,resolution_digest`；为恢复预检证据，只有R4原子消费后才能标latch已清 |

SourceFault身份由受监督检测域及持久/域内不复用序号分配；同fault_id异内容拒绝且保留原件。重复失联告警可引用已有保护，不用每个心跳制造新的全量目标集；新缺口、内容冲突、绑定变化仍必须形成可追溯的新事实。来源state的故障合并只允许增强：baseline_required→desynchronized→quarantined→closed；synchronized首先退出资格。普通重复gap不能把quarantined降级；source_changed与source_closed直接关闭旧key，替代key从baseline_required开始；closed的SourceStreamKey永不再启用。

本地每run独立保存`deny_through_generation=max(已有下界,本次被保护代次)`；保护不假装生成新arm_generation。新恢复代次必须严格大于所有已知下界，且所有清理/资格门槛满足。拒绝下界适用于新的command准入、旧queued、guard签发和最后发送出口；旧同generation请求不能换idempotency key绕过。manual的AutomationOriginBinding必须为null，正常运行代次屏障不匹配manual或其他run／Seamer数据库身份。

### 14.3 事务顺序及跨服务窗口

1. **检测时先本地关闸。** 已确认可信故障立即阻止相关来源新live受理、run新步骤提交及许可续期。此RAM保护是及时拒绝措施，不对外谎称durable；提交结果未知也保持关闸。
2. **Seamer保护事务P1。** 在短writer里查原fault；新fault核对完整来源/依赖索引修订，固定保护全集，保存fault/plan、来源失效与单调下界、全部run暂停/latch、取消待发延迟/边沿资格、保护审计及所有Controller fence outbox。各run revision只推进一次；已completed的历史run不倒改生命周期，但其未清execution/目标仍进入核对。正常设计中retire要求已清理，这种反例是完整性故障，不授予重新运行权。
3. **Controller保护事务P2。** 经配对mTLS和`automation.protect`权限核对Seamer拥有的origin_scope/run绑定。先装内存拒绝下界，再在同设备仲裁锁内提交精确拒绝记录、所有已受理未发/许可的固定切点与完整屏障清单。scope合法但没有命令时仍保存代次墓碑，以拒绝晚到prepare/command，不能把“零命令”当无需保护。权限不能由source provider取得。
4. **最终出口屏障及P3。** Controller给全部现存/旧世代可写出口发送RUN_FENCE；worker只安装单调拒绝并回报真实coverage。Controller核对完整账本和覆盖，在自己的事务保存应用回执/outbox后才报告applied。旧worker仍可能存活时必须覆盖或取得可信退役证据，不能只保护新worker。
5. **Seamer回执事务P4。** 按固定目标、selector、cut和完整覆盖引用核对回执；全部目标持久applied后remote_state才为applied。ACK或Receipt重复只查原，不增加动作或改原执行终态。已越最终出口的命令继续记录事实；unknown仍unknown，迟到证据不重开原执行。

P1不修改已提交的IngressCommit／TriggerDecision，不给未提交原事件补committed回执。若普通摄取已经开始决定后回滚，生成`admission_rollback`故障，执行同一保护路径；它与原事件受理是两个事务。该事件后来只能核对/观测，不能因busy变idle或source恢复而重新升为live。入口排队尚未求值时的有界锁等待沿第12节，不把所有BUSY都当已执行故障。

RunFence outbox可以按原operation/selector重投，因为其作用只有单调拒绝；这是保护传输幂等，不是设备动作重试。准备通道、HTTP准入与worker最终出口都检查同一拒绝下界；只屏蔽worker而仍接受旧prepare会留下复活漏洞。运行代次保护与整设备手动接管共用底层出口证明，但各自的selector和操作账本不得混为同一授权。

新IPC候选定义`RUN_FENCE/RUN_FENCE_ACK`正文，复用已有IntentRef/Coverage的完整世代语义，并新增automation_binding及其摘要回显。完整19帧联合、握手必须特性`automation_origin_binding/run_generation_fence`及HTTP操作仍须同版归并；旧worker不支持则不得授新自动化写许可，不能剥离字段降级。

### 14.4 存储、容量和进程故障

P0预算预留在发布/布防/新增Controller准备目标时核对，按全服务当前可保护的run、旧执行pin及出口上界计费；不用单条事件的max_target_runs替代保护全集。普通触发用尽P2预算不占P0保留。P0本身不足或全集无法证明时不截取前N个目标，应保持本地全局自动化门关闭并请求受监督写域保护，显示尚未完成的范围。

P1失败时不发durable或applied：RAM门保持关闭，立即向已知Controller发具名紧急单调拒绝；此路径只允许扩大拒绝、不开放许可。原fault/selector尚未落盘不能伪造持久Ref；使用已绑定的origin_scope/run代次与当前受监督域证明请求Controller先保护。Controller落盘成功可提供其自己的回执，Seamer恢复后再导入并补本地账本；如果Controller也无法写库，先阻止新Lsend，但仍不报告durable applied。

Seamer崩溃会丢失RAM故障，不依赖“重启后还能记得最后告警”作为保证：启动默认未布防且旧域许可不续期，所有旧未清run和准备/提交意图先保护核对。新进程不能因为本地没找到fault就重建旧直播资格。无法联系Controller时保留传播窗口，租期到期只是后备，不宣称远端瞬时停发。

保护全集必须在单次有界writer中冻结。若无法满足上界，不采用“分批先让前半run暂停、后半继续”的正常路径；本地全局自动化拒绝是先决安全措施，随后维护/核对可分批收集证据，但总状态仍未完整applied。具体上线规模和时间上界由容量profile及真实平台测量批准，本节不制造SLA。

### 14.5 重新同步与显式恢复

重新同步先验证当前授权来源、完整绑定和快照水位；同SourceStreamKey的baseline_sequence不能小于已见序号上界或拒绝floor。原序号无法与快照证明同域连续时，关闭旧key并新建source_epoch，不能对旧key降floor。基线事务保留全部旧gap，提升floor使旧事件永久不可触发；后续合格增量才使新基线后的状态synchronized。

source的synchronized、保护remote_state=applied、设备资源clear、run可恢复是四个不同条件。applied允许保留已发送及unknown命令；只有实际资源/结果证据满足恢复政策才允许新执行。SourcePauseResolution引用新基线、所有精确Controller回执、原latch和资源证据；source再次失步、新fault、下界提升、准备目标变化或预检过期均使该resolution失效。

R2预留恢复仍paused；R3逐目标安装新代次资格；R4在同writer复核全部当前未清latch、source revision/baseline/floor、保护目标及回执修订、run/ingest/slot CAS，原子清理精确latch并开始**新的execution**。任何旧代次命令/边沿/延迟/被抑制事件均不续跑。重baseline不能直接把run变armed，也不能清掉与本来源无关的手动接管或授权撤销latch。

### 14.6 验收与故障时序

以下PFT01—PFT18补足EN03/06/08/14/17/21/22/24和EV02/04/06/09/18，**属于待真实运行的验收规格**。附属参考检查只覆盖结构、人工权威集合和有限串行步骤，不能替代这些平台/网络/并发观察。

| 编号 | 场景 | 必须成立 |
| --- | --- | --- |
| PFT01 | 当前事件零匹配，另有guard依赖和旧execution pin | 完整保护包含二者及所有准备Controller，非空集合不能变空 |
| PFT02 | 同count换掉一个旧Controller或参数依赖run，重算摘要 | 权威双向集合拒绝，不认可count/hash自洽 |
| PFT03 | 未认证者伪报其他source故障 | 只拒绝请求，不创建保护或暂停被冒名run |
| PFT04 | P1任一行后失败／COMMIT结果未知 | 不发可靠完成；本地门仍闭，原摄取不补回执，原fault查原 |
| PFT05 | gap后接内容冲突，再收到普通gap | quarantined不降级，新增事实保留，旧latch不覆盖 |
| PFT06 | prepare先登记、响应丢失、保护随后到达 | 目标仍进入全集，代次墓碑阻晚到prepare和command |
| PFT07 | 同run代次G与G+1、其他run及人工控制混合 | selector只拒本scope/run的≤G；G+1仍须显式恢复及全门控，不因比较不匹配自动放行 |
| PFT08 | RUN_FENCE在Lsend前／后到达 | 前者旧许可未发失效，后者保留在途，不自动反向操作设备 |
| PFT09 | 已退出新worker，旧worker仍持写出口 | 未取得旧出口覆盖/退役证据前不得applied |
| PFT10 | worker ACK丢失、Controller回执丢失 | 原selector幂等重投或查原，完整覆盖不丢，不生成设备动作 |
| PFT11 | 所有fence applied但存在unknown资源 | 仍不能ready或自动恢复；原终态不改写 |
| PFT12 | 全source同步恢复但run有其他latch | run继续paused；不清手动/授权latch |
| PFT13 | 恢复预检后发生新fault或依赖索引变更 | R4拒绝旧resolution，不能只比run.revision |
| PFT14 | source快照水位低于已见上界／floor | 同key拒绝基线；须维护新epoch，不能重放丢失区间 |
| PFT15 | P0容量耗尽／全集超过批准上限 | 本地全局自动化门关闭，保护不截断，保留未决远端状态 |
| PFT16 | Seamer持久化失败且随后进程崩溃 | 新进程默认未布防；核对旧准备/执行全集，不因告警缺失自动重启 |
| PFT17 | busy决定回滚，设备随后空闲 | 旧event只查原/观测，不能重新求值成为accepted |
| PFT18 | 重复fault与迟到较小deny receipt | 原fault幂等；较小下界不能降低当前保护，旧receipt不能完成新plan |

本轮将故障保护的字段、持久所有者、状态、失败行为和恢复门槛具体化；下一步机器归并必须把AutomationOriginBinding一直带到command、guard、permit、IntentRef与RunFence，且补P1—P4物理DDL和实际writer。完整来源GC/floor留存策略、固定ProviderReceipt布局、场次/edge/budget共同顺序仍独立待收敛，不将文稿或参考模型当作已可用直播系统。

## 15. 来源保护HTTP及完整执行IPC候选

2026-10-20补充。[协议归并稿](contracts/c05-protection/PROTOCOL.md)将第14节连接到面板IPC，新增独立0.2保护OpenAPI和IPC0.5共21帧。CommandRequest、Guard、Permit和IntentRef保留同一完整AutomationOriginBinding，GUARD_ACK回显摘要；RunGrant增加origin_scope，定义版本改为正十进制计数，避免旧Version类型与自动化模型混用。原公共和局部版本不改。

新OPEN_GATE携带完整RunDenySnapshot并由ACK回显；新worker初始closed，先安装拒绝下界再开闸。新RUN_FENCE先到时旧快照不能降低下界或漏墓碑，同快照修订不能换正文。统一屏障账本按permit_id排序且唯一、每目标最多256项；这明确替代原两正文包络的多字段排序/4096边界，完整保护仍覆盖全部目标，禁止截断。人工/面板和自动化在既有接管/资源门控下各自保留。

141项离线检查覆盖新结构、原受理到发送来源链、重算摘要错配、快照/ACK/旧出口及两HTTP投影。原19帧回归仅升级后结构，旧面板102项和原保护131项另行复验；不把合成身份与固定账本当实际权威。PIP01—PIP16为待运行故障规格。两个保护接口已具机器格式，但所有公共命令/Prepare接口、实际字段签发者、P1—P4物理DDL、跨epoch重基线、GC/P0与SDK最终统一仍待交付，候选未批准，阶段0未关闭。
