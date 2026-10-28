# C11：Mixer／DM3／WING／VB 音频控制契约

日期：2026-10-18。状态：**AD01—AD07为待审阅推荐**，不是用户已确认决策。依据[旧设备映射MXD01—MXD14、VB01—VB07](rebirth-legacy-device-map.md)，衔接[C09扩展](rebirth-c09-extension-design.md)、[F02／F03](rebirth-f02-f03-design.md)、[F06／F07](rebirth-f06-f07-design.md)及[OBS／ATEM专题](rebirth-c11-obs-atem-design.md)。本轮只编写设计、来源清单与离线检查资料，不改业务代码或draft.4／IPC 0.3，不连接真实设备。

## 1. 已知事实、来源与分析

旧源码固定`5d60491d7158f87fc27b564f510d321074aedac9`。旧配置／UI范围、目录及“实机验证”注释不等于新版支持承诺。以下固定源码引用均指该提交；官方资料的适用版本另记，不能混用。

| 已知事实 | 来源及限定 |
| --- | --- |
| Mixer有五个型号配置，旧动态入口16个action和10个trigger；WING前级按物理来源写，patch分group/index两次写 | [mixer-profile](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/mixer-control/extension/mixer-profile.ts)、[manifest](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer-adapter-mixer/extension/manifest.ts)、[WING驱动](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/mixer-control/extension/drivers/wing-driver.ts#L204)。配置不证明固件实际支持。 |
| DM3目录184行，包含174参数、4场景、6meter；含binary、string、integer等异质类型和MonitorMix/Password | [固定目录](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/mixer-control/extension/drivers/dm3-rcp-catalog.ts)。[逐行来源清单](contracts/c11-audio/dm3-legacy-catalog.json)保存全部字段和原行；不是可直接加载的运行目录。 |
| 旧VB bank有8槽，保存连接配置及跨连接点位；载入逐点发送，未列点不移除；删除本地行不是Remove | [manager](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/vb-matrix-control/extension/manager.ts#L429)。这是LeafSeamer本地预置，不等于设备PresetPatch。 |
| Matrix官方手册列出64个设备预置、点增益／mute／remove及问号查询；示例查询可返回数值或−inf | [VB Matrix手册1.0.1.8，2025-10，第9、11—13页](https://vb-audio.com/Matrix/VBMatrix_UserManual.pdf)。列出的点查询未定义LeafSeamer command_id回显或跨客户端CAS；−inf示例本身不证明路由实体不存在。 |
| VBAN TEXT有28字节头、16字节ASCII流名和32位帧计数；UTF8格式0x10；TEXT完整消息小于1436字节。SERVICE另定义请求／回复计数关联 | [VBAN revision 13，2025-09，第19—21、27—28页](https://vb-audio.com/Voicemeeter/VBANProtocol_Specifications.pdf)。TEXT计数用于帧顺序诊断，不能直接套用SERVICE事务语义。 |
| 旧VB接收仅检查长度和魔数即按UTF8读正文；写入采用乐观状态；旧Yamaha OSC驱动没有设备接收或通用查询 | [VBAN驱动](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/vb-matrix-control/extension/vban.ts#L50)、[Yamaha OSC驱动](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/mixer-control/extension/drivers/yamaha-osc-driver.ts)。本轮未运行复现。 |
| 官方DM3 OSC使用UDP49900、一基路径坐标；名称8字符、标签字符串枚举、场景0—99，并有当前场景查询 | [Yamaha DM3 OSC v1.0.0，2023-05-09，第3—8、11页](https://usa.yamaha.com/files/download/other_assets/2/2063222/DM3_osc_specs_v100_en.pdf)。11页PDF已只读核验，SHA256为9995e5e294837f65ab51b952ce317c795cf631db7644a1b8682a25c613200fcc；不是TCP RCP规范。 |
| WING历史OSC资料区分显示字符串、归一化值与原生值；普通UDP写不echo；native meter另有report_id | Music Tribe官方托管[OSC V0.56第14—15页](https://mediadl.musictribe.com/download/software/behringer/WING/BE-P0BV2-WING-OSC-Documentation.pdf)、[Remote Protocols V2.0-01第77页](https://mediadl.musictribe.com/download/software/behringer/WING/WING_Remote_Protocols.pdf)。本轮只取得官方搜索索引正文，全文下载失败，不能当当前固件完整复核。meter标识不等于普通OSC写命令ID。 |

工程分析：音频目标、物理前级、路由点、设备预置与本地收藏具有不同身份及副作用。新方案必须同时保留完整操作用途和真实证据边界；“socket可发送”“回调无错误”“值碰巧相同”都不足以证明音频效果。下面的参数、许可和状态规则是设计推荐，不宣称旧设备已具备这些保证。

## 2. AD01：统一值模型与物理目标

沿用AV01的DeviceCapabilityProfile和DeviceObservation，增加以下候选类型。全部引用绑定authority、device_id、device_session_id、topology_revision及catalog_revision；同一物理设备不得因两个配置ID出现双writer。

| 类型 | 具体字段和约束 |
| --- | --- |
| AudioTargetRef | kind=`input|output|send|preamp|parameter|scene|meter|matrix_point`、稳定target_id、profile_ref、协议坐标；显示名／一基GUI序号不充当协议身份 |
| PreampRef | source_group、source_index、source_binding_revision、alias_channel_ids；共享前级的gain／48V使用同一资源键，不按通道号拆成独立资源 |
| AudioLevel | `kind=finite`时含整数centi_db；`kind=negative_infinity`时禁止centi_db。合法有限范围、量化格点和哨兵映射由具体profile定义；不把−32768、−144和“未观测”混用 |
| AudioNumber | parameter_id、整数raw_value或具名规范值、unit、encoding_profile_ref；选择一种表示，拒绝同时提供。delay、Hz、pan、dB不互推，不能依据路径名猜量纲 |
| AudioBoolean | value为JSON boolean；profile明确将设备0/1映射为false/true及方向。mute与设备On的反向关系须逐参数声明，不能统一取反所有On |
| ParameterRef | definition_id、address、x/y及coordinate_schema_ref、access、codec_ref、sensitivity、effect_footprint_ref；用户只传已批准ID及值，服务器由目录构造协议文本 |
| MatrixPointRef | endpoint_binding、slot_catalog_revision、input_suid/input_channel、output_suid/output_channel；通道一基且受各slot实际数量限制，SUID来自批准目录 |
| MatrixPointObservation | `presence=present|absent|unknown`、gain、mute、quality、evidence_refs；gain／mute各有观察版本及年龄；未知不补0或false |

整数centi_db解决常用0.1／0.5dB量化，不擅自限制未知raw精度；无法精确映射的参数走原生整数或明确decimal编码。前端以十进制文本做格点校验，服务端再校验；无静默四舍五入或越界clamp。设备量化应在预览列出requested与encoded target，观察比较使用批准的解码规则，而不是任意epsilon。

Yamaha旧UI离散推子档、WING旧0.1dB档仅作迁移参考，不能直接设为所有型号协议允许集合。规范off与最小有限值必须分别显示。last_known仅供灰显，desired单列，任何乐观值不得进入设备事实trigger。

资源足迹采用物理对象：输入链接、DCA、MuteGrp、scene及共享HA会扩大影响范围。未证明完整成员关系时保守占整设备，不能只锁当前推子；这不改变Q35首期整设备接管。外部硬件面板或其他客户端仍可能写入，项目锁不是设备原生CAS。

## 3. AD02：Mixer全部面板与SDK能力

每项写入默认retry=never，仅派发前可取消；完成／释放分别引用证据policy。旧动作名可作为迁移映射，正式SDK名称在下一版归并时固定，不在旧draft中暗增字段。

| 保留用途 | 候选能力及参数 | 足迹与边界 |
| --- | --- | --- |
| 输入／输出推子与静音 | channel/output.set_fader(target,AudioLevel)、set_mute(target,bool) | 解析链接／DCA成员；设备On与mute方向具名映射 |
| 发送level、active、pre、pan及查询 | send.set_level/set_active/set_pre/set_pan；routing.capture(source,target_set) | 两端坐标必须属于当前拓扑；PrePost／pan不可用组合显式拒绝，查询不创建默认路由事实 |
| pan、trim、gain、delay及高低切频率 | channel.set_number_parameter(target,parameter_id,value) | gain解析到物理HA，trim保留数字域；每种单位和步进独立 |
| 48V、phase、delay／filter／gate／EQ／dynamics开关 | channel.set_boolean_parameter(target,parameter_id,value) | 通道普通页与raw页使用同一能力／风险政策；不把静音或切断连接当48V安全回滚 |
| 标签／名称／颜色等 | parameter.set_text或typed parameter.set | 文本字节长度、编码、允许字符和枚举须codec定义；JSON转义不等于RCP／OSC协议转义 |
| 输入patch | input.set_patch(channel,source_ref,expected_binding_revision) | WING两次写固定为复合计划；DM3未支持入口不得因通用UI存在而开放 |
| 原始目录查询／写入 | parameter.query/set(ParameterRef,typed_value) | 不开放任意字符串、任意OSC地址或RCP脚本入口；完整目录用途通过具名参数保留 |
| scene／meter | 见AD03独立操作 | scene不是普通set；meter不是音量控制或音频播出证明 |
| 配置CRUD／活动设备／连接／断开／自动连接 | 管理API与会话状态 | 活动设备只影响面板选择；每个动作显式device_id，禁止省略后取全局活动设备 |

旧10类trigger全部保留：connection.changed、输入／输出fader_changed和mute_changed、channel.number_parameter_changed／boolean_parameter_changed、parameter.number_changed／boolean_changed／text_changed。每类都由合格observed来源产生，含旧值／新值／编码与目录版本；初始baseline、失步恢复与质量改变不伪造值跨越。连接事件表达连接状态，不意味着设备输出停止。

阈值计算只接受同一profile、单位、来源世代及连续合格观察。number的eq/gt/lt穿越规则沿C04显式定义；boolean的0/1仅在参数codec批准后转换。meter默认展示；若未来用meter驱动规则，须另批采样连续性／丢包／年龄政策，不能将可合并遥测升级成可靠触发流。

yamaha-generic、yamaha-dm3、yamaha-dm3-osc、yamaha-rivage、behringer-wing五种旧配置都进入迁移／支持矩阵。generic不声称全Yamaha兼容，RIVAGE不沿用通用16输入／8输出当实际拓扑；仅能发送的OSC路径不得冒充已完成双向控制。补足协议适配属于保留功能所需工作，不以隐藏按钮代替交付。

原始控制的扩展用途保留为“自定义参数注册”：开发者或获授权管理员提供address、读写codec、类型／值域、目标选择器、物理足迹及证据policy，经过C09目录审批后生成具名ParameterRef，GUI仍可搜索、查询和操作。新地址不能仅因正则合法就发包；未取得证据的自定义项保留unverified状态，不以新增目录条目冒充支持完成。

## 4. AD03：DM3完整目录与特殊命令

[184项来源清单](contracts/c11-audio/dm3-legacy-catalog.json)按固定提交逐行保留index/action/address/x_count/y_count/min/max/default_lexeme/unit/value_type/qualifier/access/scale/pickoffs/raw_line及source_line。source_blob_sha256绑定Git原始blob；这不是已批准ParameterDefinition，也不能由旧默认值自动初始化设备。122—144缺OK前缀的原行保留，不把补前缀解析描述成设备证据。

来源统计为160 rw／20 r／4 w，133 integer／34 binary／9 string／6 mtr／2 none。特别保留index173为r、Monitor/St/SourceCh/St的x_count=2及Fx参数的2×2坐标。DM3 OSC另建profile：一基OSC坐标不复用零基RCP坐标，官方145参数数目不与184项旧目录合并，场景0—99／0—100差异不静默取交集。旧OSC驱动无query实现是项目缺口，不是设备协议没有查询能力。

推荐建立两层目录：`LegacyInventoryEntry → QualifiedParameterDefinition`。后者必须有legacy_source_ref、实际型号／固件、协议来源、读写codec、合法值域、权限／秘密分类、物理别名、完成与释放policy及验证引用。legacy_source_ref定位旧清单，protocol_evidence_refs定位协议依据，二者不可混用；第14节明确静态定义与会话权限拆分。每个旧条目必须对应具名能力或明确的协议缺口；不能因尚未合格就从184项覆盖表删除。

| 目录类别 | 候选冻结规则 |
| --- | --- |
| 174个prminfo | 每项绑定原index和address；x/y仅在该项明确的坐标集合内。integer用精确整数；binary不能推断为boolean，string不能用min/max猜枚举；`any`不解释成任意权限 |
| 电平／PEQ／频率 | scale和unit均保留来源值；只在厂商协议／验证确认后生成显示转换。负无穷具名；PEQ的空unit和scale=1不直接解释成Hz或dB |
| Label等binary | 拟采用独立文本／枚举codec，先证实设备编码、长度含义及响应语法；禁止以JSON字符串直接拼接命令。保持原binary标记用于审计 |
| MonitorMix/Password（119） | 标为secret；凭据写走secret_ref，禁止普通parameter.query、全文搜索预览、遥测、trigger、快照／日志和导出回显；维护角色仍可执行经批准的设定。禁止保存普通digest作为可猜测口令指纹 |
| MuteGrp、InputChLink、Monitor、Cue、HA | 声明对其它通道／监听的影响；成员／链接变化使相关计划与足迹失效；不能仅按所写地址证明操作独立 |
| 只读／无访问项 | r不生成set；w不生成query；--不生成运行入口；动态目录不得扩大审批权限 |
| Scene 1000/1001 | scene.recall/store(bank_ref,scene_index)，旧范围0—100仅作核对依据；实际存储／保护／空slot状态单独确认。Store覆盖设备保存内容，不能假称不影响后续直播 |
| Scene 1010/1011 | scene.recall_relative(direction)不伪造x/y；不自动重试，未知时不猜当前场次再次inc/dec；与绝对recall区分 |
| Meter 2000/2001/2002/2100/2101/2102 | meter.subscribe(target,pickoff,interval_profile)，六流覆盖InCh/StInCh/FxRtnCh/Mix/Mtrx/St；pickoff必须来自对应列表。记录raw及解码版本；未核实曲线前不标成dBFS，不以0..127直接推物理声压 |

DM3 ToSt目录只有一个目标时，两个Stereo显示项映射到同一发送资源；不能从GUI左右输出序号直接生成不同y。实际Stereo输出推子与输入ToSt发送是不同对象，保留各自拓扑。

RCP采用有界行解析、精确地址／坐标匹配及单连接请求账本。候选策略为写入及相关核对单飞，NOTIFY只作观察，不能填补缺失的OK／ERROR。若响应无唯一request ID，超时后污染该会话的关联资格，阻止把迟到的同址响应认给下一条；关闭并重建只读baseline，旧命令仍按原证据保留unknown，重连不重放。单飞本身不证明服务端按序完成，须在型号profile中验证应答次序与ERROR含义后批准。

固定旧驱动把Recall／Store编码为ssrecall_ex／ssupdate_ex加scene_a或scene_b，增减为event；meter查询实际是mtrstart流订阅，不是指定X通道的一次读取。旧OK／NOTIFY共用解析、ERROR仅记日志，没有逐命令关联，10秒快照也只覆盖部分参数。新版按特殊操作分别编码、清空跨会话行缓存并限定长度，不把目录query按钮或轮询周期当请求完成期限。上述为[旧驱动静态事实](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/mixer-control/extension/drivers/yamaha-driver.ts#L61)；本轮未取得官方DM3 TCP RCP应答规范，厂商OSC不能补作该证据。

keepalive、devstatus、快照和meter续订列为C09 ProtocolIOPolicy；有界集中采样，不按浏览器数量复制定时器。断线取消旧采样任务，新session不能接纳旧epoch回调。停止meter订阅不等于停止设备音频输出。

## 5. AD04：WING路由、前级和受控OSC

固定拓扑中的通道／bus／main／matrix／DCA／aux各有独立坐标，不能仅用连续outputId拼OSC路径。profile维护确切address、type tags、参数arity、枚举、范围／量化、读写及响应规则；动态未批准地址只供诊断，不能变成raw写后门。OSC包／bundle尺寸、嵌套深度及字符串长度有界；定时bundle如未建立受控调度证据则拒绝，不能让设备缓存未来写绕过接管。

响应codec须区分display_value、normalized_value和raw_value，按第18节的具名叶参数类型核对tuple及types，不能照搬旧驱动“取最后一个args”的通用规则。文档定义与实际固件资格分别绑定；native meter的report_id另属采样绑定，不升级成OSC控制ACK，也不因收到meter推断该推子写已完成。

WING patch候选流程：固定channel、旧source binding、目标group/index及计划摘要 → 完整前提／权限检查 → 按第12节选择的顺序执行第一写 → 按证据policy核对中间状态 → 必要的第二写 → 核对最终绑定。每次写分别领取许可；group＋旧index或旧group＋新index可能已有音频副作用，必须在预览列出，不能宣称先静默准备。若无法证明中间态满足场景要求，动作在派发前拒绝；节点多属性写没有自动取得原子保证，不能自动加mute、恢复旧路由或用UDP合包冒充原子事务。

一旦group发送后接管、撤权、第二写失败或反馈未知，后续index不得发送，operation报告partial／unknown及已知观察；资源按未决影响保留。新的人工处理必须基于重新核对的现场，以新command显式操作，不能在清理函数中隐式回滚。

gain／48V绑定当前物理PreampRef。LCL/A/B/C等来源是否可写、范围和步进由实际型号profile批准，不把旧UI范围当所有硬件事实；patch改变后旧channel→preamp映射即失效。多个channel共享HA时GUI显示影响列表；授权覆盖整个实际足迹。仅查到前级开关不证明接入麦克风承受情况。

续订、初始查询、应答和业务控制分账；任意OSC报文不能置ready。必须验证批准的远端地址／端口策略、类型和设备身份，收到旧值不触发自动化。UDP来源匹配不是加密认证；部署信任边界与C12网络隔离一并验收。未知OSC因果语义不得通过“连续两次相同”自造强证据。

## 6. AD05：VB点控制、预置和协议解析

保留多连接、活动连接、slot发现、矩阵点选择、可见点刷新、gain／mute、本地行管理和8槽bank。Matrix／Coconut能力从实际版本与slot目录批准；原53 SUID探测集是发现候选，不是完整物理身份，不能把无响应slot按零通道／离线事实发布。

候选动作：matrix.point.set_gain(point,AudioLevel)、set_mute(point,bool)、remove(point)、patch(point,initial_gain)、preset.apply(plan_ref)；本地收藏add/remove与bank save/delete属于配置操作，均不发送设备Remove。GUI toggle先用合格快照解析为显式目标并绑定前提；不知道点位状态时不发toggle。±1dB在预览固定绝对目标，超界拒绝；不得在失败重试时再次累加。

raw发送用途迁移为typed操作，不提供任意VBAN文本；通道与SUID取批准目录，阻止分号／括号／换行注入和隐式广播。单点写只含一个primitive；跨点写使用显式复合计划，读请求可以按查询预算合包，不将不同许可的写混成无法核对的包。

候选`AudioPreset`包含preset_id/revision、origin=`leafseamer_bank`、slot_index（0—7）、显示名、固定目标bindings、entries、配置导入引用及内容摘要。设备自带PresetPatch使用不同namespace，不能按同一个数字互相调用。保存预置只采集合格观察，未知字段明确列入缺口；不能将desired当保存的现场。

`PresetApplyPlan`含operation_id、preset_ref、mode=`merge|replace`、scope、topology revisions、canonical points、ordered_steps、各步前提／许可／足迹、expected removals、最大步骤／包数及期限。默认merge只改列出点；replace必须指明有限范围和完整当前快照后列出删除集，绝不暗删范围外路由。连接配置导入是独立维护操作，先校验重建会话与目录，再重新生成应用计划；旧load把两者混在一起的行为不保留。

计划按声明顺序执行，路由添加、增益和mute不默认指定统一“安全顺序”：现场用途决定中间态，预览必须说明每一步；有不满足前提的中间态则整体派发前拒绝。跨设备没有全局原子性；运行中遇失败按Q72处理，不跳过缺连接后报告全成功，不回滚已完成点，不自动补发。所有目标及当前授权须在计划受理时检查，派发前再次检查；跨设备资源不能靠排队占满后循环等待。

VBAN接收按TEXT与SERVICE分别解析：校验长度、子协议、format、流名、允许端点、保留字段／编码及容量，再解析批准的响应语法；未知格式隔离诊断。普通TEXT frame counter只作帧诊断；本轮核对厂商示例后，另将SERVICE REQUESTREPLY列为具名请求关联候选，详见第11节，不能泛化为所有TEXT帧都无关联。两者均不是持久事件游标或设备epoch。SERVICE ping只能证明对应服务往返，不能证明先前TEXT写完成。

查询每个point/property最多一个有效相关请求；取消刷新必须退休任务身份而不接收迟到结果进入新批次。UDP延迟无上界时，单飞、清接收队列、新本地epoch和本机接收时间都不能证明包在本次查询后采样。REQUESTREPLY方案核对关联、采样语义与版本后才可形成有界年龄观察；未合格时仅显示“收到观察、因果／年龄未证”，不得提交自动化成功或条件触发。丢包不自动重发业务写。

对−inf、−144和Err分别解析：负无穷是电平语义，Err是查询错误，不直接填presence=absent。只有profile规定并已验证的路由存在性证据才能发patched/unpatched；mute不等于remove，gain=0dB不等于未连接。既有patch.changed目标保留，但完成该功能需要解决明确的存在性证明，不迁移旧推断为事实。

## 7. AD06：证据、接管与故障时序

共享证据记录保留command/attempt、计划与primitive、profile、session、发送字节摘要、响应／观察引用、相关性与年龄判据、评估结果及持久提交引用。层次分别为传输提交、协议回复、状态观察、批准效果谓词和资源释放；音频sample／监听输出不由控制协议自动证明。

手动界面可显示“已发送／观察值／未证完成”，但不能因此改写unknown、绕过相关在途资源或自动放行第二动作。证据不足时沿F07核对／恢复，由新操作取得资格；并非以“人工按钮”豁免F02。自动化只接受合格profile；模块暂未证明不能从完整交付范围删除，也不能作为已支持模块发布。

| 时序 | 必须产生的结果 |
| --- | --- |
| 推子写已进入TCP／UDP，随后FENCE，再收到目标反馈 | 接管effective阻止新提交；已发送不变not_sent。反馈按原命令证据归档，ready仍需未决覆盖及释放证明 |
| RCP写等待超时，排队有同地址新写，旧OK迟到 | 暂停新写，旧OK不归新命令；按关联policy核对或建新session，禁止简单清Promise后继续 |
| WING group已发，接管先于index许可消费 | index禁止发送；保留中间路由影响，不能在catch补回group |
| 共享前级A的计划已预览，现场patch把通道改到B | 前提／拓扑revision不匹配拒发；不能把原48V动作转发给B |
| VB preset前两点完成，第三点unknown，其余未发 | 显示逐点结果；保留第三点不确定足迹，后续按Q72停止，已完成点不自动逆转 |
| 旧UDP反馈在重连后到达，值正好是目标 | 不能因新receive time就设fresh／succeeded；按会话／相关性证据分类，必要时持续unknown |
| 目录增加参数或出现更宽范围，现有授权尚未更新 | 仅形成候选目录；不动态扩大已批准action／raw权限 |
| 订阅过载导致触发所需变化丢失，但可见电平仍刷新 | 标来源失步并保护相关自动化；不能以GUI仍有数值宣称触发流完整 |

## 8. AD07：验收与剩余冻结

以下AUDT01—AUDT40均为待执行用例；本轮只有目录逐行比较与文档检查，不计为设备或协议运行验收。

| ID | 正反例及预期 |
| --- | --- |
| AUDT01 | 184行逐一映射；缺任一来源index或重复地址绑定即覆盖失败 |
| AUDT02 | integer／string／binary／none／mtr逐类编码；binary=1不自动转bool |
| AUDT03 | finite与negative_infinity互斥；未知值不变off；拒NaN与越界 |
| AUDT04 | 不同型号量化格点、负数和上下界；禁止静默round/clamp |
| AUDT05 | Yamaha离散UI与WING连续档分别往返；显示值与编码值一致 |
| AUDT06 | dm3 ToSt两个显示目标合并资源；实际St推子仍分别识别 |
| AUDT07 | 共享HA两个通道冲突；patch改变使旧gain／48V预览失效 |
| AUDT08 | 48V普通页／raw／自动化权限一致；未批准风险范围拒发 |
| AUDT09 | r／w／--严格限制；未知目录新增不扩大批准 |
| AUDT10 | Password不进入普通查询、日志、事件、预置或导出；secret_ref写独立审计 |
| AUDT11 | 文本多字节长度／引号／换行／NUL；不拼接第二条RCP或VBAN命令 |
| AUDT12 | DM3 PEQ空unit不误标Hz/dB；默认值不当枚举全集 |
| AUDT13 | scene recall/store两bank及边界；空／保护slot拒发，无默认覆盖 |
| AUDT14 | scene inc/dec超时不重试；重连不恢复旧scene意图 |
| AUDT15 | 六meter流pickoff和长度匹配；未核实转换显示raw不显示dBFS |
| AUDT16 | RCP分包／粘包／超长行／NOTIFY交错／ERROR匹配；不误认完成 |
| AUDT17 | RCP同址迟到OK与超时隔离；新会话不承接旧请求 |
| AUDT18 | TCP接受字节后关闭／worker崩溃；不能记未发送或撤销 |
| AUDT19 | WING patch第一写成功第二失败／接管；明确partial并无隐式回滚 |
| AUDT20 | WING OSC类型／tuple／地址／来源错误、旧包、bundle嵌套／未来时间；不把normalized／display当raw，也不把meter report_id当控制ACK |
| AUDT21 | WING续订／查询与控制队列独立预算；接管后无游离业务定时写 |
| AUDT22 | WING send −144与fader哨兵统一规范化但保留raw来源 |
| AUDT23 | Yamaha OSC只发送不能标effect_verified；通用RIVAGE目录不当真拓扑 |
| AUDT24 | VB UTF8、16字节流名、1435／1436正文边界、subprotocol及保留位 |
| AUDT25 | VB TEXT counter不冒充SERVICE事务；wrap／重启／重复／乱序独立处理 |
| AUDT26 | VB伪造端点／错误流名／格式／Err；不生成unpatched事实 |
| AUDT27 | VB −inf／−144／mute／不存在分别判定；无存在证据保持unknown |
| AUDT28 | GUI toggle和±1dB绑定新鲜前提；并发改变拒发而非猜值 |
| AUDT29 | 本地删除行／bank删除零设备写；显式Remove才进写闸 |
| AUDT30 | 八个本地bank不映射设备PresetPatch编号；导入版本绑定 |
| AUDT31 | merge保留未列点；replace只删除批准有限scope中列出的点 |
| AUDT32 | preset连接配置变化先维护，重新预览，不跨旧session继续 |
| AUDT33 | preset缺连接／重复点／冲突点／步骤超限派发前拒绝，不部分偷偷开始 |
| AUDT34 | preset中途失败／unknown／撤权；停止依赖步骤且不自动rollback |
| AUDT35 | 可见刷新不会饥饿证据查询；取消任务后旧包不属新批次 |
| AUDT36 | 10类trigger基线不触发，质量不足不穿越；0/1按具名codec转换 |
| AUDT37 | DCA／MuteGrp／链接／scene影响完整足迹，不凭不同地址证明独立 |
| AUDT38 | 同设备双配置／两Controller竞争拒绝第二writer；本地锁不伪称跨主机证明 |
| AUDT39 | 普通写、raw、预置和查询维护的出口清单完整；屏障覆盖全部异步尾部 |
| AUDT40 | 各实际型号／固件、Windows/Linux宿主及远端VB Windows组合单独记录协议与音频证据，不由静态通过继承支持 |

待冻结项有明确退出条件：①DM3各codec／单位、scene完成与meter解码逐项绑定厂商依据及可执行用例；②WING原子patch可行性、中间态政策和UDP反馈关联；③VB路由存在性、TEXT反馈年龄／因果及设备版本；④全部184项到QualifiedParameterDefinition和公共SDK、IPC、raw秘密隔离的机器归并；⑤C10专用界面及C12网络／部署预算。未解决项保留在覆盖表，不以缩减功能或降低自动化证据要求关闭设计门槛。

产品尚未实现，未批准任何设备profile上线。实现阶段须在方案审阅完成后执行上述运行验收；真实设备操作与发布仍按独立授权边界处理。

## 9. AD03细化：参数目录、编码与会话资格

本节是DM3接入候选设计，未授予运行资格。参数、协议与访问政策须绑定精确profile；设备连接时另核型号、固件、参数集和当前权限，不能将静态目录作为所有固件的保证。

### 9.1 参数成果与支持边界

| 交付物 | 内容与限制 |
| --- | --- |
| [DM3参数profile](contracts/c11-audio/dm3-parameter-profile.json) | 177条连续、地址唯一的参数定义，16条r、161条rw；包含旧174个参数地址、3个新增PortToPort参数。MuteGrpCtrl/On标记为r。静态访问标记不授予会话写权限 |
| [自包含校验器](contracts/c11-audio/check_parameter_profile.py) | 校验字段、序号、地址、值域及与旧目录的兼容差异；只读取仓库交付物，不连接设备。可复验不代表协议或设备验收通过 |
| 协议profile划分 | TCP49280文本控制、49312 R2D观察、50368原生控制分别建模；50001诊断不纳入生产控制。UDP49900 OSC另建profile，不混用寻址和完成政策 |
| 官方Crestron v2.2.0模块说明 | p1/p3列DM3及TCP49280，p3提供型号/协议/参数集/固件反馈，p17明确该模块暂不支持DM3 Scene B；不能据此推断设备没有Scene B。p18电平括注不作为转换规则。（[官方包](https://data.yamaha.com/files/download/other_assets/1/1583711/Crestron_module_DM7_DM3_CL_QL_TF_TFRACK_v220.zip)） |
| 官方DM3 OSC v1.0.0 | p3—11给UDP49900、具体参数、名称8字符、场景0—99及电平/枚举；不能替代RCP全语法、请求关联或召回完整结束政策。（[官方PDF](https://data.yamaha.com/files/download/other_assets/2/2063222/DM3_osc_specs_v100_en.pdf)） |

本目录仅交付参数定义、协议约束、合成用例及独立校验器。profile无来源环境依赖；能力是否开放仍由批准定义和当前会话共同判定。

### 9.2 稳定身份和184项覆盖的修正

**推荐**以`protocol_family + parameter_address + parameter_set_ref + definition_revision`标识参数定义；旧index和现场枚举index分别作为有来源版本的注释。旧来源统一名为`legacy_source_ref`（此前source_entry_ref），须含inventory摘要、index及地址，不能只传119。旧119是口令项，候选profile中同地址为122；不做协议命名空间限定的数字索引会把秘密分类和写目标同时错配。

184是旧功能来源覆盖：174参数＋4个场景用途＋6个聚合meter目录。177是候选profile的prminfo参数数量；17个meter地址另属mtrinfo，不能比较184与177就宣布少了7项。旧6组按各自pickoff展开为3+3+2+3+3+3=17个流，建立显式地址映射，不沿用旧2000等编号当设备mtrinfo序号。场景4个操作另定义，不从prmnum数量推断存在或不存在。

新增PortToPort的HAAvailability、48VOn及HAGain仅扩展静态目录，不自动扩大写权限；设备会话仍可能拒绝访问。推荐`advertised_access`、`approved_access`、`session_access_state`三个字段分离，实际权限取交集；AccessDenied使该会话对应能力不可用，不试探密码、不换协议绕过。MuteGrpCtrl/On的只读差异必须在新profile中保留：不可继续通过旧rw发set，也不能从整项删除来掩盖功能缺口；对应用途转入适配验证，只有独立证据批准的替代命令才可发布。

新增[编码审阅计划](contracts/c11-audio/dm3-codec-plan.json)将原184项唯一分入8组：131个整数参数、7个binary名称候选、26个其余binary、1个秘密、9个string、2个绝对场景、2个相对场景及6个meter目录。[局部Schema](contracts/c11-audio/dm3-codec-plan.schema.json)强制candidate_only/runtime_approved=false；[22组正反例](contracts/c11-audio/dm3-codec-cases.json)检查覆盖、类型与秘密投影，不执行线编码或授予运行资格。该表有意绑定旧清单，现场177项以地址对照，不直接替换其index。

### 9.3 编码器的具体冻结候选

`QualifiedParameterDefinition`在原字段外固定：legacy_source_ref、protocol_evidence_refs、protocol_profile_ref、parameter_set_ref、address、coordinate_domain、read_codec_ref、write_codec_ref、raw_domain、semantic_projection_ref、advertised_access/approved_access、sensitivity、footprint_ref、response_policy_ref、release_policy_ref、qualification_refs。session_access另置于绑定定义与会话的ParameterSessionAccess，不让动态拒绝改写静态定义身份。每个codec固定版本/hash、请求终止符、编码、token语法、长度、拒绝行为和合成向量；生成物不能靠参数名自动推断单位或布尔方向。

| 编码组 | 候选实现边界 |
| --- | --- |
| integer_decimal | wire值按完整有符号十进制token解析，拒绝尾随字符、浮点、指数、NaN及超范围；内部精确整数，不用parseInt前缀吞掉异常。发送使用规范十进制。接收是否容许前导零由固定profile列明，不自行把旧报告样例扩成语法全集 |
| 0/1与电平投影 | 0/1先保存raw，只有明确参数定义才投影boolean；mute、On、PrePost方向分别定义。电平使用具名sentinel集合与有限值域，不能把[-32768,1000]整段都当可写有限dB。scale=100不是所有量纲的自动转换授权 |
| 精确数值转换 | `raw_domain`明确区间/枚举/格点；`semantic_projection`使用有理数比例与偏移并单独处理sentinel。反向换算必须精确落在格点，否则拒绝，不round/clamp。PEQ的Freq/Gain/Q空unit保持raw，不能从字面路径猜Hz/dB |
| binary名称／其余binary | 名称候选先确定UTF-8字节/字符计数、NUL、反斜线和引号规则；其余binary必须显式映射到枚举或字节格式。未解决时不生成运行encoder，绝不将binary统一当boolean或JSON任意值 |
| string | 自由文本与枚举分开；枚举必须有完整允许token表，default只是一个候选值。数字样式字符串保持文本，不能经parseInt改型；包含引号、换行及多字节的边界须实测/官方依据 |
| secret_ref | 普通查询、触发、预置及导出无value字段；写从受限秘密解析器取得，值不进入普通intent序列化、packet调试或摘要。保存引用版本与受限执行记录，不能以口令明文hash证明一致 |
| scene_absolute／relative | 显式bank/slot或direction；相对操作不接受虚构x/y或value。Recall与Store各自opcode及证据policy；Store覆盖行为单独权限。当前scene编号相同不等于此次Recall全参数完成 |
| meter_hex | 地址/pickoff精确匹配，whole-token十六进制与字节数量按流profile核对；未知pickoff拒绝而非回落第一个。原始byte显示与dB标定分离，不把原生解码器byte−126直接用于RCP |

旧格式器只转义双引号，旧接收以正则片段和parseInt读取；不能将它们作为新版安全codec。推荐先有界保留bytes，完整分帧后严格解码、词法分析及Schema/目录核对，再允许投影。无证据的转义组合拒绝且标明不可用字符，后续批准支持时版本化扩展；不是删除名称功能或偷偷修改用户文本。

秘密保护发生在日志之前：未分类帧、ERROR回显和粘包buffer都可能含秘密，默认不写原文；只有确认非敏感的具名字段才可进入审计。未知地址仅记录长度、分类失败码及会话引用，不能把完整输入dump出来。连接异常销毁缓冲，但不宣称语言运行时可保证内存归零；秘密内存生命周期按身份/存储专题约束处理。

### 9.4 会话状态、应答和采样

候选状态：`disconnected → negotiating → catalog_validating → observation_only → qualified`；任一协议不符、超时关联污染、关键存储失败或来源失步进入`quarantined`。qualified只代表该模块profile有资格，实际写仍需Controller OPEN_GATE、用户权限、资源和每次permit，不能用连接灯替代。

首期推荐显式配置端点；YSDP只作候选发现，不作身份或权限证明。文本握手按独立单飞维护IO核对encoding/keepalive/raw及型号、固件、参数集，任何不匹配拒绝套用旧profile。候选请求终止符为CRLF；LF保活另作明确maintenance primitive，各组合须通过对应profile验收。响应按LF分帧，只按profile去除最多一个尾CR；禁止trim整个payload或把超时残留当完整行。

全连接至多一个待应答事务，而非仅每地址单飞；心跳、devinfo、目录查询和meter开始/停止也纳入关联调度。NOTIFY只能归观察通道；缺关联的ERROR不能当作某次set明确无效果失败。已进入传输的写出现无法归属的回应、超时或重连，一律保留可能影响并隔离旧会话；不清Promise后接着发同地址命令。纯空行保活不填补缺失的OK，不能刷新参数观察年龄。

对于已证明应答有序且无中间缓存的固定profile，写ACK后在同会话新发get，核对精确verb/address/coordinates/value及目录代，可作为参数状态完成候选；只有TCP字节有序、观察同值或本地时间较晚均不足以建立这一政策。事件可能来自原生面板，状态完成只声明目标状态已核实，不声称独占因果或实际声学输出。scene、设备内渐变和链接传播另有完成/释放政策，不继承普通参数set结论。

meter是受控订阅会改变设备发送状态，按C09维护IO登记，不能作为无副作用get。订阅键绑定session、实际流地址、pickoff、通道数与codec；停止确认不证明音频停止，断连换代后旧数据不能归新订阅。mtrstart的参数个数、interval单位及省略行为须逐profile定义；未完成相应用例前不得将默认值作为设备保证。保留六组17流用途，参数化语法须夹具补证。

有限实验预算：行上限8192字节、未分帧buffer32768字节、token最多128个、单连接待应答1项、普通队列32项、保护槽4项、目录最多1024项、meter最多32流；每请求截止2000ms、总目录发现180s、普通采样20请求/秒、每轮解析最多64行后让出。均为夹具候选，不是设备保证；发现超限/错误不发布部分目录，meter过载不得丢失关键回应后继续自动化。现场需要更大预算时必须新profile审阅，不能自动扩容。

### 9.5 原生协议的引入边界

推荐保持同一DM3模块下的显式`rcp|osc|native`协议profile，共享唯一物理设备身份、整设备接管与资源图；协议不能在失败时透明切换。原生profile用于补足patch等能力，不从RCP缺少地址推断设备不存在该能力。49312 R2D观察独立建模，50001诊断台不纳入生产控制入口。

原生外层frame采用4字节标签及4字节大端payload长度；必须先核长度和完整分帧，再解释TLV。profile另固定功能/schema注册、参数寻址、目录同步及握手副作用清单。初始化只能使用已批准的维护步骤；设备返回同值不证明存在request ID、恰好一次或接管后无后效。身份/cache token不是授权令牌。

Patch值候选按24位group和8位member组合：`(group << 8) | member`；解码为`group=(value >> 8) & 0xFFFFFF`、`member=value & 0xFF`。例如group=`0x14000`、member=8得到`0x01400008`；group=`0x16000`、member=11得到`0x0160000B`。不能直接把group和member相加。

新版先拒绝非整数及超出24/8位的输入，再编码，不能用掩码使越界值静默回绕。合法位宽不等于可用物理端口：允许组合仍须绑定当前型号、目录与拓扑profile。值编码、参数地址、选择子及TLV标志分层验证，不能凭一个patch值推出任意参数写法或目标可用性。

设备回传内容相同只可作为观察，不能自动提升为请求唯一关联、完整路由生效或音频输出证明；消息分类和完成政策须分别冻结。本候选没有延迟保证，仍需支持矩阵、新版Schema/IPC及设备验收，不增加固件改造或虚拟DCA的默认实施范围。

## 10. 本轮新增故障与验收设计

正常参数轨迹：显式端点→单飞协商→完整目录比对→已批准profile→持久intent/permit→发送→匹配ACK→新get及合格观察→可靠完成。目录冲突轨迹：旧清单rw，当前枚举r→禁止set并显示访问差异→不以原生协议自动回退。超时轨迹：已发set→超时隔离→迟到OK→仅历史核对，后续同址请求不接收旧结果，接管仍需完整账本。

以下AUDT41—AUDT56均为**未运行的协议／设备验收**；本轮22个DMC用例仅验证审阅计划资料。

| ID | 正反例及通过判据 |
| --- | --- |
| AUDT41 | 旧184来源覆盖与现场177参数分开；地址对应后处理154项序号移动，不能index直连 |
| AUDT42 | MuteGrpCtrl/On现场r拒写；新增PortToPort rw但AccessDenied仍不可用，不自动扩大权限 |
| AUDT43 | 旧119/现场122指向同一秘密地址，普通事件/日志/ERROR不泄漏值或可猜测hash |
| AUDT44 | integer完整token：12x、1e2、NaN、浮点、非法尾部拒绝；文本数字不转型 |
| AUDT45 | 电平哨兵与有限域分离；精确反向格点失败拒绝，不把PEQ raw猜成Hz |
| AUDT46 | UTF-8跨chunk、引号/反斜线、空字符串及多字节长度按profile验证；无第二条命令注入 |
| AUDT47 | CRLF/LF分帧逐组合验证；残留超时不产完整行，单独LF保活不当参数ACK |
| AUDT48 | 维护请求与业务共享单飞关联；NOTIFY交错不完成set，未关联ERROR隔离 |
| AUDT49 | set超时后同址新请求不接受旧OK；重连不重放，旧buffer不能进新会话 |
| AUDT50 | 6组meter展开17流，错误pickoff/数量/hex尾部拒绝，不回落0；raw与标定dB分离 |
| AUDT51 | mtrstart不同参数形式、订阅/取消/续订与接管分别验证；未证interval不作设备保证 |
| AUDT52 | Scene A/B范围与空/保护slot逐一验证；Store与Recall权限分离，current编号不作完整完成 |
| AUDT53 | 目录数超限、缺行、重复地址、类型改变不发布部分可写目录；发现重试不延长总截止 |
| AUDT54 | RCP/OSC/native同物理设备只一writer，协议变更先维护；失败不跨协议续发 |
| AUDT55 | 原生8字节分帧、TLV、schema地址与24+8位值分别验证；Local/8为0x01400008，直接相加错误；group超0xFFFFFF、member超255或非整数拒绝，位宽合法但拓扑不支持也拒绝 |
| AUDT56 | 原生注册/目录同步只用已批准维护步骤；实测状态通知不冒充请求ACK、授权或音频完成 |

实施前还需收敛的具体输入是：文本编码/终止符及meter间隔的固定证据、名称/枚举全部token与长度、scene完成policy、原生寻址和同步副作用、正式资格Schema与SDK机器归并。上述候选已有明确的设计边界，但运行门槛尚未通过。

## 11. AD05细化：VB请求回复、存在性与释放证明

### 11.1 本轮新增事实与限定

2026-10-18只读核对[厂商新闻页](https://vb-audio.com/archive/Blog/VBAudioPressRelease_Nov2025.htm)直接链接的[官方示例固定提交](https://github.com/vburel2018/VBAN-Text-Client/blob/dfe047e9b8741bc26043055b23c060af52ab7591/vbantxt_client.c#L150)：发送TEXT后，接收分支识别SERVICE `0x60`、服务ID `0x02`、回复函数 `0x80`，返回帧号与正文。该C文件SHA256为`7658394c8047f79a0a9aa9a7b6f9f0609dc0ce4363380e722066a9a0be004bfe`。示例没有完整pending匹配、远端端点校验或效果判定；客户端源码不证明所有Matrix版本的服务端行为。此前“TEXT计数不是通用事务号”仍成立，但不能由此遗漏这个专用回复分支。

[VBAN revision 13第27—28页](https://vb-audio.com/Voicemeeter/VBANProtocol_Specifications.pdf)规定SERVICE回复计数关联请求，未列出上述ID 2的完整应用语义。[Matrix 1.0.1.8手册第13页](https://vb-audio.com/Matrix/VBMatrix_UserManual.pdf)列点gain/mute/phase查询，但未定义明确的点存在性查询；第9与15页对Apply影响范围有矛盾，不能据此冻结批量删除行为。厂商新闻与示例README的最早支持版本表述也不同，支持矩阵必须以精确程序版本和资格记录绑定，不能只做版本大于某值的判断。

### 11.2 推荐的请求关联与观察契约

在同一ProtocolIOPolicy中加入`vban-text-service-reply/1`候选，普通TEXT观察和SERVICE ID 2回复使用不同入口。所有字段均为下一版SDK/IPC候选，未改draft.4。

| 对象 | 字段与规则 |
| --- | --- |
| VbanRequestBinding | request_id、device/session/profile引用、transport_namespace、local_socket_ref、remote_endpoint_ref、stream_binding_ref、wire_counter、query_target、property、request_digest、issued_tick、deadline_tick；wire_counter在API中用十进制字符串，线头编码uint32LE |
| VbanReplyEvidence | request_binding_ref、packet_digest、received_tick、service_id/function、wire_counter、reply_target/property、typed_value或typed_error、codec_ref；关联结果由可信适配器生成，不接受模块自报matched=true |
| AudioObservationPolicy | profile_ref、correlation_rule_ref、sample_rule_ref、presence_rule_ref、completion_rule_ref、release_rule_ref、qualification_refs；引用独立版本证据，不能用一个“已验证”布尔值包办全部保证 |
| PointPresenceEvidence | target、snapshot/request引用、classifier_ref、state=`present|absent|unknown`、reason；classifier输入必须足以区分无点、已静音点、−inf点、slot离线及查询错误 |

回复先验证报文边界和精确SERVICE类别，再匹配端点、绑定socket、未退休counter及预期target/property；service id 0的PING、未知服务、普通TEXT与错误编码不得落入同一成功分支。服务回复中的附加字段、流名规则与正文编码按已验证profile固定，不能机械套用发送TEXT的UTF8格式位。默认采用单点单属性查询，整段查询只有在完整性标志和最大回复数量已证明后才启用，超时不能发布半个快照。

counter在同一可混淆的远端/本地路由命名空间中永不复用：持久高水位先预留再发送，崩溃跳过未用区间；重连或恢复业务备份不得归零。当前计数达到uint32上限时关停该命名空间的新请求，不自动wrap。另建namespace必须证明旧报文不能投递并被接受；仅更换进程内UUID、随机源端口或等待几秒不算证明。高水位丢失时需要重新配对和来源隔离，不从旧备份继续计数。该台账属于不能随业务恢复降低的传输身份资料，沿C12 installation恢复约束归并，而非放入可重放outbox。

pending状态为`reserved → submitted → replied|expired|cancelled`；这些是内部请求状态，不新增公共Command终态。取消/超时后旧counter永不再匹配新请求；迟到回复仅作原请求诊断，不能令旧command从unknown改成succeeded。重复相同回复去重，重复但内容冲突使profile来源失步。纯查询可用新counter重试一次且不延长原任务总截止；业务写绝不因此重传。

**条件分析**：若固定服务端资格证明“回复回显该请求的counter，且值在收到该请求后采集”，可将采样时刻限制于`[issued_tick, received_tick]`，当前最坏年龄为`now_tick-issued_tick`，以同一单调时钟域计算。counter匹配本身不证明后半句；服务端返回缓存时，必须另有缓存年龄证据，否则采样质量仍不合格。一次新读取也不自动证明之前另一UDP包中的写已被执行或不会稍后到达。

### 11.3 点存在性和写后完成的具体退出条件

推荐将“查询成功”“新鲜观察”“目标效果成立”“未来不会再有该attempt的写”四项独立记录。单点数值回复可以先获得类型正确的观察；未有presence规则时，presence仍为unknown，不抹掉可显示的数值，也不发patched/unpatched触发。−inf、mute=1、Err和静默均无默认存在性分类。

资格实验必须对同一已知点执行：有点且有限增益、有点且−inf、有点且mute、显式Remove、slot离线、坐标越界、重启恢复，逐状态采集gain/mute/phase的REQUESTREPLY原文并与设备路由图对照。只有响应签名集合互不混淆且有适用版本证据，才批准一个明确classifier；若有重叠，该查询组合不能承担存在性证明。不能反过来将所有Err定为absent来让测试通过。

写后路径有两种待验证方案，均不靠等待固定延时补证：①服务端提供与写counter关联的完成确认，再以新查询核对目标；②单个包仅包含一个获许可的绝对写primitive及其后的一次查询，并证明固定版本按顺序执行且查询在写应用之后采样。方案②不是多写批处理特权，也不是厂商已保证；其顺序、部分错误、重复包及完成含义都必须验收。若只有独立写包＋读包且无顺序证据，读到目标值不能构成该写完成。

这两种路径还都不能自动排除UDP重复或长期延迟副本造成的后续写。释放需独立的服务端去重/排空机制，或经明确审阅的有条件部署假设及失效检测；有限测试中的最大延迟不能冒充硬上界。新增本地代理只能在它真实截断的链路上给保证，不能靠mTLS包裹后就消除代理到Matrix的UDP未决。缺少依据时保留unknown及资源影响；不缩减完整VB功能目标，也不将仍缺完成/释放证明的profile标为可上线。

厂商设备PresetPatch的Apply/Recall/Unapply暂不用于实现LeafSeamer的8槽bank；本地bank继续展开成明确点操作。这样不依赖手册矛盾去推断删除集。显式设备预置能力若后续注册，必须独立绑定区间范围与影响证据，不能将整preset计数查询冒充每个点的完整快照。

### 11.4 容量与故障轨迹

候选实验预算：单设备最多8个只读pending，同点同属性1个；独立保护查询保留2槽；普通队列64项；单查询2秒、总发现30秒；普通查询最高20项/秒；请求正文最多1435字节，超限拒绝而非截断；回复单包上限1464字节，按服务profile核对正文，不自动拼接分包。计数器空间是有限资源，分配耗尽产生明确维护状态。上述为夹具预算，不是厂商吞吐保证；设备列表超过预算时分页，不能一次探测完整3112×3112点。

正常只读轨迹：预留counter 41→发送目标点gain查询→收到SERVICE ID 2且counter 41→校验目标和类型→按已批准sample policy提交观察；presence单独按classifier决定。失败轨迹：41超时→42发同址查询→41迟到，拒绝填入42→42若合法只形成新观察，旧写及旧unknown不改变。接管轨迹：写已提交→FENCE阻止新写→收到只读回复，仍分别评估原写完成和释放；请求表排空不等于设备写排空。

## 12. AD04细化：WING源绑定与原生查询路线

### 12.1 已知事实和不能据此承诺的行为

本轮核对[Music Tribe官方CDN托管的Remote Protocols 3.1-03](https://cdn-media.empowertribe.com/2106004e217b8eb2639d93672823eef5/WING_Remote-Protocols-3.1-03.pdf)，页脚版本3.1.0：p21的`/%<port>`仅重定向回复端口；p22单参数写不回显；p23—24节点多属性写可返回OK/错误，但未承诺原子性。p47分别定义主/备用的grp/in及altgrp/altin，altsrc选择与srcauto另有作用。p94/97给native TCP2222及查询值、描述、结束token；p113明确临时连接也可能收到主动事件；p117的写返回值只是发送字节数。

据此不能将回复端口当nonce、节点OK当音频完成、TCP有序或查询结束标记当先前写的引擎屏障。文档没有给出通用request ID或关闭native主动事件的操作。这里的“未给出”仅限所核对文档，不能扩成设备不存在任何可用关联途径；旧库或示例按首个匹配token取值的问题也不证明协议必然不可用。

### 12.2 推荐的PatchPlan与中间态规则

`WingSourceBinding`固定channel、conn.primary(group,index)、conn.alternate(group,index)、altsrc、srcauto、topology/profile revision、observation_refs；若同次捕获不能证明一致，绑定为incoherent。GUI当前活动页或旧sourceGroup不是完整输入源身份。请求显式`branch=primary|alternate`及`activate=false|true`；配置备用源与切换实际输入是不同动作，禁止因用户改备用地址就隐式切换altsrc。

`WingPatchPlan`包含before_binding、target_binding、ordered_primitives、intermediate_bindings、affected_sources、effect_footprint、precondition_refs、completion_policy、release_policy及plan_digest。各primitive列address、typed_value、前后投影、风险及许可槽；任何参数无法解析或来源拓扑缺失时在发送前拒绝。主/备用两套源及可能受共享HA影响的对象都进入足迹；srcauto或外部面板变化使计划失效，不能在执行中自动改算目标。

推荐按下列顺序选计划，不改变原AD04的每写许可规则：

1. group不变时只写index；index不变时只写group，避免无必要的第二次写。两者均不变仅可报告有证据的当前配置相同，不伪造“设备执行成功”的记录。
2. 两者都变时，先评估`(目标group,旧index)`和`(旧group,目标index)`两种中间绑定，检查端口存在性、信号来源及批准的现场过渡政策。固定选择通过检查且代价较小的一条，预览准确列出；两条都不被允许则派发前拒绝，不自动加mute或借备用源切换绕过。
3. 节点多属性写保留为独立`node_multi_property`候选模式。若没有各属性处理顺序和中间态证据，须保守覆盖两种顺序及部分应用；仅在所有可能中间态都被允许时才可考虑批准。只有额外证据证明原子性，才能另版提供atomic模式，单包或OK均不满足。

这些步骤是计划规则，不是假定设备有CAS。软件预览与派发之间的外部控制竞争仍须在profile前提中列明；若场景要求排除该竞争而设备不支持对应机制，就不能批准该场景。配置观察一致也不自动证明声学切换无瞬断、串音或爆音，相关要求须专用音频测量。

复合操作在内部保留`planned → first_submitted → intermediate_observed → second_submitted → target_observed`进度；已发后任一步失去关联、撤权或接管均停止后续写。progress可以显示partial，公共Command终态仍沿既有succeeded/failed/unknown等枚举，不新增partial终态掩盖不确定性。中间态未证时不发第二步；最后一步not_sent也不能清除第一步的影响。人工修复是绑定新观察的新command，不在finally中回滚。

### 12.3 原生读取的具体候选与资格实验

推荐调查独立native读取连接，以完整二进制解析代替旧OSC“最后一个args”或示例“首个匹配token”；控制与观察仍共享同一设备身份和接管域，不能因此得到第二writer。解析状态为`idle → query_open → collecting → ended → validated`，任何超限、未知结构或关联歧义转`quarantined`。任一时刻仅一个未完成查询，区分节点ID、类型、查询结束token及主动事件；不能把`0xDE`本身当无条件snapshot complete。

`WingCaptureEvidence`包含connection/session、query_sequence（本地诊断，非线上nonce）、requested_node_set、parser_profile、start/end tick、完整返回节点、主动事件插入记录和coherence判定。只有证明响应区间/事件分类后，才允许validated生成合格观察；同node主动事件与查询响应无法区分时明确ambiguous。未曾订阅、临时连接、先清队列、两次相同结果都不作为绕过规则。

首先验证节点多字段捕获是否提供完整绑定的一致视图；若只能逐叶查询，必须有版本标记或经过审阅的稳定性证明，不能把不同时间采到的主源、备用源与altsrc拼成一张“原子快照”。写后再查询还需证明服务端处理顺序及引擎应用含义。`wKeepAlive`、发送缓冲flush、native事件FIFO和meter report ID分别有自己的用途，不互借完成语义。

验证夹具明确覆盖：在查询前、中、后插入同node与不同node事件；一组返回中重复或缺失节点；跨包拆token；异常长度；合法第一属性＋非法第二属性；外部切换altsrc/srcauto；FENCE夹在两步间；断线后旧回调。若文档及实验仍无法形成可区分的返回语法，该读取路线保留为诊断，缺口返回profile设计，不直接宣布全WING完成。

候选预算：单查询2秒、native累计响应1MiB、节点4096个、嵌套深度8、单字符串4096字节、完整捕获5秒；超限终止本次捕获且不发布部分合格数据。大小仅用于设计夹具，完整设备目录可用批准分页；不得把截断记录当结束。唯一发送出口覆盖OSC写、native写及握手/keepalive等维护IO，TCP关闭只证明宿主不再发，不撤销已提交字节。

## 13. 本轮新增验收与未冻结边界

以下AUDT57—AUDT72是**未执行的运行验收**，不把官方文档阅读当协议测试。公共Schema、IPC及业务代码保持原样。

| ID | 正反例及通过判据 |
| --- | --- |
| AUDT57 | VB合法SERVICE ID2/function0x80与pending关联；普通TEXT、PING、错service/function不能完成请求 |
| AUDT58 | 正确counter但错端点/socket/target/property或已退休仍拒绝；重复同文去重、冲突内容失步 |
| AUDT59 | counter跨进程崩溃跳过预留区，业务备份恢复不归零；uint32耗尽拒发，重连不自动wrap |
| AUDT60 | 固定版本验证回显counter和查询后采样；缓存值无年龄依据不合格，截止等号按统一到期规则拒绝 |
| AUDT61 | 同点有限值/−inf/mute/Remove/slot离线/越界逐态对照；任何歧义不批准presence分类或patched触发 |
| AUDT62 | 写＋查询同包验证顺序/部分错误，跨包逆序不得成功；写回复与效果及资源释放分别取证 |
| AUDT63 | 原写的迟到重复副本在新观察后到达，不能因查询完成或本地代理签名宣告原写排空 |
| AUDT64 | 请求1435/1436字节边界、回复上限、8+2槽与慢消费者；超限拒绝无截断命令、半快照或保护槽饥饿 |
| AUDT65 | WING主/备用、altsrc/srcauto完整绑定；只改备用配置不隐式切换活动输入，缺字段不能批准计划 |
| AUDT66 | group不变单写index；两字段变更分别计算两中间态，两者不允许则零发送，无隐式mute/回滚 |
| AUDT67 | 节点多属性第一合法第二非法，记录真实部分生效；OK/单包不能通过原子性断言 |
| AUDT68 | /%端口仅路由；端口复用旧包、主动同node事件不能伪作本次nonce回应 |
| AUDT69 | native查询前/中/后事件及重复节点分别分类；结束token不自动授予完整、一致和新鲜资格 |
| AUDT70 | 逐叶采样跨altsrc/srcauto变化不拼一致快照；新连接未订阅仍处理主动事件 |
| AUDT71 | 第一primitive已提交后接管或撤权，第二步许可拒发；显示中间影响，公共终态和释放仍分开 |
| AUDT72 | 跨包token/超长字符串/过深嵌套/累计响应超限失败关闭；keepalive与flush及发送字节数不通过引擎完成断言 |

本轮已给出请求关联结构、Patch计划算法、解析状态及故障判据；VB的presence分类、写后采样和迟到副本释放，WING的一致捕获和引擎完成仍缺可批准依据。它们不是“实现时随便决定”的参数，也不能通过新增布尔标记关闭。后续须取得适用版本证据或明确提出改变保证的取舍供审阅；当前仍保留完整功能范围和先设计后实现的阶段限制。

## 14. 局部机器契约及跨项衔接修正

2026-10-18整理[候选Schema](contracts/c11-audio/audio-candidate.schema.json)、[75组人工正反例](contracts/c11-audio/audio-candidate-cases.json)及[离线报告](contracts/c11-audio/audio-candidate-report.json)。这批是上述推荐的可校验审阅资料，包络强制`purpose=design_fixture_only`及`runtime_approved=false`。它没有改变draft.4或IPC0.3，也不构成下一版完整SDK。事实依据是本稿、F02/F03及现有机器模型；以下衔接为推荐设计修正，不是新取得的设备保证。

### 14.1 参数定义、权限及引用

局部`ParameterDefinitionCandidate`只校验RCP prminfo来源对照；OSC/native仍保留原设计用途，其不同地址映射不能硬套这个验证器。场景、meter、完整codec值域及184项正式资格展开仍需后续归并。局部结构使用独立`Ref`（authority_service_id/object_id/revision/digest）表达不可变引用，不声称它与draft.4所有Ref等价；最终SDK归并须按对象种类映射，不能直接发送本夹具对象。

推荐将定义固定字段与会话状态拆开：`advertised_access`和`approved_access`属于固定定义；`ParameterSessionAccess`包含context、definition_ref、access_revision、session_access与effective_access。有效集合必须等于三者交集，重连须换device_session_id并重新取证；旧定义只读不能靠会话rw扩权。定义中的approved仅描述目录层批准，不代替当前用户授权、OPEN_GATE、资源与每次发送许可。

读写codec可以显式null，避免只读或未合格项伪造write codec。普通值曝光依赖批准的read；秘密只能secret_ref_only，无普通query/trigger/snapshot/preset/export值投影，不允许value、明文摘要或原文错误字段。旧清单定位按摘要/index/address联合检查，协议依据另列protocol_evidence_refs；不能将新的枚举序号直接套入旧清单。夹具中的codec、原始值域、足迹和资格引用都是合成占位；格式合法及引用相等不证明所引对象真实、完整或已获批准。

秘密项的advertised_access必须如实保留设备宣告，例如旧119的rw；禁止的是approved read、read codec和普通值曝光，不能为了满足保护规则把设备事实改成w。AC10覆盖“宣告rw、批准空集、无曝光”的正常记录。

### 14.2 VB时钟、请求摘要和独立观察通道

第11节三个tick字段在候选中明确为`issued_tick_ns/deadline_tick_ns/received_tick_ns`，均为uint64范围的规范无符号十进制字符串；加`task_deadline_tick_ns`限定重试不能延长总截止。请求/回复均绑定`clock_domain_id + descriptor_digest`，与draft.4 ClockDomainRef含义对齐，跨域不得比较。准入检查严格要求issued < deadline ≤ task_deadline，issued ≤ received ≤ now < deadline；最坏年龄now-issued在等于max_age时失效。有限位数和词法由Schema限制，uint32 counter及uint64时间数值上界由关联检查补足，不能依赖浮点parseInt。

ClockDomainRef直接保留draft.4的`descriptor_digest=sha256:<64位hex>`表示，并要求clock_domain_id等于`clock_`加该hex；即使请求、回复、可信夹具三处相同，内部派生关系错误也拒绝。完整descriptor内容、摘要重算和运行域权威仍是DF02/draft.4的职责，本局部夹具没有证明它们。其它局部Ref.digest及两项审阅摘要使用裸hex，归并时必须显式映射到目标对象的摘要类型，禁止自动混用。

固定两项独立JCS投影：`audio.vban-request-binding/1`规范化完整VbanRequestBinding对象，仅排除其自身request_digest；`audio.wing-patch-plan/1`规范化完整WingPatchPlanCandidate，仅排除自身plan_digest。其他顶层及嵌套字段一律保留，不能借用公共Command的content_digest投影。VB摘要绑定逻辑查询、路由引用、会话和截止，不是线上包字节摘要；packet_digest另记收到的非秘密查询报文。两种digest都不是签名或授权。原始字节解码、重复键拒绝及完整JCS跨语言实现仍沿DF01要求；本轮仅执行Python参考规范化。

SERVICE ID2/function0x80结构与typed value/error互斥；关联检查核对请求摘要、端点/socket/流/namespace、counter、point/property、会话及clock。pending必须仍为submitted，退休请求不能生成本次观察；high_water定义为已持久预留区间的**独占上界**，counter < high_water ≤ 2^32。数字关系不证明高水位已持久化或跨备份不回退，AUDT59仍需故障运行验收。

本局部模型的MatrixPoint.endpoint_binding_ref与请求remote_endpoint_ref引用同一个不可变远端绑定对象，必须相等；不能只核对回复照抄了请求，却让点目标属于另一个端点。若后续引入配置端点/解析后传输端点两种对象，必须有受信映射和版本验证，再修订此规则，不能仅更名后跳过关联。

纯轮询没有command_id/attempt_id，不得伪造它们接入现有`EVIDENCE_CANDIDATE`。本局部对象称VbanReplyCandidate，暂归观察通道；绑定命令的证据由Controller另外核对command/attempt并经T6持久提交，归并时再定义相应IPC映射。禁止候选自报matched、durable、资源已释放或命令成功。夹具的sample_policy、可信context/clock及pending均为人工输入前提，不是新实现的信任来源；`fresh_observation`仅指这些前提成立时的观察分类。−inf仍是有效电平，不产生presence=absent，也不完成旧unknown命令。

### 14.3 WING计划结构与执行绑定

计划绑定完整context、channel（1—40）、initial_observation_ref、before/target、branch/activate、ordered_primitives、affected_sources、足迹及完成/释放policy。channel必须匹配可信初始观察的通道，同设备同配置也不能跨通道复用；数值在范围内不等于该profile已批准目标。primitive有稳定primitive_id，before/after只允许所声明的一项变化；每步precondition_slot必须引用初始观察或上一步observation_slot。slot仅是计划中的待填证据位置，不能作为已经取得的设备观察或已发许可。

主/备用两种计划均允许group-first或index-first，但每个非最终中间态须在批准的现场政策中出现。只改一个字段只生成一步；字段不变且不切活动源时生成零步，表示“配置已相同”，不生成虚构执行成功。`activate=true`且活动分支确实变化时，最后独立执行altsrc primitive；group/index调整与激活合计最多3步，每步都需新观察及独立许可。activate=false不能改altsrc；本动作不修改另一分支或srcauto，不允许额外的mute/回滚步骤。node多属性模式、设备内部自动切换和声学无瞬断不由此计划证明。

`affected_sources`取before与每步after两套源的去重排序并集，拒绝遗漏中间来源；这是检查显式源足迹的下限，不能证明共享HA/链接等隐式影响已完整。实际footprint_ref仍需C09依赖图和批准政策，夹具只核对预期引用。全量运行归并须把每个primitive_id分别关联到operation/command/attempt/intent/permit；不能把两个不同参数写合并成同一个重试，也不能凭permit_slot复用旧许可。它们属于运行执行绑定，不进入这份不可变计划，须通过plan_digest回指。

正常轨迹：完整观察→计划及中间态检查→第一步独立许可/提交→合格中间观察填槽→第二步重新检查授权及许可→目标观察。故障轨迹：第一步已提交→FENCE→第二步许可拒绝→保留第一步影响并停止；即使计划摘要和所有结构校验通过，也不得补发第二步或隐式回滚。这个故障仍由AUDT71/FT运行验收覆盖，本轮未模拟真实屏障、线程或持久事务。

### 14.4 已执行检查与仍需归并的范围

AC01—AC75检查来源与静态/会话权限交集、秘密曝光、错域/错端点/迟到与截止等号、uint32边界、重算摘要后的错配、两种换接顺序、备用激活、零步计划及中间态/足迹遗漏。所有预期人工给定，验证器不生成预期；正例使用合成引用和信任前提。75项通过不包含完整协议解析器、跨语言SDK、SQLite高水位、实际授权、实时采样、网络和设备测试。

后续必须归并的边界明确保留：全部参数/scene/meter资格与codec定义、现场profile批准来源、观察通道和命令证据IPC分离、primitive执行绑定及T1/T6表结构、presence/完成/释放证据policy，以及GUI的相关状态显示。不能把这份局部候选Schema发布为完整音频API或用它关闭C11。新增报告独立绑定四个原字节输入，使用本目录检查器核对工作区/暂存区，不默认为原十份报告检查器已经覆盖。

## 15. 数值编码与多primitive执行归并

### 15.1 当前证据与适用范围

已核对Yamaha DM3 OSC v1.0.0第9页原表：电平使用整数线值，-32768表示负无穷，表内还列出-13800、0、1000等有限点；pan以-63／0／63表示左／中／右。它不能证明RCP或其他Yamaha型号采用同一格点，也不能仅凭表列举点推出所有中间值的量化行为。VB Matrix 1.0.1.8第11—13页区分dBGain、Mute和Remove，并将-inf列作增益查询结果；这里没有把该查询示例当作负无穷写入语法或路由不存在证明。（来源：[Yamaha官方规格](https://usa.yamaha.com/files/download/other_assets/2/2063222/DM3_osc_specs_v100_en.pdf)、[VB-Audio官方手册](https://vb-audio.com/Matrix/VBMatrix_UserManual.pdf)。）

OSC 1.0的i与f分别为大端32位整数和IEEE754 binary32，s使用NUL终止及四字节对齐；该基础规格的字符串为ASCII。厂商明确扩展的字符编码须独立写入codec，不能因为SDK内部使用UTF-8就声称所有设备名称均接受相同字符。（来源：[OSC 1.0规格](https://opensoundcontrol.stanford.edu/spec-1_0.html)。）

以下定稿的是数值／线字节与执行关联算法。DM3全部RCP binary／string词法、各型号完整量化／文本表、WING当前固件的原生／归一化转换和设备完成／释放资格仍需逐项来源，不能以本节通用算法冒充全部音频适配完成。

### 15.2 两阶段精确转换

1. **业务目标。** 先在批准ParameterDefinition的raw_domain／semantic_projection中验证单位、范围、格点、枚举和sentinel。十进制输入按有界字符语法解析成精确整数比例，禁止parseFloat前缀、NaN／Infinity、指数捷径和locale小数逗号；坐标／参数身份来自批准目录。AudioLevel有限centi_db与negative_infinity为互斥分支；原生raw值不因为长得像dB就自动取得单位。GUI拖动若需要吸附，必须显示确定的目标并以该目标提交，服务端不静默round或clamp。
2. **线表示。** 只有业务目标已精确成立，才按codec执行指定线编码。integer_decimal和OSC int32必须整除／在其原范围内，字节与完整token可逆；decimal-text按具名固定精度或最短精确十进制策略输出，不使用宿主locale。OSC float32则从精确有理目标**一次**按round-to-nearest、ties-to-even选binary32位型；这是明示的线表示转换，不是把非法业务格点修成合法目标。禁止先经binary64再转binary32而产生双重舍入差异。溢出、下溢到零、非有限位型及未获profile允许的subnormal均拒绝；零使用正零，不能把-0当作额外业务状态。
3. **绑定和比较。** 编码记录保存requested_semantic、codec_ref、参数／目录版本、encoded_wire及精确decoded_wire_value；float还保存8位十六进制bits。Controller核对这些字段及原计划，原packet字节摘要另算。设备自身再量化是第三个独立问题，必须有批准的量化函数／有限映射表才能预测observed目标；没有时可以保留合法原始观察，但不能用任意epsilon证明效果或触发值相等。
4. **解码。** 先核完整帧、类型标签、arity、padding、有限长度和精确目标身份，再按对应read codec解码；raw与显示值分开保存。display／normalized／native tuple只能按声明的位置和类型读取，不取“最后一个args”。语法合法但单位或量化未明的值保持raw／unqualified，不造合格AudioLevel或boolean。名字字符长度、UTF-8字节长度和OSC填充分别检查；未知编码不替换为问号后当原值。

如精确目标1/10编码为binary32，线bits应为3dcccccd，其精确值是13421773/134217728；这不等于把任意输入先round到0.1。1+2^-24恰在相邻binary32中点，ties-to-even选择3f800000；1+3×2^-24选择3f800002。参数是否允许这些目标仍由该参数格点决定，例子只固定序列化算法。接收NaN／无穷位型不能走AudioLevel.negative_infinity分支；负无穷必须由该codec明确的设备sentinel解码。

DM3 OSC的mute只对明确的Fader/On投影取反：mute=true对应On=0；其他On、PrePost或phase保持各自具名语义，不能全局取反。上述电平表用于建立明确映射和测试点，不把表内-32768到1000的数值跨度当连续有限dB。VB单点写由目录构造完整SUID／一基通道／属性和单个赋值；只批准一个primitive，禁止把用户文本拼成范围、分号附加命令或广播。-inf、Err和缺响应分别处理，均不自动产生presence=absent。

### 15.3 多primitive与现有IPC的唯一绑定

当前panel4的TransportPacket、TransmissionRef、EncodingAuthorization已经含primitive_id／primitive_plan_ref，TransmissionRef另有parent_dispatch_intent_id及ordinal；[逐传输契约](contracts/c08-controller/BARRIER_ATTEMPTS.md)明确不同primitive分别拥有原业务意图和packet。本节直接采用当前52帧及[编码授权顺序](contracts/c08-controller/ENCODING_AUTHORITY.md)，不为音频另开第二设备出口或复用第14节候选中的permit_slot充当真实许可。

单设备WING patch或多点VB计划由Controller执行一条公共command的固定primitive计划，保留同一command／attempt及整设备hold；每个primitive分别拥有dispatch_intent、packet、EncodingAuthorization、首次ordinal=0及逐次permit／issue／Guard。原DF04基础字典UNIQUE(attempt_id)仅能描述单primitive历史布局，产品应按完整scope／command／attempt／primitive建立原意图唯一键；后继protocol_resend始终指同primitive原意图，不能把第二属性写伪装成第一属性的重传。

原子受理先固定完整计划、顺序、所有中间态与足迹、precondition／observation槽、原截止和全部预算上界。第一写之前检查整个计划可接受，之后每个primitive在自身编码和最终发送前重新核当前权限／控制／保护／原件以及上一步的合格观察。首次T2取得hold，后续T2只可使用该命令仍有效的同一hold及新Ownership／资源前后态，不重新取得第二个活跃hold，也不在两步之间释放。前一步观察只证明其具名条件，不直接让整个command succeeded。

WING主／备用source与altsrc采用第12／14节的完整顺序及中间态政策；VB同设备计划保留所有点，不把场景不接受的中间态隐藏到预置执行中。跨设备是各设备独立command／hold及有序聚合；跨Controller由既有Seamer执行计划协调，不创建虚拟跨库command。独立Controller仍可执行自己拥有设备的复合动作，不依赖部署Seamer才能完成单设备patch。

任一步明确失败、关联丢失、接管、撤权或超时均关闭未发的后继primitive，保留已发／未知集合，不继续下一步或在finally回滚。public终态沿现有枚举，partial只作进度；全计划效果满足固定政策才可能成功，资源另按所有primitive／attempt／取消传输的完整ResourceCut和ReleaseEvidence核销。第2步未发不能证明第1步无影响，零步计划只返回有证据的配置已相同，不能制造设备执行成功。WING／VB业务写默认retry=never，不能因通用IPC支持protocol_resend而自动启用设备写重传。

### 15.4 实施出口及剩余范围

本节关闭精确业务数值与线float32舍入的冲突，以及多primitive到现有编码／许可／hold的归并缺口。SDK生成编码记录和具名codec定义，Controller实现纯编码核验、同命令多primitive登记与完整cut，worker实现被批准编码器及唯一I/O出口，GUI分别显示目标、编码值、观察和部分进度。

沿AUDT／A12补验：ties-to-even和双重舍入反例、整数边界、sentinel与非有限混淆、tuple错位、名称字节／字符边界、同attempt不同primitive不串账、第二步被FENCE阻断、第一步未知保留hold、整个计划预算不足零发送，以及跨设备部分成功不伪装整体成功。当前仅官方表格／Schema和精确算术检查；完整型号codec表、真实产品网络／SQLite／设备及声学测量未运行，C11仍未整体关闭。

## 16. RIVAGE型号坐标、条件codec与场景编码

### 16.1 官方依据与确定边界

本节采用Yamaha [RIVAGE PM OSC v1.0.2](https://usa.yamaha.com/files/download/other_assets/5/1407565/RIVAGE_PM_osc_specs_v102_en.pdf)，适用说明为固件V5.00及以后；不据此宣称后续每个固件均已验收。第15页列出四种引擎的最大通道数，第4—5页同一Dyna1／Dyna2 Attack地址按Dynamics类型给出不同缩放，第3／11页用字符串场景号。以下数值来自这些表格；其后的选择、校验和失效规则是本项目采用设计，不是厂商提供的并发保证。

| 引擎 | Input | Mix | Matrix | Stereo坐标 |
| --- | ---: | ---: | ---: | --- |
| DSP-R10 | 144 | 72 | 36 | 1—4 |
| CSD-R7 | 144 | 60 | 36 | 1—4 |
| DSP-RX | 120 | 48 | 24 | 1—4 |
| DSP-RX-EX | 288 | 72 | 36 | 1—4 |

Stereo的1／2／3／4分别是AL／AR／BL／BR。表中数值为边界，不证明某会话内全部通道可用；配置的引擎必须与可信设备识别和当前拓扑一致。GUI输出目标保存kind及index，不把Mix／Matrix／Stereo拼成一条无类型的outputId；自定义显示排序不改变协议坐标。未知型号不退回16输入／8输出，变更引擎或拓扑须生成新绑定并使旧目标失效。当前会话可用集合是批准profile与合格拓扑的交集，不能仅靠用户填写型号授予写资格。

| 具名参数规则 | 线类型与比例 | 坐标／解释限制 |
| --- | --- | --- |
| InCh／Mix／Mtrx／St Delay/Time | int32，raw=毫秒×1000，raw范围0—1000000 | X按该类通道，Y=1；不得先把毫秒取整 |
| InCh HPF/Freq | int32，raw=Hz×10，raw范围200—20000 | Y=1／2为Bank A／B，不能固定为1 |
| InCh LPF/Freq | int32，raw=Hz×10，raw范围200—200000 | 同样显式绑定Bank |
| InCh Dyna1/Attack及Dyna2/Attack普通表行 | int32，raw=毫秒，raw范围0—120 | 仅适用已确认普通变体的类型集合 |
| 同地址COMP260表行 | int32，raw=毫秒×1000，raw范围10—80000 | 必须绑定已确认COMP260变体，不能与普通行合并取并集 |

上述比例确定整数线表示，不宣称设备在整个数值区间接受每一个整数或按同一精度保存；设备量化沿第15节独立批准。例如1.25ms的Delay编码为1250；0.01ms的COMP260 Attack编码为10；普通Attack的0.01ms不能整除而拒绝。同一raw=10在普通与COMP260变体分别表示10ms和0.01ms，不能跨变体比较或触发。

### 16.2 条件codec的权威与失效

目录生成键不能只有address。每个ParameterDefinition绑定协议／固件profile、目标坐标模式、variant_id、selector_parameter_refs、selector_predicate、read／write codec及语义投影；variant_id是本项目稳定定义身份，不是设备返回的新字段。普通与COMP260分别保留定义，普通分支必须列出有依据的类型集合，禁止把unknown或不认识的类型一律归普通。产品生成器检查同一profile／目标的分支互斥；匹配零个或多个分支均不产生可写ParameterRef。

Controller在计划受理时保存选择器的合格观察引用及所选完整定义，绑定device_session、catalog及topology版本。每步编码与最终发送再次核对原选择器仍有资格且取值／修订满足前提；外部变化、失步或无法确认时拒绝未发步骤。计划若包含选择器写入，受理时必须固定变更后的目标变体、后继完整定义／编码及中间态；取得该选择器的新合格观察并验证固定前提后，才允许后继步骤。不能用旧codec预编码后盲发，也不得就地替换第15节的不可变计划。实际变体或目标不属于原计划时，关闭原计划后继资格，通过新计划和新命令受理，已发影响仍保留。

只读观察也绑定采样所用选择器。无相关选择器证据时只存raw／unqualified，不能用接收时GUI当前类型解释迟到raw值。选择器变化先使相关值baseline及自动化依赖失效，重新取得同变体合格baseline后才恢复阈值判断；raw相同而codec改变不产生伪造数值跨越。该检查仍需C11独立完成／释放及部署资格，软件二次校验不提供设备端CAS。

同原则适用于表中Ratio、Release等依赖Dynamics类型的参数，但必须逐项补足其精确类型标识、量化及sentinel，不从Attack规则推导其它参数。v1.0.2中Threshold表格下界与GATE／DUCKING注释不一致，不能选择较宽界或猜符号自动修订；保留该变体未合格并要求权威勘误或受控验证。静态表行存在不是全部条件codec已完成的证明。

### 16.3 场景与文本分支

RIVAGE recall采用地址`/yosc:req/ssrecallt_ex`，两个OSC string参数依次为`MIXER:Lib/Scene`及场景号。项目规范输入保存独立整数major（1—999）和minor（0—99），生成`major.minor`且minor固定两位；例如5／0生成`5.00`。线上标签为`,ss`，不带引号字符，不追加X／Y，不转float或复用DM3的scene_a／整数slot；不把范围内每个编号当作已有场景。存在性、保护与完成证据沿具名场景policy，默认不重发。

读取配置或导入的字符串必须完整匹配`[1-9][0-9]{0,2}\.[0-9]{2}`再拆整数，不接受前缀解析、符号、指数、小数逗号或静默修复。这个格式是项目唯一规范表示，不声称设备拒绝其他词法。场景store、relative recall和meter不从这条recall命令推导；需要各自协议依据后才有运行入口，完整交付范围保持。

名称、颜色、icon、patch字符串分别使用其表／模板，禁止把RCP binary类型复制到OSC或把string都当自由文本。名称的八字符限制与OSC字节／填充限制分层校验，字符集扩展仍需型号依据。MonitorMix口令仍走secret_ref专用路径，不因该规范给出字符串长度就纳入普通查询、导出或日志。

### 16.4 本项出口

本节关闭RIVAGE引擎拓扑、同址条件缩放和场景身份与DM3混用的具体设计缺口，转入SDK条件定义生成、Controller前提／观察绑定及GUI变体显示实施。沿AUDT补验四引擎首尾／越界坐标、Bank A/B、同址不同scale、未知及重叠分支拒绝、变体变化后的旧计划与迟到观察、场景两个string和边界词法。当前只复核官方PDF表格并执行精确算术／规范字节检查，未执行产品生成器、真实OSC、SQLite或设备测试。RIVAGE完整枚举／条件表、DM3 RCP、WING及VB剩余codec和完成／释放仍逐项保留，不以本节关闭整个C11。

## 17. DM3 OSC具名线绑定与目录计数

采用[DM3 OSC v1.0.0具名绑定表](contracts/c11-audio/dm3-osc-v100-bindings.json)作为产品生成的参数输入之一。其依据为[Yamaha官方OSC v1.0.0](https://usa.yamaha.com/files/download/other_assets/2/2063222/DM3_osc_specs_v100_en.pdf)第4—11页；文件只保存协议事实及未决标记，不分发原PDF。purpose为documented_wire_bindings，runtime_approved=false；它不是ParameterDefinition的替代品，不能直接加载成当前运行资格。

### 17.1 覆盖与类型

第4—8页逐行有123条唯一set地址，按页分别29／27／29／34／4条；另有两个bank各一条recall及当前场景查询，共4条场景操作。第11页的prmnum标注为145，和上述两种行数分别保留；不为凑145而生成22条未知地址，也不将这个差额解释为确定缺少22个功能。它们与RCP的184项覆盖／177项参数表不是同一身份空间。

| 绑定值域 | 地址数 | 生成规则 |
| --- | ---: | --- |
| off_on | 57 | OSC i、raw 0／1；业务boolean的含义仍由具名参数确定，PrePost不自动解释为pre |
| level | 18 | OSC i、比例100、dB及-32768 sentinel；有限域与设备量化沿第15节，不从区间跨度推断全部可写格点 |
| pan | 15 | OSC i、边界-63／63；Table 2显示值与raw分开，不能发送L63等显示字符串 |
| name | 8 | OSC s、最多8字符；字节／填充和字符集资格另核，不截断输入 |
| color／icon | 7／7 | OSC s，分别精确使用Table 3的11个及Table 4的56个token；保留大小写、空格和标点，不能发送枚举序号 |
| input_category／output_category／fx_return_category | 2／4／1 | 分别采用Table 5的10个、Table 6的4个token及唯一FX RTN；不能合并成全类型都接受的并集 |
| link_group | 3 | OSC i，0为NONE，1—9对应A—I；显示字母不作为线上string |
| ha_gain | 1 | OSC i，0—64，Table 7按整数dB对应；绑定Local Input而不是当前channel的显示序号 |

绑定表已保留所有确切地址、x／y范围、具名计数来源及出处行。输出类名InCh／StInCh／FxRtnCh／Mix／St／Mtrx／Fx等不得由GUI统一outputId猜测；Stereo Channel数2与Stereo Bus数1分别使用。Mute Group数6不授予DCA操作；官方该profile的DCA数量为0，不从其它Yamaha型号继承入口。

### 17.2 明确不作推断的分支

StInCh和FxRtnCh到Mix／Fx／Matrix的22条发送参数在表中Y为1，绑定表标记send_y_fixed_1_requires_confirmation。保留该原值，不自行扩成目标总数，也不以此宣布其余发送能力已完成或应删除。产品实现先保持该分支未合格，准确目标语法须由同协议型号依据解决；不能拿InCh的Y范围或RCP坐标补作OSC事实。

11条PrePost的表格注释只写OFF／ON；标记pre_post_direction_not_specified，禁止将raw=1直接当作pre=true。与RIVAGE中明确Post／Pre的对应不能跨型号复用。两个标记可以同时存在，生成器须保留全部阻断，不能仅保留第一个。无标记仅表示没有本表这两类疑点，不自动证明量化、会话权限、响应、效果或释放。

名称和枚举使用OSC s而非RCP binary；枚举引号只是文档排版，不进入线值，FX RTN中的空格属于token。地址由完整ParameterRef解析，用户不能传字符串扩展目录。只读模型的解析器和来源年龄必须另有依据，本表set行不自动产生get或订阅响应codec。

### 17.3 场景与实施出口

scene_a／scene_b各自recall采用`/yosc:req/ssrecall_ex`及`,si`，参数为bank字符串和0—99整数；查询采用`/yosc:req/sscurrent_ex`及`,s`，只有bank。两种请求都没有普通set的X／Y路径段，不复用RIVAGE的ssrecallt_ex和小数字符串。这里未定义的响应、store、relative recall、scene 100或meter不能从recall格式推导；完整既定用途仍按各自协议补齐，不以一个查询存在就认定原Recall完成。

本节关闭DM3 OSC已公开set表的逐地址／值域／枚举绑定及计数混用缺口，明确剩余坐标与PrePost语义疑点。SDK生成时将本表与已批准的语义投影、会话访问、物理足迹和完成／释放policy组合，缺任一依据不生成可写资格；Controller及GUI消费相同定义，不能在各端各猜一套。目录录入和11类序列化已有固定输入，产品编码器及正常／异常回复、真实设备量化、字符支持、保护与释放验收后置。RCP词法仍未获得可替代的依据，本表不关闭RCP或整体C11。

## 18. WING叶参数编解码与来源坐标采用

### 18.1 文档依据与三类返回

以下采用[厂商托管的WING Remote Protocols 3.1-03](https://cdn-media.empowertribe.com/2106004e217b8eb2639d93672823eef5/WING_Remote-Protocols-3.1-03.pdf)第20—24、40—44、47—48及51页的线格式；页脚版本3.1.0，文件SHA256为`b4496d27440e47b63729ac16786a631224e4c0a21efb9fda7f378d40ed6589ce`。这是具名协议定义，不能仅因固件版本号较大就推导兼容。部署目录仍须绑定实际型号、固件、拓扑和定义修订；不导入文档示例中的网络地址、序列号或会话数据。

对于已批准的**单个叶参数**，OSC地址、type tags和参数数目必须同时匹配；下面的位置为从零开始的args索引。node列表、node字符串dump、blob/native、错误事件及meter不得进入此分支。

| 文档类型 | 返回tags／arity | 参数位置与消费规则 | 首期绝对写的线类型 |
| --- | --- | --- | --- |
| F | `,sff`／3 | args[0]是显示字符串；args[1]是0—1归一化binary32；args[2]是该参数单位下的原生binary32。三个值分别保存，语义投影只消费具名原生值 | `,f`／1，按第15节从准确业务目标生成原生binary32，不发送归一化值 |
| I | `,sfi`／3 | args[0]是显示字符串；args[1]是归一化binary32；args[2]是原生int32。boolean只在对应参数的原生域确为0／1时投影 | `,i`／1，原生int32；不把浮点归一化值转换成整数 |
| S（字符串或枚举） | `,s`／1 | args[0]就是线字符串；是否为枚举、合法token、文本长度及字符规则由该参数定义决定 | `,s`／1；枚举发送确切token，普通字符串不得借用枚举接受集 |

SDK定义同时保存read tuple、write tag、native domain、单位／投影、sentinel和访问模式；读写tags不同不能复用一个序列化声明。显示字符串只供显示，不用parseFloat恢复控制目标；归一化值只保留为观测，不把其乘以参数最大值当作原生值。文档的fader例子中0.7000对应−2dB、0.6750对应−3dB、0.7500对应0dB；这些点不证明整个区间是一条直线。首期OSC绝对写已可直接使用原生值，因此不再把“先推导一套全局归一化逆函数”作为该写入分支的设计前置。需要复现设备滑杆曲线的GUI映射仍须独立的具名曲线，不能用上述三点外推。

文档允许对0／1整数参数发送−1来toggle，也允许用整数序号选择部分枚举；本项目的绝对set编码器固定发送0／1或字符串token，不由一次set生成toggle或依赖枚举排列的ordinal。缺少范围、单位、合法token或条件分支时拒绝该定义的业务调用，不以设备接受多种类型为由逐类型重试。浮点NaN／IEEE无穷不是业务negative_infinity；fader示例的显示`-oo`和有限原生−144另由fader域解释，不能用于其他F参数。这里不把−144至10的表列范围和1024 steps推成1024个等间距dB格点。

### 18.2 路由叶参数与来源目录

通道地址`/ch/{c}`中c为1—40；下表中所有索引仍须经过实际拓扑核验。（来源：同规格第47页。）

| 路径后缀 | 原生域／写入 | 路由中的用途 |
| --- | --- | --- |
| `/in/conn/grp`、`/in/conn/altgrp` | S，`OFF,LCL,AUX,A,B,C,SC,USB,CRD,MOD,PLAY,AES,USR,OSC,BUS,MAIN,MTX`，逐个token独立 | 主／备用来源组；不与输出路由或User Signal的枚举取并集 |
| `/in/conn/in`、`/in/conn/altin` | I，1—64 | 主／备用来源组内索引；64是字段上界，不代表每组存在64个源 |
| `/in/set/altsrc`、`/in/set/srcauto` | I，0／1 | 分别记录主备用选择及自动来源切换状态；与group/index一起进入第12节绑定 |

来源坐标按其自身目录校验，不把strip数、返回节点数和物理端口数混为一谈：第40—43页列LCL最多24且受型号约束、AUX 8、A／B／C各48、SC 32、USB 48、CRD／MOD各64、PLAY 4、AES 2、USR 56、OSC 2。OFF仍保留合法线索引，语义上不生成物理前级；不能擅自写index=0。文档节点上界不证明对应扩展卡、舞台箱或物理接口已安装。

USR不是56个同类物理前级：1—24是User Signal，25—56是User Patch。其`/io/in/USR/{u}/user/grp`在前者只取`OFF,CH,AUX,BUS,MAIN,MTX`，后者只取`OFF,LCL,AUX,A,B,C,SC,USB,CRD,MOD,PLAY,AES`；`user/in`的表列上界分别为40和64，仍按所选来源组验证。`user/tap`的PRE／POST和`user/lr`的L+R／L／R仅适用于1—24。符号为数字的字符串枚举仍按S处理，不能仅凭字面数字改成I。（来源：同规格第43页。）

`/io/in/$BUS`、`$MAIN`、`$MTX`在第43—44页分别列32、8、16个来源节点；这与`/bus`的16、`/main`的4、`/mtx`的8个strip不是同一坐标域。不得直接用同一个整数或未经证实的左右声道算式互换。跨域映射须由批准拓扑显式列出，不能从数量恰为两倍推出映射及物理前级身份。

第40页另定义`/io/altsw`及`/io/autoaltovr`两个0／1全局参数。第12节的来源绑定必须加入这两项的原始观察及其定义版本，作为路由／前级计划的依赖；任一变化均使原绑定失效。表中名称不足以确定它们与altsrc／srcauto的完整优先级，不能只按通道altsrc就断言当前物理源。物理PreampRef需要具名解析规则和同一合格捕获；未知时保留待解决，不能把主源、备用源或所有LCL源当作默认答案。

### 18.3 独立地址与型号差异

以下三组不得合并成一个宽范围定义。（来源：同规格第40—41、47、51和60页。）

| 对象 | 文档具体差异 | 采用约束 |
| --- | --- | --- |
| 物理输入gain与通道关联gain | `/io/in/LCL/{n}/g`及A／B／C对应路径列−3..45.5、98 steps；`/ch/{c}/in/set/$g`按LCL列−2.5..45、20 steps，按AES列−3..45.5、98 steps | 不取并集、不假定同一格点，也不把通道关联值直接用作物理写。后者须绑定来源条件；当前来源与具体HA能力尚不明确时不能形成前级写资格 |
| 通道main发送与main strip | 第51页`/ch/{c}/main/{m}`列1—4，并在脚注27给WING Rack的1—8，关联机背四个立体声耳机输出；第60页`/main/{m}`仍列1—4 | 脚注仅作用于其具名路径。不能据此扩展`/main`、其他发送族或所有型号；Rack的跨域目标映射仍需具名定义 |
| 原始控制与有效状态 | `/ch/{c}/mute`为I 0／1；`/ch/{c}/$mute`为只读I 0—2；`/ch/{c}/fdr`与只读`/ch/{c}/$fdr`分别为原始和受DCA影响的电平 | `$mute=2`不能转boolean true或回写mute；`$fdr`不能覆盖原始fader目标或成为其写地址。`$`不是统一只读判据，访问权逐项采用原表 |

### 18.4 实施交接与未决边界

本节关闭WING普通叶参数三类tuple、绝对写tag以及通道主备用路由／USR分支枚举的编码规则缺口。SDK按上述具名条件生成定义；Controller核对完整tuple和同版来源绑定；GUI区分原始控制、有效状态、归一化观察与显示文本。编解码实现和已明确表格的机械录入进入实施，不再为每个同类叶参数另建候选包。正常回复、错type／arity、错域／错枚举、只读状态误写、toggle混入绝对set、全局来源变化和Rack路径范围混用进入AUDT／A12。

仍需解决的WING设计依据限定为：实际来源选择优先级及跨域物理映射、HA条件差异、确实需要的具名数值曲线／sentinel／量化与文本规则，以及观察关联／完成／释放政策。单参数写无回显、node OK非声学完成、返回端口非nonce等既有边界不变。三个tuple的静态字节核对不证明任何当前固件、真实产品或设备运行通过；本节不关闭整体C11或阶段0。
