# 时间提供者完整准入来源候选

本候选为DF02/DF03补充time_provider启动来源，approved=false。从已打开的受信本机监督SQLite连接读取原件，不接受插件或网络JSON替代该连接。Schema见[机器字段](time-provider-source.schema.json)，读取规则见[参考模型](time_provider_source_model.py)。不修改既有监督协议，不启动真实进程。

## 1. 完整原件与字段绑定

| 对象 | 必须核对的来源 |
|---|---|
| SourceIdentity | journal_meta的host_installation/incarnation，以及runtime/control_scope的service/database；OS提供者身份由可信连接配置给定 |
| ClockDomainDescriptor | 完整规范字节、自摘要、clock ID、监督实例和不透明runtime_generation，与runtime物理列一致 |
| ProtectedLaunchIntent | role必须为time_provider，device_ids为空；launch/member/containment和service/监督域全部精确绑定；禁止core或worker混用 |
| 保护配置来源 | origin必须protected_config；完整origin_binding固定protected_policy_digest及intent_digest，与runtime政策摘要和原意图相等 |
| 创建尝试和准入 | 创建attempt存在；不能带扩展fence/authorization/materialization字段；launch_state必须admitted_closed，未进入retiring/indeterminate/retired |
| AdmissionReceipt | 原bootstrap/member_boot/channel、意图摘要、角色、制品、containment和Domain，与挑战及物理列逐项相等；准入tick属于原挑战半开区间 |
| ProcessObservation | 完整进程实例Ref、原成员boot/channel/制品/containment及域；OS来源身份精确，观察位于挑战开始至准入之间；独占通道/纳管/制品匹配由可信观察者确认 |

ProviderRuntime包含SourceIdentity、完整descriptor/intent/receipt/observation，以及固定revision=1、binding_id、binding_digest。binding_id由除ID/摘要外完整JCS内容的SHA256确定，前缀为time-runtime.；binding_digest再覆盖含ID的正文。此顺序没有自引用摘要环，同一已提交启动原件重读得到同一候选身份。

时间Domain中的provider_id取member_id，provider_boot_id取准入member_boot_id，runtime_binding_ref固定指向完整ProviderRuntime；authority/database和共享clock ID/descriptor从各自原件获得。clock_generation仍由Controller时间State按既有规则管理，监督器runtime_generation是Id，不能转整数或拿它代替数字代次。验证Domain时仍须通过既有时间Domain Schema，并与当前时间State精确比较；本来源不分配新的时间代次。

## 2. 事务与信任

读取器自行开启并结束一个监督日志读事务，拒绝接管调用方的外部事务；提交读取失败则不返回候选。若runtime已closing/retired，或成员已开始退役，当前读取拒绝。完整原件的自摘要、Schema及SQL关系只能证明内容一致，不能认证任意外部提交者，也不能把测试中的合成观察者变成真实OS证据。

本输出仍是**待核心采用的候选**。核心必须核对当前批准、受监督端点和时基资格，并把完整正文、固定Ref与采集器Channel/时间Binding原子持久化后，才允许把该Ref登记到时间State或用于OPEN来源。监督journal与Controller库分离，读取完成后可能发生退役；不能靠先读一次日志或“双读相等”证明跨库原子性。实际保护闭锁、同一监督运行域内的准入串行化及Controller采用失效机制仍须接通。

正常轨迹：可信监督器持久创建attempt → 受保护创建与bootstrap成功 → 保存完整OS观察/AdmissionReceipt及admitted_closed → 核心从受信连接读取完整原件 → 当前批准和监督资格核对 → 核心原子采用 → 时间来源才引用固定RuntimeBinding。此离线候选覆盖读取及关联验证，不执行创建、bootstrap或后两步采用。

关键故障轨迹：读取前成员转retiring，立即拒绝；读取事务尚持旧快照而外部退役已发生，旧原件仍可能一致，必须由核心采用与监督闭锁拒绝过时资格。若核心提交结果未知，先保持保护并按固定ID查原，不重建进程或重复消费bootstrap。历史receipt和group_owned观察均不证明当前alive。

## 3. 验收与缺口

[检查器](check_time_provider_source.py)沿用完整15表监督journal，在首次写入前构造完整合成时间提供者原件，未修改已有历史。正例包括确定性重复查询、无写入和时间Domain七项身份绑定；反例覆盖错误可信源、core/worker域替代、非空设备、错代次/boot/channel/制品/保护政策来源、观察时序、已退役/已关域、外部事务和读取提交失败。另以确定性串行交错复现“读取提交完成后、候选返回前进入retiring”，下一次读取拒绝；该反例证明候选不是持续活性令牌，不冒充真实并发或OS进程退役。报告见[验收结果](time-provider-source-report.json)。

该结果只证明受信日志中的准入来源关联。Controller对ProviderRuntime的原子采用/撤回、完整时间采集与NTS/profile、TIME保护与最终OPEN、真实进程身份和Windows/Linux运行证据继续未验。生产API不暴露本读取器，也不接受调用者自行提供所谓“可信”观察。
