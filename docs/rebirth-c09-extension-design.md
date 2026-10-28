# C09：模块生命周期、扩展授权与面板委托

2026-10-28最新成果交接：[发布原件与当前面板提供者](contracts/sdk-publication-handoff/README.md)固定SDK `ca785b2`、`aff5ccb`。panel4当前发布写入与显式panel3历史读取已有不可变存储升级参考；当前动态值提供者及发布content／metadata来源已接线，逐节点字段权限、未提交记录拒绝和撤权均有实际检查。Suite从245个固定Git原件重跑两包，保留原件字节及完整报告一致性；旧包与旧报告不改写。此前Chrome页面／Worker的35220条断言与420次HTTP交换保留为历史证据，本轮未重跑浏览器。其余来源适配、真实审批／读权、生产发布事务、投影与最终输出Gate、完整DDL、校验器硬内存限制及全局调度仍待完成，阶段0继续开放。

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

安装状态原推荐`staged → verified → approved → installed_disabled → activating → active`。第15节细化其身份和失败规则：业务槽位可以重新启用，已撤销安装实例不可复用；存在外部出口时必须先经过revoking，不能直接以failed结束清理。staged只将字节置于隔离缓存并静态检查，不执行包脚本、加载动态库、连接设备或调用模块“自检”。verified仅证明文件／依赖／来源检查完成；approved才允许在批准环境进入受监督启动，仍默认闭闸。

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

正常升级／回退用槽位新修订和新的installation_id，旧worker退出及资源核对后新worker从closed开始，依赖自动化解除布防；重新启用也不能清除旧安装拒绝墓碑，具体见第15节。纯面板卸载只撤面板委托与未发面板请求，不隐式撤销独立组织自动化；后台模块卸载影响其依赖自动化及来源，须暂停，不偷换为健康模块来源。

## 7. ME06：第三方面板通过宿主代理委托

官方事实：HTML要求跨窗口消息核验origin与数据格式，敏感数据不得使用任意targetOrigin；CSP的connect-src限制脚本连接，但不是所有网络行为的完整隔离证明。（来源：[WHATWG消息安全](https://html.spec.whatwg.org/multipage/web-messaging.html#security-postmsg)、[W3C CSP connect-src](https://www.w3.org/TR/CSP3/#directive-connect-src)。）以下部署与委托是本项目候选设计，尚未做浏览器验证。

固定面板产物使用与GUI不同的专属来源；不同安装／版本不能共享可写同源存储，禁止同源代理路径冒充隔离。面板来源无管理员Cookie或服务签发接口；主会话Cookie采用host-only，不设置跨子域Domain。只有明确批准的静态文件可供该来源读取，不允许上传内容和原始设备秘密混在同源目录。

iframe初始候选sandbox仅allow-scripts及必要的allow-same-origin，以保留可核验的独立origin；后者绝不允许与主GUI同源组合。默认无popup、top-navigation、form、download、camera/microphone、USB/serial/MIDI等能力；CSP default-src none，脚本／样式只用固定本地产物，connect-src none，object/base/form/worker默认禁止，frame-ancestors只允许批准GUI。额外媒体及外连需求逐项审阅；需要外部数据时优先通过宿主受限查询代理，不给任意URL代理。

CSP、sandbox和API代理分别验收，不能仅凭iframe存在宣称所有网络外泄已被阻断；frame自身导航等路径需要单列测试。凡安装批准要求硬性零外连而目标浏览器／网络组合不能提供证明，则该面板不获准启用该profile，不能悄悄降级。首期固定受信代码、内容与权限审阅仍不可省略；不声称可以安全执行任意恶意网页。

握手顺序：宿主取得PanelSession→创建精确origin iframe→核验初始ready的event.origin和event.source===iframe.contentWindow→发一次challenge→核验reply的nonce、安装digest及同窗口绑定→以精确targetOrigin转交MessagePort→服务激活后开放端口业务。初始ready不可能回显尚未发出的nonce，具体字段和先后见第10节。宿主观察到导航／重新load／会话结束时立即关闭旧通道；新文档必须重新握手，旧port和nonce不能复用。宿主检测不是跨源导航开始时刻的零窗口证明，检测前的受理／发送边界须如实保留，详第9节。通道身份不能单独当服务端授权，浏览器报告的extension_id/user_id均不可信。

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

服务端早期候选为`POST /api/v1/extensions/stage`及安装approve／activate／disable／upgrade／uninstall。第15节将可重复的用户管理入口归到稳定槽位，将批准与历史查询归到不可复用安装实例，并明确制品导入入口；它是替代本段简写的待审阅版本，不能同时实现两套身份语义。`POST /panel-sessions`、`POST /panel-sessions/{id}/requests|close`、`POST /device-operations`及operation查询另按各专项。路径归宿主服务，Controller设备与Seamer数据源的authority不得混用；最终Schema与OpenAPI另版生成。

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

## 9. 面板委托与可信宿主确认细化

2026-10-18补充。PD01—PD06是ME06的待审阅细化，与[身份生命周期IL](rebirth-df06-internal-trust-design.md#9-身份生命周期细化注销组织服务与配对)、[C05服务订阅](rebirth-c05-event-sync-design.md#9-服务订阅细化与局部机器候选)及[UI03—UI06](rebirth-c10-gui-design.md)共同审阅。本节没有批准第三方代码或改变旧draft.4／IPC0.3。

**官方事实。** Window.postMessage算法把发送来源与WindowProxy写入消息事件，并要求接收方检查预期origin和数据格式；MessagePort交付算法初始化data／ports，没有执行相同的窗口来源赋值。Port还可被转移，因此持有port不是原文档字节、人员点击或当前权限的证明。（来源：[WHATWG Window消息安全及发送算法](https://html.spec.whatwg.org/multipage/web-messaging.html#security-postmsg)、[Message ports](https://html.spec.whatwg.org/multipage/web-messaging.html#message-ports)。）

**设计分析。** 握手使用浏览器提供的窗口身份；通道消息使用宿主保存的绑定；服务端授权使用权威PanelSession／Delegation。三者分别验证，不能要求port回传origin当凭证，也不能把面板自报artifact_digest当实际加载字节的证明。静态制品与专属origin的对应由Suite／宿主批准配置及资源服务保证，面板回显只用于发现错配。

### 9.1 PD01：三个身份和单目标authority

PanelSession建议字段：`panel_session_id,revision,authority_service_id,database_instance_id,installation_ref,approval_ref,artifact_digest,issuer_id,issuer_epoch,principal_id,auth_session_id,gui_instance_id,panel_instance_id,document_generation,gui_origin,panel_origin,scope_ref,policy_ref,created_at,expires_at,lease_expires_at,lease_revision,state`。这里auth_session_id是人员登录会话，panel_session_id是一次面板挂载，二者不可混用。安装／批准引用包含所属authority及精确revision；opaque ID不可复用。

状态`created→handshaking→active→closing→closed`，created／handshaking／active均可转revoked或expired；closed／revoked／expired不可重开。expiry按认证时钟和本地有界租期保守判断；心跳不能延长安装批准、人员会话或原委托上限。只允许human，service不能伪造auth_session_id创建面板。创建人按当前权限请求固定子集，不能继承安装管理员全部权限。

`PanelDelegationRef={authority_service_id,database_instance_id,delegation_id,revision}`只供可信宿主到服务端的代理请求使用，不交给面板。引用本身不是bearer；服务还核对当前human凭据链、auth_session_id、PanelSession及安装批准。委托记录包含原scope／method集合、原期限及所有撤销关联，不能去掉extension字段改成普通用户调用。面板可见的`PanelPublicBinding`仅含panel_session_id、panel_instance_id、document_generation、channel_id、protocol_version及允许方法的脱敏描述，不含用户token、delegation、NodeCG key或设备secret。

一个PanelSession只属于一个目标authority。跨Controller／Seamer面板由宿主为每目标分别创建session／delegation，面板只能使用宿主分配的target_handle；请求不能提供任意服务URL、audience或替换authority。GUI mount_id只聚合显示，不提供跨库原子授权。任一目标失效关闭其对应通道／资格，跨目标业务操作仍按各服务原有规则处理，不用“一个面板”暗示原子批量。

### 9.2 PD02：握手、报文与导航窗口

宿主取得created会话后，把固定静态入口放入批准的独立origin。等待一次`panel.ready`，以event.origin精确相等、event.source等于该iframe的WindowProxy、当前挂载对象及新生成nonce核验；不接受payload中的origin/source替代浏览器字段。初始ready不携带特权数据，nonce由宿主经精确targetOrigin发出challenge后回显，禁止通过URL带secret。宿主转交一个MessagePort时携带当前PanelPublicBinding，并记录原port对象和本地文档代；服务端激活session后才开放业务请求。

握手challenge包含`handshake_id,nonce,panel_instance_id,document_generation,protocol_version`；reply逐项回显并带artifact_digest。nonce至少32字节随机值、只用于本次握手、验证后消费，不作服务授权。重复ready只处理当前等待阶段，不反复创建PanelSession或通道；超时／错版本／错digest销毁候选并关闭本次session，新挂载用新ID和nonce。不得用相同origin下另一个窗口发送的ready接替当前frame。

业务只接受port上**JSON文本字符串**，UTF-8字节及深度按有界profile检查，再走DF01严格解码；不直接把任意structured-clone对象转成JSON。拒绝ArrayBuffer／Blob／循环对象／Map／额外转移port；这同时避免结构化克隆允许的对象类型被误当公共JSON契约。双方各有channel_sequence U20，从1递增，拒绝缺口／同序异内容；序号是传输顺序，不取代持久request_id。宿主捕获port对象、channel_id及document_generation，不能从MessagePort事件或payload临时推导origin权限。

宿主主动换页／卸载／关闭先本地禁新请求，再发关闭；iframe load、messageerror、通道异常或GUI失去该挂载时关闭旧port与session。跨源自导航的开始不保证能被宿主即时观察；WindowProxy匹配也不证明文档未换代。受信静态面板、禁止未批准导航／外连的部署profile、短期租约及检测后关闭共同约束该风险，不能宣称任意恶意面板的零窗口沙箱。检测前已受理的请求保留原委托身份，检测后按PD05撤未发、核对在途；不能回写成“从未受理”。

### 9.3 PD03：具名方法与服务端代理

`panel.request`固定`protocol_version,type,public_binding,channel_sequence,request_id,method,target_handle,resource_ref,payload`；不允许额外role、token、delegation_ref、HTTP method或URL。method来自不可变`PanelMethodRegistry`，每项绑定操作ID、目标类型、输入／结果Schema引用、权限、允许scope及执行方式。动态设备参数仍按当前已批准能力Schema二次校验；不能递归禁止所有叫url／permission的业务参数，也不能允许开放payload变成通用HTTP代理。

本批[操作策略候选](contracts/c09-panel/README.md)逐项覆盖现有71操作，分为六种处理方式，不用URL前缀或SDK可导入性推导权限：

| 方式 | 允许的面板行为／服务边界 |
| --- | --- |
| panel_read | 具名只读设备、状态、命令、运行及有限元数据；精确对象权限及脱敏投影，读取不能隐式执行操作 |
| panel_write | 允许的设备manual提交／取消、草稿编辑、创建未布防run及暂停；宿主补不可变委托及请求身份，仍经接管、能力、原有授权和最终出口 |
| host_confirm | 面板只提出固定intent，可信宿主展示及确认后按PD04执行；接管／释放／转交、定义发布、布防、恢复、RunGrant撤销均在此类 |
| host_transport | 由宿主创建context、订阅、快照、票据和WS；面板拿具名代理投影或结果，不拿上游票据／完整流／原HTTP入口 |
| host_account | 登录、身份／撤销查询、刷新和签发等只在可信宿主账户界面使用，不成为面板RPC；不能因面板请求就自动签更大范围token |
| unavailable | 内部证据／introspect、provider目录／事件提交、自动化grant更新、初始化和容量管理等不通过面板桥开放；后台扩展或可信管理入口仍按自身权限存在 |

每个方法仍需InstallationApproval∩用户当前权限∩目标scope∩PanelSession的完整交集。host_confirm不是额外权限，host_transport也不意味着面板可请求任意范围。公开getCommandEvidence／getIndependenceProof只给已授权有限投影，原始内部证据不能因为它们属于panel_read而泄露。currentSession／subject目录不借普通状态订阅旁路公开。

`POST /api/v1/panel-sessions`由当前目标audience的human bearer创建，输入installation／approval／artifact引用、gui_instance_id、mount目标、期望scope及管理配置引用；origin从允许配置匹配，不信自报任意origin。`POST /api/v1/panel-sessions/{id}/activate`由同宿主凭据提交本次握手关联，只激活原绑定；服务无法通过该报告独立证明浏览器正确握手，可信宿主是明确假设。`POST /api/v1/panel-sessions/{id}/requests`只接受服务端Registry定义的方法、原始请求身份及委托引用；结果返回具名脱敏投影或command／operation引用，不回传内部RequestContext。

宿主在原请求到达时固定`PanelRequestIdentity=(authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,panel_session_id,document_generation,request_id)`及规范内容摘要，保存到服务端panel_request。authority／database／issuer由已认证目标和原会话派生，不接受面板指定。摘要覆盖固定方法、目标、参数、能力／策略版本及委托引用，不包含可更新的传输序号。相同identity同内容仅查原结果，异内容409；已关闭session先按当前查询权限判断能否查看历史，不给它新执行资格。跨重载、换session或换request_id都不是失败重试授权。面板只能保存显示关联，不保存离线写队列；宿主不得在连接恢复后扫描旧请求重新提交。

补齐候选路由语义如下，均在对应目标authority执行，属于下一版新增接口，不计入本轮现有71操作策略矩阵。路径中的id只作定位，仍核验完整身份关联；所有响应no-store，浏览器host接口沿原Origin／CSRF及单audience规则。

| 接口 | 受理与返回边界 |
| --- | --- |
| POST `/api/v1/panel-sessions/{id}/handshake` | 同创建宿主把created经CAS转handshaking，登记handshake_id和文档代；原关联重复返回原状态，不能重置nonce或已消费握手。nonce只保留宿主内存，不写审计 |
| POST `/api/v1/panel-sessions/{id}/renew` | 只续当前active租约，输入expected_lease_revision；返回新lease_revision／lease_expires_at。不改scope、身份或文档代，不复活已过期／关闭会话，不以续期替代重新批准 |
| GET `/api/v1/panel-sessions/{id}/requests/{request_id}` | 按当前人员读权返回原记录的accepted／pending_confirmation／rejected／cancelled及原结果引用；accepted不表示设备完成。查询无创建副作用，旧会话可查不表示可写；不存在／不可见不能作为换ID重发依据 |
| POST `/api/v1/panel-sessions/{id}/confirmations` | 可信宿主提交固定HostIntent及原PanelRequestIdentity；在短事务中登记pending_confirmation请求及唯一offered预览，201只表示可供确认。同身份同内容返回同一预览状态，不刷新截止，异内容409；面板requests入口的host_confirm只返回needs_host_confirmation，不创建业务操作 |
| POST `/api/v1/panel-confirmations/{preview_id}/cancel` | 同宿主取消offered预览并将关联待确认请求置cancelled；同已取消状态幂等。与commit由同writer排序，已consumed返回原受理引用及冲突，不能伪报取消成功 |

`expires_at`是创建时固定的硬截止，取人员、安装批准及policy中有限最大挂载寿命的最早边界；`lease_expires_at`是更短的活跃租约，最终受理及派发检查两者。续租复核所有授权，只改变独立lease_revision，不改变scope revision或旧请求摘要；缩权走撤销，不能用续租把旧委托原地升级。心跳只由当前可信宿主在实际通道仍有效时发出，不接受面板自报存活；租约响应丢失按原续租身份查原结果，不能重复延长。新预览截止不晚于创建时租约截止，之后续租不延长旧预览。

普通受权面板请求可以由已批准脚本发起，不为每次推子移动弹审批；manual表示当前人员委托及控制身份，并非服务器已经证明每条消息来自物理点击。实时手势仍沿UI04限定绝对赋值、单未决命令及结束后不补发，不能用面板定时器绕过同资源预算或以相对动作合并。后台自动化仍经Seamer，安装面板不自动获得组织服务身份。

### 9.4 PD04：固定内容确认与原子消费

面板对host_confirm方法提交的是`HostIntent`，不包含confirmed=true或确认票据。宿主向目标authority取得`PanelConfirmationPreview`：`preview_ref,panel_session_ref,delegation_ref,method_key,target_ref,normalized_arguments,arguments_digest,expected_object_revisions,policy_ref,expires_at,display_projection`。normalized_arguments由目标方法按固定Schema／目录版本解析，digest为JCS完整具名投影；不按面板提供的摘要放行，不在显示后追加默认值或重新选目标。

宿主用自有可信DOM展示来自服务端的目标、实际动作、关键参数、当前控制／run修订、影响和期限；不嵌入面板HTML。用户改目标／参数或权威修订变化必须重取preview，旧确认失效。需要近期再认证的管理操作仍要求它；普通接管不被本节无故升级为所有操作都需重新登录。面板可以收到pending_confirmation／cancelled等状态，但看不到可消费确认凭据。

display_projection采用逐方法白名单和纯文本字段，不透传normalized_arguments、HTML或设备原始错误。需要秘密的能力只接收已授权secret_ref及其版本，服务端绑定引用而非把口令值放入预览或摘要；不向面板暴露可用于离线猜测低熵秘密的hash。当前宿主也不得因“确认需要看见”而取得设备秘密。面板结果只保留状态及允许的业务引用，确认preview_ref和委托细节只在可信宿主保存。

用户在可信宿主确认后，宿主调用`POST /api/v1/panel-confirmations/{preview_id}/commit`，携带同human凭据、delegation及原PanelRequestIdentity。目标服务同一writer事务复核权限、session／文档代、安装批准、目标版本、预览截止和内容摘要，将preview从offered原子改consumed，并创建原方法的command／ControlOperation／RecoveryOperation或可靠发布结果。确认消费与本地业务受理同事务；不采用先在GUI服务消费、再跨库HTTP写目标的伪原子流程。恢复仍绑定既有RecoveryPreview及一次消费，不重复制造新的恢复计划。

同identity重试查原结果；同preview被另identity消费返回冲突，不替换请求ID重新执行。确认commit只推进已绑定pending_confirmation记录到accepted，不作为同identity的第二次独立业务请求；普通requests调用不能把pending_confirmation推进到accepted。提交结果未知时显示待核对，按原身份查询，不因未收到确认结果再次弹窗并自动提交。预览状态offered→consumed／cancelled／expired／revoked，均不复活；取消仅在未消费时成功，消费后的关闭弹窗不能撤销已受理动作。副作用仍在原最终出口检查，不以确认成功覆盖接管或撤权。

服务端无法单独证明一次点击发生在某个可信DOM，本设计依赖GUI凭据不泄漏、宿主代码／origin受信及面板无直接访问宿主能力。确认接口必须拒绝缺同会话委托／预览绑定的普通面板转发，不能把拥有preview_id本身当授权。宿主被攻陷不在“iframe存在即可抵御”的承诺内，按应用威胁边界另外处理。

### 9.5 PD05：撤销、查询与关闭传播

`POST /api/v1/panel-sessions/{id}/close`由同human宿主关闭，面板panel.close只触发本面板关闭请求；202返回可靠关闭操作及逐目标状态，不返回设备停止。关闭、用户退出、安装／权限撤销及期限失效都首先禁止本地新代理，再由权威写关闭状态／拒绝下界／固定关联集合／审计及通知。目标尚未确认仍保留closing或未确认操作，不能等浏览器响应才保护。期限门控不等待清理定时任务。

下一版ExecutionGuard新增精确`panel_delegation_ref`及panel_session／document_generation关联，受理时固化；不能仅复用当前extension_instance_id就声称可区分同安装的两个页面。安装撤销命中全部面板与相关后台范围；关闭单面板只命中其委托，人员退出命中auth_session链；独立组织run不混撤。关联在queued请求、permit、订阅和confirmation preview上均可索引，撤销selector在新版Schema／IPC须明确增加panel_session／delegation域，不暗改旧枚举。

关闭／卸载后已发命令保留原身份、在途与unknown，按证据核对；不自动release holder或恢复自动化。宿主和服务的结果查询按当前human读取权处理，面板关闭后可在可信宿主命令详情查看历史，但不会把旧delegation搬到新面板。普通GET查询不会重新消费preview／创建command，404也不证明旧操作从未执行。

host.subscription是面板委托范围的只读投影，必须绑定同一panel session与当前权限；不能直接转发人员完整C05订阅，或把service mTLS订阅交给面板。订阅确认仅表示投影进度，面板不得发durable_ingest充当Seamer。scope失效即停止释放；重开面板完整重建投影，不恢复旧通道序号或未提交手势。慢面板单独失步，不拖住宿主关键控制或其他订阅。

### 9.6 PD06：事务、故障及验证范围

DF04候选补充panel_session／panel_delegation、panel_request、panel_confirmation及panel_revocation_target；各记录绑定本地authority／database、完整人员会话、安装批准、文档代和不可变请求摘要。session激活CAS、request唯一登记、preview消费＋原业务受理分别为短事务；浏览器握手和用户等待不持有SQLite写锁。关闭事务固定关联集合，出口保护仍走F04和F02，不把通知outbox变成设备动作队列。恢复库／服务换域使旧未完成panel session及preview失效，不能恢复旧port资格。

沿sim-c09-v1预算，附加实验值：握手10秒、确认preview最多30秒且不晚于相关权限／恢复预览截止；每面板最多1个待确认敏感intent；session租期最长60秒、合法当前宿主续租不得越过人员及安装上限；每方向消息深度16、64KiB；64条未确认响应／1MiB先到为限。seq到U20上限关闭而不回绕。洪泛在便宜的长度／类型检查后限流，不为每个恶意请求创建确认窗口；保护关闭不占普通32未决请求槽。实验值不是生产批准。

PDT01—PDT16为待运行验收：①错origin／source／旧nonce无port；②port报文伪origin无授权；③非JSON文本及额外transfer拒绝；④同origin导航、延迟load和旧队列消息按实际检测／受理点记账；⑤同request_id异内容拒绝；⑥响应丢失查询无第二command；⑦面板伪confirmed／preview ID无消费资格；⑧显示后参数／目标版本变化拒绝；⑨两个确认只一个受理；⑩preview消费与本地业务提交各崩溃点一致；⑪关闭精确撤该委托，其他面板／组织run不误撤；⑫已发后关闭不伪not_sent或释放holder；⑬重载不补实时最后值；⑭跨authority不能替换target_handle；⑮慢投影／请求洪泛保留保护通道；⑯Edge／Chrome分别验证sandbox、CSP、导航和秘密隔离，不借离线资料通过宣告浏览器安全。

具体验收补充：PDT05加入同request_id但不同issuer／database不得命中旧业务，以及原身份改参数409；PDT06覆盖预览创建响应丢失、已consumed重复commit及不可见404均不重发；PDT09分别排列cancel与commit先提交，只准一个终态；PDT10在pending登记、preview消费和业务受理边界注入崩溃，恢复只查询原记录；PDT11验证续租与撤销竞争、截止相等即拒绝、续租不延长旧preview；PDT16验证secret_ref展示不含值或低熵摘要。这些是运行测试规格，本批元数据检查不执行它们。

本轮局部机器资料只登记71操作的面板策略及源permission／主体关联，未实现消息协议、确认事务或浏览器代理。剩余同版归并为PanelSession／Delegation／Preview和RequestActor、完整双向消息、host结果投影、委托撤销selector与IPC守卫、DDL唯一键及方法注册；当前源映射不充当这些运行证据。PD01—PD06待审阅，不关闭C09或全系统设计。

## 10. 面板会话与调用信封的机器候选

2026-10-18后续补充，仍为待审阅候选。[channel.schema.json](contracts/c09-panel/channel.schema.json)及[复验说明](contracts/c09-panel/CHANNEL.md)把会话／委托、窗口握手、端口调用、固定确认和执行Guard具体化；本节细化PD，不把候选自动登记为批准，也不改变旧协议接受集。

### 10.1 PC01：窗口握手和端口启用

已知事实：Window消息应检查浏览器提供的origin及数据格式，转移列表是消息机制的另一部分；原生机制允许非JSON对象，不会替本项目执行严格JSON协议。（来源：[WHATWG消息安全及发送算法](https://html.spec.whatwg.org/multipage/web-messaging.html#security-postmsg)。）以下序列是项目设计。

1. `panel.ready={protocol_version,type}`只宣告监听已就绪，不携带nonce、权限或自选session。宿主核对精确origin、WindowProxy、当前mount及等待阶段；重复ready不新建会话。
2. 宿主CAS登记handshake后发送`host.challenge={protocol_version,type,handshake_id,nonce,panel_instance_id,document_generation}`；nonce为32随机字节的64位小写hex编码，不入URL／持久日志。握手总期限从原开始点计，不随ready或重试续期。
3. `panel.reply`回显challenge身份并附artifact_digest；再次核验真实event.origin/source、当前mount、期限和未消费nonce。digest回显不是实际制品字节证明。所有前述消息均用严格JSON文本且不得带转移对象。
4. 宿主以精确targetOrigin发送`host.port`，正文包含handshake_id、PublicBinding、target_handle和具名MethodDescriptor列表，转移列表**恰好一个**MessagePort。面板核对批准的GUI来源及parent窗口，不能只看宿主自报绑定。PublicBinding只含panel_session_id／panel_instance_id／document_generation／channel_id／protocol_version，方法描述独立于逐帧身份，不在每个请求中复制可变权限。
5. 宿主收到目标服务activate的成功结果后才允许调用，并从host方向sequence=1发`host.active`。面板在此之前不得发业务请求。激活响应未知时查询原会话，绝不把转交port当成功；失败关闭候选通道，不创建新请求代替原请求。

WindowFrame、PanelFrame、HostFrame按方向选Schema；根oneOf只作资料分类，不是忽略方向的接收器。普通port消息不得附额外port、Blob或结构化对象。旧文档／错port／不符绑定先拒绝，不能先推进计数再判权限。文档导航检测的实际窗口仍沿PD02，host.active也不证明后来未导航。

### 10.2 PC02：调用、结果与有限确认链

面板方向为panel.request、panel.query_request、panel.close、panel.ack；宿主方向为host.active、host.result、host.closed。每条port消息带固定protocol_version／PublicBinding与本方向PositiveCounter，严格从1递增，不能Number化。未来同版订阅消息需沿相同通道规则另定义，本批不以任意host.event透传上游流。

request保留PD03字段；target_handle由host.port固定映射到单authority，resource_ref若存在须属于该方法允许的目标，跨服务参数引用另按该方法规则验证。payload是`{schema_ref,value}`，按当前不可变Registry精确input_schema_ref校验，再走能力／对象权限；面板不能靠替换schema_ref选择更宽Schema。MethodDescriptor包含method／mode／输入及结果Schema引用，mode来自已批准策略，当前71操作里仅35项可成为具名调用。服务端不能信任客户端提交的descriptor。

host.result包含request_id、status=`accepted|pending_confirmation|rejected|cancelled|unavailable`、具名reason_code及可空TypedValue结果。accepted仅表示原业务受理；只读结果及command／operation引用也须逐方法投影。pending_confirmation不含preview_ref、delegation、摘要或可消费凭据，最终结果仍用同一request_id。unavailable包括无法按当前权限确定旧记录的情况，不能解释成从未受理或换ID重试。历史查询是panel.query_request；当前通道失效后只允许可信宿主按新的当前读取权查原完整身份，不能给旧面板恢复调用资格。

panel.ack带last_host_sequence及host_frame_digest；后者为确认的完整HostFrame的JCS摘要，与业务请求／预览摘要不同。只确认已连续处理的本通道前缀，当前绑定、已发送映射和摘要必须吻合；超过last_sent或跨代拒绝，旧ACK仅在原映射仍可核验时幂等。ACK只释放面板传输缓冲，不能确认设备、消费preview、延租或充当Seamer durable_ingest。相同channel_sequence的完全相同重复帧只作传输重复、不调用业务；同序异内容或缺口关闭并重新挂载，不补发旧手势。当前generation不跨重载恢复。

沿原64条／1MiB响应保留预算，ACK和关闭有独立控制预算；数据帧预算先扣后交传输。失去保留映射即明确关闭／重建，不能凭序号大小接受ACK。host.closed的closure_state区分local_closed、closing和权威closed／revoked／expired；消息未成功发出也须本地禁止新请求，不能等待面板ACK再保护。上述传输ACK与容量行为尚无运行验证。

### 10.3 PC03：固定确认的两个摘要及时间边界

Intent完整包含RequestIdentity、DelegationRef、method、target_ref、normalized_arguments、capability_ref和policy_ref；`intent_digest=SHA-256(JCS(Intent))`。规范参数必须在展示前固定默认值及能力版本，只接受秘密引用，禁止把真实秘密纳入预览或可公开摘要。channel_sequence不在请求身份或Intent中，重送展示不生成第二业务身份。

Preview另含自身ref、expected_object_revisions、可空RecoveryPreview引用、创建／到期UTC、受监督domain_ref、固定deadline_tick、lease_revision_at_creation／lease_deadline_at_creation、display_projection、state和accepted_result_ref。`preview_digest`对**除preview_digest、state和accepted_result_ref外的完整Preview**做JCS；它包含intent_digest、预期目标修订、恢复引用、原截止和显示文本。这样用户看到的目标／参数及前提均被绑定，消费状态或结果追加不会改变预览身份。两个摘要都只在可信宿主与权威服务之间使用，不发送面板。

ConfirmationCommit只携带preview_ref、原RequestIdentity、DelegationRef、intent_digest和preview_digest；服务从本库读取不可变预览并重算，不接受请求提交替代Preview。display_projection为label_key及纯文本，不接收面板HTML；Schema只能限制形状，真正内容仍须逐方法白名单和脱敏投影，不能把text字段合法当作无秘密证明。引用本身不是权限或“用户已经点击”的证明。

内部Lifetime为domain_ref、hard_deadline_tick、lease_deadline_tick，tick统一同域纳秒U20。公开UTC只作展示，当前域／tick及权限必须由可信服务提供；达到任一截止即拒绝。Preview截止取创建时租约、硬期限、30秒实验预算、授权与RecoveryPreview更早边界；后续续租不能延长它。许可缩短或引用修订变化使旧预览失效，不能重算hash静默接受原确认。服务重启换域使旧会话／预览失效，不能借保留UTC恢复资格。

### 10.4 PC04：原子消费与关闭的故障判据

offer可靠登记pending_confirmation及唯一预览；commit在同一目标writer内检查原身份、当前权限／session／委托、目标修订、两摘要、固定截止和恢复引用，原子写consumed及原业务受理。只读查询或普通panel.request不能把pending升级accepted。取消先提交则commit冲突；commit先提交则取消返回冲突及原引用，不伪称撤回。重复commit只查原受理，不重复消费恢复计划。

关闭先提交后commit拒绝；commit已受理后关闭，保留原command／operation、在途及unknown，撤未发经最终出口保护，不改写已受理记录。提交结果未知时进入待查询，不能以“本地尚无成功回执”判断没有副作用。查询不可见时仍不换ID重发；跨库或GUI消费不是本事务替代品。

Guard固定PanelSession、document_generation、DelegationRef、安装／批准引用、auth_session_id及完整RequestIdentity，留给下一版ExecutionGuard分支。精确撤销仍须沿panel_session／delegation及安装／人员链索引到所有未发许可，不能只匹配extension_instance；本批结构不实现IPCselector、屏障覆盖或关闭持久化。关闭永不自动释放holder或恢复组织run。

### 10.5 PC05：本轮验证与剩余交付

新资料包括正向窗口／端口／内部模型、禁止面板带token／confirmed／preview／委托的结构反例，以及错窗口、旧nonce、额外port、错代、未active、错authority、动态参数、截止等号、确认重算摘要后身份错配和显示篡改。有限轨迹列出commit／cancel两种先后、关闭前后、重复消费和提交未知；人工原子步不证明真实SQLite并发。源码中授权／窗口及时间等上下文均为夹具，不作为API自证字段。

仍须同版交付35个方法的完整参数／结果／纯文本展示投影及Registry、订阅消息和scope、完整HTTP状态错误与续租幂等接口、IPC撤销与Guard以及DDL约束；本批只有调用信封和权威对象的局部Schema，不能称完整面板SDK已交付。PDT01—PDT16运行规格沿用并加入本节先后判据，浏览器／真实身份／DB故障／设备均未执行；旧28项策略检查仅回归，不用于证明新增消息。PC01—PC05与PD共同审阅，C09和全系统设计继续保持未关闭。

## 11. 逐方法输入与结果投影

2026-10-18补充，仍为候选。[字段规范](contracts/c09-panel/METHODS.md)逐一落实19个Controller与16个Seamer方法：输入Schema绑定现有领域类型，96个HTTP path／query／body字段明确由面板提供、宿主绑定、固定manual或禁止。context、幂等键、correlation与委托身份不接受面板自报；路径ID必须再与resource_ref及父子对象关系相符。旧DraftUpdate缺幂等字段，不免除panel_request与草稿CAS同事务。

新增明确取舍：preflight／recovery原引用留在服务端，面板取得绑定当前session、文档代、run修订及固定截止的展示句柄。arm与resume只提出intent；可信宿主固定原预检／组织批准或原恢复预览，确认、句柄消费与原业务受理在目标writer事务中完成。两个面板不能绕过原恢复唯一消费。句柄不是bearer，过期／错代／修订变更拒绝，不后台重做预检再沿用旧确认。page_handle同样隔离上游cursor，重复读取同页不消费业务资格。

21个结果View已列字段与嵌套白名单，命令结果／资源／控制生效／ready分别表达，隐藏未决只给has_hidden且继续阻止ready；可见targets全成功不改全局操作状态。原始证据、授权／时钟描述、秘密和错误原文不透传。定义编辑必须提供完整可授权内容，不能保存裁剪后的假全量；动态表单使用批准的本地SchemaBundle，缺闭包不回退任意JSON。SchemaBundle的具体消息和字段批准仍未归并。

输入资料包含35个手写方法正例、25个结构变异／边界例及14个元数据反例，共74项；检查同时独立对账HTTP来源和操作策略。其范围是输入形状及字段归属，不证明动态参数授权、结果过滤、可信确认或数据库原子性。PMT01—PMT12新增运行规格均未执行。完整结果Schema／展示词表、SchemaBundle、订阅、HTTP／IPC／DDL仍是明确剩余项，不能以输入Schema完成宣布C09或全系统定稿。

## 12. 21类结果Schema与关联边界

2026-10-18补充，仍为候选。[RESULTS](contracts/c09-panel/RESULTS.md)提供21个具名View及35方法分派的唯一结果Schema、人工夹具和参考检查。静态对象封闭，动态观察值与完整可编辑Definition使用明确SchemaRef；Definition结果的value保存原结构，输入保存仍取value，不能提交裁剪占位。SchemaRef在人工批准表中实际重算JCS摘要，生产SchemaBundle及字段授权尚未归并。

保留未知命令主终态与后续resolution、效果与资源、控制effective与ready的区分。gate ready允许正常在途，但不允许pending／未决；ControlOperation.ready还要同一致点核对原epoch和当前version／mode／holder，历史操作不能借新控制资格显示ready。来源integrity与投影projection_status独立，隐藏目标／grant保留has_hidden且全局状态由完整权威集合决定。转交新增关联仍需下一版持久字段，不能以旧类型已存在冒充完成。

117项离线检查包括35方法正例和82个结构／上下文用例；合法字符串的合成未脱敏文本可通过结构检查，作为“Schema不等于过滤器”的明确反证。权限、完整目标集、控制快照及动态Schema批准均为夹具；未执行真实投影、身份提供者、浏览器、并发或设备。本批补齐结果形状，不关闭完整来源映射／受控词表、SchemaBundle／订阅、HTTP／IPC／DDL与运行验收缺口，C09和全系统设计保持未关闭。

## 13. SchemaBundle交付与本地闭包

2026-10-18补充候选。[BUNDLE](contracts/c09-panel/BUNDLE.md)固定Manifest、资源／分块／exports、批准profile与动态SchemaRef；完整文档摘要与会话投递绑定分离。只有当前批准的完整投影Schema可下发，普通摘要不授安装或用户权限。definition选根$defs具名入口，RESULTS原人工根Schema映射尚需同版迁移，不以两个局部报告代替联合验证。

旧channel0.1 Active没有Schema附件，本轮明确改用0.2候选四种局部消息offer／chunk／ready／revoke；下一版Active固定Bundle／Registry／scope，再将方法调用和结果绑定同一激活上下文。局部Schema不包含完整新channel，旧文件不改、不混投。初次或更新都先校验后激活，撤权／换代停止新调用，已受理命令继续按原生命周期查询；传输ACK、Schema ready、控制ready和设备完成分别表达。

本地profile只遍历真正Schema位置，拒绝外部／缺失／非Schema引用、嵌套资源身份与未知执行扩展；数据中的假ref不作为引用。检查同实例环而保留下降到子实例的递归；模式和format需批准名单，实际worker执行预算另验。资源闭包、固定顺序、完整摘要与块布局有界检查，缓存不恢复旧资格，合法文本仍不能证明脱敏。

109项离线检查通过，四输入报告独立绑定，细分73个Bundle例、14个信封例及22条模型轨迹。该计数不含真实加载器、浏览器、权限提供者、数据库或设备运行。完整channel、订阅、方法/结果二次校验与生成、HTTP／IPC／DDL及全量预算仍待归并，C09和系统设计仍未关闭。

## 14. channel0.2完整消息与方法归并

2026-10-18候选进展：[CHANNEL_V02](contracts/c09-panel/CHANNEL_V02.md)给出19种窗口／端口消息和完整35方法Registry，将Active／Request／Query／Result／Intent／Guard绑定ActivationRef；Registry固定输入／结果完整Schema摘要，动态引用选择Bundle根$defs入口。旧channel0.1的Id不允许点号，与领域样本冲突，本版明确放宽；旧文件不改，旧协议不降级重试。Bundle四帧仍引用其唯一局部源。

结果关联原request_id／method／activation，accepted必须有具名View，其他状态为null；固定reason词表，未知结果不能伪装为拒绝后重发。一个PanelSession只激活一次，内容／scope／Registry变化重建会话；旧记录在可信宿主按当前读权核对，不能把新activation加进幂等主键以重新执行。Intent摘要和Guard均固定原激活，实际HTTP／IPC／持久字段仍待联合归并。

新增只读投影订阅：17个方法给完整View，分页目录／证据两方法只发invalidated；预检与恢复预览虽是panel_read，也不能订阅后循环生成句柄。baseline／update按订阅序号连续，ACK只确认展示；gap／closed不复活。退役释放窗口但不提升消费高水位，有限墓碑禁止ID复用，新ID必须重新baseline；Unsubscribe不取消命令或释放holder。容量仍是待运行验证的有限候选。

168项离线检查通过（145帧／上下文例及23条轨迹），包含全部35方法的70个输入／结果正例和真实本地Schema引用联接。授权、目录和原子步均为人工前提，固定合成Definition不代表完整DSL投影。当前补齐通道格式，字段权威提供者／受控词表、完整动态能力、HTTP／IPC／DDL和浏览器／服务／设备运行仍未完成，不能关闭C09或阶段0。

## 15. 安装身份、管理操作与升级恢复

2026-10-18，ILC01—ILC06为待审阅的具体推荐。本节细化ME01／ME05／ME07，不授予实现或运行批准。已知设计约束来自[安装撤销账本](contracts/c09-panel-storage/README.md)：installation_id不可复用，安装拒绝永久保留，全部owner和旧出口捕获；batch acknowledged不推出ready。[DEP07](rebirth-c12-deployment-design.md#7-dep07避免多文件指针切换的安装事务)另规定Suite安装库独立于业务库，文件和引用选择不跨库原子。以下是基于这些约束的设计分析和新增方案，不是已实现行为。

### 15.1 ILC01：槽位可沿用，安装实例不可复活

第2节原InstallationRecord同时承担用户配置容器与撤销身份，容易使disabled→active清掉拒绝墓碑。推荐拆为稳定ExtensionSlot和一次生命周期InstallationInstance；UI仍显示一个扩展和“启用／停用”操作，不要求用户删除配置再安装。

| 对象 | 必需字段／权威 |
| --- | --- |
| ExtensionSlot | authority_service_id、database_instance_id、slot_id、extension_id、kind、slot_revision、desired_state=`enabled|disabled|removed`、current_installation_ref或null、pending_operation_ref或null、configuration_ref、dependency_revision；归目标服务writer，extension_id/kind不可原地换成另一产品 |
| InstallationInstance | 完整authority/database、installation_id、slot_id、installation_revision、manifest_digest、artifact_set_digest、intake_ref、approval_ref或null、state、deny_record_ref或null、runtime_binding_refs、predecessor_ref或null；ID不复用，产物及归属固定，revision仅记录该实例状态变化 |
| InstallationApproval | approval_id/revision、精确installation_ref及内容摘要、permission_review_ref、批准权限集合、platform_profile_ref、批准者与当前认证来源、审批operation、revocation_ref或null；由服务签发，实例不能自行声称approved |
| PermissionReview | 不可变review_id/revision、manifest及依赖闭包digest、请求项与收窄后的提案项、配置约束及用途；最终获准项和批准记录归Approval，可用于同内容重新审批展示，不能作为独立运行凭据 |
| InstallationOperation | operation_id、管理请求identity与intent_digest、kind、slot_ref、source/target_installation_ref、固定依赖计划ref、phase、result_ref或null、protection_batch_ref或null、retirement_ref或null、blockers、audit_refs；由authority持久保存，不以浏览器状态为准 |

以上Ref均带authority_service_id、database_instance_id、object_id和revision；内容寻址对象另带digest。revision采用严格无前导零的非负十进制字符串，语义限制在U20范围内，不能在JS Number中比较。installation_id本身不随revision变化，旧请求不得因revision增加获得新的幂等身份。完整字段Schema、引用类型和词法将在新候选版生成，不能直接投向旧draft.4。

Ref中的revision指不可变快照引用，expected_revision才是本次状态CAS的比较值。Approval绑定审批时实例内容快照及其不可变manifest／配置／范围，不因approved→activating的正常状态修订自动失效；状态更新不能替换该内容快照。后续状态查询返回current revision及原approval_ref，明确核对实例身份、内容与当前撤销状态，不能把“审批旧revision”误作无条件失效，也不能只比installation_id忽略内容。

一次槽位最多一个待执行生命周期operation、一个被选择的安装实例；可有多个未被选择的staged候选。唯一设备writer约束仍按物理设备身份核对，不能只靠slot唯一键。多个槽位尝试占同一设备时不得同时启用；同进程共享设备出口也不能绕过原设备仲裁。

activate／enable仅用于无活动实例且desired_state不为removed的槽位；已有活动实例必须走upgrade，不能通过activate跳过退役。removed槽位保留墓碑，不接受stage／approve／enable；再次安装该扩展创建新slot，仍须核对原设备及旧资源未决。无副作用的stage可在健康实例旁准备候选，但卸载锁存后不再准入任何新候选。

stop／disable、审批撤销、升级替换、异常重启需要退役时，都永久拒绝旧实例。重新启用创建新installation_id和新审批绑定，复用未变的已验证制品及配置；当前管理员的明确enable操作可同时生成新的安装审批记录，不必对相同权限重复弹出逐项确认。若摘要、范围、配置约束、平台、信任或权限任何一项变化，则必须重新展示差异并批准；API不会因“之前装过”自动扩大权限。新的实例也不能绕过仍有效的publisher／artifact／permission撤销下界。

监督器可在同一operation中执行已批准的有界故障恢复策略，但每次退役后重建使用新实例及新的运行绑定，保持closed并锁存自动化暂停。不存在持久恢复授权时只做保护／核对，不能自行签发管理员审批。旧实例历史查询始终可用，旧permit、secret grant、PanelSession、目录批准及来源年龄证据都不迁移到新实例。

### 15.2 ILC02：制品导入不执行扩展

制品入口与远程管理分开：独立Controller和Seamer发行物都提供本机`extension import`管理工具；Suite可调用同一宿主导入协议，独立Controller不依赖Seamer或一个常驻Suite服务。这里定义未来交付接口，本轮没有实现或运行该工具。

本机管理员为导入工具指定已有离线包和import_request_id；工具通过受保护的本机管理通道申请导入operation，复制到隔离区、核验并封存。业务HTTP只接受已签发intake_ref，不接受任意主机路径、URL、shell命令、npm包名或安装脚本。远程操作者先按部署运维通道传包到目标宿主，再导入；浏览器直接上传不是首期入口，README须写明这一步，不伪装为自动下载。

`ArtifactIntakeReceipt`固定：host_installation_id、host_trust_epoch、import_operation_id、intake_id、target_authority_service_id、manifest_digest、artifact_set_digest、package_bytes、file_inventory_digest、dependency_lock_digest、platform_profile_ref、validation_policy_ref、release_authorization_ref及verification_record_ref。清单逐文件含规范相对路径、字节长度、digest和角色；artifact_set_digest覆盖按规范路径排序的完整清单。不携带秘密或可供GUI直接打开的绝对路径，Receipt是服务向可信宿主查询的引用，客户端上传一份同形JSON不产生权威。

导入核验包括完整依赖闭包、许可清单、型号／平台声明、当前发行信任及撤销下界；拒绝路径逃逸、链接逃逸、Windows备用流／保留名及大小写碰撞，限制总字节、文件数、解压展开量和处理时间。拒绝隐式脚本和联网取依赖；只静态读文件，不加载动态库、执行entrypoint或调用插件自检。暂存目录在核验和封存前不可被加载，导入中断可清理未引用暂存物，不能删已有安装引用。

Receipt不是永久授权或文件耐久证明。stage及每次launch前重新核对目标host/trust epoch、固定字节、平台与当前撤销；信任检查失效或无法读出实物时保持closed。相同extension/version不同digest不得覆盖；内容改变须用新的版本标识及新的导入operation。重新导入同字节可返回同一不可变内容对象，但请求结果按原import_request_id查询，不能在结果不明时执行另一份包。

Suite的installation.db仅由本机安装管理器写；服务业务库保存其验证引用和扩展授权。两者通过各自持久operation及精确ref核对，不建立跨SQLite“原子安装”。程序／数据整组升级仍由DEP07处理，不能把扩展生命周期API变成覆盖Suite可执行文件的后门。

### 15.3 ILC03：管理HTTP和批准范围

管理请求只接受当前具备对应对象管理权限的human会话。浏览器侧复用精确Origin、human凭据和CSRF的共同核验；第三方面板、后台模块、普通service凭据不能直接调用本组接口。关闭保护由服务内部可信入口触发时有单独原因与审计身份，不伪造human。安装管理权不授予接管、设备动作或Seamer布防权。

管理受理POST共用`ManagementContext={authority_service_id,database_instance_id,identity_issuer_id,identity_epoch,auth_session_id,gui_instance_id,host_operation_id}`；服务从实际认证核对前六项，完整七元为幂等identity。intent_digest覆盖具名operation、规范路径、目标及其余完整语义body，仅排除顶层context；配置和权限内同名字段不递归删除。先以当前权限查幂等记录：同identity同内容返回原可靠结果，即使原CAS已过期；不同内容409。新请求才验证expected revision并串行占槽，不能用新revision复活原请求。第16节新增lookup是只读POST，body仅指定原identity，不建立新管理请求；当前认证仍独立核对。

| 接口（均在`/api/v1`下） | POST的额外字段／效果 |
| --- | --- |
| POST `/extension-slots` | extension_id、kind、display_name；创建空disabled槽位，服务分配slot_id，201／重复200 |
| POST `/extensions/stage` | slot_ref、intake_ref；验证同authority／host和内容后分配新installation_id，202返回operation，静态核验可异步 |
| POST `/extensions/{installation_id}/review` | expected_installation_revision、proposed_permissions、configuration_ref；与宿主manifest请求项逐项核对收窄，返回不可变PermissionReview，200，不授运行权 |
| POST `/extensions/{installation_id}/approve` | expected_installation_revision、permission_review_ref、approved_permission_ids、configuration_ref；核对当前管理员权限及请求项子集，生成新Approval，202 |
| POST `/extension-slots/{slot_id}/activate` | expected_slot_revision、target_installation_ref、approval_ref、dependency_plan_ref；选择已批准且从未激活的候选，202 |
| POST `/extension-slots/{slot_id}/enable` | expected_slot_revision、reuse_content_ref、permission_review_ref、configuration_ref、dependency_plan_ref；disabled槽位的新实例／新审批一体化受理，内容或范围变化返回409要求新审批，不静默扩大 |
| POST `/extension-slots/{slot_id}/disable` | expected_slot_revision、source_installation_ref、reason；先持久锁存disabled及拒绝旧实例，再执行关闭，202；已disabled且目标一致返回原关闭引用／无须动作结果 |
| POST `/extension-slots/{slot_id}/upgrade` | expected_slot_revision、source_installation_ref、target_installation_ref、approval_ref、dependency_plan_ref；target已staged并批准，固定新旧身份后先退役旧者，202；回退旧字节也走本接口和当前新审批 |
| POST `/extension-slots/{slot_id}/uninstall` | expected_slot_revision、source_installation_ref或null、dependency_plan_ref、reason；锁存removed意图，关闭所有该槽位未退役实例，202，不删除历史／配置／未决事实 |
| GET `/extension-slots/{slot_id}`、`/extensions/{installation_id}`、`/extension-operations/{operation_id}` | 按当前对象读权返回SlotView、InstanceView、OperationView；不产生启动、重试或重新审批，200 |
| POST `/extension-slots/{slot_id}/plan` | expected_slot_revision、selection对象，含kind=`activate|enable|upgrade|uninstall`、source／target／reuse引用、configuration_ref；返回固定DependencyPlan引用及完整影响，200；不改运行，不隐式创建新安装 |
| POST `/extension-operations/lookup` | 原七元identity；当前认证和对象／请求归属读权核验后返回原固定结果快照，200；解决首次响应丢失导致未知slot／operation ID，不重发或另建操作 |

DependencyPlan含计划用途、slot/dependency revisions、source/target或reuse refs、配置摘要、受影响设备／来源／面板／定义／run／排期、受保护资源及当前未决命令引用、预计暂停范围、平台／策略引用和固定单调截止。摘要绑定完整具名内容，不含自身digest。计划不是许可，受理时在writer内核对当前修订及完整依赖闭包；并发新增依赖必须推进dependency_revision，否则属于协议缺陷。新epoch或已到期拒绝消费；升级过程中新增退出／屏障证据另附，不反写已批准计划。紧急disable不等待人读完计划或依赖查询成功，直接走完整保护捕获。

权限条目必须具名且类型化：device_scope、data_scope、network_endpoint、secret_role、filesystem_root_role、helper_artifact、panel_method和protocol_io各自具备request_id及精确对象／用途／约束。approved_permission_ids是完整manifest请求项的子集，不能另带未申请的自由JSON权限；需要收窄某项时先产生新的review及精确约束。secret仅角色和引用，不返回值；网络端点不允许由面板临时传URL替换。管理请求、审批者当前能力和当前全局拒绝下界共同校验，不能把review有效等同设备可写。

OperationView公开phase=`accepted|verifying|awaiting_approval|closing|awaiting_retirement|reconciling|launching_closed|completed|rejected|failed_closed|indeterminate`、固定目标引用、关闭／退役证据摘要、完成结果与有界blockers分页；不暴露秘密或本地文件路径。blockers不得截断成“无阻塞”，有总数和继续游标。202只表示已受理；completed只证明本operation声明的结果（如disabled／removed／active_closed），不代表设备成功、ready或自动化布防。运行readiness通过独立具名字段及证据表达。

401／403为当前身份或权限失败，404只表示当前读权下不可见，409为内容冲突／CAS／依赖变化，413为资料超预算，422为非法候选／不支持组合，429为普通准入配额，503为当前无法确定或持久化失败。错误不能证明原请求从未发生；通信丢失／COMMIT未知只能查原identity或operation，不自动换host_operation_id重做。响应均no-store。关闭保护有独立预留容量，不能因普通安装队列已满而漏掉内部撤销。

### 15.4 ILC04：状态转换与三个独立完成条件

安装实例状态与operation阶段分别持久，不把“operation超时”直接写成实例failed。允许的主要转换如下；表外转换拒绝。

| 实例原态 | 条件／动作 | 新态与边界 |
| --- | --- | --- |
| staged | 静态实物及信任核验通过 | verified；无owner／出口、未启动任何扩展 |
| staged／verified | 不合法或当前批准者拒绝 | rejected；终结本实例，可保留审计及隔离字节 |
| verified | 当前审批同内容、同配置、范围子集通过 | approved；不是启动许可 |
| approved | 受保护实物就绪并固定配置引用 | installed_disabled；尚未发行owner或外部启用 |
| installed_disabled | activate CAS成功且全部当前门控满足 | activating；先持久登记owner／全部出口，再允许监督启动 |
| activating | 新域准入、只读连接及基线成立，写仍closed | active；只表示扩展就绪，控制ready／自动化资格另外判定 |
| activating／active | 停用、失去批准、替换或需重建运行身份 | revoking；先拒绝并完整捕获，不直接failed或disabled |
| approved／installed_disabled | 停用或卸载，证明无owner／出口 | revoking；以完整空捕获集完成，仍落拒绝墓碑 |
| revoking | 全部关闭目标acknowledged | disabled；拒绝墓碑保留，设备在途／unknown及资源未决可仍存在 |
| disabled／rejected | 无活跃可执行入口、原子组退役或从未启动有证、无加载引用 | removed；保留身份、审批与所有未决记录，不等于数据已擦除 |

静态安装失败且证明从未登记／启用外部出口时，可终结为rejected并把operation记failed_closed；一旦可能启动，必须进入revoking并核对原运行域，未知不能靠“进程没响应”删掉。已disabled、removed或rejected的实例绝不回到activating／active；重新启用使用新实例。active的authority或监督器重启也先保护并核对，不能依据旧active行自动开闸。

三个条件分开：①`closure_complete`是原拒绝及完整出口关闭批次持久成立；②`runtime_retired`是全部原监督域／加载引用不可再运行，有可信证据；③`resources_reconciled`是每个受影响设备／来源的未知结果和资源按既有恢复政策核对。关闭可以先完成①，卸载可在①②后撤可执行入口并保留③未决；升级／重新启用与受影响资源冲突的新writer必须等①②③。人工强制接管不绕过未知资源证明，人工核对只能按既有具名恢复操作追加证据，不改原unknown终态。

原子组终止不证明外部厂商daemon、远端NodeCG或设备持续动作停止。需要这些事实的资源保留blocker。纯面板替换可在自身①②后重开新挂载，已受理设备命令仍可查询且保持正常设备资源规则；不能把面板替换扩大为撤销独立组织run。后台设备／来源替换必须暂停相应run与排期资格，待新实例核对后仍不自动重新布防。

### 15.5 ILC05：事务边界及崩溃恢复

服务writer的安装管理事务按如下职责合并DF04，事务中不读网络、启动进程或解包。业务批准库与宿主实物库仍独立。

1. **受理事务**：核对当前认证、完整幂等identity、intent摘要、slot／安装／依赖revision；占用槽位生命周期槽，保存固定operation、目标、审批或计划引用、audit和outbox。已获批准的异步任务按固定范围继续；批准或权限被撤销时撤销传播仍能截断未启动目标。网络断开本身不取消已受理操作。
2. **拒绝事务**：CAS槽位desired_state，禁止该槽位产生并发新实例授权；对精确源安装执行既有完整fanout事务。uninstall捕获全部非终结安装候选及全部旧未关闭出口，不只取current指针；关闭批次分别保持不可变，父operation聚合完整实例集合。批准撤销也按实际批准引用捕获所有关联实例；同writer中新批准先提交则被捕获，撤销先提交则不能签发。
3. **证据事务**：验证原域／出口／selector的关闭及退役证据，追加记录并推进目标和operation；未知、超时或证据落库失败保持未完成。关闭下界和墓碑不因取消升级、用户退出或新版本失败撤回。outbox仅重送保护、查询及有界管理任务，不重投设备DISPATCH或旧按钮。
4. **选择事务**：旧实例①②和需要的③满足，且目标当前审批／实物引用仍合格时，CAS选择完整新installation／configuration refs；记录新runtime launch意图，commit后才申请监督启动。文件摘要与加载之间的替换必须由受保护不可变根和启动器核验共同防止，DB选择不能独自保证实物。COMMIT未知先查原operation，不猜测current指针或重建空库。
5. **启动与完成事务**：按新LaunchIntent核对宿主实际启动证据、owner／出口预登记及基线；只发布closed状态。持久完成后可释放槽位管理占用，但不释放任何业务资源／holder。失败保持failed_closed或indeterminate并列准确原因，依赖自动化保持暂停。

升级在拒绝切点之前可取消待执行管理意图、保留原健康实例；切点之后取消只停止启动目标，槽位留disabled／protected，不能回滚拒绝。下一次恢复必须是新的明确管理operation。升级失败后不自动启动旧产物；用户选择回退也要当前发行授权、新实例及新审批，不降低版本／撤销信任下界，不恢复旧数据快照。

崩溃恢复首先读持久拒绝集合、未结束operation、全部旧出口及监督域，再接收新管理请求。没有可信退役证据的新worker不能替旧者签空账本；源批次未知则保留indeterminate。数据库存在而文件缺失／摘要不同保持closed；文件已导入而业务受理未提交时仅为未引用制品，不执行。removed指逻辑不可加载，实际文件回收另设GC任务：须无活动、加载、待恢复、审批取证保留引用才可删对应内容对象；共享同digest的另一安装不得受影响。配置删除、秘密轮换和历史保留是单独具名操作，不捆绑为卸载的隐式副作用。

launch任务本身也必须幂等：固定launch_intent_id先由监督器登记，再创建受监督组；响应丢失只查询该意图及实际组，不能因outbox重送再次创建进程。确认原组不存在且可证明从未创建时才允许同意图继续创建；无法证明则indeterminate。有界故障恢复另建新实例／launch意图并保留原退休依赖，不能以重新投递同意图实施隐式重启。

### 15.6 ILC06：验收与本轮交付界限

以下ILCT01—ILCT24都是实施后验收规格，**本轮未运行**。它们补充MX01—MX40、PSF01—PSF12和DPT41—DPT48，不替代既有运行用例。

| ID | 前置／注入 | 必须成立的结果 |
| --- | --- | --- |
| ILCT01 | 同字节停用后重新启用 | 配置／逻辑slot保留，新installation及审批；旧拒绝和许可不复活 |
| ILCT02 | 直接将disabled实例改active | 拒绝转换，即使提交原批准和新的revision |
| ILCT03 | 重新启用增加设备或网络范围 | 不能用旧review静默批准，要求固定差异及当前审批 |
| ILCT04 | 仅安装管理员尝试设备写或布防 | 安装已批准仍按动作／run授权拒绝，不借安装权升级权限 |
| ILCT05 | forged intake JSON、另一host或旧trust epoch | stage或launch核验失败，无模块加载 |
| ILCT06 | 包内逃逸链接、路径碰撞或展开超预算 | 导入拒绝且不执行脚本，不覆盖现有产物 |
| ILCT07 | 两次stage或激活同幂等identity | 同内容返回同operation；换内容409，不多建安装／worker |
| ILCT08 | 同请求重试时slot revision已因原提交变化 | 先查原幂等结果，不能仅以旧CAS判未受理并重做 |
| ILCT09 | 两管理员并发升级同slot | 一方受理，另一方CAS或占槽冲突；无双writer |
| ILCT10 | 计划生成后新增依赖run或改变配置 | dependency_revision／内容校验拒绝消费旧计划 |
| ILCT11 | 停用时普通队列满、依赖投影查询失败 | 内部保护仍捕获完整实例／出口；不能截断或静默放行 |
| ILCT12 | 全在线ACK但有离线旧出口 | closure_complete为false；indeterminate和证据目标保留 |
| ILCT13 | 出口已关闭但设备命令unknown | 可disabled，不能据此宣称resources_reconciled或新writer可用 |
| ILCT14 | 全子进程退出但远端持续动作未决 | 不把runtime_retired当设备释放证据，相关blocker保留 |
| ILCT15 | 纯面板卸载且独立组织run正在运行 | 只撤该安装挂载；不凭卸载取消独立run或释放holder |
| ILCT16 | 卸载时旧版未决，新版staged尚无owner | 父operation仍完整覆盖两实例，未知历史保留；新候选不可后续激活 |
| ILCT17 | 升级已拒绝旧者后新者启动失败 | 留closed，不能自动复活旧实例或补执行旧动作 |
| ILCT18 | 拒绝切点前／后取消升级 | 前者可保留原实例；后者只停新启动并保留拒绝 |
| ILCT19 | 批准撤销与enable受理两个提交顺序 | 新审批先提交则纳入撤销；撤销先提交则拒绝同失效review／范围 |
| ILCT20 | 实物已导入，业务commit前崩溃 | 重启只保留隔离内容，无权执行；按原operation查结果 |
| ILCT21 | 选择新实例commit后响应丢失／断电 | 只核对原operation和实物，不混代、不另签许可 |
| ILCT22 | 原监督域证据缺失，启动新的空worker | 不核销旧出口，保持保护；新boot不能冒充旧世代 |
| ILCT23 | 两安装共用digest，卸载其中一个 | GC不能删另一安装仍引用的字节；历史审批／未知证据不删除 |
| ILCT24 | 独立Controller离线导入后完整手动控制 | 不要求Seamer／常驻Suite服务；同时满足当前安装、目录和用户动作权，自动化资格不凭启用取得 |

本节初稿完成字段、路由、权威归属、状态和故障验收设计；后续第16节已有封闭Schema／OpenAPI及局部正反例。完整manifest／内部导入协议仍须与安装fanout、runtime启动意图和完整DF04领域DDL同版联校。ILCT生命周期运行测试尚未执行，旧面板参考检查即使回归通过也不覆盖ILCT。当前候选不关闭C09或阶段0，不进入业务实现。

## 16. 安装管理Schema与OpenAPI候选

2026-10-18新增[安装机器候选](contracts/c09-installation/README.md)，版本extension-installation/0.1.0-draft.1。14个操作共11个POST和3个GET，修补权限收窄提案及首次请求结果查询入口。八类Permission、四用途DependencyPlan、Approval、IntakeReceipt及Slot／Instance／Operation／BlockerPage已有封闭格式；全部Ref为本候选具名kind、authority/database、object_id、revision和带前缀digest，属于新版候选，不替换旧面板或公共draft.4的Ref。

PermissionReview是待批准提案，approve从其精确收窄内容选择，不按相同request_id回查原始宽权限。Plan固定完整影响与单调截止；BlockerPage绑定固定Operation快照，不能将新phase和旧页拼接。lookup返回原可靠结果快照，当前主体需有原请求归属及对象读权；旧auth_session仅为查找键，不能代替当前认证。原结果中的accepted不自动变成完成，仍按operation查询当前状态。

219项离线结构／OpenAPI模型接受集对照、权限与审批、计划摘要及绑定、局部状态、幂等与分页检查通过。摘要实际按JCS计算，可信上下文、安装实物及证据仍为人工前提。生成器仅生成契约资料，未实现安装服务、内部import或完整生命周期执行器；ILCT01—ILCT24仍未运行。完整manifest／文件清单／导入IPC、字段提供者、配置投影及预算、运行绑定、证据全量分页与生产DDL继续归并，候选待审阅，阶段0不关闭。

## 17. 扩展包角色解析与本机导入

2026-10-18推荐细化：[扩展包与导入候选](contracts/c09-artifact-import/README.md)给出Manifest、FileInventory、RoleDeclaration/Binding、八种PermissionTemplate、RoleResolution及ResolvedReview，另有九类本机IPC消息。格式唯一源生成两份Schema，独立于worker IPC及旧14个安装HTTP；本节及附属资料仍待审阅，不切SDK权威。

**跨项修正**：第15／16节“manifest提供requested_permissions”不能理解为分发包硬编码本机设备／秘密ID。包声明用途角色及模板，管理员在固定配置修订下选择本地对象，由目标服务可信提供者核对并纯函数解析；包代码不能参与授权。RoleResolution固定manifest、文件集合、配置、安装及最终权限，摘要覆盖除自身digest外的全部内容；ResolvedReview固定该解析与原review的对应。未来同版HTTP／Approval／LaunchIntent须引用这份关联；旧结构不暗加字段，生成新局部Schema不等于整链路已经接通。

包根控制文件与payload清单分开，manifest→inventory→逐文件原字节构成无环摘要链，整ZIP摘要另供发行授权。角色模板不含任意exec、路径、下载URL或字符串插值；worker/helper入口只指已声明的固定文件和policy。包内文件名采用portable-ascii/1，展示内容仍可多语言。完整依赖锁／能力模板的内部模型、真实解压和平台路径／加载核验仍须DF05/C09归并，不能只见文件清单就批准运行。

导入工具经受保护本机IPC登记只读文件句柄；source_attachment_id只对该连接有效。三元ImportIdentity持久唯一，intent仅排顶层attachment，允许重连换句柄查询同包原操作；换包／目标／信任代不借同ID重建。当前peer与管理权先于幂等查询。accepted先落账本，再复制隔离、完整静态验证、物化及文件／目录耐久屏障，最后installation.db提交sealed收据；任何阶段均不启动入口。业务SQLite不能与该安装库假装原子提交。

取消与sealed由同writer排序，提交未知查原operation且不换ID。已知sealed历史与当前实物可用性分离：文件后来丢失或信任撤销只使当前IntakeQuery不可用、启动拒绝，不能把历史改成未发生。物化核验回显完整challenge及LaunchIntent摘要，使用发起方同域单调窗口；verified仅是观察，load前仍需当前信任和不可变内容根检查，不授设备发送或ready。

正常轨迹：管理员登记包句柄→持久accepted→隔离复制并核包字节→逐文件／发行核验→物化和耐久→sealed→业务stage→角色解析→review收窄→approve→固定启动意图与实物再核验→关闭状态启动。故障轨迹：物化后DB响应丢失→原identity查询→核对唯一提交结果；若文件随后丢失，保留sealed历史但返回当前unavailable，禁止换实例绕过信任或启动。

181项离线参考覆盖局部结构、文件元数据闭包／摘要、八类角色解析、重算摘要后错绑、原identity幂等、收据／消息关联、有限恢复及物化时间边界。这里不解析ZIP、不执行FD传递、完整依赖锁、IPC、SQL、监督器或设备；可信提供者均为合成前提。下列IAT是实施验收规格，全部未运行。

| ID | 具体故障与验收判据 |
| --- | --- |
| IAT01 | ZIP重复名、local/central差异、链接、ADS、大小写／父目录冲突均拒绝，隔离目录外无写入 |
| IAT02 | 实际展开大小／压缩比／数量／CPU超预算立即停复制，保护查询可用且账本保留 |
| IAT03 | 源句柄复制中被修改，最终包hash或bytes不符则拒绝；stat相等不冒充完整快照 |
| IAT04 | peer自报管理员、跨连接attachment及跨目标操作均拒绝；不能传任意路径或下载URL |
| IAT05 | 同identity换attachment同包返回原operation；换包／manifest／trust代报冲突，无第二次导入 |
| IAT06 | 角色缺失、错kind、混修订重复对象、跨authority、秘密无目标、helper跨包全部拒绝 |
| IAT07 | 解析后换配置／权限重新摘要仍拒绝旧review／Approval；完整身份和当前提供者检查不被hash替代 |
| IAT08 | materialize后、目录耐久前、DB提交前后逐点断电；只有可证明耐久且提交的原操作返回sealed |
| IAT09 | cancel与sealed两种提交顺序结果确定；COMMIT未知不伪装cancelled，不删除共享内容 |
| IAT10 | sealed后文件丢失／改变或发行撤销，历史不改写，当前不可用且启动关闭；业务恢复不回退信任 |
| IAT11 | 错channel、消息重复、错reply、跨LaunchIntent核验或到期等号均拒绝，旧响应不授权新启动 |
| IAT12 | 完整校验阶段不加载包代码；verified之后替换路径／依赖、改权限及新信任代均在load前拒绝 |

安装事务、完整字段提供者、依赖／能力格式、SDK同版归并、最终预算和平台证明继续保留为明确未完成项；本轮消除的是包与导入无具体格式的缺口，不关闭C09或阶段0。

## 18. 安装0.2与审批到启动关联

2026-10-18推荐：[安装0.2候选](contracts/c09-installation/LIFECYCLE_V02.md)将角色解析纳入管理HTTP和不可变审批链，生成15接口Schema／OpenAPI，并补ExtensionLaunchIntent、LaunchAuthorization及LaunchRecord内部模型。所有请求显式选择0.2接受集，旧0.1、draft.4及IPC0.3保持原样；新增内部启动对象不发布到管理HTTP。

本轮修正第15节enable的身份循环：旧review已绑定不可复用的旧installation，不能用它给未来新ID直接批准。0.2先以StageSource.retained复用仍合格的制品建立新候选，再resolve角色、review收窄、当前人员approve，最后enable固定新target与审批和计划。GUI可以一次确认流程完成，但服务端每条记录及绑定独立明确，不能迁移旧许可。Stage同时新增slot CAS；enable计划不再带reuse_content_ref，该字段在0.2恒为null。artifact_set摘要采用第17节FileInventory的file_id排序JCS，替代第15.2节早期路径排序描述，仅适用于新版本。

ResolutionView绑定解析记录ID／摘要和authority/database；review及Approval固定同一解析引用，新增permissions_digest覆盖批准的完整收窄Permission数组。角色解析只能由可信宿主提供者执行；公开重算摘要无法替代对象权限、配置修订和批准。运行中修改配置或范围须新实例，不原地改既有审批内容。

ExtensionLaunchIntent保留DF02启动字段并加入完整extension_binding，关联实例、审批、review、解析、配置、intake、平台、宿主信任代、扩展内容和入口及批准权限摘要。外层运行组合清单与内层扩展清单分开；device_ids来自完整权威足迹，不能仅取显式device_scope。完整新摘要贯穿bootstrap／HMAC／receipt，core/time_provider引导和纯静态panel不套虚构worker安装链。

LaunchAuthorization有同监督域单调截止及当前fence revision，实验寿命上限2秒；它只允许一次受监督closed创建，不签设备permit。监督器收到撤销前可能已创建closed进程，核心必须再次核当前审批后才登记active_closed；撤销完成须确认准入关闭及已创建成员退役，不能以过期代替组清空。VERIFY_MATERIALIZATION还须绑定完整launch摘要和原challenge窗口，单独“实物校验通过”标记不够。

LaunchRecord区分registered、creating、awaiting_bootstrap、admitted_closed、retiring、retired、rejected及indeterminate；creation_attempted在OS调用前记录。创建回执丢失、进程退出、组为空均不能重投同意图再创建；原查询和新创建分开。监督器本机journal不写业务SQLite，日志不可靠／旧域未知时进入保护恢复，不能重建空账本。正常链与故障事务见附属第5／6节，LACT01—LACT12全部待运行。

191项离线参考检查通过，包含新旧接受集、精确收窄摘要、配置／解析错绑、同launch重投、撤销、截止等号、实物错意图和局部创建账本。完整生产DDL、bootstrap与启动fence消息、journal布局和提供者／平台证明尚未完成；已形成关联方案不等于完整SDK或运行验收，候选待审阅，阶段0保持未关闭。

## 19. 完整提供者读集与失效衔接

[提供者读集协议](contracts/c09-providers/PROVIDERS.md)为固定panel4选择下35方法、23结果变体和181顶层字段规定统一进程内接口。14类派生提供者与直接来源root各有独立一次性票据；可信宿主事先固定完整来源列表、模型和ObjectRef，提交时核精确引用、规范字节摘要、来源校验及完整字段组。直接字段逐路径比较原件，派生字段仍须履行各自领域核验，不能因读集完整就跳过语义。

候选状态为reading、validating、sealed、consumed或invalid。任一必要提供者失败、截止或撤权使整个结果不可用，不返回部分编辑内容；慢来源及结果校验在锁外执行，返回时再核状态。实验上限为256来源、每组64、普通值256KiB、来源及累计分组1MiB，单读集寿命不超过2秒且不续期。跨服务原件不因共享snapshot_id而原子，须有正式本地采用及失效依赖后才能进入同权威读集。

本轮参考覆盖分派、来源替换拒绝、单次票据、部分失败和实际线程撤权，来源及结果Schema为明确合成配置；不把它计作14类生产提供者已实现。生产一致读取事务、来源／权限失效监听、页与评估句柄存储、真实领域适配、校验器硬限额和最终输出Gate仍须接线。consume只返回进程内值，必须在生产Gate内与最后授权复核串行执行，不能消费后无条件排队；本候选不关闭C09或阶段0。

固定模型配置进一步将读集接到panel4完整1463模型：精确method决定结果变体，来源和结果实际执行Schema与format验证；能力引用、观察值、定义内容／元数据及每条恢复摘要必须进入独立动态批准入口，缺入口即拒绝。来源当前权利和完整领域关联守卫也必须显式提供，不能把结构成功当授权。实际检查覆盖35方法／23变体结果、四类来源和三个读集正例，其中观察路径调用固定动态校验子进程；其余领域提供者与最终发送资格仍待真实适配，详细范围以[固定模型配置](contracts/c09-providers/PROVIDERS.md#固定模型配置与动态批准)和独立typed报告为准。

[进程内依赖失效协调](contracts/c09-providers/PROVIDERS.md#进程内依赖失效协调)将已登记依赖的撤销与托管读集消费置于同一串行锁。先关闭关联读取，再在锁外清理实际动态权威；构造、来源校验或结果校验迟到均不能恢复候选。撤权先取得锁时拒绝交付，消费先取得锁时允许完成一次本地返回；该规则不承诺追回已返回值或网络字节。157项检查含6个线程场景、35方法完整托管消费及实际动态权威封装后撤销。真实事件订阅、完整来源依赖提取、数据库一致读取和最终发送门仍待实现，阶段0继续开放。

[完整面板结果交付](contracts/c09-providers/DELIVERY.md)已有局部参考：原请求和当前上下文验证、host.result完整模型、64KiB帧上限、同锁消费与入队、排队依赖撤销、重新取权及单次非阻塞释放。35方法完整结果帧、三种线程竞态和两个本机TCP场景实际运行；sent_sequence只证明指定出口完整接受，不代表面板消费或业务完成。19类帧统一序号与保护队列、生产回执账本、真实浏览器端口和产品传输仍未完成；无完整投影的结果分支由后续回执入口补齐。

[无投影回执交付](contracts/c09-providers/RECEIPTS.md)补齐host.result的5类状态与14种有限原因，核验完整RequestIdentity和原意图摘要，两个输出入口共用不可倒退的受理状态登记。投影失败不等于业务未受理；已知accepted后只能使用独立当前回执表达accepted/unavailable，不能发送unknown_outcome覆盖原事实。完整19类帧、真实账本事务与浏览器输出仍待归并，未开始业务实现。

[回执账本只读快照](contracts/c09-providers/JOURNAL.md)新增隔离SQLite布局与读取适配：单事务取得不可变原请求、原意图和有界回执历史，重新打开后仍核完整身份、原摘要和状态不可倒退。实际文件库、WAL并发读取、新进程重新打开及撤权后停止输出均有独立验证；原件由固定用例构造，领域writer和身份认证为合成配置。真实业务提交事务、数据库迁移及留存、完整失效监听、浏览器输出和19类帧归并继续保留，阶段0未关闭。
