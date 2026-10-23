# 取消独立占用与共享资源权威候选

状态：待审阅。`build_protected_hold.py`从[动作图129表](CANCEL_PLAN.md)生成另一份129表组合，不增加第二套资源表、不改变旧生成物，不是生产迁移。业务服务、真实设备及运行验收仍未开始。

已知事实：旧`cr_hold`强制普通attempt和普通发送提交，普通命令修订及取消deny也对全部hold生效；因此不能直接保存取消计划的独立保护占用。现有`cr_risk_hold`、`cr_release_validation`、`cr_release_invalidation`和`cr_recovery`已提供跨来源风险与撤回恢复机制。（来源：[resource.sql](resource.sql)、[command.sql](command.sql)、[公开存储](../c02-command-view/storage.sql)、[取消资源](cancel-resource.sql)。）

基于这些事实，本轮推荐将同一个`cr_hold`扩展成互斥的普通/取消两种归属，沿用既有整设备仲裁、完整释放集合和恢复，不伪造父命令的普通attempt。授权仍来自各自当前完整guard；持有资源不会替代身份、接管、时间、预算或独立取消Requester。

## 1. 字段与互斥关系

| 对象 | 新约束 |
| --- | --- |
| cr_hold.attempt_id | 普通占用非空；取消保护占用必须为空 |
| cr_hold.cancel_execution_id | 唯一，外键到cg_plan；普通占用必须为空，取消占用必须非空 |
| cr_hold.cancel_release_policy_ref | 取消独立释放政策引用；普通占用为空；不得暗中用父命令政策代替 |
| cg_plan.protected_hold_id/digest | 将原protected_hold_ref增加类型化投影；id外键到同一cr_hold，摘要须相等；原完整Ref正文仍保留供提供者核验 |
| cr_release.cancel_validation_id | 取消hold释放必需的第二份验证原件；普通hold释放必须为空；仍保留父命令资源政策的原validation_id |

这里的两份释放验证是合取条件：原验证满足父命令的完整资源清理政策，新增验证满足取消程序自己的释放政策，均绑定同一release身份/摘要、父命令及设备。一个取消完成并不自动满足父命令未知副作用的清理；也不能仅用父命令证明解除取消动作自身的占用。Ref原文、参数、目录批准和JCS仍由可信提供者检查，SQL非空文本不是实际权威。

## 2. 准入与最终发送

普通hold仍走原attempt、T2、命令修订和取消deny规则。取消hold只允许在自己的唯一cg_plan中建立，与该计划的protected_hold_id/digest、父命令、当前有效ordinary关闭和可信hold验证精确对应。

取消hold可以与**同一父命令**的普通风险hold共存；同设备任何其他命令的风险占用仍拒绝准入，已有设备保护锁存也拒绝。其他命令虽已物理释放但公开状态仍未清理时，沿用原命令未决门槛。取消hold进入原cr_risk_hold，反过来阻止任何无关普通动作；不另设旁路锁。

计划与占用的事务顺序：Plan（hold外键延迟）→hold验证→取消hold→全部资源/primitive/依赖→plan_commit→hold_commit。原双向延迟FK保证少任一配套不能提交；plan封存核对自己的hold，hold封存要求plan已封存。取消占用此时尚未发送设备动作，不能要求先发送再拿锁，也不生成普通attempt。真实writer应同时更新公开observe投影；如果尚未提交新投影，既有cm_current自动遮蔽旧clear，允许查询暂时不可发布，不继续宣称设备空闲。

每次取消许可签发及最后ci_cancel_commit再次检查：独立hold已提交且准入验证未撤回、hold从未关闭或释放、设备没有保护、没有无关风险hold。一次guard通过不允许未来重传绕过这些检查。已有普通hold的守卫维持原约束；仅把`cv_no_hold`等普通派发规则限定到attempt非空分支，取消分支由新增强绑定守卫接管，不删除取消deny。

## 3. 释放、撤回及恢复

沿用cr_release及cx_release的完整集合：该父命令全部普通attempt/许可、取消操作及全部取消传输、有效all关闭和每项核销证据；即使释放的是取消hold也不能忽略父命令未决副作用。父命令从未发送时，普通集合可以为空，但取消集合仍须完整。零发送情况下可依据完整关闭和独立释放证明清理，不能以空集合本身推定效果。

取消独立release验证加入同一cr_release_validation视图。任一已使用的释放/关闭/核销验证撤回时，原机制同事务记录失效，重开相关hold并锁存设备保护。晚撤回发生于其他命令已获占用之后，必须保留两份风险及原许可，不用唯一设备锁拒收事实；实际关闭其他在途出口仍走完整保护传播。

新的完整释放可以清掉风险，但不能删除旧失效或自动解锁设备；随后恢复须覆盖全部历史失效，且无剩余风险。旧恢复不能吸收后来新增失效。以上行为不改变父命令终态，不复活旧取消执行，不退款预算，不替代人工接管或重新布防。

本轮核验的是**已登记资源验证原件的撤回**。取消primitive的`cg_result`撤回到所有依赖释放证明的因果清单尚未联接，不能把二者混称已经完成。后续需明确证明依赖的完整提供者回执、封存集合及撤回扇出，并归并保护outbox、完整DecisionEvidence、其他屏障/TIME和SDK。参数足迹仍需可信提供者将原Plan资源列表映射到此整设备占用；不能把字段外键检查当全系统定稿或可部署证明。

## 4. 验收与复验

`build_protected_hold.py --check`校验固定生成物；`check_protected_hold.py --report`只运行内存SQLite。报告[protected-hold-report.json](protected-hold-report.json)记录准确数量、版本和输入摘要；`--check-report --staged`只核暂存区绑定，不重跑测试。

- 父命令零普通attempt仍可获得取消保护；父普通hold与取消hold共同可见。
- 两方向的无关普通/取消占用冲突均拒绝；取消后新普通hold仍被原deny拒绝。
- Plan/hold身份或摘要错配、普通/取消身份混填、缺任一事务写入、双政策证明缺失或错误均拒绝。
- 准入撤回后签发和签发中撤回后的最终提交均拒绝；所有失败比较全部129表回滚快照。
- 独立释放证明撤回重开风险与保护；晚撤回保留其他holder，清风险后仍需显式恢复，旧恢复不覆盖新失效。

所有用例使用合成BODY/提供者和单进程内存事务。真实NTP、IPC、提供者、writer并发、进程/磁盘故障和设备验收均为零；实际SQLite版本不构成产品引擎批准。
