# 普通布防的同库登记与完成候选

状态：`arm-storage/0.1.0-draft.1`，`approved=false`。本页延续[布防预算](ARM_BUDGET.md)及[准备资格](../c05-protection/QUALIFICATION.md)，交付[增量DDL](arm-storage.sql)、[组合生成器](build_arm_storage.py)、[83表完整候选](seamer-arm.sql)、[参考写集](arm_storage_model.py)、[验收](check_arm_storage.py)与[报告](arm-storage-report.json)。只处理设计与离线验证，不修改业务服务、draft.4／IPC0.3或生产数据库。

## 已知事实与本轮修正

上一轮在72表中复现了无准备即可直接创建armed、活动operation只允许recovery、普通准备反而要求armed三个缺口。本轮在同一组合库加入11表，普通arm从disarmed受理、持有预算并登记全部准备；全部当前资格合格后才完成armed。恢复仍使用原R2/R4/R5，不把arm伪装成恢复执行。

实际内存SQLite检查通过109项。所有fixture从建库起启用外键及全部守卫，不删除触发器、不降低既有修订、不先造armed。正例包含两目标普通布防、零设备布防、准备观察查原，以及正常arm后显式暂停、零设备reconcile_commit经R2/R4/R5回到armed。后者证明新守卫保留成功返回路径；核对及释放正文仍是合成提供者，不能解释为设备完成证据。

新守卫初版误挡reconcile期间dispatch=0到R5后dispatch=1，现已修正；仅允许同一活动execution、同run/gen、执行succeeded、精确transition及run修订+1的成功返回。暂停后借旧transition重新开放被拒绝。完成arm的最终seal还复核定义槽绑定与修订，不能只验证写入arm_complete时的前态。

## 表与事务边界

| 对象 | 固定字段与提交条件 |
| --- | --- |
| lifecycle_operation_identity | operation_id/run_id/kind；arm_id和recovery_id严格二选一。专用操作插入时自动登记，共享run外键引用；跨类型重名拒绝 |
| arm_capacity | 单例profile摘要/全文、max_operations、logical_rows/logical_bytes/queue_slots/work_units；本候选固定不可变，初始化须由可信提供者验证正文与投影 |
| arm_preflight | run/slot修订、generation、artifact、dependency_head、完整来源及目标正文、clock、issued/expires、digest；仅允许一次consumed_operation_id更新，与操作反向延迟外键配对 |
| arm_operation | request_epoch/actor/idempotency_key、原请求及摘要、三组before/after、clock/now_tick、target_count；run/slot/generation精确+1，前态disarmed且没有活动操作/执行，时间区间左闭右开 |
| arm_budget_reservation | operation/profile、四维整数预留、原Reservation正文与audit；与操作反向延迟引用。独立重算上一轮实验公式并校验实例累计容量，不能只修改列与正文同步少记 |
| arm_target / arm_register_commit | 每目标Controller别名、登记ID、完整scope/请求；与p1_preparation双向配对。最后封存目标全集、来源基线、当前槽/run和预算预测下界；漏目标、错scope或漏seal整笔回滚 |
| arm_attempt / arm_receipt | 登记ID、唯一尝试、原binding/runtime/audit；原external_evidence与当前observed_applied精确配对。登记后才可首次尝试，重复响应查原；失效后不能开始新尝试 |
| arm_complete / arm_ready_commit | operation/run/generation、run before/after、slot修订及完成正文；全部准备合格且有原回执，再更新run并封存审计与通知。双向延迟引用禁止完成半提交 |

预检读完整来源快照。受理使用BEGIN IMMEDIATE，在同一事务内查幂等身份，再验证新请求的当前提供者并构造写集。原请求查账不再次占额度；异内容不能覆盖。完成也在同一写事务重新读取库存、run、槽及准备资格。不跨网络等待持有写事务，arm不创建execution，不执行设备动作。

预算沿用[上一轮六维预测和实验公式](ARM_BUDGET.md#实验包络及冻结边界)。SQL将预测各维限定0..65536、份数1..1024、单行界不超过1MiB，四维累计各不超过10^12；这些局部有限整数运算不经浮点。API计数仍是规范U20文本，不代表可将任意20位值放进SQLite INTEGER。run/slot/gen仍使用严格十进制文本后继，不能以整数CAST实现修订。数据对象的JCS、完整摘要、可信库存和提供者资格由writer验证，SQL正文关系检查不替代它们。

## 故障顺序与验收证据

1. arm登记任一写缺失或写后异常：操作、预算、preflight消费、槽/run变化及准备全集全部回滚，不留下半次布防。
2. 准备尚未全部applied：保持disarmed且派发关闭；即使强行UPDATE armed/running也不能绕过提交。原准备观察、领域采用、external_evidence的中途异常全部回滚。
3. 准备期间或armed后来源P1：保护全集覆盖两目标；独立准备撤回同样覆盖两目标并阻止完成。旧成功回执与原预算保留，不因保护applied或收到迟到观察恢复资格。
4. 全部准备完成后，权限、人类操作资格、库存或Controller容量投影失效，或来源修订变化：拒绝完成。arm_complete与最后seal之间改变槽修订亦拒绝并回滚；槽释放另由已有slot_owned守卫拒绝。
5. reconcile恢复启动仍关闭普通派发，全部必需核对步骤完成后才R5提交。R5各写后异常均全库回滚，成功保留原arm预算和两类operation身份，外键检查为空；旧transition不能从paused重开。
6. 新增11表均拒删除，准备ready不退额度；零设备arm也必须持有预算。immutable限制只说明本候选未提供退役协议，不是永久累积的产品方案。

报告绑定生成器、源SQL、模型、Schema及检查输入字节；`--check-report --staged`核对暂存版本。109项不是并发次数，也没有真实进程崩溃、磁盘FULL/IOERR、WAL或设备检查。

## 仍须收敛的实施前事项

- **失败arm的退出**：当前P1/资格失效可以可靠关闭，却仍保留active arm；需完整准备关闭、旧引用核对和明确退出seal，之后才可显式恢复。不得直接清active_operation或把失败重新标为ready。
- **预算消费与可持续运行**：此DDL只落普通arm预留。P1/PQ实际消费、跨run分摊、主体/设备层级、profile换代、恢复新预算、结果保留、归档/GC及退款尚未同库联接。现有恢复正例只证明原路径可行，不能声称它已取得新的保护预算。
- **普通触发完整组合**：原摄取/执行DDL保留；本轮83表未运行“新arm→正常事件触发→动作→完成”的端到端正例。后续需用当前run修订接入真实写集，不能沿用旧fixture硬编码修订或绕过守卫。
- **最终可信边界**：预检和完成中的权限、库存、Controller容量、时钟及运行域为合成上下文；prepare请求是内部测试正文。实际AUTH/TIME、Controller最终准入、完整SDK单一源与公开API同版归并继续待完成。
- **运行验收**：内存库没有证明并发、提交未知恢复、持久磁盘崩溃、长期回收、服务网络或设备安全；需在Windows/Linux和OBS首闭环逐项验收。本轮不关闭阶段0，不批准发布或部署。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_arm_storage.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_arm_storage.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_arm_storage.py --check-report
```
