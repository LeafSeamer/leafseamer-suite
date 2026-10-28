# DF06：内部身份、对象授权、来源证明与查询保护

日期：2026-10-17。细化已确认的TS02、F04/F05和draft.4；IA01—IA06是待审阅推荐，不代表用户已批准新取舍。继续先完成全系统设计，不修改业务实现，不签发证书、开启监听或控制设备。

首期主体政策及身份权威归属以第11节为准：其中人员手动、服务自动化的收紧方案已确定采用。该决定不等于批准全部历史候选，不改变已有机器资料的版本或运行验收标志。

首期密码、秘密存储、内部证书及身份期限的实施选择以第12节为准，运行认证时间的采集与恢复以第13节为准；历史“具体profile待定”不再重新悬置其中已经选定的参数。真实平台与密码实现验收仍未完成。

依据：[身份与容量](rebirth-f04-f05-design.md)、[TS02](rebirth-technology-selection.md)、[draft.4归并](rebirth-draft4-review.md)、[DF02运行域](rebirth-df02-runtime-design.md)、[DF03授时证据](rebirth-df03-time-profile-design.md)、[DF04存储](rebirth-df04-storage-design.md)。候选附属模型版本`internal-trust/0.1.0-draft.1`，不修改公共draft.4／IPC 0.3。

## 1. 事实、缺口与推荐

2026-10-26补充：设备开闸的稳定授权状态、短期取证及续约边界以本稿第10节为候选归并依据。它不新增公共gate.open权限，不改变IA01—IA06的信任来源要求，也不将结构验证升级为认证成功。

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

2026-10-29归并说明：下文的设备专属SourceBindingRef及旧EventEnvelope投影是历史输入；下一完整选择采用[C05第17节](rebirth-c05-event-sync-design.md#17-设备与数据源身份分支定稿)的target判别分支和完整Origin摘要。设备来源归Controller，数据源观察归Seamer受监督核心，两者均核当前注册／批准、provider启动身份与首次接收年龄；不能给数据源伪造设备或重算历史事件。

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

因果年龄按[DF03第20节](rebirth-df03-time-profile-design.md#20-事件年龄与排期时间的同版采用)采用验证器域有效平台资格的经过量上界e_plus，年龄上界为`ceil(e_plus(now_tick - sent_tick)/1_000_000)`，下界0；sent≤received≤now且所有tick仅在验证器同域比较。e_plus包含观测delta相对速率与跨度量化，不能直接把tick差当真实经过量，也不要求先取得业务UTC才能使用已合格单调域。沿用年龄阈值语义：上界≤max_age允许，challenge期限本身仍严格小于expires。排队、查询、传输及验证后的等待全部计入，不以received−sent冻结上界。sampled结果仅用于声明允许采样的状态，不生成离散边沿或证明缺口不存在。

来源发布该观测时，事件与回执先入同一持久序列／outbox，HTTP和订阅流使用同event_id／sequence／origin_digest；两路到达按同一inbox去重，不形成两次触发。响应领先订阅流不允许静默跨越缺失sequence，完整C05规则另行归并。UTC证明采用DF03第20节双方reference-bound/1区间与固定首次接收锚点；C05第19节的SourceTimeEvidence进入新Origin摘要，AgeEvidence仍由接收方产生。旧ClockSample／UtcAgeBasis只用于旧版本历史，未证明时间可展示但不能冒充新鲜触发。本地Seamer数据源使用核验后的local_capture，不伪造对自己的mTLS或challenge。两种事件时间原件读取采用C05具名内部GET与events.internal.read用途，当前配对、来源范围和释放前撤权缺一不可。

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

## 10. 设备授权语义状态、短期取证与恢复

本节是IA02／IA05与F04的具体候选，approved=false。已知代码事实：[OPEN取证需求](contracts/c04-lifecycle/OPEN_AUTHORIZATION.md)区分评估器、持有人和限定取消；[撤销来源](contracts/c04-lifecycle/REVOCATION_SOURCE.md)能从命令授权原件重建拒绝全集，但不能作为设备开闸凭证。原Requirement尚未区分稳定授权状态和短期响应更新。本节的分析结论是：两者必须分别版本化，否则正常认证刷新可能推进authorization_revision并反复触发设备保护。

### 10.1 一个设备状态，多个不可变取证结果

[唯一局部定义](contracts/c04-lifecycle/build_device_authorization.py)生成[机器Schema](contracts/c04-lifecycle/device-authorization.schema.json)，其State与Evidence并入现有Requirement体系，不再另建公共HTTP或第二身份权威。如下是冻结建议，尚未替换批准基线。

| 对象／字段 | 定义与引用 |
| --- | --- |
| State.state_id／revision | ID按scope＋device的摘要加修订后缀确定，每修订独立ID；revision从1开始、每次语义变化严格加1，完整Ref仍含摘要；parent_ref指同设备前一修订原件 |
| State.context | 完整scope/device、当前control_authority_ref与epoch/version、mode/holder、ordinary或cancel_only用途；不引用会随闸相位更新的control_state_ref |
| evaluator_lineage／evaluator_policy_ref／device_scope_ref | 当前服务主体三元组、credential、主体及策略修订、范围摘要与完整内部策略／设备范围原件；不是某个run的grant，也不是模块自报能力 |
| holder_lineage | 仅ordinary/manual存在：当前holder三元组、session／credential、主体／会话／策略修订及设备范围摘要；automatic及cancel_only为null |
| cancel_scope_ref／cancel_lineage_ref | 仅cancel_only存在：固定ProtectionScope及完整独立取消授权链的语义引用；其中主体、代行、原操作和范围不得随刷新替换 |
| State.status／reasons | protected或policy_selected；后者仅表示已选定策略上下文，既不是Ready也不授设备许可；protected必须有稳定原因码，允许缺失的来源字段为null |
| State.recovery_ref | 固定引用RecoveryAuthorization：已可靠受理、仍有效的恢复授权，绑定原protected状态和控制权；不是本次恢复完成证据，不以新token代替恢复，不自动复活运行 |
| Evidence | 新ID、revision=1、state_ref、完整Requirement、context_digest及各来源的半开Window；context_digest由受信原件合并器按完整State.context重建 |
| Window | role、完整evidence_ref、not_before_tick_ns／before_tick_ns；角色全集必须恰好为evaluator加适用holder或cancel，不允许空缺、重复或多余角色 |

CredentialLineage不包含挑战ID、响应ID、接收时刻或freshness。正常刷新这些短期事实时，State.context与revision不变；新Evidence及Requirement另用新ID。凭据轮换、会话更换、主体／策略修订、设备范围、控制权或取消语义变化均不属于普通刷新。状态摘要只排除自身顶层摘要，证据同理；嵌套引用保留。

authorization_revision映射State.revision。资源快照的authorization_ref使用每修订独立的State.state_id，解析完整原件后再核持久当前指针；Plan.state_refs.authorization、EligibilityRefs.authorization和GateAccess.authorization_ref均为完整State Ref。Requirement.authorization_state_ref同样引用State；Evidence只引用已存在State与Requirement，State不反向引用Evidence。仅裸ID相等不得作为授权，首次恢复封存仍须固化完整来源及修订。

RecoveryAuthorization已进入同一Schema：authorization_id、revision=1、operation_id、原RequestKey对应的request_receipt_ref、完整binding、原protected_state_ref、control_authority_ref、requester三元组及kind、固定用途revalidate_device_authorization、proposed_context_digest、按完整Ref排序的evidence_refs（1—16）、issued／expires单调窗口及authorization_digest。scope/device从binding取得，不另复制冲突字段。proposed_context_digest绑定本次待选Context，不能借同一请求换设备范围、用途或凭据；它不包含尚未产生的State。一次消费状态由持久采用记录表达，不在不可变授权正文里改写。

其语义只允许本次重新取证与尝试恢复；State采用与消费同事务，旧状态、控制权、完整Binding或窗口不匹配则拒绝。证据集合的1—16是本候选有界接受范围，容纳三个角色、控制权、运行身份及其关联顶层来源；完整撤销全集等嵌套证明以具名原件Ref引用，不展开为任意多顶层项。超出拒绝且不可截断，这不是性能承诺。它不得引用即将创建的State、ResourceSnapshot或RecoveryCloseChoice。依赖顺序为“原protected状态→恢复授权→新policy_selected状态→资源恢复快照／完成→GateAccess／OPEN／ACK／Ready”；完整关闭覆盖仍在后续恢复和OPEN采用时核验，选定策略本身不解除物理保护。这样同时避免摘要循环与事务先后循环。

### 10.2 三类来源的固定解析职责

所有来源读取都由受信Controller内部服务完成，不接受API调用方自填lineage、context_digest、窗口或verified。实际提供者必须输出其完整原件与确定性投影，并在writer采用时重读当前状态。

| 来源 | 必须解析的完整原件 | 语义投影与短期窗口 |
| --- | --- | --- |
| 内部评估器 | 当前受监督runtime／配对或本机保护配置、当前credential／策略／设备范围、实际挑战响应、认证时钟有效期和撤销全集 | service lineage、策略／范围Ref进入State；runtime与原响应Ref留Evidence；上界取freshness、凭据／配对／策略有效期及本地窗口最小值 |
| ordinary/manual持有人 | 精确当前控制权、holder身份、有效人员会话及credential、原挑战响应、设备动作范围与认证有效期、撤销全集 | human lineage进入State；响应刷新不能替换session／credential；不借control.acquire或T4历史证明当前可操作 |
| cancel_only | 固定ProtectionScope／Ownership／Assessment、原取消操作及授权／代行链、相应主体与扩展批准、认证有效期、撤销全集 | 固定取消语义Ref进入State；授权撤销可允许独立安全取消，但不得借旧持有人或普通device.command降级；既有取消规则仍全部适用 |

automatic无需借某个人员或单个run授权开放设备；每个自动动作仍独立核grant、arm和命令范围。三个来源可复用同一撤销事件账本和排序算法，但必须使用各自真实绑定适配器；当前命令AuthorizationUse适配器不是上述任一来源的默认替代。多来源撤销集合按完整来源身份分别取证后归并，不能只核评估器而遗漏holder、代行者或扩展。

### 10.3 刷新、失效与状态转换

| 当前状态／事件 | 必须转换与行为 |
| --- | --- |
| 首次启动 | 建立revision=1的protected状态；缺来源可显式为null，不默认policy_selected |
| protected，恢复授权已可靠受理且当前来源成立 | 消费恢复授权并追加下一修订policy_selected；随后完成资源恢复及OPEN，不能直接Ready |
| policy_selected，语义及来源谱系未变，旧证据仍有效 | 可选新Evidence而保持State修订；正常认证刷新本身不触发AUTH_FENCE或强制重新接管 |
| 新证据到达时旧证据已到期或认证时间失信 | 不接受为续约，即使新证据本身有效；先protected并完成恢复。expiry等号拒绝，不补计失效期间的可用性 |
| 权限、scope、credential、session、控制权或取消范围变化 | 先追加protected后继与保护写集，再按新来源恢复；不能policy_selected直接切换为另一语义上下文 |
| 提供者／worker／Controller／会话／时钟域改变 | 旧Evidence绑定失效，不能按普通刷新复用；监督退役及原在途核销仍按既有协议 |
| 同一状态或证据请求重投 | 相同完整内容查原；同ID异内容拒绝。仅重查当前状态不消费新修订 |
| 修订耗尽、关键写失败或COMMIT不确定 | 本地停止派发、保护并查原；不能回绕、回退修订或依靠内存新Evidence继续。需写后继但无法提交时由既有紧急关闭路径处理 |

刷新必须在同一域的now同时验证旧证据仍有效、新证据已有效且selected不在未来，并保持完整Binding、评估器runtime和State Ref。新Requirement期限不能超过全部来源上界、资源快照与闸租期的最早终点。窗口可以缩短，不能通过新的received时刻延长原challenge freshness。业务NTP不替代认证时钟。

新Evidence不直接延长已安装worker租期。继续使用既有闸续约／ACK采用协议；旧租期仍有效期间可准备新证据，只有可靠采用后才切换当前取证选择。选择指针已换后，迟到旧ACK只能存历史。新证据失败而旧证据仍当前有效时可维持原截止，但不能续长；旧证据到期立即阻断。持有人不因刷新失败自动释放。

### 10.4 同库映射及防绕过边界

局部物理映射现见[九表原子采用候选](contracts/c04-lifecycle/DEVICE_AUTHORIZATION_STORAGE.md)。它落实下述State／消费／Evidence／head／回执和审计意图的外键与读回规则，采用完整当前选择CAS；protect只比较State，避免正常刷新抢先后挡住撤权。首次Evidence另核已消费恢复授权的完整Binding。该子域尚未连接真实来源、完整Controller库或实际保护IPC，不能据此声称以下全部实施要求已完成。

在Controller业务库统一实现device_authorization_state历史、每设备唯一head、不可变evidence及当前evidence选择。State历史主键为scope/device/revision，state_id另设唯一约束；head以预期旧修订CAS。State的recovery_ref、control_authority_ref、全部lineage与策略范围引用必须外键／类型映射到完整原件。Evidence表保存完整正文、state_ref和来源成员；当前选择只能指同设备、同State、已可靠封存的一条Evidence，不设置可由客户端清空的current选择参数。

保护事务必须同时追加State后继、移动head、作废当前Evidence及未派发OPEN资格，并按既有AUTH_FENCE／CLOSE_GATE语义登记审计和保护outbox；相关在途保持未决直到完整核销。策略重选同事务消费RecoveryAuthorization、追加State后继及审计／outbox；重复消费不能创建第二条状态链。后续资源恢复另引用这个已存在State，不反写其recovery_ref。短期刷新不增加State修订，但Evidence封存、来源全集、旧当前选择CAS及新选择必须同事务；新状态或撤销先提交时旧刷新失败。

最终writer必须从head读取旧选择。已有Evidence时只能走续约校验；只有新恢复状态尚未选择过Evidence时允许首次选择。不能通过传入previous=null或删除过期选择绕过“旧证据仍有效”的条件。纯模型的transition与单对象evidence均只是内部关联辅助；恢复应先走revalidate核完整RecoveryAuthorization和当前Binding，但它也不验证真实发行者或数据库一次消费。单独调用辅助函数即使通过，也不构成首次选择、续约、Ready或发送入口。

这些是本轮冻结的完整映射和线性化约束，物理DDL及受信提供者仍须按此实现并验证；不把尚未运行的存储、TLS、原生进程或设备验收前置为阶段0完成设计的证据要求，也不将设计成文称为实现完成。

### 10.5 关联验收与交付边界

[纯转换模型](contracts/c04-lifecycle/device_authorization_model.py)和[检查器](contracts/c04-lifecycle/check_device_authorization.py)覆盖四用途／模式组合、正常刷新不变修订、expiry等号、变化先保护、恢复消耗新修订、旧证据拒绝、窗口全集与错Ref、跨运行绑定及修订耗尽；[报告](contracts/c04-lifecycle/device-authorization-report.json)保留真实来源、SQLite采用、续约IPC及完整OPEN均未验证。特别保留孤立新证据在旧期限后仍可能通过单对象结构检查的反例，证明不能把内部辅助函数当作最终入口。

后续归入既有FA／ST／IN验收：正常连续刷新期间无额外AUTH_FENCE且State修订稳定；撤销与刷新竞争仅一个CAS胜出；语义变化保护写集逐写／漏写全回滚；不确定COMMIT按原选择查原；进程恢复不能将expired直接续约；cancel_only不能转ordinary；真实来源签发、完整同库映射与worker续约分别取证。新候选需与统一SDK／API／IPC归并审阅，C07及全系统尚未关闭。

## 11. 首期主体政策与身份权威定稿

### 11.1 采用范围与当前操作定位

**首期决定，2026-10-28。** 手动接管、转交、定义发布、布防和恢复仅允许人员；服务设备写必须经已配对Seamer、automation用途及有效RunGrant。服务不得自行发布定义、重新布防或执行恢复。后台来源事件仍可触发已经布防的运行，不要求每个自动动作再次由人员批准。该收紧替换旧Schema允许的service＋manual组合，不能声称旧版本已经拒绝该组合。

下表按[DF01第15节](rebirth-df01-sdk-freeze.md#15-首期采用输入与独立通道归属定稿)固定的SDK panel4输入定位。operationId须连同Controller／Seamer权威使用；HTTP的bearer声明、SDK函数可导入或结构校验通过均不证明主体符合政策。

| 权威／当前operationId | 首期主体与用途 | 接受后的领域边界 |
| --- | --- | --- |
| Controller：`acquireControl`、`releaseControl`、`offerTransfer`、`acceptTransfer`、`cancelTransfer` | 当前human；转交目标也是完整人员三元组；原持有人、目标、紧急权限及理由按控制契约分别核验 | T3保存受理／版本预留，T4证明生效，T5另建ready；退出不释放holder，拒绝service不得产生pending或预留版本 |
| Controller：`getControl`、`getControlOperation`、`getTransfer`、`lookupControlRequest` | 沿用控制契约的人员查询入口及当前对象读取权；lookup只查原，不是新受理 | 不从历史effective推导当前持有人，不因not_found允许换键重做 |
| Controller：`submitCommand` | human＋manual，或配对Seamer＋automation＋当前RunGrant；human面板委托仍取当前人员权限交集 | T1受理与T2派发前均核当前权限；manual还需当前holder，automation需批准版本、arm、本地自动模式及范围；两者均需ready、资源与逐次permit |
| Controller：`updateRunGrant` | 已配对Seamer提交既定运行批准，Controller取本地授权交集 | 登记不自授权限，不代表布防或设备ready；不得扩大原批准窗口／版本／动作范围 |
| Controller：`revokeRunGrant`、`cancelCommand` | 有目标权限的human，或既有规则允许的所属服务链；服务不能取消外来manual命令 | 限定取消与撤销保留独立用途、对象归属和在途核销；不因禁止service manual而禁用必要保护 |
| Seamer：`publishDefinition`、`armRun`、`resumeRun` | human；定义发布、布防及恢复分别核权限和当前前提；服务即使持有同名权限也拒绝 | 发布不布防；arm／恢复的远端准备、固定目标、一次消费及R2—R4顺序保持，不由人员请求直接跳到设备发送 |

服务只读、被授权的草稿编辑／未布防运行创建、所属运行暂停和独立服务订阅继续按各自现行契约处理；本决定没有新增这些操作的权限。`cancel_only`是独立安全取消链，不是service＋manual的兼容别名。GUI及面板不得持有服务凭据来代替人员确认。

### 11.2 身份权威与事务归属

以下是Q55—Q57、F04第2节及本稿第9—10节的实施归并，明确同名记录属于谁，不新增身份服务或跨库事务。（依据：[已确认身份与授权](rebirth-design.md)、[身份事务I1—I6](rebirth-df04-storage-design.md#10-身份生命周期事务补充)、[控制权契约](contracts/c08-controller/CONTROL_AUTHORITY.md)。）

| 记录／资格 | 唯一持久权威与写入边界 | 接收方能做什么 |
| --- | --- | --- |
| 人员／服务主体、会话、ServiceApproval、opaque Credential、AccessToken | 独立模式本地Controller；套件模式指定签发Controller。I1—I4串行处理批准、签发、注销与轮换 | 保存本地subject映射、明确远端引用及当前有界证据；不能改远端状态，也不能在签发方失联时转成本地签发 |
| 本地授权、trust_pairing及其proof／activation | 各服务自己的库；I5只激活本端记录，另一端单独提交 | 远端active只是有期限的观察；映射主体不等于批准，证书身份不等于设备动作权限 |
| 定义、运行、arm及组织运行批准 | Seamer运行域持有其版本和生命周期；指定签发方持有服务身份／ServiceApproval，不拥有Seamer的run状态 | Controller保存精确运行引用和本地RunGrant；签发方不能用更新ServiceApproval代替发布、布防或恢复 |
| Controller RunGrant、控制holder及设备授权State／Evidence | 每个目标Controller在自身库裁决；RunGrant来自配对Seamer的请求与本地交集，holder按T3／T4，State／Evidence按第10.4节 | Seamer保存逐目标receipt和运行关联；单目标成功不证明全部目标成功，远端记录不作同库外键 |
| RequestContext及每种操作的请求身份／receipt | 实际受理操作的服务；使用该操作已定义的RequestKey与版本 | issuer负责认证而非代替目标去重；不得套用DF04第3节历史context参与唯一键去改当前控制／命令身份 |
| 撤销operation、固定目标集及拒绝floor | 相应权威受理I1／I6；每个目标独立持久化本地floor、屏障和receipt | 目标只确认自己的范围；汇总者须原固定集合全部可靠确认才applied，不按在线节点缩减集合 |
| WS票据、订阅owner及面板委托 | 具体接收服务拥有单次票据／订阅及其当前授权；人员session仍归签发方，面板委托不产生新主体 | 人员与服务订阅走各自通道，service的session为null；不能伪造人员票据连接，也不能沿用旧矩阵取消独立服务WS |

**必须保持的并发次序。** 服务主体的认证与用途判定先于任何新请求的额度消费和领域受理；事务内再次核对本地当前修订／floor。签发与注销在签发方同writer排序，I4保存token与session_audience，I1捕获固定目标，不能先提交token再异步补audience。目标T1接收后若撤销先于T2，匹配许可不得派发；已经经过发送切点的动作保留在途或unknown，不伪报未发送。证据采集和远端确认发生在事务外，以有界原件参与本地提交；任何COMMIT未知均保留保护、按原身份查询，不生成新设备请求来补偿。

### 11.3 实施交接与关闭判据

本节关闭C07的service＋manual产品取舍、相关当前操作定位及身份子域的持久权威／事务归属。C01生成时须产生新选择身份，显式移除service＋manual接受分支并补齐第9节身份接口；不修改旧panel4制品的字节或批量翻转候选批准标志。DF04负责产品表、唯一键与writer实现，Controller／Seamer负责实际主体守卫，GUI保持人员动作确认；不新增同义参考包。

实现验收归入既有A01／A02／A09／A10及FA／ILT：有效service凭据调用五项控制写和三项发布／布防／恢复写均拒绝，且无请求受理／预算消费／版本预留；service＋manual命令拒绝；有效human仍须目标权限及控制条件；有效Seamer自动动作保持允许，未配对、错arm／grant／范围均拒绝；撤销与受理／发送、注销与签发两种顺序均覆盖；跨目标离线保持未确认。拒绝可以有受限安全审计，不能产生业务成功记录。结构、生成接受集和真实服务鉴权分别取证，不能用同一Schema检查替代三者。

本节核验仅为当前文件与路由映射检查，未执行上述运行验收。C07剩余设计项是证书／秘密及认证期限的精确发布profile、与C12一致的可信时间／恢复引导；IA中未涉及本节的实质取舍继续按整体清单核对。TLS、平台秘密存储、真实数据库和设备效果均在实现后验收，不能以这些尚未运行撤销本节已明确的设计结论。

## 12. 首期认证与秘密存储实施profile

### 12.1 采用边界与密码接口

本节固定`identity-runtime/1`的设计目标，属于常规技术实施选择；不把历史模拟profile改名当生产通过。服务启动必须同时选择精确profile修订及平台实现，发行验收不通过时不得静默降低成本、延长期限或回退明文。真实库版本、原生产物与平台报告进入既有工具链锁和发行清单，生成锁及执行检查属于实施任务，不再为同一选择新增参考包。

**官方事实。** Node crypto提供随机数、SHA-256、AES-GCM及固定时间比较；GCM解密必须验证认证标签，库可接受短标签，因此应用必须显式限制长度。Windows DPAPI的机器范围与用户范围不同；systemd凭据在服务激活时装载且运行期间不可变。下述具体参数、用途隔离和轮换次序为项目选择，并非这些工具自动保证。（来源：[Node crypto](https://nodejs.org/docs/latest-v24.x/api/crypto.html)、[Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)、[systemd Credentials](https://systemd.io/CREDENTIALS/)）

- 人员密码使用既选node-argon2的Argon2id：m=65536 KiB、t=3、p=1、随机盐16字节、输出32字节，保存PHC及profile修订。只接受登记的算法／成本组合，不直接执行数据库中任意高成本参数；密码计算并发2、等待队列8，超额返回429，独立于保护通道。平台负载不达标时调整资源或另版profile，不在运行中自动降成本。（算法依据：[OWASP密码存储建议](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)；本项目数值及队列为设计选择。）
- opaque服务凭据、访问令牌、刷新秘密、票据、初始化及配对挑战各用独立32字节CSPRNG输出；原始秘密规范无填充base64url，严格解码并回编码一致，拒绝等价的非规范尾位。查找ID与秘密分开，ID不是鉴权证明；对旧协议的格式差异由新SDK选择显式迁移，不修改旧制品接受集。
- 验证值固定为SHA-256：输入为UTF-8的`LeafSeamer/opaque-verifier/v1`、一个零字节、具名kind、一个零字节、原始32字节秘密。kind限定为`service_credential/access_token/session_refresh/ws_ticket/first_admin/pairing_challenge`，不可由请求任意选择；保存算法版本、kind、验证值及父绑定，比较固定32字节Buffer。仅适用于高熵随机秘密，人员密码不走这条路径。无明文重取、无可兑换的验证值公开接口，响应丢失沿I2／I4查原。

### 12.2 秘密存储与原子引用

各服务独立SecretStore。公开配置和业务库只保存`secret_ref={owner_service_id,secret_id,version,purpose}`；调用方不能把任意文件路径当secret_ref。master key每服务独立，发行签名key、部署CA私钥及人员密码验证值不得混入运行master key用途。

| 部署profile | 主密钥的确定装载方式 | 禁止回退与变更行为 |
| --- | --- | --- |
| Windows原生 | 专用服务账户使用用户范围DPAPI封装32字节master key，调用设置UI_FORBIDDEN且不设LOCAL_MACHINE；密文目录ACL仅该身份及受权安装管理者可访问 | DPAPI身份／机器不匹配即缺秘密，不改用机器范围；服务身份变更走受控重配，不能复制blob后假定可恢复 |
| Ubuntu原生 | systemd的LoadCredentialEncrypted装载该服务master key；私有源由安装管理者维护，服务从凭据目录读取 | 不把明文放unit的SetCredential或环境变量；新master key先加入下一启动配置，再维护重启并证明装载成功，不能靠运行中替换源文件热更新 |
| Linux容器 | 显式只读挂载单服务master key文件，固定服务UID/GID及最小可读权限；主机源目录不对其他普通账户开放 | 禁止映像层、Compose环境值和匿名默认密码；轮换通过受控重建装载新挂载，不把容器root视为不受宿主管理员影响 |

设备密码、数据源令牌及运行TLS私钥使用`node:crypto`的AES-256-GCM不可变信封：32字节key、12字节随机nonce、16字节tag；加解密均显式设置authTagLength=16。AAD采用现有JCS编码的`{profile_id,owner_service_id,secret_id,version,purpose,key_id}`，不包含秘密；密文保存在分离的服务秘密目录，secret_ref与信封头逐字段一致。任何标签、身份或用途不符均拒绝，final验证前的暂存明文不交给调用方。单秘密明文最多64 KiB，超限不得拆分成无界密钥材料。

每key的nonce登记在SecretStore自己的单writer账本，必须先可靠保留唯一(key_id,nonce)后加密；撞值重新采样，写入失败不得加密发布。已保留nonce永久消费，同key至多2^24个信封后禁止新写并要求轮换。信封写入不可变文件且完成平台耐久步骤后，业务writer才能原子引用新secret_ref并写操作receipt；文件就绪不代表业务引用已切换。明确未提交时保留旧引用；COMMIT未知时不得自行切回旧引用，按原操作查询真实持久选择，未引用密文不作为可加载秘密；清理前必须证明没有当前、历史恢复或未决操作引用。不同库和文件不宣称原子提交。

master key轮换：受权维护者预装新key→验证服务装载→用新key生成新信封→逐项CAS引用并登记进度→核对所有引用及所需备份覆盖→明确退役旧key。原运行资格不会因重加密自动恢复。普通秘密内容更新只新增信封和secret_ref，不要求为每个设备密码重启服务；需要重启的是平台master key装载或相关TLS上下文切换。nonce账本丢失、旧备份恢复或无法证明key使用历史时，禁止继续用旧key加密，先生成新key；旧key可在受控恢复中仅用于解密。

跨机恢复沿DEP06显式加密秘密包：在隔离状态验证包、取得授权解密材料，目标服务生成新的master key并重新封装，核对完整引用后才发布恢复集。DPAPI blob或systemd加密源的可复制性不代替该流程。缺秘密保留对应能力不可用，不伪造成功，不自动连接恢复出的设备；旧会话、票据、未完成挑战及旧许可不随秘密恢复复活。

### 12.3 内部证书与生命周期参数

内部mTLS采用独立部署CA，首期配置为ECDSA P-256／SHA-256、CA有效期最多5年、critical CA:TRUE、pathlen=0及keyCertSign/cRLSign，只签终端叶证书；叶证书最多90日，CA:FALSE、digitalSignature、精确DNS/IP SAN，按服务角色显式配置serverAuth/clientAuth。不共享跨服务私钥；叶证书更换即新credential，即使SPKI相同也须登记。证书签发由隔离的OpenSSL工具及经校验的固定配置完成，禁止复制未验证CSR扩展，CA私钥不进Controller／Seamer；精确签发工具制品纳入锁定，禁止使用任意PATH中的程序。X.509扩展和签发接口由OpenSSL实现，不自写证书编码。（来源：[OpenSSL req](https://docs.openssl.org/3.5/man1/openssl-req/)、[X.509扩展配置](https://docs.openssl.org/3.5/man5/x509v3_config/)；算法组合及寿命为项目选择。）

这套内部CA不替代浏览器HTTPS根、组织外部PKI或TUF发行root；便捷本机HTTPS仍按DEP03在部署者明确选择后安装到限定用户信任存储。服务只信固定部署CA及已配对指纹，TLS1.3、无0-RTT／会话恢复和逐请求授权沿第2节。链／SAN／用途／认证有效期全部通过才谈配对，不能因证书尚有效延长应用credential或批准期限。

| 参数 | identity-runtime/1上限或固定值 | 约束 |
| --- | --- | --- |
| 人员会话／刷新空闲／近期认证 | 8小时／30分钟／5分钟 | 刷新不改变会话绝对截止；普通注销不撤独立组织授权 |
| access token／WS票据 | 60秒／10秒 | 单audience；票据单次，响应丢失不重发秘密 |
| 首次管理员初始化／staged凭据／配对attempt | 10分钟／10分钟／10分钟 | 初始化还需本机部署者权限；proof不延长父截止 |
| 一次配对challenge | 60秒且不超过attempt截止 | F04第4.2节旧模拟“配对60秒”在此只指challenge，不把attempt偷偷压成同一对象 |
| opaque服务凭据 | 最多90日，提前30日告警 | 管理员给出有限expires_at；原批准或配对更早到期时取最早期限 |
| 新旧凭据或叶证书重叠 | 最多5分钟 | 激活时固定retire_at，重试或第二次证明不续期；失陷立即撤旧，不等待重叠结束 |
| 授权snapshot／刷新调度 | 2秒／500毫秒 | freshness从challenge发送算；调度是目标，不是SLA，晚到即拒绝且不延长旧permit |
| 活跃token／pending配对 | 每credential最多8个／每服务最多16个 | 与I4／I5同writer预留，超额拒绝；不靠GC事后修正计数 |
| 身份请求／响应 | 64 KiB／256 KiB | 仅身份接口；不覆盖各独立通道的大对象预算 |
| 登录／证明失败预算 | 每身份5次/分钟且入口全局60次/分钟 | 未认证身份桶有总界，满时统一入口节流；撤销及核对使用独立保护额度 |

组织批准与RunGrant仍必须具有明确有限窗口；本节不把会话8小时或credential90日当组织授权默认值，实际运行窗口由人员批准并受全部父边界约束。证书、秘密与身份期限选择已成文；运行认证时钟按第13节采集并接入FINAL_AUTHORIZATION，安装更新时间锚不能冒充服务运行时的持续认证采样。

### 12.4 实施与验收归属

Controller实现opaque／会话、SecretStore与证书装载，Seamer接入同一库契约但使用独立key和身份；Suite实现配置生成、签发辅助工具、安装权限及维护恢复。复用现有技术锁、I1—I6和DEP06／DEP07，不建立第二套公开身份API。每个实现必须有明确错误结果，密钥丢失、解密失败、轮换未完成或认证时间失信均不隐式产生新身份或设备资格。

既有TV07、ILT、IN及DPT14／恢复用例补足以下实施后证据：跨用途验证值拒绝；低位非规范base64url拒绝；GCM错tag／错AAD／短tag不输出明文；nonce保留失败、崩溃及恢复不复用；DPAPI换身份拒绝；systemd运行中更新源不视为已装载；只读容器挂载及权限；秘密文件就绪与业务引用COMMIT各失败点；旧key缺失／新key未装载保持保护；错SAN／用途／CA、到期及轮换重试不延长窗口。密码耗时与并发内存、TLS握手预算、文件耐久及两平台恢复各自取证；上述规格不是这些测试的通过记录。

## 13. 运行认证时钟采集与失信恢复

2026-10-29定稿。本节细化[F04的部署者信任系统时间](rebirth-f04-f05-design.md#25-浏览器与认证时钟故障)，不将业务reference-bound/1、业务NTS包或安装更新时间锚转换为认证来源。采用`trusted-system-interval/1`及[FINAL_AUTHORIZATION](contracts/c04-lifecycle/FINAL_AUTHORIZATION.md)已有区间、单调截止、故障锁存和关闭写集；正常运行不增加人工逐次校时步骤。系统时间的环境可信假设与API采集事实必须分别记录。

### 13.1 来源资格与平台接口

**已知接口事实。** Windows的GetSystemTimePreciseAsFileTime返回UTC格式的系统时间；分辨率不证明系统相对真实UTC的误差。Linux CLOCK_REALTIME会受设置和校时调整影响，CLOCK_BOOTTIME计入挂起。因而一次系统调用成功不能自报quality=trusted。（来源：[Microsoft API](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemtimepreciseasfiletime)、[Microsoft计时精度说明](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)、[Linux man-pages](https://www.man7.org/linux/man-pages/man2/clock_gettime.2.html)。）

**项目采用。** Controller与Seamer各自使用既定C／C++原生适配层在本机采集，不远程借用签发者的tick。Windows按`QueryInterruptTimePrecise → GetSystemTimePreciseAsFileTime → QueryInterruptTimePrecise`读取；FILETIME以整数减去1601至1970的116444736000000000个100ns单位，再乘100，拒绝负值／溢出。Linux按`clock_gettime(CLOCK_BOOTTIME) → clock_gettime(CLOCK_REALTIME) → clock_gettime(CLOCK_BOOTTIME)`读取；检查返回值及timespec的纳秒范围，再精确换算。禁止Date.now、字符串本地时区、浮点秒、COARSE或静默替换成另一计时API。

容器在同一已验证时间namespace内直接执行上述读取，并绑定C12宿主授时配置与DF02运行域证明；不能跨namespace拼接宿主tick和容器wall。缺少域证明只提供无授权资格的诊断，不能以同一机器名认定同域。应用不调用设置系统时间的接口，不启动或改配宿主授时服务。

`AuthenticationClockPolicy`由安装／维护入口固定，含id、revision、digest、service_id、runtime_profile_ref、native_artifact_ref、system_time_source_ref、environment_approval_ref、max_system_error_ns、wall_quantization_ns、monotonic_quantization_ns、drift_ppb、capture_limit_ns、sample_period_ns、sample_ttl_ns、health_profile_ref。完整Ref沿DF01；纳秒及身份计数用规范整数串，drift_ppb为0至1000000的整数。policy及环境批准由可信安装配置解析，不接受普通HTTP、模块或采集正文自报批准。

`max_system_error_ns=E`是部署者批准的宿主授时环境相对UTC的有限绝对误差假设，必须大于0；量化界与速率界分别有平台／制品证据引用。E不得从“已同步”状态、API分辨率、业务offset或近期平均误差自动生成。环境批准明确允许的OS／虚拟化、系统授时来源与配置、监测规则、失效条件、维护责任及证据；运行环境改变即失效。未建立该批准的安装不能开始认证业务，合成批准仅用于隔离验收。该模型对已批准环境给条件保证，不承诺检测恶意系统管理员、谎报时钟或全部硬件故障。

首期固定采样周期500ms、单次括号上限20ms、样本有效期2s；它们是调度与拒绝上限，不是实测SLA。E及两种量化／速率界按精确平台profile提供，缺项、超Schema范围或证据不匹配拒绝，不能填零占位。授时健康profile固定原生Windows W32Time或Linux宿主已安装的授时管理器及其受限只读状态映射；查询失败、服务／源配置变化、明确未同步、失去外部参考且没有批准的有限holdover条件均关闭资格。健康状态只验证批准环境仍成立，不单独证明E。

### 13.2 区间、持久来源与身份使用

设两次同域单调读数为a、b，中间系统UTC整数读数为w；`q_m`为每次单调读取的纳秒误差界，`q_w`为wall读取的量化界，`d`为速率包络ppb。要求b≥a、b−a≤20ms，且前后运行域／policy／健康配置未变。按第13.1节的UTC假设，w所对应瞬间的真实UTC在`[w−E−q_w,w+E+q_w]`；无须假定该瞬间位于括号中点。在数值锚点b处保守采用：

```text
Q = ceil(q_m * (1000000000 + d) / 1000000000)
Dplus = ceil((b - a + 2*q_m) * (1000000000 + d) / 1000000000)
L = w - E - q_w - 2*Q
U = w + E + q_w + Dplus + 2*Q
valid_before_tick_ns = b + 2000000000
```

计算使用足够宽整数，结果限制到现有无符号64位域，越界拒绝而不截断。Q把单调读数量化转换为UTC经过量上界，额外2Q同时覆盖锚点和后续当前tick的读取偏差；以后按已有整数模型从b向外外推，不能取中点后丢掉半径。提交和每次使用均重新检查当前tick严格早于valid_before；调度延迟不重置b或延长2s。固定毫秒UTC字段若需转换，起始下界向下、结束上界向上舍入，不通过浮点timestamp缩窄区间。

每次采集生成不可变`AuthenticationClockAcquisition`：id／revision／digest、service_id、service_boot_id、clock_domain_id、descriptor_digest、native_artifact_ref、policy_ref、environment_approval_ref、health_evidence_ref、a、b、原始wall整数和平台单位、换算后的w、E／q_w／q_m／d、L／U、valid_before_tick_ns。记录只从受监督本地入口进入writer；重复id只查原，不能换采样时间。配置前后检查、API失败、超时或非法数字作为失败进入既有故障入口，不构造一个“可信但空值”的样本。

采集原件与服务认证时钟当前指针在同库writer内提交；Controller按实际出口Binding生成已有AuthenticationClockSample，`acquisition_ref`必须解析到该原件，不能只比较字符串。样本的锚点、边界、期限、policy、制品／域必须与原件精确匹配；同次采集可以投影到同域多个真实出口，不能为不存在的出口补造身份。Seamer以自身service／boot／domain保存服务级认证日志，不伪造Controller设备Binding；公共认证类型和Controller出口投影在SDK中明确区分，均复用同一算法与失信规则。

每次登录、续期、签发、配对激活、内部授权响应及受权读取／写入均在本服务当前认证区间内核对有效期；登录、token或授权缓存不缓存“时钟永久可信”。现有授权使用仍取原始与当前区间、所有有效期及单调截止的交集，新采样不得延长旧permit。任何一次已确定过期的session／token／credential／grant按精确对象Ref持久记录拒绝事实或既有撤销状态，恢复较早wall或换运行域不得复活该对象；新会话、轮换凭据和新批准仍走各自现有流程。

内部TLS保留平台标准链、名称、用途及时间校验；另外在握手后、激活业务会话前，用最新认证区间验证实际验证链的有效期：L不早于各notBefore，U严格早于各notAfter。标准校验拒绝不得由区间检查覆盖；信任锚按本项目CA有效期策略处理。长连接每次释放授权响应或使用业务权限仍重新检查当前区间、配对和撤销，证书到期、时钟失信或凭据撤销不因已有socket继续授权。首期关闭业务TLS会话恢复／0-RTT，避免恢复握手绕过原验证链和当前生命周期检查；启用须另版明确等价证据。

### 13.3 失信、恢复与部署时间边界

前后配置／域不一致、系统时间与已有预测区间不相交、采集缺口达到2s、休眠／恢复或连续性无法证明，均使本服务认证域保护锁存。错误采集立即阻止新业务，不等后台到期任务；成功采集也不能清除故障。Controller按既有AuthenticationClockFault／ClockClosePlan处理完整域出口，保持持有人、已发送与unknown事实；失败提交或无法确认关闭时由监督路径停止受影响出口。Seamer停止签发新运行工作、暂停受影响运行并使未发派发失去资格；对已交付Controller的许可走既有撤权／取消传播，未获目标确认不得显示全域已停止。业务NTP单独失效仍仅影响其时间依赖，不触发这项认证域故障。

恢复沿既定本机管理员维护入口，顺序固定：①保留故障与过期拒绝事实，停止新工作；②核对全部旧运行成员的关闭／可信退役及远端在途；③管理员修复宿主授时环境并重新验证或更换环境批准；④监督器建立有新证明的运行绑定，不能仅改客户端ID；⑤采集并可靠提交新域首样本，重新建立身份验证与当前撤销来源；⑥经现有人员恢复流程重新取得设备资格及需要的RunGrant／布防。旧fault不删除，旧域许可／上下文不续用，unknown不重放。

时钟失信时普通“近期重新认证”无法完成，本机维护入口因此只使用受控OS管理员通道授权环境修复、退役和新域启动；它不直接签发业务身份、清除设备保护或跳过密码验证。新域可认证后才进入正常人员恢复。原长期身份可重新证明，但已过期或被撤销的具体版本不能因新域复活；已有人员手动持有关系保持，ready须重新证明。发现未关闭的远端效果时可恢复诊断，不能先开放冲突写。

本节不批准DF05人工更新时间方案，也不把安装时的单次UTC锚缓存成持续运行资格。发行验签／激活时间、业务reference-bound/1的NTS冷启动和运行认证是三条独立来源链；业务参考采集可使用已经有效的认证区间校验证书日期，但反向用业务未认证包修复认证区间被禁止。[DF03第19节](rebirth-df03-time-profile-design.md#19-首期业务参考采集的协议与资格定稿)现已固定协议、时代／闰秒／上游误差profile及NTS冷启动；它只读取当前AuthenticationClockAcquisition原件，不反向为认证域修复时间。实际资格、采集和TLS接线转入实现与验收。

### 13.4 实施交接与验收

采集来源、算法、原件解析、TLS使用和恢复顺序的设计选择至此明确。Controller／Seamer实现原生读取及writer、生命周期拒绝和保护传播；SDK生成policy／acquisition及服务级日志类型并绑定现有出口投影；Suite交付环境资格配置、OS维护入口和两平台部署指南；GUI分别展示认证不可用、业务参考质量及发行时间状态。未实现的类型生成、平台采集、TLS和数据库接线是实施任务，不把本节文字当作运行证明。

复用FA19、TV07／TV11／TV13、IN和ILT验收，增加以下必要轨迹：FILETIME纪元与边界／timespec非法值；采集括号变长、量化外包、提交延迟；前后policy／namespace变化；同id换时间；同域其他出口故障；到期边界与TLS长连接；失信时拒绝远程恢复而允许受限本机维护；新域不能复活曾过期credential或旧permit；Seamer停止而远端旧许可未确认；业务NTP坏而认证正常时即时手动仍受其余守卫正常判定。实际系统读取、两平台误差／速率资格、TLS、并发数据库和出口终止均尚未验收，整体阶段0也未因本节单独完成。

## 14. 身份、配对与运行授权的管理读取

2026-10-29采用。新增以下只读入口，以[C05第18节](rebirth-c05-event-sync-design.md#18-受权历史与管理目录读取)的DirectoryPage完成枚举。只接受当前human；表中权限还必须与具体对象范围相交，查询不能使service成为人员。签发Controller与接收方映射分别列出authority和完整issuer三元组；接收方的subject列表不是全套签发者账户列表。

| GET路径／operationId | 所有者与权限；首请求过滤 | 固定脱敏视图 |
| --- | --- | --- |
| `/api/v1/subjects`／listSubjects | 各服务本地映射；identity.read；principal_kind、state、issuer_id | SubjectSummary：subject_ref、issuer_id／issuer_epoch／principal_id、principal_kind、display_name、state、local_authorization_ref或null；不含登录名、密码摘要、session或token集合 |
| `/api/v1/auth/service-principals`／listServicePrincipals | 指定签发Controller；identity.read；state | ServicePrincipalSummary：subject_ref、完整issuer三元组、display_name、purpose、state、current_approval_ref或null；详情沿第9.3节既有GET |
| `/api/v1/auth/service-principals/{id}/approval`／getServiceApproval | 指定签发Controller；auth.manage及该主体范围；无 | 第9.1节ServiceApproval，含批准者、范围、期限、修订及批准操作引用，不返回credential验证材料；无批准时明确null，不虚构默认许可 |
| `/api/v1/auth/service-principals/{id}/credentials`／listServiceCredentials | 指定签发Controller；auth.manage；state | 第9.3节ServiceCredentialView，只读元数据；包括staged、retiring及保留的终态，不重交付secret或proof原文 |
| `/api/v1/auth/peer-pairings`／listPeerPairings | 各服务自己的配对；auth.manage；peer_service_id、state | PeerPairingSummary：pairing_ref、peer_service_id、issuer_id／issuer_epoch、state、binding_ref或null、activation_operation_ref或null、peer_observed_state或null；远端状态必须带原观察修订与有效性，不合成双方active |
| `/api/v1/auth/peer-pairings/{id}`／getPeerPairing | 各服务自己的配对；auth.manage；无 | 前述summary及允许的transcript引用、范围、凭据指纹、两向验证结果引用和有效期限；不包含challenge／私钥／credential原文，不由详情读取再次发起proof |
| `/api/v1/run-grants`／listRunGrants | 目标Controller；grant.read；origin_service_id、origin_database_instance_id、run_id、state | RunGrantSummary：grant_ref、origin_scope、run_id、definition_version、arm_generation、主体三元组、state、validity及preparation_ref或null；每目标独立目录，不把部分目标active汇总为全run已授权 |
| `/api/v1/run-grants/{id}`／getRunGrant | 目标Controller；grant.read及具体grant／设备动作范围；无 | 当前具名RunGrant原件的公开字段，精确device_actions／parameter_constraints／validity及运行绑定；任何字段无权则整项拒绝，不裁剪原件后保留原digest |

SubjectSummary的state来自主体／本地映射记录，支持active／disabled／revoked；该目录分类不复活远端被撤主体。服务主体state严格沿第9节disabled／active／revoked；其余state沿对应具名领域模型封闭生成，不从展示字符串反推枚举。过滤中的issuer_id只限定结果，授权比较始终含issuer_epoch和principal_id；列表项object_ref分别使用IdentityObjectRef、配对既有引用或RunGrant具名Ref，不把它们按字段名强制转换成一套引用。

身份／批准／凭据目录更新纳入I1—I4，本地映射／配对纳入I5／I6，RunGrant目录与目标Controller准备／撤销事务一起提交；远端receipt只记录已验证原件和当前观察有效性。无法获取签发者或认证时钟不可信时，不以缓存目录作为当前授权证明。密码、秘密、bootstrap能力及证书私钥没有列表查询入口；credential轮换仍保持一次交付，GET不重新发秘密。用户名称等可识别信息只进入获授权页面，不随普通日志或匿名状态输出。

GUI的组织授权页据此分开显示：签发方ServiceApproval、Seamer的运行批准、各Controller真实RunGrant及撤销操作。ServiceApproval修改仍走第9节PUT，目标grant撤销沿现有revokeRunGrant／revokeAuthorization，并核原固定目标集；updateRunGrant仍仅配对Seamer能调用。该运行批准缺口现由[C04第18节](rebirth-c04-automation-design.md#18-组织运行批准与目标范围认可)定稿：Seamer冻结完整proposal，目标Controller由当前有权人员认可自身范围，Seamer人员批准完整集合；真实RunGrant仍在prepare时签发。本表ServiceApproval或列表原件都不能代替该发放链。GrantIntent改为完整Principal，参数限制采用ActionParameterConstraint而非观察Predicate，生成时与本地可授策略共同迁移；人员历史认证只作批准审计，不能成为已布防组织授权的持续在线依赖。

本节新增8种路径／方法声明，其中列表5种、详情3种；两authority展开与实际最终operation数由SDK生成确定，不简单加到旧201。列表和详情不改变原写权限。验收包含不同issuer同principal、映射与权威分离、凭据终态可读但不可换token、配对仅单端active、失信查询拒绝、grant字段无权整项拒绝、翻页间撤权和响应不含秘密；均待实施。
