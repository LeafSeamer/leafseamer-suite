# 平台冻结方案：Windows 运行身份、NTP 误差界与原生制品

- 日期：2026-10-17；当前授权：设计定稿与验证计划，不修改业务代码。
- 已确认：用户同意 [TS01—TS05](rebirth-technology-selection.md)及本文NF01—NF03。库组合方向获准不等于产物版本、性能或平台验收通过。
- 后续归并已完成：[公共 draft.4／IPC 0.3 审阅](rebirth-draft4-review.md)落实受监督运行域、条件误差证据与实际对象／端点绑定。draft.3机器文件保留；本文“下一版候选／推荐”表述保留当轮设计上下文，当前字段和摘要投影以draft4为准，PF01—PF18仍未运行。

## 1. 推荐结论与边界

| 编号 | 推荐冻结的设计 | 仍需证明的内容 |
| --- | --- | --- |
| NF01 | 使用受监督运行域 `supervised_runtime` 作为共享 tick 的授权边界；OS 启动身份作为独立可选观测，不伪造 Windows boot UUID | 本地启动通道、进程组完整性、跨进程计时、挂起恢复竞态；机器契约已归并draft4 |
| NF02 | NTP 给出带来源、模型和适用条件的保守 UTC 区间；chrony 与 W32Time 分别使用受测采集 profile | Windows 状态字段的实际含义／新鲜度、可信源假设、漂移与采集误差、平台参考源实验 |
| NF03 | 以精确 Node＋原生二进制＋OS／libc＋配置组合冻结发布；安装不隐式编译或下载替代物 | 两平台及容器独立运行、引擎回读、签名／摘要、重建和升级回退证据 |

这三个方向不改变手动优先、unknown 不重放、关键记录失败禁止新写、旧许可不复活和错过排期不补发。冻结设计后仍需获得实施授权；完成本文不自动开始技术试验或业务开发。

## 2. NF01：Windows 宿主启动身份与共享运行域

### 2.1 官方事实

Microsoft 将 NtQuerySystemInformation 及其结构描述为可能变化的内部接口；公开说明没有为 SystemBootEnvironmentInformation／BootIdentifier 给出本项目所需的稳定保证。BCD 的 `{current}` 标识启动配置条目；HKLM 的易失键随完整关机卸载，快速启动不能等同处理。上述候选不能仅凭“能读到一个 GUID”认定为受支持的启动身份。（来源：[NtQuerySystemInformation](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntquerysysteminformation)、[BCD 标识](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/boot-options-identifiers)、[RegCreateKeyExW](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regcreatekeyexw)）

Windows interrupt time 不受墙钟校准影响，普通版本计入睡眠；Job Object 支持在最后一个 handle 关闭时终止组内进程，但外部创建路径不保证纳入。VM Generation ID 依赖虚拟化平台，读取与通知也不等于设备发送的原子屏障。（来源：[Interrupt Time](https://learn.microsoft.com/en-us/windows/win32/sysinfo/interrupt-time)、[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[VM Generation ID](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/virtual-machine-generation-identifier)）

### 2.2 推荐实现

不再让“必须获得 Windows OS boot UUID”成为建立安全共享刻度的唯一途径。推荐每个 Controller／Seamer 监督实例建立独立运行代：服务及所属 worker 在同一受监督生命周期内使用同一种本机计时后端。监督实例每次启动生成 CSPRNG 运行代，不从磁盘恢复；即使 OS 没重启也换代。它明确叫 runtime_generation，**绝不写入旧 host_boot_id 字段**。

监督职责位于已有服务启动层，不新增一个对用户独立部署的产品服务。两个独立 Controller 即使同机，也不默认共享时钟域；跨服务继续使用 F05 时间／年龄证明，不直接相减 tick。Linux 可额外记录内核 boot_id 与 time namespace；Windows 没有合格 OS 证据时明确 unavailable，不影响已验证运行域本身的建立。（Linux 观测来源：[内核 boot_id](https://docs.kernel.org/admin-guide/sysctl/kernel.html#random)、[time namespace](https://kernel.googlesource.com/pub/scm/docs/man-pages/man-pages/+/master/man/man7/time_namespaces.7)）

下一版候选 `ClockDomainDescriptor` 的具体边界：

| 字段 | 类型／约束 | 用途 |
| --- | --- | --- |
| descriptor_version | 固定版本字符串 | 精确协商，未知版本拒绝 |
| domain_kind | 常量 supervised_runtime | 不冒充 OS boot 域 |
| authority_service_id | 本地可信配置中的服务实例 ID | 标明谁有权创建／分发此域 |
| runtime_generation | 不可复用随机 ID | 监督器重启、无法证明连续性时更换 |
| supervisor_instance_id | 本次监督进程实例 ID | 不使用可复用 PID 代替 |
| clock_backend_id／revision | 枚举后端＋固定适配版本 | Windows interrupt_precise；Linux boottime |
| tick_unit／suspend_accounting | ns／included | 单位与语义，非纳秒准确度承诺 |
| namespace_identity | 受验证本地身份；Windows为适用范围标识 | Linux 不同 time namespace 不能同域 |
| os_boot_identity | tagged union：unavailable，或 verified＋source＋value＋evidence_ref | 只放已核验 OS 观测；不允许 unavailable 携带伪值 |
| platform_profile_id／revision | 已批准平台 profile | 绑定支持的 OS、计时、恢复和隔离条件 |
| descriptor_digest | SHA-256(JCS(除descriptor_digest和clock_domain_id以外的字段)) | 防混用，不代替本地身份认证；派生字段不递归入摘要 |

`clock_domain_id` 由该不可变 descriptor 的摘要确定。原始 boot 信息限制在内部诊断，公开日志使用非敏感域标识。描述符只能来自可信监督 bootstrap，不能接受模块自行提交一个摘要便获得域成员资格。provider_boot_id、worker_boot_id、ipc_session_id 继续分别绑定采集器、工作进程与通信会话，不与 runtime_generation 合并。

Windows 采用挂起创建 worker → 加入限制 Job → 验证关联及启动产物 → 传递受鉴权 bootstrap → 恢复执行。Job 不允许 breakaway，Job handle 不向子进程泄漏；bootstrap handle 可显式继承但不能成为 Job 保活句柄。创建失败、身份不符或无法纳入监督时，worker 不开放设备写。所有实际写设备的辅助进程必须同样受监督；WMI、外部 daemon 等逃逸路径不属于此模块许可。

监督器终止后，先以进程实例／句柄和组内清单证明旧 writer、辅助进程结束并完成连接处置，再创建可写的新实例；SCM 显示停止、PID 消失、管道断开都不单独构成完整证明。Job 终止不能撤回已进入传输层的数据；旧命令仍按 F02/F03 保留 unknown／资源占用，不能因“旧进程已死”就重发动作。

### 2.3 代际与故障时序

| 情形 | 必须发生的转换 | 禁止行为 |
| --- | --- | --- |
| 同 OS 内监督器重启 | 新 runtime_generation、新本地会话；旧 guard／sample／permit 拒绝 | 读取旧 DB nonce 恢复开放闸 |
| 仅 worker 重启 | 可保留监督域，必须新 worker_boot_id／IPC 会话及设备重连证明 | 旧 worker 许可继承给新 worker |
| 仅采集器重启 | 新 provider_boot_id；旧样本撤出可用集，重新核验质量 | 只刷新接收时间延长旧样本 |
| 完整重启／关机后快速启动 | 新服务运行代；按启动保护流程重新建立 | 依赖易失注册表键一定消失 |
| 挂起／恢复 | 保护性关闸、绝对样本失效、恢复检查及显式新许可 | 恢复后自动打开原闸或补执行过期场次 |
| 计时失败／回退／域证明丢失 | 关闸，终止当前域或保持不可写直到新域建立 | 回退 Date.now 或猜测正确值 |

故障序列例：旧 worker 已收到 DISPATCH → 监督器崩溃 → 新监督器生成新运行代且保持 closed → 证明旧进程组终止 → 查询持久 intent／设备状态 → 旧在途仍不确定则占用／暂停 → 只有满足既定恢复条件的新操作才能创建新许可。新运行代不自动清理业务故障。

挂起通知是保护信号，不是原子发送屏障。实现应结合 Windows 电源通知、可验证的计时连续性／睡眠差值观测及最后发送检查；Linux 同样验证 suspend。通知被延迟时不能依赖 JS 回调先于模块写入执行。若实际证明不了恢复首个发送的保护，活动直播 profile 禁止进入该电源模式，并把该模式标为未验收，不声称软件可消除任意 OS 暂停与写调用之间的竞态。（通知接口来源：[PowerRegisterSuspendResumeNotification](https://learn.microsoft.com/en-us/windows/win32/api/powerbase/nf-powerbase-powerregistersuspendresumenotification)）

VM 热快照恢复、运行内存回滚与克隆的**可写恢复**暂不列入通过范围：内存中的 nonce、时钟及 DB 都可能一起回退，本地机制无法证明外部设备未发生副作用。VM Generation ID 可作辅助探测；支持可写热恢复仍需另审虚拟化 fencing／外部隔离。普通 VM 冷启动可进入独立平台验收，不能把“虚拟机”整体误列为禁止部署。

### 2.4 与 draft.3 的实质差异

这是 F02 原“clock_domain_id 必须绑定宿主启动身份”的显式修订建议，不是纯字段重命名。下一版必须：引入 descriptor；ClockSample 用 descriptor 引用替代必需 host_boot_id；HELLO／ACK 协商 supervised_runtime 特性；GUARD_INSTALL、许可、屏障、摘要、恢复及事件年龄证明核对同一域。任何依赖 tick 可比较性的消费者都要审计，不能只修改 HELLO。

旧 draft.3／IPC 0.2 保持原语义。新服务拒绝不具备新域证明的写链，不能把旧 host_boot_id 当成新运行代或静默兼容。旧日志可以只读解释，不能升级成新许可。候选模型待本轮确认后归并下一版，本轮不调整机器契约版本号或产物。

## 3. NF02：NTP 误差界、质量证据与采集

### 3.1 官方事实

chrony 给出的系统时钟误差估计为 `|system_time_offset| + root_dispersion + root_delay/2`，明确依赖上游 stratum-1 时间正确；skew 是估计频率误差，maxclockerror 是配置的最大假定频率误差，不能直接视为已测硬件保证。（来源：[chronyc tracking](https://chrony-project.org/doc/4.7/chronyc.html)、[chrony.conf](https://chrony-project.org/doc/4.7/chrony.conf.html)）

Microsoft MS-W32T 公开了查询状态 RPC 与根延迟、根离散度、相位差等字段。其中 qwLastSyncTicks 是 UTC 时间戳，不能因名字含 Ticks 就与本地单调 tick 相减。微软的高精度目标也要求受控上游、拓扑和负载；服务运行不等于达标。（来源：[状态结构](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/f60ebce0-df96-4c96-b40b-fdbd34a2c936)、[时间服务字段](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/1da649d7-3edf-4a9a-98c2-907ecacd1633)、[查询 RPC](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-w32t/7e80a465-f5f4-4c3c-87ef-12f76e45f8d1)、[精度支持条件](https://learn.microsoft.com/en-us/troubleshoot/windows-server/active-directory/support-boundary-high-accuracy-time)）

NTP 同步距离及离散度具有协议模型前提；NTS 保护认证，但仍需处理非对称延迟等威胁。认证来源、统计误差估计和本项目执行阈值是三件事。（来源：[RFC 5905](https://www.rfc-editor.org/rfc/rfc5905)、[RFC 8915](https://www.rfc-editor.org/rfc/rfc8915)）

### 3.2 证据包与采集器边界

推荐内部 `TimeBoundEvidence` 记录如下字段；它是候选设计，不能以额外属性直接塞入 draft.3：

| 字段组 | 必须保存的内容 |
| --- | --- |
| 身份与版本 | evidence_id、provider_boot_id、clock_domain_id／descriptor_digest、backend及解析profile版本、time_policy_revision |
| 来源 | configured_source_set_digest、实际 source_ref／endpoint绑定、source_auth及证据引用、可信根／网络假设 profile |
| 采集 | capture_start_tick_ns／end_tick_ns、源状态版本／更新标识、原始响应摘要、wall读数及读取括号、单位与取整规则 |
| 质量 | leap／同步状态、stratum、root_delay、root_dispersion、系统剩余校正、源样本年龄上界及依据 |
| 误差预算 | backend_bound、source_extra_bound、capture_bound、read_quantization_bound、drift_bound_ppm、各项来源和未重复计数说明 |
| 判定 | model_id／revision、assumption_profile_ref、supported_environment_ref、valid_until约束、拒绝原因、验证报告引用 |

Linux 推荐固定版本 `chronyc -c -n` 的只读 tracking／sources 等 profile；源配置、选择及认证证明另取受限观测。不要把能修改 chronyd 的管理 socket 授给模块。Windows 推荐以公开 MS-W32T 协议的只读状态／配置查询构建隔离采集适配，固定 IDL／服务版本及单位映射；不链接未声明为稳定 API 的私有 DLL 导出。是否在目标 Win11 build 可用、最低权限及响应格式必须实测；w32tm 文本只作为受测解析 profile 或诊断来源，不能在结构化查询失败时静默换一个更弱证据源。

RPC／CLI／DNS 查询均在独立有界采集执行环境完成，不在最终写出口里阻塞。只查询本机指定授时服务，不开放远程管理面；超时、输出过长、未知字段／格式、服务重启、权限不足或状态不一致都产生不可用证据。若必须提高采集权限，权限限于可信采集组件和所需只读操作，不能把 Controller／第三方模块整体提权。

一次采集前后夹取单调时间并核对来源、策略和服务实例连续性；多个状态读取之间发生更新或选源变化则重采，重采次数有界。同一源样本反复查询不能变成新授时：原始 source 更新时间／序号需固定，样本年龄必须随单调经过时间增长。无法将后端年龄映射成可信上界时保持 unproven；首次启动不能把“现在收到一个状态响应”当作刚同步。

profile分别冻结max_capture_span_ms（单次采集跨度）、max_source_age_ms（距最后合格源更新的年龄）、max_sample_age_ms（LeafSeamer样本用于外推的年龄）、最大误差和drift_bound_ppm。这三个年龄不能混用；后端poll周期必须与源年龄预算匹配。原F05实验样本10s／误差50ms／漂移100ppm不自动成为这些生产值；Windows的UTC同步时间若不能在已验证认证／墙钟区间下换算上界，只能用于诊断，不能据此通过源年龄门控。

### 3.3 保守预算与整数规则

所有推导是**在指定源可信、网络／主机模型成立条件下**的工程界，不是对恶意根时钟或任意 OS／硬件故障的绝对保证。仅有历史最大偏差、P99、stratum 或 NTS 标签不足以建立这个界。

先把所有后端值无损解析为整数／有理数，负数只允许出现在有符号 offset；首期负 root delay、非有限值、溢出、来源不一致拒绝，不以 clamp 到零掩盖异常。单位 Windows 100ns、chrony 秒及协议毫秒分别转换，向外取整。

在采集结束单调时刻 m0，保守采用采集期间一次本地 UTC 读数 w 作为中心，**不声称它正好在 m0 读取**。设采集总时长 c 毫秒，读数／量化上界 q，已批准的额外源误差 s，后端系统误差 b，采集及外推速率误差上界 d ppm，则：

```text
b_chrony = abs(system_time_offset) + root_dispersion + root_delay / 2
B0 = ceil(b + s + q + c * (1 + d / 1_000_000))
sample_tick_ns = m0
estimated_utc_ms = w
uncertainty_ms = B0
```

采集跨度全额进入误差，不能偷用 RTT/2 作为单程或本地执行延迟保证。已被 root dispersion 包含的误差不再抵扣；s 表示明确额外、尚未计入且有依据的部分，缺依据不是填零。跨度过大或 b 变化无法界定直接拒绝。Windows 的候选 b 计算同样包含绝对系统相位差、根离散度和半根延迟，但**只有固定 Windows profile 证实字段时点、含义、增长和遗漏项后才允许用于 eligibility**；本轮不声称 chrony 的官方公式自动适用于 Windows。

后续保持 F05 的区间规则：对精确 elapsed=(now_ns−m0)/1,000,000，B(now)=B0+ceil(d×elapsed/1,000,000)，L=floor(w+elapsed−B(now))，U=ceil(w+elapsed+B(now))。age严格小于max_age，误差不超过阈值，且 L≥not_before、U<not_after 才允许相关绝对动作；右边界等号拒绝。不要先向下截断 elapsed 再通过年龄边界。

d 必须覆盖**选中单调刻度相对真实 UTC 的外推误差**，包含平台振荡／频率调整／slew 等适用项及模型余量；不能直接抄 chrony Skew、默认 maxclockerror 或实验 100ppm。Linux BOOTTIME 的频率行为与 Windows interrupt time 不同，分别标定。任意 step 不靠扩大 d 吸收；墙钟跳、源／策略变化、休眠或不连续性触发失效／代际保护。认证时间的独立策略不因业务 offset 健康而豁免。

新采样可以更新观测，但不能延长已安装的命令 deadline、复活过期 sample／permit 或补发场次。worker 在最终出口用已验证样本重新计算；`quality=synchronized` 仍需全部条件，缺界时沿现有 Schema 用空误差／区间与 eligible_for_absolute=false，不新增 unproven quality 枚举。

### 3.4 合成正反例

以下仅验证算术与拒绝规则，不代表发布参数或真实机器精度：b=9ms（2＋3＋8/2）、s=1ms、q=0.1ms、c=2ms、d=100ppm，故 B0=ceil(12.1002)=13ms。令 w=1,000,000ms，经过1000ms后 B=14ms，区间为 [1,000,986，1,001,014]。

| 输入变化 | 期望 |
| --- | --- |
| 窗口 [1,000,980，1,001,020)，其余资格全部满足 | 区间包含检查通过；仍需认证／资源／容量等门控 |
| 窗口右界为1,001,014 | 拒绝，U等于排他右界 |
| age恰好等于max_age | 拒绝，不因误差仍小而放行 |
| Windows b的字段时点尚未证明，其他数值同上 | 拒绝，算得出数值不等于有证据 |
| source_auth=nts但可信根条件无依据 | 不自动 eligible；按策略拒绝或仅展示 |
| 重复读取同一次授时状态并改sample_id | 源年龄继续增长，不获得新的授时新鲜度 |

Windows 误差 profile 未通过前，该平台绝对排期不能标记验收完成；即时控制按已有独立门控处理。Windows 首期支持目标保留，验收阻断不能通过文档自动取消。application_offset 仍需独立成熟实现选型，不以本轮公式授权自研 NTP 客户端。

## 4. NF03：原生制品冻结与安装

### 4.1 官方事实

better-sqlite3 从 v13.0.0 迁移到 Node-API；13.0.3 构建配置声明 NAPI_VERSION=10，SQLite 配置文档列 3.53.4 和 WAL 默认同步级别1。argon2 v0.45.1 包定义声明 NAPI8，并包含安装时 node-gyp-build 路径。Node-API 的 ABI 承诺不覆盖任意外部动态库／直接 V8 或内部 API 使用。（来源：[驱动13发布说明](https://github.com/WiseLibs/better-sqlite3/releases/tag/v13.0.0)、[驱动构建](https://raw.githubusercontent.com/WiseLibs/better-sqlite3/v13.0.3/binding.gyp)、[SQLite配置](https://raw.githubusercontent.com/WiseLibs/better-sqlite3/v13.0.3/docs/compilation.md)、[argon2固定包](https://raw.githubusercontent.com/ranisalt/node-argon2/v0.45.1/package.json)、[Node-API](https://nodejs.org/api/n-api.html)）

npm provenance 关联发布物和构建来源，不保证代码安全；可复现构建要求指定源码／环境／过程重建出相同目标产物，重复安装同一预构建包不满足此定义。（来源：[npm provenance](https://docs.npmjs.com/generating-provenance-statements/)、[Reproducible Builds 定义](https://reproducible-builds.org/docs/definition/)）

### 4.2 发布单位与验证顺序

维持 TS04 候选组合，不因为本轮查到标签就安装或标记可用。冻结单位是完整发布组合：精确 Node 24 补丁＋JS包＋SQLite驱动＋Argon2＋时钟适配＋动态依赖＋平台profile。npm版本相同但 `.node` 内容不同，视为不同制品。

首期分别验收 win32-x64／Windows11实际build、linux-x64-glibc／Ubuntu24.04amd64，以及固定digest的Linux glibc容器。Alpine/musl、ARM64、Windows容器不由这三个结果自动覆盖。普通用户安装包携带已验证运行时与原生文件，不要求用户装编译器；开发者源码构建另有受控工具链，不混作生产安装流程。

构建阶段允许按锁定源码受控下载／编译；安装阶段只校验、解包与配置。禁用生命周期脚本隐式编译、缺文件自动联网下载、改用系统SQLite或另一ABI；离线安装测试只是制品完整性测试，不扩展成产品断网自治承诺。动态依赖如VC运行库必须列入清单并验证，不能在加载失败后任意换包。

顺序为：预置信任根核验发布清单签名 → 校验文件hash／大小／目标平台 → 固定绝对路径加载 → 回读实际能力 → 启动保护态。受服务账户／管理员控制的安装目录不得由低权限模块修改，阻止校验后替换文件及DLL搜索路径劫持。摘要不符、依赖不符、引擎不符时不进入ready、不启动设备写；浏览器SDK不加载这些文件。

推荐 `native-release-manifest` 内容（下一轮实现前冻结结构，本轮无真实产物可填）：

| 分组 | 具体字段 |
| --- | --- |
| 组合 | manifest_schema、release_id、suite_component_versions、协议／IPC精确版本、compatible_db_schema_range |
| 源与依赖 | source_commit、source_archive_sha256、lockfile_sha256、package_name/version、registry_integrity |
| 目标 | os/arch/libc、tested_os_builds、minimum_os_build、required_cpu_features、dynamic_dependencies及hash |
| 运行时 | node_version、node_artifact_sha256、OpenSSL版本、构建工具npm版本 |
| 文件 | artifact.path/size/sha256、abi_kind=node_api或node_module_abi、napi_version或modules_abi（互斥） |
| 构建 | compiler/toolchain_versions、SDK版本、image_digest、flags、环境清单、源码补丁摘要 |
| 能力 | sqlite.version/source_id/compile_options_digest/expected_pragmas、argon2.reference_commit/known_answer_report、clock.adapter_abi/backend_profile/test_report |
| 证明 | sbom_sha256、license_bundle_sha256、acceptance_report_sha256、签名身份及bundle、provenance引用与状态、reproducibility状态及比较目标 |

SQLite实际用 sqlite_version／sqlite_source_id／compile_options及每连接PRAGMA回读；未知结果不使用网页值补齐。Argon2做固定向量与PHC验证，时钟加载成功不等于同域／休眠测试通过。Node-API版本只解决一层ABI，仍需OS接口、C运行库、CPU和权限验证。（SQLite查询来源：[官方核心函数](https://www.sqlite.org/lang_corefunc.html)）

签名、来源证明、可复现性三者分别记账。信任根必须通过独立可信安装／发布渠道提供，不能信任同一个未验证压缩包附带的任意公钥。签名工具／发布身份和轮换流程在真正发布前冻结；本轮不生成私钥、不签名。若Windows签名／时间戳改变字节，分别核验可重建的未签payload和最终签名产物，最终发布物仍须签名及hash校验。没有独立重建证据时状态是unverified，不能写verified。

升级仅在维护状态按完整组合替换并重启，禁止热替换已加载 `.node`。先处理在途／unknown与持久记录；回退同时校验数据库schema兼容，不因二进制回退复用不兼容库。备份恢复仍换控制／授权等既定epoch；回退旧程序不能降低撤销下界或重新开放已作废许可。

## 5. 验证计划与冻结交付

以下 PF01—PF18 均**未执行**；与 TV11／TV12／TV14、F02/F03 的 FT、F04/F05 的 FA/TB 验收关联，不重复宣称前轮静态用例已覆盖这些平台事实。

| 用例 | 正例与故障注入 | 通过标准 |
| --- | --- | --- |
| PF01 | 同运行域多进程夹取tick；错误域／backend／伪descriptor | 同域值可比较；错误身份全部拒绝，不能仅检查摘要相等 |
| PF02 | 监督器、worker、采集器分别重启；PID复用和旧消息晚到 | 各自代际正确变化，旧许可／样本不继承 |
| PF03 | worker挂起创建、Job关联失败、bootstrap冒充、handle泄漏、外部辅助进程 | 未纳管前零设备写；逃逸或不能证明终止即验收失败 |
| PF04 | 监督器kill后重启、旧socket已发送、DB存在unknown | 旧进程终止不被误当设备未执行；保持占用与恢复边界 |
| PF05 | OS完整重启、正常关机／快速启动、同OS服务重启 | 新运行代不复用；不依赖注册表易失行为 |
| PF06 | S3/S4/Modern Standby；通知延迟／遗漏、短睡眠未过TTL、恢复首发送竞争 | 旧闸不自动重开；不能保护的电源模式不得标通过 |
| PF07 | 时钟读取失败／回退／转换溢出、Linux不同namespace、VM冷启及热回滚模拟 | 错域关闭；热恢复局限有明确失败证据，不以nonce检测宣称完整fencing |
| PF08 | 下一版descriptor、旧IPC0.2消息及历史记录 | 协商明确，旧语义不静默升级；所有tick消费者与摘要投影覆盖 |
| PF09 | 固定chrony／Windows采集profile；本地化、截断、未知单位、RPC权限／超时 | 解析准确且有界；失败不阻塞出口、不回退弱证据 |
| PF10 | 重复源样本、服务重启、采集中换源、UTC LastSyncTicks误作单调值 | 年龄不刷新，混合响应拒绝，字段单位／时域错误拒绝 |
| PF11 | 第3.4节算术、age等号、右界等号、负delay／NaN／溢出 | 向外取整；边界错误全部拒绝；未证明profile即使数值合法也拒绝 |
| PF12 | 独立受控参考源；网络非对称、断源、频率／slew、温度／负载、睡眠 | 观测UTC落入所声称区间；任一反例使profile失败并修正模型，经验最大值本身不证明全局界 |
| PF13 | NTP源／认证／策略改变、墙钟step、闰秒／smear、迟到质量恢复 | 相关许可失效／代际保护；不延长旧截止、不补发；认证时钟独立 |
| PF14 | 无编译器／空cache／安装禁外连；删除原生文件、替换hash、错架构／musl | 完整离线安装可用；缺制品拒绝，不能编译／下载／换驱动 |
| PF15 | 两平台＋容器实际加载；SQLite回读、Argon2向量、时钟能力 | 每个发布组合有独立证据；NAPI兼容不代替能力验收 |
| PF16 | 未信任公钥、签名／manifest被改、校验后替换文件、动态库搜索污染 | 不进入ready；发布目录权限和加载路径可审计 |
| PF17 | 两个干净构建环境重建未签payload；签名后再校验发布物 | 重建比较目标明确；差异调查，不把重复下载记作可复现 |
| PF18 | 完整组合升级／回退，含DB迁移和撤销状态；存在unknown时维护 | 不混搭JS/native、不越过schema和epoch规则、不复活旧写 |

先做隔离技术试验，以模拟出口、合成身份／时间证据验证；OS重启／休眠、参考源网络、故障磁盘及设备试验需在专用受控环境执行，不能在当前直播机器直接做。正常机器无真实运行时采样、无安装操作，本文不含用户真实boot ID、NTP地址或制品凭据。

设计冻结交付：NF01—NF03决策、下一版契约差异清单、平台／源假设profile模板、PF用例及预期、制品manifest字段。运行冻结交付：原生包与签名清单、各平台原始日志及hash、实际时钟／SQLite／Argon能力、参考源误差实验、失败样本与处置、独立重建报告。两类交付分开，不以设计稿替代运行证据。

剩余具体门槛：Windows MS-W32T支持／权限和误差profile、监督域实现与挂起模式、发布信任根及工具链精确版本、所有实际原生产物hash。NF已确认且draft4生成器／正反例归并完成，具体余项见DF01—DF06；未关闭F01—F07运行验收。

本轮实际验证仅包括：既有draft.3的221个离线用例复验、合成有理数预算与边界的5项算术检查、文档链接／报告输入摘要和机器基线完整性检查。没有执行PF01—PF18、采集Windows真实身份／NTP状态、编译或加载原生包；这些检查不能替代平台验证。
