# 准备释放采用与监督退役分界

状态：内部设计候选，approved=false。接续[准备核销](AUTHORIZATION_PREPARE_CLOSURE.md)，不修改已确认公共API基线。

已知事实：既有SQL把er_request、er_ack、er_adoption、ep_release与领域seal分别保存，并以延迟外键约束原子采用；共享日志另要求完整帧与领域行对应。准备核销已定义released和retired两种证明，但此前实际参考入口未接通它们。（来源：[释放持久化](../c08-controller/encoding-release-storage.sql)、[共享日志组合](../c08-controller/build_ipc_journal_storage.py)、[核销SQL](../c08-controller/prepare-deny-storage.sql)。）

本轮采用的释放接线：

- 从实际cut成员、授权、原编码帧和撤回构建ReleaseRequest，保存完整RELEASE_ENCODING、er_request、er_request_commit与ij_commit。未尝试编码、已回收或已退役出口不得预约。每个请求仅登记一次入流尝试，前序尚未完整written时不得越过。
- ReleaseAck必须精确匹配运行域、prepare、请求Ref、message、帧摘要与reply；encoder_quiescent、consumers_quiescent、cache_empty必须全为true，满足实际入流尝试≤disposed≤received。结构正确的ACK仍需与持久请求和实际尝试关联。
- 同事务写入完整ACK、ReleaseAdoption、ep_release、er_ack_commit及ij_commit。采用的预留ID、版本、摘要和字节数从原ep_request读取，不由ACK指定。缺任意一环均回滚。ACK尚未采用时不回收，重复ACK只查原，不再次退款或刷新时间。
- 准备核销遇到worker_released时，重读完整请求、ACK、采用及两层seal，验证原预留和回收记录；使用released证明与其他成员组成完整集合。该分支不要求伪造DENY_ACK。回收仅指逻辑活缓存额度，不表示磁盘物理空间已释放。
- 同会话正常采用要求会话未结束、出口未退役。结束后首次到达的ACK在本入口被拒绝并回滚，不能退款；历史入流隔离及已退役后的历史释放ACK由后续入口处理，当前不冒充已完成该功能。已经采用的同一ACK可继续查原，完成资格仍随会话结束而失效。

监督退役的跨项分析：当前authorization_close_usable_ack要求旧会话存活，而真正退役应禁止旧会话继续发送。直接取消活会话条件会使普通失联ACK被当成退役证明；直接把ce_retirement的不透明BODY作为证明也不符合受监督运行域要求。因此保留现有阻断，退役恢复走独立证明分支，不伪造关闭ACK、不重新开放旧出口。

后续退役分支必须冻结并交付：

1. 从Supervisor持久日志读取RetirementEvidence及覆盖成员、运行域、containment、OS观察原件；核实启动入口已关闭、完整进程组为空、端点已释放，result必须confirmed_empty，不能只凭PID消失。旧域与评估域分别绑定，禁止跨域直接比较单调tick。
2. 控制器以精确exit绑定采用证据，并区分“旧出口已关闭”和“准备不再可执行”；已发送命令结果继续保持未知，不能据此宣称设备回滚。
3. 旧出口准备closure允许以有效监督证据完成；完成选择须表达worker关闭ACK或supervisor退役的互斥来源，不强求已结束会话的ACK仍然可用。所有退役证据撤回应使依赖资格失效。
4. 新出口通过新的启动身份、会话和完整准入进入关闭态；人工确认或已批准恢复策略之后才重新打开。旧出口不得复活，普通会话结束不得自动转换成监督退役。

上述监督分支为待落实推荐，不是已实现或已验证结论；对应来源为[监督Schema](../df02-supervisor/supervisor.schema.json)与[监督日志](../df02-supervisor/journal.sql)。目前仅以反例证明不透明retirement占位不能完成当前核销。

交付：[参考模型](authorization_prepare_release_model.py)、[检查器](check_authorization_prepare_release.py)、[报告](authorization-prepare-release-report.json)。实验使用真实内存SQLite写集，written、ACK和时刻是合成输入；覆盖完整混合核销、原预留回收、逐写异常/缺写、提交观察不确定、错配与未静止ACK、会话结束和退役阻断。

剩余事项：监督证据完整提供者及替代完成分支、释放证据事后撤回与额度对账、结束后历史ACK隔离、真正worker停止借用/编码/清缓存、完整T5/T2、P0与磁盘预算尚未完成。业务实现未开始，阶段0未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_prepare_release.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_prepare_release.py --check-report
```
