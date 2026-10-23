# 普通布防与保护预算的联接候选

状态：`arm-protection-budget/0.1.0-draft.1`，`approved=false`。本页延续[生命周期设计](README.md)与[准备资格保护](../c05-protection/QUALIFICATION.md)，不修改draft.4／IPC0.3，不实现业务服务。交付[具名Schema](arm-budget.schema.json)、[生成器](build_arm_budget.py)、[有限原子步模型](arm_budget_model.py)、[检查](check_arm_budget.py)及[报告](arm-budget-report.json)。本页明确普通arm与P0预算如何配合，不把恢复R2路径当成普通arm已落库。

## 已知事实与冲突

现有生命周期规定：arm可靠受理占用定义槽、消费preflight、增加run/slot修订和generation，但保持disarmed；全部准备当前合格后才armed。现有72表中，p1_preparation的arm分支却要求run已经armed，run.active_operation_id也只外键引用recovery_operation。[检查](check_arm_budget.py)实际建立72表内存库，证明可直接插入没有准备与预算的armed行，且活动操作外键只有recovery类型；源码检查定位了普通登记的armed前置。这是物理布局缺口，不能借先armed再补登记解决。

已执行108项检查：复用原生命周期reserve/prepare有限模型，覆盖四维预算各自不足与恰好足够、回滚、幂等查原、库存/权限/Controller容量失效、有限保护消耗、正文/集合增长、profile调低、共享池两run、旧代次迟到、截止等号、退款和大整数边界。另在现有72表中实际执行P1及准备资格撤回写集，检查含触发器的写入行数落在实验包络内及外键完整。两次实际SQL检查只证明这两个具体输入，不证明任意最大规模或所有保护类型。

## 推荐的正常布防事务

| 边界 | 必须固定的字段与条件 | 提交结果 |
| --- | --- | --- |
| 预检 | run/slot修订、artifact、完整授权/控制/来源基线、预检时钟和半开期限、目标全集、可信库存摘要及容量预测 | 只产生preflight，不占执行或保护额度 |
| arm受理 | 查原请求后再查新额度；human权限、run disarmed、无旧未决/锁存、CAS及全部当前提供者合格；P0预留、完整准备登记、operation/preflight消耗、审计与outbox同事务 | run仍disarmed、dispatch=false、execution为空；active_operation指向arm操作，槽归本run |
| 准备 | 精确Controller scope和新generation，prepare身份先持久后发送；Controller分别预留自身保护/结果额度；响应未知不得重新分配身份 | 操作preparing，不允许设备写；部分准备不等于armed |
| arm完成 | 全部当前准备观察合格；库存/产物/控制/授权/源基线未发生非预期变化；预算原件绑定同operation/generation，未提前消耗，profile仍相同 | 同事务operation ready、run armed、清active_operation、run修订增加；预算继续持有 |
| 失效 | 保留旧回执、原请求和已准备目标，关闭当前派发；按完整旧库存产生保护 | paused或未确认；禁止迟到成功自动完成原arm |

后续物理布局应引入共享`lifecycle_operation_identity(operation_id,run_id,kind)`，将run活动操作外键指向此身份；arm/recovery专用记录各自反向引用同kind，严禁用arm伪造recovery。arm的准备登记在disarmed且活动操作preparing时进行，并与arm seal双向延迟引用。armed状态的每次新进入必须来自明确arm完成或既有执行成功返回路径，不能统一禁掉后者。直接建armed、先占槽后补预算、先提交arm再补目标均须有拒绝用例。现有SQL在本轮保持原证据范围，这些DDL尚未联接。

## 可校验的预算对象

Schema只通过具名`$defs`使用，根对象不可直接实例化；所有计数均为规范U20十进制字符串，计算和加总不得经过浮点，超出20位拒绝而非截断。

| 对象 | 关键字段与语义 |
| --- | --- |
| Profile | profile_id/revision、purpose、capacity四维、max_shape、max_row_bytes、episodes、max_queue_wait_ns、validation_ref。发布候选必须有验证Ref，实际有效性由平台提供者核验；存在Ref不等于通过验收 |
| Shape | dependencies、runs、executions、preparations、submissions、controller_targets；来自完整可信库存及允许增长的上界，包含未知、失败、旧代次和未尝试目标，不能由用户少报 |
| Binding | 完整Seamer scope、run、generation、operation、artifact_digest、inventory_digest、profile身份及全文摘要、forecast；保护预算绑定对象，不是可移用的授权token |
| Reservation | reservation_id、binding及摘要、per_episode、held、spent、episodes_left、state。状态held/exhausted/released；完整binding摘要参与ID，多个run的相同operation别名不碰撞 |
| ProtectionUse | 原reservation及binding_digest、event_id/digest、source/preparation/control/authorization/time/storage原因、实际shape与最大行正文。事件身份完整相同才查原，异内容不覆盖 |
| ReleaseProof | 原预算与binding_digest、完整proof_ref；要求generation_closed、all_targets_accounted、no_unresolved_references、archive_durable全成立，且提供者独立授信。布尔值是证明的投影，不能由请求自证 |

四维分别为逻辑持久行数、逻辑持久字节、保护处理槽和有界处理工作量。实例账本要求各维`held + spent + new_reservation <= capacity`。准备ready、收到applied、时间流逝、连接重建均不自动减账；同请求查原先于新额度检查。多主体/设备级约束仍须同时满足，不能拿实例还有额度绕过其他层级。

## 实验包络及冻结边界

设完整预测规模为D/R/E/P/S/T，依次对应Shape六维。当前候选采用以下保守实验包络：

```text
rows = 32 + 3D + 6R + 3E + 132P + 3S + 68T
logical_bytes = rows * (max_row_bytes + 512)
queue_slots = 2T + P + 1
work_units = rows + D + R + E + P + S + T
reservation = per_episode * episodes
```

系数包含固定封存/账本开销、成员与副本、每准备最多128行及每Controller最多64行的状态/审计/通知保留余量；这些是实验上限预算，不是从生产实现测得的峰值。当前P1与准备失效初写有额外余量，但全部最大规模、JSON行正文、观察全排列、Controller共享消息及跨run来源故障仍需生成精确CostManifest逐项核对。任何实际对象超过forecast、行界或协议上限时关闭新准入，不能截断尾部、漏旧unknown或继续以较小成本记账。

实验profile为`sim-arm-budget-1`：100000逻辑行、4GiB逻辑字节、1000保护槽、200000工作单位，每行16KiB、每代次2份保护包络、排队预算500ms。用于快速制造边界反例，不是默认部署建议或直播SLA。实际受理前还须满足HTTP/IPC各自大小限制，预算并不允许把数MiB计划塞进单帧。

逻辑字节不等于SQLite文件/WAL/索引实际增量；512字节余量不是物理页证明。正式profile要绑定版本化SQL、序列化器、页/WAL/索引界、checkpoint保留、磁盘预分配与故障证据。磁盘不可写、设备故障和进程停顿仍可能发生，预算不提供必然成功承诺。工作单位是有界调度成本，不是CPU毫秒。

## 故障时序、额度与恢复

1. 首保护先关闭当前代次的内存发送资格，再尝试持久预算消费与完整保护事务。持久成功才把一份held转spent并保存事件原件；行数、目标与正文必须在预留包络内。内存关闭不产生可靠已暂停回执。
2. 存储失败或提交未知：持久账本保持原值，内存关闭保持；重启默认未布防并查原事件、预算与全库存。不能因数据库没有新fault记录就继续直播派发。参考模型只返回volatile_closed投影，没有真实受监督进程。
3. 不同保护事件分别消费额度，不按“同一run”静默合并身份或原因。精确重复查原零扣；份数耗尽仍保持关闭，返回未获持久保护确认，不能无限写新fault或伪造receipt。已持久操作按原身份查询/推进，不能把普通设备重试带入此例外。
4. 排队等待由同一受监督单调域测量，`elapsed < max_queue_wait_ns`才能开始该持久处理；等号拒绝并保持关闭。跨域/重启/休眠无法证明等待界时不得重置起点。模型输入elapsed为合成可信证据，仅验算边界，没有实现真实时钟采集。
5. 调低profile不删除已持有/已消耗额度。旧保护使用原profile正文和预算，准备中的新ready因profile变化关闭；新受理使用新上限。相同profile身份换正文拒绝，改变必须用新修订。现有持有大于新上限可以阻止新工作，但不能抢占旧保护额度。
6. 旧代次保护只消费其原预算，不更改更高代次run状态或关闭其门。新的显式恢复另取新预算，旧未知和未释放引用继续占用；恢复不以“新代次”清空旧成本。
7. 退未使用额度必须有独立可信的关闭/核对/归档证明，不能凭单一保护applied或GUI按钮。模型只退held，spent及历史事件、墓碑保留；消费后的队列/工作槽复用与持久数据GC需不同释放证明，不能一起按字节退款。正式存储还须接已有完整引用图及有限保留流程，不能把永久累积当可持续运行方案。

## 待完成的同版归并与运行验收

- 普通arm的共享operation身份、preflight/slot/预算/完整准备双向seal及armed最后守卫，联接现有恢复与触发布局；本轮没有生成新的完整SQL。
- P0的实例与主体/设备层级账本、全部保护写集CostManifest、跨run来源保护分摊、保护结果保留及归档/GC；任何消费者缺清单时不允许发布profile。
- 实际库存、权限、Controller容量、时钟、受监督闭锁及归档证明提供者；本轮有限模型中的可信上下文为合成，完整Controller准入和唯一SDK仍待归并。
- 两平台验证：保护和普通负载交错、磁盘FULL/IOERR、WAL/checkpoint压力、进程在COMMIT各阶段崩溃、监督关闭、长时间运行与额度回收、跨服务响应丢失及旧代次迟到。当前真实运行/并发/磁盘/网络/设备检查均为0，阶段0未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_arm_budget.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_arm_budget.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_arm_budget.py --check-report
```
