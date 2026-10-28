# C10：GUI 操作、状态投影与恢复交互

- 日期：2026-10-18（Asia/Tokyo）；责任仓库：GUI，依赖SDK、Controller、Seamer及Suite。
- 已确认约束：Q3／Q69统一网页操作台、完整简中和英文；Q42／Q47单持有人和持久接管；Q55—Q57身份及组织授权；Q71完整NodeCG兼容。用户要求先完成全部系统方案，再进行业务实现。
- 已知事实：[draft.4模型](contracts/draft4/first-loop.schema.json)分别定义命令、控制记录及恢复操作；[F02／F03](rebirth-f02-f03-design.md)区分接管effective和gate ready；[C05](rebirth-c05-event-sync-design.md)要求完整快照交接；[C09](rebirth-c09-extension-design.md)限定面板委托；[C11图文](rebirth-c11-nodecg-design.md)、[视频](rebirth-c11-obs-atem-design.md)、[音频](rebirth-c11-audio-design.md)分别限定设备证据。
- 当前采用状态：UI01—UI07的交互规则结合第11节的当前契约绑定作为首期实现输入；旧字段与现有选择冲突时按第11节裁决。剩余具体接口缺口见第11.4节，不再将全部交互笼统列为待审阅。未实现网页、SDK或服务，未修改历史机器制品；客户端展示状态不新增服务端命令终态，也不构成授权证据。

## 1. UI01：入口、身份及工作台

推荐保留两个主工作台，另设操作记录和受权管理入口。设备工作台提供实例列表、连接／观察质量、当前持有人、专用面板、通用能力表单及命令详情；自动化工作台提供定义、状态表、转换和动作序列、排期、运行及恢复。关系图是辅助视图，不成为唯一编辑或操作入口。

独立Controller模式只要求Controller与GUI；无Seamer时显示“未配置自动化服务”，不能把整个GUI判成故障。套件模式依据已配置服务身份及兼容组合连接指定签发方；用户输入的URL、显示名、设备名均不能重定向秘密或自动建立信任。初始化只检查身份、版本、可达性与配置，不试切、试音、启动推流或布防。

顶部常驻显示当前站点／Controller、主体及签发方、设备或运行目标、连接与同步状态。切换服务实例时隔离状态缓存、草稿和未决请求，不把同名设备合并。管理页分身份／配对、模块批准、组织运行授权、时间与容量、维护与备份；看见页面不表示拥有其中所有权限。配对、增权和凭据管理使用宿主近期认证；日常已授权控制不逐次弹确认。

登录、Cookie、Origin／CSRF及短期单audience令牌沿用[F04](rebirth-f04-f05-design.md)。GUI只在内存持有访问令牌，秘密不进入URL、持久草稿、遥测或错误报告。浏览器只持久保存语言、主题等非敏感偏好；编辑草稿首期保存在有权限的服务端，未保存输入只在当前页面内存。恢复登录不自动提交旧输入，退出清除敏感内存和面板通道；服务端已受理记录保留并按重新授权查询。

会话失效时，停止该会话新请求、关闭相关订阅／委托并显示重新登录入口；已发命令不能冒充撤销成功。页面关闭、失焦、退出和持有人离线均不释放接管。组织RunGrant独立显示：人员退出不会隐式撤销组织自动化；停用人员可同时明确选择撤销关联授权，但人员停用不等待这一步。撤销详情逐目标显示受理／应用／未确认，不用一个绿色提示代替传播结果。

## 2. UI02：权威投影、命令和未知结果

GUI状态由服务端快照和有序增量驱动。以下为展示职责，精确字段路径和原件类型按第11节绑定，不另定义同名平铺DTO，不接受客户端将其上传为可信状态。

| 投影 | 必要来源／字段 | 展示及更新规则 |
| --- | --- | --- |
| 服务视图 | service_id、实例世代、协议／组合版本、同步scope、stream／epoch、cursor、authorization revision | 按C05完整Manifest、页数／对象数／digest交接；各服务独立水位，不能拼成跨服务原子快照 |
| 设备视图 | device_id、目录及能力revision、Observation及质量、ControlRecord、当前相关CommandRecord | 目标值、设备最后观察和命令证据分开；仅设备可达不代表允许写入 |
| 命令视图 | command_id／revision、state.phase／outcome／effect_status／resource_status／reason_code／resolution_ref、completion.required／achieved及证据引用 | 按下表组合展示；未知终态只追加核对，不回改成功；隐藏无权限的证据内容 |
| 控制视图 | ControlRecord的control_epoch／effective_version／holder／mode／pending_change／gate_state及在途、未决列表；ControlOperation | operation历史成功不能覆盖更高版本的当前持有人；服务重启／epoch改变需重新建立baseline |
| 恢复视图 | lifecycle__RecoveryPreview的baseline／plan／unresolved_command_refs及LifecycleOperation.targets | 按证据引用读取获授权详情，显示计划和逐目标结果；不把preparing或ready翻译为恢复完成 |

| 真实协议状态 | 推荐中文展示 | 禁止推断 |
| --- | --- | --- |
| 请求尚无可靠响应 | 提交结果待确认 | 不在客户端造command_id；HTTP超时不等于未受理 |
| queued／pending | 已受理，等待派发 | 不显示设备已执行 |
| dispatching／pending | 正在派发 | IPC投递、写入API调用和设备已收到不可混称 |
| awaiting_evidence／pending | 等待完成证据 | 不以按钮回弹或设备值相同代替关联证据 |
| finished／succeeded | 按策略完成，并列“已发送／已应答／效果已核实”实际级别 | sent级成功不能标为效果已核实；effect_verified也不保证观众像素 |
| finished／failed | 失败，并列effect_status与资源保护 | failed不保证无副作用，partial必须可见 |
| finished／unknown | 结果未知，显示核对和保护状态 | 不改成失败后自动重试；resolution不重写原终态 |
| finished／cancelled、expired、blocked | 已取消／已过期／已阻止，附真实效果和原因 | 取消请求已受理不等于已取消；不凭文本推断not_sent |

本地同步视图可用`loading／current／resync_required／disconnected／unauthorized／incompatible`，它们不是公共命令枚举。发生缺口、权限范围变化或epoch变化时，该scope标为不可据以写入；旧值加“最后已知”及来源时间标签，禁止继续累积控制输入。重新连接只重建快照和查询结果，不重放操作、不解除暂停、不布防。慢GUI自身失步不自动停止健康的Seamer运行；执行端是否暂停按其自身C05保护判定。

同epoch、同对象revision重复一致可忽略，较旧版本不倒退界面；同身份不同内容或无法比较的世代触发重新同步，不能按浏览器收到的先后取最后值。序号和纳秒使用SDK大整数表示，不转Number排序；跨主机单调tick不能相减。UTC显示带时区／质量，浏览器倒计时只作提示，不能给服务端时效追加宽限。

## 3. UI03：接管、转交及设备可写

推荐将“控制权”和“当前允许操作”做成独立区域。写控件可用的必要条件为：当前同步范围完整、身份和目标权限有效、目录／绑定有效、本人为当前manual持有人、gate_state=ready且相关资源／维护／容量允许。GUI判定仅用于提示；受理和最终发送仍由服务端复核，不将disabled按钮当安全边界。

| 操作阶段 | GUI行为 |
| --- | --- |
| 请求接管 | 提交expected ControlVersion及身份；202后显示pending和operation_id，不乐观替换当前持有人 |
| 屏障进行中 | 展示fencing、旧持有人、目标持有人、在途／未决；可查进度，不显示“已停止设备” |
| effective但protected | 显示“接管已生效，等待资源核对”；旧未发受屏障约束，在途可能继续影响设备；相关写控件仍禁用 |
| effective且当前记录ready | 显示当前持有人和可操作目标；旧operation成功与当前epoch／版本不一致时，优先当前记录 |
| rejected／indeterminate | 显示原因和查询入口；不凭本地超时取消请求、抢占或回到automatic |
| 释放手动控制 | 独立明确操作，经服务确认更新；不等于恢复暂停run，不补发旧自动化 |

正常转交绑定`control__TransferOffer`的transfer_id、scope、device_id、revision、完整from_principal／target_principal、expected_control、lifetime、state和accepted_operation_id。Principal含issuer_id／issuer_epoch／principal_id，禁止只比较principal_id。邀请由当前人员持有人发起，对方在自己的可信宿主UI接受；请求offer_ttl_ms只表达申请时长，权威期限为服务返回的Lifetime。Lifetime含clock_domain_id／descriptor_digest／issued_tick_ns／expires_tick_ns，不换成浏览器UTC到期判定。接受前原持有人仍有效；接受时再次核查双方授权和版本，经屏障／持久化切换后旧待发失效。在途仍列出，转交不是取消。accepted只表示已关联accepted_operation_id，随后查ControlOperation和当前ControlRecord；不等于已effective或设备ready，也不因邀请原期限经过而回写expired。控制快照的旧裸身份字段按[C05第16.2节](rebirth-c05-event-sync-design.md#162-控制投影的唯一字段裁决)在新选择中替换，GUI不推测缺少的issuer。

紧急接管单独权限、明确目标和原因，不借管理员角色默许；保留接管入口，但存储不可靠时只能报告无法确认，不能提供“跳过保护”。批量接管按设备分别显示，不承诺多设备原子性，不把部分effective汇总成全部ready。首期整台设备接管；音频通道和矩阵点的资源模型不能提前变成细粒度接管。

## 4. UI04：编辑与实时控制、重复请求和容量

默认将表单编辑与发命令分开。文字／数值中间态（空串、负号、小数点、输入法组合）保持编辑态；只有确定提交且通过能力Schema、单位、范围、目录绑定校验后创建请求。目录失效显示原ID及原因，禁止自动选首项；目标在编辑中变化时保留草稿并显示差异，不无提示覆盖或改绑。快捷键和聚焦本身不提交，Esc只取消尚未提交的输入，不能撤销已发动作。

推子／矩阵拖动支持显式实时模式，首期仅批准的绝对赋值能力可用。一次手势绑定设备、参数、能力revision、接管版本和当前用户；实时发送经过与普通动作相同的入口。推荐每个冲突资源只有一个未决实时命令；在结果满足继续条件前只替换本地尚未提交的目标值，已受理命令不合并、不删账、不改digest。到达预算后停止提交并显示“输入尚未应用”，不使用无限队列或隐藏补发。手势结束仍未提交的目标丢弃发送资格，保留可见差值供用户再次明确应用；不在稍后收到结果时突然补发最后值。

实时能力profile必须声明可继续条件、最小提交间隔、单次／整段期限及容量；故障、unknown、权限／控制版本变化、失步、页面失去交互上下文时结束手势并清除未提交意图。窗口、SDK和服务端均有界，不能只靠浏览器节流保护。此策略可能降低高时延设备的手感；在模拟和真机证据允许前，不以并发堆积提升表面响应。相对±1、toggle、切换／播放／召回及复合操作均不套用“只保留最后值”。

一次明确点击分配一次请求身份，重复点击在同一未决提交中关联原请求。网络结果不明时保留非秘密请求关联，只查原状态或在相同有效上下文内按同键同内容查询既有结果；不得换新键重试。刷新后从服务端授权操作记录恢复查询，不从浏览器持久队列恢复写入；没有完整请求身份时不猜测补发。幂等详情已清理、身份过期和404均不证明从未执行。按钮“重新执行”只用于允许的新动作，明确新身份和现场状态，不能给unknown开放通用重试。

编辑保存使用expected revision；冲突展示基准、当前和草稿差异，由人重新提交。服务端验证失败绑定字段路径、稳定reason_code和可读消息，不只toast；429／容量拒绝显示可重试条件但不自动重发写入。命令详情和事件查询采用有界分页，逐页不是全量完成证明；遥测可降频，控制权、命令和失败记录不可按普通电平丢弃。

## 5. UI05：自动化、排期与恢复

定义保存、验证、发布、批准、布防和运行分开。编辑页展示草稿与运行版本，发布成功不自动切换活动run；参数引用来自固定能力目录。转换／并行组全必需，简单顺序仅Q72允许的明确失败且证明独立非必需步可继续；GUI不能开放后端不能证明的skip。新运行状态只在服务端提交后展示，设备部分成功不伪装成业务状态已提交，也不自动生成回滚动作。

排期按[C06](rebirth-c06-schedule-design.md)显示来源、草稿差异、固定日历／时区、场次身份、plannedAt和派发窗口；旧time展示文本不自动转绝对排期。DST缺失／重叠先明确错误或选择，不静默偏移；导入、验证、发布、激活与播出投影各有结果。激活新版后既有受理场次继续显示原版；时间质量恢复不补发失去资格的旧场次。界面展示使用“发送窗口”，不宣称设备到达或画面切出时刻。

恢复必须使用当前`lifecycle__RecoveryPreview`：显示scope／run_id／prior_execution_id、baseline的run_revision／slot_revision／artifact_ref／arm_generation及bindings／authorization／control／source／evidence摘要、policy_ref／business_state，另列plan、unresolved_command_refs、clock及期限。plan逐步显示step_id、disposition、previous_command_ref、evidence_refs和parameters_ref；disposition严格为retain_success／execute_new／reconcile_commit，不把所有条目都画成待发动作。观察和原结果从这些授权引用读取，不能从旧baseline__RecoveryPreview的snapshot／observations字段拼接。成功或未知步骤不得由GUI改成失败以便重跑；解除接管、资源核对、业务状态提交、补偿与恢复保持不同操作语义。

确认时以`lifecycle__Resume`提交context、expected_run_revision、expected_slot_revision、preview_id、preview_digest，返回`LifecycleOperation`；并发提交由服务端CAS决定，输家查询既有结果或由人重新预览，不能自动换新preview再次恢复。操作状态`reserved／preparing／ready／running／reconciling／completed／paused／indeterminate`逐一展示；targets绑定`PreparationTarget`，状态为`pending／applied／closing／closed／unknown`，并显示controller_id、device_ids、原／目标grant引用、receipt_ref和barrier_ref。ready不等于动作完成，closed不等于设备在途已停止；locally_closed与protection_complete单列，后者也不证明全部资源clear。预览过期、证据／授权／控制／run修订变化、服务换代使旧确认失效；重新认证后也须重新核对。撤销操作的revoking／revoked等其他域状态不得混入本DTO。

## 6. UI06：完整设备面板、扩展与NodeCG编辑入口

所有专用面板与通用表单共用SDK、请求关联、接管及完成展示；不另开直达设备的WebSocket。以下是功能分区，精确参数、型号、单位与完成政策由C11各专题及18bundle来源表约束，不能用一个通用按钮替代已有专用操作体验。

| 面板 | 首期必须保留及特别提示 |
| --- | --- |
| OBS | 场景／场景项、预监／节目、转场、媒体／播放列表、推流等完整旧用途；当前观察与拟设值分开，指定VLC条目真实播放接口未冻结时显示明确未就绪，不能以selected冒充播放 |
| ATEM | ME节目／预监、转场、辅助、宏及已映射设备控制；ACK、效果、宏完成各按政策展示，缓存相等不装作新查询；不因按钮Promise fulfilled报成功 |
| Mixer／DM3／WING | 五种旧配置、通道／总线、前级、静音／独奏、发送、场景及自定义参数用途；型号目录独立，184来源项不自动开放；共享前级突出受影响通道，WING两步patch预览中间态和部分效果 |
| VB Matrix | 矩阵点／增益／静音／删除、查询、预置及本地bank编辑；合并与替换分别预览，有限scope列出新增／修改／删除；本地bank不是设备64预置，−inf／Err／未知不显示为不存在 |
| 图文／排期 | 通用具名控制、原兼容编辑入口、字幕／比分／排期输出入口；保留旧编辑功能和外部NodeCG渲染，GUI不重写播出页面；排期执行和投影分开 |

数值控件使用能力声明单位及量化规则；finite centi_db、negative_infinity、mute、unknown分别显示，禁止把−inf转最小有限dB或把binary当boolean。未批准codec显示受限原因；设置密码等字段只通过secret_ref流程更新，不在通用表单、复制命令或日志中回显。

第三方面板沿C09精确origin／source／nonce、MessagePort、document_generation及PanelSession；reload重新握手，撤销关闭旧通道。宿主绘制身份、权限及高风险确认区域，面板不能用一个`confirmed=true`替用户接受接管、布防或恢复。安装批准不等于用户写权限，无专用面板时完整通用表单仍可用。

**推荐补齐NG03的具体编辑登录路径**：在`managed_bridge`组合中，将保留原控件的兼容编辑器打包成显式批准的C09面板制品，托管在独立面板origin。独立入口指向GUI的编辑器启动页；先走LeafSeamer指定签发方登录，再由宿主创建绑定用户、artifact、NodeCG实例、具名动作／Seamer草稿操作和期限的PanelSession，按C09握手挂载。读写均通过受限host代理，不加载带原生高权限socket的NodeCG运行上下文；这属于兼容接入适配，保留原编辑功能和播出资产，不能静默把任意NodeCG页面当获准面板。编辑器只获得不透明会话关联和授权投影，不拿LeafSeamer令牌、设备凭据或NodeCG key；host代理仅允许精确方法／scope，Seamer草稿编辑权限独立于图文控制权限。

原NodeCG dashboard继续保留独立外部入口及自身登录，`external_editor`明确显示“外部控制，不能保证统一仲裁”；不得继承LeafSeamer管理员会话，也不能在设备被LeafSeamer接管时宣称原编辑器不可写。managed组合的独占证明仍须C11／C12验证，改用面板登录本身不证明旧socket、其他bundle或原处理器已不能绕过。

官方NodeCG文档说明其授权只有全拒绝或完整实例权限，URL的`key`能授予完整访问。因此GUI不得复制含此key的URL并标成只读输出，也不能只去掉key就声称输出可用。（来源：[NodeCG Security & Authentication](https://www.nodecg.dev/docs/security/)，2026-10-18核查。）输出入口由C12经验证的访问profile提供无管理秘密URL；未批准时显示“输出访问未配置”，不自动降为公开实例。UI分别显示控制连接、映射值证据、输出访问配置与renderer诊断；桥ACK不标为已上屏。

## 7. UI07：语言、键盘与告警

简中／英文覆盖初始化、登录、管理、通用及官方面板、接管、恢复、错误和帮助。首次选择保存偏好；无偏好按支持语言匹配浏览器，无法匹配回退英文；默认暗色并提供浅色。协议ID、错误码、设备和用户内容保持原文；第三方缺译显式回退，不能显示空按钮。切换语言不改变单位、精度、时区、持久身份或草稿值；日文保留路线图。

推荐以WCAG 2.2 AA为官方GUI的验收目标，重点检查键盘可达／无焦点陷阱、焦点可见且不被遮挡、非颜色状态、表单错误、状态消息与拖动替代输入；此处是目标，未宣称合规。依据：[W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)。推子提供数值／步进替代，复杂设备表格允许必要的二维阅读但保留固定目标身份和键盘定位。认证允许密码管理器和粘贴，不用额外记忆题作为本项目默认验证。

常规状态更新不抢焦点；持续保护在目标附近和操作记录可见，toast消失不等于故障解除。高频电平不逐样本播报；失败、控制权变化和结果未知提供可访问状态消息。默认不向系统音频设备播放告警声，避免进入直播音频链；视觉告警必须足够识别。若后续增加声音，需显式启用和输出设备／捕获路径验收，不能靠音效传达唯一状态。

快捷键在可信宿主配置并显示目标和作用范围，输入法／文本编辑、非当前工作台、失焦时不执行设备快捷操作；长按重复不生成切台、加分等重复命令。页面前后台切换不保持旧实时手势。弹窗用于明确授权或高风险取舍，不覆盖持续电平和控制权信息；紧急接管不能被普通提示遮住，但仍不得绕服务保护。

正式浏览器覆盖沿Q68为发行时固定版本的桌面Edge／Chrome，两种语言、主题和键盘完整流程分别验收。窗口缩放和小桌面宽度不隐藏接管、unknown及目标标识；手机、平板、其他浏览器不因能打开就宣称已验证可控制。React／Vite精确版本及服务会话管理职责已由[工具链第3节](rebirth-toolchain-lock-design.md)确定，锁文件生成、组件实现和浏览器尺寸／缩放验收属于实施，不再重开框架选择。

## 8. 故障时序

1. **接管响应丢失**：服务已受理→GUI超时→保持提交待确认并查原operation→effective但资源未清时仍禁写；禁止新键抢占或释放旧控制。
2. **转交并发**：A邀请B→A仍可操作→C获紧急接管→B接受旧版本→冲突拒绝；B界面刷新当前C，不把自己的弹窗确认当控制权。
3. **实时推子与撤权**：首个绝对值已受理→本地累积未提交值→撤权／失步→丢弃本地待提交资格→首命令按服务真实发送边界处理；恢复连接不补最后值。
4. **浏览器刷新**：命令可能已发送→刷新丢失内存→重新登录并按授权记录查询→查不到时显示无法确认，不从设备值猜归属，不自动重做。
5. **未知结果后核对**：unknown落账→后读得到目标值／资源释放证据→展示核对与解除保护结果→原unknown保留；只在新预览及明确授权后执行新的必要动作。
6. **恢复双提交**：两窗口同preview→服务端只消费一次→获胜operation逐目标preparing→其他窗口关联该结果；失败不自动新建恢复；权限撤销中的target继续显示未确认。
7. **兼容编辑器换页**：受权PanelSession→iframe导航→宿主观察到load／导航后关闭旧port与委托→旧消息拒绝→新文档重新握手／鉴权。跨源导航起点不保证即时可见，按[C09 PD02](rebirth-c09-extension-design.md#92-pd02握手报文与导航窗口)记录检测前已受理请求及传播窗口；已受理在途继续，不因面板关闭释放接管。
8. **图文假成功**：桥effect_verified→输出浏览器未加载／持久值重启回退→GUI显示“映射已核实，画面未确认”或新观察变化；不据消息ACK宣称播出成功，不自动清屏或补写。

## 9. 验收规范与静态检查边界

以下UIT01—UIT40全部为待实现后的验收用例，当前执行数为零。每例记录SDK／GUI／服务版本、浏览器／平台、用户权限、操作目标、输入、预期与实际、服务记录和浏览器证据。模拟服务、浏览器、部署和设备证据分开记账，不用截图替代发送或持久化证明。

| ID | 正向或反向输入 | 必须观察的结果 |
| --- | --- | --- |
| UIT01 | 无Seamer的独立Controller | 登录和授权设备控制完整，自动化显示未配置 |
| UIT02 | 套件签发方不可达／同名替代实例 | 不回退登录来源、不跨实例复用令牌或缓存 |
| UIT03 | 登录／配对／续期请求 | Origin／CSRF／audience负例拒绝，URL及持久存储无管理秘密 |
| UIT04 | 用户退出且仍持有设备 | 新手动写和面板失效，接管保留，独立组织grant不隐式撤销 |
| UIT05 | 撤销已受理但一目标未确认 | 逐目标保留状态，不报告全部生效 |
| UIT06 | 缺快照页、重复错digest或缺对象类 | 不进入current，不以最后一页为空证明完成 |
| UIT07 | 旧revision、同revision异内容、epoch改变 | 不倒退／覆盖，异常重同步，不重放操作 |
| UIT08 | 慢GUI与健康自动化 | 仅GUI范围禁写并重同步，执行端不因该浏览器慢自动停机 |
| UIT09 | HTTP202后无设备回执 | 显示受理／等待，不显示执行完成 |
| UIT10 | succeeded但required=sent | 明示完成级别，不标effect_verified |
| UIT11 | failed且effect_status=partial | 失败与部分效果及保护同时可见 |
| UIT12 | unknown后追加核对／资源clear | 原终态不变，解除保护不自动重试 |
| UIT13 | 接管pending／fencing | 当前持有人不乐观替换，屏障进度及在途可见 |
| UIT14 | effective且protected | 接管已生效但相关写仍禁用 |
| UIT15 | 旧effective响应迟于新控制版本 | 展示当前持有人，不恢复旧权限 |
| UIT16 | 转交未接受、接受、过期、并发紧急接管 | 原持有者持续到真实切换；旧版本接受拒绝 |
| UIT17 | 批量设备部分接管成功 | 逐台effective／ready，不宣称原子成功 |
| UIT18 | 释放／退出／页面关闭 | 均不隐式恢复暂停run；关闭和退出不释放接管 |
| UIT19 | 数值中间态、输入法组合、Esc | 不提前派发；Esc不伪取消已发动作 |
| UIT20 | 目录项失效或同名ID变化 | 原选择报错，不自动选首项／改绑 |
| UIT21 | 连续绝对推子输入、服务延迟 | 每资源未决有界，已受理不合并，末尾未发不延后补写 |
| UIT22 | 推子途中撤权、换控制版本或失焦 | 结束手势，丢弃未提交资格，保留真实在途 |
| UIT23 | ±1／toggle／宏长按与重复点击 | 不套实时合并或键盘重复；明确请求身份可追踪 |
| UIT24 | 超时、刷新、幂等详情清理、404 | 查原记录或保持不确定，不换键重发 |
| UIT25 | 并发保存与429 | 保留草稿并提示冲突／容量，不自动覆盖或重试写 |
| UIT26 | 保存→发布→布防及更换运行版本 | 各步独立受权，不因发布成功自动运行 |
| UIT27 | 并行组失败及简单顺序非必需失败 | 按Q72及证明展示；GUI不能任意skip必需动作 |
| UIT28 | 排期导入、DST重叠／缺失及旧time文字 | 草稿／日历选择明确，不暗生成绝对时间 |
| UIT29 | 激活新版和NTP恢复 | 既有受理显示原版，旧失格场次不补发 |
| UIT30 | 两人恢复同preview、相同run但slot已变 | 同一预览一次消费，run／slot双CAS，UI关联原operation，不自动再预览再执行 |
| UIT31 | 预览后授权／证据／控制／运行域变化 | 旧确认失效，需重新核对；不比较跨域tick |
| UIT32 | 恢复ready／reconciling、target closing／unknown、locally_closed但protection_complete为false | 精确展示当前LifecycleOperation和PreparationTarget，不展示已恢复完成或已全部停止，不接受旧域枚举 |
| UIT33 | OBS／ATEM／Mixer／VB与通用表单 | 同SDK和受控入口，专用功能覆盖按C11逐项验收 |
| UIT34 | −inf、mute、unknown、binary及秘密参数 | 不混值／单位／存在性，秘密不回显，不开放未批准codec |
| UIT35 | WING多写、VB replace与本地bank | 中间态／删除清单／部分结果可见，不伪原子或设备预置 |
| UIT36 | 面板伪origin、旧port、扩大scope、伪confirmed | 拒绝或回到可信宿主授权，无秘密授予，无权限提升 |
| UIT37 | managed编辑入口与原NodeCG dashboard | 前者显式批准并走LS身份／host代理；后者独立外部登录，不继承仲裁保证 |
| UIT38 | 含NodeCG key的输出URL或桥ACK | 不作为只读输出交付；映射与renderer状态分开，不宣称像素成功 |
| UIT39 | 简中／英文、暗／浅色、缺译、键盘、缩放 | 全流程可用，目标／保护可识别，稳定机器字段及单位不改变 |
| UIT40 | 高频遥测、告警、前后台与文本输入快捷键 | 不抢焦点或逐样本播报，默认无音频告警，不意外生成控制动作 |

## 10. 归并与剩余冻结事项

1. **公共契约归并**：转交、命令及恢复按第11节现有精确根绑定；C05控制快照修订、DF06身份接口和C06排期已成文接口按DF01生成新选择。统一历史检索、管理枚举及维护入口的具体缺口见第11.4节，现有draft.4字段不暗补新状态。
2. **能力参数与预算**：逐动作冻结实时控制资格／继续条件／间隔与未决上限、复合操作中间态、设备目录和完成／释放政策。UI04的单未决策略是推荐上限，尚无时延／手感验收；相对与复合动作不因此删去。
3. **交付组合**：[C12 DEP01—DEP08](rebirth-c12-deployment-design.md)和[C11图文第9节](rebirth-c11-nodecg-design.md#9-首期采用与实现出口)给出静态资源／API／面板／编辑器origin与TLS、独立Controller及NodeCG采用路线；工具链栈已确定。完整产物锁、隔离实现和负向验收仍待实施，声明origin或选择iframe不等于证明隔离。
4. **验证**：UIT01—UIT40全部未运行；静态字段／引用检查不能关闭A09／A10／A15／A17—A21。第11节关闭核心操作页面的旧模型冲突；第11.4节和C11仍有明确设计缺口，阶段0未关闭。

## 11. 页面与当前公共契约绑定

### 11.1 固定依据与页面所有权

2026-10-29核对的机器输入是SDK提交`aff5ccbb75b6140109f948f81284785c75e46d1e`的[panel-wire契约目录](https://github.com/LeafSeamer/leafseamer-sdk/tree/aff5ccbb75b6140109f948f81284785c75e46d1e/contracts/panel-wire/contract)：controller.openapi.json、seamer.openapi.json、models.schema.json及registry-map.json。该输入是panel4候选，不是运行服务；下表“现有”仅指确有机器声明，“待生成”指已有采用文稿，“待定稿”指仍缺具体接口。最终产品采用DF01的新完整选择，禁止将文稿修订叠加到旧摘要下运行。

| 页面／分区 | 读取与字段来源 | 操作入口、权限及故障约束 | 状态 |
| --- | --- | --- | --- |
| 初始化、登录、站点切换 | discoverContracts、getMeta、getSession；DF06 PrincipalView的完整主体、audience和授权范围 | bootstrap／login／refreshSession；登出与身份生命周期沿DF06，bootstrap不变成公开注册。站点不可达不换签发者 | 现有入口＋DF06待生成 |
| 设备列表与详情 | listDevices、getCapabilities、getSceneCatalog、getDeviceState；devices／catalogs／observations集合 | 目录引用和Observation质量与目标值分开；同步完整后仍按对象许可检查 | 现有 |
| 手动接管、转交 | getControl、getTransfer、getControlOperation；ControlRecord、TransferOffer原件 | acquireControl／releaseControl／offerTransfer／acceptTransfer／cancelTransfer；仅human，control各具名权限，紧急接管另核权限；unknown查lookupControlRequest | 现有；控制快照按C05待生成 |
| 专用面板、通用动作表单 | 当前能力及绑定Schema、设备观察、控制版本 | submitCommand，device.command且human_manual；取消用cancelCommand，查lookupCommandAdmission／lookupCommandCancellation。submitCommand的原始身份operation为createCommand，不能用显示名改变去重键 | 现有；C11逐动作政策待定稿 |
| 命令详情 | getCommand／getCommandRevision／getCommandEvidence／getCommandEvidenceRevision／getCommandCancellation | command.read及对象证据可见性；列表摘要和完整证据分开，未决记录不因换页隐藏保护 | 现有；历史列表按C05第18节待生成 |
| 定义列表、状态表和动作编辑 | definitions集合；getDraft／getDefinitionVersion／getPublishedArtifact／getCompiledProgram／getIndependenceProof | createDefinition／updateDraft／publishDefinition，definition.edit／definition.publish；草稿CAS与发布单独操作，发布仅human | 现有 |
| 运行、布防、暂停、解除布防 | runs／business_states／executions集合；getRun／getActivationSlot／getExecution／getTriggerDecision／getRunOperation | createRun／preflightRun／armRun／pauseRun／disarmRun；各run权限独立；arm仅human，预检通过不代表已经布防 | 现有 |
| 恢复预览与进度 | previewRecovery、getRecoveryOperation、LifecycleOperation及PreparationTarget | run.read预览、run.resume人员确认；lookupAutomationRequest查原，run／slot双CAS；按11.2绑定 | 现有 |
| 数据源、导入与排期草稿 | C06 SourceConfigRevision／ImportSnapshot／ImportDiff、排期草稿／发布版本；sources投影仅运行来源，不是配置列表 | C06 SCH06的创建／配置、捕获、apply、publish／activate；来源只读不意味着任何人可配置凭据或应用差异 | SCH06及第9节读取待生成 |
| 场次及播出投影 | schedule_activations／occurrences集合；C06 occurrences详情 | C06 preflight／arm／disarm、场次cancel／replay；明确新场次和原关联，时间恢复不补发 | 快照现有，C06路由待生成 |
| 人员、服务身份及配对 | getSubject与DF06 PrincipalView、ServicePrincipal、Credential／Pairing脱敏引用 | DF06身份生命周期接口、管理权限及近期认证；真实凭据仅规定的首次交付，GUI不扮演service | DF06第9／14节待生成 |
| 组织运行授权、撤销进度 | getRun及授权关联、getRevocation逐目标结果 | revokeAuthorization；Controller的updateRunGrant是配对Seamer通道，GUI不能直接调用或借service凭据。授权管理另按DF06完整主体规则 | 撤销现有；读取按DF06第14节、批准管理按C04第18节待生成 |
| 扩展安装、批准和角色 | getExtensionSlot／getExtensionInstallation／getExtensionOperation | stageExtension／approveExtension／resolveExtensionRoles／reviewExtensionPermissions／planExtensionChange及slot生命周期；导入原包走受权本机工具，浏览器不直连import IPC | 详情及操作现有；列表按C09第21节待生成 |
| 兼容编辑器与第三方面板 | C09 Registry／动态Schema／授权投影，精确artifact和PanelSession | 宿主调用createPanelSession及握手／确认／请求／订阅接口，面板只走具名port方法；不得拿服务token | 现有＋C11采用资产待实现 |
| 图文输出入口 | C12选定OutputSnapshot、批准的无管理秘密URL、renderer诊断 | 三路只读输出与控制／编辑登录分开；缺配置显示未配置，不开放原NodeCG端口 | C11／C12待生成与实现 |
| 时间与容量 | getClock／getClockAssessment／getCapacity；DF06认证时钟状态、DF05发行时间状态分别展示 | status.read；setCapacity仅容量管理权限。浏览器时钟与业务reference均不修复认证／发行时钟 | 公共查询现有；新增时钟状态待生成 |
| 维护、备份、恢复与升级 | C12安装记录、backup分级／状态、完整generation选择；普通GUI不读秘密原件 | 必须走所属服务／Suite受权工具，不能用设备命令、扩展API或浏览器文件系统权限替代维护授权 | 具体管理接口待定稿，见11.4 |
| 语言、主题、键盘和帮助 | 本地非敏感偏好及随release的双语资源 | 不产生业务写入；服务会话管理器拥有请求和投影，React重挂载不重新提交 | 工具链与UI07已定，待实现 |

### 11.2 核心详情的精确字段与请求身份

- **命令**：getCommand／getCommandRevision响应根为`command__V__S0_CommandRead`，分别固定view=current／historical，record为`command__V__S0_CommandRecord`（command__CommandRecord的具名目标）；以下字段路径均相对record。摘要为`SnapshotRecord<snapshot__CommandSnapshotView>`。phase／outcome／effect_status／resource_status／reason_code／resolution_ref都在state内，完成级别在completion内；HTTP详情读取为record.state和record.completion，不能直接读取响应根。historical不可用来开放当前写控件。详情的evidence_refs与摘要的evidence_count不能互换；缺少证据读取权限不是“没有证据”。outer snapshot revision、source_record_ref、state_ref和command revision各守自己的类型及归属，不按数值大小跨层替换。
- **控制**：详情为`control__ControlRecord`，revision、control_epoch、effective_version和reserved_version各自显示／核验；pending_change由operation_id／target／requested_by／reason构成。OfferRequest提交context_id、idempotency_key、expected_control、reason、target_principal和offer_ttl_ms；接受另建自己的AcceptRequest，不能复用邀请人的请求身份。accepted_operation_id按同scope查询，不把offer revision当control version。新快照的holder与source_control_ref沿C05生成，旧effective_holder_id不足以判断本人身份。
- **定义**：`lifecycle__DraftRecord`绑定scope、definition_id、revision、content、content_digest、selection_digest、metadata_revision、metadata；`PublishedVersion`绑定definition_version、source_draft_revision、artifact_ref、program_digest、bindings_digest和published_by。编辑和发布分别显示固定版本，不能将草稿摘要当已发布artifact。定义列表从definitions快照取得display_name／published_ref／draft_revision／activation_state和外层对象身份，不因没有listDefinitions路由新造另一列表权威。
- **运行与布防**：`lifecycle__RunRecord`的lifecycle、business_state、arm_generation、active_execution_id、active_operation_id、pause_latches和dispatch_eligible分别展示。InspectRun提交context和expected_run_revision／expected_slot_revision；Preflight的passed、checks及期限是预检结果。Arm还须原preflight_id／preflight_digest，不以本地检查代替。run、slot任一修订改变按原操作查询／重新读取，由人再次决定，禁止静默刷新CAS后补发。
- **恢复**：第5节字段直接对应`lifecycle__RecoveryPreview`／`Resume`／`LifecycleOperation`／`PreparationTarget`，不使用同一models文件内保留的baseline__RecoveryPreview。reconciling显示“正在核对提交”；retain_success显示“保留已成功结果”，execute_new显示“执行新动作”，reconcile_commit显示“核对业务提交”。target unknown是该准备／保护目标结果未确定，不能将整条命令改成unknown或failed。所有引用遵守本域完整scope、revision、digest，GUI不能自行补全。

### 11.3 列表完整性、权限与故障状态

registry-map的12类集合逐一分配：devices／catalogs／observations用于设备与能力，commands用于当前命令，controls用于接管与转交，sources用于来源资格，definitions用于含未发布草稿的定义列表，runs／business_states／executions用于自动化，schedule_activations／occurrences用于已激活排期与场次。各集合仍沿C05权威所有者；服务会话管理器经createSubscription、getSnapshot、getSnapshotPage完成完整交接，再接有序events。集合不是随意可选的数据库表名，不追加管理对象进去假装旧Schema支持。

快照完整只表示所选授权scope与固定snapshot的完整，不表示全库历史、所有安装、全部身份或所有未激活排期都已列出。页面可同时显示完整baseline与详情加载状态；只有已授权空集合可显示“暂无记录”。缺页／丢帧保持loading或resync_required；401为重新认证，403为无权限，版本不符为incompatible，服务不可达为disconnected；详情404只说明当前查询未返回，不推断从未受理、已取消或已删除。业务错误保留稳定reason_code和原结果，不把所有409都归类为编辑冲突。

后台读取失败不清除已显示的unknown保护，也不因旧成功响应迟到覆盖更高revision。切换scope／主体、退出和权限缩小时销毁无权投影及面板通道，已发请求继续按所属服务真实账本处理。读取重试须有界并可取消，任何写入均不由effect、焦点、重新连接、刷新或语言切换触发；请求关联由领域SDK管理，不强行套用一个跨命令／控制／自动化通用幂等键。

### 11.4 剩余接口缺口与实施出口

本节关闭的是核心设备、控制、命令、定义、运行和恢复页面的字段／枚举／查询绑定冲突；不宣称C10全部完成。以下是仍需在原所属专题定稿的有限缺口，不能推给组件实现时猜测，也不另建候选体系：

1. **受权历史检索，设计已关闭**：[C05第18节](rebirth-c05-event-sync-design.md#18-受权历史与管理目录读取)固定各authority的listOperationHistory、领域locator、同writer目录版本、分页cut、当前授权及保留语义。SDK和服务据此实现，刷新后查询原身份；归档或缺失仍显示无法确认，不承诺任何历史都永远可取，不用重发补足。
2. **管理读取与运行批准，设计已关闭**：[DF06第14节](rebirth-df06-internal-trust-design.md#14-身份配对与运行授权的管理读取)和[C09第21节](rebirth-c09-extension-design.md#21-扩展目录读取)固定管理目录；[C04第18节](rebirth-c04-automation-design.md#18-组织运行批准与目标范围认可)固定proposal、逐Controller范围认可、RunApproval及其撤销。GUI先展示编译的完整设备／动作／参数限制和有限窗口，由各目标有权人员认可，再提交完整引用集合批准；部分认可不显示可布防。批准后独立preflight／arm，旧批准替换须先完成撤销和相关核对。详情分开显示Seamer批准与目标认可／真实grant，不直接updateRunGrant；失败和刷新按lookupRunApprovalRequest查原。
3. **排期未激活对象，设计已关闭**：[C06第9节](rebirth-c06-schedule-design.md#9-未激活排期来源和导入的读取契约)固定来源配置、导入历史、排期草稿列表及详情、差异和固定版本查询；现有sources／schedule_activations只承担运行投影，新路由由SDK生成。
4. **维护管理契约**：C12／DF04／DF05已经定义备份、恢复与安装切换规则，但尚未给出GUI到所属本机维护工具／服务的完整请求、脱敏状态和查原契约。须确定远程GUI可做与本机管理员必须做的动作边界及认证失效时入口；不能把操作系统管理员恢复入口偷换成在线GUI特权。人工发行时间选择仍独立等待决定。

目前剩余维护管理这一项具体页面接口缺口；上述已关闭读取设计转入实现，不再因生成器或组件未写重开。它们不重开已采用的人员手动政策、三人发行阈值、React／Vite、NodeCG接入和12类投影。SDK生成与客户端适配、GUI组件和双语资源、服务真实字段提供者属于实现；UIT01—UIT40及A17／A18为实现后验证，当前均未执行。进入实现仍以统一收敛清单阶段0为准。
