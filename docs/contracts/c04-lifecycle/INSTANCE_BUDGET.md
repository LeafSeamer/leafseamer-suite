# 来源保护实例分区与零run记账候选

状态：`approved=false`，承接[102表恢复预算](RECOVERY_BUDGET.md)。新增[具名PoolProfile Schema](instance-budget.schema.json)、[实例约束](instance-budget.sql)、[104表组合](seamer-instance-budget.sql)、[生成器](build_instance_budget.py)、[参考事务](instance_budget_model.py)、[检查](check_instance_budget.py)和[报告](instance-budget-report.json)。旧产物及公共draft.4／IPC0.3保留，本候选不实现业务服务。

## 已知事实

原P1支持零受影响run的来源故障完整写集，但99/102表的pb_commit要求至少一个run账户，因此该分支不能提交。来源更新、故障原件、计划、审计和通知即使没有Controller目标也占用资源，不能用虚构run预算填补。（证据：[P1参考写集](../c05-protection/storage_model.py)、[原消费约束](protection-charge.sql)）

122项内存SQLite与Schema检查通过。零run可以独立记账；有run时实例池和完整run账户必须共同消费；跨run一次来源计划只扣一个实例账户，仍分别扣每个run；两计划同事务连续编号及额度不足整笔回滚。测试实际向P1的全部sp_target提交合成applied观察后核对状态，不借用只覆盖失败重试的查询。（证据：[检查源码](check_instance_budget.py)、[绑定报告](instance-budget-report.json)）

## 推荐设计：固定分区而非额外容量

四维分别为logical_rows、logical_bytes、queue_slots、work_units。启动时对每一维要求：

`total_capacity = arm_capacity + per_episode × episodes`

arm_capacity继续包含所有arm/recovery预算的held与spent；等式右侧第二项是单独保留的来源保护区。两区均不可互借。source池每次消费一份，余额由不可变消费记录求得；applied、R5、重连、时间流逝和重复请求都不退款。当前不实现分区重配、释放或GC。

示例profile只用于模拟：总4份，每来源最多2份，每份2048逻辑行、33554432逻辑字节、64队列槽、4096工作单位，最大行16384字节、等待严格小于500000000ns。这是可复现的实验参数，不是已测定的生产需求或承诺。实际所有最大规模、观察与存储成本仍须通过完整CostManifest定值。

## 字段、关联与限制

| 对象 | 契约 |
| --- | --- |
| PoolProfile | contract_version、profile_id、scope、purpose、arm_profile_digest、total_capacity、per_episode、episodes、per_source_episodes、max_row_bytes、max_queue_wait_ns；根Schema不可实例化，通过具名定义校验；purpose目前仅simulation |
| ib_pool | 单例1，绑定storage_scope和arm_capacity摘要；保存完整profile及摘要、总容量和每份四维、全池/单来源份数、行界、等待界、审计。只能在任何生命周期操作或保护计划之前建立，UPDATE/DELETE拒绝 |
| ib_use | plan_id主键引用p1_plan，pool_id、source_id、全池ordinal及source_ordinal、profile/fault/plan摘要、四维整份消费、实际逻辑行/字节/最大行、elapsed_wait_ns、measurement_body、audit_body；反向延迟引用pb_commit |
| ib_balance | 原总份数减已持久消费数；每维held与spent之和始终等于该来源区原预留，不读取被改写的快照 |
| pb_commit | 每个P1必须有且仅有一条ib_use；零run仅对真实P1计划放宽run账户非空要求。有run时原完整run账户集合比较保持，其他保护类型不能利用零账户例外 |

U20保持规范十进制字符串。参考writer在绑定SQL前核验内部四维1..10^12、全池份数1..65536、单来源份数1..全池份数、最大行1..1048576；越界明确拒绝，不能依赖SQLite整数溢出或浮点转换。SQL重核四维分区等式、正文/列对应、连续序号、精确原件关系及半开等待界。

同一个source使用固定的单来源累计额度，不因detector变化、source修订或连接重建清零。实例总额同时约束所有source；单来源上限限制一处故障的占用，但不保证任意数量的新source均预留了独享次数。来源数量与准入预留仍须后续联接。

## 事务与故障时序

1. 来源故障入口先确认可信故障及系统关闭资格，再确认受监督关闭、同域等待证据。ctx字段仅为合成前提；未实现实际进程门控。
2. `BEGIN IMMEDIATE`内按fault_id或detector_domain/sequence查原；全文相同且ib_use/pb_commit齐全时零写返回原计划。不同正文拒绝，耗尽不妨碍查原。
3. 新计划执行原完整P1写集，保持完整依赖、历史执行、准备、提交、Controller集合以及source/run投影。零run只省略不存在的成员，不能将有run故障伪装成零run。
4. 测量本事务逻辑正文差集，为全部待写run消费、实例消费各计8192字节余量，每个最终seal计4096字节；实例账户保守承担整笔事务峰值，再核其实际序列化行不超余量。SQL检查包络、最大行、全池与单来源连续编号和等待界。
5. 实例消费写入后，原run消费writer重新采样同一事务，使run计量也包含实例行。全部run账户和pb_commit成功才COMMIT；任一维不足、错原件、缺账户或异常，全笔source状态、锁存、run投影和账本一起回滚。
6. 失败返回未确认，不得由数据库仍是旧synchronized/armed推断可以继续派发。受监督关闭及未知在途核对仍是运行层的必要工作，当前模型没有替代实现。
7. 新arm、恢复R2、arm最终就绪和R4新增门槛：实例池必须存在且有剩余额度，本run所依赖source不得已达单来源上限。P1和这些门槛由同writer串行；额度在准备期耗尽不能继续开放。

这些门槛检查当前剩余量，不是在每个run操作中再次独占一份来源配额，也不能证明未来每个故障都能成功持久化。真实空间不可写或预算不足时仍必须保留独立关闭路径。

## 验收覆盖

- 零run的每条写项省略及逐项异常、旧writer漏实例账、缺运行前提、错source/plan/fault/profile/序号、四维少扣、等待等号与非规范U20均拒绝。
- 零run不改其他run、槽、代次预算或锁存；来源明确失步，Controller目标为空，不虚构设备关闭证据。
- 单来源耗尽时另一来源仍可记账；全池耗尽不借run区；run池耗尽不借实例区，且实例账回滚；零run仍可用剩余来源份数。
- 有run的ib_use、pb_use及pb_commit任一漏写均拒绝；跨两个run分别扣账，不能省一个账户。多计划超额时两个计划一起回滚。
- run区已满不挤占预留来源区；启动分区少一单位、错scope/profile及超内部整数界均拒绝。实例池耗尽阻止正在准备的arm完成或恢复R4。
- 正常恢复代次的P1同时消费实例和恢复账户；旧arm账不动。实际合成P1观察到applied后不退款。全库外键检查通过。

## 剩余冻结事项

- 本候选恢复零run最终功能，没有将“缺run账户则拒绝”当成需求删减。实例池当前仅用于来源P1；AUTH/TIME/storage等没有run归属的保护类型还需各自原件和成本契约，不能直接改kind复用。
- 每来源独享准入、主体/设备层级配额、持续运行增长的前置准入、全链调度优先级、完整CostManifest、消费后队列/工作槽释放、引用感知归档/GC仍未闭合。固定不可变分区会最终耗尽，不能据此部署长期直播。
- SQL不能独立证明writer没有伪造逻辑计量或规范摘要；需要唯一SDK和可信writer统一入口。固定8192/4096余量仍属实验包络，真实页/WAL、CPU、磁盘预分配及失败证据未完成。
- AUTH/TIME、实际Controller输送、唯一发送出口、受监督关闭、当前权限与旧资源clear、API/IPC同版归并仍待完成。真实服务、并发、磁盘崩溃、NTP、网络及设备验收未运行，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_instance_budget.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_instance_budget.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_instance_budget.py --check-report
```
