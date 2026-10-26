# DF03：授时采集 profile、源年龄与失效设计

日期：2026-10-18；决策更新：2026-10-20。用户已明确选择第9节的应用参考时钟 `reference-bound/1`，作为两平台绝对排期及对外 API 的时间基准。这项选择修订 NF02 的模型路线，不修改系统时间；GUI 展示参考 UTC、来源及误差区间。前八节的 `system-bound/1` 记录保留为历史方案与诊断依据，其中 P02／P03 不再是绝对排期的主路径。精确协议库、制品、profile、字段归并及平台运行验收仍待完成；模型路线获准不代表这些候选已批准。遵守“先完成所有系统方案设计后进行业务实现”，本轮不修改业务代码或本机授时配置。

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

当前决策：2026-10-20已确认采用第9节应用参考时钟，NF02模型选择不再是阻塞项。下一版按此路线归并候选附属记录的可校验Schema、原始字节正反例及批准／撤销引用，不暗改draft.4；旧P项中的后端年龄／快照研究不作为新路线的实现前置。仍需冻结精确库与制品、NTS引导、时代／闰秒、上游误差包络及共享计时profile。实现后证据包括最低权限、源身份、时基／年龄、误差预算、失效传播与负载／恢复报告。无合格profile的平台不得标绝对排期验收完成。

后续全系统设计继续DF04逐表事务、DF05制品信任、DF06内部授权，然后补齐自动化／事件／排期、全部设备和NodeCG、GUI与运维。全部设计审阅完成后才进入业务实现，不能以本稿或首闭环完成代替全系统门槛。

## 9. P04／P05复审：具体后端路径与应用参考时钟候选

本节于2026-10-18提出，**模型路线于2026-10-20获用户明确批准**。字段及精确profile仍属待冻结候选。前八节保留system-bound/1设计及历史证明责任；本节不把另一种模型装进该名称，也不宣称已经解决Windows或Linux运行资格。

### 9.1 已核对的后端事实

- chrony 4.7的`last_ref_update`在内部记录单调更新时刻，但tracking导出的是`last_update_interval`。`our_ref_time`会随slew调整；更新函数先赋`last_ref_update`，随后才调用频率／offset调整。因此，不能把Ref time当不可变更新ID，也不能仅导出一个内部变量就宣称完整模型已原子应用。（来源：[固定4.7 reference.c，handle_slew、参考更新及REF_GetTrackingReport](https://gitlab.com/chrony/chrony/-/raw/4.7/reference.c)。）
- W32Time确有`TimeLastGoodSync`同步以来时长；缺少的是本方案要求的时基、连续性和模型绑定证明，不是“没有年龄字段”。已核对的QueryStatus结构及操作说明未提供更新generation或全字段原子快照承诺；本轮没有证明其他接口绝不存在相应能力。（来源：[状态元素](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/1da649d7-3edf-4a9a-98c2-907ecacd1633)、[QueryStatus操作](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/7e80a465-f5f4-4c3c-87ef-12f76e45f8d1)。）
- W32Time输入provider可重复交付缓存样本，TimeJumped不是每次连续调频通知；Operational日志有周期及节流规则。它们可以辅助审计，不能据此建立无遗漏的逐次applied-update账本。（来源：[TimeProvCommand](https://learn.microsoft.com/en-us/windows/win32/api/timeprov/nf-timeprov-timeprovcommand)、[Windows Time for Traceability](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/windows-time-for-traceability)。）

### 9.2 已确认的模型选择与历史备选

以下是基于上述事实的工程分析，不是后端现有保证。

| 路径 | 具体代价与边界 | 推荐 |
| --- | --- | --- |
| 保持system-bound/1，仅使用原查询 | 接口可做诊断；当前证据不能关闭年龄与一致性缺口，不能承诺两平台绝对排期已具备实现依据 | 不作为冻结结论 |
| 保持system-bound/1，增加后端权威观测扩展 | 必须在真正应用更新及所有失效路径内生成同代记录；Linux需单独评估可维护扩展与发行边界，Windows需可支持的后端接口或替代纪律服务，不能靠RPC包装器补造generation | 保留备选，不默认引入fork或替换系统服务 |
| 新增应用参考模型`reference-bound/1` | 独立低权限组件直接采集指定NTP端点，将UTC区间绑定本地受监督单调时钟；OS时间仅诊断。新增协议客户端和平台计时制品负担，但不依赖OS纪律内部应用代际 | **已选为两平台绝对排期及对外API主路径**；2026-10-20确认NF02模型变更 |

推荐路径保留指定NTP、Windows／Linux及对外API统一时间需求；改变的是“用什么时钟证明API时间”，不是删除时间保护。API显示的参考UTC可能与宿主日志时间不同，GUI必须标明参考来源与不确定区间，宿主时间另列。应用不修改系统时钟，也不承诺同步OBS／ATEM等设备内部时钟。即时手动控制继续沿TP36；不能用手动绕过原本要求绝对时间的动作。

若选择后端扩展，其最小原子记录必须含：`backend_instance_ref`、不可复用`model_generation`、`config_generation`、来源／认证绑定、应用完成时刻括号、同代模型参数、时基及量化、失效状态。观测必须覆盖调频、step、来源变化、重启、休眠及记录丢失；记录只在实际更新完成后发布，不能在更新前分配序号就声称完成。读接口只返回不可变已完成记录，读取失败不得回退CLI。此处定义所需接口性质，**不表示chrony或W32Time已经提供该接口**。

### 9.3 推荐路径的字段、采集顺序与条件区间

以下为候选内部对象，不写入现版封闭Schema；数值沿DF01整数串和精确有理数规则。摘要只能证明对象字节绑定，不证明来源诚实。

| 对象 | 具体内容 |
| --- | --- |
| ReferenceProfile | 精确原生组件／协议库制品、OS与共享单调时钟实现、速率误差界、读取量化、请求及源年龄／不确定度上限、NTP时代解析范围、闰秒政策、认证与来源假设、有限采集预算及批准引用 |
| ExchangeEvidence | exchange_id、运行域／provider启动身份、source_binding_ref、policy_revision、profile_ref、请求关联证据、请求／响应原字节摘要、send_before_tick_ns=`m1`、receive_after_tick_ns=`m4`、原始T2／T3及时代解释、root／precision／leap／stratum、认证结论、时间戳误差包络依据 |
| ReferenceAnchor | anchor_id、exchange_ref、同域`m4`、`utc_lower_at_anchor_ns`／`utc_upper_at_anchor_ns`、reference_model_revision、批准引用、失效代际、派生输入摘要；它是本应用采样锚点，**不是OS的source_update_id** |
| ReferenceAssessment | anchor_ref、当前同域tick、外推后的UTC区间、交换年龄／样本年龄上界、资格／拒绝原因、当前policy和批准版本；不引用宿主wall推导区间 |

采集流程：批准与配置快照 → 分配一次性请求关联 → 在同一原生组件内读m1后提交网络请求 → 接收完整响应后读m4 → 验关联／认证／报文／时代／状态及预算 → 算区间 → writer按运行域、配置、policy及批准revision进行CAS持久化 → 才发布锚点。使用用户态发送前／接收后的括号，排队与调度时间计入，不声称取得网卡硬件时间戳。模块不能提交自造锚点。共享计时来源、频率换算与重启／休眠语义仍由DF02及平台profile证明。

NTP的T2、T3分别描述服务端接收和发出时间；KoD报文不能用于时间计算。NTS提供认证及请求关联，但不会把服务器时钟变成无条件正确的UTC。（来源：[RFC5905 §7.3、§7.4、§8](https://www.rfc-editor.org/rfc/rfc5905.html)、[RFC8915 §5](https://www.rfc-editor.org/rfc/rfc8915.html)。）

**本项目的条件推导，非RFC原算法保证。** 假设请求与响应确实属于同一交换、服务端T2/T3各自真实UTC位于`[T2−E2,T2+E2]`／`[T3−E3,T3+E3]`，网络因果延迟非负，m1到m4的真实UTC经过量不超过`Dplus`，则m4处：

```text
L4 = T3 − E3
U4 = T2 + E2 + Dplus
```

因服务端发出早于本地接收，得到下界；服务端接收晚于本地发出，得到上界。不假设上下行对称，不把往返时长的一半当已证明误差。`Dplus`由共享单调差、该profile的速率上界和两次读量化向外计算；不得直接等于未经校准的tick差。若`L4>U4`，拒绝，不交换端点“修正”。服务端step、错误时代、闰秒附近或误差前提不成立时不能使用此推导。

对之后同域tick m，profile给出真实经过量`[e_minus,e_plus]`，外推为`[L4+e_minus,U4+e_plus]`。需要中心／半径的展示值只能从该区间保守导出，不能为了UI平滑缩窄边界。交换年龄从**m1**保守增长，避免延迟包在m4被当成刚产生；同一包重发／重复读取不能换anchor_id刷新年龄。上游参考新鲜度和E2/E3来源另行证明，不能把“本地刚收到”当上游刚同步，也不能仅信任root字段就批准profile。

首候选一次只采用一个已批准源；其他配置源可独立探测，切换须新代际及TIME屏障，不做未经证明的多源平均或取交集。认证模式仅为已验证NTS或显式批准的trusted_network；认证失败不降级。NTS TLS证书时间校验存在启动时间依赖，必须另有受信粗时间区间或经审阅的引导机制；不能拿同一未认证响应为自身证书背书，也不能跳过证书时间检查。NTP时代范围、参考新鲜度、闰秒与smear政策必须在profile中显式固定，未知或冲突拒绝。

### 9.4 状态、失败时序与跨项迁移

采集器内部状态为`cold → collecting → qualified`；不合格采集进入`unavailable`，按既有失效政策关闭新时间资格；重新采集成功不自动解除自动化暂停。配置／来源变化、批准撤销及域变化必须先作废旧锚点，经过原TIME屏障与恢复流程才能产生新许可。锚点持久化用于审计，不能跨provider重启直接恢复当前资格。

| 时序 | 必须成立的边界 |
| --- | --- |
| 正常 | m1发出 → m4接收 → 校验和CAS提交 → 发布anchor → 发送前以当前tick外推并检查完整窗口 |
| 撤销竞争 | 收包后、提交前撤销policy → CAS失败 → 不发布anchor，不因包认证成功重新开放 |
| 崩溃竞争 | 提交后、广播前崩溃 → 新provider启动 → 旧记录仅审计，新采集并按既有恢复规则处理；不重放旧排期 |
| 延迟／重复 | 响应迟到或同关联重复 → 超时／已消费拒绝 → 不创建“年轻”锚点 |
| 时钟或源异常 | 休眠／回退／频率假设失效／换源 → 作废代际、停止签发、TIME屏障；不宣称外部故障瞬间旧设备出口全部关闭 |
| 队列与存储满 | 采集队列满则拒新请求；证据提交失败不发布。保护消息独立预留，采集绝不占用设备发送关键线程 |

`reference-bound/1`已获选择，下一版必须新增判别分支及独立摘要投影，修改TimeBoundEvidence／ClockSample／Assessment及内部查询、TimeGuard／IPC特性协商、DF04记录、C06排期和GUI来源展示；不得填造system_offset或applied-update字段来兼容。使用方仅接受自己支持且获批准的模型；同一个guard不能混合两模型证据，不能在运行中静默fallback。所有依赖UTC的内部证据年龄也需同版审阅。认证／TUF冷启动信任不能直接套用运行时参考资格，依赖循环须在DF05/C12单独关闭。

用于有限实验的候选预算：每源最多1个在途交换、最多4个候选源、请求总截止2s、UDP报文上限1232字节、不复用请求关联重传、每源最小探测间隔16s；KoD要求更长时从其约束，停止码停止探测。NTS-KE最多1个在途、5s截止、总读取64KiB、最多8个cookie且每个不超过1024字节；超限明确拒绝，不截断后接受。这些限制可能排除部分合法部署，需与协议库及服务器组合审阅；不是生产默认或已测容量。E、漂移、TTL和排期误差目标不能用本表凭空给定。

### 9.5 新增验收设计与冻结门槛

| 编号 | 输入／故障 | 人工预期 |
| --- | --- | --- |
| TP37 | Ref time因slew变化、tracking只给update interval | 不生成applied-update身份或年龄证明 |
| TP38 | W32年龄非零、RPC成功、前后相同 | 仍不能单凭这些条件取得原子模型资格 |
| TP39 | T2=1000ms，T3=1002ms，E2=E3=1ms，Dplus=20ms | m4区间[1001,1021]ms，包含不对称延迟可能性 |
| TP40 | TP39后经过量[99,101]ms | 区间[1100,1122]ms；not_after=1122拒绝，1123可继续其他守卫 |
| TP41 | T2=1000ms，T3=1025ms，E2=E3=1ms，Dplus=20ms | [1024,1021]为空，拒绝 |
| TP42 | 单调差20ms、速率包络100ppm、读预算1μs | Dplus=20.003ms；TP39上界成为1021.003ms，不能截为1021ms |
| TP43 | 上界1021.000001ms写入整数毫秒；下界−0.000001ms | 分别向外到1022ms和−1ms |
| TP44 | NTS认证通过但root误差／时代／上游新鲜度无依据 | 不批准UTC界；认证不代替时钟准确度 |
| TP45 | 服务端未认证响应用于绕过NTS证书日期 | 拒绝循环信任，不偷偷关闭证书验证 |
| TP46 | 同包重复、旧关联迟到、两源切换后旧包到达 | 不刷新年龄、不跨源复用许可 |
| TP47 | 宿主wall变化但共享时钟连续；另组为共享时基变化 | 前者仅诊断变化，后者作废reference锚点；分别验证 |
| TP48 | 撤销／崩溃／满队列分别插在发布前 | 无未经持久批准的新锚点；旧在途照原屏障规则 |

TP39—TP43只是独立算术参考，可离线核算；TP37/38为现有接口资格反例，其余需未来采集器及平台故障测试。本轮不执行真实NTP、修改系统时间或注入宿主故障。

冻结顺序：9.2模型选择已完成；接着冻结原生协议库及双平台制品、NTS启动信任、时代／闰秒／上游E包络与计时profile，完成候选Schema和正反例归并。system-bound仅保留历史／诊断用途，不作运行时回退路线。指定NTP、两平台与完整功能目标不变；完成模型选择不提前开启业务实现。

## 10. 已选路线的可校验字段候选

2026-10-20新增[reference-time/0.1.0-draft.1](contracts/df03-reference/README.md)，将第9节落实为独立Schema和离线参考模型。Source/Profile/Approval/Policy及运行域形成完整Binding；Request、认证／时代／误差原件、Exchange、Anchor、Assessment、Failure、AuthorityState、Invalidation和UtcGuard均有封闭字段及独立摘要投影。此为已选模型的字段细化，尚未替换公共draft.4／IPC0.3，也未批准精确profile。

本候选明确原始NTP秒／小数／时代的有理数换算、相对观测delta的速率包络、m1起算交换年龄、m4起算样本年龄、上游年龄保守推进、发布时重新判定和发送前重新外推。申请／证据／锚点／当前指针同writer提交；同请求重复只读历史，失效推进代次并关闭新资格，TIME屏障完成与本机失效分开。新合格样本不恢复自动化、旧场次或旧许可。

已执行的检查范围及输入摘要见[独立参考报告](contracts/df03-reference/reference-report.json)。合成上下文不证明真实parser、NTS、上游误差或平台计时，内存字典顺序不证明SQLite／IPC／掉电。剩余实施前设计为：上述字段到公共ClockSample/TimeBoundEvidence/Assessment和内部查询OpenAPI、TimeGuard/IPC特性、C06 ScheduleGuard的同版映射；完整物理写集；精确协议库和制品、冷启动信任与双平台profile资格方法。已有字段不再重复立项为“尚无格式”。

## 11. 时间查询与完整设备IPC归并候选

2026-10-21新增[时间服务候选](contracts/df03-service/README.md)：两个公共展示接口与四个内部精确历史查询，公共及内部OpenAPI引用闭包分开；公共只展示参考UTC区间、中点、误差和来源标签，不授执行权。不可用时清空UTC，历史读取不刷新证据年龄；精确对象权限先于查原，内部固定id/revision/digest。

完整46帧IPC0.8由0.7版本化投影。普通和协作取消Guard统一绑定reference_context与ExecutionTime，TIME_FENCE改为应用参考时钟Invalidation，开闸带不可降低的时间代次下界，ACK回显精确摘要。ScheduleGuard独立绑定场次、定义、激活、受理、步骤窗口和本地执行时钟；需要UTC不自动意味着具有排期。即时操作不依赖UTC，但仍受运行域和单调期限等全部既有保护。

第10节中的公共展示、内部查询及执行IPC/ScheduleGuard格式缺口由本候选推进。跨服务EventAgeProof、其他公共事件时间字段、全SDK统一迁移、时间物理写集及采集器专属通道、精确库和profile仍未完成。新增参考检查只验证结构、合成关联及有限floor快照；真实HTTP/IPC/NTP、权限、并发/磁盘和设备均未验。模型选择不等于上述候选或运行资格已经获准。

## 12. 采集器专属通道与一次采样候选

2026-10-21新增[采集器协议](contracts/df03-collector/README.md)，给出独立14帧、监督准入到核心RuntimeBinding的映射、固定配置与PollIntent、完整Capture/Blob引用、持久提交回执查原及STOP。采集器仅提交候选，不生成或批准Anchor/State；核心对原件和当前资格独立验证并负责原子发布。

单次poll先消费后网络I/O，崩溃、cache_missing或not_found均不许可重发旧poll。STOP与发包共用串行出口，捕获reserved/consumed全集，ACK保留已消费未知；原始字节必须在发布前转入核心持久库，不能仅保存采集器暂存路径。当前身份核对、源单飞、容量、最小间隔和原截止分别成立；正常采样失败不刷新旧锚点年龄，连接/运行域/信任失效关闭资格。

第11节“采集器专属通道”现已有字段与时序候选，剩余物理写集及Blob生命周期、核心提供者和跨实例容量、加载制品、跨服务年龄及SDK归并、精确库与双平台profile继续按收敛清单处理。参考检查没有运行真实网络、监督器、IPC、SQLite或设备，也未批准生产容量。

## 13. 时间原件与发布失效的同库写集

2026-10-21新增[时间存储候选](contracts/df03-collector/STORAGE.md)：十四表覆盖完整Binding/Poll、固定Capture裁决、受保护原件、独立验证回执、Anchor、只增State/当前指针、Invalidation及事务/audit/outbox/seal。原始报文由核心取证后加密，密文BLOB与发布同库提交；暂存句柄不作为持久副本。该加密存储是待审阅推荐，精确秘密存储profile与提供者尚未批准。

发布、拒绝、普通失败和失效使用不同写集；封存核验必需原件与精确关联，延迟双向外键阻止半边提交。普通失败不动当前锚点；失效推进时间代次、清Anchor并持久TIME通知，不表示设备屏障已完成。提交未知先关闭资格、查原而不重发；旧记录只作历史。首期禁止在线删除原件/墓碑，批准容量前预留保护空间，容量不足关闭普通采样，不通过静默GC恢复服务。

独立215项检查验证内存SQL约束、每步故障回滚、缺写拒绝及串行竞争顺序；高位U20仅表达式探针，BODY与加密回执为合成占位。完整业务库组合、TIME保护/STOP账本、跨实例容量、引用感知GC、真实身份/加密/磁盘和设备验收仍分开落实；本轮不修改业务代码或宣布系统方案全部完成。

## 14. 采集器停止与报告保留的一致性修订

2026-10-21的[采集器0.2候选](contracts/df03-collector/CHANNEL_V02.md)针对旧模型复现两个问题：报告尚未到核心而本地已reported时STOP集合不一致；reported在持久回执前不计容量。修订使用同一可靠有序出口的cut_sequence和配置内poll_ordinal，STOP在唯一串行队列关闭未来网络发送，并回显精确前缀及配置代次，独立于双方采样状态观察。

reported继续占用采样槽与原件，收到精确持久回执后才释放本机详情；最高ordinal和最后m1持续保留，旧采样不能换新帧复活。核心提交后释放活动额度时，持久回执必须先于新POLL进入同一出口；存储额度和活动额度分开。STOP ACK不清未知采样或证明设备屏障完成；断连/缺口/失去可信身份只能关闸并退役。跨域未知m1从可信退役回执接收后的新域起点保守等待，不直接比较两域tick。

完整14帧0.2 Schema与92项离线参考检查已给出，旧0.1不改。该检查只复现旧缺口并验证新结构和有限串行模型/容量快照，不证明网络IPC、SQLite、退役或设备运行。发送日志、STOP和容量物理表、完整SDK及严格解码、计时/加密提供者仍待归并；本修订为待审阅候选，原件/发布与业务安全范围不缩减。

## 15. 采集发送、停止及容量的同库组合

2026-10-21新增[采集日志候选](contracts/df03-collector/JOURNAL.md)，以十一表扩展十四表时间源形成25表组合。poll与预约双向提交；Capture裁决、原件、固定回执入队和活动额度释放同事务；失效封存覆盖旧Binding全部未退役channel。唯一出口先持久attempt、再写流、再记录written，不能越过未完成前缀，重启不重放旧队列。

STOP_ACK不释放未知采样；监督退役后可以核销活动槽，但保留未知墓碑和累计存储预约。迟到旧报告仅能记不合格历史；新域间隔回执仍需证明实际等待。已纠正旧存储稿对“核心取证副本”和“采集器暂存”的混用：核心提交后释放自己的副本，采集器等精确回执。

269项内存SQL检查通过，含缺写/主动故障全库回滚、同源与全局容量、回执先于下一POLL、完整停止捕获、固定ACK及未知恢复。BODY和退役来源为合成前提，不证明网络、磁盘或提供者。第14节“尚无STOP/发送/容量物理表”已有具体候选；完整库、入站去重、TIME设备屏障、容量/密码学profile与SDK归并仍未完成，不修改业务代码。

## 16. 入站持久去重与协议方向对齐

2026-10-23新增[27表入站组合](contracts/df03-collector/INBOX.md)，显式修正25表SQL的QUERY_POLL/核心出站QUERY_COMMIT错误枚举，改为0.2实际的QUERY_CAPTURE/COMMIT_STATUS；旧文件保留。两张新表与领域效果双向提交，首次Capture、STOP_ACK和查询应答不能只提交入站记录或只提交结果。固定reply_to绑定同channel已尝试请求；原帧重复查原，新序号相同对象只引用已提交历史。

162项检查覆盖全部14帧方向及回复必要性、27表缺写与主动故障回滚、身份冲突、重复效果和容量边界。首次STOP_ACK有独立保留槽，但不能越过缺号；无法完整处理前缀时关闭并退役。入站持久所有者及恢复规则现已成文，实际reader/严格解码/字段提供者与writer联接属于后续实现验收；完整业务库、TIME保护及容量/密码学profile、跨服务时间和SDK仍须设计归并，未开始业务实现。

## 17. TIME切点与共享签发水位

2026-10-23新增[TIME持久归并候选](contracts/df03-time-fence/README.md)。现有91表只从普通ce_permit取高水位，不能覆盖IPC0.8的独立取消许可；27表失效与设备cut亦尚无完整外键。本候选要求普通/取消共用一个连续签发序列，失效、全出口及普通业务锚/普通传输/取消传输、拒绝下界和保护outbox同事务。其他依赖签发水位的屏障也须同版切换，不能只补TIME形成两套权威。

内部投影Schema与92项合成快照检查落实完整目标选择、256/257边界、精确代次、尝试后继、迟到强事实与最新采用分离、floor不回退；没有执行合并SQL或真实I/O。原件来源、完整IPC到投影提供者、失效写集缺写/崩溃验证及共享分配器反向外键仍待物理组合，未把参考模型通过当作全库或平台冻结。

## 18. OPEN时间下界的持久来源与运行身份

已知事实：现行IPC的GateSnapshot包含完整时间Domain和State引用；时间Domain的runtime_binding_ref属于时间提供者，设备出口有自己的worker运行身份。现有时间SQL验收使用合成占位BODY，不能直接当作完整来源。对应字段及物理表见[时间服务契约](contracts/df03-service/README.md)和[时间存储](contracts/df03-collector/STORAGE.md)。

推荐候选：按[时间下界来源](contracts/df03-service/GATE_SNAPSHOT_SOURCE.md)从已封存State及Binding、Anchor或Invalidation原件确定性重建快照；snapshot_revision直接取State修订，minimum_time_generation直接取Binding代次，ID由具名版本、完整Domain和State Ref的JCS摘要生成。由此无需另建可变floor权威或额外快照表。旧State查原保持同一身份，但不恢复OPEN资格。

OPEN保留完整提供者Domain，仅与出口比较共同authority/database/clock_domain_id/descriptor_digest，并分别核两份真实当前运行原件。不得把worker Ref填入时间原件，也不得因两者runtime_binding_ref不同而拒绝合法共享时钟。collecting/unavailable依旧提供拒绝下界，绝不提供UTC许可；qualified也不能省略每动作的误差、年龄及窗口判定。时间失效先提交则旧快照OPEN失败，接收端已保存更高floor时不能降低。

首期时间State继续由Controller自己的writer维护，OPEN最终裁决同库重读；独立读事务、远程读取或普通查询结果不构成最终资格。新增离线读取器和正反例覆盖完整元数据与物理列、现行IPC投影、失效/历史顺序及不同成员共享时钟。完整采集/批准/加密来源、真实监督解析、与Controller恢复布局的同库组合及OPEN/ACK/Ready仍未接通；详细验收矩阵及输入绑定报告见上述链接。本候选待审阅，不改变已批准基线或业务代码。
