# 扩展包、角色解析与本机导入候选

本目录落实[C09第17节](../../rebirth-c09-extension-design.md#17-扩展包角色解析与本机导入)。版本为`extension-artifact/0.1.0-draft.1`及`extension-import/0.1.0-draft.1`，未批准、未切换SDK权威。以下为项目推荐；参考检查只处理合成元数据和有限状态快照，没有解包、启动进程或接触设备。

## 1. 包闭包与摘要

[build_contracts.py](build_contracts.py)是唯一格式源，生成[artifact.schema.json](artifact.schema.json)及[ipc.schema.json](ipc.schema.json)。前者根拒绝实例，须选具名defs；后者根为九种本机消息联合。本地Registry只注册本目录及[安装格式](../c09-installation/installation.schema.json)，不能按外部URL联网获取Schema。Id、U20和Ref沿该候选：U20最多20位而非uint64，摘要带sha256前缀。

候选容器采用单ZIP包，根控制文件固定`extension.json`和`files.json`；分别承载Manifest及FileInventory，按严格JSON入口拒重复键和非法数字。payload均在files.json列出，控制文件不得再列入清单，不能有未声明regular file。目录仅为声明路径的父目录，不承载独立内容。包中的任意文件都不能在校验阶段import、执行或调用自检。

- `file.digest`是实际文件原字节SHA256，size_bytes是实际解压字节数；不能只信ZIP central directory或声明CRC。拒绝重复entry、local/central不一致、加密、嵌套自动解压、符号／硬链接、reparse、设备文件、ADS和重叠数据。校验器实现及解压库选型在实施时按本政策验证，本目录未执行ZIP解析。
- `files`按file_id ASCII顺序排列且file_id和path唯一。路径采用候选`portable-ascii/1`：仅相对正斜线分段，段内ASCII字母数字、点、下划线、短横线；拒绝空段、点段、尾点、保留设备名和大小写碰撞，以及文件/父目录冲突。单路径最多240字符。该限制仅适用包内文件名，不限制UI语言或文件内容。归一化前拒绝，不悄悄改名；查验实际文件系统仍须逐句柄核对。
- `inventory_digest=SHA256(JCS(files.json))`；本候选`artifact_set_digest`明确等于inventory_digest。清单不反向包含manifest摘要，消除摘要循环。`manifest_digest=SHA256(JCS(extension.json))`；`package_digest`另对整个ZIP原字节计算。相同内容不同ZIP字节可有不同package_digest，不混用这三个身份。
- Manifest固定扩展／发行者／源码版本、平台与API/IPC兼容声明、feature、entrypoints、角色和八种权限模板，以及license、dependency lock、能力模板和配置Schema的file_id。引用须在闭包内且文件role相符。入口kind/loader分别固定worker/node_module、helper/native_binary、panel/static_document，禁止任意command、路径搜索或参数插值。worker/helper须固定policy文件，panel不能声明IO policy。
- 发行授权须由宿主可信发行记录绑定package_digest、bytes、manifest和目标平台；声明publisher_id、兼容版本、role及依赖锁存在均不能自证签名、依赖闭包合法或能够运行。依赖锁及能力模板内部格式仍需与DF05/C09能力目录同版归并，不在本批偷定通用执行入口。

## 2. 可移植角色到本地权限

Manifest不携带设备实例、秘密或本机文件根ID，只声明RoleDeclaration与PermissionTemplate。管理员在当前配置修订下选定RoleBinding；由目标authority的可信提供者验证对象存在、可见性、归属、版本和用途，然后纯函数解析。模块不得参与解析，不执行包内脚本，也不允许环境变量或文本插值构造权限。

每个声明必须恰有一个同名同kind绑定，minimum≤maximum，values在基数内且无重复对象；未声明、多余、重复、缺失和未使用角色均拒绝。所有binding绑定同一ConfigurationRef。首候选角色对象全部归目标authority/database；外部服务对象先在目标服务注册为本地受控Source/Device/DataObject等，不能把远端Ref直接塞进本地角色。更换配置、对象修订、端点、profile或权限模板必须重新解析和审阅。

| 模板kind | 固定解析，不作任意对象合并 |
| --- | --- |
| device_scope | device_role多值→devices；action_ids/trigger_ids原样，至少一项用途 |
| data_scope | data_role多值→objects；access固定read或propose |
| network_endpoint | endpoint_role恰一host/port，port须在模板范围；protocol_profile_role恰一Ref，transport固定 |
| secret_role | secret_role恰一Ref，device_role/source_role各可空或多值，但至少有一个目标；不返回秘密值 |
| filesystem_root_role | filesystem_role恰一Ref；access和quota固定，不接受任意本机路径 |
| helper_artifact | helper_role及launch_policy_role各恰一Ref；可信helper记录必须绑定本包helper_file_id原字节摘要和artifact_set_digest |
| panel_method | 仅device/data_object/run角色可展开为object_refs，去重后按完整Ref的JCS字节排序；authority须与目标服务类型相符 |
| protocol_io | protocol_profile_role恰一Ref；endpoint_request_id必须指同集合network_endpoint且profile相等；frame_classes固定 |

请求按request_id排序，多值Refs按完整JCS字节排序；模板中的集合型Id数组亦要求ASCII排序、不重复。目的说明不可由绑定者改写。host必须规范IP或小写DNS，无URL/通配符；最终连接仍须核对解析地址和当前网络政策。解析产物不证明API方法存在、设备动作支持或profile获准；这些属于可信提供者检查，参考夹具不代替提供者。

RoleResolution固定authority/database/installation、manifest与artifact摘要、配置、完整绑定和最终Permission数组。`resolution_digest`对仅删除顶层同名字段后的完整JCS取SHA256；包含resolution_id，嵌套字段不删。宿主须重算权限并逐项比较，再核对权威身份，不能接受客户端自报“已解析”。相同输入的权限投影确定，记录ID不同的完整resolution摘要可以不同。

**与安装候选的修正**：旧文稿“manifest直接提供requested_permissions”细化为“manifest模板经可信宿主解析后提供”。新增ResolvedReview连接resolution_id/digest与原PermissionReview；review的配置、安装、两个内容摘要及requested_permissions必须等于该解析记录。原review摘要算法不变，新增外层关联不是原HTTP的兼容字段。下一版管理HTTP／Approval／LaunchIntent须引用这份不可变关联；本批不暗改旧14接口，也不能宣称已全链路接通。审批仍从review的收窄范围选取，不能回查宽模板。

## 3. 本机导入IPC与身份

本协议独立于设备worker的IPC0.3/面板候选0.4，不增加设备发送能力。调用者是安装管理工具和受信任authority；扩展进程、第三方面板、浏览器不能访问。客户端由受保护本机连接及当前注册证明身份，payload.client_registration_id只能回显，不能自报管理员身份。Windows句柄复制与Linux描述符传递的具体实现必须验证peer，禁止从请求路径自行open、下载URL或运行程序。

导入工具向同连接登记已打开的只读regular-file句柄，获得source_attachment_id。该ID不是路径或长期能力；重连可为同原包重新登记句柄，句柄值不进持久化记录。唯一幂等身份为`host_installation_id + client_registration_id + import_request_id`。同身份的intent摘要取ImportBegin删**顶层source_attachment_id**后的JCS；其余identity、包摘要、大小、manifest、目标、trust epoch及两个策略Ref全部保留。

先验证当前peer和目标管理权，再按完整identity查原记录；相同内容返回原operation，内容不同identity_conflict。trust epoch不另作唯一键，换epoch不能借同request ID重建导入。新请求须核当前信任、发行和容量；旧记录查询允许当前获授权人员读取历史，但旧收据不自动恢复当前运行资格。查询不可见/未知不能被解释为确认从未受理。

| 消息 | 请求或响应及权限 |
| --- | --- |
| IMPORT_BEGIN | 管理工具提交身份、attachment、包／manifest摘要、bytes、trust epoch和发行／校验策略 |
| IMPORT_QUERY / IMPORT_CANCEL | 同原ImportIdentity查询或取消，不生成新的导入身份 |
| IMPORT_STATUS | 仅响应上述三请求，返回固定operation和当前状态；sealed才有收据 |
| INTAKE_QUERY / INTAKE_RESULT | authority查询特定intake实物及当前可用性；unavailable无收据，不删除历史事实 |
| VERIFY_MATERIALIZATION / MATERIALIZATION_RESULT | 受信任启动协调者核对特定intake及启动意图；响应回显完整请求并绑定观察域／tick |
| ERROR | 只响应明确请求；无关联的协议故障关闭连接，不广播含对象信息的错误 |

信封含精确版本、channel_id、双向各自从1开始且无间隙的sequence、message_id、reply_to和payload。请求reply_to=null；响应必须非空并匹配本连接未决request ID及允许响应类型，message_id不在本连接复用。应用重试开新消息ID，但保持原ImportIdentity；断连旧response不能塞入新channel。无异步状态推送，进度由query读取。消息sequence不代替持久幂等；格式通过不证明peer可信。

## 4. 导入状态、提交顺序与恢复

正常状态为accepted→copying→validating→sealing→sealed。accepted先持久化原identity/intent及operation，才开始读源；copying写独立隔离spool并核实际包bytes/hash，源文件在复制期间变化以最终字节不匹配拒绝，不能以单次stat自称快照。validating做包／路径／逐文件闭包与当前发行信任检查。sealing只在完整校验之后进入，任何阶段不得启动入口。

installation.db为该宿主的信任／导入账本，不与业务SQLite跨库原子。推荐表与约束：import_operation主键为完整三元identity，operation_id唯一、intent不可变；artifact_set以内容摘要标识，intake以不可复用ID关联原operation；sealed必须引用完整verification记录与持久内容根。拒绝／取消记录和信任高水位不能随业务备份倒退。完整SQL迁移与磁盘实验留实施交付，不把此表描述当已运行DDL。

sealing按“隔离内容完整核验→受保护内容根物化→文件及目录耐久屏障→installation.db提交sealed/Receipt”顺序执行。只有实际平台profile的耐久证据成立才允许sealed；DB COMMIT结果未知进入indeterminate并查询原operation，不换request ID重做。文件先落地而DB未提交的孤儿保持不可执行，恢复可根据原操作重验后补完，不凭目录存在猜成功。

- accepted/copying恢复：沿同operation核对已有spool；可重新取得同包attachment继续纯静态复制，源不可得则rejected/source_unavailable。不得删除原幂等记录。
- validating/sealing恢复：核原identity、包、全部文件及当前信任；能证明无sealed提交且静态材料可重验时沿原operation继续；数据库或实物结果不明则indeterminate。indeterminate仅在权威核对得到唯一结果后回到validating、sealed、cancelled或rejected；本目录只检查给定证据，不执行恢复器。
- cancel与sealed提交由同writer排序。sealed之前取消提交→cancelled；sealed先提交→保持sealed。取消不删除共享内容、不撤既有安装批准、不停止另一个安装；未决提交不能伪装cancelled。重复取消终态只回原记录。
- sealed后的实物丢失、改变或发行撤销：原sealed历史不改写；IntakeQuery当前返回unavailable，启动核验失败，现有实例按对应撤权／故障策略关闭。不能通过重建空目录或业务恢复清掉宿主信任高水位。

MaterializationResult只证明一次观察，必须回显intake、authority、manifest、artifact、trust epoch、challenge和launch_intent_digest；错任何一项都拒绝。evidence_id、observer_domain、observed_tick由宿主提供者产生。协调者以自己发challenge的单调时间限制窗口，换域／到期拒绝，不把远端tick直接当本地年龄。verified不授启动、发送或ready；启动器load前仍需在受保护不可变根核对实物、当前信任和固定LaunchIntent。观察后替换、加载器重开路径及依赖加载竞态属于必须验证的TOCTOU边界。

## 5. 有限预算与验收

实验profile：单包512MiB、展开总量1GiB、单payload256MiB、文件最多65536、压缩比最多100、控制JSON各4MiB、IPC帧64KiB、单宿主同时导入2项／每peer 1项、静态导入总截止10分钟、物化核验响应窗口5秒。整数累计先检查溢出／上限，不以超时或磁盘不足清除已受理记录。取消／查询使用独立保留通道预算，不能排在大包复制之后；停止复制不等于删除账本。最终CPU/内存/磁盘及保护预算须与C12同版冻结，这些值不是性能承诺。

`check_contracts.py`核验生成一致性、本地Schema、合成文件清单／角色解析／摘要、幂等、回复关联、有限恢复和物化证据错绑。文件字节由人工合成映射提供，无ZIP、真实FD、TLS、权限、磁盘或安装服务。正例和变异预期写在检查器中，报告绑定本目录源及关联设计原字节；不是完整生产实现。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-artifact-import/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-artifact-import/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-artifact-import/check_contracts.py --check-report --staged
```

运行验收IAT01—IAT12见C09第17节，均未执行。当前已消除“可移植包内硬编码本机权限”和“导入无消息格式”的缺口；完整依赖／能力模板、真实可信提供者、安装review/批准/启动的同版关联、SDK／DDL和实际平台交付仍须完成，C09及阶段0不关闭。
