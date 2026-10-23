# 运行增长与完整动作计划的预算准入候选

状态：`approved=false`。承接[来源独享预算](SOURCE_BUDGET.md)，在同一106表布局上增加视图与守卫，不新增账本或改写历史产物。[增量SQL](workload-budget.sql)、[生成器](build_workload_budget.py)、[组合SQL](seamer-workload-budget.sql)、[检查](check_workload_budget.py)、[报告](workload-budget-report.json)共同构成本候选。公共draft.4／IPC0.3不变，未归并唯一SDK，未实现业务服务。

## 已知事实

原候选在普通布防、恢复和保护消费时核对forecast，但运行期间新增执行、准备、依赖及命令仍可超过预留的形状。若直到保护消费才拒绝，已发生的动作不能撤销。仅在逐命令提交时限流，也可能让前面的动作已发出后才发现同一次执行的剩余动作无额度。（证据：[原保护shape](protection-charge.sql)、[恢复seal](recovery-budget.sql)、[实际摄取计划写集](trigger_flow_model.py)）

本轮86项内存SQLite检查通过；原来源独享候选的90项回归保持通过。检查实际经过普通布防、8次双动作执行与R5、满额拒绝后的P1，以及新代次恢复R2/R4/R5。合成提供者布尔前提不证明身份、时间、设备、进程关闭或磁盘保障。（证据：[本轮检查与输入绑定](workload-budget-report.json)、[原候选回归](source-budget-report.json)）

## 推荐冻结规则

每个已有预算账户必须容纳其仍需保护的库存以及完整动作计划的未来命令槽。新工作只能使用当前代次仍有保护份数的账户；全部有剩余额度的旧账户继续接受检查。耗尽的旧账户不再允许消费或承担新工作，其历史记录仍计入新代次的库存，不删除、不退款。

| 投影 | 字段与规则 |
| --- | --- |
| `wb_command_slot` | execution_id、step_id、run_id、arm_generation、authority、database_id。每个action步骤先占一个槽，与同执行/步骤/目标的实际submission作集合并集，提交不重复占位 |
| `wb_shape` | operation_id、run_id、generation，以及dependencies/runs/executions/preparations/submissions/controller_targets六维；按预算账户而非临时保护plan计算 |
| `wb_current_account` | 当前run代次且`episodes_left>0`的账户，不凭客户端`budget_valid`放行 |
| `wb_overflow` | 对每个尚有保护份数的账户，任一维超过原`binding.forecast`即列出；等号允许 |

dependencies按run全量计数；runs固定1。executions、preparations及命令槽仅计入代次小于等于本账户代次的记录；U20先补齐20位再比较，不转换成有符号SQLite整数。controller_targets按准备记录与命令槽的`authority/database`二元组去重。同目标的多个动作分别占命令槽；`delay/retain_success/reconcile_commit`不产生设备命令槽。已完成、失败、未提交和未知动作的占位都保留，完整引用清理方案确定前不释放。

`wb_shape`是保护shape的保守上界，而不是替换实际消费账本。`pb_use`继续以实际保护写集、真实库存shape和原四维包络计费；本候选不会将逻辑槽位数量称作磁盘页、WAL、CPU或真实工作队列容量。

## 原子顺序与边界

1. 普通摄取在原`BEGIN IMMEDIATE`事务中建立执行、完整步骤计划和状态。execution、p1_preparation、p1_dependency、execution_step_plan、command_submission插入后重算本run的所有剩余账户，超额立即报错；参考writer回滚整笔事务。
2. 计划创建和封存要求当前代次账户有效；action必须含非空文本Controller scope。整个计划封存及执行进入running之前，全部动作槽和目标并集已接受检查。任一后置动作超额时，摄取、执行、计划、水位和通知共同回滚，此执行没有可发送的第一条命令。
3. submission必须对应已占位的action步骤及相同Controller scope。提交使用既有槽，不得换目标少计或重复获得额度。原计划摘要、请求参数、准备资格、授权和发送守卫继续独立生效。
4. R2原协议先写新operation/execution/preparation，再写新预算。因此仅精确匹配尚未封存、preparing修订1的R2允许暂时缺新账户；新preparation还须匹配当前active_operation和新generation。该例外不能用于普通trigger，最后预算seal及反向延迟外键仍必须完成。
5. 普通arm和R2的最后seal重核增长shape，包含历史未提交动作；R2不能只根据已提交的command数量少留预算。准备登记的暂态只有在完整事务提交后才可供外部消费者使用。
6. 新代次执行和准备不会扩大旧代次shape；新增依赖影响整个run，因此必须同时满足所有仍有额度的旧账户。新预算更宽并不允许破坏旧保护所需边界。
7. 初始generation0、disarmed的配置可以登记依赖，arm最后seal负责首次核验。此后新增依赖需要当前有效账户。已在途的accepted/terminal等证据采用原裁决规则，不因本轮新增准入守卫而拒绝保存；记录证据不等于重新获得派发权限。

SQLite语句级`RAISE(ABORT)`不是自动回滚整个外层事务的承诺。可信writer必须捕获失败并ROLLBACK；不得吞掉错误后COMMIT剩余写项。测试对每个异常都比较完整数据库快照，并未仅检查失败语句返回值。

## 故障序列与验收

| 场景 | 已执行的断言 |
| --- | --- |
| 每个普通摄取写项后故障 | 全库与事务前一致，无半个execution或递增水位 |
| 8次双动作完成，共16命令 | 每轮shape精确增长，准备/命令目标去重；第9次整笔拒绝 |
| 满额后重复第8个事件、随后P1 | 查原零写；原两份保护额度仍在，P1成功消费一份 |
| 仅一个命令余量，计划包含两个动作 | 在任何attempt产生前整笔拒绝；没有部分执行 |
| 两动作同一Controller | 两个命令槽；目标集合按二元组去重 |
| 两个准备目标再加两个新计划目标 | 第四个目标使整次摄取回滚，不能等submission才检查 |
| 缺Controller scope或提交时换scope | 拒绝；原计划槽不会变成另一个目标 |
| 计划尚无submission／计划已有submission | 两种情况下均保留两个槽，不重复计数 |
| 来源和run保护耗尽后迟到accepted | 原身份证据可存，不能新发送 |
| 4个依赖已满，第5个依赖 | 整笔回滚；新预算允许6个也不能绕过尚有额度的旧4个限制 |
| R2逐写项故障／省略新预算或seal | 全库回滚，暂时缺账户例外不能成为持久缺账 |
| R2新增执行与两个准备 | 新shape含旧库存，旧generation shape保持不变；后续R4/R5完成 |
| R2只留3个准备或1个命令槽 | 实际4准备、历史2个未提交动作分别在最后预算seal拒绝 |
| 普通执行伪造generation999 | 无当前账户，拒绝 |

本候选对新库顺序安装并运行全部守卫。原来源夹具仅增加`sql_factory`入口以复用种子和完整启用流程；不禁用触发器、不修改不可变profile，也不把已有数据库视为已升级。

## 剩余冻结事项

- 目前保证的是六维库存与未来action槽不会超出原forecast。动态动作展开必须先成为完整不可变计划并通过同一准入，不能运行中凭参数偷偷增加动作；完整AST、并行/依赖语义仍需与最终SDK归并。
- 事件、快照、观察、审计以及计划正文等长期字节增长尚需完整CostManifest、实例/主体/设备层级额度和引用感知归档/GC。固定库存上限会最终拒绝新工作，尚不能支撑无限期直播运行。
- 新候选没有自动提升预算或换代续杯，也不因R5、applied或关闭而回收历史。恢复新预算仍占共享原容量。
- 来源恢复、AUTH/TIME无run保护、真实Controller输送/唯一出口、SDK同版归并、真实容量测量及持久化故障验证继续待完成。真实服务、并发、磁盘崩溃、网络与设备验收均未运行；阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_workload_budget.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_workload_budget.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_workload_budget.py --check-report
```
