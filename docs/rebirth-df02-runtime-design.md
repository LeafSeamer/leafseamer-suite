# DF02：可信启动、进程纳管与运行域恢复方案

日期：2026-10-17。依据已确认的NF01及公共draft.4／IPC 0.3；当前仍先完成全部系统方案，再实施业务。本稿的R01—R06是具体工程推荐，尚待整体审阅，不记录为用户已确认。没有创建服务、进程监督器或设备连接，没有执行平台故障试验。

## 1. 事实、修正及推荐范围

当前[机器契约](contracts/draft4/README.md)只表达运行域、守卫、许可和证据；其中`bootstrap_authenticated`是离线夹具前提，不能充当真实启动认证。DF02负责说明此权威如何产生和失效；DF03负责时间质量，DF04负责逐表持久化，DF05负责原生制品，DF06负责跨服务身份。两服务各自建立域，GUI不建立设备写域。

官方事实：Windows支持在CreateProcess的扩展启动属性中指定`PROC_THREAD_ATTRIBUTE_JOB_LIST`，Windows 10及以后可用；`CREATE_SUSPENDED`只暂停初始线程，并不自行纳管。由此推导，原NF01“创建后再AssignJob”的两步描述存在监督器死于两步之间的窗口，应收紧为**创建时入组，随后核验，再恢复执行**，属性失败不降级到先运行后入组。（来源：[Microsoft启动属性](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)）

官方事实：Job的kill-on-close依赖最后一个句柄关闭；多数完成端口通知不保证送达。Linux cgroup v2的populated覆盖整个子树，pidfd只指向特定进程；systemd的ExitType=cgroup会在仍有组内进程时保持服务运行。这些接口没有承诺撤回内核或设备已经接收的数据。（来源：[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)、[pidfd_open](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)、[systemd v255 service](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.service.xml)）

| 推荐 | 方案 | 选择理由与代价 |
| --- | --- | --- |
| R01 | 一个服务实例一个可信原生启动层；TS主服务、worker和采集器均由它登记；同一源码的原生平台层复用既有C/C++方向 | 原生层只负责OS生命周期、端点和时钟，不接管业务规则；增加原生发布与审计成本，纳入DF05 |
| R02 | 受限继承通道启动，双端绑定启动记录；业务IPC在认证完成后才进入现有HELLO | 自报domain或PID不授予成员资格；启动认证与运行授权分开 |
| R03 | Windows创建时入Job；Linux由受控cgroup纳管；单实例锁只作为合作方互斥 | 遗留组、进程句柄及禁止新启动联合证明；不声称跨主机全局设备互斥 |
| R04 | 仅在旧worker整个写入子组已证明退出时局部重启；无法证明则保持保护，必要时停止整个域后恢复 | 保留多设备故障隔离；禁止用未验证的PID树扫描强行接替 |
| R05 | 域关闭单向锁存；监督器／核心主进程重启一律换域；休眠无法证明安全时不开放该模式 | 不依赖JS通知及时到达；正常即时控制仍不单因NTP质量差而停用 |
| R06 | 启动及终止证据绑定持久记录，分清OS已退出、命令结果、资源释放三件事 | 保留unknown；新进程不能自证旧进程未发送 |

这些是本项目设计，不是上述OS接口天然提供的完整保证。首期后台模块仍属经批准的可信代码；本方案不把Job、cgroup、进程分离或HMAC称为恶意代码沙箱。具有管理员／root或调试注入权限的攻击者不在此组内完整性证明范围，面板隔离和第三方授权仍按C09单独验收。

## 2. 角色、所有权与可信配置

启动层随Controller／Seamer发布，不增加第六个用户部署产品。原生监督器持有OS单实例锁、Job或cgroup控制权、进程实例句柄和bootstrap通道；它不读取设备密码、不连接设备、不持有SQLite业务连接、不签发设备permit。TS主服务是唯一业务和持久状态权威；worker仍是唯一设备写出口。

保护配置须绑定`authority_service_id`、实例数据目录身份、部署设备归属、批准的platform_profile、原生启动器及Node／JS／native模块制品摘要和角色允许表。运行用户不能通过网页参数替换启动可执行文件、加载路径或profile。依赖树及脚本目录必须受写权限保护，不能仅hash Node可执行文件却允许模块入口被替换。启动前校验、加载期间防替换的权限假设及制品核验由DF05验收。

单实例范围是配置的服务实例和实际数据目录，不能靠随意更换service_id绕过同库所有权。Windows锁须跨交互会话，显式ACL；遇abandoned只进入恢复，不视作旧监督进程及其writer均已退出。Linux使用固定受保护inode上的非阻塞flock，监督器专持且不传给子进程；不unlink或重建文件“清锁”。flock是协作锁，并不能阻止另一个不遵循协议的程序控制设备。（来源：[flock](https://man7.org/linux/man-pages/man2/flock.2.html)、[unlink](https://man7.org/linux/man-pages/man2/unlink.2.html)；双inode风险是基于两者语义的工程推断。）

两个数据库副本、不同主机或厂商原操作台不受上述本地锁约束。部署清单必须确保LeafSeamer设备归属唯一，跨主机接替先停止旧实例并取得隔离证据；首期不以配置文件声明、Nginx或SQLite锁充当分布式fencing。原生控制台变化继续通过现场观测、前提失效及GUI告警处理。

## 3. 启动状态与顺序

监督域状态为`starting → recovering → admitted_closed → operational`；异常进入`revoking → retired`或`protected`。`retired`不可逆，原runtime_generation不可再次使用。`protected`不得靠续租回operational；先完成恢复、严格递增gate修订和新屏障。状态名是候选内部运行状态，不写入现有ControlRecord枚举。

1. 取得单实例锁，核对保护配置及平台功能；分配新supervisor_instance_id／runtime_generation。随机值不从备份、数据库或环境变量恢复。创建受限新组；此时尚无设备worker。
2. 创建并纳管TS核心进程，仅允许打开关键库及诊断。它读出旧域、旧写入组及未核销intent，执行T8恢复；原生监督器核验旧组归属并停止遗留写者。库损坏、归属不清、权限不足或无法证明旧组清空均停止在recovering，不能创建空库或新设备连接继续。
3. 核心在关键事务中记录新域descriptor、组身份、批准profile引用和恢复结果。启动核心所需的继承通道在此前已经由OS创建／继承链可信绑定，不依赖尚不存在的数据库成员表，避免循环依赖。核心在该阶段无设备出口。
4. 每次请求启动worker前，先可靠记录launch_id、目标角色／制品／设备集合、组身份和“尚未准入”。监督器从允许表解析制品，不接收任意命令行。创建成功但回执丢失时先核对该launch_id对应组，绝不再创建一个同设备writer。
5. 子进程从受限继承通道取得本次bootstrap，验证角色、域、制品、允许的IPC对端及期限。监督器完成对端核验和证明后发准入回执；核心持久记录后才允许业务IPC握手。所有设备写闸仍closed。
6. 设备只读发现与重连须显式声明无控制副作用；完成F02恢复账本、FENCE、T4、OPEN_GATE、T5后才可签发新的T2。bootstrap成功、组已空、业务HELLO成功均不跳过此链。

核心退出即终止整个运行域：不在原域重启核心并继续使用旧worker。单个worker故障可局部恢复，但旧子组清空、全新worker_boot_id／IPC／device_session及启动账本都是前提；原域仅在监督器、核心和共享时钟连续性仍可信时保留。采集器重启更换provider_boot_id并撤旧样本，不能给旧样本刷新接收时间。

## 4. 平台具体边界

### 4.1 Windows 11 x64

受限命名根Job覆盖核心与全部worker；按模块建立子Job用于局部终止证明。创建前配置KILL_ON_JOB_CLOSE且不允许breakaway，使用正确层级的JOB_LIST在CreateProcess时关联，初始线程保持suspended。返回后持有进程与线程句柄，核对实际关联及映像，再允许bootstrap与ResumeThread。嵌套Job或现有宿主Job约束冲突则拒绝该profile，不能静默去掉根Job。SCM自动重启也必须经过同一恢复入口。

继承使用明确HANDLE_LIST，只传bootstrap／所需受限日志句柄；不传Job、单实例锁、其他worker通道或设备写句柄。一个统一spawn入口串行管理临时可继承句柄，避免另一路宽泛继承。模块辅助写进程也必须登记并保持在该子Job内，不允许WMI／外部daemon代为启动写者。（接口事实来源：[句柄继承](https://learn.microsoft.com/en-us/windows/win32/procthread/inheritance)、[嵌套与继承规则](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)；统一spawn入口为项目设计。）

旧命名Job存在时，必须核对原绑定，不能给ERROR_ALREADY_EXISTS的对象套新代身份。恢复者打开旧Job也会延长句柄生命；不能等待kill-on-close自动完成，而应在确认旧监督者无权继续启动后主动终止旧组，查询ActiveProcesses=0，并等待已掌握的进程句柄退出。完成端口消息只唤醒核验，不作为唯一证据。找不到Job也不能单独证明旧writer已退出：还须验证旧代确实采用无逃逸纳管、原绑定及OS清理证据；缺这些条件保持保护。（来源：[CreateJobObjectW](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-createjobobjectw)、[组统计](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)、[TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)）

业务IPC命名管道须显式ACL、拒绝远程客户端、首实例保护。对端PID与监督器保留的进程实例／句柄、当前角色及成员组一起核对，不信任报文PID。默认DACL和FILE_GENERIC_WRITE不得直接照搬为最小权限；管道客户端也核对预期服务端。bootstrap秘密不经这个待认证的可寻址入口分发。（来源：[管道安全](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)、[CreateNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea)、[客户端PID](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid)、[服务端PID](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeserverprocessid)）

### 4.2 Ubuntu 24.04 amd64原生

推荐systemd管理整个服务域，`Type=notify`、`NotifyAccess=main`、`ExitType=main`、`KillMode=control-group`、`SendSIGKILL=yes`，并配置有限停止和重启预算。READY只表示服务完成初始化且可报告状态，不能被GUI解释为设备可写。native监督器为MainPID；核心异常要求监督器关闭子组并退出，不在旧域悄悄重启。停止超时后即使发出SIGKILL，也仍须观察域清空。（来源：[systemd v255 service](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.service.xml)、[systemd v255 kill](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.kill.xml)）

局部worker重启需要每worker一个可证明的cgroup子树。推荐在systemd显式委派的服务子树内，由可信原生监督器管理专用supervisor叶与worker叶，遵守单一管理者和内部进程约束。使用`clone3(CLONE_INTO_CGROUP | CLONE_PIDFD)`在创建时入目标组，再exec固定制品；失败不降级为fork后追赶移动。保留pidfd及cgroup目录FD／身份，记录允许的namespace。模块不获cgroup控制FD／迁出权限；授权隔离配置无法落实时该组合不开放设备写。（来源：[systemd cgroup接口](https://systemd.io/CONTROL_GROUP_INTERFACE/)、[clone3](https://man7.org/linux/man-pages/man2/clone.2.html)；该组合仍待目标内核与权限实测。）

“不传控制FD”不足以隔离迁移：Delegate=yes配合User=会把委派子树交给该用户，同UID子进程可按路径重新打开控制文件。因此推荐监督器使用独立专用UID，核心／worker／采集器使用无委派权限的运行UID，cgroup管理路径仅监督UID可写。原生启动层只保留必要的SETUID／SETGID身份切换能力，目标UID及附加组由保护配置固定；子进程exec前清理不需要的附加组、清空capability集合并设置no_new_privs，不继承监督层提权能力或控制FD。正常关停经受鉴权通道，强制清理由授权cgroup.kill完成；不因pidfd指向子进程便假设跨UID发送信号无需权限。此方案增加可信原生启动层的权限责任，必须验证路径重开、兄弟组迁移和namespace逃逸负例，不能仅检查继承列表。对容器需证明同等权限边界，不能沿用“同UID且全部可写”的委派配置。（来源：[systemd委派](https://systemd.io/CGROUP_DELEGATION/)、[内核委派包含规则](https://docs.kernel.org/admin-guide/cgroup-v2.html#delegation-containment)；分UID方案为项目推荐。）

关闭旧子树并停止新的成员准入后，授权监督层可对委派子树执行cgroup.kill，再等cgroup.events的populated=0；pidfd退出只作为已知进程实例证据。需验证子树身份、没有逃逸和外部迁入来源；组路径或PID单独不足。僵尸无需继续执行用户态代码，但回收记录与无可运行writer证明分别处理。若子树证明缺失，不能做局部接替；整个systemd域停止并得到可靠清空证据后才重新建立服务域。

bootstrap使用明确继承的AF_UNIX socketpair端点，其他FD均关闭／CLOEXEC；业务IPC亦由监督器创建并定向交付两端，避免开放任意本机连接。socketpair的SO_PEERCRED可能反映创建时的监督进程，不能当作exec后worker身份；应结合实际spawn／pidfd、专属继承端点和启动证明。若后续使用可寻址Unix socket，则增加受限目录、连接时凭据及同样的启动绑定，不能只验证UID。（来源：[unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html)）

### 4.3 容器、开发启动与虚拟机

Linux容器也是独立profile：明确由容器运行时管理根组、谁能证明旧容器全部进程退出、数据目录单实例锁如何跨重建保持，以及是否支持委派的worker子树。不能从容器内看不到旧PID推断旧实例不存在；不授予整个Controller privileged、宿主PID空间或CAP_SYS_TIME来规避验证。

无子树管理能力的组合不能声称支持局部worker接替；可以在设计批准后采用整个容器停止、由宿主确认旧组清空、再创建全新域的恢复路径，其故障半径须显示并单独验收。该路径保持首期容器交付目标，不能以“容器不支持”删除需求。裸`node server`的开发启动只允模拟／只读，不能绕过启动层控制真实设备。VM冷启动继续可验收，热快照／内存回滚可写恢复继续不支持，不能用本地nonce证明外部现场一致。

## 5. 内部bootstrap候选契约

建议独立版本`bootstrap/0.1.0-draft.1`，不是第20类业务IPC消息。后续[监督器机器候选](contracts/df02-supervisor/README.md)已生成其Schema及独立控制通道格式，尚未并入SDK或批准。最终归并时按DF01单一来源规则管理，draft.4／IPC 0.3机器文件不改。所有对象封闭，整数词法按DF01的新版本修订另审，不从旧正则漏洞导出新允许值。

公共标识／digest沿用SDK类型；纳秒为无符号十进制字符串，不能转Number。OS句柄值、FD、原始PID／创建时间留本地受保护观测，不作为可序列化授权凭证。可公开审计仅使用不含秘密的引用。

| 对象 | 必填字段 | 权威与约束 |
| --- | --- | --- |
| LaunchIntent | launch_id、service_id、supervisor_instance_id、runtime_generation、member_id、role、artifact_manifest_ref、containment_ref、device_ids、policy_revision | 核心持久化；role仅core／worker／time_provider；设备集合去重有界；core的首记录在恢复事务建立，设备worker必须先记录再启动 |
| BootstrapAssignment | bootstrap_version、bootstrap_id、launch_id、launch_intent_digest、member_id、member_boot_id、role、完整ClockDomainDescriptor、artifact_manifest_ref、channel_binding_id、challenge_id、challenge_nonce、issued_tick_ns、expires_tick_ns、secret | 监督器专属继承通道分发；nonce与secret各32字节随机、base64url无padding；secret不落库／日志／argv／env |
| BootstrapProof | bootstrap_version、bootstrap_id、launch_id、launch_intent_digest、member_id、member_boot_id、role、clock_domain_id、descriptor_digest、artifact_manifest_ref、channel_binding_id、challenge_id、proof | 子进程回送；proof为下述HMAC；不能自行更换role、制品或设备集合 |
| AdmissionReceipt | receipt_id、bootstrap_id、launch_id、launch_intent_digest、member_id、member_boot_id、role、domain_ref、channel_binding_id、containment_ref、os_observation_ref、artifact_manifest_ref、admitted_tick_ns、gate_state=closed | 监督器生成；核心先核验且可靠保存，随后方能开始业务HELLO；receipt不是permit |
| RetirementEvidence | evidence_id、service_id、old_domain_ref、target_scope、target_member_ids、containment_ref、launch_intake_closed、os_observation_refs、result、evaluator_domain_ref、observed_tick_ns | result仅confirmed_empty／unproven；新监督器观测用自己的tick，不能与旧域tick相减；未知／权限不足必须unproven |

`artifact_manifest_ref`具体为`{manifest_id,revision,digest}`；`containment_ref`为`{group_id,generation,backend}`，backend仅windows_job／linux_cgroup_v2／container_runtime；这里是逻辑引用，不能仅凭其JSON值证明OS组真实存在。`domain_ref`复用draft.4的ClockDomainRef。`target_scope`仅member_group／runtime_domain；result=confirmed_empty须同时满足启动入口关闭、可信组归属／成员完整性、全部写入者退出及有关端点已处置。端点处置不表示远端设备队列已清空。

LaunchIntent在同一launch_id下永久不可变；状态及结果存另一条记录，禁止原地改设备集、组、策略或制品。device_ids在生成Intent前按标识ASCII顺序去重排序，其余数组保持各自声明顺序。`launch_intent_digest=sha256:<SHA-256(JCS(完整LaunchIntent对象))>`；原Intent对象不包含这个派生字段。监督器从已认证核心通道取得并匹配完整Intent，不接受模块自报digest；core首次启动的Intent由保护配置和监督器创建记录产生，在恢复事务中原样登记。digest贯穿Assignment／Proof／Receipt，引用缺失或同ID异内容即拒绝。

HMAC输入精确为ASCII前缀`leafseamer-bootstrap-proof/v1`加一个NUL字节，再接JCS对象`{bootstrap_version,bootstrap_id,launch_id,launch_intent_digest,member_id,member_boot_id,role,clock_domain_id,descriptor_digest,artifact_manifest_ref,channel_binding_id,challenge_id,challenge_nonce,issued_tick_ns,expires_tick_ns}`的UTF-8字节；key为Assignment的secret解码结果，算法HMAC-SHA-256。proof为32字节base64url无padding，恒定时间比较。该域分隔输入和既有业务digest投影完全不同，不复用用户凭据。采用平台／成熟密码库，不自写密码原语；精确构建依赖由DF05锁定。

先完成OS对端／创建实例核验，再验证proof；只证明持有本次启动秘密不等于制品可信、设备授权或恶意模块隔离。允许窗口为`issued <= now < expires`，由监督器在同域计时，子进程自报时间不能延长。每bootstrap_id只准成功一次；重复proof、错角色、错域、迟到proof、错误channel或产物均拒绝并关闭该候选，禁止自动重发新的secret来掩盖失败。受理回执丢失时按launch_id查询只读状态；不得重新启动同角色writer试探。

子进程bootstrap状态：`await_assignment → proof_sent → admitted_closed`；任何错误到`rejected`，不得回到等待状态复用相同成员身份。channel EOF、监督失联或域撤销立即锁存关闭；能否及时执行该关闭仍受最终出口本地租约及平台调度边界约束。禁止在bootstrap完成前执行模块的设备连接／自动恢复初始化。

预算作为platform_profile的必填字段：bootstrap_timeout_ms、graceful_stop_timeout_ms、forced_exit_observation_timeout_ms、restart_backoff_ms、restart_window_ms为正整数毫秒；max_restart_attempts为正整数次数。自动恢复在滚动restart_window_ms中每发起一次恢复启动就计数，创建失败、bootstrap失败也计入；正常首次启动不计。计数在创建前可靠登记，不能通过反复重启监督器清零；跨域后无法可信计算剩余窗口时保守锁存，明确的维护恢复另记授权和审计。所有超时从原起点计算，失败不会顺延。生产数值需按有限队列和保护预算实测批准；设计不能用无限值、0表示无限或“系统默认”。尚无实测profile，不能宣称DF02已经获得生产参数。

## 6. 持久化、恢复与屏障衔接

2026-10-18后续候选：[安装0.2](contracts/c09-installation/LIFECYCLE_V02.md)为扩展worker的LaunchIntent增加完整extension_binding，审批／解析及收窄权限摘要进入原完整意图摘要；BootstrapAssignment／Proof／AdmissionReceipt必须绑定扩展后摘要，不能剥离新字段。新增短期LaunchAuthorization及启动fence、一次创建LaunchRecord和监督器本机journal方案；core/time_provider引导不套扩展审批，纯panel不虚构worker。该候选未改本稿既有机器协议；完整bootstrap／fence消息及平台耐久仍待归并和验证，LACT用例未运行。

以下是DF04逐表设计必须保留的事务责任，不另建第二个业务库或让监督器绕过核心写SQLite。监督器可以在存储完全失败时先关闸／停止进程；这不意味着已经产生可靠审计记录。

| 阶段 | 关键记录与提交边界 | 不确定时 |
| --- | --- | --- |
| 域恢复T8扩展 | 旧ready作废、旧queued终结／未核销intent保守处理、限制与资源恢复；新descriptor及其批准profile引用 | 无新worker／permit，保持recovering |
| 启动登记 | launch_id唯一；角色、制品、设备集、组身份、当前域、pending准入、审计同事务 | 不发spawn；若spawn回执丢失，核对已有组而非再启动 |
| 准入登记 | 回执／观测引用、完整成员绑定、已验证通道及closed状态、审计同事务 | 候选保持closed，停止或核对，不发送业务许可 |
| 保护与退役 | 先停止调度及新启动；尽力CLOSE_GATE／停止组，后保存原OS观测与退役证据 | 保护不等数据库；不可落库不报durable，不开放继任writer |
| 再开放 | 新worker身份、旧组终止证明、T3/T4恢复屏障、OPEN_GATE和T5，随后才可T2 | 保持unknown／资源占用／人工持有人和暂停锁存 |

证明旧组清空只允许创建安全的继任进程；它不释放设备资源、不完成命令、不将unknown改为not_sent，也不自动布防。旧writer成功回执若迟到，只可按原域／尝试追加核对证据；旧FENCE_ACK不能开放新域。跨主机停止证明、备份恢复、新请求世代沿用既有规则。

关键故障时序：T2已提交→旧worker可能进入Lsend→监督器死亡→新监督器只启动只读恢复核心→发现旧Job句柄仍被保留→终止旧组并验证空组→保存退役证据→旧命令仍unknown及占资源→新workerclosed完成握手→仅有充分资源清理／恢复条件的新操作才可能开放。该序列没有重放旧DISPATCH。

## 7. 休眠与运行域失效

NF01的“睡眠计入tick”只证明经过时间语义，不证明恢复后第一次设备写一定被通知拦截。最终出口仍直接读取经验证的平台时钟并检查域、租约、guard、截止和保护锁存；OS通知仅帮助撤销，JS定时回调不是保护线性化点。

检测到休眠／连续性不可信时：关闭新派发及准入、失效时间样本、禁止续期；本轮推荐把当前域退役并走新域恢复，已签发意图按发送证据分类。不能以一次新时钟读数、恢复通知或同一OS启动身份自动重新开放旧token。该推荐比只增加gate_revision更保守，需作为R05明确审阅。

若平台不能证明恢复后的首个Lsend先于域验证被阻止，活动直播profile应要求禁用该电源模式并验证策略；用户强制挂起等违反profile假设的行为如实标为未保障，不能宣称代码绝对消除检查与OS暂停之间的竞态。即时手动不因业务NTP失效单独受阻，但运行域失效时同样禁止新写。VM热恢复仍需另审外部fencing，不在此处用长租期或nonce补救。

## 8. 正反例与平台验收

全部RT用例为待执行设计；对应PF01—PF08、FT04—FT14／FT24—FT25。各用例要观察真实最终传输入口顺序、OS组／进程实例、bootstrap与IPC身份、重开后的SQLite记录和GUI状态。单个假布尔值或有限离线轨迹不证明平台行为。

| 用例 | 输入／故障切点 | 预期结果 |
| --- | --- | --- |
| RT01 | 合法新域、固定制品、无旧writer、完整启动握手 | 先admitted_closed；未经T3—T5和T2设备写次数为0 |
| RT02 | 只提交正确descriptor和digest，无可信启动通道 | 拒绝成员准入，不能自授权 |
| RT03 | Windows创建返回前后各杀监督器 | 子进程已在正确Job内或根本未创建；不存在可运行的未纳管writer |
| RT04 | JOB_LIST失败、嵌套Job冲突、已有同名Job | 不降级创建；旧对象先识别与恢复 |
| RT05 | 意外继承Job句柄／诊断程序持有旧Job | 不能以监督器退出认定全死；主动终止和查空组后才能接替 |
| RT06 | 完成端口通知丢失、ActiveProcesses仍非0 | 以查询及实例退出证据判断；超预算保护，不伪报清空 |
| RT07 | 管道抢先占名、远程客户端、同UID错误PID／错创建实例 | 首实例／ACL／进程绑定拒绝；不发送启动secret |
| RT08 | Windows辅助进程breakaway或借外部服务写设备 | 模块／profile验收失败，不申报强屏障能力 |
| RT09 | Linux主监督者退出但后代仍在 | unit停止清组；新域不在旧写者存活时开放 |
| RT10 | clone3被seccomp拒绝、cgroup权限不足 | 无fork后补入组降级，无真实设备写 |
| RT11 | 旧worker死亡，孙进程持续fork或持连接 | 子树未清空则无替代writer；pidfd退出不够 |
| RT12 | PID被复用、cgroup路径重建、错误namespace | 旧实例引用不匹配，拒绝证据及tick比较 |
| RT13 | 对socketpair的SO_PEERCRED误用为worker身份 | 负向测试必须检出，专属端点与spawn记录才是绑定来源 |
| RT14 | flock文件被unlink后重建、FD意外继承 | 配置／profile检查拒绝错误锁策略，不能启动两个合作方writer |
| RT15 | 错role、错制品、错channel、错nonce、错域proof | 全部拒绝且候选关闭，不能进入业务HELLO |
| RT16 | proof恰在expires、重复成功proof、丢准入回执 | 等号与重放拒绝；查询原launch状态，不重复spawn |
| RT17 | bootstrap secret出现在argv／env／日志／错误对象 | 安全验收失败；只允许受限通道和短期内存 |
| RT18 | launch登记提交前／后崩溃，spawn后回执前崩溃 | 前者无spawn；后者核对组，未准入进程不写且不重复创建 |
| RT19 | 准入回执已产生但SQLite提交失败 | 不进业务握手／开放链，受控清理或核对 |
| RT20 | 核心崩溃但原生监督器存活 | 整个域撤销，新核心新域，不收养旧permit |
| RT21 | 单worker崩溃，其完整子组可核验退出 | 仅受影响设备保护；新worker/session，无旧队列继承 |
| RT22 | 子组终止证明不足／未知外部写辅助进程 | 保持保护；不以超时充当退出证明，不盲杀不明归属进程 |
| RT23 | 旧writer进入传输后被杀，设备稍后生效 | 旧命令unknown／在途保持；组空不改判取消成功 |
| RT24 | 旧域FENCE_ACK、SEND_REPORT在新域迟到 | ACK不能开新闸；报告仅关联旧尝试追加核对 |
| RT25 | 休眠通知延迟、恢复后立即送旧permit | 已批准profile下无旧许可越界；不能证明则该模式不获准 |
| RT26 | 时钟回退／读取错误／namespace改变 | 域保护／退役，无Date.now回退、无重置deadline |
| RT27 | NTP质量失效但单调域／其他即时门控有效 | 即时手动不因NTP单项被误禁；绝对排期阻止 |
| RT28 | 容器重建时旧容器进程未清空、并行副本同设备 | 宿主接替证据及部署唯一性检查阻止新写 |
| RT29 | 监督器重启风暴／bootstrap无限等待 | 有限预算、保护锁存、告警；重启服务不重新布防 |
| RT30 | 旧库恢复、旧launch/receipt/ready仍在 | 换世代并只读历史，旧准入记录不复活 |
| RT31 | 异常清理过程中关键库不可写 | 停写路径仍工作；证据不伪称durable，新写不开 |
| RT32 | 普通VM冷启动对比热快照／内存回滚 | 分别取证；冷启动通过不授权热恢复写入 |
| RT33 | 同UID模块重新打开cgroup.procs并迁移辅助进程到兄弟组 | 不接受该错误权限profile；合格分UID配置须拒绝路径重开和迁移，不能仅观察原组为空 |
| RT34 | 同launch_id替换设备集／策略／组，或重算digest后重用旧proof | 不可变映射、摘要与HMAC共同拒绝；不同ID也不能绕设备唯一所有权 |
| RT35 | 恢复创建失败／bootstrap失败连续发生，监督器随后重启 | 每次尝试计数，预算不能重置；跨域窗口不可证明则保护锁存 |

## 9. 跨项审阅及下一步

| 关联 | 一致性处理 |
| --- | --- |
| draft.4域摘要 | bootstrap绑定完整descriptor，不把新内部字段塞入既有摘要或公开API |
| F02唯一出口 | 启动层不持设备写连接；创建时纳管消除未入组窗口，OS组不替代Lsend／Lfence |
| F03持久边界 | launch／admission与T8／T3—T5衔接；控制权effective、进程admitted、业务ready继续独立 |
| F04身份 | 本地启动成员资格不是用户权限／组织grant；TLS认证时间不由此协议替代 |
| F05时间 | 同域tick用于bootstrap截止；旧域退出观测使用新观察者域，不跨域相减 |
| F06／F07结果 | 进程终止不证明命令未发，不释放unknown资源，不自动消费恢复操作 |
| C09扩展 | 经批准模块也须纳管；不能借可信后台定位宣称任意第三方安全隔离 |
| C12部署 | 原生、容器分别提交平台证据；不能因一种启动路径难验证而删除原定支持目标 |

本稿明确了创建时纳管、局部与整域恢复、bootstrap字段／密码投影及事务顺序，尚未关闭DF02。后续[监督器机器候选](contracts/df02-supervisor/README.md)已补bootstrap四帧、控制九帧、完整fence集合、创建前持久attempt、journal布局与正反例；运行阶段执行RT01—RT35及SRT01—SRT12。剩余设计归并包括DF04完整生产DDL、DF05精确原生构建及profile清单、容器平台具体运行时组合。全系统设计前置条件继续有效，不因本稿完成而开始业务实现。

## 10. 监督器机器候选与核心准入边界

2026-10-18新增[独立候选包](contracts/df02-supervisor/README.md)。监督器返回JournalView／AdmissionReceipt，核心核当前审批并持久化后才生成安装0.2的RuntimeBindingRef；监督器不持业务库，不提前伪造核心Ref。bootstrap秘密不落盘，监督器崩溃不能恢复挑战；重复CREATE只查询原attempt。fence ACK仅证明准入切断，退役仍须完整组证据，unknown及设备资源不自动释放。

完整fence覆盖registered与全部非终态成员，历史deny不可复活；快照、拒绝集合与current指针同日志事务，OS创建在确认attempt提交后最多调用一次。推荐独立监督journal采用SQLite单writer、DELETE／EXTRA，业务库WAL不变；这是新增待审阅的原生依赖和存储取舍，不是已批准制品。局部内存SQL和合成消息检查只证候选约束，真实平台／设备／磁盘故障仍未验。

## 11. 时间提供者准入来源

新增[完整时间提供者来源](contracts/df02-supervisor/TIME_PROVIDER_SOURCE.md)候选及Schema，固定time_provider角色、空设备集合、保护配置来源、创建attempt、bootstrap身份、完整准入回执和进程实例观察。由受信监督连接在单个读事务中核所有物理列和原件，关闭域或开始退役立即拒绝；读取提交失败不交付候选。固定ID和摘要来自完整不可变原件，不由调用方任意指定。

这是提供者RuntimeBinding的采用输入，不是已提交的核心Ref或当前OS活性证明。核心仍须核批准和当前监督资格，并与Channel/时间Binding原子持久化；跨监督库和Controller库的竞争须由实际监督闭锁及采用撤回机制解决，不能由两次读取相等代替。时间Domain保留独立提供者member/boot，数字clock_generation由Controller时间State管理，不从不透明runtime_generation转换。完整创建、双平台、采集器运行和最终OPEN均未因此验收，业务代码未改。
