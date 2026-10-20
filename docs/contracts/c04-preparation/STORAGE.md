# Controller 准备与关闭持久化候选

状态：待审阅，`automation-preparation-storage/0.1.0-draft.1`。本稿落实[准备协议](README.md)的 Controller 端存储，不改变既有 HTTP 接受集，不实现产品服务。[SQL](preparation.sql)是独立设计参考，不能直接作为生产迁移执行；[检查器](check_storage.py)只使用内存 SQLite。

## 1. 身份、所有者与具体布局

所有表由目标 Controller 的同一关键库、同一 writer 拥有。库身份与 C02 的 `ca_scope` 必须来自同一个实际 Controller authority/database；本参考库用 `cp_scope` 单独固定该身份，最终迁移只能保留一个公共 scope，不得部署两套可独立更换的身份。

准备键为 `(controller_scope, origin_scope, preparation_id)`；同一 origin/run/arm_generation 另有唯一约束。内部 `prep_key` 只是定位键，不能换它绕过上述唯一性。请求全文、摘要、模式、execution、代次和设备集合一经提交不得修改。拒绝、关闭、过期和重启均不释放身份。

| 表或视图 | 具体持久内容及关联 |
| --- | --- |
| cp_scope | 单一 Controller authority/database；不可变 |
| cp_request | prep_key、origin authority/database、preparation_id、run_id、generation、mode/execution_id、request_digest、完整 request_body、device_count、首次 commit_id |
| cp_request_device | prep_key/device_id 复合主键及 expected_control_body；首次 commit 核对 device_count，之后冻结 |
| cp_event | 不可变 event_id、prep_key、revision、previous_revision、state、receipt_id、completion_id、commit_id；修订连续，前一版本必须已经提交 |
| cp_grant | 一准备一个 grant_id/revision/digest/body，反向关联唯一 receipt_id；这是**首次签发快照**，当前撤销状态由授权子域拥有 |
| cp_receipt | 一准备一个 receipt_id/digest/body、request_digest、grant_id、签发 event_id；与 grant 及 applied 事件双向配对 |
| cp_close | close_id、prep_key、close_operation_id、完整操作摘要/正文、当前保护授权证据、commit_id；同一准备和 operation_id 唯一 |
| cp_protection | 每个 close_id 的固定保护意图、完整出口目标数、意图正文；没有出口时允许明确的空集 |
| cp_protection_target | close_id/target_id 及完整出口身份正文；集合在关闭提交时冻结，不能事后追加或删项 |
| cp_completion | completion_id、prep_key、close_id、完整 durable protection_ref、证据正文；只作为已核验保护结果，不表示资源 clear |
| cp_deny_event | 全表 snapshot_revision、origin/run、deny_through_generation、该 run 的 deny_revision、close_id、commit_id；只追加，拒绝下界严格升高时才生成新行 |
| cp_commit | commit_id、prep_key、kind、event_id、close_id；最后插入，检查完整写集；所有可见变更必须反向绑定它 |
| cp_audit、cp_notification | 同 commit 的脱敏审计和状态通知，双向配对；通知只传状态，不含设备派发任务 |
| cp_current、cp_deny_current、cp_recovery | 已提交状态、已提交拒绝下界与重启处置视图；未完成写集不对外发布 |

所有 BODY 都是非空 BLOB；SQL不解释 JSON/JCS，也不证明授权、完整物理出口集合或保护证据真实性。`request_digest`须由严格解码后的完整 PrepareRequest 计算；HTTP 字段到投影列和正文一致性由 writer 的 SDK 验证器检查。修改摘要不能使错配变成合法。

**计数存储映射：** 对外 U20 保持无前导零的十进制字符串；本子域 generation/revision 在库内统一左补零至20位，按 BINARY 文本排序。SQL以两个至多10位的整数段计算精确后继，避免转换整个20位数到 SQLite INTEGER 或浮点。`99999999999999999999`没有后继，耗尽时保护并进入维护，禁止回绕。ID、时间戳和正文中其它数字不能套用此映射。

外键和递归触发必须在事务外开启并验证；禁止 `REPLACE`、关闭约束、任意外部 SQL 和修改 sqlite_schema。数据库恢复不得原地改 `cp_scope`；旧库只能作历史，不能给新库提供活动准备资格。当前没有安全归档替代协议，所有墓碑、修订、签发和关闭记录都不删除。

## 2. 原子事务及唯一发送边界

每次调用先核对当前 mTLS 配对、origin 所有权和具体 prepare/read/protect 权限。幂等读取不重新要求过期的原动作授权，但仍要求当前读取或保护权限。同身份异摘要返回409；无可靠存储结果返回 indeterminate，不伪造 not_found。

| 路径 | 同一个 BEGIN IMMEDIATE 中的完整写集 | 提交后 |
| --- | --- | --- |
| 登记 accepted | request、完整 request_device、revision1 accepted 事件、commit、audit、notification | 才可返回202；不签发、不投递设备 |
| 签发 applied | 在 writer 内重核准备状态、run deny、当前批准/控制/基线；grant、receipt、下一 revision applied 事件及完整 commit/audit/notification | 返回同一个已提交 receipt；Seamer再绑定实际 grant_ref |
| 明确拒绝／本地不确定 | accepted→rejected 或 indeterminate 的下一 revision 及 commit/audit/notification | 不生成 grant；indeterminate 不授权再签发 |
| close 首次到达且准备不存在 | 完整 request/device、revision1 closing、close、protection/完整目标、必要 deny_event、commit/audit/notification | 后到 prepare 查原，只能看到 closing/closed |
| close 已有 accepted/applied/indeterminate | close、保护意图/完整目标、必要 deny_event、下一 revision closing、commit/audit/notification | 禁止该准备的新命令，保护 outbox 可投递 RUN_FENCE |
| close 已 closing/closed/rejected | 新 close_operation 独立记账、保护意图/目标、必要 deny_event、commit/audit/notification；不产生状态修订 | 返回当前状态；rejected不能借关闭变为可签发状态 |
| closing→closed | 读取并核验一个已持久保护结果；completion、下一 revision closed、commit/audit/notification | 保留原 receipt；仅证明保护完成，不释放在途资源 |
| 同请求或同 close_operation 重投 | 当前鉴权后比较完整摘要，读取原记录；不新增写集 | 不增修订、不签第二 grant、不重新占容量 |

同一 writer 内前后顺序裁决竞争：先 issue 提交再 close，历史 applied 回执保留；先 close 提交再 issue，SQL拒绝从 closing 签发。数据库写锁不是远程权限的锁；权威快照的期限、撤销版本和最终设备发送闸仍按 F04/F05/F02 核验，不能宣称此事务消除了跨服务撤销传播窗口。

`cp_event`只允许 accepted→applied/rejected/indeterminate/closing、applied/indeterminate→closing、closing→closed。首次事件只能 accepted 或 closing。`applied`必须有本准备的唯一签发回执；已有回执不得丢弃或替换，后续 closing/closed继续引用它。accepted/rejected不带回执；closed必须有本准备、同run代次保护完成引用。事件不可修改，`cp_current`只选择已经配套提交的最新修订。

所有记录及状态通知先提交才可回复。事务中不得网络访问、等待 worker、生成设备命令或写 socket；外部证据在事务前取得、事务内核验当前版本/期限。数据库提交结果未知时关闭准入，再查原库，不能重新执行签发事务。`cp_commit`是持久配对事实，非真实磁盘耐久的替代证明。

## 3. RUN_FENCE、完整集合与屏障衔接

close 事务的保护提供者输入为原请求、当前 run deny、该 origin/run 的全部相关准备/命令及历史发送出口登记，包括未知准备和旧进程。输出固定完整目标、每目标完整许可账本、关联的 registry 高水位、证明策略与保护预算预留。目标身份至少含 runtime domain、worker instance、connection、dispatch epoch及设备，不按“目前在线”过滤。

SQL只能核验**已提供的** target_count/唯一目标和冻结时点，不能证明提供者没有漏掉整个出口；实际集合完整性必须在同 writer 中对权威登记表作双向差集并绑定高水位。最终 Controller 执行/屏障布局归并时，将 cp_protection_target 绑定这些真实登记键；在那之前，本子域不得宣称 P2 完整生产布局已完成。

拒绝下界是 Controller 唯一一份运行保护权威。`cp_deny_event`是本候选对该公共账本的具体布局，最终通用 protections HTTP 与 preparation close **必须共用同一账本**，不能各自维护 floor 或各自从1分配 snapshot_revision。本参考限定由准备关闭写入，通用保护入口的外键和写集在P2归并时显式扩展，不能强行伪造 preparation。

每次 floor 实际升高，全表 snapshot_revision 与该run的 deny_revision各精确加一；相同/更低的关闭代次只绑定既有更强拒绝，不增加这两个修订。它不阻止对另一准备分别记账。新代次大于拒绝下界也不自动获准，仍须新预览、准备和完整授权。

状态持久后，唯一保护投递者读取不可变 protection意图，按既有IPC0.5发送 RUN_FENCE；它只能重投同一保护身份，不能从状态通知重建设备动作。worker ACK只有在 authority核验完整覆盖、来源、出口世代、排序摘要及耐久引用后，才允许写 completion。传输 ACK、当前空队列、进程已死或新连接的“未发送”都不能替代旧出口完整证据。保护未完成时保持 closing；不得为显示成功而改 closed。

## 4. 崩溃恢复与重复操作

| 故障切点 | 重启后的可证明事实与唯一处置 |
| --- | --- |
| 登记提交之前 | 原事务无可见完整记录；lookup仍不能证明在网络中的旧请求不存在。Seamer关闭原身份，不换ID重投 |
| accepted已经提交，签发未提交 | 默认关闭；从accepted转closing并建保护。不自动补签，即便当前审批仍有效 |
| grant/receipt任一写后但commit之前 | 整个签发回滚；若存储结果不能判定则保护/核对，不能以局部行推断applied |
| applied提交后响应丢失 | 查原返回原grant和receipt；不分配第二ID。重启默认关闭，回执只是历史，不恢复OPEN_GATE |
| close提交前主动异常 | 原状态/拒绝下界均保持原值；若调用方不能确认结果则查原/重投同一close操作 |
| close提交后IPC未发或ACK丢失 | closing及拒绝下界保持；恢复同一保护意图，查询/重投相同RUN_FENCE，不创建新设备动作 |
| completion与closed提交中失败 | 没有完整commit就仍closing；重新核验已有保护证据后提交，不拿未落库ACK报closed |
| closed提交后响应丢失 | 查原closed且保留历史receipt；同close_operation不新增行 |
| 旧applied响应晚于Seamer暂停/关闭 | 只能补历史绑定和保护；不得清暂停锁存、R4开始或恢复旧worker |
| 恢复库scope变化或完整性检查失败 | 新库保持关闭；旧库不可查不能构造“未签发”证明，待历史核对及新代次流程 |

`cp_recovery`给出默认处置分类；它不会执行恢复，也不证明文件重开、进程崩溃或磁盘断电已经测试。特别是查询原applied与当前可执行资格必须分别返回/计算，不能把查原的历史 grant.state=active 当当前有效状态。

## 5. 验收与本轮证明范围

沿用PRE01—PRE12。本轮内存SQL检查对应PRE02/03/04/05/11/12的存储部分：身份别名绕过、重复签发、close两个先后顺序、过期grant不作为关闭SQL前提、每步缺写/主动异常回滚、不可变回执、计数跨10位/超过有符号64位/耗尽，以及缺保护证据不可closed。原102项协议检查仍独立，只绑定其原覆盖范围。

`storage-report.json`列出430项实际执行的断言及四份输入字节。参考环境的SQLite版本不是产品引擎批准；串行两种顺序不是真实并发，主动异常不是真实进程崩溃。计数高位进位为独立SQL表达式边界探针，不声称执行过十亿次状态修订；SQL未解释BODY的反例通过仅证明该层限制。未执行当前认证、授权提供者、完整出口提供者、HTTP、IPC、WAL、磁盘耐久或设备。

复验：`python check_storage.py --report`；提交前 `python check_storage.py --check-report --staged` 只核输入字节。最终仍需 Controller 共库迁移/公共scope与deny账本归并、执行登记和屏障FK、P0容量、通用保护P1—P4及SDK全路由映射。本子域不再属于“准备没有物理布局”，也不以局部SQL关闭全系统设计。
