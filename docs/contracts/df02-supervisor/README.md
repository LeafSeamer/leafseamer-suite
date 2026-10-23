# DF02：监督启动、准入屏障与恢复日志候选

本批为项目推荐，未获冻结批准；承接[DF02](../../rebirth-df02-runtime-design.md)与[安装0.2](../c09-installation/LIFECYCLE_V02.md)，不替换公共draft.4、设备IPC0.3或面板IPC候选。没有实现进程监督器、设备控制或服务业务。

## 1. 权威、版本与两条通道

[build_contracts.py](build_contracts.py)是本批结构的唯一定义源，生成[监督控制Schema](supervisor.schema.json)与[bootstrap Schema](bootstrap.schema.json)。固定本地引用安装0.2的启动／权限类型和draft.4的运行域描述；不联网解析Schema。最终SDK归并仍沿DF01进行，本批不新建HTTP接口或要求浏览器持有启动权限。

- `supervisor-control/0.1.0-draft.1`：已准入核心与监督器的专属控制通道，9种帧。worker无此通道，不能以自报role取得控制权。
- `bootstrap/0.1.0-draft.1`：监督器逐进程定向继承通道，4种帧；不是业务IPC的新增消息。Assignment只经此通道交付，不能放到控制通道／日志／argv／env。
- control信封必含version、type、scope、channel_id、sequence、message_id、reply_to、payload。scope固定service_id、database_instance_id、supervisor_instance_id、domain_ref；数据库恢复换代后不能沿用旧scope。请求reply_to=null，响应必须指本连接实际未决请求；不能只验“非空”。
- 每个方向sequence从1严格递增，重连换channel_id且重新完整同步fence。乱序／重放／错误版本／角色混投关闭控制通道并锁存新准入。未知或未认证peer不获得带域信息的ERROR。
- 继承bootstrap端点已定向到创建实例，不再使用可自选channel信封；Assignment／Proof里的channel_binding_id绑定该端点。唯一Assignment→唯一Proof→ADMISSION或REJECT，重复proof不再准入，关闭候选并开始退役；原已落盘回执保留历史，不重新签发或改写为未创建。

core／time_provider只从保护配置创建，`ProtectedLaunchIntent`要求设备集合为空；core首次启动不等待尚不存在的业务库／核心授权。两者仍走同一journal、创建时纳管和bootstrap约束。保护配置入口不得接收外来LAUNCH_REGISTER，也不能选择role=worker；所有扩展worker必须携带完整extension_binding。纯panel不虚构worker。保护配置的实际制品身份／受限读提供者需在原生实现中验证，不能把该分支当任意可执行文件入口。

## 2. 逐消息字段、方向及响应

| 请求（核心→监督器） | payload与处理 | 响应（监督器→核心） |
| --- | --- | --- |
| FENCE_PUT | FenceSnapshot：scope、revision、items、digest；items每项launch_id、launch_intent_digest、allow/deny | FENCE_RESULT：revision、snapshot_digest、journal_committed=true；仅表示新创建准入边界已提交 |
| LAUNCH_REGISTER | 不可变ExtensionLaunchIntent与当前LaunchAuthorization；重复同ID只返回已登记状态 | LAUNCH_RESULT：原LaunchKey及JournalView；不得在REGISTER里调用OS创建 |
| LAUNCH_CREATE | LaunchKey、当前LaunchAuthorization、materialization_evidence_id、materialization_challenge_id | LAUNCH_RESULT：查询同一创建记录；可能creating／awaiting_bootstrap，不承诺已准入 |
| LAUNCH_QUERY | LaunchKey，仅查询；已知同ID异摘要必须identity_conflict | LAUNCH_RESULT；record=null仅说明健康当前日志没有该键，不证明外部旧进程不存在 |
| RETIRE_REQUEST | LaunchKey、完整containment_ref、reason（revoked／shutdown／bootstrap_failed／recovery） | RETIRE_RESULT：RetirementEvidence，可能unproven；不把超时或kill调用成功当退出 |

已鉴权但拒绝的请求可返回ERROR，code为identity_conflict／stale_fence／unauthorized／invalid_binding／expired／capacity／journal_unavailable／indeterminate／not_found，retry_action恒query_only。新合法操作必须由核心重新核权和显式准备，ERROR不授权自动重发CREATE或换ID。响应重投须重新构造当前信封，payload保持原身份结果；message_id不是业务幂等键。

`JournalView`含key、supervisor_instance_id、state、creation_attempted、admission_receipt、retirement_evidence、gate_state=closed。与安装0.2的LaunchRecord分开：**监督器出AdmissionReceipt；核心核验并持久化后才产生RuntimeBindingRef**。LAUNCH_RESULT不得要求监督器预先伪造该Ref。RetirementEvidence与核心登记的RetirementRef也同理。JSON内的closed只描述启动交付，不取代后续业务gate状态。

core持久准入事务须核对：JournalView.key、Receipt.launch_id／完整intent摘要／member／role／制品／组／bootstrap／端点／当前域和本地OS观察一致，当前审批仍有效；原receipt_id同内容幂等，异内容拒绝。监督器先持久receipt再交付两端；核心COMMIT未知只查询原键。子进程收到ADMISSION仍closed；缺核心持久RuntimeBinding时不得开始可写业务握手，更不能取得permit。

## 3. 完整fence集合与创建边界

FenceSnapshot.digest是仅排顶层digest后的完整对象JCS摘要，items按launch_id的ASCII顺序唯一排列。它不含LaunchAuthorization，授权只引用fence_revision，避免摘要循环。scope内revision是严格十进制串，按整数比较；同revision同摘要只回已提交结果，同revision异内容冲突，低revision拒绝。revision溢出不回绕，转维护恢复。

快照不是“在线进程列表”。核心从全部预登记owner／启动意图及撤权来源形成当前准入全集；监督器要求该control_scope的全部扩展worker非终态记录（含registered、creating、awaiting_bootstrap、admitted_closed、retiring、indeterminate）均在集合内且摘要完全一致。保护配置创建的core／time_provider不接受业务allow，仍受整域关闭／退役覆盖，不能借此遗漏扩展writer。允许加入尚未REGISTER的新意图；不在当前allow集合的新意图不能REGISTER／CREATE。终态记录可以退出当前集合，但永久否决／曾尝试创建墓碑仍保留。任一launch被deny后同ID永不恢复allow；已退休／拒绝ID也不能重新登记。固定意图的安装、审批及隐式设备范围由核心权威按完整来源捕获；监督器不能仅凭items摘要证明核心未遗漏一个尚未下发的意图。

收到已认证FENCE_PUT后先关闭本连接新创建准入，再在同一监督器串行执行上下文核对覆盖、拒绝墓碑及revision，事务提交快照／拒绝集合／当前指针，最后更新内存并回ACK。新快照失败或COMMIT未知保持关闭，不能继续用旧allow。重连即使提交同一快照，也必须核对健康日志、当前域和已认证核心，重新确认本连接同步；重放旧ACK不能开放。

REGISTER只持久固定意图与registered；CREATE须重新核对当前fence、两秒短授权、安装权威及物化challenge，不能借REGISTER时的有效期。物化evidence_id由监督器从已认证导入宿主获取并绑定原request：intake／authority／manifest／artifact／host trust epoch／challenge／完整intent摘要；调用者给的ID不是事实。五秒物化年龄从原challenge本地域起点计，加载前防替换核验另执行，不能用物化寿命延长短授权。

CREATE线性化顺序：当前快照检查→同事务记录creating／creation_attempted=true及恢复预算→确认提交→在同一串行创建临界区调用一次OS创建。进入临界区前已处理的deny阻止创建；临界区中到达的新fence等待该次调用返回或故障，**不能先回ACK再让早排队的CREATE执行**。进程创建成功也只能closed；没有无限等待，平台调用或日志超预算停止准入并按profile退出／整域恢复。撤权传播窗口中的已创建进程由后续退役处理，不声称撤权与OS创建跨库原子。

核心已提交launch prepare的outbox重投仅REGISTER／QUERY。只有健康日志明确registered、attempt=false，当前权威重新通过检查且显式CREATE时，才允许首次调用；creating及其后任何状态一律查询／退役。OS返回失败也已消耗尝试，不改成rejected；保守记indeterminate→retiring→经证明retired。组空、进程退出、回执超时均不能把attempt清零。

## 4. bootstrap投影与退役证据

四种bootstrap帧分别携带BootstrapAssignment、BootstrapProof、AdmissionReceipt、Error；字段由Schema逐项列出。secret和challenge_nonce各32字节，base64url无padding且必须规范往返；本批示例全部为合成字节，不是生产秘密。

HMAC-SHA256精确输入沿DF02：ASCII `leafseamer-bootstrap-proof/v1` + NUL + JCS(Assignment排除secret与clock_domain_descriptor，并加入descriptor的clock_domain_id、descriptor_digest)。这恰好是DF02列出的15个字段，不递归删除嵌套字段。先验OS创建实例／加载制品，再比较Assignment绑定、当前descriptor与完整intent、监督器本地原窗口、最后恒定时间比较MAC；MAC正确不能补缺OS证据或安装批准。子进程不得用自报tick延寿。

Bootstrap秘密只在当前监督器易失内存与定向通道持有；journal可存不含secret的固定挑战元数据，但不存秘密或完整Assignment。监督器崩溃后不恢复挑战、不补发secret、不重新接纳旧实例；先关闭旧域、取退出证明，再建立新域／新实例／新审批／新intent。只有核心响应丢失而监督器仍活时，允许QUERY已持久回执。

RetirementEvidence的member_group须覆盖该固定组全部成员（包括合法后代），runtime_domain须覆盖整个旧域所有受监督组。字段target_member_ids是完整注册成员ID集合，不能代表全部OS后代；os_observation_refs必须指向覆盖后代的真实组观测。先关闭旧域启动入口，核对组归属／成员完整性／无迁出条件、等待全部退出并处置相关端点，才可confirmed_empty。观察者使用自己的当前domain_ref与tick，不能拿新tick减旧tick。仅PID退出、空JSON列表、找不到路径或日志都不足。unproven保持保护。

## 5. 本机journal布局和恢复

推荐监督器独占`supervisor-journal.db`，与业务SQLite和安装库分开，路径由宿主保护配置提供，不由模块输入。候选采用本地SQLite、单writer、DELETE journal与synchronous=EXTRA；这是低频启动恢复日志的取舍，**不把业务库WAL配置整体改掉**。EXTRA在DELETE模式增加删除journal后的目录同步，但耐久仍依赖正确的VFS、文件系统与硬件，参数必须回读核对。（来源：[SQLite同步设置](https://www.sqlite.org/pragma.html#pragma_synchronous)、[原子提交及假设](https://www.sqlite.org/atomiccommit.html)。）精确原生SQLite制品／链接方式并入DF05，不用Python参考引擎冒充发行版本。

| 表／记录 | 唯一键与内容 | 事务／恢复责任 |
| --- | --- | --- |
| journal_meta | 单例；format_version、host_installation_id、journal_incarnation_id、保护profile摘要 | 仅首次受控初始化；已安装宿主缺失／坏页／来源不符，禁止自动建空库 |
| run | supervisor_instance_id；不可变descriptor与域归属、intake_closed | 启动先closed；监督器重启不重用instance_id，旧域仍保留待退役 |
| fence_snapshot／fence_item | (scope,revision)与(scope,revision,launch_id)；完整快照JCS、digest、item判定 | 快照、永久deny集合与current_fence指针同事务；先提交再ACK；重开验证摘要和完整集合 |
| launch | (supervisor_instance_id,launch_id)；完整intent JCS及摘要、member、组／generation、state、attempt、bootstrap_id、consumed、receipt／retirement | 意图／成员／组永久唯一且不可变；creating标记先提交；receipt与proof消费同事务；终态不复活 |
| observation | observation_id；所属域／组、OS实例观测元数据、事件类型和观察者tick | 不保存可复用裸handle作为权威；重开需重新取得OS证据。旧证据保持历史，不能直接证明当前组空 |
| recovery_attempt | launch唯一；恢复policy引用、origin domain／tick | 与creating标记同事务，失败仍计数；换域无法比较窗口时锁存，不清零重试 |

完整JSON须严格解析、Schema验证和摘要重算后入库，Ref身份、状态关联和组成员集合由事务层核验。序号／tick以严格十进制TEXT保存，不能转SQLite有符号INTEGER；按长度及ASCII顺序或有界大整数比较，不能用普通文本排序判断revision。journal中的JSON不保存用户秘密；观察元数据只在受限本机目录，可公开审计使用opaque引用。

[journal-probes.sql](journal-probes.sql)保留为原局部STRICT／FK探针；后续[完整journal候选](JOURNAL.md)已落实15张表、恢复计数视图、完整fence封存与双向延迟FK，具体布局以该候选为准。两者都不是已批准生产迁移，不能证明OS观察真实或BLOB内JSON合格。有效状态边：registered→creating／rejected／retiring；creating→awaiting_bootstrap／indeterminate／retiring；awaiting_bootstrap→admitted_closed／indeterminate／retiring；admitted_closed→indeterminate／retiring；indeterminate→retiring；retiring→retired。rejected仅限从未attempt；retired必须真实退出证据，即使创建前取消也不能仅凭false字段宣称组空。

故障恢复检查顺序：宿主单实例及可信日志身份→日志结构／摘要／域归属→关闭全部旧准入→查旧组与退出证据→保留所有attempt／deny／恢复计数→核心T8登记新域及原历史→新的当前fence→新实例closed握手。日志缺失／损坏／回滚嫌疑不自动修空库、不从业务备份覆盖；按DF02整域停止、人工维护确认和可证明清空后换journal incarnation，新旧域不可混用。query返回not_found本身不能完成这条链。

候选实验预算：单帧UTF-8最多256KiB、fence最多256项、每核心未决控制请求32项、bootstrap帧32KiB、固定保护队列8项；保护请求同目标合并，队列满时锁存全部新准入并走整域停止，不能丢掉deny后继续创建。fence超限拒绝整个集合，禁止截断或分批ACK冒充完整快照。journal按host profile限制总字节与历史域数，达到高水位不再新建；只允许在已证明整域退役且核心不再引用之后进行受审计归档，活跃墓碑不可压缩丢失。生产容量与时限沿DF02必须实测批准，这些实验值不是可部署默认。

## 6. 故障时序与验收

| 用例 | 切点／反例 | 必须观察的结果（运行仍待执行） |
| --- | --- | --- |
| SRT01 | 正常fence→REGISTER→CREATE→Proof→核心持久 | 只有一个OS创建；两端closed；无RuntimeBinding或T3—T5／T2时零设备写 |
| SRT02 | 同revision改内容、漏registered或旧未知成员、历史deny改allow | 完整拒绝且新准入关闭；不能部分应用 |
| SRT03 | 新fence先于CREATE临界区、或在OS调用中到达 | 前者零创建；后者ACK不得越过调用，已创建进程closed并退役 |
| SRT04 | creating事务失败／提交未知／提交后未调用OS即崩溃 | 未确认提交不调用；恢复保留保守attempt，不因组空重建同ID |
| SRT05 | OS创建成功但响应丢失或监督器死亡 | 同ID仅QUERY；死亡走整域核对，不补发secret |
| SRT06 | 正确MAC但错误OS实例、角色、意图、域、端点、制品或到期等号 | 准入拒绝；替换公开摘要或自报时间不能绕过 |
| SRT07 | Proof已消费／receipt提交成功但核心提交未知 | 原receipt不可变；QUERY核对；不得签第二次准入或设备许可 |
| SRT08 | fence ACK已到但子进程仍活、后代迁出或端点未处置 | 不得宣告退役／ready；unknown资源继续占用 |
| SRT09 | 控制通道重连、旧ACK重放、worker伪装核心 | 重新完整fence且身份精确绑定；模块不能启动其他模块 |
| SRT10 | journal缺失／损坏、旧业务备份恢复、计数跨域无法比较 | 关闭准入并保守整域恢复；不清计数或复活实例 |
| SRT11 | 日志满／fsync失败、保护队列满、fence超过容量 | 不截断证明；停止新准入及按profile整域保护 |
| SRT12 | Windows／Linux／容器创建及退役各切点 | 对应RT／PF真实组证据和落盘证据；一种平台通过不外推其他平台 |

离线[检查器](check_contracts.py)覆盖结构、两版本隔离、HMAC关联、完整fence快照、CREATE局部准入、核心回执关联、消息方向／序号快照、member_group退役和内存SQL约束。权威提供者为合成前提，未运行真实IPC、runtime_domain全部组枚举、加载与磁盘／OS故障；SRT不是已运行用例。报告不在旧顶层十份清单内，需独立复验：

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/build_contracts.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/check_contracts.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/check_contracts.py --check-report --staged
```

[报告](reference-report.json)绑定10份实际输入，staged只核字节不重跑；后续15表SQL由[独立检查及报告](JOURNAL.md#5-验证及实施交接)验证，不增加原179项覆盖声明。剩余设计工作是生产迁移与完整业务DDL／SDK归并、精确原生制品和容器组合；字段提供者／保护预算／平台耐久的运行证据随后实施取得。候选未批准、阶段0未关闭，不能把本批资料通过当系统可用。
