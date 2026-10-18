# DF03：授时采集 profile、源年龄与失效设计

日期：2026-10-17。本文落实已确认的 NF02、公共 draft.4／IPC 0.3，提出 P01—P07 具体推荐，尚待审阅；不把本轮推荐写成用户已接受。遵守“先完成所有系统方案设计后进行业务实现”，本轮不修改业务代码或本机授时配置。

权威关系：[NF02](rebirth-platform-freeze.md)、[draft.4 归并](rebirth-draft4-review.md)、[DF02 运行域](rebirth-df02-runtime-design.md)。本稿新增的采集记录与资格报告均为设计字段，不属于当前公共 Schema，不得给封闭对象偷偷添加属性。生产 profile、平台实验及业务采集器均未完成。

## 1. 已知事实与设计结论

**官方事实。** chrony 的 tracking System time 表示系统时钟相对 NTP 时钟的剩余校正；Last offset／RMS offset 不可互换。sources 的 `*` 为最佳源、`+` 为参与合并的源；LastRx 是最后一个合格源样本的接收年龄，Reach 只反映收到有效响应，不能证明该测量用于当前 tracking。Ref time 是 UTC 时间。selectdata 的 Auth=Y 不区分具体认证机制，authdata 才区分 NTS／SK／无认证。（来源：[chronyc 4.7](https://chrony-project.org/doc/4.7/chronyc.html)）

**官方事实。** chrony 的 `combinelimit 0` 禁用多源组合；maxclockerror 是配置假设，不能单凭其值建立实测漂移保证。服务版本、配置及平台共同影响资格，不能从最新手册推断 Ubuntu 实际安装包版本。（来源：[chrony.conf 4.7](https://chrony-project.org/doc/4.7/chrony.conf.html)）

**官方事实。** MS-W32T 公开 W32TIME_STATUS_INFO；LastSyncTicks 为 UTC 的 FILETIME 单位，TimeLastGoodSync 为同步以来时长，但规范未明确其单调时基、休眠与服务重启连续性。公开查询结构没有跨调用快照代际。产品行为附录说明 authenticated RPC 对所有方法检查改变系统时间权限，不能假设普通低权限 Controller 能查询。（来源：[状态结构](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/f60ebce0-df96-4c96-b40b-fdbd34a2c936)、[时服务元素](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/1da649d7-3edf-4a9a-98c2-907ecacd1633)、[完整 IDL](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/5793e908-22ef-4cea-962f-fca8a72c485a)、[产品行为注 33](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/bb576d39-587b-484a-86a4-e1d378cf9497)）

**基于事实的设计结论。** 固定格式解析可以先冻结；来源身份、模型更新年龄、读一致性及误差覆盖必须另给资格证据。前后查询相同、服务显示同步、数字很小均不足以授予绝对排期资格。Windows 目标支持不变，但不能把文档可调用当成 Windows 11 已验证。

## 2. P01—P07 推荐与冻结边界

| 编号 | 推荐方案 | 尚需交付 |
| --- | --- | --- |
| P01 | 两平台共用一条内部证据流水线；原始观测、无损解析、资格判定分层，失败不回退更弱来源 | 原始记录格式归并、固定平台报告 |
| P02 | Linux 首个合格 profile 限单一实际纪律源，可配置多个候选但禁用合并；多源合并另版扩展贡献源证据 | 固定 chronyd／chronyc 包和只读通道、配置有效性证明；不在本轮修改系统配置 |
| P03 | Windows 固定公开 MS-W32T IDL，独立受限只读 broker；普通 Controller 和模块不提权 | Win11 build 的最低令牌、ACL、服务实例和字段语义实验 |
| P04 | 只接受能绑定到当前模型更新的年龄上界；先证明时基与更新身份，再生成 source_update_id | 每个后端独立年龄方法报告；无法证明即 unproven |
| P05 | 前后夹读只是变化探测；资格还需固定后端的快照或保守包络证明，不能将相等视为原子快照 | 后端源码／协议依据、竞争故障实验、量化与漂移预算 |
| P06 | profile 批准、配置变更与撤销采用持久版本及 TIME 屏障；不延长已发许可，不补旧场次 | 批准记录及采集附属记录在下一版 Schema／IPC 归并；DF04 存储映射 |
| P07 | 冻结通过与拒绝判据；实测不能证明前提时不批准该组合，不降低目标来制造通过 | TP01—TP36／PF09—PF13 运行证据；未达标平台保持明确未验收 |

P02 是首个资格 profile 的限制，不是删除用户指定多个服务器或将来多源支持；已有多源系统可以保持原配置并显示诊断。LeafSeamer 不擅自改宿主授时策略。若希望首版直接支持组合源，则需先扩展 source_ref 对应的不可变贡献源集合及各源认证／年龄证据，不把其中一个 `*` 的身份冒充全部贡献者。

## 3. 内部采集契约与处理顺序

候选附属记录版本为 `time-capture/0.1.0-draft.1`，仅限可信采集组件与内部审计，不向模块或普通 GUI 开放原始地址／配置。所有摘要用 DF01 的 JCS 规则；二进制或原始文本先按实际字节 SHA-256，不先规范化文本。

| 记录 | 必需字段与约束 |
| --- | --- |
| CaptureEnvelope | capture_id、provider_id／boot_id、运行域引用、clock_generation、time_policy_revision、profile_ref、collector_artifact_digest、backend_instance_ref、start_tick_ns／end_tick_ns、wall_read_utc_ms；wall 读取必须处于括号内 |
| RawObservation | operation 枚举、ordinal、request_start_tick_ns／response_end_tick_ns、transport_endpoint_ref、payload_ref、payload_sha256、byte_count、result；二进制整数保留类型／位宽，秘密不进入可读日志 |
| SourceBinding | configured_source_set_digest、effective_config_digest、source_ref、endpoint_set_ref、认证证据引用、selection_mode、contributor_set_digest、backend_instance_ref；源名与实际 endpoint 分别记录 |
| UpdateAgeProof | method_id／revision、backend_instance_ref、source_ref、model_update_marker、marker_evidence_ref、source_update_id、age_upper_at_capture_start_ns、clock_basis_ref、continuity_evidence_ref；缺项不得输出 validated_upper_bound |
| CaptureQualification | capture_ref、profile_ref、coherence_method_ref、age_proof_ref、budget_report_ref、decision=conditional或unproven、reason_codes；缺失数值用 null，不用零代替未知 |
| ProfileQualification | parser／模型／年龄／一致性方法的版本和制品摘要、精确 OS／包／环境、配置与源假设、误差预算推导、故障结果及报告摘要；这是批准依据，报告存在不等于批准 |
| ProfileApproval | approval_id、authority_revision、精确 profile_ref、qualification_digest、适用 service／环境范围、approved或revoked、操作者和审计引用；修订不可覆盖旧内容，权限沿 C07 与 DF06 |

source_ref 是内部不透明 ID；它指向受保护的不可变来源绑定，不用 IPv4／32 位 refid 或可变 DNS 名直接充当安全身份。DNS 解析结果变化、provider 改变和实际源脱离集合必须可检测并走失效路径；配置文件文本摘要不足以证明有效运行配置。

处理顺序固定为：确认当前批准和运行身份 → 有界采集原始数据 → 严格解析 → 核对有效配置／来源／更新身份 → 证明年龄和一致性 → 精确预算 → 原子持久化证据链与当前指针 → 发布可用样本。任一步失败只发布安全诊断及失效状态，不发布半成品合格样本。原始证据存储容量耗尽时不能继续签发无证据的时间资格。

draft.4 的 unproven 仍要求 source_ref、source_update_id 等身份字段，并非任意失败记录容器。连来源或更新身份都无法建立时，只输出采集失败诊断和不可用评估，不伪造 ID 来凑 TimeBoundEvidence；已知更新身份但年龄／误差界未证明时才可形成相应 unproven 证据。源配置合法不授权伪造当前源身份。

CLI 固定绝对可执行路径及摘要，固定参数数组、环境与 locale，不调用 shell；只允许本地固定端点，禁止默认 Unix socket 失败后改走其他 endpoint。RPC 固定本机认证绑定与查询 allowlist，不接受远程目标或任意方法名。采集不阻塞最终设备发送线程。

每个 parser profile 必须声明最大输出字节、数组条数、字符串长度、单调用及总跨度超时、重试次数和并发数。这些是不同维度，不用一个 timeout 覆盖全部。实验建议一次采集最多重试一次、每后端单飞；数值仍须与 DF05 制品／容量报告一起批准，不能填为无限。

## 4. 平台字段映射

### 4.1 Linux chrony 候选 profile

文档参考版本为 4.7；实际首发版本须结合 Ubuntu 包与固定制品验证，不宣称已经冻结发行包。选择显式本地只读 endpoint 的 CSV profile，原始字段均作为十进制词法解析后转有理数，不能先经 JS Number 再转纳秒。

| 输入 | 输出或用途 | 拒绝／限制 |
| --- | --- | --- |
| tracking System time | system_offset_ns，方向统一为 system_minus_reference | 固定 4.7 client 中正 current_correction 表示 system 慢，需反号；绝对值预算不受方向影响，不能因此省略符号校准 |
| tracking Root delay／Root dispersion | root_delay_ns／root_dispersion_ns | 秒转 ns，保守取上界；负 delay 首期拒绝 |
| tracking Ref time／reference ID／stratum／leap | 模型标记候选及状态观测 | UTC 不当单调 tick；refid 不当安全身份；非 normal 不合格 |
| sources 状态、endpoint、LastRx | 来源选择及报告年龄的原始证据 | LastRx 不直接赋给当前模型年龄；Reach 不替代 applied-update 证明 |
| selectdata／authdata | 选择与认证证据 | Auth=Y 不等于 NTS；SK 不映射为 nts |
| 后端有效配置／实例证据 | SourceBinding 和连续性证明 | 不只看磁盘文件；无法证明当前实例时退为 unproven |

固定 4.7 client 的 tracking CSV 为14列，sources CSV 为10列，`mode` 与 `state` 分列；列数、顺序、枚举、精度属于精确 parser profile。原始十进制显示会舍入，profile 必须给出向外包络，不能把显示出的9位小数当成无限精度输入。后台协议数值表示误差另列，不能只加1ns就声称覆盖全部误差。（来源：[chrony 4.7 client.c 的 print_report、process_cmd_tracking 与 process_cmd_sources](https://gitlab.com/chrony/chrony/-/raw/4.7/client.c)）

chrony 原始实现仅作为协议行为依据，不复制其实现代码进入 Apache-2.0 业务库。NTS 身份与可信网络假设分别验证；SK 支持若需独立认证枚举，走后续显式协议修订。trusted_network 表示已审阅网络信任条件，不能由“配置了密钥”自动赋值。

### 4.2 Windows W32Time 候选 profile

候选 parser ID 为 `windows-w32t-r23-status-v1`，绑定公开 MS-W32T revision 23.0 与目标 Win11 build；实际 RPC 接口兼容性仍须测试。使用公开 W32TIME_STATUS_INFO，不假设存在 `_1／_2／_3` 变体。（来源：[协议版本](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/0e425c15-8ae4-4c2a-b431-84a66b92986a)、[完整 IDL](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/5793e908-22ef-4cea-962f-fca8a72c485a)）

| 输入 | 原始类型／单位 | 处理 |
| --- | --- | --- |
| qwLastSyncTicks | u64，1601 UTC 起100ns | 留作 UTC 标记；不与本地 tick 相减 |
| toSysPhaseOffset | i64，100ns | 精确乘100；方向另由固定 build 校准 |
| toRootDelay | i64，100ns | 保留有符号输入；负值拒绝，不 reinterpret 为 u64 |
| tpRootDispersion | u64，100ns | 大整数乘100，范围检查后写 ns 字符串 |
| tpTimeLastGoodSync | u64，100ns | reported age；年龄资格另证，不能标成 QPC 年龄 |
| nPollInterval／nClockPrecision | i32，2的指数秒 | 用有理数处理负指数；poll 与 precision 分开 |
| ulLcState／eLastSyncResult／eLeapIndicator／nStratum | 独立状态 | 完整已知组合才合格；低 stratum 不替代同步成功 |
| wszSource／refidSource／ulTSFlags | UTF-16／u32／flags | 来源与认证绑定分别校验；MS-SNTP 标记不映射为 NTS |

字段来源为[状态结构](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/f60ebce0-df96-4c96-b40b-fdbd34a2c936)和[时服务元素](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/1da649d7-3edf-4a9a-98c2-907ecacd1633)。ulClockRate 不能当 QPC frequency；扩展槽不能当 snapshot generation。输入长度、RPC返回码、结构大小与保留枚举均验证。

broker 只允许 QueryConfiguration、QueryStatus、QueryProviderStatus，禁止 Sync、Log、配置修改、任意 RPC 转发。只接受受信本机调用方与有界请求；设备模块无通道权限，broker 无设备控制能力。查询权限不足时显式报告，不自动启动管理员 Controller，也不回退到 w32tm 本地化文本。broker 属于可信平台组件，其权限分离与 DF02 启动层一并验收。

provider peer 的显示名和计数不证明“当前选中且用于纪律的源”；配置列表也不证明实际来源。`u64LastSuccessfulSync` 的公开 peer 描述存在时长／纪元表述歧义，首 profile 不用它建立强年龄证明。（来源：[Peer 结构](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/123072f7-8031-4e17-b1ae-f1c04348332e)、[Peer 元素](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/28e3c644-cb9d-4925-8c80-288f6339d9e0)）

## 5. 年龄、快照与预算证明

### 5.1 年龄必须属于当前模型更新

资格方法必须证明：被测更新确实被后端纪律模型采用；更新身份在同一后端实例内不重用；年龄时基及量化已知；配置／源变化或实例重启会打断连续性。source_update_id 是这些证据的引用身份，不是每次轮询生成的新 UUID。重复响应、传输重试和新的 sample_id 都不能刷新源年龄。

推荐按两类方法审批，不允许混用前提：

1. **已验证后端年龄。** 固定后端提供的 elapsed 与当前 applied-update 绑定，证明截断／舍入、回退、休眠及更新时间关系；对报告值增加有依据的量化和时基误差上界。若取值发生在采集开始之后且期间确认没有更新，可直接把更晚时刻年龄作为开始处的保守上界，不反向扣减未证明的时间。发生更新则重采，不能把新年龄塞到跨更新的旧括号里。
2. **可验证因果更新锚点。** 权威后端观测证明新 applied-update 发生于本地域区间 [a,b]，且 marker 不可重复，则在采集开始 s 的年龄上界由 s−a 加时基预算给出。只观察到 Ref time 改变、KeyID 递增、收到网络包或成功读取状态，均不单独构成这种证明。冷启动无法取得历史锚点时保持 unproven，等待可证明的新更新。

只用 `nowUtc−lastSyncUtc` 有循环信任和墙钟跳变问题，首 profile 不作为备用年龄算法。测试发现“通常递增”不是单调保证；必须同时有后端语义依据、模型假设和针对失效条件的验证。现有公开材料尚未足以批准任一平台的上述方法，相关缺口保留为 PF09—PF13 的明确输入，而非填充虚构证明。

### 5.2 一致性不由重复读自动产生

候选采集顺序为：配置／实例前 → 状态前 → 来源及认证 → 状态后 → 配置／实例后；每项都有运行域 tick 括号，整个流程内夹取 wall。不同结果、缺项、服务重启、超时一律拒绝本次采集，有界重采。

结果相同只证明“未观察到变化”，不能排除 A→B→A、未采到的时钟 step 或模型中间更新。只有下列之一有资格进入 conditional：后端具有已验证同代快照；或固定实现及受控配置提供可验证的更新串行化，并有覆盖整个采集区间的保守模型包络。将两次较大的 offset／dispersion 取 max 也不能自动覆盖中间未观测状态。

仅靠当前公开多命令 CLI／多 RPC 查询，不宣称存在原子快照。若固定后端无法提供足够依据，则该 parser 只供诊断；在设计复审中选择受支持的观测扩展或另一个后端 profile，而非运行时静默降级。实现阶段的实验证据只能验证既定模型，不能用有限样本证明任意故障下绝对正确。

### 5.3 精确换算与条件界

沿用 draft.4 的 `system-bound/1` 与[归并稿公式](rebirth-draft4-review.md#3-ntp误差证据与独立批准)，不改摘要投影。source_age_at_capture_ns 指开始处的上界；判定为 age＋完整采集跨度＋后续elapsed 严格小于 max_source_age。采集跨度允许等号，源／样本年龄拒绝等号，误差上限允许等号，排期右端 U=not_after 拒绝。

所有单位用整数或有理数。秒小数转 ns 后若非整数，非负预算向上取整；offset 用区间表达转换误差，将无法在单个有符号 ns 值中表达的剩余量加入 read_quantization_bound_ns。最终输出 B0 毫秒向上、UTC 区间下端向下／上端向上，不能先截断 elapsed。原始字段量化、backend 数值编码、wall 读取量化、采集耗时、源额外项及外推漂移逐项列预算，不重复抵扣或任意设零。

两平台的 d 必须覆盖运行域计时刻度相对 UTC 的速率差及适用的 slew／负载／电源行为；QPC 测采集耗时不能证明服务内部年龄，也不能替代运行域共享时钟。Windows root 项是否满足同一模型须独立验证，不照搬 chrony 公式结论。恶意根时钟、超出批准环境和任意硬件故障不属于条件界保证。

固定预期算例：i64 `-1` 个100ns → `-100ns`；precision `-23` → `1e9/8388608ns`，上界120ns；u64 `18446744073709551615` 个100ns → `1844674407370955161500ns`，不能经 Number。b=9ms、s=1ms、q=0.1ms、c=2ms、d=100ppm 时 B0=13ms，elapsed=1000ms 时 B=14ms。w=1000000ms 给出 [1000986,1001014]，not_after=1001014 必须拒绝。这些为参考预期，不是生产预算。

## 6. 批准、变更与故障时序

资格状态为设计内部状态：diagnostic → candidate → approved；批准被撤销后不可原地复活，需新批准修订。它们不替代公共 ClockSample.quality；bound_state=unproven 时界为空且 absolute eligibility=false。批准由受保护管理权威登记，不能由采集器或第三方模块自授。

| 触发 | 处理顺序与完成条件 |
| --- | --- |
| 受控配置／profile更换 | 持久登记变更意图并停止旧时间许可签发 → TIME_FENCE覆盖相关旧许可 → 持久屏障结果 → 才允许执行独立获准的配置操作 → 新代际、证据与批准匹配 → 按原恢复规则创建新许可 |
| 外部源／配置／认证变化、模型异常 | 发现即本地拒绝新绝对资格并传播失效；推进新时钟代际与TIME屏障；完全生效点仍以持久完整屏障定义，不声称故障发生瞬间所有旧出口已关闭 |
| profile撤销 | 持久撤销及authority_revision → 停止签发、撤销旧guard并建立TIME屏障 → 记录全出口覆盖；已发送／unknown依原命令和资源规则处理 |
| broker／采集器崩溃 | 新provider_boot_id，清除当前可用引用；历史证据只读；不能加载旧样本并刷新接收时间 |
| DB失败或原始证据无法保存 | 不发布新的合格证据；本地保护及故障传播；既有在途的已发送边界不追认取消 |
| NTP恢复／新profile批准 | 仅使新证据有资格，不能自动恢复运行、延长deadline或补执行旧场次 |

批准与采样竞争采用同一当前状态版本比较：采集开始记版本，提交时 CAS 核对 provider／clock_generation／policy／profile批准修订／配置摘要；变化就丢弃结果重采。安装guard和最终发送仍独立核对可信当前状态，不能以“采样事务曾成功”豁免后续撤销。

数据库事务只提交本服务权威事实和outbox，不与操作系统配置或远端屏障构成原子事务。变更意图持久后、配置操作前崩溃仍保持保护；配置操作已执行但确认未落库则按不确定新环境重新观测，不自动回滚 OS 配置。DF04细化表、索引及事务重入，DF06细化批准权与对象范围。

失效传播存在实际窗口，最终出口不能凭一个静态批准文件获得无限期资格。现有许可／guard期限继续约束；失效通知、采集检测与TIME屏障的延迟需单独测量并纳入可接受运行profile，不能以平均值作硬上界。即时手动控制的time_required=false保持原义，NTP不可用本身不新增手动禁用条件；运行域、接管、授权、资源或存储保护故障仍会阻止发送。

## 7. 正反例与验收矩阵

以下 TP01—TP36 是待执行验收设计，当前执行数为0；PF09—PF13继续未完成。每项保留原始输入／平台版本／期望／实际／日志摘要；故障注入仅在隔离环境和相应授权下执行。

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| TP01 | 固定chrony版本、合法14列tracking和10列sources | 严格解析，仍需后续资格证明 |
| TP02 | 列数、locale、单位、枚举或版本变化 | 拒绝，不猜字段 |
| TP03 | CLI默认端点失效 | 不自动换endpoint |
| TP04 | 小数舍入、半ns、负offset | 精确包络，不缩窄预算 |
| TP05 | 负delay、NaN、Infinity、过长输出 | 拒绝，无合格样本 |
| TP06 | 单一有效源且完整资格前提成立 | 来源／模型绑定通过 |
| TP07 | 出现参与合并的`+`源 | 首单源profile拒绝资格，诊断保留 |
| TP08 | Auth=Y但实际SK，或NTS-KE次数增长 | 不伪标nts、不刷新update年龄 |
| TP09 | 配置含允许源但实际来源不同 | 拒绝并失效 |
| TP10 | DNS结果、运行配置或backend实例变化 | 旧绑定退出可用集 |
| TP11 | LastRx很新但tracking仍使用旧更新 | 不以LastRx刷新模型年龄 |
| TP12 | 相同source更新重复查询或重传 | update身份固定，年龄继续增长 |
| TP13 | 合格elapsed方法，确认无中途更新 | 保守映射开始年龄并全额加跨度 |
| TP14 | 冷启动仅取得UTC Ref time／FILETIME | 不冒充单调源年龄 |
| TP15 | 年龄倒退、溢出、更新marker复用 | 拒绝并打断连续性 |
| TP16 | 查询过程中发生applied update | 拒绝跨代拼接，有界重采 |
| TP17 | 状态前后A→B | 拒绝本次采集 |
| TP18 | 注入A→B→A但前后值相同 | 不得仅靠夹读通过；验证coherence方法能拒绝或覆盖 |
| TP19 | 中间未观测step且两端offset较小 | 拒绝，不能只取两端max |
| TP20 | span恰等于上限／超1ns | 前者可继续，后者拒绝 |
| TP21 | 源年龄或样本年龄恰等于上限 | 拒绝，不截断小数掩盖 |
| TP22 | B等于误差上限，或U等于窗口右端 | 前者可继续，后者拒绝 |
| TP23 | W32 i64 -1及u64最大值的100ns转换 | 分别得到-100与1844674407370955161500，精确往返 |
| TP24 | W32 precision=-23、poll=6 | precision上界120ns，poll64s，不混用 |
| TP25 | W32结构大小／保留枚举／空source错误 | 拒绝，不尝试私有结构 |
| TP26 | 普通账户RPC被拒、broker允许查询 | 前者诊断；后者仍需身份及资格校验 |
| TP27 | 模块尝试broker管理方法或远程目标 | ACL／allowlist拒绝并审计 |
| TP28 | MS-SNTP flag／peer显示名被当NTS／endpoint身份 | 拒绝错误绑定 |
| TP29 | service restart、休眠、时基不连续 | 旧年龄证明失效，按DF02恢复 |
| TP30 | profile摘要正确但未批准或环境不匹配 | 拒绝绝对资格 |
| TP31 | 采集期间撤销批准，提交CAS竞争 | 旧采集提交失败，无短暂重新开放 |
| TP32 | 受控换源屏障未完成／已完成 | 未完成不得宣称生效；完成也不改写已发送／unknown |
| TP33 | 配置已改而记录未落盘时崩溃 | 保持保护并重新观测，不盲目重放／回滚 |
| TP34 | DB或原始证据容量失败 | 不发布无证据样本，保留既有未知边界 |
| TP35 | 授时恢复、旧permit／已过期排期仍在 | 不延长、不复活、不补发 |
| TP36 | NTP不可用的即时手动命令及失效传播延迟 | time_required=false不单因NTP拒绝；其余守卫必查，延迟单独取证 |

## 8. 本轮交付与剩余事项

本轮完成官方字段与权限核对、候选记录、年龄／一致性证明责任、TIME屏障和事务顺序、36项验收设计。只运行文档链接／编号／机器基线保持检查；不宣称解析器、NTP、broker或真实平台验证通过。

设计未决：P01—P07待审阅；每个平台须确定具有可证明年龄和一致性的具体后端方法。下一版归并需给候选附属记录可校验Schema、原始字节正反例及批准／撤销引用，不暗改draft.4。实现后证据：最低权限、实际包／制品、源身份、时基／年龄、快照关系、误差预算、失效传播与负载／恢复报告。无合格profile的平台不得标绝对排期验收完成。

后续全系统设计继续DF04逐表事务、DF05制品信任、DF06内部授权，然后补齐自动化／事件／排期、全部设备和NodeCG、GUI与运维。全部设计审阅完成后才进入业务实现，不能以本稿或首闭环完成代替全系统门槛。
