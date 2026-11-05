# LeafSeamer

> **施工中 / Work in progress。** 新版已按依赖进入业务实现，SDK 已有可本地安装的开发包，Controller 已有持久身份、保护态启动、本机健康接口和首次管理员事务；本地HTTPS身份与GUI设备读取闭环已验证，生产认证资格与完整业务服务、完整GUI、部署组合及设备验收尚未完成，当前不提供生产可用的直播系统。

LeafSeamer 是直播软硬件控制与自动化项目。各组件独立仓库、独立版本，Suite 负责总体设计、部署组合和整套验收；首期不使用强制 Submodule。

| 仓库 | 职责 |
| --- | --- |
| [leafseamer](https://github.com/LeafSeamer/leafseamer) | Seamer 规则、状态机和排期 |
| [leafseamer-controller](https://github.com/LeafSeamer/leafseamer-controller) | 独立设备控制、模块、接管和执行 |
| [leafseamer-gui](https://github.com/LeafSeamer/leafseamer-gui) | 统一网页操作台 |
| [leafseamer-sdk](https://github.com/LeafSeamer/leafseamer-sdk) | 公共契约、客户端与模块开发接口 |
| [leafseamer-suite](https://github.com/LeafSeamer/leafseamer-suite) | 总入口、设计、兼容组合、部署与验收 |

- [当前SDK开发包：产品契约、业务客户端与独立监督通道](https://github.com/LeafSeamer/leafseamer-sdk/tree/ca0a119188b1bbf09559f12008b2d0d84b1d9a4c)
- [当前Controller开发入口：持久身份、核心监督与同源GUI服务](https://github.com/LeafSeamer/leafseamer-controller/tree/7983c38d0439a64f54b285e565ef545f692911b7)
- [GUI开发工作台：人员会话与设备读取](https://github.com/LeafSeamer/leafseamer-gui/tree/1e14019ac7f89ad56c854649161b889a3b3daa29)
- [SDK既有契约：发布原件与当前面板提供者](docs/contracts/sdk-publication-handoff/README.md)
- [完整设计稿与 Q1—Q72 决策](docs/rebirth-design.md)
- [全系统设计定稿收敛清单：具体缺口、审阅包与实施交接](docs/rebirth-design-closure.md)
- [当前归并审阅：受监督运行域、NTP 证据、公共 draft.4 与 IPC 0.3](docs/rebirth-draft4-review.md)
- [DF01：SDK 唯一契约源、固定生成链、JCS 与大整数](docs/rebirth-df01-sdk-freeze.md)
- [工具链收敛：精确候选、官方元数据与冻结验证步骤](docs/rebirth-toolchain-lock-design.md)
- [DF02：可信启动、进程纳管与运行域恢复](docs/rebirth-df02-runtime-design.md)
- [DF03：授时采集、源年龄、profile 批准与失效](docs/rebirth-df03-time-profile-design.md)
- [DF04：SQLite 表契约、事务、保留与恢复](docs/rebirth-df04-storage-design.md)
- [DF05：发布清单、信任根、升级与回退](docs/rebirth-df05-release-design.md)
- [DF06：内部身份、对象授权、来源证明与查询保护](docs/rebirth-df06-internal-trust-design.md)
- [C04：自动化表达式、发布绑定、触发仲裁与失败恢复](docs/rebirth-c04-automation-design.md)
- [C05：事件身份、快照交接、订阅 ACK 与容量保护](docs/rebirth-c05-event-sync-design.md)
- [C06：排期导入、日历、场次身份与逐步派发窗口](docs/rebirth-c06-schedule-design.md)
- [旧排期五模块能力映射与源码边界](docs/rebirth-legacy-schedule-map.md)
- [C09：模块生命周期、扩展授权与面板委托](docs/rebirth-c09-extension-design.md)
- [C10：GUI状态、接管转交、实时控制与完整编辑入口](docs/rebirth-c10-gui-design.md)
- [C11：NodeCG桥接、旧图文、编辑器与远端在途](docs/rebirth-c11-nodecg-design.md)
- [C11：OBS／ATEM全能力、传输与完成证据](docs/rebirth-c11-obs-atem-design.md)
- [C11：Mixer／DM3／WING／VB音频契约与184项来源清单](docs/rebirth-c11-audio-design.md)
- [C12：部署入口、只读输出、备份恢复与维护切换](docs/rebirth-c12-deployment-design.md)
- [旧设备八模块能力、型号与完成证据映射](docs/rebirth-legacy-device-map.md)
- [旧自动化、图文、日志、备份与持久化映射](docs/rebirth-legacy-system-map.md)
- [实施前技术选型：SDK、代码生成、认证、SQLite 与时钟](docs/rebirth-technology-selection.md)
- [平台冻结：Windows 运行域、NTP 误差界与原生制品](docs/rebirth-platform-freeze.md)
- [整体审阅及待落实事项](docs/rebirth-review.md)
- [实施前契约与验收交付清单](docs/rebirth-readiness.md)
- [首闭环 SDK/API 与执行契约草案](docs/rebirth-first-loop-contract.md)
- [可校验 Schema／OpenAPI 与正反例](docs/contracts/README.md)
- [F01—F07 进度及命令／接管边界审阅](docs/rebirth-contract-review.md)
- [F02／F03：IPC、唯一写出口、SQLite 与故障验收](docs/rebirth-f02-f03-design.md)
- [F04／F05：身份撤销、NTP 时间边界与容量保护](docs/rebirth-f04-f05-design.md)
- [F06／F07：OBS 完成证据、失败依赖证明与恢复并发](docs/rebirth-f06-f07-design.md)
- [路线图](docs/ROADMAP.md)
- [旧版交接记录](docs/LEGACY_HANDOVER.md)
- [开发记录](DEVELOPMENT_MEMO.md)

新版运行库采用 SQLite，支持指定 NTP 时间源，GUI 脱离 NodeCG；播出图文通过可选 NodeCG 桥接提供。完整功能仍在实施，实际完成范围以上述统一收敛清单为准。五仓的 `rebirth` 已通过 merge commit 合入 `main`，后续在 `main` 推进设计与实施。

## 本机安装账本与静态归档验证

Suite 已提供 `@leafseamer/suite/installation` 内部运行模块，使用与当前产品相同的 Node 24.22.0、better-sqlite3 13.0.3／SQLite 3.53.4 和 canonicalize 5.1.0。依赖固定于本仓 `package-lock.json`；构建后的包不需要相邻仓库。Windows开发环境先安装依赖并构建固定原生输入，再运行检查：

```powershell
npm ci --ignore-scripts
npm run build:native -- --headers C:\toolchain\node\include\node --node-library C:\toolchain\node.lib
npm test
```

上述工具链路径为示例，须使用`native-inputs.json`固定的Node头文件及Windows x64导入库，配合CMake、Visual Studio 2022 C++工具链和Windows SDK。构建产物核原生源码、输入、编译配置及二进制摘要，并随包交付。测试发行引用由真实验签和安装库生成，密钥、初始渠道、固定时间及安装策略仍为合成输入，不代表真实生产发行已获批准。

`createInstallationStore(directory)`只供可信首次安装入口使用，要求安装器预先建立并保护的空目录。它创建独立安装／权威／数据库／epoch身份和持久标记；普通`openInstallationStore`只开既有库，不因缺库新建。目录或数据库文件身份不符、额外DDL、错误Schema／引擎、完整性／外键失败均拒绝。连接按DF04使用单writer、WAL／FULL、零等待、外键／递归触发器和禁止可信Schema；它不与业务数据库共用事务，也没有业务备份恢复入口。标记和文件身份核验不代替OS访问控制或首次安装信任证明。

`recordAcceptedImport(request)`是本机agent核对端、目标管理权及安装策略之后的持久事务入口，不能直接暴露给网络或GUI。新请求在同一事务中查验同库真实发行记录、当前活跃会话、最新发行序号／撤销和包长度／摘要／扩展清单摘要，并核同库校验策略原件及其撤销状态；手工构造同形Ref不能受理。模块核闭合字段、完整ImportIdentity及不可变意图，仅排除顶层source_attachment_id计算摘要；同身份同摘要查原，异内容冲突。历史查原不重新授予新请求资格。`queryImport`读取原状态，`cancelImport`与复制结果由同writer排序，重复取消保留原结果。库保留全部操作、事件和复制尝试，SQL禁止删除／替换历史并以外键和字段绑定约束发行及校验策略引用；最多4096个保留请求、同时2项非终态、每peer至多1项。每操作复制尝试另有1024修订开发预算，保留终止修订空间，满额拒绝且不删旧记录。

`store.validationPolicies.configure({policy_id,approval_reference})`仅供已核人员批准的可信配置入口使用，返回同库`ValidationPolicyRef`及不可变正文。正文由宿主生成，绑定当前完整Suite构建清单、Node／平台身份，以及yauzl、pend、canonicalize静态校验执行文件的实际摘要。配置者不能上传校验器路径、脚本或自报实现摘要；同ID异内容拒绝，更新制品须重新批准新的策略ID。`historical(ref)`只查原，`revoke(policyId,operationId)`永久撤销，不删除旧导入或验证记录。配置传入的批准引用仍须由生产管理入口证明其来源，本方法不凭字符串证明人员已审批。

新受理及静态验证前后在writer之外核实际部署字节，在事务内核策略、撤销及本进程绑定的实现身份；策略撤销先提交时，迟到校验不能保存成功结果。已保存报告保留历史，后续封存仍须查当前资格。部署字节变化不能在已加载旧实现的进程内重新批准；重新启动后旧策略也不能自动绑定新制品。此检查不是不可变内容根或加载器TOCTOU证明，运行包及安装配置仍要求受保护部署。当前开发库Schema增加策略记录，旧开发布局拒绝自动打开或重建，不提供隐式迁移。

`copyImport(identity, sourceFd)`只读调用者持有的regular-file描述符，不接收源路径、URL或命令。先提交copying及唯一spool引用，再异步分块写入安装根内独立文件，核实际512MiB包上限、长度、SHA256和10分钟复制窗口，文件sync／close后提交字节回执并进入validating。它不解包、不执行包内代码。调用者仍拥有源描述符；复制期间源改变以实际复制字节核验，单次stat不作为快照。取消先提交时，迟到复制结果不能覆盖；复制中agent退出后，显式重试沿原operation分配新spool并保留旧尝试，未完成文件不被当作有效包。存储结果不明进入indeterminate或关闭当前writer，不能以新请求清除旧状态。

`validateImport(identity)`读取已复制包，在持久记录验证尝试后执行两遍静态ZIP检查。控制文档由固定SDK的artifact-import入口严格解码，核清单摘要、平台、角色及文件引用；随后逐文件检查local／central一致性、路径、CRC、SHA256和实际大小，并解压到新的隔离目录。支持stored／deflate、数据描述符和ZIP64；拒绝加密、多盘、链接、路径别名、未列条目和重叠。包上限512MiB，单文件256MiB、完整库存1GiB、压缩比100及10分钟验证预算。包内代码不执行。

`prepareMaterialization(identity,{reader_sids,release_authorization_ref})`供可信安装协调者准备Windows内容根。先核原静态报告、当前同库发行与校验策略，持久记录独立准备尝试，再由专用worker复制实际库存。首次安装为新建的空`content`父目录设置显式DACL并将目录身份写入安装标记；不会自动修改既有非空内容目录。准备时检查父目录owner与有效写权限，普通主体可写则拒绝；新根、子目录和文件使用受保护DACL，SYSTEM和安装进程用户可写，显式选定的读取SID只有读／执行权限。读取主体必须来自可信安装配置，不能由扩展包决定。

原生核验保留目录与文件句柄，核FILE_ID、实际长度／SHA256、单链接、完整树及ADS，拒绝reparse、别名和额外内容；源和目标分别复核。文件逐一sync／close，结果绑定原验证记录、内容摘要、当次发行引用、实际根身份及权限策略。目录使用可继承ACE，普通文件使用无继承标志的ACE，设置后逐项回读比较；参见[Microsoft继承规则](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)与[基于句柄设置权限](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)。安装用户及宿主管理员仍属于可信管理边界，不能用此DACL隔离共享同一写入身份的worker；生产运行身份、ACL部署和加载时检查仍须验收。

准备报告的内部`storage_identity`从实际持有的内容根句柄取得卷GUID路径、文件系统、卷序列号、文件系统标志及扇区／分配单元几何，复制前后必须一致，并与根FILE_ID的卷身份绑定。字段不接受客户端自报，也不通过导入IPC暴露。卷序列号由格式化分配，不是硬盘厂商序列号；这些信息只用于后续资格匹配，不证明存储控制器、刷新支持或断电耐久，不使结果成为sealed。接口依据：[Microsoft卷信息](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew)、[句柄最终路径](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)及[分配单元几何](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdiskfreespacew)。

文件ACL设置后再次以原生写句柄执行`FlushFileBuffers`，随后在内容锁持有期间从最深子目录向上刷新内容根，最后按已持有父目录句柄的实际身份刷新父目录，再复核内容与存储身份。`metadata_flush`保存方法、顺序、文件／目录数量和父目录身份；任何打开、类型、身份或刷新错误使本次准备失败并关闭准备句柄。此路径不打开卷设备、不执行卷级刷新。`FlushFileBuffers`要求`GENERIC_WRITE`，只读目录句柄失败不能推导写句柄不可用；接口依据：[Microsoft刷新接口](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)与[目录句柄打开方式](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)。该记录证明调用完成，不证明硬件缓存、断电恢复或平台配置已验收。

准备在独立worker中运行，writer仅记录尝试和结果，查询／取消不排在文件复制之后。取消或资格失效时终止worker并等待资源回收；迟到结果不能登记为prepared。同operation最多16次准备尝试，失败或崩溃遗留目录保持独立且不自动采用，当前不提供孤儿清理入口。正常完成后`preparedArtifact(identity)`只返回持久历史与内部目录定位；相同策略重复准备查原，不重新证明此刻字节或ACL，也不为旧报告补写刷新事实。结果明确为`directory_durability=unqualified`、`sealed=false`，导入仍为validating且无intake收据。文件与目录刷新不替代掉电实验或不可变加载资格，后续封存和启动须重新核验当前实物及信任。

可信安装入口可通过`store.platformQualifications.observe(identity)`取得实际物化根的资格适用范围及摘要，再用`configure(identity,{profile_id,approval_reference,evidence_digest,scope_digest})`登记已审阅的外部平台验收批准。范围绑定本安装实例、目录及内容父目录身份、实际卷、写入SID、OS版本、Node与构建摘要、SQLite引擎及持久策略、ACL和刷新顺序；调用者不能自报这些观察字段。批准引用与证据摘要由可信配置提供，此接口不鉴定外部报告真实性，也不自动批准本机。实际验收应覆盖存储设备、驱动及缓存配置与断电恢复；这些配置变化时须撤销原资格并重新验收，卷序列号不能替代物理磁盘身份或证明硬件配置未变。

资格的`assertCurrent(identity,ref)`重新打开原内容根并固定祖先、目录及文件句柄，核原FILE_ID、卷、库存字节和逐项ACL；缺失、同名替换、额外文件或权限漂移均拒绝，不重建目录或修复ACL。`historical(ref)`仅按完整Ref查原；`revoke(profile_id,operation_id)`永久撤销，同ID不得重用为新批准，历史仍可查询。改变构建或适用范围需要新的资格。上述入口仅供可信安装装配调用，不经管理工具IPC开放；平台资格也不替代当前发行信任、校验策略或加载许可。开发版安装库继续严格绑定DDL摘要，旧布局拒绝打开，不隐式改库。

静态结果与原复制修订持久绑定，重复调用查原；取消先提交时不采用迟到结果。静态准备成功后仍为validating、receipt=null。`copiedArtifact`及`validatedArtifact`只给可信内部后续步骤提供定位和原件，不能把隔离目录或静态报告当作当前内容证明、发行授权或启动许可。

`sealImport(identity,{platform_profile_ref,release_authorization_ref})`接续已登记的内容准备。安装库先持久记录sealing尝试，独立worker重新打开原内容根、核库存和ACL，按文件／最深目录至根／父目录顺序刷新，并持有内容句柄等待writer裁决。writer再次核当前宿主信任代、校验策略、发行授权及平台资格后，在同一事务中保存核验原件、完整ArtifactIntakeReceipt和sealed状态；SQL约束绑定原操作、内容摘要及完整引用。查询和取消不排在文件工作之后，取消先提交则迟到结果不能封存，sealed先提交则取消仅返回原收据。每operation最多16次封存尝试，不执行扩展入口。

`trustEpoch()`读取安装库持久信任代，新库从1开始；可信管理入口可用`advanceTrustEpoch({expected_epoch,operation_id})`比较并推进，重复操作查原，不能下降或复用操作ID。该代独立于TUF metadata epoch，不由客户端指定或随业务恢复重置。`sealedArtifact(identity)`返回历史收据、IntakeRef及核验原件；后续实物丢失、资格撤销或信任代变化均不改写历史。存储提交结果未知时当前writer关闭使用并要求沿原identity重开查原；若账本仍为sealing且不存在sealed提交，可重新核验并提供当前发行授权续接，不复用失败尝试的intake ID。测试覆盖写入故障造成的事务回滚和续接，真实COMMIT响应丢失、断电恢复仍待验收。

sealed表示该次内容封存提交，不能代替当前可用性查询、安装批准或加载许可。安装CLI和可信时间提供者仍未实现；生产平台验收原件及实际部署资格仍须落实，合成测试批准不能用于实际安装。

`queryIntake({intake_id,target_authority_service_id})`按安装库原件定位已封存内容，重新核当前宿主信任代、校验策略、平台资格、完整库存及ACL。发行授权从原信任域／渠道／目标及部署profile内选择同包、长度和扩展清单的最新记录，再核实际当前验证会话、metadata、撤销和发行序号；缺少当前记录返回unavailable，不用其它信任域批准或历史收据替代。重开后须先恢复真实发行验证会话及当前授权。available返回原sealed收据，unavailable不带收据，均不改写历史。

`verifyMaterialization(request)`使用相同的当前实物检查，并核请求的manifest、artifact及信任代；字段不同返回mismatch，当前实物或资格不可用返回unavailable。响应回显完整请求，包括challenge和launch_intent_digest；verified带本次随机evidence_id。这个接口证明内容观察，不证明该启动意图已获安装、权限或运行批准。观察在独立worker内进行，最多四个并行观察，开发截止为4秒；查询不执行文件刷新、修复或扩展代码，期间仍可处理其它连接的取消与撤销。

观察时钟由宿主产生：`materializationClock()`给出当前安装库打开实例的描述，响应ClockRef绑定该描述摘要，重开更换domain ID。计数取[Microsoft QueryInterruptTimePrecise](https://learn.microsoft.com/en-us/windows/win32/api/realtimeapiset/nf-realtimeapiset-queryinterrupttimeprecise)并将100ns单位转为纳秒，检测回退与溢出，不使用客户端自报时间。响应的observed_tick属于该观察域；协调者必须按自己发challenge的单调时间限制窗口并核完整响应，不能直接把宿主tick当成本地年龄。句柄在本次观察完成后释放，verified不承诺后续加载时内容仍未变；监督器／加载器接线及加载前重验仍须完成。

16项测试使用真实文件库、描述符、ZIP字节和进程强停，覆盖持久幂等、取消竞态、复制恢复、验证查原及结构反例；验证前包不可读保持indeterminate，恢复文件不能清除旧状态。磁盘写入失败为注入验证。目录身份变化后当前writer锁存关闭。真实发行信任、Windows ACL部署、Linux、真实磁盘满／COMMIT未知和掉电耐久仍未验收；安装模块的局部实现不关闭阶段1或全系统交付。

### 信任元数据内部模块

`store.trust`接入独立安装库的根、元数据原字节、根转换、缓存代际和验证会话。`initialize`只供已经核验独立渠道与批准的安装入口使用；`openVerification`要求调用者提供已验证的固定时间及证据引用和受控传输。它们当前核结构并记录输入，不负责核验真实操作者、外部渠道或时间来源，不能直接暴露为网络API。每个域同时只允许一个会话，刷新只运行一次，600秒后拒绝继续；调用者必须关闭会话后才能关闭安装库。

发行资产包含明确标为`6.0.0-leafseamer.1`的tuf-js窄补丁。`tuf-inputs.json`固定官方6.0.0全部输入摘要，`scripts/build-tuf.mjs`仅补固定时间、同步持久化、根阶段缓存轮换及公开传输错误类型；验签、引用校验和委托遍历仍由上游核心执行。构建产物保存原输入、补丁和最终字节摘要及MIT许可。每个已验证根逐代提交，在线密钥发生变化时pending永久保留到最终有效根阶段；A→B→A或中途退出不能抹掉轮换。完成轮换后递增metadata_epoch，旧缓存退出当前集合，原字节仍保留。读取或提交失败使当前客户端不可再用；已提交前序角色不因后续失败回滚。

验签前检查原JSON字节容量、重复键、有限安全版本、真实UTC整秒日期及metadata引用的长度／SHA256，不重新序列化后验签。输入最大4MiB、48层、262144节点；本机profile拒绝`__proto__`、`constructor`、`prototype`键。其它未知字段保留交给上游；目标绑定只返回当前成功会话中按路径查得的数据，不接收外来TargetFile。root与稳定targets各要求独立密钥的2-of-3，snapshot／timestamp各独立单钥；合成测试密钥不代表真实独立持有人。

`createReleaseTransport`按安装配置固定metadata和target的HTTPS地址范围，执行系统CA或显式配置CA与主机名验证，不跟随重定向，不接受压缩或部分响应。元数据最多4MiB，目标最多512MiB；30秒无活动或会话600秒总期限会中止连接。`session.download(path)`仅采用本次成功会话查得的TargetFile，以SHA256前缀构造consistent-snapshot地址，先持久记录尝试和完整元数据依据，再分块写入新的staging文件。实际长度、上游TargetFile全部哈希、文件身份及sync／close完成后才提交下载回执。

`trust.downloadedArtifact(id)`是可信安装内部查原接口，返回历史绑定及隔离文件定位，不证明文件此刻未变、目录耐久或已经获得安装权限。下载失败或关闭会话时不产生成功回执，保留尝试与已接受的元数据；不能以文件存在补写成功。真实HTTPS目标字节已经通过发行验证记录、受理事务及文件描述符交接到复制和ZIP验证，相关用例的对端、管理权、安装策略和时间环境仍为合成输入。

`trust.inspectDownloadedDocument(downloadId, kind)`将已完成可信下载的`release`或`revocations`原字节交给固定SDK发行入口检查。完整发行清单采用`native-release/0.2.0-draft.1`，涵盖五仓、入口、多通道、存储及多镜像引用闭包；文档最多4MiB。首次读取核实际文件类型、长度、SHA256和安装库身份，成功后将原字节、下载依据及解码选择不可变地保存。重复调用读取原文档，隔离文件之后变动不覆盖历史，也不证明当前实物合格。本接口只保存文档检查结果，不推进发行序号、不应用撤销、不签发ReleaseAuthorization。

可信安装配置通过`trust.configureRevocations(domain, {target_path, approval_reference})`固定每个域的全局撤销路径；配置首次写入后不可覆盖，不能从待安装包取值。`session.adoptRevocations(documentId)`只采用当前成功会话下载并检查的撤销原件，重核目标长度／摘要及根授权顶层targets；局部委托不能签全域撤销。修订按精确十进制整数比较，更低拒绝，同修订要求同原字节。新快照、采用回执与新增撤销项同事务提交，跨重启或metadata_epoch轮换不清除下界；新快照省略旧项也不撤回已经记录的撤销。`lookupRevocation(domain, kind, value)`仅查询历史撤销，null不证明当前许可存在，也不授安装或启动权。

`session.authorizeExtension({release_document_id, package_download_id})`检查当前会话的完整发行原件、扩展包下载和已采用撤销快照。扩展target的受签`custom.leafseamer`使用SDK的`leafseamer.release-extension/1`绑定两层清单；完整发行原字节与C09扩展清单JCS摘要分开，归档须与所选profile中的`extension_archive`长度／摘要一致。当前入口仅接受根授权顶层targets；第三方受限委托的发行审批入口及包含完整清单自身的组合归档仍须另外实现。

成功时同事务保存发行批准与逐包验证记录，返回同库`ReleaseAuthorizationRef`。发行序号在`(trust_domain, channel, target_profile)`内精确比较，更低拒绝，同序号要求同完整manifest原字节；一个组合可以分别绑定多个包。release_id不可换内容复用，在线key轮换不重置这些记录。`trust.releaseAuthorization(ref)`只读取历史原件；新受理另核当前会话，关闭、超时或重启后旧Ref不能创建新导入。复制／静态检查完成仍不授运行权，激活前必须重新核验当前发行及安装资格。

固定上游客户端34项测试在补丁产物上通过；本项目包含13项信任传输测试和5项发行授权／受理测试，覆盖真实签名、文件库、子进程、本机HTTPS、序号／ID冲突、多包同发行、撤销及旧Ref拒绝。真实初始信任渠道、可信时间原件与下界、安装管理权配置来源、平台资格和激活前复核仍未接通或验收；当前内部发行结果不关闭正式发行或完整安装验收。

### Windows本机安装通道

`@leafseamer/suite/local-peer`在Windows x64／Node 24.22.0提供实际命名管道。可信启动器先用`captureInstallationPeer(pid)`保留预期进程句柄，再用`createInstallationChannel({name,peer,server})`建立连接；名称限定在`\\.\pipe\LeafSeamer.Install.`前缀。双方核实际管道PID、进程创建时间、主令牌SID、登录及会话身份，拒绝AppContainer、远端和错误进程。服务端使用显式受保护DACL、首实例及单实例；同SID进程的区别依赖实际进程核对，不能仅靠DACL。原生实现不使用Node私有管道字段。

可信配置入口`store.registerClient(policy)`持久保存SID、角色、目标authority范围、权限及批准引用。management_tool仅允许import.begin／query／cancel，authority仅允许intake.query，launch_coordinator允许intake.query及materialization.verify；同一SID不自动取得其它角色权限。同ID异策略拒绝，`revokeClient`永久记录撤销并关闭现有连接。角色和`approval_reference`均来自可信启动配置，客户端自报不能证明管理权或服务身份；真实peer仍按固定进程实例核验。生产启动器、人员／服务身份与批准来源及目录ACL部署仍须落实。

`@leafseamer/suite/local-import`提供`serveInstallationClient({store,registration_id,channel_id,channel,validation_policy_ref,reader_sids=[],platform_profile_ref=null})`与`createInstallationClient({channel,channel_id})`。注册ID、channel ID、固定校验策略Ref、平台资格Ref及内容读取SID由可信配置选择；平台Ref和读取身份在首次等待前复制，管理工具不能通过IMPORT_BEGIN增添SID或平台批准，默认不额外授予读取主体。服务端在同一writer事务中先核当前对端、未撤销注册、操作权限和目标范围，再查原或受理；新请求另核当前真实发行记录及宿主信任代。客户端`attach(fd)`登记已经打开的只读普通文件，得到仅限本连接的`source_attachment_id`；`begin(input)`、`query(identity)`和`cancel(identity)`走固定SDK九帧中的对应请求。省略服务端校验策略Ref时不能开始导入。Ref匹配不替代策略配置本身的批准。

附件传输使用长度前缀内的专用二进制记录：请求为标记字节0及8字节小端无符号客户端HANDLE，成功响应为字节`0,1`及36字节ASCII UUID，拒绝为`0,0`；它不增加SDK业务消息。服务端只向该连接已经固定的真实peer进程调用`DuplicateHandle`，核对象为普通磁盘文件、最大512MiB且访问权不含写入／删除／修改权限，再由Node自身libuv转为描述符。每连接最多8个未消费附件及4096次登记；句柄和附件ID不写入持久操作。客户端须保留原fd直至`attach`完成，之后可以关闭。源字节仍可能被其它持有人修改，最终以完整复制长度及摘要判定。API依据为[Microsoft句柄复制](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)、[对象访问权查询](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryobject)和[libuv描述符转换](https://docs.libuv.org/en/v1.x/fs.html#helper-functions)；对象查询不可用时拒绝附件。

开始请求先返回持久受理状态，后台依次完成复制、ZIP检查和受保护内容准备，查询／取消不等待整个任务。相同operation的重投共享同一后台任务，不再次复制或创建内容根；已有静态校验结果的原operation可继续准备，无需重传源附件。读取策略与平台Ref均绑定进行中的任务，不接受另一配置借原任务改变ACL或资格。关闭连接清理未用附件并等待已受理任务释放资源，不自动取消已受理操作；store关闭也须等待整条任务完成。准备失败保留原尝试及失败结果，可沿原operation重核，不自动删除目录。未配置平台Ref时止于validating；配置后以该资格和请求中原发行授权继续封存。发行会话更换后须由可信安装入口提供新的当前发行授权续接，不能改写原请求intent。sealed之后的query、cancel及同identity重投均返回原收据，不重新物化。

可信库装配另可调用`store.describeIntake(IntakeQuery)`：在与当前intake查询相同的实物、ACL、信任与平台检查通过后，返回完整收据引用、原manifest和FileInventory；不可用时content=null。它用于Controller持久候选内容，尚未增加网络IPC消息，不授予运行批准。

`store.describeConfigurationSchema(IntakeQuery)`在同样的当前资格检查下，只读取清单指定的configuration_schema_file_id，且该库存项必须为schema。读取沿用本次固定内容观察持有的原文件句柄，至多1MiB，不重开调用者路径；返回完整intake引用、清单／制品摘要、库存文件条目和原始bytes，返回前核长度及摘要。观察结束后句柄读取能力失效。不可用时content=null；该方法仍是可信库装配接口，不执行包内模块，不授予配置或运行批准。

`store.describeCapabilityTemplates(IntakeQuery)`沿相同的当前实物／ACL／信任／平台检查读取清单capability_template_file_ids指定的schema文件，合计至多1MiB、至多64个文件。读取使用本次观察持有的原文件句柄，返回前逐项核库存条目、长度和SHA-256，返回完整intake／清单／制品身份及文件原bytes。它仅供可信库装配，未新增网络IPC帧。Controller据此验证静态动作声明和Schema；包内模块不执行，运行目录批准仍须另行取得。

可信启动器可调用`store.acquireMaterialization(IntakeQuery)`取得有界加载交接。可用结果含冻结的完整内容原件、原生观察的root路径／FILE_ID／存储身份，以及同安装观察域的固定四秒截止；`assertCurrent()`核当前资格，`close()`与`closed`可等待实际句柄释放。独立worker持有祖先／目录／文件句柄，平台／策略／信任资格失效或截止即关闭；持有期间最多四个并发观察或交接，store关闭须先等交接结束。路径副本不是句柄或授权，接收方须在释放前核完整原件并建立自己的加载保护。该入口仅为可信同进程装配，未增加公开IPC，不签发启动许可，不执行扩展模块。

客户端另提供`queryIntake(input)`和`verifyMaterialization(input)`，分别收取INTAKE_RESULT和MATERIALIZATION_RESULT。服务端在查询前及观察期间核当前注册、peer和目标范围；客户端除核reply_to及预期消息类型，还核intake／目标及完整challenge请求回显，错绑关闭连接。管理工具不能借导入权限调用这两个服务查询。

每帧最多64KiB、双向序号连续、message ID不复用；响应必须匹配reply_to。开发预算为握手／单次读写5秒、接收队列16帧、每连接4096个业务请求。断连或丢失响应后沿原identity查原，不生成新请求猜测结果。实际Windows子进程、管道和安装库检查覆盖进程绑定、句柄交接、受理幂等、自动准备及封存、当前物化、恢复、取消与撤销。Controller原生监督器已接通这两个查询；Linux描述符传递及实际平台耐久与部署验收仍未完成。

跨仓本机联调使用`test/controller-materialization.integration.mjs`：先构建两仓，将`LEAFSEAMER_CONTROLLER_TEST_ROOT`设为Controller绝对路径，再运行`node --disallow-code-generation-from-strings --test test/controller-materialization.integration.mjs`。它使用临时安装库、真实进程与管道；合成发行／平台批准只供测试，不授予生产资格。

上游兼容检查入口为`node scripts/check-tuf-upstream.mjs <固定源码检出目录>`；先按该提交的package-lock安装测试依赖并构建。入口核对固定提交及源码未变，把该提交的客户端测试映射到本仓实际补丁产物；上游测试依赖只供本地验证，不进入Suite运行包。

旧版 [leafseamer-legacy](https://github.com/ikenainanodesu/leafseamer-legacy) 已停止维护，保留旧代码及 Git 历史。旧数据库不自动迁移，新版仅提供人工迁移建议。

新项目主许可为 [Apache-2.0](LICENSE)。从旧仓延续的设计文档保留其 MIT 声明，详见 [来源与许可说明](THIRD_PARTY_NOTICES.md)。
