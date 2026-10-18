# C11：OBS／ATEM 全能力契约与完成证据

日期：2026-10-17。状态：**AV01—AV06为待审阅推荐**。本稿覆盖[旧设备映射](rebirth-legacy-device-map.md)的OA01—OA10、AA01—AA08，不替代已确认F06 OBS首闭环；进一步明确全部旧面板功能及协议库边界。未改业务代码或draft.4／IPC 0.3，未安装程序、启动服务或连接设备。

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

1. **VLC指定条目播放**：保留真实功能目标。推荐评估固定的OBS端辅助接口，以明确的playlist generation＋item identity选择并回报实际当前项；不采用改selected、按猜测index循环NEXT、暗改列表顺序或读私有内存结构。标准接口现有证据不足，辅助接口能否通过受支持扩展实现、是否需修改VLC源及独立许可制品必须先完成设计审阅；尚未冻结，不能默认安装或将其记为已完成旧功能。
2. **ATEM库边界**：推荐固定受审阅传输适配，显式传播逐项发送失败、提供逐次重传门控和完整待发账本。库tag／tarball一致只证明来源，补丁及原生／线程产物仍须DF05固定；不将3.7.0直接批准上线。
3. **ATEM效果与年龄**：逐型号给出设备反馈到命令／执行代的证明路径。普通缓存与时间请求不够；若协议无法提供所需因果证据，需评估厂商受支持控制接口或明确较弱手动政策，不能默认降低自动化要求。该结论是待设计问题，不是删除ATEM范围。
4. **全量能力机器契约**：将本表每个action、target、错误码、复合计划及证据政策合入下一版SDK；OBS四帧仅保留原适用域，不把通用DeviceActionEvidence存在当作验证器已实现。Media／Transition／Stream／ATEM专属profile须有正反例及独立批准。
5. **型号及预算**：实际固件、合法range、重传预算、采样年龄／完成期限和解码容差由固定夹具取证。设计必须给字段、选择规则和失败关闭行为，未测试的数字不得包装为生产默认；完整支持矩阵在实现验收后发布。

本稿将旧面板用途落实为候选契约并揭示新的实质缺口，尚未关闭C11。Mixer／DM3完整目录、WING与VB、GUI身份流程、部署恢复及跨项机器归并仍须完成；全部系统方案审阅前继续不进入业务实现。
