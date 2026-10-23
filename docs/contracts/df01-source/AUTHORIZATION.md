# DF01／DF06：逐操作主体与用途候选

本稿补齐[导出清单](EXPORTS.md)没有表达的调用主体边界。状态为**待审阅推荐**，机器资料固定`approved=false/authority_switched=false/runtime_approved=false`；既有draft.4／IPC0.3及其接受集不变。适用范围是现有两服务71个HTTP／WS操作，未来安装、配对、面板和服务订阅接口不冒充已经存在。

## 1. 已知事实与新增取舍

已知事实：当前HTTP骨架声明认证方式和权限，但没有完整主体用途策略；AuthorizationBinding结构允许service＋manual；Session和WsTicketBinding要求非空session_id；issueToken是人员Cookie＋CSRF换取定向短期令牌，路径中的service-tokens不表示创建组织服务身份。updateRunGrant已有“配对Seamer提出范围、Controller取本地交集”语义；provider目录和事件不得按自报provider_id信任；人员退出不撤销独立组织授权。（来源：[两份HTTP骨架](source/http/controller.operations.json)、[公共模型](source/public.schema.json)、[首闭环§2/§6](../../rebirth-first-loop-contract.md)、[F04§2](../../rebirth-f04-f05-design.md)、[draft.3§3](../../rebirth-draft3-review.md)。）

本轮推荐以下取舍，不能从历史security自动推导，也不能当用户已批准：

1. **人员手动、服务自动化分开。** manual及接管/转交仅接受human；服务设备写只接受配对Seamer的automation＋当前RunGrant。后台KEY/数据源通过受控provider事件驱动Seamer；人员操作面板仍由宿主代理当前human。此项收紧现有Schema的service＋manual组合，归并时必须有接受集差分。其他服务不能靠origin改成manual、假session或自报Seamer身份绕过布防。
2. **服务可以准备，不能自我批准。** 在组织授予的目标范围内允许服务读取、编辑草稿、创建未布防run、只读预检/恢复预览、暂停所属run；发布、布防、执行恢复要求人员明确操作。定时触发仍由已布防的服务执行，不要求每次场次到达再由GUI批准。保留未来受控服务发布需求的扩展位置，首期没有自动发布/自动重新布防权限。
3. **当前会话订阅链先保持人员语义。** getSession/createSubscription/getSnapshot/issueWsTicket/openEvents用于当前人员会话；服务获取状态可使用已授权单对象HTTP，provider仍能提交事件。此为当前链的推荐边界，不证明历史createSubscription已经禁止service，也不取消C05的服务事件交付目标；独立服务订阅必须另版建模。
4. **权限下降也核对目标。** 人员按grant.revoke撤销授权；配对Seamer只撤销其权威范围内的grant。service的cancel/pause只作用于授权且归属自己的command/run；不能猜中ID便取消他人人工操作。保护性本地暂停/到期是服务内状态机，不通过伪造人员HTTP调用实现。

## 2. 权威上下文与固定评估次序

候选`AuthenticatedRequestContext`由入口从凭据和权威记录构造，不是客户端JSON：`authority_service_id, database_instance_id, issuer_id, issuer_epoch, subject_id, principal_kind, principal_id, session_id|null, credential_id, credential_revision, audience, permissions, object_scope_ref, authorization_revision, auth_deadline, peer_binding_ref|null, source_binding_ref|null, delegation_ref|null, recent_auth_ref|null`。subject_id使用目标服务本地不可复用映射，不能把裸外部principal_id当本地holder_id。当前RequestContext的线字段不足以携带全部关联，服务端必须保存完整绑定；下一版补可核验引用，不信任调用者传入的完整上下文。

评估顺序：限定入口与原始报文预算→验证对应凭据→核对当前权威/撤销/认证时间/单audience→匹配本表主体分支及源x-permission→目标对象归属/当前范围→委托及用途守卫→请求上下文/幂等/修订→操作自己的接管、完成、时间和容量门控。原始报文检查可在鉴权前保护资源，但不返回对象内容。多个分支是OR，各分支内的条件及对应OpenAPI Security Requirement是AND；不能把Cookie与CSRF拆成OR。

受理和最终派发均重新核验其负责的授权；查询在释放响应前复核，已交传输层字节不可撤回。auth_deadline取凭据、会话、组织批准、grant、委托及快照可证明截止的最小值，依F04从challenge发出时计时；新token不延长旧许可，权限撤销不释放接管。绑定摘要不是权限证明。（依据：[F04](../../rebirth-f04-f05-design.md)、[DF06§2/§3](../../rebirth-df06-internal-trust-design.md)。）

`createRequestContext`只为当前主体/凭据授权链及目标audience保存所请求操作的交集；需要的操作未获授权时整项请求拒绝，不静默扩权或改成另一主体。每次消费继续检查实时权限；context存在不代表grant/接管已经成立。委托产生的context绑定同一delegation和撤销域，不能提升成独立human请求。恢复后换请求世代，不能只凭相同principal_id重用上下文。

## 3. 认证档案与操作矩阵

机器清单见[authorization-candidate.json](authorization-candidate.json)，每个键精确为`service:operationId`，绑定四份源字节摘要。每行包含source_pointer、permission、branches；每分支固定profile、origin及guard。未列分支拒绝，未知profile/guard拒绝；不能按URL前缀、SDK入口或客户端填写kind推断权限。

| profile | 认证和主体 | 不可省略的权威检查 |
| --- | --- | --- |
| human | 定向bearer，human，非空当前session | 会话和凭据有效，当前用户权限、认证时间、audience及撤销下界 |
| service | 定向bearer，service，session=null | 当前服务凭据和组织批准范围；不继承批准人员会话，不获得设备manual资格 |
| seamer | 定向bearer，service，session=null | service条件＋双方当前配对、权威登记peer_kind=seamer；请求body中的名称不算证明 |
| provider | 定向bearer，service，session=null | service条件＋精确来源注册、owner服务、provider/boot/stream及用途；配对/扩展批准按实际来源链取交集 |
| internal | serviceMtls，service，session=null | TLS真实对端、当前双向配对、用途及单对象范围；bearer不能替代，反向代理头不能构造此身份 |
| cookie | sessionCookie AND csrfHeader，human | 有效会话、精确Origin、会话绑定CSRF；签发交集不创建service主体 |
| ticket | wsTicketHeader，human | 既有人员会话、audience/Origin/client/scope绑定、期限及一次消费；101不是授权永久有效 |
| bootstrap | 无普通登录主体 | 有限一次性部署能力、未初始化、原子消费；security=[]不等于匿名管理 |
| login | 登录前证明 | 可信Origin、登录证明、有限预算、账户状态；失败不泄漏账户存在性 |

所有已认证profile均需当前目标范围和基础权限；bootstrap/login的auth.*是入口用途标记，不要求先取得登录后RBAC。openEvents没有x-permission时只沿票据已授权scope，不能解释为无限权限。内部profile不自动获得public API资格；public服务请求也不能因为同时持有证书跳过bearer来源。

以下汇总为可读投影，机器清单逐行保留全部71个操作；不把同名operationId跨服务合并成同一权威。

| 操作范围 | 允许profile与用途 | 对象/特殊守卫 |
| --- | --- | --- |
| 两服务meta/clock/clock-assessment/capacity | human、service | 只返回该服务的受控公开投影 |
| 两服务getSession | human | 仅当前自身会话，禁止自报subject切换 |
| 两服务createRequestContext | human、service | 操作/用途交集、同主体凭据链、单audience、有界期限 |
| 两服务createSubscription/getSnapshot/issueWsTicket/openEvents | human；最后一步ticket | 固定会话、当前scope、订阅owner；票据一次消费和快照范围相符 |
| Controller设备/目录/状态/场景/控制查询 | human、service | 当前授权设备范围；列表逐项过滤，游标不泄漏未授权对象 |
| Controller命令/证据查询 | human、service | command所属device及查询范围，原发起人也需当前读取权限 |
| Controller submitCommand | human＋manual；seamer＋automation | 人员当前holder与ready；或完整run/grant/arm及本地自动模式；两分支仍经公共执行守卫 |
| Controller cancelCommand | human、service | 人员有目标取消权；服务限自己组织run命令，不取消外来manual；受理不证明设备停止 |
| Controller acquire/release/offerTransfer/acceptTransfer | human | 强制取得另需control.emergency；释放为持有人或明确授权释放者；邀请由持有人发起、仅固定目标接受 |
| Controller updateRunGrant | seamer | 本地批准交集、run/definition/arm/approval/validity匹配，不接收自报active |
| Controller revokeRunGrant | human、seamer | 人员具目标撤销权；Seamer仅本权威/组织范围，不解除manual控制 |
| Controller bootstrap/login/refreshSession/issueToken | bootstrap/login/cookie/cookie | 初始化一次消费；登录证明；刷新轮换；定向签发交集及扩展关联 |
| Controller introspect | internal | 仅目标服务audience及其可使用凭据；不能枚举所有主体token |
| 两服务revokeAuthorization/setCapacity | human | auth.manage/容量权限、精确对象、近期认证；后者还须已验证profile |
| 两服务getRevocation/getSubject | human、service | 当前可读目标；服务仅自身或显式授予对象，不公开完整身份目录 |
| Seamer updateCatalog/ingestEvent | provider | 仅已登记来源；目录修订/能力与事件boot/序号/因果/年龄资格另验 |
| Seamer createDefinition/updateDraft | human、service | 目标定义编辑范围和修订；服务仅可编辑组织明确授予草稿，不隐式发布 |
| Seamer publishDefinition | human | 明确发布固定草稿修订，依赖证明/能力/范围另验；发布不布防 |
| Seamer createRun | human、service | 固定定义版本，在许可范围内新建未布防run，不继承旧grant |
| Seamer getRun/preflightRun/previewRecovery/getRecoveryOperation/getIndependenceProof | human、service | 精确run/definition/operation读取范围；预检/预览只读设备，不生成派发许可 |
| Seamer armRun/resumeRun | human | 显式布防批准/完整预检；或固定恢复预览与一次消费；不能以刷新或心跳触发 |
| Seamer pauseRun | human、service | 人员有目标暂停权；服务限本组织授权run，逐Controller确认，未确认仍显示未确认 |
| 两服务四个内部时钟查询 | internal | 原authority与精确对象/修订、当前/历史读用途，no-store；不从公开入口绕取原始证据 |

guard字典随机器清单保存具体定义。它们是待实现规则的名称，不是已取得的事实；`all_guards_true`一类自报标志不能进入真实API。扩展面板不属于额外principal_kind：仍是human＋可核验delegation，权限为安装批准∩当前用户∩目标∩面板scope。强制接管/布防/恢复由可信宿主确认；当前draft.4缺此委托绑定，归并前不能部署面板绕行普通HTTP。（依据：[ME06](../../rebirth-c09-extension-design.md#7-me06第三方面板通过宿主代理委托)。）

票据签发使用`ticket_issue`守卫检查请求scope、Origin和client，而非要求请求携带当前WsTicketRequest中不存在的subscription_id。升级/订阅交接再核对`ticket_binding`及`subscription_owner`；下一版若增加精确subscription引用，必须连同C05显式归并，不能仅在校验器假定字段存在。

其中openEvents的`subscription_owner`是**下一版开始交付订阅数据前**的要求，依赖C05的精确绑定/attach；不是当前GET升级请求已经拥有subscription_id，也不要求尚未attach时凭空取到订阅对象。当前draft.4只能按既有人员票据及scope核验，不能从scope_digest猜订阅。候选下一版允许票据通过后升级，但在owner关联通过前不交付订阅数据；绑定失败依升级后的协议关闭/失步处理，不再返回HTTP JSON。具体消息字段与阶段调用点须随C05归并，本元数据检查未证明该守卫已能凭现有线模型执行。

## 4. 身份生命周期不能靠现有路径名称补齐

以下是下一版必须覆盖的接口族及明确边界，**不计入71个已有操作，也不声明已生成OpenAPI**。沿用DF06/DF04/C09的权威表，不创建第二套授权数据库。

| 缺口 | 推荐归并契约与结果 |
| --- | --- |
| 普通退出 | `DELETE /auth/sessions/current`，Cookie＋CSRF＋精确Origin；只撤当前会话，不需auth.manage，不要求近期再认证；幂等返回撤销operation及逐服务状态，清Cookie不等于撤销已全局应用。凭据过期无法请求时仍清本地会话显示，服务端按有限期限/撤销处理，不伪报applied |
| 当前主体视图 | 增加具名PrincipalView与`GET /api/v1/principal`，human/service判别、service的session=null、audience/范围引用；保留旧getSession的人类会话语义，避免给service伪造会话 |
| 服务身份与凭据 | 由指定签发方管理service identity、组织批准、credential登记/轮换/撤销；创建/增权/凭据管理要求管理权限与近期认证，秘密仅首次交付，已有issueToken不能代替。恢复与轮换不延长旧批准或复活grant |
| 配对与信任 | stage→双向challenge/指纹与scope确认→双方分别active；有界期限、单次消费、精确revision，撤销保留固定目标集；不以TLS成功替代配对批准 |
| 服务订阅 | 与人员票据不同的service订阅绑定：服务凭据、audience、source scope、日志世代、消费身份与撤销；按C05快照/ACK交接，不伪造session，不以普通HTTP轮询代替关键事件完整性。协议和额度另版联校 |
| 面板委托 | C09的PanelSession/Delegation引用、宿主具名方法、安装及会话revision、一次确认绑定；不能只在TokenRequest中自报extension_instance_id便取得扩展身份 |

公开错误：未认证/已过期为401，已认证但无操作用途为403，超出对象可见性与不存在统一404；修订冲突409/412、不可证明权威可用性503，具体码沿目标端点已声明集合。不能把权限失效当作设备failed或自动重试理由。WS升级前按其现有401/403集合处理，升级后使用版本化的关闭/失步协议，不硬塞HTTP错误正文。鉴权先于返回幂等历史记录；即使请求内容相同也不得泄漏其他主体结果。

## 5. 正反例与验收衔接

以下运行用例是**计划**，不计入元数据离线通过数量。纳入FA/IN/UIT/MX的后续实现验收，不替代原验收条目。

| 轨迹 | 必须结果 |
| --- | --- |
| human持有人manual、有效context且全部执行守卫成立 | 可进入原命令受理流程；202仍不是设备完成 |
| service拥有device.command但origin=manual | 推荐新版拒绝；旧Schema可接受的差异有独立记录，不能靠SDK隐藏按钮实现 |
| human提交automation、填写合法grant_id | 拒绝主体用途；猜中grant不代表属于该服务 |
| 配对Seamer自动命令→人员接管/撤grant先到出口 | 旧许可不得发送；先发送则保留在途，不改成未发送 |
| provider.publish＋另一provider路径/boot/注册revision | 拒绝来源绑定；合法token和合法JSON不能覆盖越权 |
| service编辑草稿/建run后尝试publish/arm/resume | 准备操作只在授权范围内；后三者拒绝，不自行恢复自动化 |
| 准备命令后human退出，独立组织run仍有效 | 撤该会话queued及未发委托，不撤组织run、不自动释放holder |
| 人员同名但issuer_epoch或本地subject不同 | 不继承holder/订阅/context/转交目标资格 |
| 持有人发邀请，另一账号或新会话试图改目标 | 非目标拒绝；目标新会话仍须精确主体、当前权限、未过期及版本匹配 |
| 只有Cookie或只有CSRF，Origin错误 | 拒绝刷新/签发，不能选择另一个宽松分支 |
| ticket重用/跨audience/跨Origin/跨client或错订阅 | 拒绝；断线不能重新消费票据或扩展scope |
| service请求当前Session或复用人员WS票据 | 拒绝，不生成虚假session；独立服务协议未交付前明确不支持此链 |
| internal有效证书但配对撤销/用途错/对象owner错 | 拒绝；已建TLS连接不能保留旧权，释放响应前再查 |
| 两个credential同主体，旧凭据context被新凭据直接搬用 | 未经明确继承策略拒绝；新凭据另取context，已受理记录按当前权限查询 |
| 普通用户退出但没有auth.manage | 新注销接口可撤自身会话；旧管理员撤权入口不被偷偷降权 |
| delegated请求撤权后换普通human入口重投 | 委托绑定保留并拒绝；不能去掉extension信息洗掉撤销域 |
| 已撤权主体以旧幂等键查既有成功命令 | 先按当前查询权限裁决，不因历史成功自动返回敏感结果 |
| 权威查询超时，缓存已到认证截止 | 拒绝新受理/派发；不续TTL，不猜账号未撤销 |

离线检查只验证候选结构、71操作无遗漏、源permission/security与分支匹配、用途约束和人工变异。所有权威取证、真实token/CSRF/TLS、并发撤权、接管和运行用例执行数均为零。完整身份生命周期接口、服务订阅和面板委托归并完成前，C01/C07仍未关闭；本稿不会把已知缺口改成已实现能力。

复验：`docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_authorization.py --report`运行结构与36项元数据预期；`--check-report [--staged]`仅核对九输入的原始字节。minimum guard和主体集合是独立审阅预期，不作为未来服务的第二份权威策略。检查器不解释guard文本、不取身份事实，也不实现真实授权决策；未来实现仍需每个具名守卫的来源、评估及调用点绑定。
