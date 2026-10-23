# 动作失败保护的重新关闭候选

状态：`failure-protection-retry/0.1.0-draft.1`，`approved=false`。承接[94表失败保护](FAILURE_PROTECTION.md)，新增[具名Schema](protection-retry.schema.json)、[约束](protection-retry.sql)、[97表组合](seamer-protection-retry.sql)、[生成器](build_protection_retry.py)、[参考写集](protection_retry_model.py)、[检查](check_protection_retry.py)与[报告](protection-retry-report.json)。本轮只交付实施前设计与离线验证，不改变公共draft.4／IPC0.3，不实现业务服务。

## 已知事实及推荐边界

此前sf计划不可变，保护观察失效后能重新进入待查列表，但没有创建新关闭身份的可靠写集。本候选新增独立关闭尝试；原动作终态、sf库存和旧准备/提交全部保留。68项内存SQL与Schema检查通过，覆盖pending/applied拒绝、失效后重试、完整目标重关、幂等、迟到回执、16次上限及旧代次与新恢复隔离。（证据：[检查源码](check_protection_retry.py)、[报告](protection-retry-report.json)）

推荐采用此重试语义：只有最新尝试的最高已观察状态为indeterminate才能新建关闭计划；pending只按原身份查账，applied不重复关闭。超时、连接断开或没有回复不能自行视为indeterminate。本模型接收合格失效观察，不实现时钟/通知流健康判定。

## 输入、输出与存储字段

| 对象 | 必需字段与语义 |
| --- | --- |
| RetryIntent | contract_version、root_plan_id、previous_plan_id、request_epoch、actor.principal_id、idempotency_key、reason=proof_invalidated；禁止额外字段，身份字符串最多128字符。actor和epoch为认证域注入的内部writer身份，不能由客户端自报授信 |
| RetryResult | 原root_plan_id、新plan_id、attempt_index（1至16的有界整数）；actions_replayed、resources_cleared、budget_released固定false。查原返回原尝试结果，不混入当前运行状态 |
| sr_attempt | 上述幂等域、原请求正文/摘要、root及previous关联、连续attempt_index、完整计划正文/摘要、目标数；双向延迟引用sr_commit和sp_plan_commit |
| sr_target | 新目标operation_id、完整Controller scope、原run/受损代次选择器和selector_digest、新target_set_digest、完整binding与派发正文。目标scope集合必须与原sf集合完全相等 |
| sr_commit | 审计及通知；最终复核previous仍为最新失效、库存仍一致、完整目标与sp接收计划/目标相等、局部容量未越界 |
| sr_latest／sf_pending_dispatch | 原sf计划为attempt_index=0；只从已封存尝试选最大序号。待查只投影最新计划，旧计划及观察仍可按原身份检索 |

Schema根禁止直接实例化，必须选择`$defs/RetryIntent`或`$defs/RetryResult`。它们是本候选的内部接口，不是最终公共HTTP操作或SDK冻结声明。摘要采用既有JCS/SHA-256参考函数；SQL不验证密码学来源真实性。

## 原子时序与故障处理

1. 当前可信上下文核对系统关闭授权，或当前人类操作授权；失效的人类授权不妨碍独立授信系统关闭。进入事务后先按epoch/actor/key查原，同内容返回原结果，异内容冲突。
2. 新请求必须绑定同一root的最新previous且序号精确后继。原库存重新对比全部受损代次及以下准备、执行、提交，完整原始正文保持；不能根据当前“只剩一个目标失败”缩减集合。
3. 同事务保存sr_attempt、全部新目标、sp计划/目标/接收seal、sr_commit及通知；最后seal前重新验证。任一漏写或异常整笔回滚。提交确认之后未来消费者才可发送。
4. 只有一个Controller失效也重新生成完整目标的关闭身份；其它Controller的旧applied不计入新计划。旧ACK因operation/binding不同不能移植，旧成功迟到不消除新计划的pending。
5. 新计划pending只查原，新的indeterminate才能再建下一次。较旧幂等请求仍返回原结果，不回退sr_latest、不产生重复动作；已提交的缓存写集不能复用。
6. 重试只保存关闭记录，不更新run、业务状态、执行/动作终态、锁存、槽或预算。新代次已进入R2时，旧关闭仍限定旧generation；本轮实际验证不改变新run并允许其按原R4启动，恢复资源核对仍是独立合成前提。

原sf计划已经设置旧代次DENY，重试不扩大下界。全部新观察applied不自动恢复、不释放资源、不退款；失败后的自动化恢复必须继续走独立预览、新代次、全部锁存、当前资源核对和既定授权协议。

## 容量、验收与剩余事项

- 每个原失败计划最多16次新关闭尝试，初始sf计划另算序号0；第17次拒绝但历史查询保持可用。目标上限256并受p1_limit更小值约束；正文容量在最后seal检查。这是实验存储上限，**不是取得16份保护预算或物理磁盘预留的证明**，也不是允许无限故障后继续直播的保证。
- 检查逐条省略/异常回滚、Schema缺字段/多字段/非法身份、错root/previous/序号/scope/目标数、相同请求冲突、旧ACK移植、单目标失效后的全集重关、耗尽与查原、新代次隔离及最终外键。原94表83项检查因夹具新增可选完整布局参数而实际回归；默认路径和全部守卫保持。
- 本轮未新增网络消费者、发送尝试和COMMIT未知后的实际查账器。数据库不可写或提交不确定时须由受监督运行域立即volatile_close；不能把事务回滚误报成设备已经关闭。
- 独立关闭成本消费、层级/跨run预算、恢复新预算与GC、耗尽后的通用退役/现场核对、真实Controller关闭和资源核销、AUTH/TIME、完整准入、唯一SDK及API/IPC归并仍待完成。
- 当前观察和外部授信/释放证据为合成。真实服务、IPC、网络、并发、磁盘崩溃、NTP及设备验证均未运行，阶段0不关闭，候选不能部署。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_protection_retry.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_protection_retry.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_protection_retry.py --check-report
```
