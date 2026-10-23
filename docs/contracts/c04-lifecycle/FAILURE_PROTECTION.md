# 动作失败到独立保护计划候选

状态：`approved=false`，承接[普通触发91表候选](TRIGGER_FLOW.md)。交付[增量约束](failure-protection.sql)、[94表组合](seamer-failure-protection.sql)、[生成器](build_failure_protection.py)、[参考写集](failure_protection_model.py)、[检查](check_failure_protection.py)及[输入绑定报告](failure-protection-report.json)。这是实施前存储契约，不改变公共draft.4／IPC0.3，不实现业务服务。

## 已知事实

此前普通触发能够在必需动作失败或结果未知时暂停本地run，但未强制保存Controller保护计划。本轮将需要保护的step_terminal反向引用sf_plan，终态、run/执行投影、锁存、完整保护库存、共享sp计划及通知必须同事务成功。旧的“只记终态与本地暂停”写集在新布局被拒绝。

83项内存SQLite检查已实际执行。混合历史检查发现并修复了按当前execution关联库存导致漏掉历史提交的问题：当前库存实际包含两个执行及七个历史/当前提交，而非重复当前提交。相邻动作失败分别保留终态和计划，后到unknown不覆盖execution已形成的failed；两个step的原始事实继续独立存在。（证据：[检查源码](check_failure_protection.py)、[报告](failure-protection-report.json)）

## 内部契约与原子写集

| 对象 | 字段及约束 |
| --- | --- |
| step_terminal.protection_plan_id | 必需failed或任意unknown/blocked/expired/cancelled必须非空，指向与terminal、execution、step、run和outcome精确相符的sf_plan；成功或可选确定failed不得附带此计划 |
| sf_plan | plan_id、terminal_id、execution_id、execution_state_before、step_id、run_id、generation/current_generation；固定run修订与活动引用、生命周期/dispatch、槽修订/归属/版本、affects_current、latch、准备水位、完整inventory、目标数及计划正文/摘要 |
| sf_target | 完整Controller scope、目标operation_id、原保护binding和内部protect_registered_run派发正文；origin来自存储scope，拒绝下界使用受损代次，target_set_digest绑定整份计划。派发正文必须包含同一binding |
| sf_commit | 非空审计和通知；最后核对终态、step_state、run/槽投影、锁存、完整库存与目标集合、sp计划及两端目标、终态transaction_record与event_outbox |
| protection_plan_registry／p1_deny | 新增互斥failure_plan来源；不能冒充来源故障、准备资格失效或失败arm退出。封存后加入共享旧代次拒绝下界 |
| sf_pending_dispatch | 尚未观察到applied或已观察失效的目标集合；供未来消费者查原。不是可靠输送实现，也不是持续健康证明 |

写集先固定sf_plan前态，再执行原终态审计/通知及step/run/执行/锁存投影，随后保存完整目标、sp计划与目标及接收seal，最后sf_commit封存。全部放在一个`BEGIN IMMEDIATE`事务，提交确认前禁止发送。seal必须位于可信writer写集最后，不能解释为允许seal后任意修改业务状态。

inventory包含同run受损代次及以下的全部准备binding原字节、execution binding摘要、submission请求原字节；planned、响应未知、已受理、历史成功均保留。Controller集合取准备与提交scope并集，不只选失败动作所在设备。SQL同时校验数量、集合差集和固定正文，不能用同数替换绕过。scope始终区分authority与database。

## 失败与恢复语义

1. 受损execution仍是当前活动执行且代次相同：run修订精确加一，paused、dispatch=false，保留活动引用；每个终态追加独立step_terminal_failure锁存。execution处于prepared/running/paused时按该结果投影，已有failed/unknown等终态保留，原step事实不互相覆盖。
2. 旧代次迟到：保存旧终态和旧代次完整保护计划，当前run、活动操作/执行、槽及锁存保持不变；不得把新恢复执行纳入旧库存。已验证实际R2之后旧失败迟到不影响新代次，再经原R4可启动；旧unknown和DENY仍保留。
3. 可选确定failed不产生保护计划且继续running；可选unknown等仍保护。此处只验证独立动作及相邻终态，完整并行组依赖、取消执行和补偿策略仍按既定设计另行联接。
4. 系统关闭独立于已失效的人类操作权限：参考输入要求terminal_evidence_verified和trusted_system_closer。它们是外部授信结果，不能由HTTP客户端自报；未实现真实身份、授权撤销或证据签发者核验。
5. 全部保护观察applied只减少待查集合，绝不自动恢复、清资源、退预算或删除锁存。高修订indeterminate重新列入待查；迟到旧applied不能覆盖。applied不替代恢复的独立old_resources_clear证明，本轮明确验证该资格为假时R2拒绝。
6. 同终态同证据查原零写，异outcome或原证据冲突拒绝；新失败不修改既有计划。planned提交在失败后禁止attempt，已经attempt的命令只允许原身份查账；迟到受理补历史而不恢复run。

## 验收与运行边界

- 从完整94表新库实际完成arm及事件/动作路径；终态保护每个写项分别省略和注入写后异常，比较全部表快照，确认无半终态、半锁存或孤立保护计划。
- 错代次/修订/槽/动作、同数替换库存、错误派发正文、最后槽漂移、旧本地终态写集均拒绝。正常成功动作及R5仍可完成。
- profile自建库起固定，未移除不可变守卫。正文与计划数量耗尽整笔拒绝，不截断库存；计数上限沿用p1_limit，目标另有256及库存65536实验上限。这不是完整P0成本或实际磁盘预留。
- 两个失败分别封存，首锁存与首执行终态保留；共享sp接收器验证applied/失效/乱序。观察是合成原件，不是本轮实际Controller输送、最终出口关闭或资源释放证据。

事务失败、容量不足、存储不可写或COMMIT结果未知，旧数据库状态可能仍显示可派发。实际运行层必须立即触发受监督volatile_close并按原身份核对；该运行联接仍未实现，不能仅凭SQL回滚宣称设备已停止。

剩余事项：将独立关闭计划消费到真实Controller，接入唯一发送出口及完整未知在途关闭证据；保护预算消费和恢复新预算/GC；失效保护的新尝试协议；通用disarm/retire；AUTH/TIME和当前授信；完整API/IPC及唯一SDK映射。当前内部BODY、摘要和scope自洽不证明外部提供者可信。真实服务、网络、并发、磁盘崩溃、NTP及设备验证均未运行，阶段0保持开放。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_failure_protection.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_failure_protection.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_failure_protection.py --check-report
```
