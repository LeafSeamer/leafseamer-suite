# C11：OBS／ATEM 全能力契约与完成证据

日期：2026-10-18。状态：**AV01—AV06为待审阅推荐**。本稿覆盖[旧设备映射](rebirth-legacy-device-map.md)的OA01—OA10、AA01—AA08，不替代已确认F06 OBS首闭环；进一步明确全部旧面板功能及协议库边界。未改业务代码或draft.4／IPC 0.3，未安装程序、启动服务或连接设备。

Controller负责模块、设备身份、最终发送及证据；SDK承载目录／参数／观察／错误和证据模型；GUI保留专用操作流；Seamer引用批准的能力和失败政策；Suite固定库、程序／固件及平台夹具。首闭环仅是实施顺序，不能替代本稿的完整能力范围。

## 1. 已知事实与工程分析

旧仓源码固定`5d60491d7158f87fc27b564f510d321074aedac9`，本轮核对HEAD一致。旧锁中的obs-websocket-js 5.0.7、atem-connection 3.7.0不是新版支持承诺。OBS参考继续使用[F06](rebirth-f06-f07-design.md)的obs-websocket 5.6.3与OBS Studio 32.0.4候选，两者实际发行物组合未验证。

| 静态事实 | 官方来源与边界 |
| --- | --- |
| OBS场景项序号0为底；设置处理器还限制0—8192 | [SceneItems](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_SceneItems.cpp#L607)。新版仍须按当前容器实际项数进一步限制。 |
| OBS转场设置按名称查找，名称不保证唯一；可调时长范围50—20000ms | [Transitions](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_Transitions.cpp#L118)。有UUID目录不意味着每个写接口都接受UUID。 |
| OBS媒体seek要求playing或paused，只检查非负，不按实际片长限制；媒体动作调用后返回成功 | [MediaInputs](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_MediaInputs.cpp#L89)。ACK不证明跳到目标或播放指定文件。 |
| Start/StopStream调用前端函数后返回；设置推流目标在正在推流时拒绝，同类型设置合并旧字段 | [Stream](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_Stream.cpp#L91)、[Config](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_Config.cpp#L521)。开播与改目标不能隐藏成一次原子动作。 |
| 旧VLC列表按钮改playlist[].selected并标Playing；候选OBS的vlcs_update只读取条目value，不读取selected，更新还会停止并重建媒体列表 | [旧UI](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/obs-control/src/dashboard/obs-control-panel.tsx#L505)、[官方VLC源](https://github.com/obsproject/obs-studio/blob/32.0.4/plugins/vlc-video/vlc-video-source.c#L549)。不能从该写入证明指定项正在播放；尚未运行复现。 |
| ATEM库3.7.0外层发送等待使用Promise.allSettled，未把内部拒绝重新抛出；state读取是本地缓存 | [固定源码](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/atem.ts#L192)。fulfilled不能直接证明packet ACK；缓存不等同OBS式后置查询。 |

工程分析：功能名称相似不代表证据相同。OBS request response、ATEM可靠UDP应答、插件动作完成和画面输出必须分开。以下推荐不把底层缺失能力“补成true”；保留真实指定媒体播放、完整ATEM控制等交付目标，缺口列为设计／实现门槛，不以按钮存在视为完成。

## 2. AV01：共同目录、参数及观察身份

设备配置使用逻辑device_id，多连接不以IP或显示名当永久身份。端点／凭据／协议／型号改变先维护、闭闸、重建session及绑定；仅改显示名不重建设备。启动连接只认证、发现与采样，不恢复控制权、组织授权或布防。连接删改须显示依赖和未决命令，不能删除账本来清unknown。

候选`DeviceCapabilityProfile`固定profile_id/revision/digest、模块及库artifact、实际device_model/firmware或OBS版本、protocol_revision、endpoint_identity_binding、transport_policy_ref、catalog_digest、supported_actions、parameter_schemas、evidence_policies、footprint_refs、limits_profile_ref、qualification_refs。未取得实际型号／版本证据时只发现不发布已批准写能力。设备自报版本不是产物来源证明，分别登记。

| 引用／记录 | 必需字段与不变量 |
| --- | --- |
| ObsSourceRef | F06 collection_ref/generation、device_session_id、catalog_revision、input_id、obs_input_uuid、input_kind及其版本profile；不同场景中的同一input合并物理资源 |
| ObsItemRef | collection绑定、container_uuid、container_kind=`scene|group`、scene_item_id及item_binding_revision；另存source_uuid关系；项ID不能跨容器使用 |
| ObsTransitionRef | collection绑定、transition_uuid、当前精确name、kind、transition_catalog_revision；名称写接口只允许当前唯一匹配且UUID对应的对象 |
| AtemTargetRef | device_session_id、topology_revision、protocol_version、model_profile_ref、kind及零基协议坐标；输入用实际source ID，不把显示序号当ID |
| DeviceObservation | C05来源身份／序号、quality、raw_ref、target_ref、value、sampling_policy_ref及年龄证明；last_known与current分离，unknown不能填false或0 |
| DeviceActionEvidence | command/attempt/operation引用、会话／目录／profile、实际发送记录、协议应答、观察集合、谓词、评估期限和释放policy引用；字段自报不授予权威 |

安全整数参数在JSON中为integer；修订、单调tick及不可用JS Number表示的计数沿DF01十进制串。任何设备返回超过安全范围的数字不得先舍入再转换，原始解析按SDK词法规则处理。媒体时间用非负整数毫秒，未知duration/cursor为null；ATEM转场用帧，不按浏览器FPS换算。有限范围、枚举和默认值均进入目录摘要与GUI，不在运行时猜单位。

OBS集合切换与重连沿F06使绑定失效；Input移除、Item替换及目录缺口同样失效。ATEM重连／拓扑／视频制式／固件变化重建相应批准，ME不在目录则拒绝，不能默默回落ME0。对外观测源无可信年龄证据时只显示，不作为合格自动化事件；断线不造“停播”“输入0”或“宏结束”触发。

## 3. AV02：OBS 动作与GUI完整映射

以下动作是候选SDK目录名，参数均含目标引用和当前批准profile；所有写经唯一出口，默认retry=never、仅派发前取消。只读API同样鉴权、受容量和集合切换限制，不能偷偷执行初始化纠正。

| 动作／用途 | 参数及协议映射 | 结果／资源／GUI边界 |
| --- | --- | --- |
| `obs.program_scene.set` | SceneRef；SetCurrentProgramScene(sceneUuid) | F06四帧仍适用其Cut夹具；GUI单击只本地预选，明确Switch才执行 |
| `obs.transition.set` | ObsTransitionRef；SetCurrentSceneTransition(精确name) | ACK＋新GetCurrentSceneTransition UUID相符，只证选择完成；重名或改名冲突拒绝，不按首匹配发送 |
| `obs.transition.duration.set` | duration_ms整数50—20000；当前非fixed转场绑定 | ACK＋后读duration相符；不对fixed转场发送；作为明确配置动作，不声称旧面板已有时长控件 |
| `obs.program_scene.switch_with_transition` | SceneRef＋TransitionRef＋可选显式duration_ms | 固定operation：选择转场→可选时长→切场景；每步独立permit和证据，部分完成不回滚转场 |
| `obs.stream.destination.set` | service_type固定rtmp_custom，server、use_auth、key_secret_ref及按需username/password_secret_ref；expected_config_revision | 不含明文秘密；目标及凭据修改单独授权，要求已验证非推流状态；ACK＋受保护后读比较配置，未匹配不进入开播 |
| `obs.streaming.set` | active:boolean；StartStream或StopStream，禁止ToggleStream替代 | ACK＋后置GetStreamStatus目标active；启动还要求非reconnecting；只证OBS输出状态，不证远端平台收到流 |
| `obs.stream.configure_and_start` | 固定目标配置引用与active=true | 保留旧一键用途但展示两步；改目标成功、开播失败时明确部分完成，不自动恢复旧key或补开播 |
| `obs.scene_item.enabled.set` | ObsItemRef、enabled:boolean；SetSceneItemEnabled | ACK＋后置GetSceneItemEnabled；输入媒体可能因显隐激活，足迹不能只写可见标志 |
| `obs.scene_item.index.set` | ObsItemRef、index整数0..min(item_count−1,8192)、expected_order_digest | ACK＋新GetSceneItemList／Index核对；占整个容器顺序，GUI反序映射在边界转换，不逐帧发拖拽写 |
| `obs.media.action` | ObsSourceRef、action=`play|pause|stop|restart|previous|next` | TriggerMediaInputAction显式枚举；previous/next仅批准VLC或具同等能力的类型。后读mediaState不能证明上一／下一或restart确已发生 |
| `obs.media.seek` | ObsSourceRef、cursor_ms、media_binding_revision | SetMediaInputCursor；playing/paused、片长已知且0≤cursor≤duration，动态／直播源未知片长不伪造可seek范围 |
| `obs.input.settings.patch` | ObsSourceRef、settings_schema_ref、expected_settings_digest、typed_patch | SetInputSettings overlay=true，限定批准字段；现有值与默认合并的语义按输入类型profile固定，禁止settings:any通配授权 |
| `obs.vlc.playlist.read` | ObsSourceRef | 返回受权限过滤的条目及配置revision；selected只是配置字段，不能作当前播放证据 |
| `obs.vlc.playlist.item.play` | ObsSourceRef、playlist_revision、稳定item_ref、播放语义版本 | 必须真实选择并证明当前条目，见AV06缺口；不能实现成改selected后显示Playing，也不能暗中改列表顺序 |
| 只读目录／采样 | Scene/Input/Item/Transition列表、GetMediaInputStatus、GetStreamStatus及受限Settings | 集中轮询，有界订阅；不能因多开面板倍增设备查询，不广播完整stream settings／文件路径／URL凭据 |

媒体文件可被多个场景引用，resource按input UUID合并；Item排序占容器，转场与节目切换关联program/transition，推流目标与输出关联stream/config。场景切换、显隐和任意设置的间接媒体／音频效果无法证明完整时，footprint保守占整设备且禁止F07独立失败继续；首期整设备手动接管始终不变。

配置读取缺字段与秘密不可读分别返回unavailable／redacted，不能用空串覆盖设备已有凭据。use_auth=false时其余凭据字段的保留／清除必须显式语义并在固定profile验证，不能依赖OBS同类型merge的隐式旧值。已经active的Start或已inactive的Stop不使用Toggle；按预检返回稳定`already_target`拒发说明，不能伪造四帧成功。本轮不新增未发送succeeded的机器状态。

输入设置仍保留旧Get/Set用途，但只开放已审阅输入种类／字段；VLC列表、ffmpeg local_file等路径均是OBS宿主资源，不由Controller按自己文件系统解释或擅自上传。输入改变可发起OBS宿主外连、停止／重启媒体，属于控制效果；同一输入类型的未知插件扩展字段不能当作无害JSON转发。

expected digest只用于拒绝已经观测到的前提冲突，OBS协议没有与这些写原子绑定的跨客户端CAS。读到旧值到实际写之间原生GUI仍可能改变配置，必须在UI和自动化profile中报告该窗口；后置不符暂停，不循环读改写去覆盖现场。列表／顺序变化不能在旧operation中重新解析成另一个目标，重新选择必须建立新请求与授权。

媒体seek成功谓词必须按来源定义：paused且静态文件可比较目标位置和经测量的解码量化容差；playing的游标随时间前进，不能要求永远等于目标，也不能仅凭“已经超过目标”证明seek。无当前条目身份、速率／循环边界及可靠采样时，只能报告accepted层级，不能批准依赖精确seek完成的自动化。容差来源是固定媒体／解码器夹具，不把任意500ms写成通用默认。

非Cut节目切换需独立profile，绑定当前转场、场景覆盖、Studio模式及画布。转场start/end事件与后置Program查询、库无待发写记录组成候选证据；事件可能先于ACK，按本地io_seq记录实际顺序，不强行套F06四帧。丢失开始／结束、外部并发转场或配置改变时不通过；单次cursor=1不能证明刚才这次转场已完成。Studio／多画布未设计的写入口保持明确未冻结，不伪装已支持，也不自动改现场模式来满足夹具。

## 4. AV03：ATEM 动作、拓扑与复合控制

ATEM库参考固定`atem-connection@3.7.0`提交`3e11369e2937931c88453ce65e44fb6c406ce392`；该库是Sofie-Automation的第三方实现，不能当Blackmagic对UDP语义的保证。实际型号／固件及视频制式仍须逐组合取证，源码中的枚举或旧UI标签不形成产品支持矩阵。

| 动作／用途 | 参数及映射 | 结果／资源／GUI边界 |
| --- | --- | --- |
| `atem.program.set` | AtemTargetRef(me)、source_id；changeProgramInput | 目标在该ME可选输入中；PGM写独立于PVW，不将拖放PGM解释成预选 |
| `atem.preview.set` | 同上；changePreviewInput | GUI点击或拖放PVW的真实设备动作，区别OBS本地预选 |
| `atem.transition.cut` | 明确me、预期PVW／PGM及当前转场背景／key选择绑定；cut | 一次动作会改变多个状态，非简单设置目标源；禁止自动重试 |
| `atem.transition.auto` | 同一ME与明确转场绑定；autoTransition | 只启动设备转场；需专属结束证据，不能等固定100ms当完成 |
| `atem.transition.mix_rate.set` | me、frames整数及对应型号／制式批准范围；setMixTransitionSettings | 单位帧；旧滑条1—125与数字框1—250差异按profile统一，不从一个byte编码推断完整合法范围 |
| `atem.aux.source.set` | aux_index零基、source_id；setAuxSource | aux目录实际可用数量及可路由source集；标签来自型号／用户命名，不固定Output/Webcam |
| `atem.macro.run` | macro_index零基、macro_catalog_revision、批准内容／足迹引用；macroRun | used/name不是稳定内容身份；单次启动非宏完成，未知宏占整设备 |
| `atem.program.take` | me、source_id、method=`cut|auto`及转场绑定 | 旧卡片固定operation：PVW设目标→效果核对→CUT/AUTO；取消未发后继，部分完成保留PVW改变 |
| 只读拓扑／状态 | 连接初始化及stateChanged投影 | 实际ME、inputs、aux、macro与转场信息分开；缓存陈旧不能充当fresh query |

所有ME参数显式给值，不缺省偷用0。只有ME0观察的实现不能发布多ME写能力。source_id允许内部色源、媒体等实际目录项，不假设连续1..N；不同目标的route可达性独立校验。宏目录必须保留未命名但实际可用与不可用原因，不能因旧UI只展示有名宏就认定未命名宏不存在。

CUT/AUTO可能涉及background及上游key转场，完整足迹未知时占整设备；ME边界不是独立性证据。AV03的旧source.set可在SDK迁移映射到明确PGM/PVW/Aux动作，旧字符串destination不得靠未识别时回落默认路由。换型号／固件／视频模式作废动态范围和转场profile，不重解释已受理计划。

宏是设备内程序，连接断开、worker终止或启动ACK均不能停止它。初期保留独立手动启动及执行状态展示，自动化中需要宏完成的步骤必须有经过审阅的内容范围／run状态证据及释放policy；缺证据时该组合不能布防，不把一次ACK标成required动作完成。停止宏若新增，作为单独动作逐型号审阅，不把disconnect包装成取消。

## 5. AV04：传输应答、重传与证据政策

OBS保持具名Request白名单；禁止以RequestBatch、hotkey、vendor或自定义事件绕过逐次发送许可。可支持的辅助vendor请求需像普通action一样固定Schema、目标、资源与专属profile，不开放任意vendor透传。WebSocket底层已提交字节属于in_flight；应用重连不重发旧request，协议requestId并非设备端幂等键。

ATEM全部自动发送、重传及工作线程路径必须纳入TransportAdmissionProfile。不能只包裹changeProgramInput等顶层方法，随后让库私自排队／重传越过最终出口。3.7.0外层Promise的allSettled缺口必须修复或通过受审阅适配显式读取每项失败和实际ACK，不能把catch未执行当成功。

固定库源码还给出以下事实，数值只描述旧实现，不推荐作生产预算：

| 传输事实 | 对冻结方案的影响 |
| --- | --- |
| 子线程保存完整payload后可重传；超时60ms、检查10ms、重试常量10，实际判断为resent≤10；设备RetransmitRequest路径不检查该上限 | 不能把60ms×10当严格排空时间；重复请求与后续包连带重传须验收。[固定子线程](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/lib/atemSocketChild.ts#L358) |
| restart清空_inFlight并重建session；disconnect关socket及两个interval但不立即清_inFlight，NanoTimer ACK尾部另存 | 队列消失不证明设备没执行，关闭须覆盖全部异步尾部并区分纯ACK和控制payload。[关闭／重建](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/lib/atemSocketChild.ts#L126) |
| socket层会合包，threadedclass配置autoRestart并在重启后connect | 每个业务primitive固定到可追踪packet，禁止把不同permit的动作合为一个未分账发送；子线程重启不得绕过监督域与重新开闸。[socket实现](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/lib/atemSocket.ts#L107) |

3.7.0发布tarball的内存SHA512核验与旧lock及npm元数据一致，且dist也含allSettled；该检查只证明本次读取的发行内容一致，没有运行包代码、安装或真机验证。

同一ATEM packet的协议重传不同于新建一次CUT/AUTO调用，但仍是库层的再次send。推荐在每次实际控制datagram发送前通过同设备发送闸；原attempt记录packet/session、重传ordinal和每次发送，禁止生成新动作身份。屏障／撤权／截止禁止尚未发出的控制重传，已提交datagram仍属in_flight；设备可靠性如何受中止影响须专项故障验证。keepalive／纯ACK／握手按C09已批准维护IO分类，不给夹带控制payload的包豁免。

协议重传所需许可表达及完整账本须下一版与F02联合归并：重传不允许用已消费permit再次授权，也不为相对动作自动创建新的应用attempt。若库不可提供逐发送门控、待发队列清单和停止证明，则该固定库组合不能获准可写；保留功能实现任务，改造受控传输适配，不降低接管要求。

推荐新增受限`TransportResendPermit`候选：绑定原command/attempt、原已发送packet字节digest、当前session／协议序号、单次transmission_id、递增ordinal、总预算及不晚于原发送截止的expires。仅精确重复原packet，不能变payload或重新调用高层动作；每次准入单独消费并进入屏障账本，关闭后不再签发。设备对重复包是否只应用一次仍需协议与实测证明，不能因本地身份相同宣称恰好一次。此为明确新增契约，现有IPC不假装支持。

| 政策候选 | 必需证据及禁止推断 |
| --- | --- |
| OBS固定设置 | 原请求成功响应＋同会话后置读取＋目标／目录匹配＋无剩余应用写；沿F06期限与可靠落账。配置effect不等于画面／音频正常 |
| OBS媒体动作 | play/pause/stop可在固定输入profile核对状态；restart/previous/next必须另有当前媒体身份／世代证据。通用GetMediaInputStatus不足以证明这些动作发生 |
| OBS开停播 | 原响应及新输出状态，绑定stream profile，启动非重连；远端平台接收另验，不把输出字节增长当观众画面证据 |
| ATEM传输ACK | 精确session／packet与tracking ID映射及真实ACK记录；只证协议传输层，不能直接作effect_verified |
| ATEM设置效果 | 当前型号profile验证设备状态反馈的顺序与新鲜度、目标字段、完整发送排空及无配置失效；仅库state缓存相等不够 |
| ATEM转场／宏结束 | 上述条件外加相应执行代及结束状态，不能用duration定时器或一次idle快照代替；缺关联保持unknown／unresolved |

ATEM本参考库没有PGM/PVW/Aux/rate/macro的OBS式Get往返，requestTime不是动作因果屏障。推荐补专属设备反馈证据方案并验证，而非伪造四帧查询。人工操作可明确显示传输ACK层级，但这不解除未知影响，也不让自动化将弱证据冒充效果成功；ActionDescriptor的完成要求由已批准政策固定，调用者不能临时降低。

精确状态路径为`video.mixEffects[me].programInput/previewInput`、`transitionSettings.mix.rate`、`transitionPosition.{inTransition,remainingFrames,handlePosition}`、`video.auxilliaries[aux]`及`macro.macroPlayer.{isRunning,isWaiting,loop,macroIndex}`，以[3.7.0状态定义](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/state/video/index.ts#L79)和[宏状态更新](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/commands/Macro/MacroRunStatusCommand.ts#L5)为准。旧桥读`me.inTransition`并把transitionPosition当标量，不能直接复用。key-only转场可以不改变PGM，宏isRunning=false也不说明所有宏步骤成功；资源和完成谓词必须覆盖实际选定层与宏语义。

对所有动作，明确错误只有在固定实现已证明调用前拒绝时才形成无效果释放证据；未取得该证明一律不能从错误字符串推断未执行。迟到完成只追加resolution，不改终态或重布防。本地进程／队列排空不证明设备内宏、转场和已送网络包不存在后效，资源释放另判。

## 6. AV05：触发、GUI、故障与验收

保留OBS scene.changed／streaming.changed及ATEM program.changed，并注册专门状态采样能力；事件和采样不同类型，初始化快照不制造变化。来源无可信新鲜度或目录失步时暂停相关自动化，显示last_known；ATEM缓存及OBS断线false不得变成确认事件。UI显示“受理、已发送、协议应答、效果核实、未知、保护关闭”，不以单一connected/绿灯替代。

GUI保留OBS连接CRUD、场景预选／切换、转场选择、推流目标／开停播、场景项显隐与反序拖动、媒体按钮／时间输入／列表；保留ATEM连接管理、PGM/PVW、CUT/AUTO、mix rate、Aux及宏。写按钮与只读状态分离，提交后显示命令／operation，不能先乐观改confirmed值。双语单位与身份一致，原始秘密只在受限输入路径处理，不回显到通用目录。

故障时序：①设置转场成功后接管，后续切场景未发，显示部分完成而非回滚；②修改推流目标成功后Start超时，保留目标已变及开播unknown，不自动再次Start；③VLC列表读取后原生编辑改变，expected digest冲突拒发，不能覆盖新列表；④ATEM包发出后撤权，旧重传被闸拒绝，原attempt保持可能影响，不能标not_sent；⑤宏启动后worker崩溃，进程退出不释放宏资源；⑥CUT短于一次状态采样且ACK丢失，不以后来PGM/PVW刚好交换认定本命令成功。

以下VAT01—VAT32为**未运行**验收，必须分别记录模拟、固定库、平台和真实设备证据；官方源码核查不计运行通过。

| ID | 场景与通过判据 |
| --- | --- |
| VAT01 | 连接／重连只发现不写；改端点或型号不沿用旧目录／许可 |
| VAT02 | 同OBS输入跨场景引用冲突；同sceneItemId跨容器不混用 |
| VAT03 | 转场同名、改名、UUID不匹配时拒发，不能选择第一个同名项 |
| VAT04 | 固定转场禁止duration；49/20001拒绝，50/20000按profile验证 |
| VAT05 | 选转场后接管，后续切场景不发，已改变配置明确保留 |
| VAT06 | sceneItem index的UI反序与协议底部0一致；越界／目录变动拒绝 |
| VAT07 | 排序中原生修改，旧order digest拒绝；失败刷新不能声称已回滚设备 |
| VAT08 | stream目的地含旧凭据／关闭认证时语义明确，日志／快照不含秘密 |
| VAT09 | 配置成功、开播失败或unknown显示分步结果，无自动重试／回滚 |
| VAT10 | outputActive=true但reconnecting，不通过启动效果政策；平台画面另验 |
| VAT11 | 断线不发streaming=false／program=0事实事件；重连baseline不补触发 |
| VAT12 | 媒体动作枚举严格；不支持previous/next的类型明确拒绝 |
| VAT13 | seek负数／超过片长／片长null／非playing或paused拒绝，不猜时长 |
| VAT14 | paused与playing seek采用各自证据；仅游标经过目标不能证明seek |
| VAT15 | playlist selected改变不能显示Playing；固定OBS插件验证实际行为与副作用 |
| VAT16 | 指定列表条目真实播放并能识别条目；目录、重复URL、shuffle变化不得误归因 |
| VAT17 | 设置patch缺Schema／未知字段／过期digest拒绝，外连和媒体重启足迹可见 |
| VAT18 | 非Cut结束丢失、Studio或覆盖转场变化拒绝套用Cut释放policy |
| VAT19 | ATEM不同ME／Aux／内部source按实际拓扑匹配，不回落0或固定两个输出 |
| VAT20 | mix rate滑条和数字输入共享型号范围及帧单位；视频模式变化使旧profile失效 |
| VAT21 | allSettled内部拒绝仍fulfilled的固定库探针，不能计为ACK或成功 |
| VAT22 | ACK真实关联packet/tracking/session，其他设备或旧session包不释放等待者 |
| VAT23 | CUT/AUTO协议重传逐次过闸，屏障后无新控制send；已送包仍在途 |
| VAT24 | 库自动重连／工作线程重启不续发旧控制意图，维护IO不夹带业务写 |
| VAT25 | ACK后读取state旧值／恰好同值不能冒充fresh query；反馈policy须独立取证 |
| VAT26 | 超短CUT、连续AUTO、外部T-bar与背景／key选择变化不误配完成 |
| VAT27 | 宏更名／内容更换／重用index使批准失效；无内容证明不宣称完整足迹 |
| VAT28 | 宏执行中断线／worker退出不报取消或clear；stop若支持需单独证据 |
| VAT29 | ATEM PVW已设置、AUTO未发时接管，不留下100ms游离timer |
| VAT30 | 集中采样在多面板下有界；超限不能丢关键触发后继续自动化 |
| VAT31 | Controller独立使用覆盖全部旧面板；SDK／Seamer目录不只含旧两个action |
| VAT32 | 两平台分别记录具体OBS／插件／ATEM型号固件及视觉／协议证据，未测组合不继承支持 |

## 7. AV06：明确的剩余冻结与推荐

1. **VLC指定条目播放**：保留真实功能目标。[第9节](#9-av02av06补充vlc源扩展与studio转场)已将辅助接口收敛为VLC源内窄补丁及受限桥候选，定义列表／条目／播放代与独立制品边界；不采用改selected、猜测NEXT、暗改列表顺序或读私有内存。该路线及维护交付边界已由第11节采用；安装仍须本机维护批准，不记为功能已实现。
2. **ATEM库边界**：[第8节](#8-av04av06补充可审阅的传输与证据冻结方案)已细化逐传输可靠许可、接收校验与两级账本，显式传播逐项发送失败。库tag／tarball一致只证明来源，补丁及原生／线程产物仍须DF05固定；不将3.7.0直接批准上线。
3. **ATEM效果与年龄**：逐型号给出设备反馈到命令／执行代的证明路径。普通缓存与时间请求不够；若协议无法提供所需因果证据，需评估厂商受支持控制接口或明确较弱手动政策，不能默认降低自动化要求。该结论是待设计问题，不是删除ATEM范围。
4. **全量能力机器契约**：将本表每个action、target、错误码、复合计划及证据政策合入下一版SDK；OBS四帧仅保留原适用域，不把通用DeviceActionEvidence存在当作验证器已实现。Media／Transition／Stream／ATEM专属profile须有正反例及独立批准。
5. **型号及预算**：实际固件、合法range、重传预算、采样年龄／完成期限和解码容差由固定夹具取证。设计必须给字段、选择规则和失败关闭行为，未测试的数字不得包装为生产默认；完整支持矩阵在实现验收后发布。

本稿将旧面板用途落实为候选契约并揭示新的实质缺口，尚未关闭C11。Mixer／DM3完整目录、WING与VB、GUI身份流程、部署恢复及跨项机器归并仍须完成；全部系统方案审阅前继续不进入业务实现。

## 8. AV04／AV06补充：可审阅的传输与证据冻结方案

2026-10-18补充。以下是工程推荐，不表示AV方案已获确认。本节把“需要受控适配”收敛为具体边界；它新增传输层记录和许可，必须与F02、DF04及下一版IPC联合审阅，不能直接写入已确认IPC 0.3。

### 8.1 已核对事实与接收适配边界

固定ATEM源码的`sendPacket`先调用`_sendPacket`再加入`_inFlight`；`_sendPacket`直接调用UDP socket。`_receivePacket`在解析长度前更新接收时间，读来包session后直接赋给`_sessionId`，未在该方法核对`rinfo.address/port`；ACK按循环序号累计覆盖在途项。`_retransmitFrom`从请求位置起逐项重发原payload，设备请求与超时均可进入该路径。这些是第三方库实现事实，不能据此声称设备保证去重或网络对端可信。（来源：[固定接收和发送实现](https://github.com/Sofie-Automation/sofie-atem-connection/blob/3e11369e2937931c88453ce65e44fb6c406ce392/src/lib/atemSocketChild.ts)。）

推荐在受审阅适配内统一接收校验：最小头长度、报文实际长度、允许flags、当前socket实例、固定数值端点及协议session全部匹配后，才更新存活／状态／ACK账本。新session只由当前握手状态接受；已建立连接收到不同session不能直接覆盖。累计ACK必须落在本连接实际已提交的序号窗口内，不得用未来ACK清空账本；未知重传起点进入保护恢复，不自动建立新可写会话。坏包有界计数及丢弃，不能凭来包刷新租期或可信年龄。端点过滤不是密码认证，部署profile须明确可信设备网络前提，不能将UDP来源标签等同mTLS身份。

推荐每个连接世代内不复用控制packet序号；接近协议回绕时在无在途／未知影响、写闸关闭后维护重连，建立新device_session_id并完成恢复屏障。无法清空则保护停止，不跨回绕猜ACK归属。此前原生设备可能仍执行已收命令，连接更新不产生释放证明。该保守选择有周期维护成本，须在长时直播试验中评估；不可将其包装成无中断保证。

### 8.2 两级身份与持久化发送

保留一个业务attempt，新增其下多次传输记录。F02的“一attempt一permit”仍适用于原始派发；新增重传例外只在下一版明示，不能把同一许可消费多次，也不能以新attempt重做CUT/AUTO。

| 候选对象 | 具体字段及约束 |
| --- | --- |
| `TransportPacket` | packet_ref、command_id、attempt_id、primitive_id、device_session_id、writer/domain引用、socket_instance_id、protocol_session、wire_packet_id、tracking_ids、immutable_bytes_ref、byte_length、sha256、transport_profile_ref；一个控制primitive独占一个packet，禁止跨command合包；超单包须另设计显式多primitive计划 |
| `TransmissionIntent` | transmission_id、packet_ref、ordinal、kind=`initial|protocol_resend`、cause=`dispatch|timeout|peer_request`、trigger_observation_ref、parent_dispatch_intent_id、issued_revision、permit_id、send_window、state；ordinal=0绑定原DispatchPermit，后续ordinal严格递增且单独许可，跨重启不复用 |
| `TransportResendPermit` | transmission_id、packet_ref、packet_sha256、byte_length、ordinal、device_session_id、协议session/packet序号、原command/attempt、当前gate/control/authorization绑定、守卫引用、expires_tick_ns、budget_revision；单次使用，不携带可替换payload；有效期不得超过原命令及许可总截止 |
| `TransmissionReport` | report_id、transmission_id、gate_io_seq、disposition=`not_sent|in_flight|unknown`、proof、transport_entered_tick、socket_callback_observation_ref；异步socket回调成功只证本地提交，错误通常不证明设备未收 |
| `PacketAckObservation` | observation_id、socket/session绑定、receive_io_seq、原始ACK引用、wire_ack_id、按当前窗口推导的covered_packet_refs；不生成effect_verified，不能声称ACK对应某次ordinal |

发送路径推荐：worker只编码并提出`PREPARE_PACKET`→Controller核对目录、primitive与内容摘要，原intent及初次传输行在关键事务可靠提交→发`DISPATCH`→worker串行闸核对并消费→socket提交。初次编码准备没有设备写副作用；Controller不持有设备socket。封包变化使准备作废，不在已批准摘要上暗改协议头。

重传路径推荐：worker提出`RESEND_REQUEST(packet_ref,cause,observation_ref)`→Controller在同设备调度锁内核对原尝试、未终结、原截止、当前授权／资源／守卫、预算和未ACK状态→事务预留一个ordinal及可靠intent→发`RESEND_DISPATCH(permit)`→worker在与FENCE共用的仲裁器中再核对→逐次发送。所有超时、peer请求和批量连带重发均走此路，不预发整组重传许可。每packet最多一个未消费重传许可；重复请求只合并待处理原因，不能刷新时限、重置计数或绕预算。ACK在许可投递后到达，worker可丢弃尚未消费许可并报告not_sent；ACK不是强制再发依据。

持久化候选约束：`transport_packets(packet_ref PK, attempt_id FK, session_id, wire_id, hash, bytes_ref)`、`transmission_intents(transmission_id PK, packet_ref FK, ordinal, permit_id UNIQUE, issued_revision, disposition)`，唯一`(packet_ref,ordinal)`和同session的wire_id；证据与报告另存不可变引用。重传预留事务原子增加预算消费及行；未发许可也占预算，取消不返还以免重复请求循环。字节与账本保存按关键资料保留规则处理，不放普通debug日志。这些是DF04候选表映射，不是已完成迁移脚本。

任何关键事务失败都不签发许可；持久intent存在而发送结果丢失，重启后为unknown，不从数据库重放。worker旧报告只能核对历史；新worker不能发送旧packet，即使payload、IP和wire序号相同。底层全部回调、定时器、自动重连和子线程重启纳入监督及出口账本，未能证明已终止则不启动替代writer。

### 8.3 屏障切点与完成分离

下一版`FENCE`除原业务open_intents还携带`open_transmission_intents`，每项含传输及parent身份；两清单分别排序／摘要并由同一持久化issued_cut_revision绑定。它们属于同一个签发切点，不能先截业务清单再允许重传签发。ACK覆盖全部未核销传输；零次未发和原packet曾发必须并存，不能用“最后一次重传未发”覆盖原attempt的在途事实。即使原始DispatchPermit已有发送报告，该packet待发重传／未决影响仍须纳入切点。

`Lresend < Lfence`时本次重传归in_flight；`Lfence < Lresend`时拒绝本次发送。两者均不保证网络线路已静止。屏障后的peer请求只能登记/拒绝；纯ACK维护包仅在固定无控制payload格式和有界维护预算内允许。业务关闭不自动关闭所有接收，迟到ACK／状态可追加resolution；不改变已存unknown终态、不自动清保护、不改持有人。

推荐有限实验profile：每设备最多32个未核销控制packet、64KiB不可变包缓存；每packet最多10次实际重传且最多10次重传许可预留；两条重传入口共享预算；最小60ms间隔、总重传窗口至多600ms且取原截止更早者；普通请求不挤占F02保护槽。数字只供夹具，不能沿用库默认推导可靠性或时限保证。每次持久化增加延迟，超窗口就停止，不能为了赶60ms而越过事务。真实吞吐／丢包／持续接管预算验收后才能批准生产profile。

### 8.4 ATEM效果政策的具体放行条件

推荐分开提供`transport_ack_only`观察与`qualified_state_effect`完成政策。前者只供界面说明已收到协议ACK，不能把命令终态改成succeeded。完整人工控制仍可发出，但结果可能为unknown且冲突资源保持保护；GUI必须在执行前展示该组合的证据限制。自动化required动作仅在后者已批准时可布防，不由调用者临时降低。

`qualified_state_effect`候选必须绑定型号/固件、命令codec、资源与前置快照、当前会话有序反馈、原发送和ACK、期望字段谓词、观察区间及反馈关联规则。接收顺序较晚、同值状态或累计ACK本身都不证明“该命令造成了状态”；不能把本地receive_io_seq伪装成设备因果序号。若固件协议不能提供执行代关联，独占控制前提及固定协议模型必须按第12节取得对应保证类别的资格；可验证事实与有条件运维确认分开，已知外部控制器／面板仍可不受约束地操作时前提不成立。需要改走厂商受支持接口时另固定对应接口及制品，不能假定换SDK就自然得到命令ID。

CUT/AUTO需明确background/key选择及转场开始／结束关联；宏需内容身份、运行代与完整影响的结束证据。状态字段足以显示，不一定足以证明本命令完成。配置读取或ACK不能解除设备内程序的后效；没有可靠释放证据保留unresolved。由此得到的是明确的资格判定算法与失败表现，逐型号能否满足仍是实施验证门槛，不能据空白资格记录发布支持声明。

## 9. AV02／AV06补充：VLC源扩展与Studio／转场

### 9.1 VLC公开接口事实与推荐实现位置

OBS32.0.4的`vlcs_create`只注册`get_metadata` proc；媒体callbacks无直接选择列表index的接口。`vlcs_update`会展开目录、shuffle和重建列表；`get_media`还会按路径复用media对象。因此设置数组索引、URL以及原实现media指针均不能天然唯一标识重复条目。LibVLC3公开了`libvlc_media_list_player_play_item_at_index`，但其句柄由VLC源内部持有，现有proc没有导出对应操作。（来源：[固定VLC源码](https://github.com/obsproject/obs-studio/blob/32.0.4/plugins/vlc-video/vlc-video-source.c)、[VideoLAN列表API](https://videolan.videolan.me/vlc-3.0/group__libvlc__media__list__player.html)。）

推荐**固定VLC源最小补丁＋受限vendor桥**，不再将“纯外部插件即可控制现有源”列为默认路径：在`vlc-video`内新增具名、版本化proc和所需LibVLC动态符号；桥经公开`obs_source_get_proc_handler`调用源，不读取私有结构。通过obs-websocket已公开vendor API承载具名请求与事件；禁止任意proc名、函数地址、源指针或vendor透传。（扩展机制来源：[obs.h](https://github.com/obsproject/obs-studio/blob/32.0.4/libobs/obs.h)、[obs-websocket vendor API](https://github.com/obsproject/obs-websocket/blob/5.6.3/lib/obs-websocket-api.h)。）

该选择新增OBS宿主制品维护和安装成本，第11节明确采用及维护安装边界。补丁、桥、LibVLC及OBS组合单独版本、hash、ABI和源码交付清单；不能在发行目录中同时装两个冲突的VLC源实现，也不能静默替换运行中OBS插件。安装在停止OBS的维护阶段显式选择固定组合；不兼容时保留普通OBS能力及明确的VLC扩展不可用原因，不用selected回退实现按钮。OBS官方许可为GPLv2或以后版本，相关派生制品保留适用许可和源码义务，SDK协议文档沿项目许可；进程／目录分隔本身不构成重新许可依据。（来源：[固定COPYING](https://github.com/obsproject/obs-studio/blob/32.0.4/COPYING)、[README许可说明](https://github.com/obsproject/obs-studio/blob/32.0.4/README.rst)。）

### 9.2 VLC候选接口与执行代

| 候选接口／记录 | 必需字段与行为 |
| --- | --- |
| `GetPlaylistSnapshot` | source UUID、source_instance_id、playlist_generation、materialized_list_digest、shuffle/repeat设置、entry_count、entries及完整性状态；generation为十进制串，不随显示名改变；目录展开／顺序／成员／设置改变须换代 |
| `PlaylistEntryRef` | source_instance_id、playlist_generation、entry_id、occurrence_index、materialized_index；entry_id是不透明的本代条目身份，不用路径/URL作ID；受限显示名称与敏感宿主路径分开 |
| `SelectPlaylistItem` | bridge_protocol_revision、command_id/attempt_id、单次request_token、source绑定、expected_generation、expected_list_digest、entry_id、mode=`start_from_beginning`、deadline守卫引用；只控制一个条目，不改列表顺序，不支持通过该接口任意seek或设置 |
| `SelectionReceipt` | request_token、source_instance_id、generation、entry_id、playback_generation、submission_seq、result=`rejected_before_submit|submitted|uncertain`、reason；提交返回不等于playing，未证实无副作用不得填rejected_before_submit |
| `PlaybackObservation` | source_instance_id、generation、entry_id或null、playback_generation或null、observation_seq、state、cursor/duration、evidence_policy_ref、quality、关联token或null；无法唯一识别时明确unresolved，不按最近请求补身份 |
| `GetSelectionObservation` | token及上述源绑定；返回已存在记录或明确未知。重复控制请求只查询原收据，不再次调用LibVLC；换源实例后不能用同token重新播放 |

推荐在源内部使用单一有界串行执行通道，接收设置更新、列表选择、现有媒体操作及外部回调的有序记录；不能仅在桥侧加锁。实际列表冻结后生成entry表；每个物化occurrence拥有独立、受引用计数管理的media对象，避免原按路径缓存让重复URL合并身份。销毁或重建先废止旧映射，迟到callback通过source实例及持有的对象生命周期识别，不能复用裸指针值作为身份。

目录展开、shuffle或嵌套媒体改变实际成员后，必须重建完整映射并使待发选择失效。动态嵌套内容若无法提供稳定映射，只返回明确的`playlist_not_materialized`；相关格式支持仍保留实现／夹具任务，不静默截断成可写列表。原生Next/Previous、自动下一项、循环及重新开始都会改变播放代或使关联不确定；调用令牌不自动贴到它们产生的事件上。

源内在线性化点核对源实例、generation、digest和entry，随后调用公开LibVLC选择接口；所有源内列表替换共享该边界，因此该检查可作为**本扩展受控列表操作**的CAS候选，不泛化为OBS所有原生状态的CAS。若底层媒体引擎仍可独立改变列表，profile必须显示该缺口且不得宣称CAS成立。返回0仅记submitted；完成要求同一条目唯一身份、该次播放代的已确认playing状态及连续来源证据，错误/Opening/旧playing不能通过。仍不证明帧已进入节目输出或观众已看到画面。

Controller发出的vendor请求本身经过唯一写闸；源内部已经受理的异步播放是设备端在途效果，不因Controller接管或断连消失。源不保存可跨OBS重启重放的动作队列；回执丢失时保持unknown并只查询。源端期限校验必须使用已协商且有证据的时基，不能比较两主机tick；没有跨端时基时不声称可阻止设备端晚启动，只能采用已批准的最大排队／处理profile并保留在途影响。接管effective不等于该播放已经停止，ready仍遵循冲突资源释放政策。

有限实验预算：每源最多4096个物化条目、控制队列8项、每设备最多32项未决选择、每源256个有界回执缓存；记录到Controller确认及规定保留期前不得挤掉未决回执，满即拒发并保护，不LRU删除unknown。展开超限先报容量错误，不用部分列表作完整快照。扫描／展开在后台取消友好任务执行，不占OBS渲染线程；跨线程回调不得持有锁调用可重入LibVLC函数。具体构建和线程验证后才批准参数，本文未实现补丁。

### 9.3 Studio与转场的动作拆分

已知事实：`TriggerStudioModeTransition`取执行当时preview，接口没有expected preview CAS。`SetCurrentProgramScene`调用前端API，在Studio模式走`TransitionToScene`；场景override影响实际转场，已有转场时可能直接退出而handler仍返回Success。转场事件只有transition name/UUID，无request/attempt/from/to；`obs_transition_force_stop`也会发stop。因此Success、Ended或cursor=1均不独立证明正常完成。（来源：[Scenes](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_Scenes.cpp)、[Transitions](https://github.com/obsproject/obs-websocket/blob/5.6.3/src/requesthandler/RequestHandler_Transitions.cpp)、[前端实现](https://github.com/obsproject/obs-studio/blob/32.0.4/frontend/widgets/OBSBasic_Transitions.cpp)、[转场信号](https://github.com/obsproject/obs-studio/blob/32.0.4/libobs/obs-source-transition.c)。）

推荐保留三个独立用途：`obs.preview_scene.set`明确写Studio预览；`obs.studio.take_preview`对当前预览执行一次转场；`obs.program_scene.switch_with_transition`指定目标并固定模式/转场profile。GUI本地预选不等于Studio的真实preview。前两个补足模式适配，不能把旧Switch按钮在模式变化后悄悄改义；设置模式为独立、显式配置操作，不作为命令隐含前置步骤。

候选`ObsTransitionExecutionProfile`固定canvas绑定、Studio模式及版本、from/to引用、当前转场UUID/kind、scene override、duration来源、audio/video结束谓词、预检busy判据、允许外部控制前提和全部资源足迹。Studio取预览要求当前预览与请求预期一致；标准接口的读写间隙仍存在，不声称原子CAS。模式/override/preview变动或来源缺口使未发请求失效，发送后变化进入unknown／核对，不重新取新preview补执行。

每次仅一个相关资源的转场attempt；记录实际send、ACK、Started/Ended/VideoEnded观察及后置Program读取。事件允许先ACK，但不能与另一个attempt共享“结束证明”。没有事件关联ID时，profile须证明独占控制与信号连续性；检测到原生控制、force-stop、连接缺口或无法判别的并发，则不批准该次完成。stinger的cut point和视频结束按固定类型分别处理，音频尾部另定义，不把一种Ended语义套所有类型。多画布仅允许写能明确寻址的目标；标准接口无法定位的画布须受控扩展设计，不按显示名猜默认画布。该部分保留全量支持任务，未测组合不列支持矩阵。

## 10. 本轮故障时序、验收及归并门槛

正常ATEM轨迹：准备packet→可靠初次intent→发送→超时请求→可靠重传intent→同packet重传→累计ACK→专属效果证据→持久完成；只有最后两步具备批准证明才可succeeded。接管轨迹：原发送→重传许可已提交→FENCE切点包含两者→worker先安装屏障，后到重传许可not_sent→原发送仍in_flight→接管effective且资源未clear。任何旧包ACK均不能反向开放写闸。

正常VLC轨迹：完整快照g→选择entry E→源内CAS→提交及新播放代p→同E/p的playing证据→Controller可靠完成。冲突轨迹：读g后原生修改列表成g+1→源内拒绝未提交，不改新列表；若提交后OBS崩溃或关联丢失，则unknown，不以重开OBS后同路径正在播放作为原命令证据。转场轨迹：预检空闲→发送→外部force-stop→收到Ended和目标PGM→仍不能据此宣称正常转场完成。

以下为新增**未运行**验收，补充VAT01—VAT32，不以文档检查冒充执行：

| ID | 正反例与通过判据 |
| --- | --- |
| VAT33 | 同packet精确原字节重传可准入；改payload、session、ordinal或过原截止拒绝，不能新建CUT attempt |
| VAT34 | 重传intent事务失败无许可；事务成功但报告丢失，恢复unknown且不自动重发 |
| VAT35 | FENCE与重传分别先到两种顺序；完整覆盖原发送和每次重传，最后一次not_sent不能释放原影响 |
| VAT36 | peer与timer并发仅一待消费许可；统一计数，ACK先到丢弃未消费许可，预算耗尽不重置 |
| VAT37 | 短包、错端点、错session、未来累计ACK不改变连接/账本；合法累计ACK只覆盖本窗口，回绕不误配 |
| VAT38 | 子线程重启、ACK定时尾部、重连路径均在监督范围；没有控制包可从维护IO绕闸 |
| VAT39 | 同值旧state和较晚接收的无因果反馈均不通过效果政策；固定型号夹具明确何种证据才可通过 |
| VAT40 | 两个相同URL条目分别选择并识别occurrence；目录展开／shuffle后旧配置索引不能选择错误项 |
| VAT41 | 选择与列表更新竞争；源内CAS拒旧代，不能更新后靠重新找同URL继续旧请求 |
| VAT42 | submitted/Opening/旧playing均不算完成；同条目正确播放代才可核实，画面输出另验 |
| VAT43 | 自动下一项／循环／原生媒体操作不冒充请求令牌；迟到回调与复用地址不继承新源身份 |
| VAT44 | 回执丢失只查询；OBS重启更换实例，旧token不重新播放；队列满不挤掉未决记录 |
| VAT45 | 接管后源端已提交动作仍可晚生效，记录in_flight；不能用Controller worker退出证明OBS排空 |
| VAT46 | Studio模式／preview变化、已有转场但ACK Success均不误报新动作完成，不自动切模式 |
| VAT47 | 强制停止产生Ended、stinger cut point、丢VideoEnded分别验证，不能将信号名称等同全部结束 |
| VAT48 | 同名多画布／不可寻址画布拒绝误写；扩展部署的版本/ABI/许可清单独立记录，未安装时不伪回退 |

本轮已形成明确推荐：VLC源内窄扩展、ATEM逐传输可靠许可及接收校验、Studio／转场独立完成profile。待审阅的实质成本是额外OBS制品、ATEM传输适配与逐次落盘延迟、序号回绕维护，以及缺证据组合的保护表现。接下来合入新版前仍须完成辅助接口Schema、传输IPC/DDL关联、精确制品锁、逐型号证据profile及对应正反例；候选成文不等于产品批准，真实插件/协议/平台/设备用例均未执行。

## 11. VLC扩展的采用与请求回执契约

2026-10-29。本节采用第9.1节的固定VLC源补丁＋受限vendor桥作为`obs.vlc.playlist.item.play`的实现路线，关闭辅助接口、令牌去重及回执保留的设计缺口。OBS32.0.4／obs-websocket5.6.3为固定源码基线，补丁、实际LibVLC及两平台制品按DF05分别锁定。通过C12维护计划在OBS停止时安装并保留许可／源码交付，不远程替换运行中插件；机器生成、插件实现和运行验收后置，不能再把“尚未编译”当选型未定。设备效果／资源释放仍需独立资格，本节不批准缺少依据的完成结论。

### 11.1 入口身份与严格消息边界

**已知接口事实。** 固定obs-websocket vendor请求回调签名只有请求、响应和注册时的私有上下文，没有逐客户端会话身份参数。桥不能从request里的controller_id自证调用者，也不能把注册者的priv_data当远端会话。（来源：[obs-websocket5.6.3公开接口](https://github.com/obsproject/obs-websocket/blob/5.6.3/lib/obs-websocket-api.h)。）

**本项目选择。** vendor名称固定`LeafSeamer.VLC`，协议`vlc-source/1`；只注册下表六种请求，不开放任意proc、vendor名称或原生函数透传。外层仍须正常OBS WebSocket认证；跨主机通过受控TLS入口，明文OBS WS只允许同机受保护回环段。GUI不直连该入口，Controller受监督OBS worker是唯一业务调用方。

Suite在本机维护时配置BridgePairing：pairing_id、credential_id、完整Controller scope（authority_service_id／database_instance_id）、device_id、允许source UUID集合、状态和独立32字节随机MAC key。key不复用OBS密码或发行密钥，按DF06秘密存储规则分别装载，公开配置只存引用；配对／轮换／撤销没有vendor远程接口。OBS进程每次启动生成新的bridge_boot_id，每个VLC源创建生成新的source_instance_id；配置持久bridge_id与运行boot分开，旧源UUID重新创建也不能继承source_instance_id。

GetBridgeInfo仅返回协议、bridge_id／boot_id、源扩展可用性和制品摘要，不含播放列表、宿主路径或秘密。CallVendorRequest.requestData采用仅一个envelope_json字符串字段，响应亦以该字段承载；桥对内层原始UTF-8字符串执行严格JSON解码，不能依赖obs_data_t已经转换过的字段证明无重复键或精确数字。GetBridgeInfo使用固定最小发现正文，其余请求使用闭合Envelope：protocol、bridge_id／boot_id、pairing_id、credential_id、controller_scope、device_id、sequence、request_type、payload、mac。sequence为严格U20、MAC为HMAC-SHA-256，输入是UTF-8 `LeafSeamer/VLC/request/1`、零字节及只排除顶层mac的完整JCS正文；固定32字节结果以小写64位hex编码并恒定时间比较。内层未知字段、重复键、非法数字／字符串、错源范围及旧boot均在入队前拒绝。原Envelope及MAC不得进普通日志，诊断只保留分类后的非秘密引用和错误码。MAC只证明已配对Controller来源，不代替Controller自身的人员／automation授权、当前Guard和唯一写闸。

每pairing、bridge_boot的请求sequence共用递增水位，Controller在自己writer可靠预留后使用；source串行器认证后先保留新水位和写请求记录，才允许排队或调用LibVLC。较低／相等sequence只能返回仍保留的同摘要原选择收据，否则返回retired_sequence，绝不执行；同保留sequence异摘要为identity_conflict。只读请求也使用新sequence，但不增加设备写权；水位只拒绝再次进入的旧消息，不自动取消已经登记的队列项。高水位耗尽停止新请求，不回绕；源端水位是本boot内状态，重启必须换boot，旧消息不能进入新域。Controller恢复或更换库身份需重新本机配对，不能沿旧MAC身份假装同一权威。

### 11.2 六个请求与领域映射

| request_type | payload与结果 | 写入边界 |
| --- | --- | --- |
| GetBridgeInfo | 无payload；返回协议／运行身份与可用性 | 仅最小发现，不列目录或授予调用权 |
| GetPlaylistSnapshot | source_uuid、source_instance_id，首次无cursor；后页仅opaque cursor；返回固定generation、list_digest、entry_count、entries、next_cursor、complete | 对应obs.vlc.playlist.read；分页读取不调用播放或改设置 |
| SelectPlaylistItem | source绑定、expected_generation、expected_list_digest、entry_id、mode=start_from_beginning、原command_id／attempt_id／primitive_id和deadline_guard_ref | 对应obs.vlc.playlist.item.play；仅在Controller现有逐传输许可下调用，不能由分页或刷新触发 |
| GetSelectionObservation | 完整SelectionToken及source_instance_id | 只读取既有收据与最新关联观察；无记录返回unavailable，不发设备动作 |
| GetPlaybackObservation | source_uuid、source_instance_id | 当前观察及独立seq，token可空；不是旧命令补执行入口 |
| AcknowledgeSelectionReceipt | SelectionToken、receipt_revision／digest、controller_record_ref | 仅证明Controller已持久保存指定收据，允许清理该版本；不是效果或资源释放命令 |

SelectionToken为`{pairing_id,bridge_boot_id,sequence}`，sequence必须等于原Select请求sequence，不由调用方另造随机令牌；源和正文摘要由收据一起固定。原action的playlist_revision映射为expected_generation，item_ref必须含source_instance_id／generation／entry_id；裸数组index、路径／URL或旧selected不能形成可执行请求。源内部根据当前固定目录将entry_id解析为materialized_index；外部请求不携带该索引，不信任客户端传来的index。

GetPlaylistSnapshot每页最多128项、编码后最多64KiB；超过字节预算提前结束一页但不得跳过未返回项。每源最多4096个物化条目，全部快照最多4MiB；source只保留一个当前generation的不可变条目映射，cursor绑定pairing／boot／source／generation／页位置，32随机字节，绝对30秒有效不续期。列表或设置改变立即使旧cursor失效，不能拼接新旧页。条目显示为ordinal及受权配置标签（每标签UTF-8≤256字节），不默认返回URL、文件路径、凭据或原始媒体元数据；无标签使用条目序号。超过条目／单项／总量上限明确拒绝，不能截断后标complete。

所有普通请求／响应JSON最多64KiB，每pairing每秒最多32请求，源控制队列8项、设备未决选择32项、每源回执256项；按第9.2节保留未确认／未决记录，满时拒绝新Select，不能LRU删除unknown。队列入队到开始调用最多100ms，以源本机单调计数判断，未开始且超时记rejected_before_submit；开始调用后超时只能uncertain。该本机预算不证明满足Controller跨主机业务deadline，deadline_guard_ref只绑定原守卫；不能拿两机tick直接比较。Controller进入传输后仍按可能迟到的设备端在途处理。

### 11.3 收据、事件与回收

SelectionReceipt保留第9.2节身份，增加receipt_revision、request_digest、桥运行身份、completion_evidence_ref可空、release_evidence_ref可空及receipt_digest。result仍只有rejected_before_submit／submitted／uncertain；源端submitted不是公共Command succeeded。每次修订只追加新观察和引用，不替换原提交事实；无法唯一关联的PlaybackObservation令token、entry_id或playback_generation为空并标unresolved。播放代、目录代、收据revision及观察sequence分别计数，不互相充当版本。

正常轨迹：Controller固定当前目录与Command／attempt→先可靠预留vendor sequence并准备固定包，再以T2消费预留并提交原传输intent→worker写闸消费许可→源核对MAC／boot／水位并登记SelectionToken→源串行器核对完整列表CAS→调用LibVLC一次→返回submitted收据→Controller同T6持久保存原件及关联→经后续具名完成政策裁决，再发送AcknowledgeSelectionReceipt。任何一次socket或请求返回成功都不跳过效果及释放核对。

响应丢失后只发GetSelectionObservation，使用新查询sequence和原SelectionToken，不再次Select。源记录丢失、源销毁或OBS重启返回unavailable及当前boot，Controller保留原unknown与资源；新boot下查询不到不代表原动作未发生。断连不取消源已受理播放，不把查询包作为自动重试动作。源端可明确证明尚未调用时才给rejected_before_submit；解析错误、取消等待者或Controller本地超时不是这种证明。

源可在收到精确ACK后回收对应已封存详情，但必须保留本boot的sequence水位；有未解决关联／回调或存在更新收据版本时不能回收。ACK旧revision仅确认旧版本，不删除新版本；ACK响应丢失可按同token／revision重复确认，不调用LibVLC。Controller的持久副本才承担跨OBS重启的命令历史，桥不把内存收据称为durable，也不保存重启后重放的控制队列。BridgePairing撤销阻止新调用并保留诊断事实，不自动停止正在播放的媒体。

首期vendor广播事件只发`PlaybackChanged`提示，字段限定bridge_boot_id、source_instance_id和observation_seq，不含条目标签、token或路径。OBS其他订阅者收到提示不获得目录读权；Controller随后使用已认证GetPlaybackObservation拉取原件。事件缺失／重复／乱序不改变命令结果，不能用vendor事件的接收顺序伪造源端因果。

### 11.4 回调身份与完成资格的界限

物化occurrence对象与一次playback execution不是同一身份：同一条目重复播放时，媒体指针、路径和“最近Select”均不能给迟到Playing回调补request_token。源实现须给原生回调持有不可复用的执行上下文并核生命周期；不能携带执行上下文的引擎事件只作无关联观察。直接一次libvlc_media_list_player_play_item_at_index返回0只证明submitted，不证明该上下文已经playing。受控源的CAS及一次调用可以验证，但媒体引擎关联、音视频输出和未来无旧选择后效仍各需资格证据；实现发现公共回调不足时先保持unresolved，不能用时间延迟或同值状态补成true。

人工控制的未知呈现及自动化完成要求沿F06与当前Command模型；本节不降低required动作的成功／资源证据。WING、VBAN及部分ATEM的有条件部署资格按第12节采用，不能从本节的MAC或源内队列推导设备端排空，也不把候选profile写成已可上线。

## 12. 有条件部署资格的首期采用

**已确定的产品政策。** 首期允许WING、VBAN及部分ATEM在逐型号审阅的独占控制、受控传输和设备行为假设下建立有条件完成／释放资格。资格必须明确前提、适用范围、失效处理和界面呈现；本项决定不批准任何具体设备，也不把有限实验最大延迟升格为硬上界。此为用户已确认的产品取舍；以下规定其实现和验收边界。

### 12.1 同一政策引用中的保证类别

沿既有model／protocol profile、completion／response／release policy及qualification_refs扩展生成，资格记录的`assurance_class`固定为`protocol_verified`或`deployment_conditional`。前者按已有可验证协议模型评价；后者显式依赖部署前提。完成与释放分别选择政策和类别，不能因其中一项通过就推导另一项，也不新增一个可绕过原许可、资源或命令账本的出口。

每份有条件资格记录至少绑定：不可变id／revision／摘要；型号、固件、实现版本、codec与动作集合；具体部署及端点／会话／拓扑绑定；effect与release政策引用；完整影响足迹；批准人员身份、批准时间及有效期；条件清单、条件证据／确认引用、失效事件与保护范围。条件逐项声明可监测事实或不可连续观测的运维假设，及其责任人、复核周期、缺证处理。不可观测假设不能用绿色心跳冒充已证事实；允许人工确认的必须有明确人员、范围和有效窗口，过期或无法确认即未满足。

资格的Controller权威、持久原件与摘要沿DF04现有政策／证据记录归属；SDK生成不可变定义与运行条件快照的区别，Seamer只消费当前Controller绑定的资格。人员审阅／批准与服务自动化权限分开，服务不能自行批准部署假设。修改型号、固件、传输路径、控制者集合、动作或条件生成新修订并使旧运行资格失效，不能原地覆盖历史依据。

### 12.2 条件、判据和发送边界

| 领域 | 必须具体化的条件 | 不足以单独放行的材料 |
| --- | --- | --- |
| 独占控制 | 具名控制者、面板／其它客户端／设备内程序的处置、访问隔离和变更发现；区分配置承诺与可验证事实 | 仅本进程没有竞争、一个布尔勾选或当前值未变化 |
| 受控传输 | 从最终出口到设备的每一段、队列／重传／重复副本模型、关闭切点、在途影响和条件失效检测 | mTLS包裹、SERVICE ping、本地队列清空或库ACK |
| 效果 | 精确目标／codec、合格后置观察、采样关联／年龄、分辨率、设备行为假设及期望谓词 | 同值缓存、一次无关联观察，或Matrix一位小数被当作原生精确值 |
| 释放 | 完整发送及后效集合、不会再产生相关写的依据、设备内程序结束或具名有条件排空模型 | 命令终态、保护完成、请求表清空、固定sleep或实验最大延迟 |

若释放模型依赖时间界，必须逐项标明它是协议保证还是**经审阅的部署假设**，记录来源、数值、单位、计时起点、适用链路／动作、误差和失效条件。假设期限经过只能产生有条件结论，不能改写为无条件设备排空。计时以DF03合格单调时钟及同一运行代为准；记录缺失、时钟失格或不能确定最后可能发送的边界时，不启动一个猜测期限。

ATEM首次发送、超时重传、设备请求重传等每次物理传输仍各领permit，覆盖切点按既定transmission账本冻结；有条件资格不允许FENCE后继续旧重传。WING复合patch仍逐primitive核准并保留中间态及共享来源影响；VBAN代理只约束实际控制的链路，未受控的下游不能被省略。宏、转场及设备内程序的后效须进入释放模型，不能仅按声明duration或瞬间idle推导结束。

受理／布防、每次发送前、效果评价及释放评价都核对同一资格修订和当前条件。资格满足也不替代主体授权、有效RunGrant、OPEN_GATE、资源与每次permit。required动作可采用已批准的`deployment_conditional`完成政策，但它必须在定义与Run计划中明确，审阅和布防时展示；请求者不能临时把严格政策降级。缺codec、目标身份、必要分辨率或关联模型时仍不得批准，不能把未知协议语义整体写成一项假设。

### 12.3 失效、历史结果与恢复

条件取值为满足、不满足或未知；每种条件有自己的证据年龄。发现任何必需条件失效、缺证或过期，立即关闭受影响写闸并冻结相关自动化，按FENCE／Q72保留已发送或可能发送的完整影响；不把失效本身当作释放依据，不自动重试、回滚或补发。本政策不保证即时发现所有不可连续观测的假设破坏；这类残余风险必须在批准及GUI中明示，不能显示成持续验证的事实。

尚未发送的工作停止；在途命令保留原证据并按当前政策判unknown／unresolved；已经完成的条件性结果保留原条件快照，追加“依据失效”及影响核对记录，不改写成设备已撤销操作。若此前已按条件释放，则对受影响范围重新进入保护并核查后续依赖，不能声称旧副本必然无后效；无法界定范围时至少保护该设备。恢复由获授权人员重新确认条件、取得新鲜baseline和新运行资格，沿原恢复／重新布防流程执行，旧命令不重播。

GUI在执行前展示保证类别、前提、有效窗口及残余限制；结果分别显示“有条件完成”和“仍受保护／已按条件释放”，不只显示成功绿灯。审计／导出保留政策与资格修订、条件快照、证据及评价时点，历史消费者能够重建当时采用的保证类别。保护报告原覆盖切点不变，迟到强证据仅追加resolution。

### 12.4 实施与验收出口

资格记录、条件采集／时效、每次许可检查、两类结果呈现和恢复接线进入SDK、Controller、Seamer与GUI实施；逐型号的部署批准、网络条件及真实设备行为验收后置。必须覆盖：条件成立且仅效果通过时不释放；仅释放判据成立时不伪造动作成功；发送前失效零发送；首个primitive后失效停止后续步骤；重传前失效拒permit；条件性释放后发现前提失效重新保护；断线／重启不继承运行资格；同一设备不同动作的资格不串用。这些是验收要求，当前未宣称已运行通过。

本节关闭“首期是否允许有条件完成／释放及其失效政策”的设计选择。具体设备记录必须有实际批准和适用证据后才可启用；没有设备时保留未验收，不反复重开本项产品政策，也不以该决定替代剩余型号codec和精确观察语义。

### 11.5 当前IPC采用与实施验收

当前panel4／IPC0.14已包含具名`command__S9__TransportPacket`、PacketAckObservation及逐传输／FENCE关联，采用DF01第15节的这份输入，不再以第8节历史IPC0.3描述重新创建一套传输协议。上游ATEM适配仍须将所有初发和重传接到当前许可与唯一出口，真实ACK只更新传输事实，不提升效果；型号关联与释放政策仍是独立未决。

SDK生成独立vlc-source/1消息与新公开播放列表DTO，Controller实现pairing秘密装载、sequence预留、受权代理和T6回执保存，Suite交付源补丁／桥／维护步骤，GUI只通过现有设备动作显示列表、submitted、unknown及关联结果。公开API不得透传MAC或OBS私有路径；旧panel4没有这些VLC具名模型，现有52帧设备IPC的数量不因vendor请求而增加。

| 用例 | 实现后退出条件 |
| --- | --- |
| VAT49 | 错MAC／scope／source、旧boot、篡改payload、同sequence异摘要均在调用前拒绝；发现接口不泄露目录 |
| VAT50 | 响应丢失后按原token查询，重复Select／回执回收后的旧序号／OBS重启均不再次播放 |
| VAT51 | 重复URL、同条目多次播放、源销毁重建与迟到回调不借用新播放代；无法关联保持unresolved |
| VAT52 | 列表换代使cursor与CAS失效，4096条／64KiB页／4MiB总量边界不假报完整 |
| VAT53 | T6提交前不得ACK回收，旧revision ACK不删更新收据，满队列及未决回执不被挤掉 |
| VAT54 | 广播提示不含目录和秘密；源内排队超时与已调用uncertain分开，断连不伪取消设备效果 |

本节只关闭VLC辅助请求、授权、去重、保留与历史查询的设计；上述用例、真实插件及LibVLC回调均未运行。源端完成／释放资格、其余设备codec和跨域引用继续沿统一清单核对，未以此宣布C11或全系统设计完成。
