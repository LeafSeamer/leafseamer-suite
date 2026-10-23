# 取消资源核销与迟到失效候选

状态：待审阅，103表离线组合。`build_cancel_resource.py`把[99表RUN覆盖](CANCEL_FENCE.md)与`cancel-resource.sql`组合，输出`controller-cancel-resource.sql`。移除“父命令含取消传输就一律拒绝释放”的临时阻断，改为完整成员、all关闭及当前有效核销证据的要求；旧99表保留历史。释放之后禁止继续给该取消签发设备传输。

已知事实：99表已保存取消传输、原报告、核销及RUN覆盖，但`cr_release_member`与释放失效来源仍仅关联普通传输。已有恢复机制要求先清理全部风险占用，再精确消费已知失效集合。（来源：`resource.sql`、`cancel-fence.sql`及[命令资源设计](COMMAND_STORAGE.md)。）基于这些约束，本轮沿用同一资源权威和恢复机制，补取消关系；不另造一个可绕过普通资源锁的取消资源状态。

## 1. 字段与封存规则

| 表 | 字段与绑定 |
| --- | --- |
| cx_closure | cancellation_id、operation_revision、validation_id、closure_digest/body；引用已提交且future_writes=closed的原取消修订，验证回执必须属于同命令、设备、取消身份及释放政策，purpose=close |
| cx_settlement | settlement_id引用cf_settlement，validation_id引用cr_validation、settlement_digest；回执须绑定该取消传输的父命令/设备、原核销ID、同一释放政策，purpose=settlement |
| cx_release_cancel | release_id、cancellation_id、closure_validation_id；每条释放完整列出父命令的取消操作及其all关闭证据，不允许只保留ordinary关闭 |
| cx_release_member | release_id、permit_id、settlement_id；完整列出全部取消传输历史，包括已核销的初始与重传，不能只取当前open集合或最后一次许可 |

释放仍用cr_release/cr_release_commit：共享ci_issue水位、全部普通attempt及关闭证据、全部普通许可与核销，加上述取消集合、审计与outbox同事务封存。两个新集合分别双向EXCEPT；取消核销必须指向该permit且提供者未撤回。never_sent要求当前not_sent，整个release的never_sent类别不能夹带effect_resolved。合法Schema或非空BODY不能替代来源、摘要、权限与效果政策验证。

cx_closure把公开closed修订与独立资源提供者回执双重绑定，**尚不代替完整ordinary/all屏障原件FK**。当前closed的语义仍依赖此前明确的“仅all关闭才可公开closed”；具体目标/ACK/采用到该修订的完整来源图、取消执行Plan与独立准备/预算仍待下一布局归并。因此103表不是可部署的最终迁移。

## 2. 强事实、证明撤回与恢复

扩展cr_release_validation，使取消关闭及取消核销回执参加既有撤回机制；扩展cr_invalid_release，使被in_flight推翻的取消never_sent也使原释放失效。普通与取消共用cr_risk_hold、cr_device_protection、恢复写集，不删除旧释放，不把原命令终态重新计算为成功。

| 事实来源 | 同事务效果 |
| --- | --- |
| cf_report的in_flight | 保存原报告，引用cancel_report来源登记首次release失效，设备保护锁存 |
| 原ce_barrier_ack的取消in_flight覆盖 | 无论最终是否采用，强事实进入风险视图并产生失效；来源仍是精确barrier_id |
| 目标结果的取消in_flight覆盖 | 以fence_id/exit_id绑定来源，不和普通覆盖混淆 |
| 取消关闭/核销或总释放提供者回执撤回 | 既有validation_revocation路径使对应释放失效并锁存保护 |

失效来源判定同时支持普通与取消成员；服务器报告ID与工作进程报告身份仍独立。取消报告使用独立source_kind，避免同名普通报告被误认为同一原件。首次失效去重不丢后来的原始报告或撤回记录。

修复需要追加当前有效的独立核销与一份新的完整释放；旧失效记录继续保留。随后恢复必须精确覆盖该设备所有已知失效，且当前风险占用为空。旧恢复不能覆盖后续新出现的失效；恢复只解除设备保护，不自动重放动作、恢复运行或改写取消结果。单纯重复传输报告不会撤回独立effect_resolved，相关提供者证据撤回则会重新锁存。

## 3. 验收与限制

`check_cancel_resource.py --report`实际加载103表，验证释放逐条缺写/主动异常回滚、双类别完整历史、错误核销与关闭关联、三种迟到来源、撤回与失效同事务、新释放和精确恢复、不可变记录及外键完整性。预期集合手写，BODY/摘要与提供者真实性为人工前提；回滚不是磁盘崩溃，串行顺序不是writer并发。`--check-report [--staged]`只核声明输入原字节。

剩余设计：取消执行Plan和ordinary/all关闭的原件来源图、资源足迹与独立取消准备、真实身份/时间/预算提供者输入、完整公共状态投影、FENCE/AUTH/TIME以及时间27表归并。实时设备、真实IPC、并发和磁盘耐久尚未运行；候选通过不关闭全系统设计，也不解除“先设计后实现”的阶段约束。
