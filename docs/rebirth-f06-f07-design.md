# F06／F07：OBS 完成证据、失败依赖证明与恢复并发

> 后续确认与归并：用户已同意本文 F06／F07 推荐方案；[F01—F07 整体审阅](rebirth-draft3-review.md)已将候选归并为公共 draft.3／IPC 0.2，并补齐跨对象引用。本文保留当轮设计，当前机器基线以新版为准；OBS与并发故障验收仍未执行。

- 日期：2026-10-17；用户已同意 F04／F05 推荐方案。认可设计不等于身份、NTP、容量或设备运行验收通过。
- 已确认约束：Q1—Q72、公共 `1.0.0-draft.2`、F02／F03 与 F04／F05；以[主设计](rebirth-design.md)为准。
- 以下为本轮工程推荐 `f06-f07/0.1.0-draft.1`，尚待评审。只新增协议资料和离线检查，不修改业务代码。候选结构及人工向量见[校验入口](contracts/f06-f07/README.md)。

## 1. 已知事实与本轮分析

**官方事实。** obs-websocket 5.6.3 文档给出场景 UUID、设置／查询 Program 场景、按 requestId 返回请求结果；集合列表只提供名称，集合切换中官方要求暂停查询。场景事件没有命令 requestId。协议版本号不能替代请求可用性检查。（来源：[固定版本协议](https://github.com/obsproject/obs-websocket/blob/5.6.3/docs/generated/protocol.md)）

该版本源码在验证目标场景后调用 `obs_frontend_set_current_scene`，随后返回成功；读取 Program 是另一请求。这个返回点不是本项目的图像验收点。（来源：[官方场景处理源码](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_Scenes.cpp)）

**项目分析与推荐。** 首闭环使用 UUID，设置应答加后置新查询证明协议后置条件；原生命令与图像、外部操作、状态机提交分别取证。恢复需要新的明确执行计划和一次消费，不能把暂停按钮反向实现为重发旧队列。静态独立性证明采用有限、保守的依赖分析，不能由模块或 GUI 自报“安全”通过。

三个跨项补充需要下一版显式归并：完成证据增加同会话顺序及目录代际；独立性证明绑定可审计的依赖闭包；恢复预览增加有效期、单次消费、授权及控制快照。这些模型不混入拒绝额外字段的 draft.2 对象，公共 OpenAPI 和 F02 IPC 本轮保持不变。

## 2. F06：首模块边界与能力映射

### 2.1 固定参考与候选验收组合

协议／源码参考固定为 obs-websocket `5.6.3`，RPC `1`，JSON 编码。OBS Studio `32.0.4` 作为首轮**候选测试版本**，Windows 11 x64 和 Ubuntu 24.04 amd64 分别记录；该版本官方发布页存在两平台产物，不据此宣称组合兼容。（来源：[OBS 官方发布页](https://github.com/obsproject/obs-studio/releases/tag/32.0.4)）

目前尚未下载、安装或测量任何 OBS 包，未确认该包内嵌的 WebSocket revision；不能将两个参考版本写成“已支持组合”。实施前须记录 `obs_version, websocket_version, negotiated_rpc, available_requests_digest, obs_artifact_sha256, module_artifact_sha256, platform, source_commit, protocol_digest, fixture_digest`，核对二进制内嵌协议源码并按实际版本重新审阅。若不符，新增版本化映射并重跑用例，不能只放宽版本字符串。当前既不承诺最新版本，也不发布支持矩阵。

首验收夹具建议只有两个静态场景 A/B、无场景切换脚本／额外插件写入、单画布、Studio Mode 关闭、Cut 转场且无场景专属覆盖、不推流。它是最小已测配置的候选，不删减后续功能。配置由操作者在隔离环境准备；模块只核对，不自动改 Studio Mode、转场或开停推流。非该配置的写能力首期保持 unavailable，完成专项取证后才扩展能力 profile。

### 2.2 映射表

| LeafSeamer 能力／用途 | OBS 映射 | 约束 |
| --- | --- | --- |
| 连接预检 | Hello → Identify → Identified；GetVersion | 认证成功、RPC 与 required requests 均可用后才发布能力；不把连接成功当就绪 |
| 场景目录 | GetSceneCollectionList、GetSceneList | 按下述代际构建目录；只含真正 scene，group 不能混入 |
| `obs.program_scene.set` | SetCurrentProgramScene，仅发送 sceneUuid | 参数 SceneRef；唯一最终出口；禁止名称回退、batch／hotkey／vendor 写入旁路 |
| 完成查询 | GetCurrentProgramScene | 必须在原设置成功应答后发起，读取 sceneUuid；只读查询可用预留预算，不能在集合切换期发送 |
| `obs.program_scene.changed` | CurrentProgramSceneChanged | 生成观测与触发事件，不伪造 command_id 或确定 actor；因果 unknown，不能冒充“由本命令触发” |
| 目录／连接失效 | 集合 changing/changed，scene created/removed/renamed，连接断开 | 作废相关目录及许可；按实际影响暂停，不自动改绑定义 |
| 夹具核对 | Studio 状态、当前及场景覆盖转场的只读查询 | 缺字段、未知转场或不支持 profile 即不可写；具体查询支持随版本清单锁定 |

动作声明保持 `completion=effect_verified, cancellation=before_dispatch_only, retry=never`，冲突域 `device/{device_id}/program`。完整设备接管范围不缩小为此资源。读集合、目录、转场和当前值的动作不产生设备写；它们仍受连接状态、集合切换和容量保护约束。

事件使用 Controller 的 source epoch／sequence／固定 event_id 去重。OBS 原始事件缺乏本项目可信发生时刻，首期自动化触发需 F05 的可信年龄证明；无法证明年龄的场景事件只更新显示／使规则暂停，不凭“刚收到”认定新鲜。可用 challenge 后的只读 fresh sample 作为**另一个状态采样触发**，不能把它包装成之前那次场景变化；注册的触发类型及规则需显式区分。重连快照不制造 changed 事件，自己的设值事件也不得形成无界反馈：规则预检拒绝确定循环，运行还有重入／速率／预算上限，超限暂停，不丢关键事件后继续。

### 2.3 SceneRef 与目录生命周期

`collection_ref` 是 Controller 持久分配的本地不透明身份，不是假装 OBS 提供的集合 UUID。`scene_id` 绑定该集合内的 OBS sceneUuid；`catalog_revision` 是行为目录修订。名称仅显示。CatalogBinding 候选字段见 Schema：`device_id, device_session_id, collection_ref, collection_generation, catalog_revision, binding_revision, status, entries[]`，entries 为 `scene_id, obs_scene_uuid, display_name`，身份必须一一对应。

1. 初次发现建立 `unconfirmed` 绑定，操作者核对后成为 ready。在同一连续会话中单纯改名只改显示，不换 scene_id；新增／删除引起目录修订，删除的引用不复活，重新同名创建是新 UUID。
2. CollectionChanging 立即令该设备目录 changing，关闭此模块新写并停止轮询；已发送只保留证据，不能为完成强发查询。Changed 后才能重新发现，分配新的集合代际及绑定；即使名称相同也不能自动把旧集合身份续上。
3. 重连、OBS／worker 重启或漏事件后目录 stale。由于名称不足以证明集合连续性，首期要求显式重认绑定、定义预检和重新布防；不通过读写 persistent data 给第三方配置偷偷植入标识。
4. 预检和最终发送都比对绑定／目录／会话代际；失效先于发送则 blocked/not_sent，发送先于失效且无完整证据则 unknown/possible/unresolved。目录重建不清除旧命令占用。

OBS 不提供本项目的跨客户端目录锁。原生 GUI 可在最后检查后改变配置；最终门控只能拒绝**已知**失效，不能保证物理原子性。隔离夹具控制外部写入，真实现场需报告此限制；后置查询不匹配时暂停，不能重试把现场强行改回。

## 3. 完成证据与资源释放

### 3.1 候选数据结构

| 模型 | 核心字段／语义 |
| --- | --- |
| ObsEvidenceFrame | evidence_id、command_id、attempt_id、worker_boot_id、device_session_id、collection_generation、catalog_revision、protocol_request_id、kind、io_seq、tick_ns、success、scene_uuid；io_seq 为同一 worker 串行发送／接收日志序号，tick_ns 为同一启动单调时钟，不能比较不同进程时钟 |
| ObsCompletionBundle | policy_id、目标 scene_uuid、上述身份锚点、set_request_id、query_request_id、frames[4]、evaluation_tick_ns、deadline_tick_ns、max_query_age_ms、catalog_current、fixture_current、durable；4帧依次 set_send/set_ack/query_send/query_result，必需全部来源匹配 |
| 业务完成投影 | bundle 通过模块证据策略并可靠落库后，引用到公共 CompletionEvidence／completion.evidence_ids；achieved=effect_verified，不能让调用者自报 durable 或 predicate_result 来授予成功 |

`set_send < set_ack < query_send < query_result` 必须是严格递增 io_seq，同启动 tick 非递减；两个请求 ID 不相同且分别匹配，结果 success=true、scene_uuid 等于目标。查询完成到评估的年龄严格小于预算，整个评估严格早于命令 evidence deadline；实验例值 500ms 只是离线向量，不是生产承诺。生产预算还须考虑 OBS 主线程负载，并受 F05 容量／时间预算约束。集合／夹具在评估前失效则不满足本策略。

已是目标场景也不省略本契约规定的设置应答和新查询。仅 ACK、仅事件、预发查询、缓存同值、其他连接同 requestId、超时后新查询同值均不能拼成这次成功。证据策略版本由受信任模块和 Controller 验证绑定，文件中的布尔值仅是输入示例，不能替代权威事实。

### 3.2 结果决策

| 已获得事实 | 命令结果及后续 |
| --- | --- |
| 确定从未进入发送出口 | 按原因 blocked/expired/cancelled；not_sent；clear 必须有 F02 未发送证据 |
| 完整四帧、目录／夹具有效、及时且可靠保存 | succeeded/verified；在该已验证 Cut profile 下资源 clear，保存模块释放证据；业务状态仍由 Seamer 自己提交 |
| 设置 ACK 成功，查询明确不同 | 完成谓词未满足，failed/acknowledged；资源默认 unresolved，直至独立释放证明，不自动重发或回滚 |
| 请求发出、ACK 丢失／断连／查询超时／目录切换 | unknown，possible 或 acknowledged，unresolved；暂停锁存 |
| OBS 明确错误响应 | 只有该固定实现的错误分支已审阅为调用前拒绝，才可 failed 并证明该尝试无设备效果；首期错误白名单为空，其他错误保守 unresolved，不按所有非100码一律释放 |
| 原终态后获得完整迟到事实 | 追加 resolution 和必要资源证据；原 outcome 不变，自动化仍 paused_latched |

`effect_verified` 在此只证明请求已被接受且后置查询看到目标 Program 身份，不证明唯一因果、持续保持、音视频输出正常或观众收到画面。原生操作刚好改到同目标无法区分。截图／录屏属独立视觉验收记录，包含采集时刻、夹具、平台、包摘要及脱敏产物摘要；不能替代协议证据，也不要求生产命令每次截图。

资源 clear 表示本动作按已验证策略不再有未决影响，不是锁住 OBS 原生 GUI。非 Cut、Studio Mode、转场覆盖、多画布等必须独立定义结束／资源释放策略后开放，禁止沿用“Program 名称相同就已结束”。Unknown 不能仅凭新查询清锁；首期没有通用强制覆盖／自动 OBS 重启，需模块级未决核对证明或维护流程，保留原历史。

### 3.3 故障时序

- O-T1：持久化 intent → Set 发出 → ACK 丢失 → 事件 B → 新查询 B。结果仍 unknown；事件及查询只表明现在是 B，禁止重发 Set。
- O-T2：Set 发出 → 成功 ACK → 集合 Changing → 完成查询尚未发送。停止查询，目录失效，命令 unknown；Changed 后重发现也不完成旧会话／代际命令。
- O-T3：Set ACK → 后置查询 B → 完成事务失败。不能公布可靠 succeeded；F03 保护写入，恢复先按原 command/attempt 核对记录，不重发。
- O-T4：Set ACK → 后置查询 B → 接管屏障生效 → 完成证据入库。接管仍有效；旧动作可被记录完成并清资源，Seamer 不自动继续，ready 要重新核对未决集。
- O-T5：预检有效 → 原生 GUI 改集合／场景 → 最终出口尚未知 → 命令可能发出。真实记录此竞争；不宣称后置检查消除了外部写入窗口。

## 4. F07：失败独立性证明

### 4.1 证明范围与责任

仅用于 Q72 的简单顺序规则中 `required=false, on_failure=continue_if_independent`。状态转换及并行组保持全部 required/stop，不接受证明豁免。OBS 首动作 retry=never；证明通过不意味着可以重试失败动作。

SDK 模块声明 EffectFootprint：`action_ref, manifest_digest, semantics_revision, complete, reads[], writes[], failure_writes[], resources[], safe_failure_classes[]`。键使用解析后的类型化完整路径（设备状态、变量、步骤输出、事件、资源等），目录别名先规范化；前缀相交算相交。缺少、通配、动态计算、外部隐藏依赖、未声明脚本均是 unknown；不将空集合视为“未填但独立”。OBS 场景切换可能影响声音、媒体源和图文，首期使用整个设备的保守影响足迹，不能只声明 program 指针而忽略这些副作用。

Seamer 内置有限 DSL 分析器根据固定定义生成参数、谓词、守卫、目标状态要求、失败路径、控制流及资源依赖图；扩展不能上传执行任意证明程序。图中含显式 depends_on 和隐式数据／资源边，计算**全部可能后继闭包**。每个相关表达式必须可解析到有限已知键；无法证明就拒绝继续策略，可改为 stop，并向编辑者指出依赖位置。

推荐独立性条件：失败步所有可能写／失败写集合，与后继闭包的读、写、资源、前提、目标约束均不相交；后继不读取失败步输出／状态、不依赖它解锁或选择分支。保守拒绝写写相交，即便有人认为后一步可覆盖前一步。证明只保证声明模型内无影响；模块足迹必须经过来源与实现审阅及反例测试，模块自报 complete=true 或 signed=true 不构成事实。

### 4.2 IndependenceProof 具体字段与失效

`proof_id, proof_revision, generator_version, definition_digest, bindings_digest, failed_step_id, successor_step_ids[], failed_footprint, successor_reads[], successor_writes[], successor_resources[], graph_complete, control_dependency, verdict`。

bindings_digest 的 JCS 输入固定为：definition_id/version/content_digest；按 action_ref 排序的模块产物／manifest／semantics revision／参数Schema摘要；按 device_id 排序的控制归属及能力目录修订；分析器版本、DSL版本、资源别名表修订及完整依赖图摘要。proof_revision 为 Seamer 分配的单调修订；公共 StepDefinition 上的修订引用必须同时落到同一发布定义中持久保存的 proof_id，不能跨定义猜同号证明。只读展示可返回 proof 摘要；发布端及运行端读取权威存储而非相信提交的 verdict。

定义、模块二进制、足迹、目录、别名、谓词或分析器改变均使旧证明 stale；只改显示文字且不改变这些输入无需重证。发布时生成／核验；布防时复核；在失败继续的瞬间再次核对 proof revision、bindings、当前控制／授权／时间／存储门控、步骤状态及全部相关资源。发现变化锁存暂停，不能后台重新证明后自动接着跑。

继续必须同时满足：outcome=failed 且属于已批准的明确业务失败类；资源 clear、有有效无未决效果证明；证明当前且 independent；所有相关门控合格。unknown、blocked、expired、cancelled、撤权、接管、存储故障、事件失步等不满足；optional 不豁免这些保护。无副作用的失败也可能有控制依赖，仍需证明。允许的失败仍记录在执行摘要 completed_with_failures，不能将 failed 改为 succeeded。

正例：模拟器 optional 写设备 A 的诊断标记明确拒绝，足迹完整；后续只读取设备 B 自有输入且无共享总线／互斥域，资源已清且门控有效。反例：后续参数引用失败步输出、守卫读取 A、两个逻辑设备映射同物理资源、目标状态要求诊断已完成、动态脚本读取未声明值；均拒绝。该正例不是对任意真实设备的安全认证。

## 5. 恢复预览、单次消费与状态提交

### 5.1 候选 API 与字段

保留 draft.2 `/runs/{run_id}/recovery-preview`、`/runs/{run_id}/resume` 的路由和请求身份规则，以下扩展待下一公共版本归并。预览是只读计划，不预占设备控制权，不使 grant active，不延长旧命令截止。

| 契约 | 候选字段与约束 |
| --- | --- |
| RecoverySnapshot（扩充预览） | preview_id/digest、run_id/revision、service_boot_id、request_epoch、definition_digest、plan_digest、authorization_digest、control_digest、proof_bindings_digest、evidence_digest、arm_generation、issued_tick_ns、expires_tick_ns、unresolved_command_ids[]、proposed_step_ids[]；摘要覆盖所有字段但排除 preview_digest，JCS＋SHA-256 |
| 预览附属执行计划 | 有序条目 step_id、source_execution_id、source_command_id/null、decision=`retain_success/execute_new/reconcile_commit/stop`、reason、parameters_digest、evidence_ids、预算／截止；plan_digest 覆盖全部条目及资源；UI 逐项展示已有副作用与计划新操作 |
| Resume 请求 | 继续使用 context／幂等身份、expected_revision、preview_id/digest；服务端取固定预览及计划，不能用请求携带的新参数替换计划 |
| RecoveryOperation | operation_id、run_id、preview_id、request_digest、previous_run_revision、committed_run_revision、recovery_generation、state=`reserved/preparing/ready/running/completed/paused/indeterminate`、new_execution_id、new_command_ids[]、consumed=true；查询权限按当前身份复核 |
| 错误与接收 | 202 表示操作已可靠受理，不表示已恢复；401/403 当前身份不可用；409 revision／已消费／请求键内容冲突；412 快照／前提失效；429/503 容量或服务保护。错误附稳定 code 和 operation 引用（若调用者有权） |

authorization_digest 包含操作者身份与 scope revision、目标组织批准／grant 修订，control_digest 包含所有目标 Controller 的 epoch、设备接管版本与资源状态修订，evidence_digest 包含原命令及 resolution／资源证据版本。不同启动域的 tick 不可比较；服务重启所有旧预览作废。实验有效期30秒仅供向量测试，生产值待 GUI 与延迟测试。预览过期仅阻止消费，不改变设备现场。

### 5.2 SQLite 事务与跨服务边界

**R1 预览保存。** 收集权威记录与新鲜观测，读到的 run_revision 未变化才保存快照；否则重算或返回冲突。Controller 快照只是观察，不提供分布式锁。未决命令非空可以展示计划，但 resume 消费必须拒绝；不允许靠勾选“忽略 unknown”放行。

**R2 单次消费。** Seamer 短写事务内先按原请求身份查询已有操作；同键同摘要在当前授权仍允许查询时返回原 operation，同键异内容409。对新键，核对 run_revision、未消费、当前启动／请求世代、快照摘要、有效期及本地权威依赖版本；CAS 更新 run revision 和 active_execution_id，消费 preview，分配 recovery_generation/new_execution_id，保存计划／操作／审计／固定 outbox event。唯一约束 `(request_epoch, actor, operation_kind, idempotency_key)`、preview_id 单次消费和 run 单一 active recovery。两个不同键消费同预览只能一个成功；失败事务不能留下“部分已消费”。同键重试响应丢失不重新执行 R2。

**R3 准备／激活。** R2 后仍 paused，先重新核对各 Controller，申请新执行绑定与 grant／写闸守卫；既有 grant 不因“恢复”扩权，不复用旧 arm_generation。所有目标 applied 且预期快照仍一致，才将该恢复操作设 ready，随后 running；每次实际派发仍走 F02/F04/F05 最终门控。准备阶段不得投递设备写 intent；授权安装不等于设备写。跨 Controller 不原子，部分准备失败时 operation paused/indeterminate，尽力撤销已准备许可并记录各目标确认；不能把取消ACK缺失当全部撤销。消费过的 preview 不复活，后续须新预览和明确恢复。

快照绑定的是消费前基线；R2 的 run revision 和后续新 arm/grant 是本操作的**预期变化**，另存 `baseline → target` 的逐目标修订、operation_id 和可靠 receipt，不能要求它们与旧摘要永远相等。除此以外的变更一律视为失效，不把新接管／撤权吸收为“准备成功”。新 grant 严格绑定本 operation／new_execution／新 arm_generation，不能授权旧队列；旧 generation 先失效并完成屏障核对。失败后的撤销目标也按这些固定身份记录，不能误撤销其他独立运行。

**R4 步骤执行。** 从未派发步骤可在已批准计划中创建新命令身份；旧 finished 命令永不改回 queued。明确失败若需人工重做，计划逐项展示并创建新逻辑执行／command，绑定 supersedes_command_id 审计，不能规避 OBS retry=never 变成自动重试。成功步骤 retain_success；未知步骤必须先取得资源核对证明，且旧结果只追加 resolution。禁止重用旧幂等键装入新参数、重放旧排期场次或解除 Q60 锁存；错过场次不能通过 resume 补发，如需操作应成为独立的新手动计划。

**R5 状态提交。** 状态转换的退出／转换／进入全部必需步骤有批准证据，源 business_state/revision、definition_version 和 active_execution_id 仍匹配，且没有接管／撤权／未决等暂停锁存时，在单一 Seamer 事务写目标状态、转换完成、revision、审计和固定 event_id outbox。失败继续只适用于简单规则，不参与此豁免。状态已提交而事件未发只重传同一事件；提交不确定先按 transition/execution 唯一身份查证，不再发设备动作。

该提交表示 Seamer 基于当时已知权威证据完成业务转换，不声称所有远端设备状态在提交瞬间原子保持。Controller 已发生而通知尚未到达的接管／外部改变仍有传播窗口；后续收到即记录偏离并暂停，不能抹去已提交历史。任何恢复计划也不能跨服务消除这一物理边界。

设备成功而 R5 未提交：保持旧业务状态并显示设备实际效果。明确恢复可以批准 `reconcile_commit`，只在成功证据齐全、源状态CAS一致、当前必要前提重新核实后提交；不自动补提交，也不重复成功步骤。若前提已不成立则暂停，现场业务状态校正走 Q41 独立授权审计，不能伪造缺失动作证据。

### 5.3 状态转换与竞争

恢复操作：`reserved → preparing → ready → running → completed`；任一阶段的已知门控失败进入 paused，跨服务／提交结果无法判定进入 indeterminate。paused/indeterminate 不自动回到 preparing，需核对已有事实，再新预览／新操作；旧操作继续保留。正常恢复不是对 finished command 的重开。服务崩溃后同样先暂停核对，不因恢复计划存在而自动继续。

R-T1：两个 GUI 读取 revision=8 → A、B 不同幂等键同时消费 → A 的 R2 提交 revision=9 → B 的 CAS 失败409；只生成一个新 execution。A 响应丢失以原键查询，返回同一 operation，不再消费。

R-T2：预览完成 → 接管／授权修订变化 → R2 或 R3 检查失败；若变化发生在检查后，最终写屏障按 F02 决定已发／未发。不能声称 preview digest 保证跨服务原子性。已发的结果照常追踪，自动化锁存。

R-T3：R2 提交 → 一个 Controller 已准备、另一个超时 → 新写尚未投递 → paused/indeterminate；撤销已准备守卫并核对 ACK。旧预览已消费，不能重试接口另起一套 grant。

R-T4：设备动作完成 → R5 COMMIT 结果丢失 → 重启。先读同一转换身份：已提交则只补事件；未提交则生成 reconcile_commit 预览；无法读库则保护，三种情形都不重放设备动作。

R-T5：optional 明确失败 → proof 校验通过 → 模块／目录更新或撤销到达 → 派发前门控拒绝后继，暂停。证明缓存不提供时间上的永远有效保证。

## 6. 待执行验收（本轮全部未运行）

所有用例需保存脱敏请求／事件顺序、操作及命令身份、权威修订、证据摘要、预期／实际结果；只在隔离夹具运行。故障注入要覆盖边界前后，不能只有正常路径。

| ID | 前置／注入 | 必须断言 |
| --- | --- | --- |
| OB01 | 两平台固定包与隔离 A/B | 记录实际版本／包摘要；预检请求清单、UUID和夹具通过才可写；未测组合不显示 supported |
| OB02 | 缺 UUID／必需请求／不兼容 RPC | 只读诊断、写 unavailable；不回退名称或隐式协议 |
| OB03 | 正常 A→B 与 B→B | 两次均有独立设置ACK及之后新查询；成功证据与视觉记录分开 |
| OB04 | 仅事件、缓存B、ACK前发查询 | 全部不得判 succeeded |
| OB05 | ACK丢失但查询B | unknown、占用、无重发；事件不伪造命令因果 |
| OB06 | 重用requestId到另一连接／boot | 证据拒绝，不能串接旧完成 |
| OB07 | 集合切换发生在 intent／ACK／查询各边界 | 未发失效；切换期零查询；已发未证实unknown；重建不复活旧引用 |
| OB08 | 同名删重建、集合同名、断连漏改名 | 不改绑；连续会话单纯改名维持scene_id；需重认情形明确提示 |
| OB09 | ACK后查询非目标、转场或Studio配置改变 | 不报成功，不强行设回；无有效释放证据不清资源 |
| OB10 | evidence截止／年龄刚好到界、UTC回跳 | 按同启动单调边界拒绝过期证据，UTC不延长 |
| OB11 | 完成落库失败／成功ACK延迟至终态后 | 保护并核对；迟到只resolution；不自动恢复 |
| OB12 | 接管与发送／完成交错 | 屏障语义保持，完成不解除持有人；ready等待资源证据 |
| OB13 | 不明错误码／已审阅调用前拒绝码 | 默认未知影响；只有已测分支支持明确失败／清资源；没有通用非100放行 |
| OB14 | 无可信年龄事件、重连快照、事件重传 | 不补changed；旧事件不伪成采样；固定event去重及失步暂停 |
| OB15 | 反馈循环／事件洪泛／查询预算耗尽 | 有界暂停；P1预算不被遥测挤掉；不把超时判成功 |
| OB16 | 原生GUI插入改场景，视觉黑场或音频异常 | 记录外部竞态；协议成功不等于视觉／声音验收通过 |
| AU01 | 模拟独立optional明确失败 | proof当前、资源clear、门控合格才继续；摘要completed_with_failures |
| AU02 | 后继引用失败步结果／守卫／控制分支 | 生成器拒绝独立；解释具体依赖边 |
| AU03 | 隐式资源别名、父子路径、写写冲突 | 即使depends_on为空也拒绝 |
| AU04 | 动态脚本、缺足迹、不完整闭包 | unknown而非独立；发布不得接受自报proof |
| AU05 | 定义／模块／目录／证明生成器更改 | proof失效并暂停；显示改名不误改行为身份 |
| AU06 | optional unknown／expired／blocked／撤权／存储故障 | 全部停止；不套用明确业务失败策略 |
| AU07 | 转换或并行配置optional＋continue | 配置拒绝；必需失败不提交目标状态 |
| AU08 | 并行一个成功、一个失败、一个在途、一个未发 | 保留成功／在途，阻止未发；无自动回滚和重放 |
| AU09 | 同预览两客户端不同键并发 | 一个CAS赢家、一个409；一个execution，最多一次首次派发 |
| AU10 | 赢家响应丢失同键同内容／同键异内容 | 前者原operation，后者409；权限撤销后不泄露结果或再执行 |
| AU11 | 预览到期／服务重启／请求世代变化／摘要被改 | 拒绝消费，旧计划不复活 |
| AU12 | 预览后接管／撤销／目录／证据版本变化 | R2/R3/最终发送分别复核；记录传播窗口及未发／在途边界 |
| AU13 | 部分Controller准备成功后超时 | 无设备写，核对撤销结果；preview保持已消费；新恢复须显式 |
| AU14 | R2提交前后崩溃、R3运行前后崩溃 | 持久化身份可核对、默认暂停；旧intent不复投 |
| AU15 | 步骤成功但Seamer未存／R5提交不确定 | 按原身份查证；已成功不重跑；只允许明确reconcile_commit |
| AU16 | R5已提交但event未发布 | 同event_id重传；目标state和设备执行各一次 |
| AU17 | 现场业务state已改、源state CAS冲突 | 不覆盖现场；需要新预览或独立校正审计 |
| AU18 | unknown后迟到证据／资源仍占用 | 终态不改；无资源释放证明不恢复；resolution不自动布防 |
| AU19 | 已过排期、授权或动作预算 | 不延期、不以新key偷补场次；新手动计划独立授权 |
| AU20 | 证明生成超时／图或资源数量超预算 | 发布／预检失败有解释；不降级为空依赖；既有运行保持固定版本 |

## 7. 交付状态与剩余门槛

本轮交付：候选字段／结构、人工正反例、同会话证据与依赖闭包的有限判定向量、恢复消费的串行交错模型、OB01—OB16／AU01—AU20 运行验收规范。离线报告见[validation-report.json](contracts/f06-f07/validation-report.json)，不等于真正并发或故障测试。

实施前仍须：归并公共下一版与内部守卫协议；固定 OBS 产物及内嵌源码、客户端库与实际请求表；实现并审阅权威足迹生成器和有限DSL；冻结发布预算与清资源策略；准备两平台 OBS／IPC／SQLite／身份／NTP 联合故障测试。全量18个旧bundle、其余厂商和NodeCG兼容仍按路线图交付，首闭环不代替它们。
