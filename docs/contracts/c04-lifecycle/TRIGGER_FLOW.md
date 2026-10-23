# 普通触发至状态提交同库候选

状态：`trigger-flow-storage/0.1.0-draft.1`，`approved=false`。承接[90表布防退出布局](ARM_EXIT.md)，增加[约束](trigger-flow.sql)、[91表组合](seamer-trigger-flow.sql)、[生成器](build_trigger_flow.py)、[参考写集](trigger_flow_model.py)、[检查](check_trigger_flow.py)及[输入绑定报告](trigger-flow-report.json)。本轮只交付设计与离线验证材料，公共draft.4／IPC0.3尚未归并，业务实现和部署未开始。

## 已知事实与验证范围

离线检查从真实arm登记、准备回执采用及完成写集开始：run为armed、revision=3、generation=1；事件受理后run变running、revision=4，槽revision从2到3；完成全部必需动作并提交R5后，run回armed、revision=5，业务状态从idle/revision=1到live/revision=2。再次触发读取当前live/2，不复用旧执行。这里的“真实写集”指实际执行SQL，不表示真实认证、网络或设备证据。

旧90表隔离反例实际得到run仍running、业务状态仍idle而execution已经succeeded。新布局要求transition_commit反向延迟引用flow_commit_seal，最后seal核对完整run、业务状态、槽、审计和通知。摄取最后seal也显式核对PLAN的transaction_record与event_outbox，防止仅创建执行计划而漏通知。

本轮151项检查涵盖列出的路径，验证器比较失败前后全部91表快照。主动异常回滚属于事务检查，不能作为进程崩溃、磁盘持久性或并发验证。（证据：[检查源码](check_trigger_flow.py)、[报告](trigger-flow-report.json)）

## 内部字段与写入顺序

| 对象／阶段 | 字段及原子边界 |
| --- | --- |
| ingress_snapshot.body | 内部flow_version、run_id、run_revision、generation、slot_revision_before/after、input；accepted必须精确匹配当前run/槽并各推进一次。这是存储投影，尚不是公共EvaluationSnapshot的完整wire格式 |
| 摄取受理 | inbox、完整监听集合、每run决策、执行计划及步骤、run/槽修订、来源与摄取水位、审计通知和charge同事务，最后ingress_commit.sealed=1；计划和外部求值资格仍由合成上下文提供 |
| anchor／ready | anchor绑定原触发决策；动作ready绑定不可变计划及anchor。提交后时钟采样、依赖核验和当前运行域是提供者前提 |
| command_submission | 从步骤原计划提取完整Controller scope、request及parameters_ref；目标必须属于本run当前代次有效准备，恢复准备还须属于本execution |
| submission_attempt | 当前执行及派发资格检查后持久记录attempt；提交成功才返回一次调用标记。重开查原返回原身份，不新投；本模型没有实际网络发送 |
| 受理及终态 | accepted保存精确submission、request摘要、scope与command引用。succeeded必须匹配已受理command的完成证据；accepted本身不改变业务状态，迟到accepted不改unknown |
| transition_commit | 新增规范U20文本run_revision_before、run_revision_after、slot_revision；run必须精确后继，状态机源状态/revision采用当前CAS，目标与execution一致，规则不伪造状态行 |
| flow_commit_seal | commit_id反向配对transition_commit，非空audit_body与notification_body；封存前run必须armed且无活动操作/执行、last_commit和修订精确，业务状态和槽一致，当前准备/来源/锁存/DENY合格，R5审计通知齐全。原件不可修改删除 |

R5写入顺序为审计/通知、transition_commit、execution成功投影、业务状态投影（状态机）、run投影、最后seal；它们必须在同一事务。seal不是任意SQL写入之后的自动全库验证：可信writer必须遵循这份完整写集，不允许seal后再写相冲突的业务投影。

恢复执行继续走原R2/R4/R5协议，补齐新三列并最后封存；seal要求recovery_operation已completed且recovery_lock已有release_id。普通finish显式拒绝恢复执行，不能借普通完成绕过恢复收尾。

## 失败、重入与故障时序

- 必需动作failed或任意动作unknown/blocked/expired/cancelled：保存终态及审计，同事务暂停当前run、关闭dispatch、追加锁存并投影execution；旧业务状态及活动execution引用保留。旧代次回报只记历史，不暂停另一代次。核心SQL资格也拒绝后续ready、submission、attempt和R5；失败前生成的旧ready写集同样被拒绝。
- 可选动作确定failed可在其它必需动作成功后提交；可选unknown不能按可选失败忽略。本轮只使用独立action步骤，完整依赖图、并行组和三值求值不由这些正例证明。
- 忙时事件可靠记录suppressed_busy，完成后不补发；no_match不产生执行且不改变run修订。完整监听集缺项拒绝；重复事件同身份同内容查原零写，异内容冲突。
- source失步或准备资格撤回后拒绝新的推进；R5最后seal前出现新锁存或槽变动整笔回滚。摄取及R5逐条漏写、各阶段逐写异常、失败投影逐写异常均验证全库回滚。失败投影尚未具备独立的“任意漏写都被最终seal拒绝”证明。
- R5原提交查原必须有当前读权限及原seal，返回原完成结果，不执行第二次状态迁移。尝试查原同样先核权限。真实权限生命周期仍由AUTH契约承担，合成布尔值不构成实现。

## 推荐边界与剩余冻结事项

1. 采用91表作为普通触发与R5联接候选，保留旧90表作为独立历史验证输入。当前失败锁存只证明本机停止新派发，须继续接入完整Controller保护计划、未知在途集合、关闭证据及资源核销，不能将本地paused当作远端关闭完成。
2. 将内部snapshot、计划、command回执、seal和通知逐项映射到唯一SDK契约源；本轮合成对象不是已冻结公共API。实际AST求值、歧义与unknown、完整依赖计划、参数/完成提供者、OBS能力映射仍须联接。
3. ingress_charge仅合成计费投影，未接真实预算消费；保护预算、恢复新预算、层级账本和GC仍待完成。当前来源年龄/来源鉴权/监督域/时间窗口/完成与释放资格也都是显式合成前提。
4. 来源异常检测至P1闭锁的服务编排、通用disarm/retire、混合历史关闭库存、AUTH/TIME、Controller最终准入和完整SDK仍有缺口。不得通过删除这些功能收缩最终交付范围。
5. 本报告没有实际服务、网络、设备、并发、磁盘崩溃、SQLite FULL/IOERR或长期容量证据。候选未获部署批准，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_trigger_flow.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_trigger_flow.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_trigger_flow.py --check-report
```
