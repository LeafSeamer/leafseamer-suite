# 来源启用与独享保护份额候选

状态：`approved=false`。承接[104表实例分区](INSTANCE_BUDGET.md)，新增[Admission Schema](source-budget.schema.json)、[来源预留约束](source-budget.sql)、[106表组合](seamer-source-budget.sql)、[生成器](build_source_budget.py)、[参考事务](source_budget_model.py)、[检查](check_source_budget.py)及[报告](source-budget-report.json)。保留旧产物及公共draft.4／IPC0.3，尚未归并唯一SDK，不实现业务服务。

## 已知事实与推荐方案

104表限制每个source最多消费若干次，但所有source仍竞争同一个实例池。检查“现在还有余额”不能证明已启用的每个source都有自己的份额。本候选在来源首次启用时分配不可重用的份额，消费只使用本source已分配额度。（证据：[104表实例池](instance-budget.sql)、[106表预留约束](source-budget.sql)）

90项内存SQLite与Schema检查通过。正常来源在其他来源耗尽后仍能经过真实候选写集完成事件摄取、两个动作和R5；本来源耗尽时缓存的摄取、ready、submission、attempt写集均拒绝，已在途accepted证据和原身份查询仍可记录。（证据：[检查源码](check_source_budget.py)、[绑定报告](source-budget-report.json)）

推荐把`ingress_source`视为可保存的待启用配置，把已封存的`sb_reservation + ingress_registry + sb_commit`作为来源启用事实。待启用配置不能建立运行listener/保护依赖、提交正式摄取或使用来源保护池；它尚未取得执行影响资格，不应伪造P1已保护回执。初始来源身份及同步证据继续由可信提供者确认，不凭配置状态字符串自行联网放行。

## 字段与容量不变量

| 对象 | 具体契约 |
| --- | --- |
| Admission | contract_version、source_id、expected_source_revision、source_key_digest、pool_profile_digest、episodes、request_epoch、actor.principal_id、idempotency_key；具名Schema、无额外字段，计数为规范十进制字符串 |
| sb_reservation | source_id主键；reservation_id由规范请求摘要导出；pool_id、profile_digest、source_revision/key_digest、内部有界episodes、请求身份与完整request_body/digest。每来源只有一份准入原件，幂等键全实例唯一 |
| sb_commit | source_id主键；reservation_id、request_digest、registry_revision固定初始1；非空audit_body及notification_body，绑定完整来源注册 |
| sb_balance | 每来源已分配份数减本source的ib_use数；episodes_spent单独保留 |
| sb_unallocated | 实例总份数减所有sb_reservation.episodes。这里不减spent，因此消费后不能把相同额度再次出售 |
| sb_run_eligible | 本run的全部p1_dependency均存在已封存且余额大于零的来源预留；不能只检查事件入口的那个source |

对全池有：`未分配份数 + Σ(每来源held + 每来源spent) = 原实例池份数`。每个请求分配1..该profile的per_source_episodes，内部最大65536；所有来源分配之和不得超过实例总份数。申请一份只能消费一份，即使该profile允许每来源最多两份、池里还有未分配份数，也不能绕过已签发的独享范围。

source身份键沿用原不可变source_key；名称、连接、detector或状态变化不重建额度。来源关闭、全池满额、消费、applied、重启和查原不释放分配。当前不允许追加、替换或撤销这份分配；完整关闭/归档/GC证据未定稿前不能实现“删除来源腾额度”。

## 原子启用与门槛

1. 入口先校验Schema及当前授权，按source_id或request_epoch/actor/key查原。原请求字节一致且seal存在，零写返回原件；不同请求不能替换同source、换source占用同幂等键或补充值。
2. 新请求在`BEGIN IMMEDIATE`内核验human/current/source_identity_verified前提，source_key摘要、source修订、当前pool摘要及同步状态。`source_identity_verified`是合成提供者前提，不代表实际认证实现。
3. 同一事务写sb_reservation、初始ingress_registry、最后sb_commit。SQL重新计算分配总额，并核对请求/列、source及注册投影；三个对象反向延迟关联，任一漏写或故障全部回滚。缓存写集不能越过其他已提交的份额占用。
4. 新listener和p1_dependency必须引用有余额的已启用来源。新arm、恢复R2、arm就绪、R4、step_ready、command_submission及submission_attempt再次核对本run全部依赖来源的余额。正式ingress_commit按inbox.source_id核对来源余额；重复摄取先查原，不重新消费份额。
5. P1继续走实例消费与完整run消费共同封存；ib_use.source_id现在引用独享预留，source_ordinal不得超过该预留episodes，不能借其他来源或未分配池余额。其他来源耗尽不减少本来源的独享份额。
6. 耗尽停止新工作，不拒绝历史查询或已在途证据。已存在attempt只查原command身份；迟到accepted依原裁决规则保存，不能清锁存、重开自动化或生成新的设备发送。

来源准入的元数据也有成本。参考writer和SQL将reservation行、registry初始行、seal行分别限制在8192/2048/4096逻辑序列化字节内；BLOB按十六进制表示计量。每笔来源保护消费还须满足`observed_rows + 3 <= per_episode.logical_rows`与`observed_bytes + 14336 <= per_episode.logical_bytes`，保守将准入三行计入每份包络。SQL重核行长、关联和数额，但不自行证明规范摘要或提供者身份的真实性。

## 验收与故障序列

| 场景 | 结果 |
| --- | --- |
| 准入三写项逐条省略/写后故障，直接旧registry写入 | 全库回滚；没有半启用来源 |
| 缺字段、非规范U20、超内部整数界、错source修订/key/profile | 拒绝；不修改剩余额度 |
| 两来源各两份占满四份，第三来源申请 | 第三来源拒绝且不注册；缓存准入写集同样不能超卖 |
| 来源消费完或关闭后再启用第三来源 | spent仍占原总额，拒绝重新分配 |
| 同来源申请一份，其他池余额充足 | 第二次消费拒绝；其他来源仍可申请剩余未分配份额 |
| 其他来源两份耗尽，本来源仍有两份 | 本来源正常事件、双动作及R5成功，保护份数不被普通动作消费 |
| 本来源耗尽后的缓存摄取/ready/submission/attempt | 在数据库插入边界拒绝，全笔回滚 |
| 耗尽后原事件/准入/attempt重试，迟到accepted | 查原零写或保存原身份的证据，不重发、不充值 |
| 省略来源准入元数据成本 | 即使observed等于原每份上限，也因需加三行/14336字节而拒绝 |

测试以旧夹具取得公开合成种子，在新库按“基础配置→实例池→来源准入→运行登记”的顺序执行全部守卫。没有关闭触发器、修改不可变profile或将旧库强行视为已迁移；这些检查不是数据库升级方案。

## 剩余冻结事项

- 已有来源独享分配设计，尚未解决主体/设备层级额度、每次运行库存增长的容量准入、完整CostManifest、队列/工作槽释放、引用感知归档与GC。来源预留仍是有限不可变占用，不是可持续运行容量证明。
- 每次保护都受run与实例两层预算和实际写集界约束。独享来源份额不能替代run预算，不能保证磁盘故障时写入成功，也不赋予真实网络/设备关闭能力。
- 全部运行依赖索引的完整性、长期事件增长、快照/观察保留以及AUTH/TIME/storage等无run保护类型继续待收敛。当前新增门槛仅约束来源额度，不宣称已覆盖全部未来容量变化。
- 真实身份、NTP/时钟、受监督关闭、Controller输送及唯一出口、API/IPC/SDK同版归并仍待完成。实际服务、并发、磁盘崩溃、网络及设备验收未运行；阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_source_budget.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_source_budget.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_source_budget.py --check-report
```
