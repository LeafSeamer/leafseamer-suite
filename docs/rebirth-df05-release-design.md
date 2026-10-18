# DF05：发布清单、信任根、升级与回退

日期：2026-10-17。本稿细化已确认NF03，AF01—AF06是待审阅推荐。继续先完成全系统设计，不创建发布密钥、不签名、不安装或发布制品、不修改业务实现。

依据：[NF03](rebirth-platform-freeze.md)、[DF01 SDK源与工具链](rebirth-df01-sdk-freeze.md)、[DF02可信启动](rebirth-df02-runtime-design.md)、[DF04存储恢复](rebirth-df04-storage-design.md)。本轮的可校验候选为`native-release/0.1.0-draft.1`，独立于公共draft.4／IPC 0.3；不在业务接口增加远程安装权。

## 1. 已知事实与推荐边界

**官方事实。** TUF负责可信获取更新文件，不定义安装事务，也不自动解决首次安装信任。客户端以可信初始root为起点，按版本链验证root轮换，核对后续metadata版本、期限及目标文件。TUF签名格式和规范化规则由其规范／实现负责，不能套用业务JCS替换。（来源：[TUF规范1.0.37](https://theupdateframework.github.io/specification/latest/)）

**官方事实。** Node-API不替外部动态库或私有Node/V8接口提供兼容保证；ABI可加载不等于SQLite、时钟或密码实现能力已通过。Authenticode提供Windows签名验证机制，不证明业务正确；npm provenance关联构建来源，也不证明代码安全。（来源：[Node-API](https://nodejs.org/api/n-api.html#implications-of-abi-stability)、[Microsoft加密工具](https://learn.microsoft.com/en-us/windows/win32/seccrypto/cryptography-tools)、[npm provenance](https://docs.npmjs.com/generating-provenance-statements/)）

**设计分析。** 五仓独立发版，但一个可部署组合必须有精确的组件／协议／数据库／平台绑定。摘要、发布授权、构建来源、可复现性、平台测试分别取证。任何一个verified字符串、自报签名ID或报告路径均不能单独授予安装／设备写权限。

| 编号 | 推荐方案 | 冻结边界 |
| --- | --- | --- |
| AF01 | 每个目标平台发布一个完整组合清单；文件、依赖、能力及报告全部按摘要绑定 | 明确5仓版本与可选安装子集；不允许运行时混装未验收组合 |
| AF02 | TUF作为发行metadata验证路径，Windows签名作为额外平台验证；复用成熟客户端 | tuf-js为候选，精确包／依赖锁与规范兼容性待试验；不自研签名解析器 |
| AF03 | 离线root阈值密钥、稳定targets发布审批、受限在线timestamp/snapshot，按规范逐代轮换 | 具体持有人、设备、域名及初始root指纹须在真实发布前登记；本轮不生成密钥 |
| AF04 | 安装只校验、解包、配置；运行时／原生依赖预打包，按固定路径加载并回读能力 | 缺文件／错ABI／未知引擎不得现场编译、联网补包或切换系统库 |
| AF05 | 维护期整套切换，安装日志与业务数据库分离；回退使用当前信任下明确批准的旧payload | 不降级TUF版本、不恢复旧许可、不只替换程序忽略DB |
| AF06 | 先完成格式与拒绝用例，再做独立构建、签名、两平台／容器和恢复验收 | 无真实证据不得发布稳定生产组合；合成manifest只验证结构 |

## 2. 发布单位与文件契约

一个manifest绑定一个目标profile：Windows 11 x64、Ubuntu24.04 x64 glibc或单独容器profile。容器必须固定镜像digest并另验宿主时钟／设备通道；musl、ARM64和Windows容器不能借用这些结果。清单是完整兼容组合目录，部署计划可选择其中必要组件，不能因此更换其版本或删去依赖闭包。

`release_id`是不可复用ID；`release_sequence`为1起的规范十进制字符串，按DF01大整数规则比较，不靠SemVer推断防回滚顺序。独立组件version保持各自SemVer。公共协议、IPC、bootstrap、数据库Schema与profile revision分别记录；未实现的候选协议不能伪标为已发布兼容版本。

| 字段组 | 本轮候选具体字段 |
| --- | --- |
| 身份 | manifest_schema、release_id、release_sequence、channel=preview/stable、created_at、target_profile_id |
| 组件 | components五个固定键；各含version、source_commit、source_archive_sha256、lockfile_sha256 |
| 平台 | target.os／arch／libc、tested_environment_ref、required_cpu_features、container_image_digest可空 |
| 协议与DB | protocols.public／ipc／bootstrap；db_compatibility分别列Controller/Seamer可读取／写入的精确Schema修订集合，不用含糊major兼容 |
| 运行时 | runtime.node_version／npm_version／openssl_version、artifact_path；加载后回读必须与预期一致 |
| 构建 | build.toolchain_manifest_path；该文件绑定编译器／SDK／构建镜像digest／flags／完整依赖锁／补丁／输入输出摘要及许可证 |
| 文件 | artifacts每项path、size_bytes、sha256、role、component、abi；路径是安装根内相对路径，没有下载URL或任意安装脚本 |
| ABI | abi.kind=none/node_api/node_module_abi；后两者分别只含napi_version或modules_abi，禁止两者同时声明 |
| 动态依赖 | dynamic_dependencies每项为bundled的artifact_path，或host的name／requirement／environment_report_path；宿主库不能以不验证的null hash跳过环境检查 |
| 运行能力 | capabilities.sqlite的version/source_id/compile_options_digest/expected_pragmas/report_path；argon2的reference_commit／report_path；clock的adapter_abi／backend_profile_id／report_path |
| 证明 | reports.sbom_path／license_bundle_path／acceptance_path／provenance_path；reproducibility的status、comparison_target、report_path可空 |

所有path引用必须指向清单内的相应文件；artifact path按ASCII区分存储，同时拒绝大小写折叠碰撞，以便Windows/Linux统一交付。拒绝绝对路径、`..`、反斜杠、冒号、NUL、百分号编码、尾空格／尾点和Windows保留名；解包还拒绝符号链接、硬链接、reparse point与重复目录项。首期发布包在构建时展开必要链接，不让安装器靠跟随链接写出根目录。

文件hash固定为最终发布字节的SHA-256，不用JCS摘要代替二进制hash。manifest不包含自己的digest，避免自引用；TUF targets绑定其原始字节长度与hash。归档包也作为TUF target，manifest列出归档内文件；包hash与内文件hash都校验，清单外文件拒绝。清单不引用包含自身的归档hash，避免循环；两者的关联记录在受签targets的应用元数据与部署计划中。

工具链文件和SBOM不是可执行配置。完整依赖锁须记录所有直接／传递依赖、registry integrity、下载源、确切制品与补丁，而非只记录package-lock文件名。安装阶段禁止执行npm lifecycle、postinstall、node-gyp、curl脚本或包内命令；开发者源码构建另有受控流程，不复用普通安装入口。

候选Schema位于[DF05契约资料](contracts/df05/README.md)。结构校验只确定字段形状；交叉引用／角色／路径／平台语义另验，实际字节、签名、动态依赖与能力由发布验证器和启动器验证。不得把这三层合并为一个“manifest有效”。

## 3. 信任根与批准链

推荐根角色2-of-3，稳定targets角色2-of-3，密钥分别离线保管；timestamp和snapshot使用不同的受限在线角色，不能替targets批准新程序。多个key ID必须对应不同实际密钥，重复签名不重复计数；不同介质也不等于独立管理员，需要如实记录持有与恢复职责。若项目暂时无法落实阈值管理，仅可保留候选制品，不能伪造三把独立受控密钥或跳过生产门槛。

初始root从已可信安装器／操作系统包信任或独立认证渠道取得并固定指纹；同一个未验证ZIP里的root和checksum不能彼此证明。实际发布域名、GitHub组织控制、代码签名身份和root指纹尚待登记，不能因为LeafSeamer组织已存在就假定所有外链可信。SDK包发布权限与设备运行授权也独立。

root N→N+1依规范同时满足旧root与新root阈值，逐代验证；角色轮换不可覆盖旧文件后跳过历史链。timestamp／snapshot／targets执行版本和到期核对；本项目profile进一步要求snapshot/targets相关引用都带长度及SHA-256，尽管TUF部分字段本身是可选。consistent snapshots启用，timestamp入口按客户端规范使用未加版本前缀的timestamp.json。（规范依据：[TUF客户端流程与consistent snapshots](https://theupdateframework.github.io/specification/latest/#detailed-client-workflow)）

TUF格式由受测客户端处理；不得按业务JCS重签TUF metadata，也不把自制签名数组冒充TUF。候选实现为官方[tuf-js](https://github.com/theupdateframework/tuf-js)，精确版本、转移依赖、资源限制和升级行为在隔离试验后冻结。验证器bootstrap本身由可信安装入口提供，不能先运行未验证Node包去证明该包可信。

### 3.1 到期时间与缓存

规范核验注：1.0.37的§6.3.3.4仍写timestamp带版本前缀，而客户端§5.4及§6.2.1使用无前缀入口。本方案以`timestamp.json`为入口，版本副本仅留档，并要求所选客户端互操作验证，不隐藏该表述差异。root中间链允许过期，但最终root必须晚于固定更新开始时间；timestamp/snapshot密钥轮换的缓存失效由客户端规范处理，不能沿用旧缓存跳过验证。（来源：[TUF 1.0.37](https://theupdateframework.github.io/specification/v1.0.37/index.html)）

每次更新固定一个认证时间基准；其可信性与DF03业务NTP区间分开。系统认证时间明显错误或无法满足更新profile假设时，拒绝这次更新，不自行关闭期限校验，不用manifest自报created_at校准自己，也不无限放宽过期metadata。TUF要求可信时间，有限本地持久最大时间记录只能发现部分回退，不能证明首次启动或整机快照回滚安全。

更新metadata过期阻止新的安装／升级，不因此在直播中自动停止已安装、已批准的程序。运行授权、证书、时钟与现场保护仍按各自规则处理；不得混用“更新元数据过期”和“当前命令权限到期”。获知制品被撤销或本地文件被改动时记录受影响版本并阻止新加载／新批准，现场停控按维护与保护规则，不自动黑场、静音或重启设备。

允许离线介质校验安装只表示制品可完整验证，不改变Q1不考虑断网自治的范围。介质包含所需metadata链但不能绕过过期检查；旧可信root可按规范走逐代轮换到有效新root，不能将任意过期包视为长期许可。

### 3.2 回滚保护与密钥事故

持久保存最高已接受root／metadata版本、release_sequence、撤销记录和可信渠道状态，置于安装管理域而非可被业务备份覆盖的数据库。丢失或损坏进入显式重新引导信任流程，不从“缺文件”推断首次安装。普通应用回退、业务恢复、清理缓存均不得降低这些下界。

被入侵密钥先按TUF角色撤销／轮换，发布新的metadata与受影响制品清单，再按维护操作处理已安装组合。旧targets签名仍合法不代表制品永远获准；根阈值全失或全部泄露时，必须独立可信重新引导，不能用同一失陷密钥宣告自己恢复可信。TUF与本地文件权限也不能阻止完全控制宿主管理员的攻击者，相关假设写入运行profile。

第三方模块可拥有独立发布根或限定路径的委托，但平台签名仅证明来源。安装批准、扩展权限、宿主访问和控制grant仍按Q65/Q66及DF06办理，不能因为TUF target可信就自动激活模块或扩大设备权限。

## 4. 构建与运行能力冻结

延续已有候选：Node 24精确补丁、better-sqlite3 13.0.3及其SQLite组合、Argon2、原生时钟与监督辅助程序；本稿不以网页版本直接批准下载物。生成器TypeScript 5.9.3只约束DF01生成链，不能误记成所有运行程序必须依赖TS编译器。

| 层次 | 实际取证要求 |
| --- | --- |
| 来源 | 每仓完整commit、源码归档hash、脏树拒绝／明确补丁、所有第三方版权与许可；历史来源说明不可丢 |
| 工具链 | Windows编译器／SDK／运行库，Linux编译器／glibc／链接器／镜像digest；精确flags和构建环境清单 |
| 包完整性 | 最终Node／.node／helper／JS／GUI文件长度hash，动态依赖闭包；禁止在安装时补缺 |
| ABI | 实际Node N-API能力或modules ABI匹配；OS API／CPU／libc条件单独核对 |
| SQLite | 真实sqlite_version/source_id/compile_options；每连接WAL/FULL/foreign_keys/busy_timeout/autocheckpoint回读，已知WAL缺陷修复证明 |
| Argon2 | 固定参考版本、已知答案和PHC验证、目标环境成本报告；加载成功不代替密码验收 |
| 时钟／监督 | 平台profile、DF02创建时纳管／退役、DF03年龄与误差证据；不自报一个backend ID便通过 |
| 可复现 | 两个干净构建环境对指定未签payload逐字节比较，差异保留；不能以再次下载相同包代替重建 |
| 最终签名物 | 签名／时间戳可能改变字节，未签比较目标与最终发布hash分别保存；Windows签名另核验身份、策略和时间戳 |

报告身份由manifest绑定的文件hash核验；报告内容是否满足PF14—PF18／ST／RT／TP还需独立审阅。stable组合必须具备实际平台验收及批准；reproducibility=unverified的候选保留为preview，不标正式生产可用。本轮Schema可表达该状态，但结构通过不会自动将其晋级。

## 5. 安装与升级状态机

安装管理记录至少包含operation_id、操作者／近期认证、原active_release、候选manifest digest、目标平台、选中组件／依赖闭包、安装日志revision、业务维护操作及备份引用、当前phase、错误与恢复动作。它属于Suite／本机安装管理，不向普通GUI或第三方模块开放任意文件写接口。

`requested → metadata_verified → bytes_staged → payload_verified → maintenance_confirmed → old_domain_retired → activated_protected → validated → completed`；任何步骤失败记录failed或indeterminate并保持已建立的保护，禁止凭目录存在跳到completed。

1. 验证认证时间、TUF根链／版本／期限，取得批准manifest及归档target；尚不执行包内任何代码。
2. 在受保护、唯一的新目录下载有界字节；核对归档大小hash后解析目录，再按清单解包并核验每文件。拒绝链接、设备文件、路径越界、重复／大小写碰撞、额外文件和解压后超量；临时文件失败不覆盖旧release。
3. 检查平台、CPU、依赖、ABI、协议及DB兼容计划；先有完整包再请求进入维护。错误结果返回具体缺项，不调用npm自动修复。
4. Suite确认所有受影响服务的维护状态；停止新trigger和设备写，收集在途／unknown及固定账本，保存备份与未决清单。维护不主动操纵播出设备。
5. 证明旧运行域／writer全部退役。存在unknown不等于必须丢记录或现场回滚；保留资源和暂停，新组合保护态只做核对，未解决前不开放相关动作。
6. 按DF04迁移计划处理DB，切换活动组合；[C12 DEP07](rebirth-c12-deployment-design.md)进一步推荐在独立数据generation准备迁移，由安装管理SQLite事务选择完整release／data／配置引用，不依赖symlink或通用rename作为唯一active权威。多个文件／多个库不宣称原子提交，崩溃按日志逐项核对；此细化仍待审阅。
7. 新监督域以保护态启动，核对实际文件／能力、DB与领域不变量、配对和秘密；只读健康检查通过仍不自动布防。恢复写入依新的屏障／ready／明确恢复条件。
8. 完成清单／报告并保留上一已验证组合及备份；GC只在其不再被恢复计划引用时进行。安装完成不等于现场自动化已恢复。

安装目录采用release_id独立不可变目录，数据／秘密独立目录；普通模块无写权限。固定绝对加载路径并限制DLL／动态库搜索；核验与加载间的替换风险由目录ACL、对象句柄／路径身份及平台验证处理，不能以“一分钟前算过hash”保证之后字节不变。

C12 DEP07避免覆盖被占用的活动程序路径，并给出installation.db、不可变release及独立data generation的选择顺序；Windows／Linux文件持久化、安装数据库提交、旧writer退出和容器卷切换仍须平台故障证据。无法满足时保持indeterminate，不删除旧安装以“修复”；选择记录原子不等于跨文件／设备原子，尚未完成运行验收。

## 6. 回退与升级故障

维护回退不是接受旧TUF metadata：新的、当前有效且获授权的targets／release计划可以引用已知旧payload，安装管理operation明确from/to及理由，所有信任版本下界继续递增。旧payload必须仍未被撤销、依赖完整且有兼容证据。

若旧程序能安全读写当前Schema并经过该组合验证，可在维护中切换；否则恢复配套备份并走新DB实例／control/request epoch流程，核对备份之后可能已发生的设备副作用，默认未布防。绝不自动降Schema、丢新数据、撤销floor或unknown来换取启动成功。用户数据处置属于可审阅维护计划，不在失败回调里猜测。

| 故障位置 | 恢复依据与结果 |
| --- | --- |
| 下载／校验失败 | 旧组合不变；不执行候选，隔离失败字节 |
| 维护目标未全确认 | 不切换，目标集不缩减，记录保护／超时事实 |
| 旧writer退出不明 | 不创建可写继任者；不以进程PID消失替代完整退役证据 |
| 迁移已提交而active指针未更新 | 按migration/installation身份查证，保护态选择兼容组合；不重跑副作用或直接用旧程序打开新库 |
| 指针切换结果未知 | 比较安装日志、实际目录、hash和DB版本；无法证明一致则保持保护 |
| 新包加载失败／能力不符 | 不ready；只按已验证回退计划处理，不现场编译／降ABI |
| 新组合启动成功但恢复有unknown | 安装可记录完成，相关业务保持暂停和占用，界面不显示已恢复直播 |
| 信任缓存损坏／业务备份带旧root状态 | 不降低下界，不按旧备份重建信任；显式重新引导或维护核对 |

## 7. 验收与剩余冻结事项

RA01—RA28为待执行运行／发行验收，不能由Schema正反例代替。

| 编号 | 输入／注入 | 期望 |
| --- | --- | --- |
| RA01 | 五仓精确组合及正确文件 | 匹配后才进入protected，仍不自动布防 |
| RA02 | manifest未知字段、缺组件或协议混搭 | 拒绝，不忽略兼容条件 |
| RA03 | hash/长度错、额外文件、归档错配 | 执行任何payload之前拒绝 |
| RA04 | ../绝对路径/ADS/保留名/大小写碰撞 | 拒绝写盘或加载 |
| RA05 | symlink/hardlink/reparse/解压炸弹 | 不越界，不接受超量或链接目标 |
| RA06 | 假root与包一同分发／非信任签名 | 无带外信任则不安装 |
| RA07 | root跳版本／仅旧或仅新阈值／重复签名 | 轮换拒绝，不凑阈值 |
| RA08 | 正确逐代root链含过期中间root | 按规范轮换且最终有效，不能任意跳链 |
| RA09 | timestamp/snapshot/targets过期、倒版本或混搭 | 拒绝更新，无忽略到期开关 |
| RA10 | 系统认证时间错误／固定更新时间中途改变 | 按更新profile拒绝或重启验证，不使用业务offset豁免 |
| RA11 | metadata过期但既有合法程序正运行 | 不因更新检查自动停直播；运行保护独立 |
| RA12 | root／targets密钥撤销或阈值失陷 | 新链拒绝旧授权；全失陷须带外恢复 |
| RA13 | 修改本地可信缓存／用旧业务备份回滚缓存 | 不静默降级到首次安装或旧版本 |
| RA14 | 合法维护回退到旧payload但新metadata | 保持信任版本下界，检查撤销及DB兼容 |
| RA15 | Node ABI/NAPI正确但libc/CPU/OS依赖错 | 不ready，不能只凭ABI通过 |
| RA16 | 原生文件缺失、空缓存、无编译器、禁安装联网 | 完整包可安装；缺项拒绝，不触发安装脚本 |
| RA17 | SQLite实际version/source_id/options/PRAGMA错 | 不接受网页值补齐，不进入ready |
| RA18 | Argon2向量失败或时钟profile未批准 | 对应能力不通过，不用加载成功替代 |
| RA19 | 两个干净环境重建，含签名改字节 | 未签比较与最终hash分别准确，差异不标verified |
| RA20 | 校验后文件替换／DLL搜索污染 | 路径权限／加载核对检出，拒绝启动 |
| RA21 | 模块有有效发行签名但无安装／运行批准 | 不自动激活或授予设备权限 |
| RA22 | 维护只确认部分目标或unknown仍在 | 不伪报全部停写；保留未知资源与暂停 |
| RA23 | 旧域退出失败、遗留helper仍能写 | 无可写继任者 |
| RA24 | 迁移提交与指针切换各边界崩溃 | 日志和真实字节可核对，未知保持保护 |
| RA25 | 新组合启动失败／旧程序不兼容新Schema | 不盲退程序，不丢新数据或撤销下界 |
| RA26 | 容器换镜像但旧卷schema／宿主profile不匹配 | digest正确仍拒绝不兼容组合 |
| RA27 | 在线备份或安装完成但运行未恢复 | 清晰区分安装与业务ready，不自动续跑 |
| RA28 | 断电导致安装日志／active目录不一致 | 按平台恢复协议保护，不新建空库顶替 |

本轮只交付文档、候选Schema和合成正反例，具体检查数量与输入hash见[参考报告](contracts/df05/reference-report.json)。没有真实签名验证、TUF客户端运行、归档解包、原生构建、安装、升级或设备试验。

设计未决：AF01—AF06及C12切换候选审阅；精确TUF客户端／完整依赖锁、工具链manifest内层Schema、安装记录／部署模型归并、初始信任渠道及角色保管安排。实现后证据：所有真实制品hash、签名、独立重建、运行能力、PF14—PF18及RA01—RA28／DPT01—DPT48。候选清单与合成hash不进入release-ready目录，不降低首期Windows/Linux目标或全部模块交付范围。
