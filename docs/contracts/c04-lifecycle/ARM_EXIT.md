# 失败布防退出与屏障重试候选

状态：`arm-exit/0.1.0-draft.1`，`approved=false`。承接[普通布防同库候选](ARM_STORAGE.md)，交付[Schema](arm-exit.schema.json)、[七表增量](arm-exit.sql)、[90表组合](seamer-arm-exit.sql)、[唯一生成器](build_arm_exit.py)、[参考写集](arm_exit_model.py)、[验收](check_arm_exit.py)与[报告](arm-exit-report.json)。这是实施前离线候选，不改变公共draft.4／IPC0.3，不实现HTTP服务或操作设备。

## 已知事实与范围

此前83表可以关闭失败布防的派发资格，却没有解除其active_operation的可靠写集。直接清字段会绕过全部已登记准备的关闭核对；把旧回执applied当作资源释放也不成立。本轮实际在完整90表中执行停止、保护观察、退出及新代次恢复，125项检查通过，全程保留原守卫。

本轮退出只结束未完成arm的准备过程，结果仍为paused。旧锁存、槽、准备、未知引用、预算和历史全部保留；不把操作退出解释为设备资源clear、disarm、retire或允许自动恢复。已完成armed的操作不能使用此入口，必须走既定显式disarm/retire流程。

## 推荐的状态与身份边界

以下是内部账本投影，不增加公共Operation状态枚举；公共Operation投影和SDK统一仍须最终归并。

| 边界 | 原子结果 | 后续行为 |
| --- | --- | --- |
| 停止受理 | aa_stop、run修订+1且paused、独立arm_exit锁存、第一保护尝试、完整Controller集合及审计通知同事务 | 原active arm继续占用；该代次进入共享DENY，原准备不得新尝试或完成 |
| 等待证明 | 同一plan/target的sp观察与接收提交持久保存 | pending只查询原请求；不因超时制造第二逻辑请求，不猜测目标已关闭 |
| 证明失效 | sp当前状态indeterminate，旧applied原件不覆盖 | 允许明确的新关闭尝试；新plan/target身份、previous_plan和ordinal绑定最新尝试，旧成功不能代替新尝试 |
| 退出封存 | 最新尝试所有目标当前applied、原库存和槽仍一致；固定观察原件、run修订+1、清active arm及audit/notification同事务 | 保持paused与dispatch=false；不退预算、不清锁存、不产生execution |
| 显式恢复 | 原R2/R3/R4/R5，新预览、新generation、全部当前锁存与独立资源核对 | 旧unknown、旧DENY及关闭历史继续保留；新恢复准备不复用旧arm成功回执 |

停止请求可靠受理后预览消费和原arm受理都不回滚。请求幂等身份使用当前认证域提供的request_epoch、actor和key；同键异内容冲突，同内容查原先于再次执行。Schema里的身份字段是内部可信writer输入，客户端不能自报principal或trusted_system_closer。

人工取消要求当前人类操作权限；来源、授权、时间或存储恢复触发的系统关闭可由独立授信的关闭提供者推进，不依赖已失效的人类授权。模型中的布尔上下文仅表示这条边界，真实鉴权与授信尚未实现。

## 字段与物理约束

| 对象 | 关键字段及约束 |
| --- | --- |
| StopIntent / aa_stop | arm_operation_id、expected_run_revision、reason、幂等身份；存run/generation、run before/after、slot_revision、inventory_body、latch_id和first_plan_id。first_plan与operation复合反向延迟外键配对，不能借其它操作的已封存计划完成受理 |
| aa_attempt | plan_id、operation_id、ordinal、previous_plan_id、原请求/摘要、完整计划/摘要及target_count。首次绑定StopIntent；后续必须基于最新已封存且indeterminate的尝试。每次反向绑定attempt_commit及sp_plan |
| aa_target / aa_attempt_commit | 每个完整Controller scope、独立目标operation_id、原保护binding及内部dispatch正文；集合与sp_target双向相等，最后封存重新验证库存、run、槽、锁存及容量 |
| aa_exit / aa_exit_pin | 原arm、最新plan、run/gen及修订、槽；每目标固定当前revision=1和observation_digest，并引用原sp_observation，不只存一个成功布尔值 |
| aa_exit_commit / ExitResult | 最后再次验证最新plan和全部观察仍applied、全部pin齐备、库存/槽/run一致。返回paused、resources_cleared=false、budget_released=false，且绑定原退出修订 |

成员清单包含截至原generation的全部准备binding、execution绑定摘要和提交原请求；Controller集合取准备与提交目标scope并集。完整计划按此库存生成，不按“本次已发过的目标”缩减。关闭不需要事件来源已经恢复同步，恢复R2仍必须通过来源核验。当前检查实际覆盖两准备目标、零目标、来源故障与资格失效；混合历史执行和提交并集的完整运行前态仍需在disarm/retire及正常触发全链完成后验证，不能用125项总数代替该证据。

所有新表原件不可更新/删除；成员、目标和pin各自在seal后禁止追加。run的活动arm只能由原arm完成或本退出双向seal清除。旧83表产物仍独立保留；生成器精确扩展共享保护注册表和DENY来源，不把主动停止伪装成事件来源故障。

## 故障与重试验证

1. 停止受理、每次屏障重试和最终退出均逐条删除写项及注入写后异常：全部90表回到原快照，无半消费、半目标或提前清active。
2. 原准备已经尝试后迟到applied：接收器只保存观察历史，不补arm_receipt；绕过该接收器直接采用被SQL拒绝。即使历史观察显示applied，共享DENY仍阻止原arm完成。
3. 错代次、跳修订、非规范U20、同数替换目标、错scope、少库存、缺pin、错摘要、旧plan及最终槽漂移均拒绝。最终seal前写入真实sp失效观察也整笔回滚，不能依赖事务早期采样。
4. pending不能创建新屏障身份；indeterminate后可显式新尝试。同一重试请求查原零写，旧previous_plan冲突。新尝试必须重新收齐所有目标；旧plan原件和失效事实保留。
5. 本候选暂设每arm最多16次关闭尝试、每次最多256个目标，并服从p1_limit更小的目标和正文上限。第17次拒绝后仍暂停且保留最新计划，查询原件不受此新尝试限额影响。这是实验存储上限，**不是已经取得16份保护预算的证明**；正式profile须经成本清单及预算消费联接后冻结，耗尽后的现场核对/退役路径仍待实现。
6. 退出查原返回原退出结果，不把当前run状态混入历史结果。保护观察后续失效保留新的证据，但不回写已提交退出，也不自动关闭另一个新generation。新恢复需要独立当前资源与控制证明，不能把退出时的旧pin当作持续授权。
7. 正例使用原恢复事务，验证停止退出后和资格失败退出后都能以新预览、新代次和全部当前锁存恢复到armed；旧预算、DENY和首失效未被删除。来源desynchronized时，R2自身整笔拒绝；此前单独提交的暂停/预览不应被误报成R2回滚的一部分。

## 实施前仍未完成

- 新关闭尝试与P1/PQ的实际保护消费、恢复新预算、所有成本清单、层级额度、跨run分摊和GC仍未接入。不可将固定16次上限或SQL逻辑字节约束解释为磁盘预留/直播保障。
- 此退出不是完整通用pause/disarm/retire协议；保留paused和槽是明确语义。后续须完成通用资源核对、全部历史引用、槽释放，以及正常arm→事件触发→动作→R5的同库正例。
- 真实鉴权、可信库存、监督域、当前参考时钟、Controller最终准入和公开SDK归并仍缺。保护观察为已解码合成对象，使用共享接收器验证结构、scope、精确绑定和失效顺序，不是实网或硬件证据。
- 进程崩溃、SQLite FULL/IOERR及WAL、真实并发、两平台网络/IPC/设备、长时间容量与耗尽后的恢复均未运行。阶段0仍未关闭，候选不得部署。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_arm_exit.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_arm_exit.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_arm_exit.py --check-report
```
