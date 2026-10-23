# 屏障尝试恢复与逐传输IPC归并

状态：待审阅。新增 `ipc/0.6.0-transmission-draft.1`，由[唯一生成源](build_execution_ipc.py)输出[完整30帧Schema](execution-ipc.schema.json)。在原46表之后加载[barrier-attempt.sql](barrier-attempt.sql)，构成51表运行保护存储候选。旧0.3/0.4/0.5和旧参考报告保留；本轮不切换SDK权威，不实现业务服务。

## 1. 已知约束与推荐

既有方案要求：缓存缺失不得编造旧屏障生效时间；新尝试采用新barrier_id并保留旧历史；进程换代不能替旧出口证明未发。C11另要求编码准备与实际发送分离，每次重传有独立许可，并同时冻结业务清单和传输清单。（来源：[F02/F03第3节](../../rebirth-f02-f03-design.md)、[C11第8节](../../rebirth-c11-obs-atem-design.md)。）

本轮推荐将**固定cut、一次屏障尝试、原始ACK、采用结果**分开。运行保护的cut不会因查询或重试重算；每个目标出口有独立递增attempt_ordinal。相同进程/连接仍存活但ACK缓存丢失，可在当前目标资格仍成立时重新安装同cut，生成新barrier_id和真实新生效tick。连接或进程换代时，旧target不能改指新出口；旧出口走监督退役证据，替代出口另走启动屏障和完整deny快照。运行来源保护不会借重试改变人工holder/control_version。

人工控制转交的恢复仍遵守“同一尚未被替代的目标版本”；已effective的公共操作只恢复当前写闸，不重复转交。本轮统一了线格式，但SQL五表只连接现有运行保护ce_target，不冒称其他三类屏障已获得完整业务DDL。

## 2. 新字段与摘要

| 模型 | 字段及含义 |
| --- | --- |
| BarrierAttemptBinding | cut_id、cut_digest、target_exit_id、attempt_ordinal、previous_barrier_id。首次ordinal为1且previous为空；后继精确加一并指向同cut/exit的紧邻前次 |
| TransportPacket | packet_id/digest、command/attempt/primitive、writer_exit_id、device_session_id、socket_instance_id、protocol_session、wire_packet_id、tracking_ids、immutable_bytes_ref、byte_length、sha256、transport_profile_ref、primitive_plan_ref |
| TransmissionRef | transmission_id、packet_ref、primitive_id、完整IntentRef、ordinal、kind、cause、trigger_observation_ref、parent_dispatch_intent_id、initial_permit_id、issued_revision、send_window |
| TransmissionPermit | 保留完整控制/身份/时间/面板/运行守卫绑定，新增完整TransmissionRef及budget_revision；每次实际传输用新permit_id |
| TransmissionCoverage | 完整TransmissionRef及disposition/proof；not_sent、in_flight、unknown的证明关系沿用原Coverage |
| PacketAckObservation | 原socket/session/exit、receive_io_seq、raw_ack_ref、wire_ack_id、covered_packet_refs；不含某次ordinal，不直接成为effect_verified |

初始传输ordinal=0/kind=initial/cause=dispatch，observation为空且permit_id等于initial_permit_id。重传ordinal>0，cause为timeout或peer_request，必须有可信观察引用；parent_dispatch_intent_id始终绑定该primitive的原业务意图。不同primitive拥有不同原业务意图和packet；不能以同attempt为由合包或共用许可。

原业务身份和当前发送守卫分开：command/attempt/primitive、来源、原设备连接和包内容保持不变；重传可以绑定重新取得且仍有效的当前guard，但必须逐项验证当前control/gate/authorization/grant、时钟、资源、原截止和预算。新guard不等于准许重试已终态或未知动作。

摘要使用已选JCS/SHA-256约定，带`sha256:`前缀：

- packet_digest覆盖TransportPacket除自身字段；sha256覆盖实际字节；immutable_bytes_ref.digest必须等于字节sha256。ContentRef只供同一可信本机通道和拥有库解析，不能把object_id当可跨服务寻址或授权凭据。
- 两个ledger_digest分别覆盖按permit_id升序且唯一的完整数组；传输排序键为TransmissionRef.intent.permit_id。业务清单保留每个parent的原IntentRef，即使原初次传输已核销而重传仍未决；已核销原件只能作为锚，不能被重新执行。
- cut_digest覆盖`{type,target_exit_id,body}`，其中body为对应FENCE请求正文去掉barrier_id和attempt_binding；含operation、目标修订/selector、issued_cut_revision、两份完整清单和摘要。不同尝试使用相同cut_digest，新的cut或目标不复用。
- request_digest为当前尝试完整请求正文的摘要；ack_digest为完整原ACK正文的摘要，包含真实effective_tick_ns。message_id/reply_to/seq是传输封装，不参与缓存正文身份；查询响应可使用新封装，但正文原样返回。

新计数使用严格U20十进制字符串；数据库中补零20位，线上无前导零。旧借用类型仍存在历史词法，严格原始JSON解码和全部字段统一仍由DF01归并，不能把本轮新增字段检查称作全协议严格解码完成。

## 3. 完整消息与准备链

原21帧保持具名入口，在新版统一增加需要的传输/尝试字段，并增加以下9帧；与其他内部通道仍分离。

| 消息 | 方向与正文 | 约束 |
| --- | --- | --- |
| ENCODE_PACKET | C→W：prepare_id、command/attempt/primitive/device_session、原CommandRequest、计划/profile引用、guard引用及expires_tick_ns | 只编码；不得调用设备写、自动重连写或提前消费permit |
| PREPARE_PACKET | W→C，reply_to原ENCODE：prepare_id、TransportPacket、bytes_hex | 完整不可变编码提案；Controller核对原受理、已批准primitive/codec及字节后才可提交T2 |
| PACKET_ENCODING_FAILED | W→C，reply_to原ENCODE：prepare_id及原因 | 只说明准备失败，不产生设备失败/成功终态 |
| PREPARE_PACKET_REJECTED | C→W，reply_to原PREPARE：prepare_id、packet_ref及原因 | 拒绝准备，不得因此改包重发或转换协议 |
| RESEND_REQUEST | W→C：request_id、packet_ref、cause、observation_ref | 不带可替换payload；同packet最多一个待消费重传许可，原因可合并但不刷新时限 |
| RESEND_DISPATCH | C→W，reply_to原RESEND_REQUEST：原DISPATCH字段、prepare_id、固定packet、resend_request_id及新TransmissionPermit | 可靠T2之后才投递；最后串行发送门控仍与FENCE互斥 |
| RESEND_REJECTED | C→W，reply_to原RESEND_REQUEST：request_id、packet_ref及原因 | 不退款、不重置ordinal，不授权新attempt重做业务动作 |
| BARRIER_UNAVAILABLE | W→C，reply_to原QUERY：operation/barrier、attempt_binding及cache_miss或unknown_barrier | 无coverage、无生效时间，不是未执行证明 |
| BARRIER_STORED | C→W：operation/barrier、attempt_binding、ack_digest及record_revision | 原ACK关键事务可靠提交后才确认；仅释放对应缓存，不改变控制资格 |

DISPATCH继续是C→W非响应，正文绑定已核对prepare_id/packet，transmission必须initial，resend_request_id为空。初发、重传都比较完整原CommandRequest，不能用新parameters配旧packet摘要。

准备请求来自Controller已持久受理及已登记attempt。worker对同prepare_id/完整内容只返回原提案，不分配新wire ID；异内容复用拒绝并保护。准备过期、会话变化或缓存已失效后不得收到许可再临时编码。Controller保存关键字节和身份，再提交首个许可；断开/重启不重放提案或发送。无明确准备回复时只查询/取消该准备，不能把编码失败提升为可自动重做设备动作。

固定实验结构上限为单packet 65536字节，bytes_hex最多131072字符；实际单包、全缓存、队列和速率必须由设备profile进一步收紧，不能把结构上限当设备支持值。完整包可能含敏感控制数据，只在受控本机通道和关键存储流转；普通日志、审计/outbox投影不能记录原字节或秘密参数。预算/profile/纯编码结果提供者仍待产品实现与验证。

HELLO/ACK新增三项必选特性：per_transmission_permit、complete_transmission_fence、barrier_attempt_history，并保留既有特性。版本或特性不匹配保持关闭；不剥掉新字段降级。原方向/seq/peer/reply_to规则继续生效；Schema不证明端点真实性、实际单次消费或消息顺序。

## 4. 四类屏障、查询与证据

FENCE/AUTH_FENCE/TIME_FENCE/RUN_FENCE都增加attempt_binding、open_transmission_intents、transmission_ledger_digest；ACK增加相同binding/digest、完整transmission_coverage及effective_tick_ns。两份集合在同一issued_cut_revision冻结。每出口最多256条业务锚和256条传输，完整字节还受P0 profile限制，超限拒绝全集而非截断。

每条传输必须映射本cut的原业务锚，完整来源/command/attempt/连接不变；guard可按上述规则更新。ACK逐项回显原件，不能新增、漏项、跨出口或重算为当前空清单。已知transport_entered不能降级。业务汇总取所有传输及原已知业务证据的保守上界：任一已发则in_flight，存在unknown或无足够覆盖则unknown，仅完整未发证据才not_sent。最后重传未发不能覆盖原发送。

effective_tick_ns属于该ACK信封绑定的原clock域，必须落在实际请求与接收观察边界内；不与新clock域直接比较，不伪装为UTC。旧attempt的迟到ACK可追加历史及更强发送事实，但不能采用为新attempt的生效结果。真实各进程采样、时钟关系和当前目标有效性来自提供者，本轮仅用合成上下文检查关联，不解决DF03模型选择。

QUERY_BARRIER正文精确绑定operation/barrier/attempt。缓存存在则返回原同类ACK正文；缓存不存在只返回BARRIER_UNAVAILABLE。Controller先将不可确认原因持久，再创建新barrier_id；不能刷新旧ACK的时间或覆盖。查询未知、超时、断连接都不是not_sent证明。

同一出口只丢ACK缓存但消费账本完整时，可利用仍可靠的本地事实；消费账本也不完整则未明项unknown。连接丢失或worker重启不再沿旧exit创建新尝试，旧目标由监督退役核对；新出口另做启动控制屏障并装完整deny。已经应用的target禁止增加尝试，已applied公共保护只查原记录。恢复当前写闸是独立事务。

## 5. 五表写集与物理映射

| 表 | 提交内容及不变量 |
| --- | --- |
| ce_barrier_attempt | barrier_id、fence/exit、精确后继ordinal、previous、request_digest/body、audit及保护outbox同一行；必须已有完整cut且未应用/退役 |
| ce_barrier_failure | 原attempt及cache_miss/deadline_elapsed/channel_lost证据和审计；不表示未执行，已有ACK不能再造失败重试 |
| ce_barrier_coverage | 每attempt的完整原permit覆盖；与原ce_item复合FK，与ACK延迟配对，ACK后不可新增 |
| ce_barrier_ack | 原barrier、effective_tick、ack_digest/body和审计；全部coverage同事务，缺写整体回滚；旧失败attempt的迟到ACK也可保留 |
| ce_result_binding | 每fence/exit只采用一个当前未失败attempt，或明确supervisor_retired；与ce_target_result延迟配对，coverage必须与选定原ACK双向一致 |

先持久原ACK和其覆盖，再独立选择并复制其原覆盖至ce_coverage/target_result。应用汇总仍由全部target齐备后产生ce_application。SQL的当前保守归类立即吸收任何已存ACK的in_flight，包含未被采用或已替代的尝试；不会等最终应用才保留强证据。原ACK/coverage不改写，资源释放仍另需证据。

后继尝试必须引用同cut/exit的紧邻前次，且前次已有cache_miss或deadline_elapsed失败依据；channel_lost直接转旧出口退役核对。尝试/错误/ACK均不可更新删除或REPLACE。请求和ACK正文中的真实摘要、时钟/发送事实由可信提供者核对，SQL不解释BLOB。

物理映射沿用ce_packet.packet_body保存TransportPacket和关键字节引用；ce_permit.permit_body保存完整TransmissionPermit，ce_transmission_commit持久guard/预算/意图；TransmissionRef.intent.permit_id映射ce_permit主键，ordinal和issued_revision分别映射其对应列。ce_item是全部未决传输集合；ce_target.target_body/cut_body还保存原业务锚及两份摘要。锚从每packet原初发许可及不可变业务意图取得，不能根据最后一次状态猜测。此投影提供者未实现，BODY占位检查不证明其正确。

## 6. 故障与验收交付

| 时序 | 必须结果 |
| --- | --- |
| 原ACK缓存丢失，但旧出口仍活着 | 持久失败依据，精确后继新barrier，同cut，重新取得真实新tick；无可靠消费证据的许可保持unknown |
| 新尝试登记后旧ACK迟到 | 保存旧原文及强证据，不采用旧尝试，不覆盖新attempt |
| 原ACK/coverage写入中异常 | 51表快照完整回滚，不确认BARRIER_STORED |
| 原ACK已提交，选择结果中异常 | 原ACK保留；selection/结果/coverage全部回滚，重启只补选择事务 |
| 已有更强在途证据，新ACK称未发 | 原ACK原样保留，当前归类继续in_flight，不核销资源 |
| 新出口借旧attempt回复 | 关联验证拒绝；新出口不能证明旧permit未消费 |
| RESEND_REQUEST与FENCE竞争 | 全部许可签发共享writer切点，实际发送共用串行闸；保护后拒绝新许可，之前已发继续归类 |
| 累计ACK覆盖多个packet | 只追加同socket/session内窗口核对后的packet观察，不冒认某次ordinal，不生成动作成功 |
| 关键事务结果未知 | 查询持久原件，不能以超时创建第二次设备发送 |

离线交付分两份报告：[30帧与关联检查](execution-ipc-report.json)、[51表尝试存储检查](barrier-attempt-report.json)。它们分别绑定自己的输入，不计入旧十份报告清单。参考器使用人工可信上下文、旧帧结构夹具、内存SQL及主动异常；不证明真实鉴权、编码codec、进程缓存、IPC竞态、WAL、掉电或设备效果。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_execution_ipc.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_execution_ipc.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_barrier_attempt.py --report
```

本轮关闭“缺少明确编码往返格式、逐传输屏障格式、同cut尝试/ACK/采用关系”的设计缺口。仍须冻结完整资源/命令终态及其他三类屏障DDL、真实guard/预算与packet准备持久提供者、P1/P4/P0/GC、全部SDK/API归并和候选审阅；不能把新Schema或内存通过作为这些事项已经完成。
