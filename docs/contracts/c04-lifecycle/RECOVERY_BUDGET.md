# 恢复代次预算准入与共享容量候选

状态：`approved=false`。承接[99表保护消费](PROTECTION_CHARGE.md)，新增[恢复约束](recovery-budget.sql)、[102表组合](seamer-recovery-budget.sql)、[生成器](build_recovery_budget.py)、[参考事务](recovery_budget_model.py)、[检查](check_recovery_budget.py)及[报告](recovery-budget-report.json)。仅设计及内存验证，保留旧SQL产物和公共draft.4／IPC0.3，尚未迁入唯一SDK。

## 已知事实与本轮边界

旧99表只能按arm操作找到预留。恢复R2虽然增加generation，却没有新预算原件；新代次保护因缺账户而拒绝。本候选将R2与新预留及最后封存强制关联，继续保留旧代次已持有和已消费的额度。（证据：[旧消费查询](protection_charge_model.py)、[本轮SQLite约束](recovery-budget.sql)）

109项内存SQLite检查通过：新旧账隔离、逐项漏写和写后异常回滚、四维容量不足、重算摘要后的绑定错配、R4前消费与库存增长、恢复失败保护及显式reconcile R5。旧99表82项实际回归通过。所有身份、库存、时钟、资源clear与设备观察均为合成前提，不能据此声称真实授权、物理容量或设备关闭已验证。（证据：[本轮检查及报告](recovery-budget-report.json)、[旧布局报告](protection-charge-report.json)）

## 字段与身份

| 对象 | 具体字段及规则 |
| --- | --- |
| budget_account | operation_id主键引用lifecycle_operation_identity；run_id、generation、kind精确对应真实预留原件；UNIQUE(run_id,generation)。kind为arm或recovery，由各类预留AFTER INSERT登记。不能建立没有预留的空账户 |
| recovery_budget_reservation | operation_id主键引用recovery_operation；profile_digest引用实例profile；logical_rows、logical_bytes、queue_slots、work_units四个内部有界INTEGER；preview_digest、manifest_digest、request_digest绑定R2原件；budget_body复用既有Reservation具名Schema，audit_body必填 |
| Reservation.binding | scope、run_id、新generation、operation_id、artifact_digest、inventory_digest、profile_id/revision/digest、forecast六维。所有对外计数仍为规范十进制字符串，不经浮点；binding_digest由参考writer按既有规范重算 |
| recovery_budget_commit | operation_id主键；binding_digest、preview_digest、manifest_digest；非空audit_body、notification_body。反向延迟外键使recovery_operation和新预留不能单独提交 |
| protection_budget_reservation | arm和recovery预留的UNION ALL视图，保留同形四维原件并显式给出run_id/generation/kind。pb_use引用真实budget_account表，不能把视图用作外键目标 |
| pb_balance | 对两类预留统一求spent/held/episodes_left。原budget_body保留当时held快照，当前余额必须从不可变消费账计算 |

全部新原件不可修改或删除。两类预算使用同一实例容量：普通arm及恢复R2的count和四维SUM均统计完整共享预留集合。消费、applied、R5完成或新代次出现都不释放容量，不能将spent重复出售。当前profile仍只有不可变单例，更新、释放和GC尚未实现。

## R2、R4及保护时序

1. 当前授权先检查，持久操作身份先查原。相同operation或同epoch/actor/kind/key必须对应完全相同请求摘要，且已有预算seal；查原不受新库存或满额影响，不新增预留。
2. 新请求在`BEGIN IMMEDIATE`内核对原R2的paused、预览/槽位修订、时钟窗口、旧资源clear前提，并确认human、可信库存和Controller容量前提。采用实例当前profile计算新代次整份预留，旧代次预算不能挪用。
3. 原R2完整写集先写操作、execution、锁、全部准备目标/登记、预览消费、run/slot投影、pr_commit；随后写恢复预算及最后recovery_budget_commit。容量不足或任一失败使这整笔回滚，预览不消费、修订不推进、旧账不改。
4. 最后seal再次检查preparing revision1、paused且dispatch关闭、run/execution/generation、槽位、已消费预览、pr_commit和预算的摘要对应、发布artifact、profile身份、dependency水位、来源同步及DENY。实际同run的历史execution、准备、提交、Controller并集不得超过forecast，新预算不能已有消费。
5. R3沿用全部准备当前资格。R4新增数据库守卫：预算seal与当前profile、共享账户必须存在，全部实际库存仍不超过forecast，且该新代次没有任何pb_use。已有消费即使还剩一份也不允许继续原恢复启动；不能仅凭budget_body里的held判断。
6. R4成功后按原恢复执行与R5协议推进。reconcile成功必须同时完成run、operation、execution、锁释放及flow_commit_seal；预算仍保留。新故障按受损generation找到新恢复预留，旧失败重试仍只消费旧arm池；既不互相代付，也不修改另一代次run。

参考writer复用原Profile/Shape/Reservation验证和成本公式，SQL重核身份、范围、计数与四维计算，但SQLite没有内置本项目的规范摘要实现，不能独立证明恶意writer提供的binding_digest等哈希正确；最终可信writer及SDK摘要入口仍须归并。inventory_digest由合成可信库存上下文提供，SQL的实际集合计数不能替代完整外部资源证明。

## 故障与验收

| 故障/正例 | 验收结果 |
| --- | --- |
| R2每个写项省略、任一写项后异常 | 全部102表回到事务前；旧R2 writer漏新预算不能提交 |
| 错preview/manifest/request/profile，重算摘要后错run/gen/artifact | 拒绝；不能以内部摘要自洽代替跨原件关联 |
| 四维任一少留、库存低估、seal前新增依赖 | 拒绝并回滚预览、slot、操作及新预留 |
| 旧arm刚好占满任一维 | 恢复失败；已有预览不消费；四个维度分别验证 |
| arm+恢复恰好等于容量 | 允许；随后另一run的新arm必须计入恢复占用而被拒绝 |
| 旧池耗尽，新恢复池完整 | 旧重试只扣旧池；新R4及显式R5仍可成功；新保护消费恢复账户 |
| R2后、R4前发生消费或库存增长 | 缓存的R4写集同样拒绝，锁存不被清除 |
| R4后恢复步骤unknown | 创建保护并消费新代次预留，run保持paused |
| 重复R2/预算满额查原 | 返回原操作，全库零写；同键异正文拒绝 |
| 新原件UPDATE/DELETE、空账户 | 拒绝；已消费和原预留不能篡改或抹除 |

## 剩余冻结与实施证据

- 102表解决恢复代次缺预算；零run来源计划仍缺实例应急账户，保持原最终范围，下一轮补该账户及独立限额。主体/设备层级、保护观察后续成本、精细跨run分摊、完整CostManifest仍未闭合。
- R4重检只是该启动点的预算门槛；长期armed运行中库存增长、每次事件/准备/提交的前置容量准入、profile变更及预算不足退役策略仍需整体联接。不能用保护时拒绝来宣称直播故障均有足额处理空间。
- 逻辑行/字节包络与合成计量不是SQLite页/WAL、磁盘预分配、CPU、调度或实时队列证明。尚无退款/GC，长时间运行会达到有限实例容量，不能作为生产部署方案放行。
- AUTH/TIME、受监督volatile_close、真实Controller输送与唯一发送出口、可信旧资源clear、完整API/IPC/SDK归并仍待完成。实际服务、并发、磁盘崩溃、NTP、网络及设备检查未运行，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_recovery_budget.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_recovery_budget.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_recovery_budget.py --check-report
```
