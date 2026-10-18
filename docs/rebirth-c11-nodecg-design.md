# C11：NodeCG 桥接、旧图文与编辑器兼容

日期：2026-10-17。状态：**NG01—NG07为待审阅推荐**，承接已确认Q26／Q28／Q71及C09候选。本文只完成NodeCG子专题，不表示全部设备型号的C11设计已关闭。未改业务代码、draft.4或IPC 0.3；未安装、运行NodeCG或操作真实播出设备。

责任：Controller仓库交付本地适配模块、远端桥bundle、旧图文兼容资产与编辑入口；SDK定义版本化映射、桥协议及证据；Seamer负责排期草稿／发布；GUI提供控制、状态与外部入口；Suite固定组合及部署验收，无第六仓。本文候选依赖[C09](rebirth-c09-extension-design.md)、[C05](rebirth-c05-event-sync-design.md)和[C06](rebirth-c06-schedule-design.md)，未将它们自动视为已确认。

## 1. 已知事实与工程分析

官方固定源码：NodeCG tag `nodecg-v2.8.0`对应提交`29d70b39f514d1649b27c8d0ca2281f07b63e7bd`。以下是静态核查，不是运行复现；2.8.0仍只是兼容验证候选。

| 已知事实 | 官方来源与设计影响 |
| --- | --- |
| Replicant revision在新实例从0开始；持久恢复value不恢复该revision；初次监听可立即得到当前值 | [共享实现](https://github.com/nodecg/nodecg/blob/29d70b39f514d1649b27c8d0ca2281f07b63e7bd/workspaces/nodecg/src/shared/replicants.shared.ts#L76)。不能作为持久事件游标或证明发生了新变化。 |
| revision/schemaSum不匹配分支调用错误回调后没有return，随后仍调用applyOperations | [replicator.ts](https://github.com/nodecg/nodecg/blob/29d70b39f514d1649b27c8d0ca2281f07b63e7bd/workspaces/nodecg/src/server/replicant/replicator.ts#L239)。不能依靠原revision实现可靠CAS；不推断所有输入都一定完成写入。 |
| 持久保存由change异步节流触发，保存错误被捕获记录；已声明的同名Replicant直接复用 | [声明与保存](https://github.com/nodecg/nodecg/blob/29d70b39f514d1649b27c8d0ca2281f07b63e7bd/workspaces/nodecg/src/server/replicant/replicator.ts#L72)。change／赋值返回不证明落盘，后声明options不能覆盖已有配置。 |
| 客户端消息Promise等待扩展主动ack；服务端消息API不提供同等完成Promise | [客户端API](https://github.com/nodecg/nodecg/blob/29d70b39f514d1649b27c8d0ca2281f07b63e7bd/workspaces/nodecg/src/client/api/api.client.ts#L83)、[服务端API](https://github.com/nodecg/nodecg/blob/29d70b39f514d1649b27c8d0ca2281f07b63e7bd/workspaces/nodecg/src/server/api.server.ts#L344)。ack不证明持久化、渲染或播出。 |
| NodeCG认证可接受自身session/key；关闭login时authCheck放行 | [authcheck](https://github.com/nodecg/nodecg/blob/29d70b39f514d1649b27c8d0ca2281f07b63e7bd/workspaces/nodecg/src/server/util/authcheck.ts#L8)。它不是LeafSeamer的逐动作授权器，不能把其浏览器key当只读输出凭据。 |

旧源码事实见[GR01—GR05](rebirth-legacy-system-map.md#2-nodecg图文实际范围)与[LS映射](rebirth-legacy-schedule-map.md)。三路渲染器分别读取`graphics-package/graphicsData`及`schedule-manager/scheduleData`；排期只按active过滤，不检查是否未来，字幕仅visible改变重启动画。保留namespace及字段可复用渲染代码，但实际兼容尚待浏览器验证。

工程分析：原Replicant提供共享状态，不提供LeafSeamer所需的命令账本、接管或持久事件语义。推荐桥采用独立请求身份、串行写临界区与有界收据；远端桥是设备协议端点，不能冒充本地受监督writer。NodeCG版本的已知CAS缺口须纳入固定组合发布阻断，不能以“我们不使用revision”替代对原编辑器路径的验收。

## 2. NG01：交付组合及单一映射权威

交付分为本地`nodecg-controller-adapter`、远端`leafseamer-nodecg-bridge`、保留原bundle身份的渲染资产与编辑兼容层。名称为候选逻辑组件名，不创建新仓。兼容资产保留原来源路径、提交、MIT及第三方许可；新的桥代码按新版许可。不能仅复制原完整18-bundle运行目录，导致旧Seamer、ScheduleService到期定时器、外部采集器或旧数据库适配器重新启动。

`NodeCGMapping`候选字段：`mapping_id/revision/digest`、`artifact_ref`、`nodecg_release_ref`、`target_bundle`、`replicant_name`、`field_schema_ref`、`direction`、`action_ids`、`resource_footprint`、`completion_policy_ref`、`editor_mode`、`persistence_profile_ref`、`limits_profile_ref`。对象不可变，摘要沿DF01固定投影；安装与目录批准按ME01／ME04另做，不以hash自授权限。

首期方向限定`output_projection|device_control|draft_input|state_observation`，每条映射只承担一种用途。相同Replicant不同方向必须显式列出关联和冲突，不默许双向镜像。默认拒绝任意bundle、messageName、Replicant名或JSON pointer通用写接口；新增第三方图文须提交固定映射和验收。

同一NodeCG实例作为首期整设备接管单位；字幕、比分、排期声明子资源用于依赖证明，暂不据此缩小Q35接管范围。整体`graphicsData`替换会影响两个分支，footprint必须包含两者；只改一个分支也须在临界区读取并保留当前另一分支，不能用旧客户端快照覆盖。映射或部署组合改变使旧批准及待发许可失效，既有在途继续核对。

## 3. NG02：桥会话、唯一出口与远端故障

候选协议`nodecg-bridge/0.1.0-draft.1`，与本地IPC分开版本化。桥使用专用受限身份与mTLS，绑定批准的Controller服务、NodeCG实例及映射；不接受NodeCG登录cookie充当LeafSeamer服务身份。HTTP升级路径和反向代理固定于C12部署profile，禁止公开未鉴权业务WS。

| 消息／对象 | 必需字段及边界 |
| --- | --- |
| HELLO／WELCOME | protocol_version、controller_service_id、bridge_instance_id、bridge_boot_id、connection_generation、mapping_ref、approved_artifact_ref、features、limits_profile_ref；服务身份从验证过的连接派生 |
| EXECUTE | 当前会话引用、sequence、command_id、attempt_id、content_digest、mapping_ref、action_id、parameters、expected_target_digest及必要projection_binding；不得携带任意JS或目标路径 |
| RECEIPT | 同一请求身份、phase=`accepted|applied|rejected_before_apply|outcome_unavailable`、reason_code、实际post_state_digest及可用观察引用；它是桥协议阶段，不直接替代公共命令状态 |
| QUERY_RECEIPT | 原boot／generation／sequence／command／digest，允许读取保留的旧会话收据；只读查询不重新执行 |
| CLOSE_GENERATION／CLOSED | 指定旧连接代、最后消费sequence、未消费已失效确认、仍可能执行的任务清单；后者非空则不得证明远端排空 |
| OBSERVATION | C05来源namespace／epoch／sequence、mapping_ref、state、实际采集身份、cause=`bridge_write|external_or_unknown`；cause=bridge_write还需唯一关联收据 |

所有数字身份使用DF01规范十进制字符串，帧关闭未知字段、拒重复键，参数二次校验；ACK、查询和观察不得包含秘密或管理token。sequence在单连接内从1连续递增，不等同NodeCG revision；分配及发送串行，消费floor在当前bridge boot内保留，缓存淘汰不降低floor。旧sequence只能返回原收据或outcome_unavailable，不能重新执行；不同digest复用身份是协议错误。遇缺号、身份冲突或发送结果不明关闭该连接代，不自动跳号或重放来修复。

每个bridge实例只绑定一个已批准Controller权威，并只允许一个当前写连接。新连接不能凭HELLO抢占旧连接；换代须先关闭旧代并完成排空判定，未完成时保持只读／保护关闭。connection_generation由桥在同boot内单调分配，保存最高代并永久拒绝较低代执行，不靠无限保存全部会话；收据有界淘汰后仅降低可恢复证据，不扩大执行权限。

本地适配器全部业务写经过F02唯一出口及T1—T6。桥不维护可重放的持久命令队列；volatile inbox有界，满时在应用前拒绝。进入桥执行临界区后，验证会话、批准、sequence、当前目标摘要，消费身份并同步完成单个受支持Replicant写，不跨await、timer或外部任务。当前映射若无法满足这个约束，不得注册该完成政策，须另定义远端在途／排空能力。

桥在接收关闭／换代后使尚未消费的旧回调失效；同一事件循环的串行CLOSED处理确认之前同步临界区已结束，不能撤销已经赋值的状态。桥boot更换后拒绝全部旧boot帧，重新建立baseline；旧收据丢失只表示结果未知。新连接不得重新封装旧command执行。Controller的持久账本负责跨重启命令去重，桥receipt只是辅助证据，不标durable=true。

**接管边界**：Controller发送闸关闭可以证明后续未发送，但已进入网络传输的旧帧仍可能稍后在NodeCG应用。它们必须列为in_flight／unknown，不能因本地worker退出就标not_sent。只有远端代关闭／原进程终止等可信证据证明不再有后续apply，且目标按专属政策核对，才可释放冲突资源；新连接读到相同值本身不够。手动effective与ready继续分离，不以接管成功掩盖未清的远端写。

Q60时间窗约束开始协议发送，不保证远端应用或浏览器显示时刻。桥不能拿自己的接收UTC或任意TTL重新给过期命令授权，也不比较两主机单调tick。需要按画面时刻执行的未来功能单独列路线图；本期不宣称帧级播出定时。

## 4. NG03：原编辑器、并发写与回流

保留原图文编辑能力和外部入口。推荐提供两个明确的部署模式，模式不是可以静默切换的运行按钮：

| 模式 | 写入与并发边界 |
| --- | --- |
| `managed_bridge` | 默认桥独占已映射Replicant的服务端业务写；兼容编辑器保留原两行文字、显隐及比分控件，只替换写入适配层，提交具名Controller命令。编辑者使用独立LeafSeamer身份及权限，不能由NodeCG超级用户身份代授。原未适配写处理器停用。 |
| `external_editor` | 保留原生编辑器直写用于兼容；明确标为外部控制，Controller无法阻止后续覆盖。检测到外部／无法归因的变更按C04暂停受影响运行、保留手动状态，不自动修正现场；依赖独占写或可靠外部变化检测的自动化不获批准。 |

managed_bridge不是靠移除一个页面就获得安全隔离。必须验证目标NodeCG profile阻止原生客户端、旧bundle和其他socket凭据绕桥写入；不能证明时只能按external_editor能力发布，不能宣称独占。原生NodeCG key不能交给被当作只读的输出浏览器。用户仍可使用原编辑器的功能，不以“禁用全部原编辑器”冒充兼容交付。

编辑器适配层的授权通过可信LeafSeamer登录／批准流程建立短期、用户绑定、特定NodeCG实例与具名action范围的委托，服务端按C09权限交集验证；不把管理员cookie写进iframe、URL或NodeCG存储。[C10 UI06](rebirth-c10-gui-design.md)推荐将保留原控件的兼容编辑器显式打包批准为C09面板，由GUI启动页完成登录、PanelSession及精确origin／port握手；读写均经宿主代理，不能加载原生高权限NodeCG socket上下文。原dashboard仍独立外部登录，任意旧页面不会自动获得面板资格。此路径待审阅；C12须固定origin／TLS／输出访问与独占写组合并做负向验收，本候选不宣称已实现。

写前比较使用桥自己的`projection_revision`与当前完整目标值digest；同一个同步临界区内比较、构造新值、赋值及后读。失败返回rejected_before_apply，不覆盖现场。此CAS只保障本桥当前临界区，不能锁住其他原生客户端、跨Replicant事务或浏览器输出。原生revision仅作诊断。外部A→B→A即使终值相同也不能推断没有外部变化；需要跨时间排他时必须依赖已验证managed模式，而非值hash。

输出投影带`projection_id/revision`和来源发布引用，旧投影拒绝；相同ID／revision且digest相同只查询或返回已有结果，不重新播动画。无因果标记的change为external_or_unknown，不能因“值等于我刚发送的值”无条件丢掉。只有绑定同请求的桥收据和受控同步写观察可归为bridge_write；不得将随后NodeCG异步change自动套用该原因。

桥重启后的投影下界由Controller持久记录与当前批准的重建握手提供，不能从NodeCG旧持久value推导。握手只安装当前投影身份和核对基线，不自动写画面；需要恢复显示时生成新的、经授权的绝对投影命令，原旧命令仍保持其历史结果。投影下界无法证明则不接受写请求。

初始监听、重连、NodeCG持久值恢复均为baseline/reconcile，不触发离散业务事件或自动重布防。状态采样与明确操作事件分开，原Replicant不充当可靠事件日志。回流不反向生成同一输出写命令；确需自动化监听时在C04因果／预算图中显式建边，不能隐藏反馈循环。

## 5. NG04：三路旧图文与排期编辑映射

| 旧能力 | 候选具名动作及输入 | 完成谓词／保留行为 |
| --- | --- | --- |
| 两行字幕文字 | `lower_third.content.set`：line1、line2字符串 | graphicsData.lowerThird对应字段相等，保留visible；文字改变不主动重播动画 |
| 字幕显隐 | `lower_third.visibility.set`：visible布尔 | 对应visible相等；不证明GSAP动画已结束 |
| 主客分数直接设置 | `scoreboard.scores.set`：homeScore、awayScore非负安全整数 | 两个分数相等，保留visible；HOME/AWAY标签不新增成原有队名编辑 |
| 原±1按钮 | `scoreboard.score.adjust`：side=`home|away`、delta仅−1或1 | 同步读取当前分数后计算max(0,current+delta)，记录before/after；非幂等操作，不自动重试 |
| 比分显隐 | `scoreboard.visibility.set`：visible布尔 | 对应visible相等，保留分数 |
| 排期画面 | `schedule.display.project`：projection_binding、完整items数组 | schedule-manager/scheduleData目标摘要相等；保留1920×1080及active/time/title/description展示逻辑 |

items至少固定`id:string`、`active:boolean`、`time:string`、`title:string`、`description:string`；time是显示文字，不推导plannedAt、时区或到期触发。当前集合由已批准投影策略决定，默认保留旧active显示语义，不擅自只显示未来条目。排期执行状态和播出投影状态分别展示；未投影不表示排期未发布，投影成功不表示场次已执行。

推荐实验上限`sim-ng-v1`：每行字幕4096 UTF-8字节、显示字段各4096字节、最多1000显示项、映射请求总量1 MiB、每连接inbox最多64条、每boot保留收据最多4096条。分数上限由映射profile明确且不超过2^53−1；以上仅故障夹具预算，不是旧代码限制或生产批准。容量不足明确拒绝，不截断字幕、裁掉尾部排期或丢掉得分操作；字节／行数及浏览器实际容量在固定组合验收后冻结。

旧排期编辑器保留本地新增、编辑、删除及外部来源只读语义，但编辑写入Seamer草稿API，不直接替换已发布排期，也不由scheduleData change反推激活。适配器提交C06的草稿expected_revision、来源引用和条目，冲突显示给操作者；保存、验证、发布和显示投影各有状态。原本地time不能暗自生成plannedAt。Seamer不可用时排期编辑显式不可用；独立Controller仍可控制现有图文，不启动旧ScheduleService替代Seamer。

## 6. NG05：证据、持久化与重启恢复

| 公共事实／结果 | NodeCG映射所需证据 |
| --- | --- |
| sent | Controller实际跨最终发送边界；收到桥请求之前也可能已sent |
| acknowledged | 经认证的当前桥收据绑定command／attempt／mapping；若是目标bundle自有消息ACK须另列映射，不混称为已应用 |
| effect_verified | 明确桥apply收据＋同一有效会话下应用后实际目标读取满足谓词，Controller核验并可靠落账；不能只用本地desired、缓存或无关联change |
| rejected_before_apply | 桥证明本请求在应用前拒绝；Controller已sent的attempt不得回改为not_sent，是否failed及可重试依据专属政策 |
| unknown | 发送后断线／崩溃／收据丢失且无法形成充分证据；终态保留，仅追加核对，不偷偷重发 |

完成证据候选`NodeCGCompletionBundle`含请求及会话引用、mapping_ref、apply_receipt_ref、post_read_ref、before/after digest、controller_capture_ref和完成policy_ref。桥自己的tick只用于同桥内部顺序，不能与Controller tick相减；采样年龄沿DF06因果采样或双方合格UTC证据。真实权限及来源由受信连接和批准记录证明，不靠字段自报。

effect_verified只表示映射目标在读取时满足条件，不证明后续保持、NodeCG持久化成功、动画结束、OBS浏览器源加载或观众收到像素。renderer观测可作独立诊断／验收证据，未形成新政策前不增加公共completion枚举或改写succeeded含义。

NodeCG的Replicant持久化作为自身恢复机制单独配置；桥不依赖它存命令许可。启动先检查schema、已有声明options、资产和唯一写者，缺失／冲突则闭闸。旧持久图文值只作为待核对现场值：不默认清屏、不自动重放Controller旧desired，不因重启恢复value就生成业务触发。重启可能在完成收据后恢复较早画面，必须纳入验收与GUI警示，不承诺瞬时画面保持。

对于相对比分调整，丢收据后“当前分数正好加1”仍不足以证明本请求执行或没有后续待apply；先取得旧代排空证据，结合人工核对和专属释放政策处理unknown，再由操作者决定新的绝对设置命令。恢复不改原unknown，不重用原command，也不自动减1补偿。

## 7. NG06：部署、认证及版本冻结门槛

推荐固定组合记录NodeCG commit／发布制品digest、Node版本及依赖锁、bridge／renderer／editor制品、namespace配置、持久后端、认证／代理／浏览器profile、映射与测试报告。2.8.0的revision拒绝分支缺口先保留为已知静态阻断：选择经修复并验证的固定2.x组合，或明确维护来源可追溯的补丁制品并完整验收；本轮不修改NodeCG、不安装补丁、不承诺任意2.x兼容。

输出URL只标识画面，不含LeafSeamer管理token或NodeCG高权限key。[C12 DEP05](rebirth-c12-deployment-design.md)推荐桥bundle独立只读listener、固定三路资产与有限Replicant读取兼容层，保留旧渲染；分别提供private_render_network与显式public_projection。原端口／Socket.IO不暴露给输出，任意bundle不自动兼容；Nginx只负责TLS及路由，不授逐动作权限。该具体profile待审阅及负向／视觉验收，未通过不开放；不把“OBS需要访问”当成公开管理socket的理由。

本地运行域终止不证明远端NodeCG、输出浏览器或已播画面终止。远端进程崩溃、权限撤销、桥断开时，GUI应区分“控制不可用”“最后已知值”“画面状态未知”；保护关闭阻止新写，不自动隐藏当前播出内容。NodeCG是可选部署，但启用后的三路旧图文、编辑器与浏览器源均属必须验收范围。

## 8. NG07：故障时序与验收

时序A：Controller持久intent→发送→网络延迟→本地接管屏障→旧帧在桥apply。预期接管可effective但冲突资源未ready，迟到结果按原attempt登记，手动写不越过unknown；不能把本地屏障之后的远端apply判为“系统没有发送”。

时序B：比分调整消费sequence→赋值→桥崩溃→无receipt→新boot恢复较早持久value。预期原命令unknown、关闭自动化、新baseline只核对，不能自动重发加1或依据重启值判未执行。

时序C：桥写前摘要匹配→同步赋值／后读→原编辑器后来覆盖。前者证据只证明当时效果；后者独立外部变化，暂停依赖，不改写历史完成、不自动恢复目标。若原编辑先写，桥前置digest不符应在应用前拒绝。

时序D：Seamer草稿保存→验证／发布→投影请求排队→映射撤销。排期发布保持其事实，未发投影取消；已发投影按桥在途核对，不能用显示失败回滚发布，也不能用发布成功显示“画面完成”。

以下NGT01—NGT32均为**未运行**用例，需记录固定组合、原始证据、期望和实际结果；静态文档检查不算通过。

| ID | 正／反例与通过判据 |
| --- | --- |
| NGT01 | 三路原渲染器正确加载，字段／namespace精确匹配；错误namespace不得静默显示旧值为成功 |
| NGT02 | 文字更新不重播字幕动画；显隐变化保持原动画；比分及排期画布尺寸保留 |
| NGT03 | 原编辑器文字、显隐、±1与零下限可用；上限／非法值有明确拒绝，无静默截断 |
| NGT04 | 排期本地可编辑、外部只读，保存仅草稿；time文本不产生plannedAt |
| NGT05 | active过去项仍按旧策略显示；展示不误代表未来场次或执行结果 |
| NGT06 | 原ScheduleService定时器／旧Seamer未启动；第三方同目标写者使managed资格失败 |
| NGT07 | 错误证书／Controller／bridge／mapping身份拒绝，无副作用 |
| NGT08 | 同seq同digest重送只返收据；不同digest拒绝；缓存淘汰后不重新执行 |
| NGT09 | sequence缺号、旧代帧和旧boot帧拒绝；重连不自动重新封装旧命令 |
| NGT10 | inbox满／帧超限明确拒绝；关闭／撤销通道保留容量且无隐藏timer |
| NGT11 | CAS摘要匹配正常写；原编辑先写导致冲突，不覆盖另一graphicsData分支 |
| NGT12 | 原生revision/schemaSum拒绝后不得仍修改状态；固定发布组合必须验证已修复或受控隔离 |
| NGT13 | 初始change、重连和旧持久value只reconcile，不生成新触发 |
| NGT14 | 相同目标值但外部原因不可伪造bridge_write；A→B→A不被当排他证明 |
| NGT15 | bridge_write回流不形成无限动作环；显式业务监听受C04因果及容量限制 |
| NGT16 | 收到accepted后桥崩溃，Controller不标effect_verified／durable／rendered |
| NGT17 | apply及后读有效、Controller可靠落账后记录效果；错会话／过期读不得升级完成 |
| NGT18 | 时序A延迟网络包跨接管，完整覆盖在途，manual ready不得提前 |
| NGT19 | 时序B相对比分崩溃，原unknown保留，无自动加1、减1或旧命令重放 |
| NGT20 | CLOSED确认所有旧回调失效；残留异步任务必须阻止排空证明 |
| NGT21 | 仅本地worker退出或新连接读到相同值，不释放远端未知资源 |
| NGT22 | 旧NodeCG持久化写失败／节流未落盘，change不声称durable；重启旧画面显式核对 |
| NGT23 | schema缺失、声明顺序错误或options冲突启动闭闸，不用后声明假装修复 |
| NGT24 | 外部编辑器覆盖触发受影响自动化暂停，不自动纠正现场或释放手动接管 |
| NGT25 | managed编辑者权限撤销使未发失效，NodeCG超级用户不能替代LeafSeamer授权 |
| NGT26 | 输出页／OBS浏览器源不能凭画面URL调用管理写；URL及日志无管理token |
| NGT27 | 跨源伪Origin、CSRF、委托错用户／错实例拒绝，外部入口不共享GUI管理会话 |
| NGT28 | NodeCG断线时画面与控制状态分别显示；不自动清屏或恢复布防 |
| NGT29 | Q60截止前发送但截止后apply，只记录实际时序，不宣称按时播出或重新授权 |
| NGT30 | 时序D发布与投影失败分离，草稿冲突不覆盖新版本；旧projection拒绝 |
| NGT31 | Controller独立运行时字幕／比分可控；Seamer不可用不启动旧排期自动化 |
| NGT32 | 固定Windows／Linux组合分别验证编辑器、输出浏览器和OBS源刷新／重连；任一路未验不借用其他结果 |

冻结退出条件：NG及C10／C12候选审阅；三个部署组件及编辑器的精确资产／许可、Schema及初始化所有权明确；桥收据／代关闭与公共attempt／资源证据成套归并；编辑授权、输出访问与固定组合的机器模型及NGT夹具齐备。C10／C12已有具体候选，仍未冻结；真实运行验收在实现后执行，不要求尚未存在的业务代码先通过。当前C11设备逐型号政策、工具链及全系统归并仍是设计待办。
