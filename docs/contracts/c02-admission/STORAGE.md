# Controller 请求裁决持久化候选

状态：待审阅，`command-admission-storage/0.1.0-draft.1`。这是[命令裁决](README.md)的完整受理子域布局，不是全部Controller数据库或已发布迁移。沿用[DF04](../../rebirth-df04-storage-design.md)单writer、短事务、BODY及身份规则；不实现服务，不变更旧公共契约或Seamer旧表。

## 1. 所有者与字段映射

本候选11张表全部在目标Controller同一关键库；不通过跨库事务、另一张去重缓存或GUI数据库裁决。表使用`ca_`前缀以免被误当作旧逻辑表已经完成迁移。连接必须在事务外设置并检查`foreign_keys=ON`和`recursive_triggers=ON`；产品SQL入口禁止`REPLACE`、关闭约束及任意外部SQL。参考检查显式尝试REPLACE以证明当前连接配置下不能删除墓碑。

| 表 | 权威数据及SDK对应 | 提交约束 |
| --- | --- | --- |
| ca_scope | 唯一authority_service_id、database_instance_id、契约版本，对应RequestKey.target_scope | 一个不可变库身份；未知/缺失库不自动新建 |
| ca_namespace | issuer_id、issuer_epoch、principal_id、request_epoch及历史归属证据；引用scope | 四字段唯一；namespace_id仅内部定位，换内部ID不能绕原身份 |
| ca_namespace_closure | namespace_id、保护操作及关闭证据 | 只追加且不可重开；不删除历史，不把关闭当设备停止 |
| ca_request_key | namespace、固定createCommand、idempotency_key、完整内容摘要/BODY、device投影 | 唯一键不含digest或context_id；与裁决双向配对提交 |
| ca_adjudication | adjudication_id、revision=1、decision、初始command_id、commit及摘要/BODY | accepted必须匹配初始命令；rejected不能带命令；初始裁决永不改写 |
| ca_command_initial | 初始command_id/revision=1/digest/BODY及完整admission_binding_body | 一key一命令；反向匹配accepted；必须存在同key/command容量预留 |
| ca_reservation | key/command、批准容量profile及预留维度BODY | 与初始命令双向提交；不可变准入事实，不是活跃资源hold |
| ca_commit | commit_id、原key、accept/reject_new/reject_existing、创建裁决及拒收操作关联 | 新裁决反向配对原commit；拒收必须反向配对原操作；每commit必须有审计和通知 |
| ca_rejection | 当前actor三元身份、rejection_operation_id、完整请求摘要/BODY、原key、commit及授权证据 | `(当前issuer,issuer_epoch,principal,rejection_operation_id)`唯一；scope由该库固定；同ID异内容冲突 |
| ca_audit | commit/key/kind及脱敏审计BODY | 与commit双向同身份配对，不能缺失或移到其他裁决 |
| ca_notification | commit/key/kind、唯一event_id及投影BODY | 同commit原子发布的固定通知；禁止承载DISPATCH或设备写任务 |

`ca_request_key`中的namespace展开后就是完整RequestKey，包含issuer_epoch；本轮不把新列偷偷加进旧C04模型。`request_digest`、初始command摘要、裁决摘要存规范`sha256:`加64位小写hex。BODY为非空BLOB保留既定编码；SQL不实现严格JSON、JCS、字段投影或来源真实性，不能以`b'{"fixture":true}'`通过SQL证明它是合法DTO。

当前命令状态必须另有版本化状态/证据表；它可以到revision2及更高，而`ca_command_initial`永远保留revision1。查询初始裁决不联接“最新版本”重算CommandRef。取消、设备效果、attempt、资源释放和屏障账本均不写入本子域代替原执行事务。容量释放也另有消费/释放记录，不能删除预留事实来腾出请求键。

## 2. 历史命名空间与当前权限的提供者边界

下列接口是writer内的逻辑输入输出，不是新增公开HTTP，也不是接受客户端`trusted=true`。字段来源不足时拒绝或保护，不把SQL外键当作鉴权。

| 输入 | 可信来源与输出 | 失败结果 |
| --- | --- | --- |
| 当前认证上下文、目标scope、context_id | 指定issuer的当前验证器及本Controller上下文账本；产出完整issuer/epoch/principal/request_epoch与所选契约版本 | 401/403或版本错误；不创建裁决 |
| 原RequestKey、当前actor、原content | 本库不可变namespace归属证据，加当前subject/配对及对象权限；输出允许读/保护的原namespace和目标设备集合 | 归属不能证明则403；存储未知则503/indeterminate，不返回伪not_found |
| 新CommandContent及当前门控 | 准备/实际grant、运行来源、控制版本、时间/资源和容量的权威快照；输出完整admission_binding及固定预留维度 | 不受理，不生成“永久rejected”假证明 |
| 新RejectRequest | 当前command.cancel、历史namespace所有权、完整identity/content摘要及面板来源/委托交集 | 拒绝越权；旧grant到期本身不阻止当前仍有权的保护 |
| BODY/查询列和Ref | 所选SDK结构/语义/具名投影检查，当前服务的提交器 | 校验失败回滚；重启发现不一致则进入保护 |

历史归属证据至少绑定issuer/epoch/principal、request_epoch、target_scope、原签发或配对记录引用及其摘要、契约接受集；记录证据不延长token、context或动作grant。当前actor三元组不能仅按principal字符串与旧主体匹配。证书轮换是否仍是同一主体由DF06确定；新的issuer_epoch不能继承旧归属，管理员也不因角色名取得未授予的原请求读取/拒收权限。

namespace关闭仅禁止**新的accepted**；已受理/拒收原件在当前读取权限下仍可查，当前有权保护仍可新增拒收墓碑。普通context到期必须由当前鉴权门控拒绝新受理，不必伪造namespace关闭或删除其历史。关闭与受理在同一writer顺序下判定：先受理则保留原命令并走已有保护/取消；先关闭则后续新受理失败。关闭不撤回已发送副作用。

备份恢复改变scope，不能更新`ca_scope`原地复活旧命名空间。旧scope作为只读历史独立保管，新库/epoch的注册遵循恢复设计；旧原件不可访问时保持indeterminate，不能在新scope“补”一个rejected证明原目标不会执行。尚无归档替代证明和GC规则，因此本子域所有身份、裁决、拒收、审计及通知行均不删除。

## 3. 原子写集与返回顺序

所有操作先作当前认证和对象可见性检查；查原结果优先于重新要求原动作资格，但不绕当前读取/保护权限。同key同digest返回原件，同key异digest返回409。查原未知不重发设备动作。

| 路径 | 同一短事务的完整写集 | 提交后的行为 |
| --- | --- | --- |
| T1受理新key | 复核门控/容量；request_key → adjudication(accepted) → command_initial → reservation → commit(accept) → audit → notification | 提交成功才回202并把原command_id交给现有执行器；通知只能重传观察事实 |
| 永久拒收新key | 当前保护及归属核验；request_key → adjudication(rejected) → commit(reject_new) → audit → notification → rejection | 提交成功返回原rejected；不创建命令，不取得设备写许可 |
| 拒收已有accepted/rejected | 当前保护及完整原件核对；commit(reject_existing) → audit → notification → rejection | 返回原裁决；accepted仍需独立查询/取消/资源核对 |
| 相同拒收操作重投 | 当前权限下按actor三元组和rejection_operation_id查原，核完整operation_digest | 返回原结果，不插入第二commit/通知，不重新占容量 |
| lookup | 在一致读取点核原namespace、key、digest及完整裁决，释放响应前复核当前可见性 | found原件／确定无记录时not_found／不能确定时indeterminate；不生成写入 |

箭头是建议插入次序，不意味着每次插入即可成功对外。循环外键为延迟约束，COMMIT才证明配对完整；任何半边不能提交。COMMIT返回未知按DF04核对事务状态与原件，不能强行分类为回滚。完整受理后进程在入队前崩溃由原命令/intent恢复规则裁决；本子域无发送证据，不能自行重排为一个新动作。

错误响应不构成永久拒收。容量上限由已批准profile在writer内检查，重复操作不能再次收费；本SQL只固化一次预留及关联，不计算生产配额或进行真实容量准入。墓碑/审计/通知空间耗尽时关闭准入并保留原件，不删除旧行恢复写入。

## 4. 故障与正反例

沿用ADM01—ADM12，不另起产品验收编号：

- 正例：accept完整提交后响应丢失；原完整RequestKey查到同一accepted/初始command，随后reject_existing增加独立保护审计但不改变裁决。
- 正例：reject_new先提交；迟到accept即便换内部key_id、context或digest仍不能突破原namespace/operation/idempotency唯一键。
- 反例：漏初始command、reservation、commit、audit、notification或rejection任一必需写入，COMMIT失败且全表回滚；不得已经返回202。
- 反例：相同原key改digest、相同拒收操作改目标、跨key配对command/commit/通知、删除墓碑、REPLACE覆盖原件均拒绝；重算公开摘要不改变归属。
- 边界：issuer_epoch不同可形成不同存储身份，但不证明新主体已被签发或允许操作；关闭namespace后保护仍可执行，新受理拒绝。
- 限制反证：合成占位BODY可通过SQL非空检查，说明JCS、权限、动态参数及真实证据仍由writer与SDK验证，不能从SQL成功推断它们成立。

[check_storage.py](check_storage.py)只连接`:memory:`。逐写切点通过主动异常回滚，全表快照对比覆盖原件和通知；两个先后顺序为串行操作，不是多连接竞争、掉电或WAL证据。报告绑定本文、SQL、检查器和命令Schema；`--report`执行并记录，`--check-report --staged`只核暂存字节。实际SQL版本在报告中记录，不据此批准产品引擎。

本子域布局与关联方案已具体化；完整Controller执行/保护DDL、当前提供者的实现、Seamer身份列/SDK统一迁移、生产配额及归档GC仍需后续工作。ADM运行验收、HTTP、磁盘、监督器和设备均未执行。
