# DF05：发布清单、信任根、升级与回退

日期：2026-10-18。本稿细化已确认NF03，AF01—AF06及第8节具体信任方案均为待审阅推荐。继续先完成全系统设计，不创建发布密钥、不签名、不安装或发布制品、不修改业务实现。

首期采用状态以第9节为准：三人独立持有的root及稳定targets阈值方案已经确定采用；真实持有人在首次发行前落实。历史待审阅表述不重新悬置该决定，其余未明确采用项不由此批量批准。

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

持久保存root版本、当前TUF缓存代际内的metadata版本／原字节、发行序号、撤销记录和可信渠道状态，置于安装管理域而非可被业务备份覆盖的数据库。普通回退／恢复不能降低这些下界；TUF在线角色密钥合法轮换触发的缓存重置必须按第8.4节独立记录，不能用全局metadata最大值阻断规范允许的失陷恢复。丢失或损坏进入显式信任修复，不从“缺文件”推断首次安装。

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
6. 按DF04迁移计划处理DB，切换活动组合；[C12 DEP07](rebirth-c12-deployment-design.md)进一步推荐在独立数据generation准备迁移，由安装管理SQLite事务选择完整release／data／配置引用，不依赖symlink或通用rename作为唯一active权威。多个文件／多个库不宣称原子提交，崩溃按日志逐项核对；该组合选择已由C12第7、10—11节及本稿第10节采用，真实平台验证仍待实施。
7. 新监督域以保护态启动，核对实际文件／能力、DB与领域不变量、配对和秘密；只读健康检查通过仍不自动布防。恢复写入依新的屏障／ready／明确恢复条件。
8. 完成清单／报告并保留上一已验证组合及备份；GC只在其不再被恢复计划引用时进行。安装完成不等于现场自动化已恢复。

安装目录采用release_id独立不可变目录，数据／秘密独立目录；普通模块无写权限。固定绝对加载路径并限制DLL／动态库搜索；核验与加载间的替换风险由目录ACL、对象句柄／路径身份及平台验证处理，不能以“一分钟前算过hash”保证之后字节不变。

C12 DEP07避免覆盖被占用的活动程序路径，并给出installation.db、不可变release及独立data generation的选择顺序；Windows／Linux文件持久化、安装数据库提交、旧writer退出和容器卷切换仍须平台故障证据。无法满足时保持indeterminate，不删除旧安装以“修复”；选择记录原子不等于跨文件／设备原子，尚未完成运行验收。

## 6. 回退与升级故障

维护回退不是接受旧TUF metadata：新的、当前有效且获授权的targets／release计划可以引用已知旧payload，安装管理operation明确from/to及理由，root和发行序号下界保持不下降；metadata按当前TUF缓存代际校验，不能绕过第8.4节。旧payload必须仍未被撤销、依赖完整且有兼容证据。

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

设计未决：AF01—AF06及C12切换候选审阅；第8节已给初始信任、保管、时间及缓存恢复具体方案，客户端适配补丁尚未批准／实现，完整锁、工具链manifest内层Schema与安装记录归并仍待完成。实际持有人、发布身份及根指纹在首次发行登记，不虚构。实现后证据：真实制品hash、签名、独立重建、运行能力、PF14—PF18及RA／DPT。候选清单与合成hash不进入release-ready目录，不降低首期Windows/Linux目标或全部模块交付范围。

## 8. AF02／AF03／AF05具体冻结候选

本节区分官方接口事实与项目推荐。未生成密钥、未下载npm包或运行TUF；官方源码读取不等于所发布tarball已经核验。

### 8.1 固定客户端的真实边界

官方npm元数据所指tuf-js6.0.0源码提交为`c30653d07f0c41fbe5a2030d25eca6fd04f8547f`。该提交的Updater公开选项不含时间注入，TrustedMetadataStore构造时取一次`new Date()`；store未由公共index导出。loadRoot逐代验证并保存root，所读路径没有比较在线角色key集合并清除timestamp／snapshot缓存的步骤。普通metadata持久化直接调用`writeFileSync`，没有临时换名／fsync或事务回调；downloadTarget本身不刷新metadata或重验到期，只验证所给TargetFile的长度hash。不能从返回成功推导发行授权仍有效或安装数据库与文件共同耐久。（来源：[固定Updater](https://raw.githubusercontent.com/theupdateframework/tuf-js/c30653d07f0c41fbe5a2030d25eca6fd04f8547f/packages/client/src/updater.ts)、[固定Store](https://raw.githubusercontent.com/theupdateframework/tuf-js/c30653d07f0c41fbe5a2030d25eca6fd04f8547f/packages/client/src/store.ts)、[公共导出](https://raw.githubusercontent.com/theupdateframework/tuf-js/c30653d07f0c41fbe5a2030d25eca6fd04f8547f/packages/client/src/index.ts)、[本地元数据记录](contracts/toolchain/metadata-observation.json)。）

**项目推荐。** 保留成熟TUF签名／metadata验证核心，以精确上游版本加可审计的窄范围适配补丁交付；补丁限固定时间入口、metadata存储接口和规范轮换缓存状态。不访问private字段、不全局替换Date、不把源码深层导入当稳定公共API、不在外层重写验签器。补丁必须有原始源码hash、补丁hash、上游测试及本项目故障用例；发行包标识包含补丁版本，不能仍宣称与未修改npm包完全相同。上游将来具备同等接口后，以新精确版本复验替换；本轮不提交上游或生成补丁。

若审阅不接受维护该补丁，则必须重新选择满足这些接口的成熟客户端，并完成语言／制品方案评估；不能将缺口隐藏在wrapper里，也不能以现有6.0.0候选名义标记已冻结。仅添加应用侧过期检查无法自动补齐逐步持久化与轮换恢复。

### 8.2 初始信任与密钥保管

首次安装支持两个明确入口：已通过宿主包签名体系验证且发布者匹配的安装器内置初始root；或由管理员通过**既有独立认证渠道**取得验证器摘要及root指纹后，再核对下载物。两者都记录BootstrapTrustReceipt：trust_domain_id、安装身份、初始root原字节SHA-256／版本、验证器制品hash、渠道类型／证据引用、批准人及操作ID。普通下载页与同页checksum、同GitHub账号控制的两链接不算两个独立根。未知渠道进入未建立信任状态，不能仅点“信任下载包”让包自证。

| 角色 | 保管及签发推荐 | 事故边界 |
| --- | --- | --- |
| root | 2-of-3；三名可独立审阅的持有人，各自离线加密介质／专用签名环境；每人只持自己的密钥及异地加密备份 | 少于阈值泄露可由未失陷阈值轮换；阈值失陷或无法集齐有效阈值需带外重建 |
| targets | 独立于root的2-of-3密钥；每次签名前核对五仓组合、平台报告、目标长度hash和撤销清单 | CI仅产待签对象，不能调用两把离线私钥；换人不复制全套私钥 |
| snapshot／timestamp | 分开密钥及受限在线签名身份；只接收已批准metadata集合，分别轮换；发布存储无私钥 | 在线密钥不能签targets或root；受控轮换仍须保留快进攻击恢复证据 |
| 第三方委托 | 具体路径、角色、阈值与批准范围；与本平台稳定频道隔离 | 有效委托不授予设备或安装权限，不能跨路径签平台更新 |

持有人姓名、介质编号及保管位置不放公开仓库；公开材料记录角色、keyid、阈值和签名仪式摘要，私有台账记录交接与恢复测试。一个人创建三把key可测试阈值算法，但不满足三个独立持有者的生产安排；不能以preview标签绕过生产目标。设备型号／硬件密钥供应商不在本轮虚构。

候选运维期限：root365日、targets90日、snapshot7日、timestamp24小时；分别在到期前90日、30日、2日、12小时告警。期限是项目政策，非TUF强制值；续签更新版本并重新验证，不能只覆盖旧字节。失陷时不等到期再处理。root轮换演练须能使用两位有效持有人、公开连续链和离线恢复副本完成，不把“备份文件存在”当恢复成功。

### 8.3 更新专用时间与客户端接口

TUF在一个更新流程内固定开始时间，最终root及后续metadata到期必须晚于该时间；中间root允许按规范经过过期版本。（来源：[TUF1.0.37 §5.1—§5.6](https://theupdateframework.github.io/specification/v1.0.37/index.html#detailed-client-workflow)。）

**项目候选。** 首期更新按明确维护操作启动，推荐`operator_attested_utc_interval`作为独立引导方式：具有本机安装管理权限的操作者从既有可信时间来源核对UTC，声明一个包含当前真实UTC的区间。UpdateTimeAnchor保存anchor_id、方法／证据引用、操作者、安装进程时基身份、anchor_tick、utc_lower／upper、最大年龄及profile。GUI只展示本机时间供比较，勾选“看起来正确”或包内created_at不构成独立来源。该方式依赖操作者声明正确，并非机器证明精确授时；增加一次维护核对的运维代价须审阅。以后可增加已独立批准的机器时间来源，不自动采用仍待选择的DF03模型。

实验建议区间宽度最多240s、开始更新时anchor年龄小于300s、一个验证会话最多600s；本地单调经过量按已批准安装时基profile保守外推。没有该profile、发生休眠／时基变化或无法给出区间时拒绝更新。每次开始得到`[L0,U0]`，固定`reference_time_ms=ceil(U0)`注入客户端，expires必须严格大于它；此保守选择可能提前拒绝临近到期metadata。只拒绝更新，不因此停现有直播服务。

安装域保存`trusted_time_lower_floor=max(历史floor,L0)`，不能把历史U0当真实时间下界。新U0小于floor时拒绝；跨重启floor只辅助检出明显回退，不能推导经过了多少时间，更不能证明整机快照未回滚。开始时将floor与会话身份持久化；错误的大幅前跳不能通过删除记录修复，须独立时间复核和显式信任修复记录，不自动调低floor。

下载可复用已核对hash的暂存字节，但超过600s或进入实际激活前，必须使用新时间锚点／会话重新刷新metadata并核对同一目标仍获授权；不能用数小时前的固定开始时间无限延长安装许可。这属于项目激活门槛，不改变单次TUF流程中的固定时间语义。失效前已经运行的程序不因本次刷新失败被自动停止。

适配补丁的接口契约为：`fixedReferenceTime`构造输入；`loadTrusted(role)`返回安装域保存的精确原字节；`persistVerified(role,bytes,transition)`完成持久提交才返回；`finalizeRootPhase(rotationReceipt)`负责下节的缓存转换；会话输出只包含已验证metadata摘要、路径和目标绑定。输入时间必须有限、在Date可表达范围且为精确整数毫秒；TUF数值版本超出客户端安全整数范围拒绝，不改写为业务字符串再验签。Metadata本体仍由TUF规则编码，应用审计对象才使用DF01投影。

Suite门面只允许以当前成功会话内取得的目标路径／摘要调用下载，不接收模块传来的任意TargetFile；一个客户端实例只服务一个固定时间会话。另在验签前做有界原始输入限制而不重序列化：重复JSON键、非有限值和不安全／非整数版本拒绝；expires采用本项目全串UTC整秒格式`YYYY-MM-DDTHH:mm:ssZ`并检查真实日历日期及有限Date值，禁止依赖Date对非法日期的归一化。未知的合法TUF字段仍由原库保留。该限制是项目POUF候选，不能宣称未修改模型已具备；合法原字节继续交原库验签，不用业务JCS替代签名算法。补丁与外部门面分别列测试范围。

### 8.4 三种下界与逐步持久化

TUF §5.3.11规定：timestamp或snapshot密钥轮换后删除旧timestamp和snapshot缓存，用于解除fast-forward造成的锁死。这不同于用户回退程序或删除缓存文件。（来源：[TUF固定规范](https://theupdateframework.github.io/specification/v1.0.37/index.html#update-the-root-role)。）

| 对象 | 持久作用域与比较规则 |
| --- | --- |
| root | 同trust_domain逐代N+1，原字节及轮换证据追加保存；普通恢复不得降低 |
| TUF metadata | 在当前`metadata_epoch`内由完整可信metadata执行TUF版本／引用／期限检查；不是只有一个max数字 |
| release_sequence | `(trust_domain,channel,target_profile)`内保持最高已批准发行授权序号；更低拒绝，相同只准同manifest字节的幂等查询；旧payload回退须新序号授权 |
| 撤销与时间记录 | 撤销记录追加，时间floor按8.3；metadata_epoch切换不清这两类记录或业务保护 |

installation.db新增候选记录：TrustDomain、TrustedMetadata原字节BLOB及hash、RootTransition、MetadataEpoch、UpdateSession、UpdateTimeAnchor、ReleaseAuthorization、RevocationRecord。每个trust_domain只有安装管理writer可写。快照／targets引用表与缓存原字节共同保留，不能删缓存后只拿数字重建半套TUF信任。工作目录文件仅为导出副本，不能覆盖数据库权威。

每次成功验证N→N+1后，在一个SQLite事务内CAS当前root版本／hash，保存新root原字节、转换依据、是否发生在线角色key集合变化及`cache_reset_pending`，提交完成才允许客户端继续。任何提交失败／结果不明立即废弃该内存客户端实例，按operation查询持久结果，不继续使用只存在内存的新root。

最终root阶段有效后，若pending为真，另一个事务追加RotationReceipt并递增metadata_epoch，使旧timestamp／snapshot及其派生targets缓存退出可用集合，清pending；旧原字节留审计。额外失效派生缓存是项目保守策略，不是宣称TUF要求删除所有历史记录。只有已验证root链引起的变化可设置pending，普通清缓存／过期／版本过高不能触发。A→B→A发生于同链或跨崩溃时仍保留pending，不能仅比较链头与链尾就漏掉轮换。重启遇pending先完成root阶段校验，禁止旧缓存进入timestamp流程。

后续每个被验证接受的metadata也单独持久化原字节／摘要／版本与当前epoch，遵循TUF的部分进展；后续目标下载失败不回滚已接受root或metadata。验证流程只有在所有所需角色、目标字节和本项目发行授权检查完成后才给出安装可用receipt，不能把任一角色提交当整套可安装。事务只负责metadata BLOB与引用耐久，不证明下载包文件已flush，文件证据仍按C12处理。

在线密钥轮换后的新epoch可以接受低于旧epoch的timestamp／snapshot版本，但仍须完整验签和引用校验；root版本、release授权序号及撤销记录不能随之降低。没有root轮换证据的降版本一律拒绝。损坏或缺失installation.db不自动建空库；整机受控快照回滚无法仅凭同一磁盘内的记录检出，必须在部署profile明示该假设，恢复进入独立信任核对。

### 8.5 密钥事故与冻结用例

少于root阈值的泄露：隔离签名端 → 未失陷有效阈值签连续新root → 轮换相关在线／targets key → 发布当前撤销与新metadata → 客户端完成epoch转换并禁止新加载被撤销组合。targets阈值失陷但root仍可信时同样依root撤权，不让旧targets自己签“已恢复”作为唯一依据。已经发出的设备动作不受发行签名撤回，现场处置仍走C12保护流程。

root阈值失陷或足够私钥不可恢复：原trust_domain进入`rebootstrap_required`，不再从其更新链自动接受新根。通过8.2独立渠道和显式安装管理操作建立新trust_domain，记录旧域终止及迁移收据；旧审计、撤销、安装事实与业务unknown全部保留，不把新域当首次安装清空数据。跨域不直接比较无共同意义的root／release数字；迁移计划必须列新批准组合和旧撤销继承，不能利用换域安装旧恶意包。带外渠道实际控制与恢复演练是发行证据，不能由本稿自授可信。

| 新增用例 | 输入／故障 | 必须结果 |
| --- | --- | --- |
| RA29 | 未验证ZIP同时带root和checksum | 无独立BootstrapTrustReceipt，不进入可信更新 |
| RA30 | 一人持三key或同key重复签名 | 算法签名计数与独立持有人政策分别检查，不能假报2-of-3生产安排 |
| RA31 | 时间区间[1000,1240]s，expires=1240s／1241s | 前者拒绝；后者只通过时间这一项 |
| RA32 | 历史真实时间下界1000s，新区间[990,1001]／[990,999] | 前者未被floor单独否定但须当前来源；后者拒绝，不能将旧upper当floor |
| RA33 | 更新时间中途wall跳变、单调域失效或600s用尽 | 不修改固定referenceTime继续；退出会话并重新取证 |
| RA34 | 新root已提交、后续timestamp失败 | root进展保留，下次从持久root继续，不回滚到旧root |
| RA35 | 在线key变化后root提交即崩溃 | pending保留，重启先完成root阶段及epoch转换 |
| RA36 | 在线key A→B→A，两端相同 | 仍处理pending，不漏掉途中轮换 |
| RA37 | 原epoch timestamp=9000，新epoch合法新key签version=1 | 有完整轮换证据可按新epoch验证；普通降版则拒绝 |
| RA38 | metadata_epoch已换但旧release_sequence或已撤销payload | 不因TUF恢复重置应用发行授权／撤销边界 |
| RA39 | persist回调失败而内存store已更新 | 丢弃客户端实例，查原operation，不签发安装receipt |
| RA40 | 同release序号不同manifest，或低序号旧payload | 拒绝；维护回退须当前授权的新序号 |
| RA41 | root阈值失陷后同链自称新可信root | 拒绝自动恢复，显式带外新域并保留旧事实 |
| RA42 | 包下载成功但激活前授权过期／撤销 | 新会话重验失败，不切换；已运行服务不因更新失败停机 |
| RA43 | 导出缓存文件写入成功但数据库提交未知 | 按DB原字节与operation恢复，不以导出文件替代权威 |
| RA44 | 初始根恢复、时间引导及补丁上游测试／两平台故障 | 分别取得真实证据；文档用例不作验收通过 |
| RA45 | 非法日历日期、日期尾部字符、重复键、不安全版本 | 原始入口拒绝，不因Date返回无效值而绕过expiry |
| RA46 | 外部TargetFile、已结束会话或旧客户端对象再次下载 | Suite门面拒绝，不以目标hash正确代替当前发行授权 |

RA29—RA46均为计划；本轮仅核对源码、文档与离线边界算例。实施前需审阅窄适配补丁、独立持有者及人工时间引导的运维取舍，并归并上述安装记录与POUF；具体密钥、真实渠道和平台结果在发行验收交付。不得据此标记tuf-js、更新器或全系统已完成。

## 9. 首期发行信任采用状态

### 9.1 阈值持有与首次发行边界

2026-10-28首期确定采用第8.2节的三人独立持有方案：root为2-of-3，稳定targets为独立于root的另一组2-of-3密钥，三名持有人分别只保管各自角色密钥及加密备份；同一组三名人员可以分别承担两个角色，但两套密钥不复用。snapshot与timestamp继续使用彼此分离的受限在线密钥。首次真实发行前落实身份、交接与恢复职责，不在公开仓库登记姓名、介质或保管地点。

该决定关闭C12关于单维护者或三人阈值的运维取舍，不以虚构持有人或一人生成三把key满足它。缺少实际持有人时可以完成源码、构建、集成和合成发行验收，但不能标记正式发行已获授权。TUF key与DF06的部署CA、运行TLS及SecretStore主密钥分别管理，三个不同信任用途不能互相签发或自动导入。

第8.1节固定TUF客户端加窄适配补丁作为实施路线：只补时间输入、逐步持久化与规范缓存轮换接口，复用原验证核心。补丁编写、完整锁、上游与故障测试、真实制品及签名演练列入实施／验收，不再把“尚无补丁代码”当成选择路线尚未成文。若实施发现固定上游无法满足这些接口，必须指出具体失败并重新裁决，不能改成隐藏private字段访问或自行验签。

人工时间引导的运维采用决定与运行认证时钟profile分别记录；本节的阈值决定不代替它们。没有当前有效时间证据时更新拒绝，已有运行不因更新失败自动停止。首次安装独立渠道和阈值失陷带外重建沿8.2／8.5，渠道实际控制、持有人与两平台恢复证明仍属于发行前证据，不要求先取得它们才能编写产品。

## 10. 首期发行、通道与部署组合映射

本节固定C12整体发行映射，沿第9节已采用的三人阈值与TUF窄适配路线。第8.3节人工发行时间方式仍等待独立决定，本节不授予更新时间、真实签名或安装权限。源码生成、合成构建与验收可继续；真实发行持有人、发布渠道及时间证据必须在适用发行操作前取得。

### 10.1 旧清单与下一版差集

当前[清单Schema](contracts/df05/release-manifest.schema.json)仍是native-release/0.1.0-draft.1：protocols仅public／ipc／bootstrap，db_compatibility仅controller／seamer，capabilities.sqlite固定WAL／FULL，target只有一个可空container_image_digest，runtime只有一个Node条目。它不能完整描述当前已定的独立通道、监督journal或多镜像组合；结构通过不代表可安装首期产品。旧Schema及其报告保持原版本，以下字段在产品SDK生成时形成新清单版本，不给旧格式增加宽松未知字段。

| 新版字段／绑定 | 必需内容与约束 | 取代的歧义 |
| --- | --- | --- |
| component_bindings | 保留五仓version／完整commit／来源归档／锁摘要；每组件列entrypoints、artifact_refs及requires组件集合；无运行入口的SDK仍以生成制品参与依赖 | 五仓组合身份不等于五个必须启动的进程；选择子集仍必须满足完整依赖闭包 |
| protocol_bindings | 每项channel_id、完整契约ID／digest、schema_artifact_ref、端点角色、方向及使用组件；HTTP／人员WS／服务WS绑定同一完整selection，独立通道分别绑定原件 | 不从三个版本字符串推导所有通道兼容，不用SemVer major代替选择摘要 |
| storage_bindings | owner_role、store_kind、schema_id、精确read/write revisions、engine_ref、connection_profile_ref、migration_refs和验收报告；同schema_id才可比较修订 | 不把不同库的revision=1当同格式，不把监督或安装库遗漏于兼容检查 |
| runtime_bindings | runtime_id、kind、精确版本／制品／ABI／平台和使用组件；Node、原生helper及可选外部运行时分别列出 | NodeCG或Go helper不继承业务Node条目的ABI；构建工具不是必须启动的运行时 |
| container_bindings | 每项image_id、image_archive_ref、config_digest、有序rootfs_diff_ids、平台、对应entrypoint、使用组件、容器环境报告；registry_manifest_digest仅在确实取得该原件时登记 | 镜像身份、导出归档hash及仓库manifest摘要分别绑定；一个字段不能代表多个服务镜像 |
| deployment_profiles | profile_id、所需组件／入口／协议／存储／容器绑定、可选能力、宿主前提及所需报告；引用全部在本清单或显式受信外部依赖中闭合 | 按profile判断可部署集合，不因某单组件可加载放行整个组合 |

这些数组按各自ID唯一；引用须指向清单内具名artifact及其最终字节hash。制品／运行入口的依赖无环，服务间双向通信关系另按通道边记录，不作为相互安装依赖；所有被选入口的传递依赖、协议和存储绑定必须齐全；同一入口不能绑定两套活跃公共selection。通道端点逐对匹配角色、方向、ID及digest；已有独立bootstrap／监督／设备／授时／导入／面板，以及新增source-worker／VLC／maintenance-local均按DF01第15节各自归属，不拼成通用消息联合。VLC辅助插件在外部OBS进程中运行，其本机插件制品及OBS平台兼容报告单列，不伪造为Controller内置设备worker。

artifact的role新增明确image_archive、protocol_schema、configuration_template和migration等交付类别；模板及迁移文件只交受信安装器的固定入口处理，不提供任意包内脚本执行。动态依赖仍须bundled完整字节或明确host前提及环境报告；宿主前提不成立时预检拒绝，安装器不下载“latest”补齐。完整清单自身由TUF target的长度／hash绑定，归档与manifest仍沿第2节无环关联；运行profile、报告或协议制品不得反向嵌入最终manifest hash造成摘要环。

### 10.2 存储与兼容判定

| store_kind／权威 | 首期连接profile | 兼容、备份与恢复边界 |
| --- | --- | --- |
| controller_business／目标Controller，seamer_business／Seamer | DF04固定WAL／FULL，每连接foreign_keys=ON、busy_timeout=0、wal_autocheckpoint=0及领域要求的触发器配置 | 各库独立scope与Schema；同组件读写集合分别核对，实际迁移脚本和from/to摘要明确；不将读兼容当可写 |
| supervisor_journal／独立监督器 | DF02第12节固定DELETE／EXTRA，单writer；外键／触发器等按实际具名布局回读 | journal_schema独立，不能用业务WAL报告证明；启动／退役原件与旧域保持关联 |
| installation／Suite本机agent | DF04第19节固定WAL／FULL及单writer | 不随业务备份回退；旧agent／helper退役后由受信引导入口执行具名安装库迁移，trust／release／time下界保持，失败不得新建空库 |
| nodecg_data／可选NodeCG | 使用所选NodeCG发行的真实持久化格式和专用备份提供者 | 不宣称是业务SQLite；固定版本／插件／数据格式及恢复兼容，缺少恢复证据时归档覆盖明确缺项 |

SQLite engine_ref绑定实际二进制、version／source_id／compile_options及驱动；同一引擎可供不同profile使用，但验收逐连接验证实际设置。Supervisor与installation迁移程序不得由设备模块或普通业务请求执行。首次产品库从最终Schema创建，旧离线候选库不自动升级为可执行业务库；后续业务升级按DF04第24节在新data generation内完成。

跨主机部署不要求所有主机同OS或同release_id；每个主机使用对应已批准manifest，连接两端仍必须拥有同一完整公共selection和对应独立通道绑定。没有共同选择则拒绝连接，不默认回退旧协议或自动缩减能力。跨主机预检结果只形成兼容报告，不能证明远端仍有权限、旧writer已退役或全部主机已原子切换。

### 10.3 Compose镜像的字节与运行身份

官方格式中，ImageID由配置JSON的SHA-256确定，配置包含有序rootfs.diff_ids；DiffID是未压缩层内容摘要，不能与分发层或整个导出包hash混同。Docker load从归档恢复镜像及标签，load成功不代表项目计划已经验证通过。（来源：[OCI Image Configuration v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/config.md)、[Docker image load](https://docs.docker.com/reference/cli/docker/image/load/)。）

首期Compose发行采用已签清单列出的单平台镜像归档：外层发布包按原路径规则解包；image_archive是完整受hash约束的独立payload，不把其内部层文件当宿主安装根文件展开，也不以宿主包的“无链接”规则宣称普通Linux镜像层不可含符号链接。受信宿主agent先验证归档字节及声明平台／配置／有序层绑定，再通过固定引擎入口导入；导入后读取引擎实际ImageID／平台／RootFS并与清单相等，记录导入回执。归档只允许本发行声明的镜像与标签集合；标签不得覆盖指向不同身份的既有安装标签。

启动以已核验的不可变ImageID关联实际container ID，标签仅供显示，不作为启动权威；生成计划禁止自动pull和无限restart。镜像缺失或身份不符明确失败，不按标签拉取替代物。registry_manifest_digest不能从ImageID或归档hash猜造；如果将来采用仓库分发，应另验证真实manifest及其选择平台，而不是增加一个自报字符串。引擎／Compose精确版本、导入／inspect能力、宿主组证明与相应环境报告属于该profile完整锁和平台验收，当前未运行Docker导入或容器启动。

### 10.4 完成边界

Suite负责生成发行／部署闭包、受信验证与安装工具，SDK生成新版具名清单和校验器，各产品提供实际入口／协议／数据兼容声明及运行报告。构建锁、最终hash、镜像归档、签名和平台报告由真实构建产生，不能在设计阶段填写虚构值；平台组合不满足已有发布门槛只能保留未就绪状态。

本节关闭C12的发行组合、独立通道、存储和多镜像映射缺口；第8.3节发行时间的运维选择仍独立待决定。沿A20／A22及DPT增加验收：缺依赖、同ID错摘要、不同库同revision混用、读兼容却需写、错PRAGMA报告、只换一服务镜像、tag漂移、导入半成功、安装库迁移未知、跨主机选择不同，以及已激活后回退丢失新账本。当前只核验固定Schema与上述官方格式来源，不声明产品打包、签名、安装、容器或恢复成功。
