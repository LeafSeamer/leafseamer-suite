# DF04：SQLite 表契约、事务与恢复设计

2026-10-27最新存储交接：[SDK局部持久化与正文成果](contracts/sdk-wire-handoff/README.md)固定5表owner恢复journal、6表快照消费者及3表增量投影写集，并关联已有7表注册存储。各表属于局部参考边界，不能简单相加为生产数据库。Windows同机排他及2次子进程强杀已有证据，Linux、掉电、生产迁移及备份恢复未验。最终释放门已有排序参考，完整owner／Context／票据／发送映射／ACK／pin、规范摄取与执行的生产DDL仍须统一；历史“进程崩溃未验”只适用于原注册存储报告。

上一注册存储交接的历史状态：[固定SDK写集交接](contracts/sdk-scope-handoff/README.md)提供7表局部DDL和226项检查，包括40条逐写入故障、DELETE／WAL双连接、提交观察丢失与关闭重开。对象／墓碑、操作、审计、通知、封存通过双向延迟外键同提交，固定启动authority，禁止覆盖及删除。其结果不代表完整生产库或迁移已交付；owner／Context／票据／订阅代际／发送映射／ACK与pin仍须归并。WAL旧读反例保留，新writer读取不是最终释放门，进程崩溃和断电未验。

2026-10-21时间子域更新：[十四表存储候选](contracts/df03-collector/STORAGE.md)落实reference-bound/1原件、采样裁决、锚点/State及失效通知的同库写集和恢复规则，215项内存检查通过。它覆盖本机时间发布/失效，不替代既有业务库或TIME设备屏障布局；精确加密提供者、完整库组合、STOP/容量/GC及真实耐久验收仍未完成。后文历史时间字段以该新候选的显式映射为准，旧机器文件不改。

日期：2026-10-17。本稿细化已确认的 F02/F03、F04/F05、F06/F07 与 draft.4，DB01—DB06为待审阅推荐，不视为用户已同意。当前继续完成全系统设计，不迁移业务库、不启动服务、不修改业务实现。

范围为首闭环及其安全依赖的存储契约；完整厂商配置、排期导入和GUI模型随各专题补齐。下列逻辑表不是已发布迁移脚本，SQL参考资料只验证若干约束行为，不能代替完整建库、驱动、WAL或故障验收。关联：[F02/F03](rebirth-f02-f03-design.md)、[F04/F05](rebirth-f04-f05-design.md)、[F06/F07](rebirth-f06-f07-design.md)、[DF01](rebirth-df01-sdk-freeze.md)、[DF02](rebirth-df02-runtime-design.md)、[DF03](rebirth-df03-time-profile-design.md)。

## 1. 官方事实与推荐

**官方事实。** SQLite INTEGER是有符号64位；NUMERIC affinity可将超界整数文本转成REAL，STRICT也允许无损类型转换。STRICT不能替代SDK的原始JSON词法校验。（来源：[数据类型](https://www.sqlite.org/datatype3.html)、[STRICT](https://www.sqlite.org/stricttables.html)）

**官方事实。** WAL＋FULL在提交时同步WAL，但仍依赖VFS／存储正确实现；WAL多文件即使ATTACH也不是跨库原子事务。官方已披露WAL-reset修复，产品实际引擎须包含修复，不能只锁定绑定包。（来源：[synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous)、[WAL与修复说明](https://www.sqlite.org/wal.html)）

**官方事实。** 外键需每连接在事务外启用；RETURNING不证明COMMIT成功。BUSY_SNAPSHOT需要结束旧快照重新判定；COMMIT BUSY时事务可能仍活跃，其他存储错误也不能统一当作已经回滚。（来源：[外键](https://www.sqlite.org/foreignkeys.html#fk_enable)、[RETURNING](https://www.sqlite.org/lang_returning.html)、[隔离](https://www.sqlite.org/isolation.html)、[事务](https://www.sqlite.org/lang_transaction.html)）

**设计推荐。** 保持Controller／Seamer各一本地关键库、单writer队列、短事务及独立保护通道；明确持久事实与当前运行资格分离。以下表结构和算法是基于已确认不变量的设计，不是平台运行结论。

| 编号 | 推荐 | 冻结条件 |
| --- | --- | --- |
| DB01 | 公共大整数用规范十进制TEXT；快照保留原协议字节，查询投影不得改写摘要 | 与DF01下一版词法修订一起审阅，禁止暗缩draft.4接受范围 |
| DB02 | 每个库内部用外键、唯一约束及CAS固化身份；终态、资源释放、写闸ready分离 | 表字典与完整DDL生成须逐项等价；无跨库FK或跨服务原子承诺 |
| DB03 | T1—T8与R1—R5保留编号，审计／事件／事务凭据同事务；设备派发不放重传outbox | 有限重试只处理存储，最终设备发送仍按唯一出口 |
| DB04 | 普通重启关闭旧运行资格，备份恢复更换控制／请求世代；保留unknown和人工限制 | SQLite结构检查与领域恢复检查分别通过 |
| DB05 | 引用感知保留、幂等墓碑、关闭上下文与固定事件游标共同防重放 | 容量阈值待实测；不得为腾空间删除未决证据 |
| DB06 | 备份完成、升级维护与恢复发布逐步记账，首期不在线变更Schema | 固定引擎／驱动、故障、负载与两平台证据齐全 |

## 2. 类型、身份与不可变内容

所有业务权威表使用STRICT，主键显式NOT NULL，文本比较使用BINARY；跨表标识均复合绑定所属service／主体／设备／命令，不能只碰巧匹配一个ID。拒绝INSERT OR REPLACE及任意覆盖旧证据；参数绑定，不拼接用户SQL。

| 简写 | 物理表示与规则 |
| --- | --- |
| ID／H | TEXT；分别按固定SDK Id／Digest验证。所有不透明身份不可复用，区分大小写，不做Unicode规范化 |
| U20 | TEXT，0或无前导零的十进制，最多20位；最大99999999999999999999，不是uint64 |
| U24／S25 | TEXT；NF纳秒范围按对应SDK版本；原始有符号-0不静默改为0，后续词法收窄须另版批准 |
| SMALL | INTEGER，仅用于已证明范围的计数／布尔／索引；布尔CHECK IN(0,1)；不承担公共无限递增游标 |
| UTC | 固定协议时间戳TEXT或范围可证的安全整数毫秒；审计排序仍依事务／事件序号，不依赖UTC不回跳 |
| BODY | 不可变UTF-8字节BLOB、schema_version、具名投影digest；原始wire与JCS摘要输入分别存，禁止“重序列化后当原报文” |
| REF | 同库明确表的外键；远端引用另带service_id、对象种类、ID／revision／digest和验证记录，不伪装同库FK |

U20范围比较采用 `(length(a), a COLLATE BINARY)` 与 `(length(b), b COLLATE BINARY)`；可建表达式索引。CAS只做精确文本等值。递增在已验证的BigInt中计算，并在原事务内CAS写回；禁止SQL `revision+1`、CAST AS INTEGER、REAL或Number中转。溢出进入保护／维护，不环绕、不擅自换epoch躲过旧身份。

新存储profile建议严格拒绝尾部LF、NUL、空白、指数、正号和前导零。draft.4正则存在已登记的尾部LF／-0接受差异，本轮不声称它们已修复：新活跃存储profile须随下一协议修订启用；旧材料原字节归档，不能偷偷规范化再作为新权威记录。STRICT可能把整数9转为TEXT '9'，因此SDK／绑定层必须证明传入值原本就是正确字符串。

BODY与查询列的权威关系：快照字段不可变，查询列为其受校验的投影；生命周期当前值由专门可变表负责。一次writer事务验证版本、摘要和投影一致后写入。启动核对若发现两者冲突则保护，不能任选一个继续。SQL不实现JCS、签名或授权来源验证。

## 3. 共用基础与身份表字典

表名在两个独立库中可相同，记录归属不相同；只存该服务权威记录及明确标注的远端镜像。下表列出关键列，未列出的公共DTO字段完整保留在版本化BODY中；这不授权实现自行遗漏DTO或随意增加权威字段。

本节`request_identity`保留draft.4历史字典。新命令裁决采用第17节的RequestKey：scope、issuer/epoch/principal、request_epoch、固定createCommand及idempotency_key，**不含context_id或digest**。其他操作不能未经各自契约审阅套用该键；旧表与新候选不混用，也不把旧字典当成已迁移。

| 表 | 主键／核心列 | 必需约束与索引 |
| --- | --- | --- |
| service_state | service_id；database_instance_id、control_epoch、request_epoch、schema_revision、maintenance_state、state_revision | 单库唯一service；epoch变更带恢复／维护操作引用；DB文件缺失不得自动创建新实例 |
| schema_migration | migration_id；from/to_revision、script_digest、backup_ref、state、tx_id | 版本链单调；摘要不变；失败／未知迁移阻止运行 |
| transaction_receipt | tx_id；kind、business_id、request_digest、result_ref、commit_sequence U20 | UNIQUE(kind,business_id)；与相应业务状态同事务，行存在不单独证明外部副作用 |
| subject | local_subject_id；issuer_id、issuer_epoch、principal_id、kind | UNIQUE(issuer_id,issuer_epoch,principal_id)；holder只引用本地subject，不复用已删除主体ID |
| request_context | context_id；service_id、完整principal三元组、context_epoch、audience、有效窗口、max_unique_requests、used_count、state | 复合UNIQUE供identity外键；epoch／主体不可变；关闭后不可重新开放 |
| request_identity | identity_id；RequestIdentity全部8字段、content_digest、operation_result_ref、state | UNIQUE(service_id,issuer_id,issuer_epoch,principal_id,context_epoch,context_id,operation,idempotency_key)；复合FK核对context归属；closed/tombstone仍拒新执行 |
| capacity_reservation | reservation_id；owner_kind/id、profile_ref、dimensions BODY、state、revision | 与T1／控制操作受理同事务；完成证据预算不得提前释放；owner索引 |
| audit_event | audit_id；tx_id、actor_ref、event_kind、object_ref、sequence、redacted BODY | 关键审计同事务；无令牌／明文秘密；时间戳非唯一排序依据 |
| event_outbox | event_id；stream_id、stream_epoch、sequence U20、kind、payload_digest/BODY、tx_id | UNIQUE(stream_id,stream_epoch,sequence)；只放通知，不放DISPATCH或设备写任务；payload不可变 |
| delivery_cursor | (subscriber_id,stream_id,stream_epoch)；ack_sequence、revision、state | 不跨epoch继续；ACK推进CAS；对未知／过旧游标返回失步，不从尾部假装无丢失 |
| trust_pairing | pairing_id；peer_service_id、issuer/epoch、指纹、范围、revision、state | 配对两端状态分别记录；不以对端自报active代替本地批准 |
| credential／auth_session／run_grant | 各自ID；subject_ref、revision、有效期、scope或grant BODY、state | 各自独立表；credential只保存验证材料／秘密引用；session与组织grant不可混撤 |
| authorization_floor | (kind,issuer_id,issuer_epoch,target_id)；revision_floor、permanent_disabled、operation_ref | U20按数值单调上升；credential/trust的永久禁用不可被新revision解除 |
| revocation_operation | operation_id；selector BODY、issuer_commit_revision、state、request_identity_ref | 固定目标集不可因离线缩减；同身份只生成一个操作 |
| revocation_target | (operation_id,target_service_id)；状态、receipt BODY/digest、target_boot、barrier_ref | FK operation；覆盖完整且逐项可靠后才能applied |
| one_time_credential | token_id；kind=first_admin/pairing/ws、verifier、主体/Origin/权限绑定、expires、consumed_tx_id | 不保存可重用明文；消费与本地状态变更同事务；重启策略按类型失效，WS票据不跨服务boot复活 |

token_id只是查找身份，不能充当秘密。first_admin指首次管理员初始化，不是DF02进程bootstrap；后者短期secret仍只留受限通道／内存，不落库。单次票据消费成功后进程崩溃可造成未升级连接，票据仍已消费；客户端重新取得新票据，不回滚消费。近期认证、认证时钟、秘密加密及权限生命周期细节继续以C07／DF06为准，不用表字段代替真实鉴权。

## 4. Controller执行、屏障与证据

| 表 | 主键／核心列 | 必需约束与索引 |
| --- | --- | --- |
| runtime_domain | domain_id；descriptor_digest/BODY、supervisor_instance_id、state、retirement_ref | 不可变descriptor；同一服务只有一个可接收新工作的域；历史域保留只读 |
| process_launch | launch_id；domain_ref、intent_digest/BODY、role、制品、OS组实例、admission/retirement记录 | UNIQUE启动通道身份；秘密不落库；spawn前有持久intent；新进程不能继承旧准入 |
| device_control | device_id；epoch、version U20、holder_ref、mode、gate_revision、pending_operation_id、revision | CAS预期epoch/version；人工持有人离线不自动释放；device主键唯一 |
| control_operation | operation_id；device_id、identity_ref、expected/target控制版本、state、final_barrier_id | device上pending/indeterminate操作至多一个，除非显式完成替代审计；effective只绑定可靠最终尝试 |
| barrier_attempt | barrier_id；operation_id、kind=control/auth/time/recovery、设备与域/session、cut_revision、ledger_digest、state | 同操作可多attempt，新barrier_id；旧ACK不可覆盖新attempt；device/operation索引 |
| barrier_member | (barrier_id,permit_id)；intent/command/attempt及原身份、guard摘要 | 保存切点完整成员；复合FK绑定原intent；不可因后到完成而删除成员 |
| barrier_coverage | (barrier_id,permit_id)；disposition、proof、ACK引用 | 复合FK→member，防止额外成员；FK本身不证明无遗漏，事务另核对集合完全相等 |
| gate_installation | installation_id；device、domain、controller/worker_boot、IPC/设备session、gate_revision/token、barrier、状态、lease | 历史可留；当前ready只允许精确当前身份，T5提交后发布；重启全部退出可用集 |
| command | command_id；identity_ref、request BODY/digest、device/action/catalog、revision、phase/outcome、effect/resource状态、暂停锁存 | identity UNIQUE；phase finished iff outcome非pending；finished后phase/outcome不可改；device/phase及identity查询索引 |
| attempt | attempt_id；command_id、attempt_no、domain、worker/session、原截止、outcome | UNIQUE(command_id,attempt_no)，attempt_no限既有策略；UNIQUE(attempt_id,command_id)供复合FK |
| dispatch_intent | intent_id；attempt_id、command_id、permit_id、guard_id、issued_revision、permit/请求/窗口 BODY、会话与域 | UNIQUE(attempt_id)、UNIQUE(permit_id)、UNIQUE(guard_id)；复合FK attempt/command；全部不可变；设备未核销索引 |
| intent_adjudication | intent_id；classification、report/evidence_ref、revision、accounting_state | 发送判定与原intent分开；无报告不是not_sent；核销不等于资源释放 |
| resource_claim | (command_id,resource_key)；device、冲突模型revision、state=queued/active/retired | T1保存排队需求，T2才提升活跃占用；多个queued需求不代表多个可写所有者 |
| resource_hold | hold_id；device、command、resource_key、state=held/unresolved/released、release_evidence_ref | 首期整设备冲突，device上held/unresolved至多一条活跃hold；released保存历史，未知无证据不可清理 |
| report_receipt | (worker_boot_id,ipc_session_id,report_id)；digest、intent_ref、tx_id、record_revision | 同ID同内容返回原结果；不同内容协议错误；绑定发送者，不以全局report_id碰撞串账 |
| evidence | evidence_id；kind、command/attempt、domain/session、policy/version、BODY/digest、tx_id | 来源／类型／归属复合校验；只追加，明确completion/release/resolution不同种类 |
| command_evidence | (command_id,evidence_id,usage)；record_revision | FK及证据归属一致；资源clear须合法release，unknown+clear还需resolution |

首期whole-device活跃hold唯一约束只是粗粒度资源保护；未来Q35拆通道时必须替换成已审阅的重叠模型，不能简单删除索引让冲突漏过。T1排队claim与T2活跃hold拆开，避免第一条queued请求永久占用设备，也避免用UNIQUE(resource_key,command_id)假装阻止不同命令冲突。

command终态保护只冻结phase/outcome，不禁止revision增长、追加resolution或根据有效释放证据更新resource_status。成功且完成级别仅sent仍可能占资源；unknown获得释放证据仍是unknown。Schema约束、数据库约束、证据来源与领域判定共同成立才发布结果。

## 5. Seamer状态、输入与恢复

| 表 | 主键／核心列 | 必需约束与索引 |
| --- | --- | --- |
| definition_version | (definition_id,version)；BODY/content_digest、DSL版本、绑定快照 | 发布版不可变；新版本不替换已受理执行 |
| independence_proof | (proof_id,proof_revision)；definition_ref、bindings_digest、分析器版本、BODY | 定义／目录／模块绑定精确；旧证明仅历史，不能依赖自报independent |
| business_state | machine_id；state_id、revision、definition_ref、last_transition_id | 源状态／revision／active_execution三者CAS，不用设备当前画面直接覆盖业务状态 |
| run | run_id；definition_ref、run_revision、arm_generation、active_execution_id、state、暂停锁存、authorization_ref | 新恢复CAS；控制／撤权等锁存不因设备成功自动清除 |
| execution | execution_id；run_id、kind、generation、plan_digest、state、source_execution_id | run中至多一个活跃执行；恢复创建新ID，旧执行不重开 |
| step_execution | (execution_id,step_id)；固定参数／绑定、状态、required、command_link、证据引用 | 不以(run_id,step_id)覆盖多轮执行；每个动作执行身份固定 |
| command_link | link_id；execution/step、controller_id、command_id、request_identity、观察revision、证据引用 | 远端ID不做本地command FK；同一绑定唯一；只按已验证远端记录更新 |
| event_source_state | (provider_id,provider_boot_id,stream_id)；sequence下界、sync_state、revision | 缺口／换boot进入失步；快照不补造离散事件 |
| trigger_inbox | (provider_id,provider_boot_id,event_id)；source_sequence、digest/BODY、decision_ref | 源sequence另UNIQUE；同ID异内容拒绝，同sequence异事件视协议故障 |
| trigger_decision | decision_id；inbox_ref、definition_ref、规则版本、结果／原因、execution_id | 去重受理、决策与execution创建同事务；过期或失步明确记录，不静默删后重触发 |
| schedule_version | (schedule_id,version)；source/binding/definition、内容摘要、状态 | 导入版本不可变；激活指针CAS；详细导入字段由C06专题补齐 |
| schedule_occurrence | occurrence_id；schedule_ref、稳定逻辑场次键、窗口、qualification_latch、execution_ref、终结原因 | 版本变化不重放已消费逻辑场次；窗口内曾失去资格仍锁存，不补发；跨版本场次身份由排期专题明确 |
| recovery_preview | preview_id；run/revision、domain/boot/request_epoch、BODY/digest、plan BODY/digest、expires、consumed_operation_id | preview不可变；消费从null单次CAS；旧域或过期不消费 |
| recovery_operation | operation_id；identity_ref、run_id、preview_id、baseline/target修订、新execution、状态 | identity与preview各UNIQUE；run至多一个active recovery；暂停／未知旧操作必须登记保护核对后才能建立新操作 |
| recovery_target | (operation_id,controller_id)；baseline→target完整绑定、state、receipt/digest | 目标集固定；applied须可靠receipt；新接管不吸收成预期变化 |
| transition_commit | transition_id；execution_id、machine_id、source/target状态修订、证据集合、tx_id | 状态转换execution_id唯一，(machine_id,target_revision)唯一；与business_state、运行结果、审计及outbox同事务 |

暂停／indeterminate的恢复操作不由partial UNIQUE自动判断“可新建”：事务必须核对准备过的目标、未决写及撤销状态，满足F07后才释放该run的恢复锁；不以把旧state改为paused绕过单活跃约束。预览保持已消费，重试同幂等身份只查旧操作。

时间附属记录按DF03分表：time_profile_revision主键(profile_id,revision)不可变；time_profile_approval主键approval_id并按authority_revision有序；time_capture/capture_id、time_evidence/evidence_id及clock_sample/sample_id保存相互REF、BODY和摘要；time_current以provider_id为主键指当前域／boot／generation／policy／批准修订及样本。提交当前指针CAS所有这些版本，历史样本存在不等于可用。原始大附件另存受保护对象，先完成并核验对象，再提交引用；对象孤儿可以稍后清理，已提交关键引用缺对象则保护。

## 6. 事务边界与并发顺序

| 事务 | 本地原子写集与比较条件 | COMMIT后才允许 |
| --- | --- | --- |
| T1 | 查当前授权及原identity；新identity占用context额度／capacity、command、queued claim、审计、outbox、tx receipt | 返回202；重复身份不重复占额度 |
| T2 | 当前控制/授权/域/ready/资源/截止CAS；active hold、attempt、不可变intent/permit/guard、dispatching、tx receipt | 安装guard，ACK后单次DISPATCH；不是自动重传队列 |
| T3 | control operation pending、设备fencing、queued终结、切点revision、完整barrier_member、摘要、tx receipt | 发送FENCE；AUTH/TIME使用自身选择器，不篡改holder |
| T4 | 原ACK与coverage、集合相等和proof验证；control或auth/time权威结果、intent判定、receipt／审计／事件 | 宣称effective/applied；OPEN仍是独立步骤 |
| T5 | 当前boot/session/token/版本和保护条件匹配；gate安装记录与ready状态 | 开放主调度的T2资格；不以ACK到达代替提交 |
| T6 | report去重、证据、终态或resolution、合法资源变化、暂停锁存、outbox／tx receipt | REPORT_STORED及可靠结果；迟到报告不改写终态 |
| T7/R5 | 固定执行必需步骤证据齐全，源business_state／revision／active_execution匹配，当前锁存检查 | 发布目标状态和固定event_id；不重跑设备来补提交 |
| T8 | 新服务boot/domain登记、旧ready/context/ticket可用性关闭、queued终结、未核销intent保守unknown、旧人工限制／资源保留 | 只读对账及受控新握手；不自动恢复布防 |
| R1 | run revision未变才保存immutable preview/plan；远端只是绑定观测 | 展示预览，不安装grant或投递设备写 |
| R2 | identity去重、preview一次消费、run CAS、新execution／recovery operation、目标固定集、tx receipt | 返回202；保持paused准备，不立即执行 |
| R3 | 逐目标保存baseline→target与可靠receipt；全部一致后operation ready | run仍paused，不派发；必须另经R4开始事务，部分成功不算全部恢复 |
| R4 | 重新核对run/slot/op及完整目标、计划和精确latch；保存ExecutionStart、两侧start引用、run running与op running/reconciling、审计/outbox | 提交后另固定执行锚；execute进入后续新命令资格检查，reconcile_commit禁止设备写；不重用旧队列或补旧场次 |
| 身份撤销 | 签发方记录状态、floor、固定目标和outbox；目标方按T3/T4安装／保存receipt | 仅对完全确认目标报告applied；拒绝下界可先保护安装 |
| 时间变更 | profile批准／撤销修订、time_current失效、TIME屏障、记录完整切点 | 新证据重新建立后仅创建新许可，不复活旧样本 |

事务前可做有界解析／纯计算，事务内重新核对所有依赖版本，不能把事务前预检当锁。BEGIN IMMEDIATE后不等待HTTP、IPC、NTP、设备、密码计算或用户交互；事务结果返回外部前必须明确COMMIT成功。RETURNING行只供本连接后续处理。

transaction_receipt的business_id按事务种类固定：T1为request identity，T2为attempt_id，T3/T4分别为barrier_id，T5为installation_id，T6为已绑定发送者的report身份，T7为transition_id，T8为本次recovery_boot_id；R2为recovery operation。重复提交核对同一request_digest及结果，不以command_id笼统去重全部T6，否则会吞掉后续合法证据。stage属于kind，不能用同一唯一键把pending与effective两个事务合并。

SQL CAS示意：`UPDATE run SET run_revision=:next,active_execution_id=:new WHERE run_id=:id AND run_revision=:expected AND active_execution_id IS :expected_execution`；精确检查影响行数为1，否则整事务回滚。next为有界精确计算值。任何附属INSERT失败须回滚整事务，不能只忽略冲突留下部分消费。状态检查还需在该事务内读当前锁存／依赖，不由这句CAS包办全部授权。

同一命令T6完成与T4屏障并发时，writer串行：先保存不可变切点／原coverage，再按更强已知证据归并当前状态；后到证据不修改原屏障账本。只允许通知outbox重传固定事件。跨库恢复或状态提交通过引用／receipt核对，不能ATTACH两库宣称原子，更不能重发设备命令消除记录不确定性。

## 7. 存储错误、恢复与保留

BEGIN BUSY在原deadline和有限存储预算内重试；BUSY_SNAPSHOT先结束旧事务并重读全部前提。COMMIT BUSY且仍处于同一事务，只重试同一COMMIT或显式回滚核对。FULL／IOERR／CORRUPT／未知驱动状态立即保护，禁止新许可和续约，按业务ID＋tx_id安全重开查证；无法读库不能报告“肯定未提交”。所有重试逻辑不包含设备调用。

普通重启恢复顺序：取得单所有者与旧writer退出证明 → 打开原库并核验database_instance/service/schema → 结构／FK检查及领域核对 → 完成T8 → 重新取得权威授权与时钟资格 → 新worker闭闸安装完整未核销账本 → T4/T5。记录缺失或校验不明保持保护，不新建空库顶替。旧域不能用于当前tick计算；恢复每次有稳定recovery_boot_id／tx_id可幂等核对。

领域核对至少包含：request identity与command一一绑定；attempt/intent/permit/guard归属一致；finished不可回退；unknown的资源与resolution合法；未核销intent无遗漏；effective操作有完整持久屏障；ready属于新域且必须重新建立；恢复预览未重复消费；业务状态提交有同执行证据；撤销floor未倒退；outbox sequence未复用。integrity_check成功不证明这些条件成立。

保留采用引用图与状态判定：未核销intent、未解决hold、屏障成员／证据、未完成recovery/撤销目标、有效context及被运行引用版本均禁止GC。已关闭context保留墓碑和拒绝依据；同一context绝不因删除identity后被重建。关闭epoch的请求一律拒绝，即使详细历史已归档；active epoch只删除已证明无法再次受理的关闭上下文资料。原始证据归档后留不可变摘要／定位／权限及成功校验记录，不能以文件已上传视为可删除本地唯一副本。

outbox按流sequence推进，ack只证明该订阅者已确认，不证明任意设备动作。保留窗口前游标返回显式失步并锁存依赖自动化；快照恢复当前状态，不补旧离散trigger。高频遥测走独立有界内存／聚合路径，不进入关键逐条审计。容量紧张先停止新增P2/P3，保留P0/P1及已受理证据预算；预算不足仍可能FULL，须走保护，不能承诺预留空间永不耗尽。

## 8. checkpoint、备份与Schema升级

[C12 DEP06／DEP07](rebirth-c12-deployment-design.md)补充分级加密包、NodeCG及多库覆盖、隔离恢复与完整release／data generation选择。installation.db不进入可回退业务备份；其事务只选择引用，仍须先验证每个候选文件和旧writer退役。维护管理和安装持久关联按C12第10节及本稿第19节实施，不以安装日志替代本稿业务事务或存储耐久证明。

延续WAL、FULL、每连接foreign_keys=ON、busy_timeout=0、wal_autocheckpoint=0，初始化后读回验证；固定驱动必须能取得扩展错误码与事务状态。主writer与checkpoint任务有界协调，PASSIVE也占I/O；长读事务／备份持续延长导致WAL增长必须监测和限制。正常直播不主动VACUUM、RESTART/TRUNCATE或迁移。所有阈值依发布profile实测，不使用示例阈值冒充SLA。（来源：[checkpoint](https://www.sqlite.org/c3ref/wal_checkpoint_v2.html)）

备份状态为requested→copying→copied→validated→published，任一步失败不覆盖上一有效备份。Online Backup必须观察到step返回SQLITE_DONE，随后finish成功；提前finish返回OK不代表复制完成。关闭／同步目标、结构／FK及领域清单校验、计算hash后发布manifest；清单记源database_instance、service、schema、engine构建、控制／请求epoch和备份操作ID，不带明文秘密。只复制正在变化的.db或逐个拷贝.db/-wal不构成一致快照。（来源：[Backup API](https://www.sqlite.org/c3ref/backup_finish.html)、[WAL文件](https://www.sqlite.org/wal.html#the_wal_file)）

Suite多服务manifest记录每库独立一致点，不宣称同一时刻快照。需要一致维护恢复集时先暂停新工作、记录所有目标及未决事实、关闭相关writer，再逐库备份；目标未确认的集合不得标为完整恢复点。普通在线备份不必须打断直播，但恢复后都需跨库对账。

恢复备份先隔离验证／确认旧实例退出，再登记新的database_instance/control_epoch/request_epoch；原人工控制仅作历史并重新建立当前限制，所有旧客户端／票据／guard／排期队列作废，默认未布防。恢复不能用备份中缺少某记录推断现场没执行该动作。

Schema升级先进入整库维护并保存有效备份；核对from版本、脚本hash、程序／模块兼容组合。可原子DDL在单事务内写新表／索引／转换及schema_migration、user_version；大迁移离线构建新文件，验证后按固定平台原子替换／恢复协议发布，跨文件替换不冒充SQLite事务。首期不支持边直播边双写迁移。回退使用已验证兼容组合与恢复流程，不能只替换可执行文件。文件替换／目录同步／断电恢复的具体平台步骤归DF05／运维设计并列验收。

## 9. 验收设计与本轮参考检查

下列ST01—ST32均为待执行产品／故障验收，不由内存SQL探针自动勾选通过。参考资料见[DF04检查入口](contracts/df04/README.md)。

| 编号 | 注入／场景 | 期望 |
| --- | --- | --- |
| ST01 | U20最大值、24位ns、64位边界 | DTO→绑定→读回精确，禁止Number／REAL中转 |
| ST02 | 9与10与20位值排序、递增溢出 | 数值顺序正确，溢出拒绝，无环绕 |
| ST03 | LF/NUL/-0/前导零与旧协议归档 | 新profile按新版本拒绝；旧字节不暗改摘要 |
| ST04 | STRICT接收被转换输入 | 绑定层检出原始错误类型，不靠STRICT假通过 |
| ST05 | 另一issuer/epoch或context冒用幂等键 | 不串账、不越权返回原结果 |
| ST06 | 同键同摘要／不同摘要／受理响应丢失 | 原结果或409，无重复容量占用和执行 |
| ST07 | 关闭context清理后重放 | 永不产生新命令 |
| ST08 | T2外键错command／重复attempt或permit | 整事务拒绝，无DISPATCH |
| ST09 | T2提交前后各崩溃，未收到send report | 未提交无派发；已提交无可靠证据则unknown且不重投 |
| ST10 | 不同命令争同设备，另有queued claim | 至多一个活跃hold，queued不冒充已占写资格 |
| ST11 | barrier额外成员、缺成员、重复覆盖 | 全部拒绝effective/applied |
| ST12 | T4与T6各先后顺序 | 原切点不变，强证据不降级，终态不回退 |
| ST13 | unknown迟到成功及有效release | 追加resolution，unknown不变；释放须证据 |
| ST14 | OPEN_ACK后T5失败、重启恢复旧ready | 不发新许可，旧ready永不继承 |
| ST15 | report重传同内容／异内容／错会话 | 幂等确认／协议错误／拒绝串账 |
| ST16 | 两客户端不同键消费同preview | 仅一个operation/execution，失败无部分写入 |
| ST17 | R2提交响应丢失、preview已消费 | 原身份查原操作，不重建grant或执行 |
| ST18 | R3部分目标成功、撤销确认缺失 | 保持paused/indeterminate，不删目标或释放恢复锁偷跑 |
| ST19 | T7/R5提交前后崩溃 | 原状态或已提交状态可核对，不重发设备动作 |
| ST20 | 完成动作但状态CAS失败 | 保留现场效果，显式reconcile_commit且不重跑 |
| ST21 | trigger重复、序号冲突、丢事件或换boot | 去重／失步锁存，快照不补旧trigger |
| ST22 | outbox发送后ACK丢失 | 重传同event_id，消费者不二次触发 |
| ST23 | BEGIN BUSY／BUSY_SNAPSHOT | 有界重试／重读前提，原deadline不延长 |
| ST24 | COMMIT BUSY仍活跃／结果未知 | 不重跑事务副作用，按原tx_id核对 |
| ST25 | FULL/IOERR/损坏、关闭路径DB阻塞 | 独立保护起效，传播窗口如实记录 |
| ST26 | 两连接外键配置或实际engine不符合 | 启动拒绝，不能降级继续 |
| ST27 | 长读者／checkpoint饥饿／备份重启复制 | 有界告警与停止新增，证据预算保留 |
| ST28 | backup提前finish OK但未DONE | 不发布有效备份，不覆盖旧备份 |
| ST29 | 备份跨库不同时刻／秘密恢复缺失 | 标出不一致与缺项，恢复不自动布防 |
| ST30 | 恢复旧库、第二实例仍活、完整性通过但领域错配 | 拒绝开放写，不能凭integrity_check宣告安全 |
| ST31 | schema升级每个边界崩溃／回退程序不兼容 | 可核对原版或新版；未知保护，无在线混合写 |
| ST32 | GC碰到unknown/被引用证据／旧游标 | 不删关键事实；返回显式失步，不补旧执行 |

本轮仅执行内存SQLite结构／约束参考探针、文档链接／编号和既有机器基线保持检查。参考解释器所带SQLite不是产品候选引擎，未测试WAL、真实驱动、掉电、并发、备份、系统恢复或设备；精确环境与计数记录在参考报告中。

剩余设计：DB01—DB06审阅；完整DDL与SDK源切换的字段等价映射；[C06候选](rebirth-c06-schedule-design.md)已补排期逻辑场次键、日历／导入表、激活受理串行化及资格与执行结果分离，须与本稿共同审阅归并；各模块配置及扩展权限字段继续随专题定稿；DF05固定引擎与平台文件发布、DF06内部证据权限。上述设计缺口与实现后ST／FT／AU验收分别登记，不能把结构探针通过当作DF04或全系统完成。

## 10. 身份生命周期事务补充

实施时以[DF06第11节](rebirth-df06-internal-trust-design.md#11-首期主体政策与身份权威定稿)的主体政策及权威表解释本节I1—I6。第3节把credential／auth_session／run_grant并列仅为逻辑字典，不表示三者由同一签发方写入：会话与服务凭据属于指定签发Controller，本地RunGrant属于各目标Controller，Seamer的run／arm属于Seamer。镜像与本地授权须分开，不能通过复制相同表名建立第二权威。

控制请求按控制契约的RequestKey，命令裁决按第17节；其他身份管理操作按自身已成文幂等契约生成，不能将第3节历史八字段identity一概套用，也不能凭本节补充表的request_identity_ref改变操作身份。新增service＋manual及服务发布／布防／恢复拒绝须发生在新业务受理／预算消费前，事务内仍复核当前本地权限与floor。这里关闭归属与旧字典适用范围的歧义，完整DDL及真实并发故障证据属于实现任务。

2026-10-18候选，与[DF06第9节IL01—IL06](rebirth-df06-internal-trust-design.md#9-身份生命周期细化注销组织服务与配对)共同审阅。补充表字典，不代表已有生产DDL或数据库迁移；旧内存探针未覆盖本节，不复用其通过数量。

| 补充记录／约束 | 事务归属及不可省略的字段 |
| --- | --- |
| service_approval | 指定签发方拥有；approval_id、subject_ref、revision、audience／permission／object_scope BODY、validity、state、approved_by_ref、operation_ref。本地接收方仅保存明确远端镜像与自己的批准，不互相覆盖 |
| credential_proof | credential_id＋proof_request_id唯一；credential_revision、proof_ref、request_digest、state、tx_id。每credential revision至多一个成功proof，其他合法重试映射原记录，不刷新年龄；不保存原始secret，非通用授权 |
| credential_activation | request_identity_ref唯一；新旧credential_ref、approval_ref、proof_ref、固定retire_at、结果及tx_id。每subject至多一条未完成轮换，两个可换token凭据上限由同writer验证 |
| access_token | token_id、verifier／算法版本、父credential_ref、subject_ref、approval_ref、audience、scope BODY、expires、state；UNIQUE(credential_id,request_id)，关联不可改，token原文不入幂等结果 |
| session_audience | (session_id,audience)唯一，首次签发tx及关联状态；签发token／票据和添加audience同事务，注销固定目标并集不能漏过并发新签发 |
| pairing_attempt | attempt_id、pair_attempt_id、两端身份／binding／证书／scope／配置摘要、transcript BODY/digest、validity、runtime_domain_ref、state、revision；固定投影字段不可修改，变更新建attempt |
| pairing_proof | (attempt_id,direction,challenge_id)唯一，issuer／peer身份与真实TLS验证引用、transcript_digest、消费tx、非秘密receipt；direction不得由自报body替代本地角色推导 |
| trust_pairing扩充 | 原binding记录增加两端attempt关联、scope批准引用和credential集合；active只由本端可靠激活产生，peer当前状态另存有界观察，不把两个状态折叠为一个全局active |

pairing challenge继续使用one_time_credential的pairing类型，增加attempt／direction／域／deadline绑定；每attempt每方向最多一个未消费值。替换challenge在同事务失效旧值，attempt截止不移动。消费验证材料与写proof必须同事务，重复请求只读原receipt；重启失效未完成attempt，不能恢复旧单调截止。墓碑保留到相关旧身份域永久拒绝条件成立，不以普通日志TTL删除。

| 身份事务 | 原子提交内容／提交后行为 |
| --- | --- |
| I1 注销／撤销受理 | 先阻止对应身份新工作；同writer关闭session或目标、推进拒绝floor、冻结完整目标集、写operation／audit／outbox／receipt。提交未知保持保护并查原身份，不创建第二操作；目标屏障分别确认，非跨库原子 |
| I2 凭据创建 | 验证当前批准／容量／幂等，保存staged credential的verifier和非秘密创建结果，提交后仅本次内存响应可交付secret。提交失败无active凭据；响应丢失不能从DB恢复明文，撤销原staged后重建 |
| I3 凭据证明及激活 | 证明独立事务保存proven；激活事务再次检查当前subject／approval／旧credential／proof／revision，原子新active＋旧retiring＋固定截止＋操作记录。网络验证和管理员等待不在SQLite事务内 |
| I4 定向token签发 | 验证父链当前状态与预算，原子登记token验证值、完整父绑定、请求唯一性和session_audience（人员链适用）；秘密只首次交付。扣额度与记录同事务，失败不靠后续GC补偿签发计数 |
| I5 配对证明／激活 | challenge消费＋proof同事务；本端activation再检查所有当前前提与验证记录截止，写binding active／批准／receipt。远端查询先完成再由有界证据参与，不能持有写事务等网络或声称两端同时提交 |
| I6 到期／撤销传播 | 到期门控独立于清理任务实时执行；永久撤销floor和固定操作可靠提交后通知目标，重传同操作不刷新期限。目标侧T3/T4及F04屏障保留在途账本，receipt必须覆盖原目标集合 |

授权关闭先在本端拒绝新工作，不表示提交已耐久或远端已应用；I1/I6提交未知不得发布durable/applied。重启按受保护恢复规则核对，不因内存关闭标记丢失重新开放。认证时间、证书／凭据和批准有效窗口取最早可证明截止，过期状态尚未清理也不能继续接受；UTC回跳或恢复旧库不得续命。已受理设备动作不会进入身份通知outbox，身份状态重传不产生设备重发。

凭据轮换不更新旧context／intent／ExecutionGuard的credential引用。RunGrant原本以主体为范围，其有效期及arm不因轮换延长；新凭据用于新请求仍核对当前grant与本地批准。关键范围减权要处理关联grant及floor，不能仅覆盖ServiceApproval BODY使旧执行链漏撤。secret、token、challenge原文及可离线猜测的低熵秘密摘要不进入事件或普通audit。

运行验收采用ILT01—ILT18加ST23—ST32：在各事务提交前、提交后响应前及确认丢失处注入故障；两个并发签发／注销／激活连接验证唯一性、CAS和预算；恢复旧副本验证epoch及拒绝下界。实际驱动／WAL／掉电／网络均尚未执行，完整SQL与SDK映射必须在后续机器归并逐字段核对。

## 11. 监督器独立journal的完整布局候选

2026-10-18新增[监督journal候选](contracts/df02-supervisor/JOURNAL.md)及15表SQL／恢复计数视图，属于监督器独占的恢复日志，不是Controller／Seamer业务库或installation.db；三者无跨库事务承诺。保护配置创建core／time_provider不依赖尚不存在的业务scope，扩展worker全部受当前核心fence；全域退役覆盖所有角色。

J1—J6分别给出域／scope、完整fence封存、REGISTER、一次CREATE、bootstrap准入、关闭与退役的提交边界。快照封存同事务追加永久deny并更新current指针；intent／state、attempt／标志、receipt／准入状态分别用双向延迟FK防止半份记录提交。恢复预算从不可变attempt视图计算，不能在监督器重启后清零；runtime_domain证明目标覆盖旧域全部登记意图，OS后代完整性另由可信提供者证明。

本批SQL具备完整监督日志表布局，但原始JSON词法／Schema／JCS／权限与OS证据不由SQL验证；完整业务表、生产迁移和原生SQLite制品仍待统一归并。内存事务探针只证明列明约束与故障切点，未验证真实磁盘、DELETE／EXTRA、并发、监督器或设备。该候选不改变业务库WAL方案或批准DB01—DB06。

## 12. C04恢复核心的物理事务候选

2026-10-18新增[恢复核心SQL与字段映射](contracts/c04-storage/README.md)：16张STRICT表、双向延迟FK和恢复分类视图，具体覆盖R2预览消费／新执行／独立恢复锁、R3准备、R4开始／精确latch清除、R5业务提交／固定outbox。执行表区分普通触发与恢复来源，使预览可以引用旧unknown执行而不改写其终态。暂停或indeterminate不释放恢复锁；仅经核对的release证据允许单次释放。

本节同步纠正第6节旧R3/R4描述：R3 ready不使run运行，R4独立开始，提交后执行锚仍是后续短事务。SQL固化身份配对及不可逆记录，不能证明完整目标、Schema/JCS、当前授权、设备效果或跨服务原子性；可信writer必须核验并以同一事务更新全部投影。内存检查包括部分关系直接COMMIT拒绝、逐写切点整库回滚及FK合法但领域投影错误的反证，不把两者混为同一保证。

此布局尚不是全Seamer DDL：逐步CommandSubmission由第13节补充；普通触发受理、发布草稿、delay依赖边、edge/budget、C05/C06输入及身份表仍需归并。未执行生产迁移、磁盘/WAL故障、真实并发或设备操作，DB01—DB06与后续候选审阅状态不变。

## 13. C04逐步提交与裁决持久化

2026-10-18新增[执行层9表](contracts/c04-storage/DISPATCH.md)，与recovery.sql组成25表候选。基础transaction_record增加PLAN/ANCHOR/READY/SUBMISSION/ATTEMPT/ADJUDICATION/SUBMISSION_OBSERVATION/STEP_TERMINAL阶段；每阶段沿用固定审计/event配对。两份SQL共同定义draft.2布局，不直接运行于旧库，原恢复报告仍只验证基础16表。

计划封存同时核对步骤与初态覆盖，完整路径仍从固定编译产物重建；数量不能证明语义完整。StepReady同域不早于执行锚，attempt同域不早于ready；这些列关系不能证明采样发生在COMMIT返回后。请求身份、参数、attempt、裁决及终态不可改写，step的accepted必须对应已accepted的submission；最终裁决与其状态双向延迟FK，半边结果不能COMMIT。

发送标记不是outbox任务，重启只查原身份；accepted/rejected最终裁决与步骤unknown分属不同状态域。远端永久拒收需要原命名空间的Controller持久账本，Seamer只保存核验后的引用/正文，不能凭本地一行宣布远端不再受理。取消或失败终态不等于资源释放，R5仍核对完整证据与当前业务状态。数据库scope、拒绝下界、归档/备份与C05事件世代须在最终整库方案中统一。

新增212项内存及合成检查通过，包含六阶段逐写切点的25表回滚、缺半边提交拒绝、迟到回执不重开、受理非完成与取消非成功。BODY/digest及可信前提为人工夹具；没有测试生产驱动、网络/IPC、WAL/掉电、并发或设备。普通触发/发布、delay依赖边、edge/budget及身份和输入表继续补齐后才能称完整Seamer布局，DB01—DB06未因本批自动批准。

## 14. 来源摄取批次与多运行实例的存储边界

2026-10-20补充，待审阅。普通事件须按[C05第12节](rebirth-c05-event-sync-design.md#12-规范摄取的完整扇出与原子受理)一次受理完整目标集合。现有transaction_record.run_id非空，不能靠伪造run或任选第一个run承载数据库级摄取；已有25表不改写为“完整Seamer”。本节给出下一版字段映射，**尚未新增DDL或生产迁移**。

| 逻辑持久对象 | 主键／唯一性及内容 | 与原执行层的提交关系 |
| --- | --- | --- |
| ingest_epoch | `(scope,ingest_epoch)`；同库一个open；next_sequence用U20 TEXT，epoch不可复用 | 分配游标与规范事件同事务；关闭epoch不删除旧去重／拒绝下界 |
| source_state／source_floor | SourceStreamKey及revision、连续前沿、baseline、状态／gap／拒绝下界 | 来源更新和inbox升级成对；来源保护另有持久账本与完整依赖集合 |
| trigger_inbox | inbox_id；UNIQUE(SourceStreamKey,event_id)与UNIQUE(SourceStreamKey,source_sequence)；固定origin正文／摘要、first-observation及可变状态 | pending可单独持久，不含规范游标；canonical_commit_id与ingress_commit反向配对，不允许半边规范提交 |
| ingress_commit | commit_id；UNIQUE(inbox_id)与UNIQUE(scope,ingest_epoch,receive_sequence)；前后source revision、匹配索引revision、封存摘要和notification_id | 无run_id必填要求；零run也必须有账本；canonical升级、全部决定／计划／配额与通知同一SQLite事务 |
| ingress_target | `(commit_id,run_id)`；definition/version、artifact、触发binding、前态与expected_decision_id | 由权威匹配全集生成，封存时与实际decision双向差集；expected_count不能替代集合比较 |
| evaluation_snapshot | snapshot_id及不可变正文／摘要；精确inbox内容、游标、run/ingest/slot及观察修订 | 所有需求值决定引用本批snapshot；仅存在同ID不足以证明内容及来源 |
| trigger_decision | decision_id；UNIQUE(scope,run_id,inbox_id)；游标、结果、原因、可空snapshot／execution和摘要 | target／decision双向延迟FK；accepted与trigger execution双向配对，非accepted不得有新执行 |
| run_ingest_progress／baseline | run_id的当前progress及不可变baseline历史；ingest_revision、水位、source_baselines | 与本批各run决定一起更新；生命周期run.revision与进度revision分开，writer精确+1 |
| ingress_notification | notification_id和唯一commit_id、固定payload／digest及发布身份 | 与ingress_commit双向配对；转C05持久journal的投递幂等，不能在发布通知时才创建规范决定 |
| ingest_quota_reservation | 稳定quota_scope／policy与commit_id及各维度charge | 全批额度预留和受理同提交；与后续动作规则／设备预算区分，不重复扣原事件或擅自退动作预算 |

这些是领域表映射要求，不声明表数量已冻结。每个引用的scope、epoch、revision、digest必须参与关联校验；JSON正文的Schema／JCS和真实权限由writer验证。生命周期／存储候选版本将共同升级，旧trigger_ref BLOB不能继续作为唯一“证明”，需要具体decision外键和完整Ref内容核对。

推荐保留原per-run transaction_record／event_outbox用于运行阶段，新增数据库级ingress_commit根记录。每个目标run的受理审计用明确`INGRESS_RUN`阶段并引用父commit，父记录不反向依赖任意一个run；零目标仅有根记录。目标、决定、执行、计划、run/slot、容量及所有根／子审计outbox在**同一次COMMIT**完成，不能为每个run分别BEGIN／COMMIT。父子关系和封存约束需在下一DDL中实现，现有phase枚举尚无该值。

普通触发的PLAN写入同一受理事务；原PLAN事务身份可以作为同COMMIT内的子审计存在，但不能另行提交。source、inbox及根记录全部成功且全体target有对应decision后才允许seal；accepted路径还须完整计划和运行投影一致。冻结后target／decision集合不可添加、替换或删除。若目标为零，empty-set摘要及数量显式保存，不跳过根审计。R4恢复和后续ANCHOR／READY／SUBMISSION等事务继续独立；这些关系不构成跨库或设备原子性。

ACK丢失只读原commit；COMMIT结果未知按DF04存储故障闭闸，再核对原身份，不能先ACK后后台补账。已开始决定写集却回滚时不得自动重放live事件；另存来源资格失效／保护事实，写库仍失败则保持入口关闭并请求远端保护，恢复后按reconcile和旧身份核对。普通锁等待发生在求值前且未失去资格时仅允许有界等待。完整故障期望见EN03/05/16/21/24。

GC须同时考虑来源重复身份／拒绝floor、任何未决执行、run基线、恢复预览、审计和订阅pin；不能只按last_receive_cursor删inbox。原始正文可按批准留存政策清理，但无证据的旧身份必须永久拒绝重新触发；需要原详情才能安全恢复而详情已失去时只能保护并说明缺证。备份恢复先更换数据库／摄取身份并恢复拒绝下界和关闭旧资格，不能清空唯一键重放来源。

后续验证必须覆盖全批逐写回滚、半边关系COMMIT拒绝、空全集、同count换目标、epoch不同比较拒绝、已提交重复、保护事务独立和提交未知查询。现有212／257／88项SQLite参考检查仅按原25表／16表／监督日志范围回归，不执行本节逻辑表或EN验收；完整DDL、生产驱动WAL与并发／掉电／网络及权威提供者均仍待交付。


## 15. 摄取附属布局与封存完整性

2026-10-20补充。**已知事实：**[ingress.sql](contracts/c05-ingress/ingress.sql)在原16+9表之后新增15表，局部40表组合覆盖连续规范受理及原pending单次升级。原布局保持原样；本候选不声称已完成全Seamer DDL或来源保护与GC。

**推荐衔接：**第14节逐run INGRESS_RUN子账本具体采用独立ingress_run_audit，避免在本附属候选中修改旧phase枚举。根commit不要求伪造run；target、snapshot、decision、execution映射和通知构成不可变配对，accepted执行的PLAN审计与步骤封存在同COMMIT；基线与run进度独立。

封存前显式核对监听全集、决定/快照对应、运行投影、来源/epoch水位，以及通知、容量行与所有逐run审计。参考实验观察到仅有延迟FK时缺通知仍可COMMIT、随后外键检查报错，因此加入显式封存反例与约束；对目标产品引擎须重新执行，不把参考结果推广到其他版本。数量相同的错误绑定、半边写集和sealed后改写均拒绝。

94项内存SQL检查包含空集合、两个accepted逐写回滚、三类决定混合、pending首观察不变、observed_only不可升级、重复查原、晚注册不补决定及独立锚事务。SQL BODY和预算行为仍是合成占位；完整引用内容、JCS、准确加一、当前授权/时钟、匹配索引修订和实际额度由可信writer另验。保护latch、完整来源历史/GC/floor、备份恢复、固定provider回执及生产并发/WAL/掉电仍待完成。

## 16. 来源保护的持久所有者与四个事务

2026-10-20补充。以下为[C05第14节](rebirth-c05-event-sync-design.md#14-来源失效完整依赖保护与恢复门槛)的具体存储设计，**不是已实现DDL**。上一版40表不包含这些完整记录；[局部保护检查](contracts/c05-protection/README.md)使用有限内存对象模型，不能记作SQLite证明。

| 所有者／记录 | 主键、关联与保留规则 |
| --- | --- |
| Seamer source_dependency | `(source_key,run_id,dependency_kind,owner_ref)`；固定artifact/source binding/revision及当前/历史pin；owner可为run、execution或recovery。仅在资格解除且无未清引用后删除 |
| Seamer run_controller_target | `(origin_scope,run_id,arm_generation,controller_scope)`；登记revision、准备/提交意图完整引用。先持久后发送prepare；响应未知不能删目标 |
| Seamer source_fault | fault_id；UNIQUE(detector_domain,detector_sequence)，固定source_key、reason、gap及证据正文/摘要；冲突不覆盖 |
| Seamer source_protection_plan／target | protection_id及`(protection_id,run_id)`、Controller子目标身份；完整依赖索引revision/前态、排序集合/摘要、封存标志。封存后不可增删，不能分页受理半个全集 |
| Seamer run_source_latch／deny | latch_id及`(run_id,protection_id)`唯一；不可变来源/plan及被拒代次。deny按完整origin_scope/run存max下界，不随source变绿删除 |
| Seamer protection_outbox／audit | `(protection_id,controller_target_id)`唯一，固定operation_id、selector/target摘要、请求body；与plan及latch同COMMIT。投递重试不重建身份 |
| Controller run_generation_deny | `(origin_scope,run_id)`；拒绝下界、revision、原操作引用；单调不降，prepare/command/guard/最后出口共同检查 |
| Controller run_fence_operation／target／receipt | `(controller_scope,origin_scope,operation_id)`唯一；selector、请求目标摘要、设备/旧出口切点与完整intent账本、coverage及receipt；相同operation异内容拒绝 |
| Seamer protection_application | `(protection_id,controller_target_id)`唯一；精确Controller scope/operation/selector/cut/ledger/receipt摘要，重复同结果幂等，当前汇总不能替代原回执 |
| Seamer source_rebaseline／source_pause_resolution | 不可变baseline与resolution身份；绑定floor、旧gap、保护回执、资源证据、预检/代次及latch；R4清理记录反向指向实际start，不以删除latch表示恢复 |

P1—P4的字段/正文均须通过具名Schema、摘要和作用域关联检查；不能只存Ref字符串就声称已校验真实性。下一DDL需要双向FK、唯一键、单调触发器及封存显式全集检查，与第15节避免单靠延迟FK的发现一致。全批额度/日志正文有独立受限profile，不把无限JSON BLOB当作有界设计。

| 事务 | 同库原子写集 | 成功边界／故障处理 |
| --- | --- | --- |
| P1 Seamer本地保护 | fault去重、完整依赖/Controller目标快照、source失效与run deny、所有必要run暂停和latch、待发定时器/边沿资格关闭、P0预算、audit及fence outbox | 本地committed才能对外报可靠暂停；任一失败全部回滚，RAM门仍闭，不补原摄取回执 |
| P2 Controller接收保护 | origin授权/幂等复核、单调run deny、所有匹配queued阻止、完整旧出口切点/intent清单、操作与屏障outbox | accepted只说明保护请求持久；还不是所有出口已fenced。空命令集也存deny墓碑阻止晚prepare |
| P3 Controller应用保护 | 完整coverage/监督退役证据校验、屏障状态及每intent归类、固定receipt、audit/outbox | applied仅证明匹配代次后续不能再越已覆盖出口；in_flight/unknown与资源占用仍保留 |
| P4 Seamer记录应用 | 固定目标/selector/cut/范围摘要核对、receipt和application、完整目标汇总、audit/通知 | 全目标已applied才汇总applied；少项或错scope不成功，后续恢复仍另验源基线、资源和全部latch |

Controller持久拒绝与Seamer持久暂停不构成跨库原子事务；P1先提交后P2完成前存在传播窗口。故障时可以先安装更保守RAM拒绝，但必须显示unconfirmed/indeterminate，不伪造durable receipt。保护动作可按原幂等身份重投；设备动作不能继承该重试例外。

重基线事务仅保存新的可信baseline、source修订、拒绝floor和未补旧gap，不能删除deny/latch或将run变armed。R4恢复事务必须核对全部当前source和依赖索引/ingest前态、精确latch集合、完整保护应用及资源证据，新generation严格超过已知deny floor。R4完成后latch保留cleared_start_id，旧代次deny仍有效；新fault与R4同writer串行，不能用旧snapshot覆盖刚到的保护。

发布/布防及新增准备目标在产生可发资格前预留完整P0最坏写集。存储不可写或P0不足时先保持本地自动化门闭并请求受监督写域保护；按既有可信准备记录可发送紧急拒绝，但未保存的Seamer计划不得当作持久Ref。重启从默认未布防和完整旧准备/提交库存核对开始，不能凭本地没有fault记录恢复执行。PFT04/06/09/15/16要求真实writer、驱动、进程和网络故障验证，本轮未运行。

## 17. Controller命令裁决子域

2026-10-20补充。[11表候选](contracts/c02-admission/STORAGE.md)落实同key受理/永久拒收排他裁决。namespace绑定真实target_scope及issuer_epoch，digest只是内容；request_key与adjudication、accepted与初始command/容量、commit与审计/通知及拒收操作均双向同事务配对。初始CommandRef固定revision1，最新命令状态由独立记录演进；rejected不产生command，reject_existing不改原decision或清理资源。

历史namespace归属证据和当前权限分别取证。namespace关闭永久阻止新accepted，但保留当前有权的查原/拒收；备份恢复使用新scope并保留旧历史，不能修改库身份伪造原目标的永久拒收。所有墓碑暂不GC，完整归档替代证明未冻结前禁止删除。通知只发布事实，不能作为设备写重传队列。

159项内存SQL检查验证缺写不能提交、主动异常全表回滚、两裁决顺序、身份/关联错配、关闭与删除保护。BODY/授权/JCS仍为合成占位，检查不证明真实writer、并发、WAL或掉电；本候选不是全部Controller执行/保护DDL或已发布迁移。C04身份列、SDK同版归并和生产提供者继续待完成。

## 18. 组织运行批准的产品写集

采用[C04第18节](rebirth-c04-automation-design.md#18-组织运行批准与目标范围认可)的不可变正文和独立状态，不复用身份ServiceApproval表来承担RunApproval。下表是产品迁移及writer的明确约束，不是已执行DDL或新增隔离数据库；所有远端Ref保留原authority／database／revision／digest，本地事务不能声明跨库原子。

| 所有者／写集 | 必须一起提交的内容与唯一约束 |
| --- | --- |
| Seamer提案 | proposal正文／摘要、固定run和artifact／完整足迹、原管理RequestKey结果、审计及C05目录版本；RequestKey唯一，同键异内容拒绝，失败不留下可被认可的半个proposal |
| Controller认可 | endorsement正文／摘要、当前状态、真实人员与本地可授范围证据、原RequestKey结果、审计／目录／通知；同proposal_ref与本controller_scope最多一个有效endorsement，拒绝记录不因新请求键消失 |
| Seamer批准 | RunApproval正文及状态、proposal→approval唯一关联、run当前approval指针、run revision递增及旧preflight失效、RunApprovalOperation、去重结果、完整认可引用、审计／目录／outbox；当前指针每run至多一个，CAS包含原run修订及原approval_ref |
| Controller准备 | 既有prepare／grant／receipt事务内读取认可状态、approval拒绝及当前政策，RunGrant正文与本地endorsement强关联，approval_ref／endorsement_ref及真实服务主体纳入grant摘要；本地FK绑定本地原件，远端批准由已核验原件及完整Ref绑定，不造远端FK |
| Seamer撤销 | approval永久拒绝／状态、run新工作关闭、proposal全目标与已登记prepare／grant／旧执行pin并集、完整operation targets及保护outbox、审计／目录；空的当前grant列表不能缩成零传播目标 |
| Controller批准撤销 | 原Seamer撤销身份唯一登记、approval_ref拒绝墓碑、所有本地匹配准备／grant失效及RUN_FENCE意图、receipt状态、审计／目录／outbox；先到撤销也持久占位拒绝，没有grant不等于可以忽略 |
| Controller认可撤销及Seamer通知 | Controller同writer写认可拒绝、匹配grant保护及通知固定原件；Seamer以原Controller scope／撤销操作Ref／endorsement_ref去重，同writer拒绝该proposal新批准并保护全部已派生approval／run，重复通知只返回原receipt |

批准／认可的不可变BODY与独立status_revision不可互相覆盖；状态终结、replacement引用及当前run指针分别存储。管理Key按C04新定义，不能照搬本稿第3节历史context参与唯一键的旧字典。人员认证引用是当次操作审计，运行检查不能用外键级联删除把人员停用变成组织批准撤销。ServiceApproval／本地政策变化按独立拒绝及当前交集处理，纯增权不扩大旧批准正文。

实际发送与撤销仍在同一目标writer／最终Gate排序，HTTP返回receipt不等于worker已停；applied由已完成的本地拒绝、RUN_FENCE和持久回执共同证明。原件或拒绝账本不明时保护，COMMIT未知查原，不先响应成功再补目录／outbox。旧域备份恢复保留历史和deny证据，新scope重新批准；任何未核销、unknown或恢复pin存在时不清理这些记录。

SDK生成和产品迁移按上述唯一键及写集一次接入原服务库；新增验收为逐写失败全事务回滚、并发批准CAS、认可撤销与prepare排序、撤销先到、COMMIT观察丢失、重复通知、人员停用不级联及恢复新域拒绝旧资格。当前未执行这些产品SQL／进程／平台检查，不能引用早期局部SQL报告作为本节通过证据。

## 19. 维护账本与业务备份的事务分界

[C12第10节](rebirth-c12-deployment-design.md#10-维护管理请求与本机执行权威)的maintenance authority由Suite本机agent承担；installation.db使用本稿单writer、FULL／WAL及错误处理规则，具备自己的database_instance_id和安装域，业务服务不得直接写入。维护记录不随业务备份回滚；路径、秘密和OS审批审计保存在受保护域，API只给脱敏投影。

| 本机writer事务 | 同事务事实及提交后的动作 |
| --- | --- |
| 计划与请求受理 | MaintenanceRequestKey唯一及摘要、不可变plan_ref、operation初始态、预期generation、目录版本和receipt一起提交；提交后返回202或执行固定工作，不先回accepted |
| 本机批准／取消 | OS主体和固定计划摘要／RecoveryPlan、expected generation及operation revision CAS、批准或cancel_requested与审计同写；不得以取消清除激活事实 |
| 归档发布 | helper已退出、文件同步且摘要／验证／覆盖确定后，在同事务写archive状态、result_ref、operation结果与目录事件；崩溃遗留文件仍是未发布，核原摘要后才允许补提交 |
| writer退役与激活 | 每目标退役receipt和来源域持久绑定；只有全目标满足且新代已保护准备才按DEP07原子CAS完整ActiveDeployment与activation_operation结果，不能另起独立业务库事务冒充跨库原子 |
| 重启核对 | 原operation、文件／helper／监督域证明及activation_operation_id核对后更新revision／结果；不确定保留indeterminate和旧拒绝下界，不以新空库或超时推翻已受理事实 |

各业务库在线备份提供者使用backup_operation_id唯一关联maintenance operation和自己的service／database scope，在自身writer记录requested及复制／校验结果；SQLite Backup完成证明不能由agent的202替代。agent按这些真实回执汇总，每库一致点仍独立；NodeCG另提供其持久化证据。业务侧响应丢失查同backup_operation_id，不重复发布不同内容到同archive；原任务未证明结束时不启动第二份helper。业务库记录与installation.db不能同事务提交，采用固定请求身份与持久结果的重试读取；原业务库损坏或换代且缺原记录时保留unknown，不推断从未备份。

目录记录与对应原件同writer，跨域只保存完整Ref和已核摘要，不建立虚构的跨库FK。在线复制／归档的大块IO不放在安装或业务writer事务中；生成文件、同步、验证与发布引用分阶段执行。这里是产品DDL／实现输入；维护agent、业务备份提供者、跨进程崩溃恢复及两平台耐久验证均未运行。
