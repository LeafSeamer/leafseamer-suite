# 保护计划与预留消费同库候选

状态：`approved=false`，承接[97表重新关闭](PROTECTION_RETRY.md)与[原布防预算](ARM_BUDGET.md)。新增[消费约束](protection-charge.sql)、[99表组合](seamer-protection-charge.sql)、[生成器](build_protection_charge.py)、[参考事务](protection_charge_model.py)、[检查](check_protection_charge.py)及[报告](protection-charge-report.json)。原预算Schema和旧SQL产物保留，未归并公共draft.4／IPC0.3，不实现业务服务。

## 已知事实

原arm_budget_reservation持有四维预留，但保护计划提交没有强制消费记录。来源P1、准备失效、失败arm退出、动作失败和重新关闭都能引用同一代次；各自计算“尚有两次”会产生重复使用额度的风险。本候选把protection_plan_registry反向延迟引用pb_commit，任何新计划都必须同时封存完整消费账户集合。

82项内存SQLite检查通过。实际从普通arm、事件和动作写集进入失败保护，首关闭扣一份、重新关闭扣第二份，第三次整笔拒绝；同来源两个run分别扣各自预留，缺一个账户不能提交；来源P1与动作失败共享额度，准备撤回不能绕过耗尽；失败arm退出也消费原代次预留。（证据：[检查源码](check_protection_charge.py)、[报告](protection-charge-report.json)）

原普通arm预留示例有两份，每份590逻辑行、9968640逻辑字节、9个队列槽、624工作单位。该数值来自现有实验profile及forecast，不是生产参数或物理容量保证。收到applied不退款，查原不重复扣，持有量加已消费量始终等于原预留。

## 账本字段与约束

| 对象 | 规则 |
| --- | --- |
| pb_expected_account | 从注册表的五类来源读取完整plan/run/受损generation集合；跨run P1每run一个账户，重新关闭使用原sf受损代次 |
| pb_shape | 从当前同库依赖、受损代次及以下历史执行、准备、全部提交与Controller并集求实际六维规模。planned、未知和旧成功均计入，不接受客户端少报 |
| pb_use | 主键plan_id/run_id/generation，绑定原arm operation、profile全文摘要、预算binding_digest、原sp计划摘要、连续ordinal；保存四维整份包络、实际shape、逻辑行/字节计量、最大行正文、elapsed_wait_ns、计量说明及审计 |
| pb_commit | plan级审计与通知，最后核对受影响账户集合完全相等、sp接收计划已封存、计量时shape仍未变化。注册表及每笔消费均反向引用此记录 |
| pb_balance | 由不可变原预留和不可变消费记录求held/spent及episodes_left，不改写原budget_body。四维单位按原预留总量除以原profile份数，SQL禁止少扣任何一维 |

所有消费原件不可更新/删除；一个计划不能在同账户重复消费，ordinal必须为已存在消费数的精确后继并不超过原份数。run/generation必须精确匹配预留所属arm，不能按当前活动代次猜测账户或跨run代付。内部有界INTEGER沿用原预留最大值；对外计数及等待值仍采用规范十进制字符串，等待用文本长度及字典序比较，不经浮点。

## 原子顺序、计量和故障

1. 运行层先确认受监督关闭和同一单调域的等待证据；参考上下文的volatile_close_verified、clock_wait_verified只是合成前提，未实现真实进程闭锁。
2. `BEGIN IMMEDIATE`内执行原完整保护写集，尚不COMMIT；从本事务新增注册计划推导全部预算账户及当前shape，核对原forecast。
3. 按当前/事务前的全表逻辑行差集计量新增和改写后的行正文。BLOB以十六进制计入序列化上界；每笔消费另加8192字节、每计划seal另加4096字节，并核对预算原件实际序列化不超该上界。该计量是离线writer证据，SQL不能独立证明外部writer没有伪造计量。
4. 每个受影响账户保守承担完整事务的逻辑峰值并消费一整份原包络；尚未实现精细跨run分摊。所有账户均须满足预测规模、最大行、四维包络和`elapsed_wait_ns < max_queue_wait_ns`，等号拒绝。这不表示实际SQL页/WAL/索引、CPU或实时队列成本已经测定。
5. 写入所有pb_use及pb_commit，全部成功才提交。任一预算、目标、正文、最后shape检查或写入失败，原保护事实和消费一起回滚；不得留下半个计划、半个暂停或已扣账无计划。
6. 失败返回未确认，不能因为数据库仍为旧状态便恢复派发。实际进程必须保持受监督volatile_close并按原请求查账；本模型的protection_confirmation仅是事务观察，不是设备关闭证明。

已持久的同一终态或重试请求先查原；即使额度耗尽或新的等待时间越界也不重新消费。等待证据不合格的处理入口与纯读取API最终映射仍待统一。当前未提供任何退款路径；applied、重连、时间流逝和新代次都不减少spent。

## 验收与尚未具备的能力

- 终态保护及扣账每个写项逐条省略和注入异常，比较全部99表；四维少扣、错原件/代次/序号/摘要、非法等待与截止等号、缺运行关闭确认均拒绝。
- 一份、两份和耗尽后的查原；P1、准备失效、失败arm退出、sf和sr共用入口；双run P1分别记账；依赖增长超过forecast与最后封存前新增依赖拒绝。首次计量尚未覆盖所有最大规模、完整观察排列或所有类型组合。
- 旧代次重试在新R2后仍扣原arm一代，不改新run。**恢复R2还没有新代次预留原件**，因此新代次保护明确拒绝generation_budget_missing；不能借旧池补齐，也不能据此宣称完整恢复已满足预算准入。下一步须建立恢复预算及最后准入约束。
- 零受影响run的来源计划没有实例级账户，本候选拒绝其消费seal；实例应急/来源元数据账户仍待建立。旧97表的相关功能仍是最终范围，不能用此拒绝删除需求。
- 完整CostManifest、所有后续观察/审计的精确保留成本、实际工作/排队释放、主体/设备层级、跨run精细分摊、物理预分配与GC、profile更新、通用退出和耗尽处置仍缺。
- Controller输送与最终出口、AUTH/TIME、当前授信、唯一SDK及完整API/IPC归并继续待完成。真实服务、并发、磁盘崩溃、NTP、网络及设备验收均未运行；阶段0不关闭，候选不得部署。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_protection_charge.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_protection_charge.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_protection_charge.py --check-report
```
