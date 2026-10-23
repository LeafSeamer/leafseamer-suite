# 来源重新同步与恢复资格边界候选

状态：`approved=false`。本候选落实[C05来源基线与连续补齐规则](../../rebirth-c05-event-sync-design.md)，承接[运行增长预算](WORKLOAD_BUDGET.md)。提供[具名Schema](source-resync.schema.json)、[增量SQL](source-resync.sql)、[109表组合](seamer-source-resync.sql)、[生成器](build_source_resync.py)、[参考writer](source_resync_model.py)、[离线检查](check_source_resync.py)和[报告](source-resync-report.json)。公共draft.4／IPC0.3及既有产物保持原样，尚未归并SDK，也未实现真实订阅或设备操作。

## 已知事实与本轮范围

已确认C05要求新快照只建立来源基线，后续连续增量完成同步；旧缺口、旧事件拒收floor与运行暂停不得被抹去。既有`ingress_source`存储只有单调更新约束，缺少绑定恢复证据的完整事务原件。（来源：[C05第3节及订阅规则](../../rebirth-c05-event-sync-design.md)、[原来源保护写集](../c05-protection/storage_model.py)）

本轮148项内存SQLite与Schema检查通过，覆盖三阶段逐写缺失/故障、来源身份与水位、重复查原、零run来源、保护额度不回充、补齐限额及显式R2/R4/R5。另发现一项尚未关闭的跨项问题：恢复准备绑定单一execution，而恢复R5默认回armed；后续正常触发仍缺可靠的继续运行准备转交。测试明确保留该分支的拒绝，不能把来源同步成功描述成完整直播恢复成功。（证据：[本轮检查](check_source_resync.py)、[原准备约束](../c04-preparation/README.md)、[R5释放说明](../c04-storage/README.md)）

## 具体契约

三个请求共用`contract_version, transition_id, baseline_id, source_id, source_key_digest, fault_id, expected_source_revision, delivery_ref, request_epoch, actor.principal_id, idempotency_key`。Ref含scope、id、revision、digest，指向可信提供者验证过的不可变原件；它不替代实际认证或完整订阅Binding。所有计数为规范U20字符串，额外字段拒绝。

| 请求 | 专有字段 | 来源投影 |
| --- | --- | --- |
| Baseline | watermark、snapshot_ref；baseline_id等于transition_id | desynchronized→baseline_required；contiguous_sequence与reject_floor同置可信快照watermark，revision精确加1 |
| Delta | source_sequence、event_ref | baseline_required保持；只允许下一个连续序号，revision加1，floor保持；只存reconcile证据，不创建触发或命令 |
| Ready | through_sequence、last_delta_id、checkpoint_ref | 必须指向本基线最新封存delta，检查点水位等于当前连续水位；baseline_required→synchronized，revision加1，floor保持 |

baseline必须引用本source最新且已完成本地保护记账的P1故障，源修订等于该故障的source_after。来源身份仍使用原不可变source_key，不接受换epoch后清零旧序号。watermark不得小于当前连续水位或拒收floor，也不能等于U20最大值而留下没有下一增量的基线。

delta与ready沿用基线的精确delivery_ref；新连接、运行域或输送Binding失效必须由提供者停止当前链并登记新保护事实，不能改正文继续旧链。同一来源事件原件的scope/id/revision不能更换序号或摘要重复使用。至少处理一个合格连续delta后才可ready；快照本身不触发动作。

当前入口不恢复quarantined或closed，不修改source身份，不补齐无法证明的旧历史，不增加来源独享额度。耗尽来源保护份额时拒绝新的恢复进展；原请求在当前读取授权下仍可查原。

## 持久化与故障顺序

新增三表：

- `rs_limit`：模拟普通存储分区的不可变限额，max_transitions为3..65536、max_deltas为1..4096。
- `rs_transition`：请求原件/摘要、幂等身份、source与fault、baseline关联及完整before/after投影。每个(source,revision_before)唯一；每fault最多一个baseline，每baseline最多一个ready；请求正文最多4096字节，编码行最多16384字节。
- `rs_commit`：同transition_id的最后封存、请求摘要、固定审计和通知。反向延迟外键要求transition与seal共同提交，原件均不可改删。

每步固定在`BEGIN IMMEDIATE`内执行“写transition→CAS更新source→写seal”。最后seal重核全部投影，任何失败由writer回滚整笔事务。直接把source改绿、跳到新floor或在失步状态推进序号均需要对应未封存transition，不能只凭状态字符串完成恢复。SQL的U20加1拆成两个十位整数段，不经double或整体有符号64位转换。

第一次baseline占用整条链的`max_deltas+2`个transition名额，历史占用不回收；每transition固定预留两行，每行按16384字节上界计算。全体基线分配之和不能超过max_transitions，后续delta只能消费本链额度，ready保留独立槽。测试中配置3个transition/1个delta：第二个delta拒绝，但ready仍能提交。这个普通逻辑分区不使用run或来源保护预算，不证明物理磁盘预留；实例完整CostManifest仍需把它与其他分区共同核算。

source同步三步不修改run、execution、业务状态、活动槽、暂停锁存、P1历史、DENY或预算消费。source变绿后收到新live事件时，paused运行仍形成suppressed_inactive决定。旧已提交事件继续查原；未曾摄取且低于新基线的历史事件不能成为新直播动作。

## 与Controller保护和R4的联接

已有R2/R4参考writer的`old_resources_clear`是合成提供者前提。来源重新同步后，仅检查source.state会留下空隙。本候选增加`rs_pending_protection`及R4插入守卫：每个来源对该run的最新P1计划，当前`sp_observed_summary`必须为applied。较旧indeterminate记录保留，但可由同来源针对该run的新保护计划及其当前applied观察覆盖；不能拿旧applied覆盖更新的pending/indeterminate。

R2可以预留新预算与准备；R4才允许运行。缺最新Controller保护观察时R4拒绝且全库回滚，观察完整后原R4可继续。本门槛不把applied解释成设备动作回滚、资源全部释放或当前授权；这些仍是独立资格。

## 实质冲突：R5之后的继续运行准备尚未定稿

已知约束有两条：

1. [准备候选](../c04-preparation/README.md)规定recovery准备只允许其execution_id，不能直接用于下一个trigger。
2. [恢复存储说明](../c04-storage/README.md)要求R5释放证据说明准备grant已明确转交当前run继续使用或经撤销核对，但目前没有对应的持久转交原件和Controller采用协议。

实际串联证明：source恢复→新代次R2/R4/R5可以完成，随后新trigger会在command_submission处因目标未准备被拒绝。该结果不满足持续直播恢复目标。本轮将已有准备作用域检查前移至完整计划seal，缺任何目标资格时整次摄取回滚，避免部分动作已发送；保留原recovery execution限制，不把它改成run通用授权。

**推荐下一轮冻结显式继续运行转交协议**：由新的人员授权/预检确认持续运行范围；每Controller返回不可变的`RunContinuationReceipt`，至少绑定原preparation/恢复execution、origin与Controller scope、run/generation、持续运行的已批准plan_ref、控制/授权修订和新的范围摘要。原recovery准备不改写；追加的继续运行资格必须与共享撤销、唯一出口和保护关闭保持同一约束。Seamer只有取得完整目标集合并持久采用后，才能宣称具备正常触发资格。R5之前或之后执行转交、转交失败时run的精确公开状态，以及旧grant资源释放的证明边界，必须与Controller契约一起定稿；不能仅在Seamer增加布尔字段或复用合成release证据。

这项协议目前只是推荐方向，未实现、未批准。恢复后正常trigger成功用例仍是必需交付项；本轮拒绝用例只是证明不会复用越界准备，不能代替最终正例。

## 验收与剩余事项

148项检查包含：三步各写项省略/写后异常全库回滚；字段缺失、SQL原件/投影错配、身份冲突；基线不直接同步、ready需要最后连续delta；重复事件、跳号、过期故障、换输送绑定、U20安全整数和十位进位；零run同步；隔离/关闭/额度耗尽拒绝；分区满额不抢ready槽；来源同步不清锁存、不退款，R4必须有最新保护观察。

真实快照完整性、新鲜度、输送世代、源身份、连续增量和检查点验证仍由合成上下文提供；event_ref只持久绑定已验证证据，完整领域观测投影、订阅分页/追赶、edge baseline重建及最终公共API/SDK尚须联接。真实服务、并发、磁盘崩溃、网络和设备验收均未运行。继续运行转交、普通存储总容量/GC、AUTH/TIME及最终SDK未齐，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_source_resync.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_source_resync.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_source_resync.py --check-report
```
