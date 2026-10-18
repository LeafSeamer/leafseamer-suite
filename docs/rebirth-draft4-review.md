# NF01—NF03 归并审阅：公共 draft.4／IPC 0.3

日期：2026-10-17。用户已同意 [NF01—NF03](rebirth-platform-freeze.md)，授权设计及机器契约归并，暂不修改业务代码。本文是已确认方向的具体落实与一致性审阅；不会把合成证据、文档确认或结构检查当成平台运行证明。

后续确认：用户已同意本文公共draft.4／IPC 0.3归并基线。[DF01细化](rebirth-df01-sdk-freeze.md)给出唯一SDK契约源、精确候选工具链、JCS／大整数规则和SV01—SV20。新推荐尚待确认；原始正则尾部换行与有符号-0接受差异已登记为下一版显式修订项，当前机器基线未改。

## 1. 交付与版本边界

- 新版公共协议 `1.0.0-draft.4`，内部协议 `ipc/0.3.0-draft.1`，入口为 [draft4](contracts/draft4/README.md)。Schema、Controller／Seamer OpenAPI、IPC、正反例及离线判定器成套归并。
- [draft.3](contracts/draft3/README.md) 的机器文件和夹具保持原字节。旧协议可按原解析器读取归档记录，不能降级为新版本的写路径或把旧记录原地补字段冒充新证据。
- NF01 是显式语义变更：运行代不再冒充 OS boot 身份。新增域字段进入 guard、恢复预览和 ledger 的 JCS 摘要；原 command content_digest 的请求身份投影不变。
- IPC 仍为19类消息。HELLO／ACK要求精确新版本和7项能力；新增 `supervised_runtime_domain`、`time_bound_evidence`，缺任一项不得进入可写态。兼容检查失败不尝试 IPC 0.2。
- NF03 的制品manifest仍是发布面契约，不新增对设备的业务操作或远程安装入口；精确格式、签名身份、工具链和实际制品仍列入冻结余项。

## 2. 受监督运行域的实际挂接

`ClockDomainDescriptor` 包含 `descriptor_version=clock-domain/1`、`domain_kind=supervised_runtime`、authority_service_id、runtime_generation、supervisor_instance_id、clock_backend_id／revision、tick_unit=ns、suspend_accounting=included、namespace_identity、os_boot_identity、platform_profile_id／revision、descriptor_digest、clock_domain_id。

摘要算法明确排除两个派生字段 `descriptor_digest` 和 `clock_domain_id`，对其余内容做 SHA-256(JCS)。`descriptor_digest=sha256:<hex>`；`clock_domain_id=clock_<同一hex>`，避免将包含冒号的摘要误塞入旧 Id。内容不可变；摘要只防错配，**不能证明域成员资格**。成员和平台profile批准必须来自可信本地bootstrap及受保护配置。

`OsBootIdentity` 严格二选一：`{status:unavailable}`，或 `{status:verified,source,value,evidence_ref}`。unavailable 不能附伪值；verified 的合法结构不证明观测真实。删除 ClockSample 的 host_boot_id，保留独立 provider_boot_id、worker_boot_id 和 IPC 会话身份。

| 挂接位置 | 新约束 |
| --- | --- |
| 所有19类IPC envelope、HELLO／ACK完整descriptor | 会话归属于本次可信运行域；握手不能凭自报摘要获准 |
| ExecutionGuard、DispatchPermit、send_window、IntentRef | 同一派发链的domain_id与descriptor_digest均一致；guard及durable intent仍是必要条件 |
| ClockSample、ClockAssessment、ScheduleGuard | 样本、评估tick、入窗tick、排队截止只在绑定域内比较 |
| AUTH／TIME屏障及其ACK、open_intents／coverage | envelope绑定当前会话；旧域intent仅可保留unknown，不能宣告旧写肯定未发送 |
| ControlOperation、BarrierAck | 持久接管结果保留所属域；operation与ack一致，重启不能靠旧ACK恢复有效接管 |
| Attempt、CompletionEvidence、ResourceReleaseEvidence、OBS frame／bundle | 证据所属域与尝试一致；旧域历史记录允许只读审计，不能作为当前许可 |
| RecoverySnapshot | issued／expires tick绑定Seamer监督域；新监督器拒绝旧预览，即使摘要正确 |
| RecoveryTarget | baseline_domain明确旧基线；target_domain可在pending为空，applied必须有目标域；各Controller域独立 |
| EventAgeProof | UTC路径绑定双方样本／证据／域；因果路径用验证器域中的发送／接收tick，不能跨服务相减tick |

监督器重启必换运行代；worker重启可同域但换worker／IPC／设备会话；采集器重启必换provider_boot_id并撤出旧样本。旧writer终止不证明设备没执行。休眠恢复、未知结果、手动优先和显式恢复规则沿用NF及F02/F03，未因新域字段自动放宽。

## 3. NTP误差证据与独立批准

新增三个引用模型：`ClockSampleRef(sample_id,sample_digest)`、`EvidenceRef(evidence_id,evidence_digest)`、`TimeProfileRef(profile_id,revision,profile_digest)`。profile及evidence各自摘要排除其digest字段；sample摘要包括完整样本及证据引用。

`TimeBoundProfile` 定义 backend、parser_profile_id、model_id、环境／假设／验证报告引用、配置源集合摘要、允许的源认证方式、三个年龄／跨度上限、最大误差、drift_bound_ppm及源／读取额外预算。profile revision和digest不可变；拥有文件、摘要和报告名称不等于已获批准，接收方必须独立核对批准清单及其实际证据。

`TimeBoundEvidence` 定义：

| 分组 | 字段 |
| --- | --- |
| 身份及版本 | evidence_id／digest、provider_id／boot_id、域引用、clock_generation、time_policy_revision |
| 模型与来源 | backend、parser_profile_id、model_id、profile_ref、source_ref／auth、configured_source_set_digest、source_update_id |
| 采集 | capture_start_tick_ns、capture_end_tick_ns、wall_read_utc_ms、source_age_at_capture_ns、source_age_basis |
| 原始观测引用 | raw_response_digest、source_state_digest；不向普通客户端暴露原始响应、地址或启动观测 |
| 预算 | system_offset_ns、root_delay_ns、root_dispersion_ns、source_extra_bound_ns、read_quantization_bound_ns、drift_bound_ppm |
| 判定 | bound_state=conditional或unproven、uncertainty_at_capture_ms、leap_status、stratum、reason_code |

纳秒值采用有界十进制字符串；只有offset允许负数。`conditional`要求源年龄已证明、leap正常、stratum 1—15和完整数值；`unproven`的界必须null。它不是 ClockSample 的新quality枚举；不能通过填零界伪装合格。

本版 `model_id=system-bound/1` 仅服务 `system_disciplined`。application_offset仍保留旧模式的表达能力，但没有合格模型便不能通过绝对时间判定。W32Time字段只有在受测profile证明意义、时点、单位和保守余项后才能套用本模型；本版枚举包含w32time不表示Windows采集器已经验收。

单位和边界固定如下，使用精确有理数计算，中途不先截断：

```text
c_ns = capture_end_tick_ns - capture_start_tick_ns
b_ns = abs(system_offset_ns) + root_dispersion_ns + root_delay_ns / 2
B0_ms = ceil((b_ns + source_extra_bound_ns + read_quantization_bound_ns
              + c_ns * (1 + drift_bound_ppm / 1_000_000)) / 1_000_000)
m0 = capture_end_tick_ns
w = wall_read_utc_ms
elapsed_ms = (now_tick_ns - m0) / 1_000_000
B_ms = B0_ms + ceil(drift_bound_ppm * elapsed_ms / 1_000_000)
L = floor(w + elapsed_ms - B_ms)
U = ceil(w + elapsed_ms + B_ms)
```

源年龄字段明确指**采集开始时**的已验证上界，再累加完整采集跨度及elapsed；若后端只在更晚时刻给出年龄，适配器必须保守换算或拒绝，不能少算。采集跨度允许等于max_capture_span；样本年龄及源年龄均严格小于各自上限，误差可等于max_uncertainty；排期要求L≥开始、U<结束。源年龄、样本年龄、采集跨度互不替代。drift值来自受测假设，夹具100ppm不是生产默认值。

ClockSample绑定evidence／profile，合格样本不得缺引用；ClockAssessment对外提供同样的安全引用及区间。ExecutionGuard在time_required=true时必须绑定样本摘要、evidence和profile；GUARD_INSTALL携带对应实体。即时命令这些字段必须null，避免误把NTP质量当成即时手动写的新增前提；运行域无效仍阻止写。

最终发送判断除旧授权、控制版本、完整屏障、容量和持久intent外，还核对可信当前采集器／时钟代际／时间策略／源配置、样本及证据摘要、已批准profile、来源身份和新鲜度。接收时间不能刷新source_update或延长样本，NTP恢复不能复活旧permit。

## 4. OpenAPI与隐私边界

两服务各增加4个内部只读mTLS操作，精确请求／响应类型归入同一公共Schema：

- `GET /internal/clock-domain`：当前完整运行域descriptor。
- `GET /internal/time-evidence/{evidence_id}`：不可变证据。
- `GET /internal/time-profiles/{profile_id}/{revision}`：不可变指定版本profile。
- `GET /internal/clock-samples/{sample_id}`：不可变样本。

都要求 `clock.internal.read`、配对服务身份和对象归属授权，所有成功／错误响应 `Cache-Control:no-store`；路径及权限扩展标记不代替服务实施鉴权。普通GUI继续读取ClockAssessment；公开响应引用图检查禁止到达内部descriptor、OS观测、原始证据profile或ClockSample。digest引用可供审计，但不允许模块向这些内部入口写入自己的“可信”运行身份。

跨服务获取样本必须验证服务身份、返回引用和摘要；请求不存在对象返回404，不能用当前profile代替指定revision。内部资料存放／保留策略沿用受保护审计目录与容量上限，原始响应不放公共日志。开发者适配器仍提交能力和事件，不能自授clock.internal.read。

## 5. 跨项一致性结论

| 问题 | 本版处理 | 仍需运行证据 |
| --- | --- | --- |
| OS boot ID与Windows支持目标冲突 | 用受监督域，独立可选OS观测；不伪造标识 | 可信bootstrap、Job全纳管及跨进程tick |
| 增加域却漏掉排期、恢复和持久ACK | 对实际消费者及摘要投影补齐 | 事务及重启还原不丢字段 |
| 新域关闭误被当作旧命令未发送 | unknown保留；历史域与当前许可分开判定 | 传输边界故障与迟到回执 |
| NTP数值合法但源证据不足 | 完整链、独立批准及当前代际三者同时检查 | 平台profile、源年龄及漂移实验 |
| API时钟与业务时间混用 | NTP时间模型仅用于其声明用途，F04认证时钟独立 | 认证故障、撤销优先与换源并发 |
| 跨服务tick相减 | UTC双方区间证据或验证器本地域因果证明 | 网络采集顺序、challenge身份绑定 |
| profile复用或更新不明确 | ID＋revision＋digest精确引用，内部读取带revision | 版本批准、撤销及保留容量 |
| signed/hash合格等于原生安全 | NF03继续分列签名、来源、重建、运行能力 | 平台组合、实际二进制与加载证明 |

未发现需要推翻已确认方向的实质冲突。源年龄锚点、摘要排除集合和内部profile版本寻址是本轮明确的实施细节，现以本稿和draft4为准；旧稿同名字段的旧语义不得与新协议拼接使用。

## 6. 离线用例与验收界线

实际数量、依赖版本和输入摘要见 [validation-report.json](contracts/draft4/validation-report.json)。旧draft3反例按原验证器另行复验；本版迁移旧正例并新增针对本次变化的结构／语义／配对正反例，不能把二者数量相加宣称全新覆盖。

覆盖包括：无OS观测的合法descriptor；伪值、篡改运行代、旧IPC和缺特性拒绝；可信握手与自报身份拒绝；新监督器／新worker不能继承旧许可；AUTH／TIME错误域ACK和遗漏coverage拒绝；恢复快照到期／错域拒绝；负delay、未证明源年龄、闰秒、无界填零拒绝；重新签digest并重新绑定后仍过期的源证据拒绝；当前provider／policy更换拒绝；100ms采集和1ns外推的向外取整；公开assessment区间篡窄拒绝；跨服务UTC年龄证据、错域及低估拒绝；旧域命令证据只读可核验。

结构例中的单独引用可使用合成占位；配对用例才验证具体对象关联。判定器中的bootstrap_authenticated、approved_profile_digests、active_time_state是**夹具提供的受信前提**，不实现身份验证，也不证明真实环境已经满足前提。旧判定器保留的限制性实验预算不构成生产容量／精度承诺。

## 7. 剩余冻结与交付事项

C12候选[DEP01—DEP08](rebirth-c12-deployment-design.md)新增部署／安装组合、健康状态、备份／诊断及只读输出投影的归并义务；这些字段不是当前OpenAPI已存在接口。安装事务仅原子选择完整release与data generation引用，不能替代文件耐久／旧writer退役／设备结果；输出投影不成为离散trigger来源。DPT01—DPT48未运行，公共draft.4／IPC 0.3不变。

C10候选[UI01—UI07](rebirth-c10-gui-design.md)保持真实CommandRecord、ControlRecord、TransferOffer及RecoveryOperation枚举，客户端同步状态不冒充服务终态。下一版需明确TransferOffer完整主体／到期与operation查询关联、C05同步投影、C09兼容编辑器批准／Seamer草稿代理范围及刷新后查询；不以新GUI设计暗改draft.4。实时控制预算、GUI工具链、NodeCG输出profile仍待冻结，UIT01—UIT40未运行。

C11音频审阅新增：[AD01—AD07](rebirth-c11-audio-design.md)要求下一版加入AudioLevel、AudioTargetRef、PreampRef、ParameterRef、MatrixPointObservation、AudioPreset及PresetApplyPlan，并关联既有footprint、secret、command/attempt、session和证据policy。DM3源目录不是批准能力，RCP／OSC各自绑定codec；VB TEXT帧计数不能套SERVICE请求身份，−inf不直接证明不存在；WING复合patch不因合包变原子。AUDT01—AUDT40未运行，旧机器契约保持。

C11 OBS／ATEM审阅新增：[AV01—AV06](rebirth-c11-obs-atem-design.md)明确OBS各类目标引用、ATEM拓扑／传输身份、复合计划和独立完成政策。推荐TransportResendPermit使每次协议控制重传单独过闸并计入屏障，不能复用已消费permit或冒充新的业务attempt；该模型须与F02联合设计，不暗改当前IPC。ATEM缓存不能伪造OBS四帧，VLC selected不能充当媒体身份；VAT01—VAT32未运行，原机器基线保留。

C11 NodeCG审阅新增：[NG01—NG07](rebirth-c11-nodecg-design.md)要求独立桥协议及NodeCGMapping／会话代际／收据／完成证据模型；旧NodeCG revision不得充当可靠CAS或持久游标。远端apply可能晚于本地屏障，原attempt、unknown和资源释放需按F02/F06继续核对；桥阶段不替代公共命令状态。NGT01—NGT32未运行，原编辑器委托及输出隔离待C10／C12定稿；本轮不修改draft.4／IPC 0.3。

C09审阅新增：[ME01—ME07](rebirth-c09-extension-design.md)要求下一版补ExtensionManifest／InstallationApproval／RuntimeBinding／CatalogApproval／PanelDelegation以及DeviceOperationPlan与子命令绑定。connection_state.ready、模块complete声明、普通消息回调不构成当前权限或设备完成证据；扩展撤销须覆盖关联queued／permit而非仅关iframe。原机器基线保留，MX01—MX40未运行；[旧设备映射](rebirth-legacy-device-map.md)及[其他系统映射](rebirth-legacy-system-map.md)是来源事实，不是新版能力已实现。

C06审阅新增：[SCH01—SCH07](rebirth-c06-schedule-design.md)登记ScheduleGuard缺发布／场次／逐步窗口权威绑定，以及关联检查未核对guard.definition_version与RunBinding的缺口；推荐下一版补OccurrenceBinding、StepWindow、日历／导入／激活API和来源观察契约，并区分资格锁存、执行结果与资源证据。现有机器基线不变，CT01—CT42未运行；[旧五模块映射](rebirth-legacy-schedule-map.md)仅证明源码覆盖范围，不代表功能运行通过。

C05审阅新增：[ES01—ES06](rebirth-c05-event-sync-design.md)登记旧stream_id即日志世代与DF04 stream_epoch的语义分歧、Snapshot缺runs、数字resume缺流绑定、WS缺客户端ACK及票据未绑定subscription_id。推荐下一版统一身份与双向帧、补完整快照及来源资格状态；保留draft.4原文件，不将新增候选路由视为已实现。EV01—EV36未运行。

C04审阅新增：[自动化设计AR01—AR06](rebirth-c04-automation-design.md)登记definition_digest递归排除误伤parameters业务键、proof递归误识别、4096步定义与256后继证明的容量错位。推荐下一版将程序与proof分离，固定完整输入／图／活动槽，显式扩充证明容量并受总预算限制。当前机器文件不改；DF01等价提取阶段仍保留旧语义，随后版本化修复并提供新旧差分，EX01—EX32仍未运行。

| 编号 | 待落实交付 | 阶段 |
| --- | --- | --- |
| DF01 | [D1—D6具体冻结推荐](rebirth-df01-sdk-freeze.md)：源提取切换、固定工具链、JCS／大整数与SV01—SV20；保留旧机器接受集并登记修订缺口 | 已给方案及部分参考向量；源迁移、完整锁、SDK生成与跨平台验收未执行 |
| DF02 | [可信启动与运行域恢复细化](rebirth-df02-runtime-design.md)：R01—R06推荐、创建时纳管、bootstrap字段／投影、子组终止证明与持久事务映射 | 方案待审阅，候选Schema待归并；RT01—RT35／PF01—PF08待实现后执行 |
| DF03 | [授时采集与失效细化](rebirth-df03-time-profile-design.md)：P01—P07推荐、字段映射／只读broker、源年龄和一致性证明、批准撤销与TIME屏障 | 方案待审阅；候选附属记录待归并，TP01—TP36／PF09—PF13未运行，尚无生产批准profile |
| DF04 | [SQLite表契约与恢复细化](rebirth-df04-storage-design.md)：DB01—DB06、字段／索引与T/R事务映射、大整数、GC与备份 | 22项内存SQL参考检查通过；完整DDL待归并，ST01—ST32及F02/F03/F04/F07运行验收未执行 |
| DF05 | [发布清单、信任根与维护切换](rebirth-df05-release-design.md)：AF01—AF06推荐、候选manifest Schema、合成正反例、RA01—RA28 | 格式／关联参考检查独立于发布批准；精确客户端、工具链内层与平台切换仍待冻结，PF14—PF18及真实发行验收未执行 |
| DF06 | [内部身份与来源证明细化](rebirth-df06-internal-trust-design.md)：IA01—IA06、单对象权限、采样challenge、来源命名空间、查询容量及日志投影 | 有限附属Schema与合成参考已补齐；API／inbox／投影待下一版归并，IN01—IN32及F04/F05运行验收未执行 |

PF01—PF18仍未运行。本轮没有启动业务、数据库或设备，没有Windows重启／休眠、NTP真实测量、原生编译加载或发布。下一阶段可继续冻结上述交付，真实试验和业务实施仍保持独立授权范围。
