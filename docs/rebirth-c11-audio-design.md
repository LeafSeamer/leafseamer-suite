# C11：Mixer／DM3／WING／VB 音频控制契约

日期：2026-10-17。状态：**AD01—AD07为待审阅推荐**，不是用户已确认决策。依据[旧设备映射MXD01—MXD14、VB01—VB07](rebirth-legacy-device-map.md)，衔接[C09扩展](rebirth-c09-extension-design.md)、[F02／F03](rebirth-f02-f03-design.md)、[F06／F07](rebirth-f06-f07-design.md)及[OBS／ATEM专题](rebirth-c11-obs-atem-design.md)。本轮只编写设计和静态来源清单，不改业务代码或draft.4／IPC 0.3，不连接真实设备。

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

推荐建立两层目录：`LegacyInventoryEntry → QualifiedParameterDefinition`。后者必须有source_entry_id、实际型号／固件、协议来源、读写codec、合法值域、权限／秘密分类、物理别名、完成与释放policy及验证引用。每个旧条目必须对应具名能力或明确的协议缺口；不能因尚未合格就从184项覆盖表删除。

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

响应codec须区分display_value、normalized_value和raw_value，逐路径核对tuple及types，不能照搬旧驱动“取最后一个args”的通用规则。历史文档的,sff例子仅用于形成反例，必须按实际固件确认；native meter的report_id另属采样绑定，不升级成OSC控制ACK，也不因收到meter推断该推子写已完成。

WING patch候选流程：固定channel、旧source binding、目标group/index及计划摘要 → 完整前提／权限检查 → group写入 → 按证据policy核对中间状态 → index写入 → 核对最终绑定。每次写分别领取许可；中间的group＋旧index可能已有音频副作用，必须在预览列出，不能宣称先静默准备。若无法证明该中间态满足场景要求，动作在派发前拒绝；推荐调查厂商原子patch方式，不能自动加mute、恢复旧路由或用UDP合包冒充原子事务。

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

VBAN接收按TEXT与SERVICE分别解析：校验长度、子协议、format、流名、允许端点、保留字段／编码及容量，再解析批准的响应语法；未知格式隔离诊断。frame counter可诊断重复／乱序及wrap，但不当command_id、持久事件游标或设备epoch。SERVICE ping只能证明其对应服务往返，不能证明先前TEXT写完成；应用重启／序号重置须重新核对身份。

查询每个point/property最多一个有效相关请求；取消刷新必须销毁任务身份而不接收迟到结果进入新批次。UDP延迟无上界时，单飞、清接收队列、新本地epoch和本机接收时间都不能证明包在本次查询后采样。需要设备回显／受支持关联机制或有证据的型号采样profile；否则仅显示“收到观察、因果／年龄未证”，不得提交自动化成功或条件触发。丢包不自动重发业务写。

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
