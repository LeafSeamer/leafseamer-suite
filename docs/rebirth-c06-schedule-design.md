# C06：排期导入、日历解释与场次执行

日期：2026-10-17。状态：**SCH01—SCH07为待审阅推荐**。依据已确认Q27、Q32、Q58—Q60及F04/F05时间门控；依赖DF01／DF03／DF04和C04／C05候选的部分须共同归并。当前仍是全系统设计阶段，不修改业务代码或draft.4／IPC 0.3。

责任：Seamer保存排期、导入、日历解释、激活与场次账本；SDK定义其Schema及版本化解释器接口；Controller只接受已固定的命令与逐步时间守卫并在唯一出口复核；GUI显示差异、原本地时间／UTC、版本、布防与失败原因；Suite固定数据／工具制品和完整验收。NodeCG负责既有播出展示，不能因展示倒计时到零自行取得设备写权限。

## 1. 已知事实与缺口

事实来源：[当前Schema](contracts/draft4/first-loop.schema.json)、[Seamer OpenAPI](contracts/draft4/seamer.openapi.json)、[IPC](contracts/draft4/ipc.schema.json)、[F04/F05](rebirth-f04-f05-design.md)、[DF04](rebirth-df04-storage-design.md)及[Q58—Q60](rebirth-design.md#8-时间模型与-ntp)。五个旧排期模块的源码能力与新归属见[旧能力映射](rebirth-legacy-schedule-map.md)；源码存在不代表已做运行验收。

| 已存在的契约 | 缺口／需要保留的边界 |
| --- | --- |
| Dispatch.scheduled含occurrence_id、not_before/not_after、clock_policy_revision、max_queue_ms | 没有排期版本／每步窗口来源，不能证明这个时间窗获哪次发布批准 |
| ScheduleGuard含definition_version、时间代际、域、window_enter、queue_deadline及锁存 | 定义版本未与请求RunBinding作完整交叉校验；当前无OccurrenceRef或独立step-window模型 |
| GUARD_INSTALL带单个schedule_guard，time_required时强制时间证据 | 单次命令应绑定自己的窗口，不能把整个节目唯一窗口套给全部步骤 |
| DF04有schedule_version与schedule_occurrence表概要 | 跨版本逻辑场次键、激活／受理竞争、导入和日历产物尚未具体化 |
| 当前公共接口没有排期导入／发布／激活／场次查询／取消 | 本稿新增的路由及模型都是下一版候选，不能标成SDK已有功能 |

已确认故障边界：最终开始发送须同时满足`L >= not_before`及`U < not_after`，窗口为半开区间。故障锁存从可信条件下预先计算的“U最早可能到点”单调边界window_enter开始，不能等L安全到点才锁存；质量失效后仍推进计时。重启、域变化或映射丢失而无法证明仍在窗前时保守阻止。这个边界仅用于保护，不是发送许可。（来源：F04/F05第3.2节。）

## 2. SCH01：外部来源只产生可审阅草稿

推荐统一流程：`fetching → captured → validated → diff_ready → draft_applied`；任一步可failed/cancelled。数据抓取不激活排期，不直接创建设备命令。外部源只读，SQLite仍是本系统运行库；Google Sheets及PostgreSQL外部数据源继续保留。

| 候选对象 | 关键字段与不变量 |
| --- | --- |
| SourceConfigRevision | source_id/revision、kind、adapter_artifact_ref、只读connection_secret_ref、允许数据集／查询模板、mapping_revision、source_timezone、稳定主键规则、采集及大小预算 |
| ImportSnapshot | import_id、source_ref、capture_started/finished、source_revision或null、coherence=`transaction_snapshot|single_response|unproven`、raw_digest、mapping_digest、完整性／截断标记、记录数与受限原件引用 |
| NormalizedRow | source_record_key、logical_item_id、mode=`display_only|executable`、原始展示字段、时间输入／时区、固定能力／动作绑定、诊断；无稳定身份不得自动匹配 |
| ImportDiff | diff_id/digest、import_ref、base_draft_revision、added/changed/removed/conflicts、空源／删除确认标记；删除列表不直接变取消操作 |
| ApplyImportRequest | context_id、idempotency_key、expected_revision、diff_id/digest、明确选中的变更；服务取固定diff，不接受客户端偷换原件 |

稳定主键来自源内明确ID／数据库主键，不能使用行号、标题、排序位置或抓取时间。同一批重复key拒绝；源里修改key视为删除与新增，UI必须显示，不能推断同名即同节目。没有源key的历史资料允许人工建立映射后导入草稿；未解决的映射不能进入执行发布。标题、说明、显示颜色等变更不重置逻辑身份。

空响应、连接失败、超时、部分分页、范围遗漏或截断均不得变成“删除全部”。真实完整空源仍产生明确的全删差异，需用户在草稿中选择；发布和激活另有操作。source_revision缺失时以固定捕获内容摘要识别该次输入，但摘要不证明外部源事务一致或没有中间修改。重复同内容导入不新建逻辑项／场次，不把新抓取时间当新版本播出资格。

Google Sheets推荐一次受限batchGet读取所需范围，固定valueRenderOption/dateTimeRenderOption，不依赖默认格式化字符串；保存原响应和明确来源时区，日期序列值必须按批准映射解释。API响应提供spreadsheetId及valueRanges，不提供本项目可用的完整事务版本锁；分次读设置／范围不能仅因前后相同就宣称原子快照。输入仍作为人工审阅草稿，需更强一致性的源应提供明确发布版数据集。（来源：[Google Sheets batchGet](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchGet)。）

PostgreSQL推荐最小权限只读账户，在一个有时限的REPEATABLE READ只读事务内完成固定查询／分页；SELECT列清单、绑定参数、稳定唯一ORDER BY及总行数上限固定于配置。只读不自动证明任意函数无外部副作用，因此只允许已审阅视图／查询模板，不接受网页任意SQL、用户函数或锁表语句。READ COMMITTED的多个查询可见不同快照，不能据此拼接发布输入。（来源：[PostgreSQL事务隔离](https://www.postgresql.org/docs/current/transaction-iso.html)。）

取消导入仅停止该次抓取／草稿操作。回退导入产生新草稿及反向差异，不回拨已执行场次、删除审计或覆盖已发布版本；旧版有rollbackImport功能，重构保留其编辑恢复用途，执行效果另按现场恢复规则处理。导入凭据、原SQL连接及原件不进入普通日志或NodeCG输出。

旧版`field.changed`能力独立保留：推荐另设已发布的SourceObservationBinding，固定source/mapping版本、字段路径及标量类型、from/to条件、采样质量／年龄和事件权限，不能从导入行携带的动作或任意表达式即时建立规则。首次完整采样仅建立基线；后续合格完整样本按稳定key比较，经C05持久摄取／去重进入已批准且已布防的自动化。草稿apply、rollback或映射变更本身不产生设备触发；映射改变须重新批准及建基线。观察通道无权激活导入排期，排期发布也不自动授予观察权限。轮询只能证明采样状态差异，不能保证捕获两个采样间的全部变化；失步后重新建基线不补发历史边沿。这个候选通道的完整Schema及来源质量profile与C05/C09共同冻结。

## 3. SCH02：版本无关的逻辑场次身份

推荐区分可编辑逻辑排期项、不可变发布版本、逻辑场次和执行尝试。不得把version、标题、UTC时刻、导入批次或NTP代际放入“是否曾执行”的唯一身份。

| 类型 | 候选字段／唯一约束 |
| --- | --- |
| ScheduleItem | schedule_id、item_id（永久稳定）、mode；一次项保存one_shot_key，重复项保存series_id及有稳定slot_id的日历时段 |
| LogicalOccurrenceKey | authority_id、schedule_id、item_id；一次项加one_shot_key；重复项加series_id、slot_id、original_local_date；显式重播另有new_instance_key及replay_of |
| OccurrenceRecord | occurrence_id（服务分配）、完整逻辑键／digest、revision、固定或候选发布引用、原时间及解析结果、窗口、qualification_latch、admission_ref、execution_ref、原因／证据 |
| OccurrenceBinding | occurrence_id、logical_key_digest、schedule_id/version、activation_revision、definition_artifact_digest、calendar_profile_ref、plan_digest、admission_id |
| OccurrenceOverride | 原逻辑键、override_revision、目标时间／跳过、理由；改时间仍引用原键，不生成替代身份 |

数据库对规范逻辑键及occurrence_id分别唯一。重复规则的slot_id代表用户定义的一次日内播出位置；修改该slot时间保留ID，新增第二次播出必须明确新增slot。重复日历选择器改变后，在原来已经物化的场次上必须显示保留／删除／新建差异；不能自动重建series_id来绕过历史消费。

跨日期移动已有场次用OccurrenceOverride，original_local_date仍是原锚点，不能因目标日期变了变成新执行。改变时区／重复模式导致映射歧义时发布拒绝，先给出明确身份迁移／取消及新增清单。已accepted/completed/blocked/missed/cancelled的身份不因新时间或新版本复活；明确“重播”创建新场次并记录replay_of，显示将再次发生的设备效果，重新走布防、授权和时间门控。

部分详情清理后保留稳定消费／拒绝依据；重复生成器的过往覆盖floor和关闭命名空间不能因回拨时间或换版本降低。源记录删除后再出现仍映射同逻辑身份，不把旧历史丢失解释为从未执行。

## 4. SCH03：日历解释与固定时区数据

一次项保存原始本地日期时间、明确命名时区或固定偏移、选择的offset、UTC结果及calendar_profile_ref；纯显示文本不自动转为可执行日期。外部无时区值必须使用明确批准的source_timezone，不能用浏览器／服务系统时区补齐。人工不存在的本地时间拒绝；歧义时间必须选择明确偏移并校验它属于该时区该时刻的有效候选。

重复规则首期推荐有限ISO日历语法：daily、weekly（显式星期集合）、monthly（日期或第n个星期几）、yearly（月日），interval为正整数，固定anchor_local_date、slot_id/local_time、命名时区、例外日期与可选结束边界。月末无对应日期及闰年缺失日期默认跳过，不自动挪到月末；不同语法分支封闭，不接受任意cron字符串或宣称完整iCalendar兼容。旧能力盘点若要求额外语义，应补具名分支及用例，不能默默丢失旧功能。

重复DST策略固定在发布版本：gap=`skip`并保留跳过记录；overlap=`earlier|later`必须明确选一个，只生成一次逻辑场次。不得调用库的默认gap平移／默认fold选择后省略该决定。一天不是固定24小时，按本地日历生成日期再解时区，不以UTC加86400秒模拟每日节目。多个slot碰到同一UTC不自动合并，发布预检显示冲突，执行仍受设备资源和单实例约束。

CalendarProfile候选字段：profile_id/revision、calendar_language_version、parser_artifact_ref、tzdb_release、tzdb_artifact_sha256、zone_alias_map_digest、supported_date_range、gap/fold/month_end政策及生成器版本。命名时区数据会随发布更新；本系统固定具体数据产物，展示新旧UTC差异并显式发布，不能运行时自动下载latest。（来源：[IANA Time Zone Database](https://www.iana.org/time-zones)。）

技术推荐：以`@js-joda/core`和`@js-joda/timezone`作为可锁定日历／时区候选，使用完整时区数据制品，显式枚举local time的有效offset后按上述政策决定；不依赖宿主Intl当前隐式tzdb，也不使用SYSTEM区。官方当前主干提供IANA数据生成、版本化数据加载和完整／裁剪bundle；裁剪包超范围可能静默给错误偏移，因此必须有独立有效日期范围检查。主干package.json显示core 6.3.0、timezone 3.1.0，但这仅是源码元数据，本轮未核实注册表发布物／integrity，不能当已冻结可安装版本。（来源：[官方timezone README](https://raw.githubusercontent.com/js-joda/js-joda/main/packages/timezone/README.md)、[core元数据](https://raw.githubusercontent.com/js-joda/js-joda/main/packages/core/package.json)、[timezone元数据](https://raw.githubusercontent.com/js-joda/js-joda/main/packages/timezone/package.json)。）

同进程provider的数据加载可改变模块级状态，因此生成任务按calendar_profile隔离worker，每个worker只加载一份固定数据且禁止热替换；旧版本任务不受新tzdb载入影响。GUI使用服务返回的批准解析结果作提交依据，本机预览不成为权威。运行中已批准场次直接使用固定UTC和窗口，不能临发送再次按最新时区规则重算。（来源：[官方TzdbZoneRulesProvider源码](https://raw.githubusercontent.com/js-joda/js-joda/main/packages/timezone/src/TzdbZoneRulesProvider.js)；worker隔离是本项目推荐。）

重复生成采用有界滚动区间，保存generation_id、版本／calendar profile、covered_through日期及生成结果摘要。自动延展仅沿已批准相同规则与同一数据产物，不等于允许新规则自动发布。生成数量或复杂度超限必须拒绝或暂停扩展，不能截断列表后声称覆盖完整。启动后过往区间标历史／错过，不将未物化过的旧日期作为新事件补发。生成失败使安全前瞻区间不足时暂停相关排期，不能默认无限执行未来。

## 5. SCH04：发布、激活与受理的原子边界

草稿CAS→导入／手工差异审阅→类型／身份／时区／能力及逐步窗口预检→保存不可变ScheduleVersion与plan digest→明确ActivateRequest。发布不激活，激活不布防；Q57组织授权需绑定批准版本／计划，不能把旧授权无条件沿用到新动作。

ScheduleVersion至少绑定source/import_refs、逻辑项映射、definition artifact、calendar profile、生成政策、逐步窗口、容量profile及批准记录。ActivationRecord保存schedule_id、active_version、activation_revision、幂等身份、操作者及提交序号。激活事务与场次受理事务使用同一Seamer writer串行化：

| 顺序 | 必须生效的结果 |
| --- | --- |
| 激活先提交、场次尚未accepted | 受理读取新的active_version，复核该版本下固定场次与所有门控；旧物化缓存不能抢占 |
| 场次受理先提交、随后激活 | 已accepted场次永久固定原version及计划，包含尚未派发步骤；新版本仅影响尚未受理的未来场次 |
| 激活提交结果不确定 | 按原幂等身份／activation_revision查询，不另建“看似同一”的激活 |
| 两人按同expected_revision激活不同版 | 只一方CAS成功，另一409并展示差异，不最后写入覆盖 |

物化未来场次不等于受理：draft/planned只作候选，不提前数周冻结所有版本。首次可执行步骤进入自己的安全发送资格后，受理事务原子完成逻辑键claim、active_version CAS核对、资格锁存检查、固定OccurrenceBinding、execution／活动槽、预算、审计与outbox。没有准备步骤时不能在计划时间前先发设备；明确准备步骤可使受理发生在节目名义时刻前，但从那时起整场固定版本，GUI须展示这一影响。

删除草稿项／激活移除项不会默默取消已accepted场次。尚未受理场次的删除／取消由明确操作记录cancelled；已accepted但未发的替换须先取消并取得全部相关出口未发送／资源释放证明，再显式建立新执行身份；无法证明未发不得同时启动替代。已发送、未知或部分准备成功不自动回滚，沿F07现场核对。旧场次身份及已成功步骤仍不可重放。

时间修改只能改变未消费且仍具资格的未来候选；已发生的qualification_latch永不因改期清零。activation不以“新计划还在未来”为理由掩盖原场次已经missed/blocked。用户确需重做时走明确新场次，不偷偷创建新版本绕过这一约束。

## 6. SCH05：每步窗口、可能到点与不补发

候选StepWindow：step_window_id、step_id、role=`prepare|on_air|follow_up`、相对名义UTC的start_offset_ms、latest_start_offset_ms、固定解析后not_before/not_after、批准动作类别／最大提前量引用。要求每步not_before<not_after；角色不自动授权提前，prepare须在发布／授权中显式列出设备副作用。相对C04延迟与绝对窗口同时存在时取约束交集，不能由延迟重置绝对截止或反过来绕过相对等待。

扩充后的ScheduleGuard应绑定OccurrenceBinding摘要、step_window_id/digest、execution_id、step_id、definition_artifact_digest、schedule_version与activation/admission身份；RunBinding、CommandRequest、permit／guard／IPC及权威账本的这些字段必须一致。时间来源ClockSample/profile与排期来源import／publish是两类独立证据，不用clock_generation代替schedule_version。最终出口核对摘要对应权威许可，不能只信任字符串字段存在。

每个窗口有自己的window_enter_tick_ns、queue_deadline_tick_ns及资格状态。所有tick只在所属受监督域可比较，Controller从自己的可信样本建立本域约束，不能拿Seamer tick直接计算。Seamer整体锁存与各Controller已知门控仍有传播窗口，最终发送继续F02/F04/F05唯一出口及撤销检查，不宣称分布式同时停止。

下表是场次聚合展示状态，不是替代命令终态的单一数据库枚举。持久层分别保存admission状态、qualification_latch／reason、execution引用及其结果；未受理planned可转blocked/missed/cancelled，accepted后固定执行身份，保护失效只关闭后续资格并驱动C04停止／暂停，不把已发送命令重写成missed。已发效果unknown优先显露，资源仍按独立证据释放；晚到反馈追加核对，不抹去阻止记录。

| 场次状态候选 | 进入／退出条件 |
| --- | --- |
| planned | 已物化但未受理，绑定仍需按active version复核；显示未布防与距离窗口 |
| accepted／running | 首步骤资格满足且受理事务完成；固定版本，新命令逐步受控 |
| blocked | 可能到点后必要资格失效、无法证明始终合格，或前提／保护阻止；锁存且不自动回到planned |
| missed | 未发送所需步骤而截止已过，或启动／回拨恢复时识别为过往场次；不补发 |
| succeeded／completed_with_failures | 批准完成证据与C04规则满足；状态转换及并行仍全required，不能借排期放宽Q72 |
| failed／unknown | 已有动作失败或效果未决，保留设备真实结果；按F07人工恢复，不装作missed便清除资源 |
| cancelled | 明确取消且相应未发／在途处置可证；取消请求受理不等于已取消 |

开始发送约束不等于完成时限：截止前已发送的命令允许之后返回完成证据，但后续步骤仍按自身窗口；迟到成功不能解锁已过窗后续。准备成功而播出窗口阻止时保留实际准备效果，暂停后续，不自动撤销准备。每步evidence_timeout及资源未知处理继续独立存在。

正常质量下`U`已越开始而`L`尚未越开始，可以等待，不因不确定带正常跨界直接判missed；但故障发生在预先固定的window_enter之后必须锁存。质量恢复、接管释放、重新登录或恢复审批都不能复活同场次。window_enter映射可证明仍在未来且尚未失去资格时允许重新预检；不得通过不断刷新映射把保护边界向后推。

同一名义时刻多个场次按稳定逻辑键次序提交Seamer受理序列，不声称物理同时发出；C04活动槽busy时相关触发抑制／blocked，不排队补跑。跨设备冲突由Controller有界仲裁，等候不延长not_after。NTP校时不重置场次身份、调度计数或命令幂等键。

## 7. SCH06：候选API、持久表与展示

| 候选HTTP路径 | 权限及语义 |
| --- | --- |
| POST /api/v1/schedule-sources；PATCH /schedule-sources/{id} | schedule.source.manage；版本化只读连接／映射，凭据走秘密引用，不在列表回显 |
| POST /schedule-sources/{id}/imports；GET /schedule-imports/{id} | schedule.import；受限采集，202为操作受理；只读状态含完整性及差异引用 |
| POST /schedule-imports/{id}/apply | schedule.edit；按固定diff与草稿CAS生成新草稿，不激活 |
| POST /schedules；PATCH /schedules/{id}/draft | schedule.edit；显式版本／幂等身份，display_only不变成可执行 |
| POST /schedules/{id}/publish；POST /schedules/{id}/activate | schedule.publish／schedule.activate；固定产物后CAS切换；组织运行授权单独核对 |
| POST /schedules/{id}/preflight；POST /schedules/{id}/arm；POST /schedules/{id}/disarm | schedule.read／run.arm／run.manage；复用F04/C04资格、授权安装及保护流程 |
| GET /schedules/{id}/occurrences；GET /schedule-occurrences/{id} | schedule.read及相应对象范围；固定分页、原计划与实际派发／反馈及失效原因 |
| POST /schedule-occurrences/{id}/cancel；POST /schedule-occurrences/{id}/replay | run.manage及实际设备授权；取消操作可查询，新场次显式关联replay_of，不复活原执行 |

上表省略重复的`/api/v1`前缀。所有变更沿公共context_id/idempotency_key/expected_revision语义；查询支持C05固定快照／scope，发布的定义和原始导入文件另按精确引用读取。401/403身份范围；409修订／身份／消费冲突；412前提、时区或授权绑定失效；422时间／映射／规则非法；413数据超限；429容量；503关键存储／保护不可用。202只可靠受理，最终状态另查；取消、replay不能绕过手动接管或资源未知。

候选表补充DF04：source_config_revision、import_operation、import_snapshot、import_diff、draft_revision、schedule_version、schedule_activation、calendar_profile、generation_range、schedule_occurrence、occurrence_override、occurrence_admission、step_window_binding。各不可变对象BODY与摘要同写；source外部ID不直接当本地PK；逻辑场次键唯一、admission一次消费、execution反向唯一，旧版本与旧拒绝floor不回拨。导入抓取／时区生成在事务外，提交时复核输入；不得把外部HTTP／SQL查询包在本地writer事务内。

GUI必须同时显示来源稳定ID、草稿／发布／当前激活版、原本地时间／时区／offset、批准UTC、每步开始／最晚开始、实际发送与反馈、准备步骤已发生效果、不可执行原因及仍未决命令。浏览器语言／时区改变只影响展示；日期确认提交仍带固定calendar profile和解析结果摘要。NodeCG排期展示与编辑兼容保留，但外部编辑只进草稿，输出页不携带管理凭据或自动成为审批入口。

## 8. SCH07：验证与剩余冻结

候选容量`sim-c06-v1`：单导入10000行／8 MiB、每来源1个未完成抓取、每服务4个；查询／抓取总deadline10 s；未来物化30天且每schedule最多10000场；实验场次最多64步骤且仍受C04总图／发布预算。任一超限明确失败，不截断后标完整；这些不是实测生产参数，也不是把C04合法定义永久限制到64步。正式profile须联合冻结图规模、最大提前准备量、动作类别迟到上限、生成安全前瞻、扫描周期、最坏事件循环／writer阻塞和保留预算；无有效时间上限不能布防。

技术验证须先获取实际发布包及完整依赖锁／integrity／许可证，核对tzdb内嵌版本与数据hash，确认全bundle范围和有效offset API，再在Windows/Linux及两个基准浏览器对照同一输入。当前只核实官方主干资料，未安装日历包、连接Google或PostgreSQL、修改授时或运行排期。新包不进入业务依赖直到设计定稿和制品验证完成。

以下**CT01—CT42均未运行**，对应A11/A12/A16/A19/A21。期望是验收规范，不是结果报告。

| ID | 输入／故障 | 必须观察的结果 |
| --- | --- | --- |
| CT01 | 重复导入同key／同内容，只有抓取时间变化 | 不新增逻辑项或可执行场次 |
| CT02 | 调换行序、改标题／显示时间文本 | 身份保持；display_only不会隐式变执行时间 |
| CT03 | 重复source key、缺key、同名不同key | 拒绝或明确人工映射，不按行号／名字猜合并 |
| CT04 | 查询失败、部分页、截断、空响应 | 不全删；真实完整空源也须显式差异确认 |
| CT05 | Sheets范围与时区分次变化 | 不声称事务快照；固定捕获草稿并显示不确定性 |
| CT06 | PostgreSQL导入中并发更新 | 固定只读事务快照；不拼接多个READ COMMITTED结果 |
| CT07 | 导入取消／rollback及旧数据重新出现 | 只影响草稿；已执行身份不复活，原审计保留 |
| CT08 | 本地无时区、非法日期、数字日期格式歧义 | 发布拒绝，不能使用系统默认时区补齐 |
| CT09 | 人工DST缺失时间／重复时间 | 前者拒绝；后者必须选有效offset，不能默选 |
| CT10 | 重复规则遇gap／overlap | skip有记录／明确只生成一次，不重复播出 |
| CT11 | DST前后每日排期 | 本地时刻保持，UTC间距允许非24小时 |
| CT12 | 月31日／2月29日不存在 | 按固定政策skip，不能悄然挪到月末 |
| CT13 | 浏览器、服务器时区或语言变化 | 固定UTC／逻辑身份不变 |
| CT14 | tzdb更新使未来UTC变化 | 差异可审阅，旧批准场次不静默重算 |
| CT15 | 裁剪数据范围外／混用两个profile | 明确拒绝／隔离；不使用默认末偏移或全局热替换 |
| CT16 | 生成超行数／超过horizon／worker失败 | 不截断声称完整；覆盖不足暂停相关计划 |
| CT17 | 修改未消费未来项时间 | 保留逻辑身份，CAS新候选；不影响已accepted版 |
| CT18 | 已完成／blocked场次改标题、改时间、换版本 | 原消费／锁存保持，不再次执行 |
| CT19 | 跨日期移动已物化场次 | override保留原锚点；不可变成新场次绕防重放 |
| CT20 | 新增同日第二slot及显式replay | 新身份、明确副作用差异，重新走资格门控 |
| CT21 | 激活先提交、受理后提交 | 场次固定新active版，不用旧缓存 |
| CT22 | 受理先提交、激活后提交 | 未发及后续步骤也固定原版 |
| CT23 | 两操作者并发激活／响应丢失 | 单CAS获胜／幂等查询原结果 |
| CT24 | 只发布或激活但未布防 | 无设备写；导入自动轮询也不激活 |
| CT25 | 删除项但旧场次已accepted | 不默默取消旧执行，提示明确操作 |
| CT26 | 替换旧未发场次但无法证实未发送 | 不同时启动替代，保留未决 |
| CT27 | U到开始、L未到且质量持续合格 | 正常等待，未早发、不仅因误差带判missed |
| CT28 | window_enter已过后质量失效又恢复 | 同场次锁存阻止，即便未到not_after也不补发 |
| CT29 | 质量失效后本地timer继续跨window_enter | 按原映射锁存，不能停计时掩盖到点 |
| CT30 | 恢复发生窗前但域／映射不可证明 | 保守阻止；不能按猜测重新预检 |
| CT31 | L等于not_before、U等于not_after | 前者满足下界，后者拒发；仍核对其他条件 |
| CT32 | 排队、重试、相对延迟延后到截止外 | 原截止不延长，不借新请求键续期 |
| CT33 | prepare提前成功，播出时接管或暂停 | 后续阻止，准备效果保留；不自动补偿 |
| CT34 | 截止前已发、截止后效果核实成功 | 可记录原命令成功，但不解锁已过窗后续 |
| CT35 | Guard与RunBinding定义／step／场次版本错配但各自摘要合法 | 关联拒绝，不能只校验时间与digest格式 |
| CT36 | 跨宿主tick数值碰巧相同或不同域 | 禁止直接比较，使用各自可信本域守卫 |
| CT37 | NTP回拨／前跳、重启后旧场次未物化 | 不重复、不补历史；保存missed／拒绝依据 |
| CT38 | 同时刻多场次争单活动槽或设备资源 | 稳定受理次序、有界仲裁；busy不积压补跑 |
| CT39 | 设备成功后提交失败／outbox重发 | F07核对原执行；不再发设备动作，只重传固定通知 |
| CT40 | NodeCG外部编辑／展示倒计时到零 | 编辑进草稿，展示不授权设备控制；兼容输出另验收 |
| CT41 | 已批准字段观察、首次采样、映射改变、重同步或草稿rollback | 首样／新映射建基线不触发；仅后续合格变化走C05；导入操作不激活规则或补历史边沿 |
| CT42 | 已accepted场次后续错过，但先前命令unknown或晚到成功 | 资格锁存、执行结果、核对与资源证据分开保存；不能覆盖unknown或解除原锁存 |

冻结退出条件：SCH推荐完成审阅；旧排期能力逐项映射；日历及数据源制品验证清楚；完整Schema/OpenAPI/IPC和新旧投影差分一致；激活与受理事务、逐步窗口及失败状态能由上述用例覆盖。实施后才执行实际并发、存储、浏览器和设备验收；设计文档不等于完成项目。

## 9. 未激活排期、来源和导入的读取契约

2026-10-29采用，补齐SCH06写入流程对应的列表及详情；只由Seamer提供，列表共用[C05第18节](rebirth-c05-event-sync-design.md#18-受权历史与管理目录读取)的DirectoryPage、固定cut及当前授权。下表路径均含`/api/v1`前缀，所有路由尚待生成，不在旧panel4操作计数内。

| GET路径／operationId | 权限、首请求额外过滤键 | 响应字段或详情 |
| --- | --- | --- |
| `/schedule-sources`／listScheduleSources | schedule.source.manage；kind、state | SourceConfigSummary：source_ref、kind、state、adapter_artifact_ref、mapping_revision、source_timezone、credential_configured、last_import_ref或null |
| `/schedule-sources/{id}`／getScheduleSource | schedule.source.manage；无 | SourceConfigView：前述summary及允许数据集／查询模板引用、稳定主键规则、采集policy_ref；仅凭据已配置状态，不返回secret_ref、连接串、原SQL或秘密值 |
| `/schedule-imports`／listScheduleImports | schedule.import及来源／目标草稿范围；source_id、schedule_id、state | ImportSummary：operation_ref、source_ref、schedule_id、base_draft_revision、state、snapshot_ref或null、diff_ref或null、applied_draft_ref或null、reason_code或null |
| `/schedule-imports/{id}`／getScheduleImport | schedule.import及对应对象范围；沿SCH06现有详情路径，不重复创建 | ImportSummary及captured／validated／diff_ready／draft_applied阶段已有的ImportSnapshot、ImportDiff引用，抓取进度只反映实际持久阶段 |
| `/schedule-imports/{id}/snapshot`／getScheduleImportSnapshot | schedule.import及来源／目标范围；无 | 完整ImportSnapshot脱敏视图，原件仅给受限引用，不通过此入口返回连接信息或原始外部响应 |
| `/schedule-imports/{id}/diff`／getScheduleImportDiff | schedule.edit及目标草稿范围；无 | ImportDiff的固定diff_id／digest／import_ref／base_draft_revision、added／changed／removed／conflicts及确认标记；超预算整项拒绝，不截断删除清单 |
| `/schedules`／listSchedules | schedule.read；state、source_id | ScheduleSummary：schedule_ref、display_name、draft_ref或null、published_version_ref或null、activation_ref或null、source_refs；包括只有草稿且从未发布的对象 |
| `/schedules/{id}/draft`／getScheduleDraft | schedule.read及草稿可见范围；无 | ScheduleDraftView：scope、schedule_id、revision、content_digest、metadata、rows、source_refs、calendar_profile_ref或null、validation_diagnostics；rows使用SCH01 NormalizedRow，不返回秘密配置 |
| `/schedules/{id}/versions/{version}`／getScheduleVersion | schedule.read及该版本范围；无 | SCH04不可变ScheduleVersion原件的公开字段、calendar profile和内容引用；固定原version，不替换为当前激活版 |

state过滤固定闭合集：来源为enabled／disabled（配置资格，不等于运行来源live）；导入沿SCH01为fetching／captured／validated／diff_ready／draft_applied／failed／cancelled；排期为draft_only／published／active／retired的目录分类，不新增场次终态。ScheduleSummary分类按已提交的发布／激活／退役记录计算，不能因active被时间保护就改成retired。SourceConfigSummary不得以最近导入成功推导运行观察来源已批准；credential_configured只说明秘密引用可配置，不保证当前凭据有效。

source_refs、草稿和导入summary的引用均带同Seamer scope、精确版本及原模型摘要；来源配置、导入和草稿事务按SCH06同时更新目录。ImportDiff绑定精确base_draft_revision；读取后草稿改变，apply仍由原CAS拒绝，不自动重算或偷换diff。独立导入未绑定schedule时schedule_id及base_draft_revision可为null，但apply前必须明确目标并生成针对该draft的diff；不得据文件名猜目标。

导入详情仅在该阶段存在对应原件时提供引用；未产生返回明确阶段及null，已归档按C05保留语义，不能将failed/cancelled转成空成功结果。差异和草稿正文继续受原C06行数限制；本组snapshot／diff／draft／version详情的完整公开JSON上限为16 MiB，在生成该原件时即验证，超过则明确失败，不创建只能靠截断才能读取的原件。原始捕获8 MiB上限仍独立适用。超过普通1 MiB目录页上限的完整详情不塞进列表，也不提高全局列表预算。修改凭据继续通过原受保护配置写入口，读取接口不交付旧秘密供前端再提交。

源列表与sources运行快照、排期列表与schedule_activations快照是不同投影；未发布、停用、导入失败或已退役但留档的对象都能按权限检索，不从活跃集合猜全目录。历史变更通过listOperationHistory定位原SCH06操作；取消和rollback仍只影响既定捕获／草稿语义，读列表不创建设备动作。新增验收覆盖从未激活草稿、空完整来源、并发apply、导入失败、秘密字段缺席、目录分页及归档后无法恢复详情；均待产品实现后执行。

## 10. 业务参考时间与排期字段采用

2026-10-29。按[DF03第20节](rebirth-df03-time-profile-design.md#20-事件年龄与排期时间的同版采用)关闭本稿跨服务年龄及时间字段的同版映射：采用现有ScheduleGuard、ExecutionTime、EvidenceBundle及UtcGuard；第6节的ClockSample泛称不再指baseline旧ClockSample，而指reference-bound/1的精确锚点／评估链。Seamer的发生项、定义、激活、受理、步骤窗口和其摘要保持来源权威，Controller仅在自己的当前运行域建立queue_deadline及发送Guard；二者分别关联，不跨机相减tick。

calendar_profile_ref决定民用时间解释；SourceQualification／LeapSchedule／Reference Profile决定运行参考UTC的可用性，不能互相替代。每步UTC窗口与当前发送UtcGuard完全一致，接收事件的年龄合格不延长原窗口，也不改排期版本。固定window_enter后的失信按SCH05锁存，原场次不因新锚点、认证恢复或重新登录复活；已发送命令保留自己的终态和未知资源。

field.changed沿C05 SourceTimeEvidence与接收方AgeEvidence：本地可信核心可使用local_capture，跨Controller使用合格UTC或批准因果采样；每个观察绑定固定允许的capture_semantics、basis及max_age。首次完整捕获只建基线，后续完整捕获的差异不声明捕获了间隔内全部物理边沿。ImportSnapshot、外部行的日期、导入完成时间以及草稿apply时间都不能替代运行观察年龄。导入／激活仍不自动建立观察授权。

新SDK生成、排期writer和实际时间提供者接线进入实现；SCH及TP57—TP62验证域错配、窗口等号、pending过期、不补发与同库写集。当前没有真实调度或平台运行证据，本节不修改排期范围、日历解释选择或设备完成政策。
