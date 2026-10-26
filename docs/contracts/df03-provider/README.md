# 时间提供者同库采用与撤回候选

本方案基于现有契约的分析与推荐，approved=false。它把[受信监督准入来源](../df02-supervisor/TIME_PROVIDER_SOURCE.md)接入Controller侧完整原件存储；不改变已批准draft.4／IPC 0.3，不修改业务服务。

## 1. 当前事实与范围

现行采集日志含时间十四表、采集出口十一表和入站两表，共27表，tc_channel只持运行Ref、间隔Ref和Channel正文。本候选在同一连接追加3表，将完整ProviderRuntime、Channel、Configuration和初始State绑定为30表事务。Schema见[adoption.schema.json](adoption.schema.json)，SQL见[storage.sql](storage.sql)，实现边界见[参考模型](adoption_model.py)。

ProviderRuntime来自已打开的受信监督连接，调用者不能直接提交一份自造JSON替代capture。核心自身启动身份、配置批准的当前权威、稳定来源槽和间隔提供者仍属于未接通的可信边界。保存了完整approval正文，不代表已证明它当前有效；本模型不签发授时、采样发送、UTC许可或OPEN资格。

## 2. 字段与写集

| 对象 | 固定关系 |
| --- | --- |
| Adoption.runtime | 完整准入原件；runtime ID、摘要、正文与tp_runtime逐项相等 |
| Adoption.channel | 完整0.2 Channel；channel_id必须为监督AdmissionReceipt的channel_binding_id，domain与配置一致 |
| bootstrap_receipt_ref | id为原receipt_id，revision固定1，digest为完整AdmissionReceipt的JCS摘要；Channel和Configuration精确回显 |
| Configuration | 完整source/profile/policy/approval及各自摘要与Binding Ref；collector制品与监督manifest及profile一致 |
| bootstrap_state_ref | 完整collecting State的固定Ref，首次revision=1，无Anchor、无Invalidation |
| 采用持久身份 | source_slot_id、binding_storage_id、bootstrap_commit_id、interval_receipt_ref均进入摘要并与物理列相等；重复采用不得换参 |
| tp_adoption | 绑定runtime、channel、时间Binding及bootstrap commit；审计和outbox保存同一完整采用正文 |
| tp_revocation | 绑定固定采用Ref、Invalidation Ref及cause_ref；连接原channel、同一失效commit及固定STOP意图 |

Revocation还固定invalidation_commit_id和next_binding_storage_id；重复请求不得换后继Binding，查原重新核完整Invalidation、STOP意图及已封存不可用State。

首次采用在BEGIN IMMEDIATE内执行十步：runtime → Binding → adoption → bootstrap commit → audit → outbox → State → head → seal → Channel。原tc_channel要求已封存collecting State，因此seal在Channel之前；adoption到Channel的延迟外键保证缺Channel不能提交，State及Channel触发器要求反向存在正确adoption。仅在事务提交成功后返回候选采用结果。

撤回亦为十步：新Binding → invalidate commit → audit → TIME outbox → Invalidation → revocation → STOP意图 → unavailable State → head → seal。时间代次严格递增；STOP与撤回相互绑定，漏写任一项不能提交。不可变原件不可更新或删除，撤回不删除历史采用、不清在途采样、不释放资源。此处STOP是持久意图；有序出口随后才能分配真实sequence/cut，不能把此意图当STOP帧或ACK。

该轮覆盖首次采用和其撤回。已有时间State时不接收新的首次采用，也不覆盖原绑定；后续重采集和跨域重建要走完整恢复设计，不能通过换channel或清表绕过。旧同一采用重投仅精确查原；提交后的观察错误不得当回滚、不得重复创建监督成员。

## 3. 读取与竞争边界

read要求调用方事务，核Schema、自摘要、完整物理列、原bootstrap State及来源正文；bootstrap回执、审计、outbox和seal必须保存同一采用正文。current再读取当前State、绑定完整运行域并查撤回墓碑。调用者不再给current传入任意expected_provider_domain。current只表示**该SQLite读快照中的采用来源可用**；实际writer、当前授权与监督闭锁仍须在最终动作前共同核验。

监督capture结束后发生退役，Controller仍可能提交与旧快照一致的采用记录。这是已知跨库竞争，双读相等或本地COMMIT不能消除。生产需在受监督域内串行化准入/失效并将失效投递到核心，最终设备门仍核完整运行域资格。当前模型不声称这一竞争已闭合，也没有将历史OS观察转换成存活证据。

收集到qualified时间证据之前，采用只产生collecting且没有UTC锚。Provider撤回后仍能查历史正文，但current、旧Binding登记采样以及旧配置重新bootstrap均拒绝。对无需UTC的即时控制如何保留本机单调域拒绝下界，要由恢复/OPEN组合接线处理；本候选不把失效提供者当作当前资格，不自行替换时间Domain。

## 4. 故障与验证

| 切点 | 预期 |
| --- | --- |
| 采用或撤回任一写入主动异常／漏写 | 拒绝，全部30表回到事务前内容 |
| COMMIT成功、调用方观察丢失 | 固定记录仍可查，重投零新写入 |
| Channel、bootstrap或制品错绑，重新计算摘要 | 仍拒绝，摘要不能代替身份关联 |
| 外部事务已开启 | 不接管且不回滚调用者事务 |
| 撤回重复、撤回后查历史 | 返回原件，不能恢复当前资格 |
| 原监督成员已退役或未知 | capture拒绝新采用；历史读取另走read |

[检查器](check_adoption.py)在完整27表采集布局和真实SQLite内存事务上追加3表，以完整合成监督原件、配置和来源槽验收。另以串行交错实际复现监督读提交后转retiring、核心采用仍可提交且本地current仍可读的边界；下一次监督读取拒绝。该反例不冒充真实并发或OS退役实验。报告见[adoption-report.json](adoption-report.json)。未执行真实IPC、NTP、OS进程、磁盘故障、跨库并发或设备操作；最终批准、核心身份、TIME保护账本、完整290表恢复组合及OPEN仍待接通。
