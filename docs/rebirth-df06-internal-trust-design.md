# DF06：内部身份、对象授权、来源证明与查询保护

日期：2026-10-17。细化已确认的TS02、F04/F05和draft.4；IA01—IA06是待审阅推荐，不代表用户已批准新取舍。继续先完成全系统设计，不修改业务实现，不签发证书、开启监听或控制设备。

依据：[身份与容量](rebirth-f04-f05-design.md)、[TS02](rebirth-technology-selection.md)、[draft.4归并](rebirth-draft4-review.md)、[DF02运行域](rebirth-df02-runtime-design.md)、[DF03授时证据](rebirth-df03-time-profile-design.md)、[DF04存储](rebirth-df04-storage-design.md)。候选附属模型版本`internal-trust/0.1.0-draft.1`，不修改公共draft.4／IPC 0.3。

## 1. 事实、缺口与推荐

**当前项目事实。** 两服务各有4个内部时钟GET，声明`serviceMtls`、`clock.internal.read`和`no-store`。Controller还有`POST /internal/auth/introspect`。Seamer的`POST /api/v1/providers/{provider_id}/events`目前为bearer＋provider.publish。当前EventEnvelope有provider、boot和sequence，但没有服务身份／来源注册绑定；CausalAgeBasis只有验证器域和发出／收到tick，没有因果新采样请求端点。上述结构不能单独证明谁有权读取哪个对象，或来源真的进行了新采样。（依据：`contracts/draft4/build_contracts.py`、`first-loop.schema.json`与两份OpenAPI。）

**官方事实。** Node 24服务端必须启用`requestCert`才要求客户端证书；`rejectUnauthorized`仅在该条件下生效。内建`checkServerIdentity`核验主机名／IP，不能把URI SAN当作自动完成的应用身份验证。TLS 1.3的0-RTT没有固有重放保护。RFC9525要求服务器身份使用SAN，不能仅凭CN匹配。（来源：[Node 24.22.0 TLS](https://raw.githubusercontent.com/nodejs/node/v24.22.0/doc/api/tls.md)、[RFC8446 §8](https://www.rfc-editor.org/rfc/rfc8446.html#section-8)、[RFC9525](https://www.rfc-editor.org/rfc/rfc9525.html)）

**设计分析。** 建立四层独立检查：传输对端→当前配对及用途→对象归属→来源与时效。摘要仅绑定内容；权限、真实采样和平台批准必须来自受保护状态。普通只读接口也可能泄露内部地址或耗尽关键证据预算。

| 编号 | 推荐 | 设计边界 |
| --- | --- | --- |
| IA01 | 内部服务直接终止mTLS，绑定具体CA、证书与当前配对记录；公网代理不转发内部接口 | 不信任自报身份头、同名service或仅CN；内部TLS首期1.3，禁0-RTT |
| IA02 | 每请求及响应释放前校验权限与对象归属，当前验证和历史审计分别授权 | TLS连接存在不等于持续有权；已交传输层的字节不可收回 |
| IA03 | 单对象有界查询、有限并发与字节预算，关键核对保留独立额度 | 普通调用者不能自报P0/P1；限额不截断证明或伪造成功 |
| IA04 | 来源注册由Controller背书，Seamer维护本地订阅批准；因果新采样绑定一次challenge及真实只读查询 | 有效mTLS只证明服务来源，不证明设备物理状态或模块诚实 |
| IA05 | 撤销／轮换使缓存和未消费challenge失效，旧域证据只供历史核对 | 新证书、收到响应、重启和重传都不刷新事件年龄或重放动作 |
| IA06 | 公共日志只写允许字段，完整内部证据存独立受限存储；导出需显式筛选 | 不对未知对象递归“尽力脱敏”后公开；日志故障与关键审计故障分别处理 |

## 2. mTLS、配对与凭据生命周期

内部监听与公开GUI/API入口分离；Nginx公开server不路由`/internal/`。跨机可通过私有网络、隧道或四层透传到服务端mTLS；网络位置本身不授权。本机也验证应用身份，不因127.0.0.1或同容器网络而信任。内部mTLS若要在代理终止，须另定受认证代理协议并专项审阅，不能靠`X-Client-Cert`等头默认替代。（Nginx的`optional_no_ca`不要求可信CA，不能当成已完成mTLS验证；来源：[官方SSL模块](https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_verify_client)。）

首期推荐专用部署信任包，限定允许CA及链用途，不使用系统全部公共根自动认可内部客户端。两端检查有效链、用途、认证时间和精确配对；客户端额外按配置的DNS/IP SAN校验目标服务器，禁止CN-only和通配符身份。应用服务身份由受保护配对记录中的证书DER SHA-256与SPKI SHA-256映射到`issuer_id/issuer_epoch/peer_service_id/credential_id`，不从证书显示名称推导角色。本候选不引入需要自行解析URI SAN的新PKI命名协议。

`InternalPeerBinding`持久字段：binding_id、revision、local_service_id、peer_service_id、peer_service_kind、issuer_id/epoch、trust_bundle_digest、credential_refs、permissions、allowed_source_binding_ids、state、scope_digest。每个credential记录credential_id、certificate_der_sha256、spki_sha256、not_before/expires_at、state。certificate更换必须显式登记，即使SPKI相同；相同密钥不得同时映射不同服务。指纹从真实已验证证书字节计算，不接受请求body携带的“证书指纹”。

`scope_digest`为SHA-256(JCS(用途、允许来源、对象范围等完整授权投影))；排序与投影归并SDK时固定。它不是权限票据。两端binding_id可不同，交换和核验各自引用，不把同一个revision数字当作跨服务共同版本。

两端`pending → active`各自可靠提交，尚未完成的一侧不得使用对端自报active补齐；局部已active也只能在对端接受时通信。轮换先验证新凭据控制权及同一服务身份，登记有界重叠，再撤旧credential；新增CA、服务或用途属于增权，须原有管理批准。旧credential被撤即永久拒绝，不因后来的revision变大复活。配对撤销触发F04 trust/credential相关保护；重配是新记录和新批准。

已建连接不延长证书、配对或用途期限：每请求及释放响应前复核当前状态。首期新连接要求完整握手，不使用TLS会话恢复或0-RTT；连接复用只复用传输，不能复用旧授权判定。实现须证明客户端不提交旧session、服务拒绝意外resumed连接，并测量并发握手预算；后续开放恢复须另验身份与撤销绑定。证书临近到期可提前建新连接，但不能自动更换信任根或延长旧凭据。

认证时间采用F04独立区间与保守截止，不以DF03业务NTP偏移修改TLS有效期。CA签发工具、算法组合、证书寿命及轮换重叠的精确发布profile仍需与Suite安装设计归并；本轮不生成密钥或选择未验收的生产参数。

## 3. 对象归属与响应释放

服务内部从TLS socket和当前权威状态构造`InternalRequestContext`：local_service_id、peer_service_id、issuer/epoch、credential_id、binding_id/revision、connection_id、request_id、permission、object_scope、auth_deadline和本地域。它不是客户端可提交的JSON模型。只接受服务内部传入的已鉴权上下文；模块、GUI及HTTP头不能构造它。

对象查询键至少为`authority_service_id + object_kind + object_id + exact_revision(适用时)`，所有者由本地表／不可变记录得出。对象记录另绑定database_instance_id与所属runtime domain，恢复后旧对象归为历史；不以URL中的service_id、猜中ID或全局同名对象证明归属。数据转发必须仍向原authority验证，不让Controller A冒充Controller B产生证据。

| 路径／对象 | 当前请求的授权规则 | 返回边界 |
| --- | --- | --- |
| `/internal/clock-domain` | 配对允许本authority当前运行域且有clock.internal.read | 只返回当前descriptor；不能靠该路径替代旧domain查询 |
| `/internal/time-evidence/{id}` | exact对象所有者、来源范围、clock.internal.read，且当前验证关联成立 | 原结构化证据，不返回raw_response正文或可任意访问的路径 |
| `/internal/clock-samples/{id}` | 样本与证据／provider绑定且在允许来源范围 | 不用最新sample替代指定ID |
| `/internal/time-profiles/{id}/{revision}` | exact ID＋revision＋authority在本地允许profile集合 | 能读取不表示profile批准；许可与批准清单独立 |
| `/internal/auth/introspect` | 已配对目标服务，auth.introspect用途，audience必须为该peer | issuer只返回该服务所需快照；不再依赖待查询token来证明查询服务自身身份，避免递归 |
| 候选`POST /internal/events/sample-challenges` | events.internal.sample用途、允许source及只读能力、当前pairing | 返回本次观察及回执；不能调用任意能力、任意URL或设备写动作 |
| 候选Seamer `POST /internal/events` | events.internal.publish用途、实际mTLS服务与注册owner精确一致 | 202只表示inbox可靠受理，不表示新鲜度合格、自动化触发或设备执行 |

保留现有4个GET路径；下一版用独立内部查询参数`purpose=validation|audit`明确用途，默认validation。audit要求新增`clock.internal.audit.read`与精确历史范围；该参数只选择用途，不授予权限。历史信息可读不等于可参与当前写许可；validation不得用历史域或已撤批准满足当前门控。旧descriptor审计需要新增按不可变引用查询的专用路径，不能复用当前GET返回旧值；精确路径随下一版API归并。

顺序：有界握手→认证对端→解析有界请求→当前binding／用途→对象归属→有界读取→当前授权复核→一次释放响应。数据库读取和异步序列化之后都可能发生撤销；在释放门`Lrelease`与撤销应用点串行排序。撤销先发生则丢弃未释放正文；释放先发生则记录已释放，不能声称已回收网络字节。普通查询不产生设备许可或自动布防。

无证书／无效TLS在握手拒绝；已验证服务缺用途返回403；用途具备但对象不存在或不属于其范围统一404。授权状态不可确定／关键存储保护返回503，额度不足429，过大413，结构错误422，revision冲突409。以上错误也`no-store`，不返回对象存在性、内部路径或对端证书正文。不得声称时序侧信道绝对消除，相关差异须负载验收。

当前4个GET只列200/401/403/404/412/503；429、413、422及明确状态→原因码映射属于下一版显式补齐，不声称旧OpenAPI已覆盖。412继续表示指定前置条件不成立，409用于本轮新增带修订的操作冲突；握手失败不伪造HTTP401。

## 4. 来源注册和不可变事件

Controller为已批准模块建立`SourceRegistration`，绑定owner_service_id、database_instance_id、provider_id、provider_boot_id、device_id、trigger_id、capability_version、模块制品及批准revision、capture_policy_id/revision、delivery_semantics。注册只允许设备能力声明的事件；模块自报source ID不成为可信来源。Seamer另保存本地授权订阅／用途及当前配对，不把远端注册直接当本地批准。

现有bearer＋provider.publish入口保留为已登记提供者的输入边界，令牌主体必须与provider及允许能力相符；不因为payload带causal/UTC字段就升级为可信证明。可信Controller跨服务转发走新增内部入口；Seamer自有数据源由其本地批准的提供者建立等价来源记录。外部输入无法取得所需来源／年龄证明时标unproven，只用于允许的展示或不要求该证明的用途，不扩大既有触发权限。两类入口共用来源命名空间、摘要与inbox去重，不产生绕过一次消费的第二通道。

候选`SourceBindingRef`含registration_id/revision、owner_service_id、database_instance_id、provider_id、provider_boot_id、device_id、trigger_id、capability_version、capture_policy_id/revision、delivery_semantics=`sampled|discrete`。它用于绑定，不是签名或授权。任何字段变化都生成新引用；重启换provider_boot_id，不重置旧来源的序号去掩盖缺口。

下一版引入`origin_digest = SHA-256(JCS({source_binding, event}))`。`event`固定包含draft.4 EventEnvelope的全部来源字段：event_id、provider_id、provider_boot_id、source_sequence、trigger_id、capability_version、device_id、occurred_at、observed_at、clock、payload，以及存在时的causation_command_id；仅排除接收方产生的age_proof，不删除嵌套同名字段。新增来源字段必须显式升版投影，不能按任意字段名自动删减。来源序号仍是大整数串。

接收方核对TLS实际peer与注册owner、当前订阅批准、producer boot、能力／设备／trigger、原始内容digest和去重身份后才记录来源可信。相同event_id或sequence却不同内容是协议故障，隔离该来源并暂停依赖运行，不能覆盖旧inbox。重传携带原event内容／原时间／原序号；年龄证据由各接收方自行建立，不转用其他Seamer的causal tick。

DF04原`trigger_inbox(provider_id,provider_boot_id,event_id)`必须在下一版表契约中增加authority/source registration命名空间，避免两个Controller同名provider串账；unique sequence范围同步扩大。此为设计修订，旧探针与draft.4不原地改写。来源断开重连、序号缺口和快照衔接仍按C05，不能靠新采样掩盖离散边沿缺失。

## 5. 因果新采样与challenge

验证器在本地建立一次待决challenge，然后发送到允许的Controller。请求字段：schema_version、challenge_id、verifier_service_id、verifier_domain、source_binding、scope_digest、max_age_ms。challenge_id至少256-bit CSPRNG，固定64个小写hex；服务器不能只凭ID授予访问权限。`scope_digest`绑定版本、验证器service/domain、source_binding及max_age_ms。来源从实际mTLS对端验证verifier_service_id，不读取客户端提供的自报可信标志。

本地`PendingCapture`保存challenge_id、request_digest、来源／配对双方引用、verifier_domain、sent_tick_ns、expires_tick_ns、state及result_digest。sent_tick在首次发送之前取得，重试不刷新；有效期严格`now < expires`。它是运行域内受保护状态；落库审计只记录其固定身份和消费结果，重启后所有未决challenge失效，不恢复旧单调deadline。

来源处理顺序：认证及范围→唯一challenge登记→排队时再次确认期限及能力→执行已批准只读查询→收到同设备会话／query ID的新响应→保存事件和capture receipt→返回。设备只读查询也必须受限并遵循模块协议，不接受调用者指定method、payload或URL。不能从旧缓存读取后给它一个新observed_at。对设备协议无法证明“本请求之后的新观察”的能力，只能返回不支持；不得宣称设备物理测量时间已获证明。

来源在自己的运行域用接收tick加`min(max_age_ms,本地profile上限)`形成更早查询预算，不直接比较验证器tick。验证器仍从原sent_tick计入完整往返。来源登记在查询前可靠提交，以(peer、challenge_id)唯一，并保存request_digest与状态；提交失败不查询。验证器消费与规范inbox决定同事务，崩溃后只查持久结果，不从RAM丢失推断未消费。

`CaptureReceipt`绑定challenge_id、request_digest、source_binding、scope_digest、origin_digest、event_id、source_sequence、capture_query_id、source_session_id、capture_policy_id/revision及capture_mode=`fresh_query`。这些字符串的存在不能证明新查询，来源Controller必须核对模块回执、受监督IPC会话及批准能力；原始证据受限留存。可信Controller／适配器能如实报告查询是条件假设，mTLS不防御已失陷来源服务伪造数据。

相同challenge的首次请求注册为pending，重复请求只查询原结果或返回pending冲突，不能再次采样；同ID异request_digest拒绝。来源重启／注册变化后拒绝旧请求并标失效，不把它当新challenge。当前配对、source、观察和保留状态均合格时可重传同一个完成结果，但不得重建采样时间。设备查询发生而结果持久化失败时记录不确定／拒绝返回合格证据；不得用重采样覆盖原challenge。

过期只能清理大正文，不能删除活跃命名空间内的消费／拒绝墓碑后让同ID重新采样。墓碑直到相关verifier域被可靠关闭、旧域永久不再受理后才能随其归档；旧域拒绝依据继续保留。来源先通过已配对、固定地址的域查询核对验证器当前域，不向请求指定地址回调；缓存仅有界有效，无法核实则拒绝新采样。墓碑预算单独限额，耗满停新受理，不以GC抹掉防重放依据。全事件存储设计须据此补source capture表及epoch关闭规则。

验证器收到响应时保存本地received_tick，核对来自原peer、request/source/digest/域及待决状态，并用CAS将pending改consumed。结果丢失后再次收到同一响应只返回原处理记录，不再次触发。若消费事务结果不明先查询持久身份，不重新执行规则；新challenge也不是重放旧业务动作的授权。

因果年龄上界为`ceil((now_tick - sent_tick)/1_000_000)`，下界0，sent≤received≤now，所有tick仅在验证器同域比较。沿用已有年龄阈值语义：上界≤max_age允许，challenge期限本身仍严格小于expires。排队、查询、传输及验证后的等待都计入；不能只用received−sent锁定一个不会增长的上界。sampled结果可参与声明允许采样的状态规则，不能生成离散边沿或证明缺口不存在。

来源发布该观测时，事件与回执先入同一持久序列／outbox，HTTP和订阅流使用同event_id／sequence／origin_digest；两路到达按同一inbox去重，不形成两次触发。响应领先订阅流不允许静默跨越缺失sequence，完整C05规则另行归并。UTC证明沿用DF03双方可信链，未证明时间可展示但不能冒充新鲜触发。

## 6. 撤销、容量与日志

配对／credential撤销先更新内存拒绝下界、阻止新查询及未释放响应、失效未消费challenge，再可靠记录并形成F04 receipt；关闭连接只是后续清理。若旧credential另有执行授权，执行保护仍走AUTH_FENCE，不因本节只读流程遗漏。来源／能力撤销、provider重启、验证器换域、授权或认证时间失效均使相关pending结果不可用；已消费结果保留事实，但不能复活旧run或补发被阻止动作。

容量候选`sim-df06-v1`只供故障测试：每peer内部请求并发4、全服务16；单次请求64KiB、响应256KiB、JSON深度32；每peer未决challenge8、全服务64；排队及总请求deadline2s；每peer10/s、burst20；单独关键核对预留4槽。均需两平台实际负载后才能成为release profile，不承诺SLA。无自动放大或null无限值；HTTP禁止压缩请求，响应本轮不压缩，后续启用须限制解压大小。

关键核对额度只由服务根据已可靠受理的operation和实际对象归属选择，远端header/body不能自选优先级。普通历史查询与诊断不得耗尽已受理命令结果、撤销及屏障预算。保护消息不走普通证据GET队列；超时／429只说明证据未取得，不能当作“已取消”“未发送”或“对象不存在”。未知结果与相关资源继续保留。

证据查询只读不可变单对象；本轮不提供任意过滤、全量枚举、任意SQL或自动跨对象递归拉取。单对象超过响应上限时明确拒绝，不截断列表／coverage后返回200。缓存以authority、object引用和digest索引，并受当前读权限约束；缓存命中不能延长认证、时间证据或challenge有效期。读连接／队列与DF04 writer预算分离，长读不能长期占住WAL快照。

公共日志采用固定DTO允许列表：时间、服务公开ID、operation/request ID、固定原因码、phase、受控计数及延迟桶；名称、payload、URL、IP、文件路径、证书、token、Cookie、challenge原文、设备秘密、原始NTP响应和异常对象正文默认不输出。客户端输入的message、嵌套对象、栈和未知字段不进入公共日志；CR/LF等仅留安全编码后的受限诊断。摘要也可能可关联，低熵秘密不以hash代替脱敏。

完整审计与内部原始证据使用受限角色／存储／保留策略，普通GUI只读已授权投影。支持包按模板复制允许字段并重新检查秘密，默认不包含内部原件；诊断导出不自动上传。认证查询token等秘密不进入内部普通日志。普通日志写错降级告警；关键来源／challenge消费／授权审计无法持久化则保护相关处理，遵循F04/F03，不在日志函数里自动停止播出设备。

## 7. 故障时序与验收

| 时序 | 必须结果 |
| --- | --- |
| 握手通过→排队→撤credential→准备返回 | Lrelease复核拒绝正文；不沿用握手时权限 |
| 返回已交TLS→撤销 | 记录已释放不可回收；其后请求／challenge停止 |
| challenge发出→来源新查询→撤来源→旧响应到达 | 拒绝新鲜触发，保留审计，不能重新标来源active |
| challenge发出→验证器重启→旧响应到达 | 域／待决状态不匹配，拒绝，不重建pending |
| 响应到达→消费提交结果不明→重复响应 | 查询原消费身份，不再触发或新建执行 |
| 普通查询满→撤销／在途核对到达 | 预留路径可用；若关键路径也故障则保护，不报应用完成 |
| 查询源与本地同名provider→摘要合法 | 所有者不匹配拒绝，不能跨Controller串账 |

IN01—IN32为待执行运行验收；参考夹具不替代TLS、数据库并发、真实设备新查询或日志链路测试。

| 编号 | 注入 | 期望 |
| --- | --- | --- |
| IN01 | 无证书／错CA／错用途／过期 | 握手或身份层拒绝，无内部正文 |
| IN02 | DNS/IP不符、CN-only、同名服务不同证书 | 不因名字相同获配对权限 |
| IN03 | 公网伪身份头／直连内部接口 | 公开入口无路由，内部需真实mTLS |
| IN04 | 合法证书但binding pending/revoked | 拒绝；连接不是授权 |
| IN05 | keepalive期间撤credential／认证时间失信 | 释放前拒绝，已释放如实审计 |
| IN06 | 旧TLS session／0-RTT重放 | 不接受首期内部应用数据 |
| IN07 | 指纹登记轮换失败／两端批准不同步 | 不自动active或扩大范围 |
| IN08 | 读取另一authority的同名对象 | 统一404，不泄露存在性 |
| IN09 | 指定旧profile revision已GC／不存在 | 不用当前版本顶替 |
| IN10 | 只有普通读权限请求历史audit | 拒绝；历史证据不入当前门控 |
| IN11 | introspection token属于另audience | 不返回可用快照，不递归依赖该token鉴权 |
| IN12 | 大body／深JSON／压缩体／巨大响应 | 有界拒绝，不截断成功 |
| IN13 | 单peer突发和多peer公平竞争 | 普通额度隔离，预留核对不被自报优先级挤占 |
| IN14 | 查询长读阻塞checkpoint／writer压力 | 保持限定快照和deadline，关键失败保护 |
| IN15 | 模块伪owner/provider/device/trigger | 拒绝来源，不仅核对hash |
| IN16 | 同event ID／sequence异内容 | 保留旧记录并隔离来源，暂停依赖运行 |
| IN17 | 正确fresh query及双通道重复事件 | 只消费一次，保留原捕获身份 |
| IN18 | 从缓存重标时间／旧设备响应冒充新查询 | 无合格来源证据，拒绝因果新鲜度 |
| IN19 | sampled challenge指向discrete能力 | 拒绝，不能补造边沿 |
| IN20 | 改scope、来源revision、能力或request digest | 拒绝，不接受重新摘要后的自授权 |
| IN21 | challenge重复／同ID异内容／双消费者 | 不二次查询，不二次触发，冲突可观察 |
| IN22 | source重启／设备session切换／审批撤销 | 旧响应失效，不静默转到新来源 |
| IN23 | verifier换域／跨主机tick相减 | 拒绝年龄证明 |
| IN24 | now等于deadline；年龄恰好上限和加1ns | deadline等号拒绝；年龄上界按ceil并≤阈值 |
| IN25 | 收包后等待再触发／重传旧包 | 年龄继续增长，不因收到重置 |
| IN26 | 采样后持久化失败／消费提交未知 | 不报合格消费，不重采样覆盖原请求 |
| IN27 | 响应领先事件流且存在缺口 | 去重但不掩盖缺口或补动作 |
| IN28 | 字段嵌套秘密／异常栈／恶意换行 | 公共日志只有允许字段，秘密无泄漏 |
| IN29 | 支持包导出含内部证据／低熵秘密摘要 | 默认排除，明确授权的导出也需检查 |
| IN30 | 普通日志故障对照关键审计故障 | 前者降级；后者保护对应处理，不自动黑场 |
| IN31 | 备份恢复含旧binding／challenge／inbox | 新实例身份和拒绝下界生效，旧结果不触发 |
| IN32 | Windows/Linux及容器真实网络负载／抓包 | 分别证明身份、截止、容量及脱敏，不借用纯离线结果 |

## 8. 归并及未决

需归并下一版：来源绑定与origin摘要、trigger_inbox命名空间、sample-challenges请求／回执、内部GET用途及历史descriptor接口、配对字段和权限表、日志DTO与预算profile。当前draft.4／IPC 0.3保持原字节；附属Schema与[参考资料](contracts/df06/README.md)仅校验本轮有限结构／决策，不是完整下一版SDK。

设计未决：IA01—IA06审阅；证书发行／寿命profile、SDK完整投影与源迁移、C05全事件快照与订阅语义、各模块fresh-query证据、Suite内部监听和安装证书配置。实现后取证：IN01—IN32、F04撤销窗口及TLS／OS／数据库／设备实证。DF06形成具体方案不等于全系统设计已经完成，其他C01—C12和旧功能映射继续按实施前清单推进。

## 9. 身份生命周期细化：注销、组织服务与配对

2026-10-18补充。以下IL01—IL06是IA01／IA05的**待审阅细化**，与[逐操作主体矩阵](contracts/df01-source/AUTHORIZATION.md)共同审阅；没有新增已批准权限。路径、DTO和状态均为下一版候选，尚未生成对应OpenAPI／Schema，不计入现有71操作。服务订阅、面板委托继续由C05／C09归并，不能由本节的凭据发放代替。

**已知项目事实。** F04规定指定Controller签发身份，其他服务显式配对并自行授权；当前RunGrant绑定issuer三元组和principal，没有credential_id，而AuthorizationBinding及ExecutionGuard绑定credential_id。现有issueToken只是人员会话换定向token，不能据路径名称把它当组织服务登记。（依据：[F04第2节](rebirth-f04-f05-design.md#2-f04-身份登录与信任)、[当前模型](contracts/df01-source/source/public.schema.json)、[HTTP骨架](contracts/df01-source/source/http/controller.operations.json)。）

**设计分析。** 分开四种记录：主体的持续身份、组织批准、可轮换凭据、单次请求资格。轮换可保留仍有效的组织批准，但不得迁移旧context、permit或未决命令；只有轮换导致的资格变化与明确撤销、暂停、恢复分开，才能避免把正常轮换变成自动重新布防。

### 9.1 IL01：共同字段、权威及错误

本节候选引用`IdentityObjectRef={authority_service_id,database_instance_id,kind,id,revision}`；revision按DF04的规范U20字符串精确CAS。主体另含`issuer_id,issuer_epoch,principal_id`，本地映射到subject_id，显示名不参与身份匹配。请求携带expected_revision；创建使用调用者原有RequestContext／幂等键，没有历史revision时不虚构0号对象。所有管理写均由当前human、auth.manage、精确对象范围和近期认证共同授权。近期认证只证明本次管理意愿，不使管理员成为新service的运行主体。

只读`GET /api/v1/principal`在两服务提供`PrincipalView`：`subject_ref,principal_kind,issuer_id,issuer_epoch,principal_id,audience,session_ref|null,credential_ref,authorization_ref,effective_permissions,scope_digest,auth_valid_until`。human必须有session；service必须为null。服务端从当前权威上下文投影，不接收body自报角色；只返回自身，敏感配置和原始凭据无字段。旧getSession继续仅human。scope_digest不取代对象级检查，view也不能回传作为授权快照。

指定签发Controller拥有ServicePrincipal／ServiceApproval／opaque Credential／AccessToken；接收方持本地subject、配对及本地批准交集，不能修改远端权威记录。这里“组织”沿用F04的独立服务授权语义，不新增未设计的多租户组织管理产品。`ServiceApproval`包含`approval_id,revision,subject_ref,audiences[],permissions[],object_scope,validity,state,approved_by_ref,approval_operation_id`；增权创建新revision并重新批准，减权先进入F04撤销传播，旧revision不能因高版本重新active。已有RunGrant不会因批准更新自动扩大。

ServicePrincipal状态为disabled／active／revoked；初次批准可disabled→active，revoked永久拒绝，不靠修改display_name复活。批准revision是不可变范围快照，生命周期为pending／active／superseded／revoked／expired；修改写新revision，不覆盖旧BODY。纯增权经管理员批准形成新active，但仍不扩旧grant；含减权或混合变更先阻止受影响旧范围，并可靠登记撤销floor和固定目标，完成相关确认后新revision才active，期间不签发使用新范围的token。变更失败保留保护及原操作，不回退成旧范围全开。

已有token中的approval_ref保留签发来源，不能据superseded快照单独授权。每次重新取权威快照时取原token范围与当前active批准及本地批准的交集，并核对撤销floor；没有当前有效批准则拒绝。纯增权不使旧token变宽；减权待确认期间，受影响范围继续关闭，不用旧approval_ref跨越传播屏障。

错误映射：401无有效凭据；403有身份但缺用途；404未知或不可见对象；409状态／幂等异内容冲突；412预期revision不符；413超预算；422结构或具名约束不符；429容量拒绝；503权威、认证时间或关键存储不可证明。所有响应no-store，秘密响应及错误正文禁止回显请求。以下202只代表可靠受理，200／201也不表示远端已撤销、配对双方已可用或设备ready。

### 9.2 IL02：普通注销及响应丢失

`DELETE /auth/sessions/current`仅在签发方提供，使用Cookie＋会话CSRF＋精确Origin，无body目标选择器，不需auth.manage或近期认证；只能撤销认证得出的当前session。原子受理生成唯一`(issuer_epoch,session_id,logout)`操作，写session不可用、session撤销floor、固定目标集、RevocationRecord及通知outbox。刷新／issueToken／注销受理在同一身份writer排序：刷新先提交的后代凭据仍属于同session；注销先提交则刷新拒绝。刷新轮换不得创建一条脱离原session的授权链。

目标集取本session已签发audience与仍有执行／订阅关联的服务并集，包含签发方；离线目标不删除。签发／登记audience与注销捕获目标集同writer排序，不能在捕获后再凭旧session增加新目标。`202`返回`{operation_ref,local_session_state:"revoked",propagation:RevocationRecord}`并清Cookie；零待确认目标也须沿实际receipt判定applied。事务结果未知返回503而不是伪造202；本地立即禁用本session新工作并保留保护状态，按原操作身份核对提交结果。

注销会撤销该session的access token、context、票据及委托资格，目标按F04精确AUTH_FENCE处理未发送和在途命令。它不撤独立ServiceApproval／RunGrant，不自动释放manual holder，不清除unknown或恢复自动化；新登录同人仍需当前holder与ready等原有检查。停止操作者资格与移交设备控制是两个动作。

请求在注销前通过认证而重复到达时，唯一键返回同操作；注销后旧Cookie不再能访问普通API。首响应丢失后的旧Cookie重试可返回401并清Cookie，不开设“已撤凭据继续鉴权”的通道。GUI显示“本地已退出，远端撤销状态未确认”，不得将401或清Cookie解释为applied。重新登录的有权用户／管理员可经现有撤销查询核对原操作；原操作无权限则不泄漏其详情。过期／无Cookie只能清本地状态，不能猜session并代撤他人。

### 9.3 IL03：服务身份、一次交付与定向令牌

服务不通过普通登录密码或虚构人员session取得资格。首期候选保留F04不透明凭据路线：签发方用密码库生成32字节随机秘密、以无填充base64url首次交付；只存不可逆验证值及算法版本，验证值不进入公开DTO。具体库与保存密钥／验证profile沿技术锁定审阅，不将本节格式推荐冒充已完成密码实现验证。凭据原文只经受保护管理响应交给受权部署者，消费服务放入Suite秘密存储，普通模块和GUI持久存储不持有它。

| 候选入口（签发Controller） | 输入与结果 |
| --- | --- |
| `POST /api/v1/auth/service-principals` | 管理context、display_name、purpose；201返回ServicePrincipal，初态disabled，无默认权限或credential |
| `GET /api/v1/auth/service-principals/{id}` | 当前管理读取范围；200返回脱敏主体与批准／凭据引用，不返回secret／verifier |
| `PUT /api/v1/auth/service-principals/{id}/approval` | expected_revision、明确audiences／permissions／object_scope／validity；202返回批准变更操作。新主体的首次有效批准可启用主体，减少范围须逐目标传播后才宣告完成 |
| `POST /api/v1/auth/service-principals/{id}/credentials` | context、主体／批准expected_revision、expires_at、replaces_credential_ref或null；201仅首次返回`credential_ref,secret,stage_deadline`，持久状态staged |
| `POST /auth/service-credential-proofs` | credential_id、secret、proof_request_id；只允许staged凭据证明持有，成功可靠记录proven并返回非秘密proof_ref；不能顺便签token或调用业务API |
| `POST /api/v1/auth/service-credentials/{id}/activation` | 管理context、expected_revision、proof_ref、approval_ref、重叠截止（首次为null）；202返回CredentialActivationOperation，不以proven自动active |
| `POST /auth/service-access-tokens` | active／retiring的credential_id及secret、单audience、requested_permissions／scope、request_id；200首次交付短期opaque token及非秘密binding_ref，无refresh_token |

上述两个`/auth/service-*`证明／换token入口以凭据证明自身，不要求先有access token，也不兼容旧人员Cookie签发入口；无浏览器CORS放行，仍有入口级和credential级预算。不使用body自报principal_id／service_kind决定身份；Seamer角色还需配对中登记的服务身份及本地用途批准，任意服务不能申请一个叫seamer的名字获得设备写权。

`ServiceCredentialView`固定`credential_ref,subject_ref,kind="opaque_service",approval_ref,state,created_at,not_before,expires_at,stage_deadline,proof_ref|null,replaces_ref|null,retire_at|null,activation_operation_ref|null`。允许状态`staged→proven→active→retiring→revoked/expired`；staged/proven可过期或撤销，active也可直接撤销，所有终态不可返回活跃。activation采用当前批准交集，不照搬staging时的旧权限。首期每主体至多一个未完成轮换、最多两个尚可换token的凭据；第三个须先完成前次退役，防止靠连续轮换叠加过渡窗口。

证明不延长stage_deadline，激活时同时核对原stage截止、proof绑定及credential有效期；已过期proven不能激活。重复proof只返回原非秘密记录，不能换proof_request_id刷新证明年龄。受理、证明和激活的管理权限及当前批准均从权威表取，不信任客户端写入state或proof_ref所声称的结果。

首次交付的秘密不保存在幂等响应、audit或outbox。credential创建提交成功但响应丢失：同request identity返回200非秘密创建结果和`secret_delivery="unavailable"`，不再生成／重发秘密；受权管理员撤销该staged凭据，再以新请求创建。只有赢得首次创建事务的处理器可交付它生成的原文，重复处理器丢弃自身临时值。因为staged不能签token，未知交付不会留下无人掌握却已active的权限。数据库提交结果不明时按原identity核对，禁止生成第二个credential；临时原文尽快释放，不声称运行时内存必定归零。

token换取取credential、主体、批准、目标本地授权及所请求范围的交集；audience不在批准内直接拒绝，其他请求范围不完整可授权时整项拒绝，不静默授予另一个范围。`AccessTokenBinding`保存`token_id,credential_ref,subject_ref,approval_ref,audience,permissions,scope_ref,issued_at,expires_at,request_id,state`；授权评估同时检查token与父credential，撤credential不能只禁下一次换token。TTL取profile上限、credential／批准／认证期限最小值；后续回包不续TTL。

换token以`(credential_id,request_id)`唯一且绑定请求摘要；响应丢失后同ID只返回非秘密结果，不重发token。调用者可用新request_id取新token，但旧token保持原有限截止、同父撤销链，并计入每credential活跃token上限；不能利用响应丢失无限签发。proof响应丢失可重取同proof_ref，证明接口只返回最小状态，不因正确secret扩大成管理会话。

### 9.4 IL04：轮换、撤销与运行授权连续性

正常轮换：旧credential active→新credential staged→消费服务证明新secret→管理员批准activation→同事务新active、旧retiring、固定retire_at及操作记录。activation须确认新旧同一subject／issuer_epoch、旧尚可轮换、当前批准仍覆盖新请求；proof与credential revision精确绑定。重复activation返回原操作，不能重新计算重叠期限。默认建议部署profile给有限重叠；精确生产时长待平台／运维profile审阅，实验值不直接上线。

retiring只允许在原范围及固定retire_at之前换取token；token截止不晚于retire_at。认证区间上界到截止即拒绝，时间失信也拒绝，不能等待后台计时任务才停权。到期／显式撤销写永久拒绝floor并创建F04传播操作。旧token、context、permit始终绑定旧credential，不能改字段迁到新凭据；在途操作依原证据结案，不能把撤销改写成not_sent。

新credential可为同一仍有效组织批准和未撤销RunGrant建立**新**context／快照／permit；因为RunGrant绑定主体而非credential，这不自动修改grant_id、revision、arm_generation、validity或设备范围。若运行已因失信、保护或失败暂停，则仍需既有恢复流程；不得因新token可用而自动resume。配对、来源、模块批准及本地自动模式仍需成立。此连续性只允许健康运行正常换凭据，不给任何旧命令重试或重新布防授权。

撤销继续统一走`POST /api/v1/auth/revocations`：credential只撤该链，principal覆盖该主体全部凭据／授权，trust覆盖配对相关用途，grant只撤该grant。批准减权必须将关联grant缩小或撤销并阻断旧快照，不能仅让下一次token变窄。目标集按权威发放／配对登记和未决关联固定；两端断线保留applying／indeterminate，完整receipt之前不显示applied。秘密疑似泄漏可立即撤旧，不强求“先激活新凭据”而延误保护。

### 9.5 IL05：配对引导、双向证明和证书轮换

初次没有配对时，不能要求先拥有active binding才能完成引导，也不能把pending当一般内部权限。推荐部署者经两端可信管理入口，分别导入相同`pair_attempt_id`及双方service／issuer身份、两端固定endpoint引用、信任包摘要、证书DER／SPKI指纹、拟批准用途／范围和有限期限。材料从部署者已认证渠道核对，禁止首次连接自动接受指纹。缺初始信任时保持未配对；普通远端请求不能写入CA或动态指定回调URL。

`PairingAttempt`包含`attempt_ref,pair_attempt_id,local_service_ref,peer_service_ref,local_binding_id,peer_binding_id,local_credential_ref,peer_certificate_ref,local_trust_bundle_digest,peer_trust_bundle_digest,endpoint_config_refs,local_scope,peer_scope,transcript_digest,validity,runtime_domain_ref,proof_refs[],approval_ref|null,state`。引用及身份由stage验证，证书指纹必须与真实TLS字节相符。transcript的具名投影按service_id排序双方完整身份／证书／scope／binding／endpoint配置摘要／有效窗口，包含schema_version和pair_attempt_id，排除本地可变revision、proof、approval及state；不能直接对整个对象删若干常见字段。任一固定字段变化须新attempt，禁止复用旧proof。

| 候选入口（各服务本地权威） | 认证与语义 |
| --- | --- |
| `POST /api/v1/auth/peer-pairings` | human管理＋近期认证；建立staged attempt和pending binding，返回脱敏引用及transcript预览 |
| `POST /internal/pairings/{binding_id}/challenges` | 专用pending-proof档案，精确预登记TLS证书＋CA／SAN检查；输入pair_attempt_id／transcript_digest；返回challenge_id、challenge及本地固定期限 |
| `POST /internal/pairings/{binding_id}/proofs` | 同一精确证书及attempt；提交challenge_id、challenge、transcript_digest；事务消费后返回非秘密proof_ref |
| `GET /internal/pairings/{binding_id}/status` | 精确pending或active对端；仅该attempt的state、transcript_digest、proof及binding引用，无设备／token／来源数据；用于双向证明和激活确认，不需预先普通内部权限 |
| `POST /api/v1/auth/peer-pairings/{id}/activation` | human管理＋近期认证；expected_revision、固定transcript及两向验证记录；只提交本端binding active和批准引用 |

pending-proof是专用服务端认证用途，不能由HTTP头选择；无条件签发CA、普通时钟查询、introspect、事件摄取均不对pending放行。双向各执行一轮challenge/proof，challenge使用32字节随机值；只保存验证值，返回丢失可创建新challenge，但同attempt每方向最多一个未消费值，新建必须原子失效旧值且不延长attempt截止。proof是本地认证通道的验证记录，不是可在别处离线信任的签名票据；两向记录由服务实际发起的受信连接和本地消费记录形成，用户粘贴proof_id不能替代。

本地attempt状态`staged→proving→proved→activated`，非终态可进入expired/rejected；activation结果引用独立binding。binding保持`pending→active→revoked/expired`，撤销不可回到pending。双方分别可靠提交，无跨服务事务；A active而B pending时，只能继续专用配对状态查询，普通业务必须等待双方当前active证据及用途交集。查询双方状态的控制通道不依赖普通业务权限，避免激活死锁；缓存使用F04有界新鲜度，不能宣称零窗口远端撤销。

attempt截止取两端批准窗口交集；每端按自己的认证区间保守验证，并绑定本地运行域内单调截止，不比较跨机tick。任一端重启使本端未完成attempt及challenge失效，重新stage新attempt；已active绑定可以保留配置身份，但新域须重新核对当前对端状态，不能恢复旧快照／permit。凭据／CA／scope改变使旧未完成attempt无效。active配对证书轮换使用新attempt绑定`replaces_credential_ref`和原scope，双向新证书证明及两端批准分别完成，旧证书只在固定重叠内有效；新增CA或scope仍单独管理批准。不会因为SPKI相同自动登记新DER。

对端先撤销或本端activation提交不明：不基于网络重试创建新binding，不把对端active响应当本端提交证明，按原操作查询。最终无法完成时只关闭候选attempt／未投入使用的新credential，不自动撤掉仍合法的旧配对，也不延长旧期限。明确安全撤销优先，不因轮换未完成推迟拒绝floor。

### 9.6 IL06：故障轨迹、预算及冻结出口

实验profile候选`sim-identity-lifecycle-v1`：近期认证最长5分钟；staged credential／pairing attempt最长10分钟；challenge最长60秒；opaque token最长60秒；轮换重叠最长5分钟；每credential最多8个未过期token；每服务最多16个pending配对；每身份管理请求64KiB、响应256KiB，范围集合沿具名能力预算。验证失败每身份每分钟5次、入口全局每分钟60次，超过预算429；未认证ID不得产生无限独立桶。撤销及核对使用独立保护额度，不因普通登录失败额度耗尽而被阻塞。均为有限故障夹具值，实际发布需两平台负载、认证时间及运维流程验证；未批准profile不得取这些值作为生产默认。

正常服务接入：管理员建disabled主体→明确批准→创建staged凭据→消费服务prove→管理员activate→定向换token→接收方核对当前权威和本地交集→按原用途工作。正常配对：两端stage相同transcript→双向证书验证及一次proof→两端分别批准／提交→当前双方状态确认→才开放批准用途。没有任何一步隐含设备ready、布防或动作派发。

| 新验收ID（均待运行） | 正反轨迹与通过判据 |
| --- | --- |
| ILT01 | 普通human无auth.manage仍能注销自身；body指定另一session、错Origin／CSRF拒绝 |
| ILT02 | 刷新先于／后于注销两种排序；先发后代归原session，后发拒绝，无遗漏audience |
| ILT03 | 注销提交成功响应丢失／提交未知；旧Cookie不恢复一般权限，GUI不伪报全局applied |
| ILT04 | 一目标离线；固定目标不删除，独立组织run不混撤，holder不自动释放 |
| ILT05 | service PrincipalView的session必须null；伪造human或Seamer显示名不提升用途 |
| ILT06 | staged秘密首次丢失；同幂等键无新秘密／新credential，撤销后新请求才能重建 |
| ILT07 | secret证明正确但未批准、批准已撤或audience错；不发可用token，proof不当管理权 |
| ILT08 | token首响应丢失、同ID异范围、反复新ID；只一次签发原身份，达到活跃预算拒绝 |
| ILT09 | 轮换提交成功／失败／结果未知；新旧状态同事务，重试不移动retire_at或产生第三活跃链 |
| ILT10 | 旧credential撤销后已有token／context／permit；逐目标屏障拒旧，已发效果仍按原证据结案 |
| ILT11 | 新credential取得仍有效grant；只能新context／permit，原期限及arm不变；paused run不自动恢复 |
| ILT12 | 待配对证书正确但访问introspect／clock／events；拒绝，pending-proof仅限具名引导接口 |
| ILT13 | 同attempt改scope／CA／端点／证书、重算digest；旧proof无效，不能跳过管理员预登记 |
| ILT14 | 双向challenge重复／错证书／交叉方向／重启／截止等号；一次消费或拒绝，无二次激活 |
| ILT15 | A提交active而B失败或撤销；状态查询可核对但普通业务不可用，不伪造分布式原子成功 |
| ILT16 | 同SPKI新DER、双端轮换不同步、旧证书已撤；新证书需新批准，旧永久拒绝不因revision复活 |
| ILT17 | 认证时间失信／回跳及库恢复；期限不续，旧epoch／域与拒绝floor不能回退 |
| ILT18 | 普通配对／登录洪泛和大scope；有限预算拒绝，撤销／屏障独立额度可用，日志无秘密 |

以上扩充IN07／IN21／IN31、FA及ST相关验收，不替代原用例；本轮只进行文档与跨项契约审阅，真实身份／TLS／数据库并发／设备执行数为零。下一版机器归并须包含本节DTO、状态、认证档案、具名transcript投影、错误集合与[DF04第10节](rebirth-df04-storage-design.md#10-身份生命周期事务补充)；生产验证器不得只检查枚举而遗漏权威及事务来源。剩余证书发行／寿命与秘密存储profile、服务订阅、面板委托和完整生成源仍按各专题冻结；本轮不宣告C07或全系统关闭。
