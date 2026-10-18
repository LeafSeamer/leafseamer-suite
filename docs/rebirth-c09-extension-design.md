# C09：模块生命周期、扩展授权与面板委托

日期：2026-10-17。状态：**ME01—ME07为待审阅推荐**。依据已确认Q35／Q53／Q54／Q65／Q66，衔接F02—F07、DF01—DF06及C04—C06候选。本文只补系统设计，不改业务代码或既有draft.4／IPC 0.3；安装、运行与真实设备验收均未执行。

责任：SDK维护manifest、模块接口、候选证据和面板消息；Controller管理设备模块、唯一写出口、目录批准及设备操作；Seamer管理数据源扩展及规则；GUI承载受限面板代理；Suite固定制品、平台组合、安装维护与验收。Controller独立运行时保留完整手动控制，不依赖Seamer取得控制权。

## 1. 已知事实与分析

已知机器事实：[draft.4模型库](contracts/draft4/first-loop.schema.json)已有CapabilityCatalog、DeviceDescriptor、ActionDescriptor、TriggerDescriptor、EffectFootprint及完成证据。动作声明参数／结果Schema、资源、取消／重试、完成策略、平台和依赖；触发器声明采样／离散、年龄与因果能力。当前没有扩展安装审批、权限修订、面板会话或具体模块生命周期的完整机器模型。DeviceDescriptor.connection_state的ready不能独自证明目录已批准、未知动作已核对或写闸已开放。

已确认信任边界：后台扩展是管理员明确信任的代码，独立进程主要隔离故障；SDK权限声明不能宣称实现恶意代码沙箱。安装批准不授予用户动作权限，模块自报footprint.complete也不证明足迹完整。具体依据见[设计稿Q53／Q66](rebirth-design.md#6-controller接管与模块隔离)、[Q65面板约束](rebirth-review.md)及[DF02运行域](rebirth-df02-runtime-design.md)。

工程分析：模块版本、型号固件、连接配置、能力目录和权限各有不同寿命；仅保存module_id/version不能证明当前运行的字节或批准范围。下一版需显式绑定这些对象，避免“换个插件文件但沿用旧审批”“目录里出现动作即自动可写”以及“面板借宿主身份代用户越权”。

本轮旧源码证据见[设备8模块映射](rebirth-legacy-device-map.md)及[自动化／图文等5模块映射](rebirth-legacy-system-map.md)。例如ATEM定时AUTO、WING两步patch及VB多点preset均要求明确复合写；OBS断线投影false、Mixer/VB乐观状态不能直接作为设备事实。这里只登记设计依据，未将静态问题描述成已复现事故。

## 2. ME01：不可变制品与逐安装审批

| 候选对象 | 关键字段及不变量 |
| --- | --- |
| ExtensionManifest | manifest_version、extension_id/version、kind=`device_module|data_source|panel|nodecg_bridge`、artifact_ref、publisher/source_ref、license_refs、dependency_lock_ref、SDK/IPC兼容范围、平台组合、entrypoints、requested_permissions、初始化和传输声明 |
| ArtifactRef | DF05发布清单及对象digest；包含完整依赖、原生辅助程序和静态面板资源，不接受可变latest URL作固定产物 |
| PermissionRequest | device selectors、data objects、允许网络目标与用途、secret roles、文件／辅助进程需求、privilege_requirement及说明；不将通配设备默认为全部 |
| InstallationApproval | approval_id/revision、authority、manifest_digest、固定artifact digest集合、批准权限子集、approved_by、审批记录、状态；升级／权限扩大须新审批 |
| InstallationRecord | installation_id、extension_id、当前批准引用、installation_revision、stage、依赖与实际落地制品核验记录 |
| RuntimeBinding | installation_id/revision、approval_revision、member_boot_id/domain、模块产物、配置revision、授权设备集合、secret授予引用、catalog approval及保护状态 |

安装状态推荐`staged → verified → approved → installed_disabled → activating → active`；任一步可rejected/failed，active可进入maintenance/revoking/disabled/removed。staged只将字节置于隔离缓存并静态检查，不执行包脚本、加载动态库、连接设备或调用模块“自检”。verified仅证明文件／依赖／来源检查完成；approved才允许在批准环境进入受监督启动，仍默认闭闸。

产物清单不得包含任意安装命令行、自动在线解析依赖或后装脚本；需要原生厂商组件时作为明确独立依赖和权限审批项，沿DF05离线固定组合。签名与hash支持来源／一致性核验，不证明模块安全。回退到旧产物也须满足当前信任／撤销下界，不恢复旧审批或旧运行许可。

同名不同字节不能覆盖已安装版本；允许保存多个不可变版本，但同设备只准一个当前writer绑定。磁盘文件替换与DB审批提交不是一个原子事务，安装operation记录阶段并按制品hash恢复；结果不确定时不启动“可能是新版本”的进程。

## 3. ME02：启动、连接、采样与可写分离

推荐设备生命周期：`disabled → launching → admitted_closed → connecting_readonly → baseline_pending → reconciled_closed → ready_for_manual`。自动化另需Seamer预检／布防和Controller当前grant／guard，不能让设备ready自动恢复自动化。故障进`faulted_closed`，维护进`maintenance_closed`，旧身份退出可证后才建立新worker/session；恢复沿DF02与F02的完整账本路径。

| SDK接口候选 | 可做与禁止事项 |
| --- | --- |
| describeStatic(manifest) | 读取包内固定Schema／能力模板；不能动态联网补代码或在模块加载时写设备 |
| connectReadOnly(binding) | 批准的认证、发现、订阅和读请求；若连接会恢复预设／接管设备或改变输出，必须声明为写副作用，不得自动重启 |
| captureBaseline(request) | 固定来源身份／会话的新样本，按DF06返回候选证据；缓存值不伪装新采样 |
| proposeCatalog(observedIdentity) | 根据实际型号／固件／目录提议能力，宿主验证后另发CatalogApproval；不能自赋执行权限 |
| prepareAction(fixedInput) | 有界纯计划／编码，返回参数、前提、足迹及有限写计划；不持有隐式写连接，不启动计时器写设备 |
| executeAuthorizedPrimitive(permit) | 仅通过SDK DeviceWriteGate提交批准传输；不是让模块获得可任意调用的公共socket句柄 |
| onProtocolFrame(frame) | 产生固定会话的候选状态／证据，宿主验证持久化；不自填durable或自行提交Seamer业务状态 |
| stopReadOnly() | 取消采样和断开连接；关闭连接若会改变设备行为也须显式声明，不能标为无副作用清理 |

“只读”指没有本项目定义的设备控制效果，不等于不发送任何协议字节。认证、keepalive、查询、ACK及订阅也须列入批准的ProtocolIOPolicy：协议类型、合法帧、目标、预算和副作用分析。未分类字节不准发送。若订阅占用设备独占控制、心跳维持持续动作或连接退出会静音，它们属于控制／持续效果，不能藏在read polling中。

一个模块进程可管理同类多设备，保持每设备独立写闸及账本；worker崩溃时所承载设备一并保护，不能声称每设备完全故障隔离。动态扩设备集合须新RuntimeBinding与审批范围核对，不能在原LaunchIntent中原地加ID。配置身份、端点、凭据、协议或型号选择改变需维护并重建session／目录；仅显示名称改变不重建设备身份。

nodecg_bridge类型不把远端NodeCG服务器纳入本地Job/cgroup证明：本地Controller适配进程按DF02纳管，独立NodeCG bundle按C11配对／授权。停止本地worker不能证明远端图文、外部编辑器或厂商daemon已经退出／停止输出；各自运行域和在途事实必须分开。

Seamer数据源扩展采用具名SourceRuntimeBinding，绑定source_id、固定查询／映射、capture policy、批准外连／secret范围和provider epoch，不伪造device_id来套设备许可。启动与重启仍受DF02监督；采集只能提交C06导入快照或经独立批准的C05观察来源，不能调用设备写入口、发布草稿或自行布防。数据源断连／重启使来源失步并撤旧年龄证据，抓取恢复不自动补事件。SourceRuntimeBinding须与下一版LaunchIntent的具名对象范围一起归并，当前只含device_ids的旧候选不能被解释成已经覆盖全部数据源授权。

物理设备身份候选DeviceIdentityBinding含authority、logical_device_id、协议端点、可证明的厂商稳定标识或人工核对记录、别名集合及owner registration。名字/IP不足以证明物理唯一；不能自动发现就新建第二writer，端点改变先核对原设备。跨Controller双写的部署注册／接替仍沿F02单所有者约束，数据库唯一键不能证明另一服务器没有连接设备。

## 4. ME03：唯一出口、协议重传与复合动作

F02的边界不变：同设备屏障、许可消费与进入传输层串行排序。下一版要求每种具体协议给出TransportAdmissionProfile，绑定库／原生组件版本、全部写入口、内部队列、重传、重连回调、定时器及取消证明。单纯包装顶层方法不能证明后续异步flush仍受控。

- 主动控制帧必须有当前有效permit，校验完整动作／参数／session／批准目录与守卫；进入传输前复核期限和权限。FENCE后丢弃未消费许可及尚未提交的应用重发。
- TCP等底层已接收字节可能在屏障之后继续传送，这属于已登记in_flight；不能因为之后关闭socket就改成not_sent。库自己的新业务重试／重连恢复不等同底层可靠传输，必须重新经出口，默认禁止自动重发设备动作。
- 单个协议事务的多个帧须固定为有界传输计划，清楚标明每帧进入传输的证据及取消边界；任何部分提交后不能把整个动作报告为未发送。后置只读核对可按批准策略继续，不得附带“纠正到目标”的写入。
- 厂商库无法关闭／纳管控制重试，或无法判断内部队列是否还可能写入时，该组合不能获准可写profile。保留该功能的实现任务，审阅库或改写协议适配后再验收，不能把功能悄悄删去。

对本地渐变、批量路由、跨多个协议写调用的“一个按钮”，推荐显式Controller DeviceOperationPlan：operation_id、根action/version、计划digest、有限primitive列表／顺序、参数／资源／前提、各子命令身份与截止。根是可查询operation，子项各走现有T1—T6命令／许可，不循环复用一次permit。Controller独立运行也能执行这种已批准有限操作；它不是可任意脚本化的第二个Seamer。

计划在受理时固定最大项数和预算；依赖前项结果的后继仅按明确类型化分支选择，不允许无限循环或重新采目标补齐。首期不承诺多设备原子批量，失败／接管停止未发后继并保留已发生效果；同一原生设备macro只有一次启动写时，则作为一个可能持续的设备动作，仍不能据启动ACK声称macro完成或可取消。UI展示根operation、子命令和部分完成／未知，不能只有一个绿勾。

复合操作是下一版新增模型/API，当前CommandRequest／IPC不能被默认为已支持隐式子命令。根幂等身份只创建一次固定计划，响应丢失查询原operation，不重新生成子命令；执行中崩溃不自动续跑。具体旧渐变／macro／batch参数与完成政策由C11逐能力映射冻结。

## 5. ME04：能力提议不等于能力批准

候选CatalogApproval绑定installation/runtime、device_identity、model/firmware/protocol版本、capability_catalog_revision/digest、每动作参数／结果Schema、ProtocolIOPolicy、EvidencePolicy、FootprintQualification、平台profile及批准记录。模块只能propose，Controller核对后发布；Seamer注册引用完整来源与revision，不能接收任意进程提交的“我支持这些trigger”。

EvidencePolicy至少固定支持的完成等级、因果关联方法、会话及目录约束、查询／事件新鲜度、谓词、超时、失败类、资源释放／取消证据及不可证明范围。transport提交不升格为设备ACK；ACK不升格为效果；查询看到目标也不证明观众画面或持续保持。F06 OBS四帧policy继续独立保存，不把其证明直接套到ATEM、Mixer或VB Matrix。

FootprintQualification记录审阅来源、批准语义版本、确定的read/write/failure_write/resources及别名规则，绑定模块字节和设备族。未知macro、动态路由或未证明共享资源至少占整设备；无法证明完整时不授予F07 optional继续／并行独立资格。首期人工接管始终整设备，细资源足迹不缩小接管范围。

能力模板保留厂商差异：参数单位、线性／dB、哨兵、通道／总线种类、范围、步进、枚举及动态目录分别建Schema。明确不可用或不支持的能力不伪装成通用最低动作成功；GUI显示缺失原因。默认值若影响设备效果须参与固定参数摘要，不允许模块升级后悄悄补新默认。

外部面板／原生GUI／第三方控制器不受LeafSeamer写闸管理。模块报告可信程度明确的external_change／observation，无法证明来源就unknown因果，不按“与目标相同”冒认为自己的ACK。已知相关前提偏离使依赖自动化暂停，重新观测不自动纠正设备；无外部检测协议时显示实际盲区并限制需要该证明的自动化profile。此限制不禁止独立手动控制，也不声称可以锁住原生硬件操作。

## 6. ME05：秘密、撤销、维护与卸载

秘密通过已认证宿主通道按RuntimeBinding发放最小设备集合；可使用宿主代理完成协议时优先不交付原秘密，需要原秘密的协议只交付对应设备凭据。SecretGrant包含授予者、installation/member/session、secret role/reference、范围及revision；不通过argv、通用环境变量、普通日志或面板传递。进程同用户能否读其他文件属于平台证据，不能把“SDK未提供API”说成操作系统隔离。

撤销操作推荐同一宿主短事务保存拒绝下界、受影响安装／设备／面板／许可集合和operation。提交后停止新调用、关闭相应出口并按F04完整屏障核对，撤销订阅与秘密获取；仅完全确认目标才applied。若关键存储失败，仍允许CLOSE_GATE保护，但不能伪报持久撤销完成。处理顺序不等待浏览器主动关闭。

卸载先显示定义、运行、场次、GUI面板、NodeCG桥及设备依赖；进入maintenance，禁止新计划，处理已受理／在途／unknown，撤销宿主访问、证明旧子组退出后才移除可执行入口。未决证据和审批历史不删；缓存可按保留政策回收。模块已读到的秘密不可收回，必要凭据轮换作为具名后续操作而非虚假撤销证明。

正常升级／回退用新安装修订，旧worker退出及资源核对后新worker从closed开始，依赖自动化解除布防。纯面板卸载只撤面板委托与未发面板请求，不隐式撤销独立组织自动化；后台模块卸载影响其依赖自动化及来源，须暂停，不偷换为健康模块来源。

## 7. ME06：第三方面板通过宿主代理委托

官方事实：HTML要求跨窗口消息核验origin与数据格式，敏感数据不得使用任意targetOrigin；CSP的connect-src限制脚本连接，但不是所有网络行为的完整隔离证明。（来源：[WHATWG消息安全](https://html.spec.whatwg.org/multipage/web-messaging.html#security-postmsg)、[W3C CSP connect-src](https://www.w3.org/TR/CSP3/#directive-connect-src)。）以下部署与委托是本项目候选设计，尚未做浏览器验证。

固定面板产物使用与GUI不同的专属来源；不同安装／版本不能共享可写同源存储，禁止同源代理路径冒充隔离。面板来源无管理员Cookie或服务签发接口；主会话Cookie采用host-only，不设置跨子域Domain。只有明确批准的静态文件可供该来源读取，不允许上传内容和原始设备秘密混在同源目录。

iframe初始候选sandbox仅allow-scripts及必要的allow-same-origin，以保留可核验的独立origin；后者绝不允许与主GUI同源组合。默认无popup、top-navigation、form、download、camera/microphone、USB/serial/MIDI等能力；CSP default-src none，脚本／样式只用固定本地产物，connect-src none，object/base/form/worker默认禁止，frame-ancestors只允许批准GUI。额外媒体及外连需求逐项审阅；需要外部数据时优先通过宿主受限查询代理，不给任意URL代理。

CSP、sandbox和API代理分别验收，不能仅凭iframe存在宣称所有网络外泄已被阻断；frame自身导航等路径需要单列测试。凡安装批准要求硬性零外连而目标浏览器／网络组合不能提供证明，则该面板不获准启用该profile，不能悄悄降级。首期固定受信代码、内容与权限审阅仍不可省略；不声称可以安全执行任意恶意网页。

握手顺序：宿主取得PanelSession→创建精确origin iframe→核验ready消息的event.origin和event.source===iframe.contentWindow、安装digest及一次nonce→以精确targetOrigin转交MessagePort→端口绑定session和document generation。导航／重新load／会话结束立即关闭旧通道；新文档必须重新握手，旧port和nonce不能复用。通道身份不能单独当服务端授权，浏览器报告的extension_id/user_id均不可信。

| 候选对象／消息 | 字段及限制 |
| --- | --- |
| PanelSession | session_id、installation/approval/artifact refs、subject/session ref、panel_instance_id、document_generation、GUI及panel origin、允许动作／数据对象、revision、有效期；权威保存在服务端 |
| panel.request | request_id、session_id、channel_sequence、method、具名resource_ref、typed payload；不得含自报角色、授权token或原始HTTP方法／URL |
| host.result | request_id、operation／command引用或类型化只读投影；202仍只是受理，敏感证据另受权限限制 |
| host.subscription | 固定scope的C05投影和失步消息，受同session权限；不转发整个服务内部事件流 |
| panel.close | 仅请求关闭本面板会话，不能自动释放手动接管或恢复自动化 |

服务实际授权为安装批准∩用户当前权限∩目标对象当前授权∩panel session scope；宿主从当前会话绑定用户／安装身份，每个调用在受理与最终发送继续校验。采用短期不透明PanelDelegationRef供宿主代理内部使用，服务端查权威绑定；不交给面板长期bearer，不允许面板把operation包装成独立普通用户命令来逃离扩展撤销范围。公共RequestActor需下一版增加可核验扩展委托引用，不能只添加不受验证的审计字符串。

委托撤销同时失效关联queued／未发许可；已发送继续核对。页面关闭仅关闭委托，不释放设备持有人；重开面板重新授权，不重播旧按钮请求。面板可请求显示接管／恢复预览，但强制接管、布防、执行恢复和扩大权限由宿主可信UI展示实际目标及影响并完成既有授权流程；不接受面板绘制的“已确认”布尔值。普通已授权设备操作仍可由面板直接发起，不为每次推子移动加一次审批。

## 8. ME07：候选API、容量与验收

服务端候选接口：`POST /api/v1/extensions/stage`、`/{installation_id}/approve|activate|disable|upgrade|uninstall`、`GET /extensions/{installation_id}`、`POST /panel-sessions`、`POST /panel-sessions/{id}/requests|close`、`POST /device-operations`及operation查询。路径归宿主服务，Controller设备与Seamer数据源的authority不得混用。安装／审批／运行授权分离，副作用入口有context、幂等键、修订CAS、明确对象范围和可查询operation；最终Schema与OpenAPI另版生成。

存储候选补DF04：immutable extension_manifest、installation_approval、installation_revision、runtime_binding、protocol_io_policy、catalog_approval、secret_grant_ref、panel_session/delegation、device_operation/primitive_binding及revocation_target。主库只给宿主writer；模块如需缓存，限定可删除的非权威目录与预算，恢复不从缓存重建许可或动作队列。

`sim-c09-v1`实验预算候选：每宿主32个后台实例、每实例16设备；单操作最多256个primitive、同设备同时1个控制primitive；每GUI 8个面板、每面板32个未完成请求，单消息64KiB，20请求/秒突发40；超限明确拒绝、不得静默丢动作。只读遥测可声明合并，命令、屏障和结果不能合并丢失。计数归安装／用户／设备交集，重开面板不清服务器窗口；关闭及撤销保留独立处理预算。它们不是生产默认或已测吞吐，需与C04—C06及DF02预算联合批准。

以下**MX01—MX40均未运行**，对应A01／A03／A04／A09／A10／A15／A17—A21。

| ID | 输入／故障 | 验收结果 |
| --- | --- | --- |
| MX01 | 同extension/version替换不同字节 | 拒绝覆盖，原审批不适用 |
| MX02 | 安装包含隐式脚本／在线依赖 | staged阶段不执行，缺批准制品则拒绝启用 |
| MX03 | 安装者批准但访问者无动作权限 | 面板／模块调用仍403，不继承安装者权限 |
| MX04 | 签名正确但权限或依赖扩大 | 新审批，不自动升级激活 |
| MX05 | 文件落地后DB提交失败／相反顺序崩溃 | operation按hash核对，不能启动不确定版本 |
| MX06 | bootstrap成功但未完成目录／在途核对 | 保持闭闸，不用connection.ready代替可写 |
| MX07 | 连接／心跳／断连会改变设备输出 | 标为控制副作用，不能以只读自动恢复 |
| MX08 | worker多设备中一个失败 | 精确设备保护；进程崩溃时保护其全部设备 |
| MX09 | 动态扩设备集或更换端点／凭据 | 新绑定和维护；旧LaunchIntent不修改 |
| MX10 | 同物理设备别名／不同Controller注册 | 不以名字或本库唯一键证明唯一writer，明确核对／拒绝 |
| MX11 | 厂商库异步队列在FENCE后flush | 未提交写被阻止；已入传输登记in_flight |
| MX12 | 自动重连恢复预设或应用重发 | 无新许可不得写；不能称为底层重传豁免 |
| MX13 | 已交给TCP后屏障／断连 | 不能改写not_sent或宣称设备停止 |
| MX14 | 多帧只发送一部分后崩溃 | 保留部分提交／unknown，不报整个动作未发 |
| MX15 | 复合动作中途接管／撤权 | 后继不发，已发效果与子命令保持可查询 |
| MX16 | 根操作响应丢失／重复幂等请求 | 返回同根及原子命令身份，不重建计划 |
| MX17 | 原生macro启动ACK但未完成 | 不声称效果完成／可取消；资源按政策保留 |
| MX18 | 能力自报complete或加入新action | 无批准目录／足迹不得获得自动化资格 |
| MX19 | 型号／固件／目录换代 | 原批准失效，固定旧请求不可被新默认重解释 |
| MX20 | ACK、缓存目标值或无关联事件冒充效果 | 按专属证据policy拒绝升级完成等级 |
| MX21 | dB／线性／静音哨兵／通道差异 | 参数Schema与UI一致，不丢型号特性或单位 |
| MX22 | 原生面板外部改变同目标／不同目标 | 因果不猜；偏离暂停，不自动纠正现场 |
| MX23 | 设备无可靠外部变化检测 | 显示盲区，不能批准要求该证明的自动化 |
| MX24 | 模块索取其他设备秘密／主库／签发密钥 | 宿主拒绝，记录来源；不声称SDK即OS沙箱 |
| MX25 | 撤销时存储故障／worker失联 | 保护关闭，未确认不能报持久撤销完成 |
| MX26 | 卸载时存在unknown或依赖运行 | 显示依赖、停新发、保留证据，不清空历史 |
| MX27 | 模块已读取秘密后卸载 | 只撤未来访问，轮换另记，不伪称秘密收回 |
| MX28 | 纯面板卸载／页面关闭 | 委托关闭但手动接管保留，独立组织自动化不误撤 |
| MX29 | iframe与GUI同源／共享管理员Cookie | 该部署拒绝面板启用 |
| MX30 | 假origin、其他窗口或旧nonce发送ready | 握手拒绝，不转交数据／通道 |
| MX31 | iframe导航后复用旧port／session | 旧代失效，新文档重新握手 |
| MX32 | 面板自报管理员或另一个extension身份 | 服务端从委托绑定派生身份，拒绝伪造 |
| MX33 | 用户权限／安装批准在排队后撤销 | 最终出口拒绝未发，已发继续核对 |
| MX34 | 面板发送任意URL／HTTP方法／超范围订阅 | 只允许具名API和scope，不能成为通用代理 |
| MX35 | 脚本外连、子资源或frame自导航外泄路径 | 按批准浏览器profile验证；无法证明硬性零外连则不启用该profile |
| MX36 | 面板伪造强制接管／恢复确认 | 宿主可信UI与实际目标授权，不信任布尔确认 |
| MX37 | 面板请求洪泛／重复重开规避限流 | 服务器有界拒绝，保护／撤销通道仍可处理 |
| MX38 | 模块重启风暴或缓存含旧写意图 | DF02有限预算，新进程闭闸，缓存不恢复派发 |
| MX39 | 停Seamer只运行Controller | 已授权手动／复合操作可用，自动化不被偷偷内建恢复 |
| MX40 | NodeCG桥声称消息ACK就是观众画面成功 | 分离桥接受理、目标状态与真实输出证据，按C11验收 |

冻结退出条件：ME推荐完成审阅；每个实际模块给出设备／协议／初始化／重传／完成证据矩阵；面板委托与扩展撤销挂接公共身份和最终许可；复合operation及子命令模型纳入下一版SDK/IPC；两平台和浏览器的未运行试验有明确夹具及判据。未完成C11具体能力映射、C10交互和C12部署profile前，不把C09候选稿当成全系统已定稿。
