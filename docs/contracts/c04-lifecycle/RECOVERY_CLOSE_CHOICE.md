# 恢复关闭依据二选一

状态：内部设计候选，approved=false。接续[完整退役关闭集合](RETIRED_CLOSE_SET.md)，不更改已确认公共基线。

已知事实：既有恢复目标强制引用go_close_ack，go_ready候选也直接读取该目标表。独立退役完成必须同时进入恢复seal和后继资格判断，否则只新增一张证明表无法用于恢复。（来源：[开放存储](../c08-controller/open-storage.sql)、[关闭ACK扩展](authorization-close-ack.sql)。）

本轮方案保留旧ACK表，增加显式gr_retired_target，并通过gr_all_target和gr_valid_target统一两种依据。每个最新close必须恰好选择worker_ack或supervisor_retired之一。worker_ack仍要求完整准备核销、未撤回ACK及适用时的认证日志；时间只与相同运行域的新快照比较。退役分支绑定整个RetiredCloseSet的id、摘要、出口及close，不填入旧ACK表，不制造完成时间。

RecoveryCloseChoice保存新出口binding、完整快照与hold集合的摘要Ref、提供者Ref、选择时刻及完整目标原件Ref。BEGIN IMMEDIATE写入恢复、快照、holds、快照seal、分支目标与恢复seal；重复恢复ID仅查原，不刷新时间或替换来源。go_valid_recovery要求精确覆盖设备全部最新close和当前依据，后继ready候选改用同一验证入口。

快照仍须指向未退役的新worker。当前参考场景为同一运行域中新controller boot及worker替换，监督观察域可不同；原controller故障域禁止登记新出口的守卫保持，夹具不能复用已关闭的controller身份。它不证明整个运行域切换后的快照排序，因为旧go_current_snapshot按tick排序，跨域重建和控制状态换域仍需另行归并。新worker启动认证、握手及快照授权/资源/时钟提供者和物理效果为合成输入，不宣称已经验收。

69项离线检查通过，涵盖混合依据完整提交、六步逐写回滚及缺写、提交观察丢失查原、漏项/重复/过期/旧出口拒绝、二选一Schema反例。另一设备的兄弟出口退役证明撤回时，即使本设备没有新增hazard，整个RetiredCloseSet仍失效并使本设备go_valid_recovery不可用；原件仍可查询，新的恢复ID不能绕过失效。恢复seal不会改变持有人或protected状态，不会签发最终许可。

本轮消除恢复目标仅能引用ACK的关系缺口。仍需验收恢复seal之后的新出口fence、开放、ready、最终授权与实际发送完整链，并补proof失效后的主动保护与通知。go_ready候选及提交守卫已通过统一go_valid_recovery检查当前性，但没有完整重新开放正例，不能据此关闭T5。整个运行域重建、快照同域排序规则及真实提供者继续作为后续设计事项；旧最终发送阻断保留。

交付：[Schema](recovery-close-choice.schema.json)、[附属SQL](recovery-close-choice.sql)、[组合布局](recovery-close-choice-layout.sql)、[参考模型](recovery_close_choice_model.py)、[验收](check_recovery_close_choice.py)、[报告](recovery-close-choice-report.json)。未执行真实设备操作，业务实现仍未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_recovery_close_choice.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_recovery_close_choice.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_recovery_close_choice.py --check-report
```
