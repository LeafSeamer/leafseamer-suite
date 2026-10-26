# 认证关闭后的完整准备核销

状态：内部设计候选，approved=false。接续[关闭ACK](AUTHORIZATION_CLOSE_ACK.md)，复用255表组合及现有DenyRequest、DenyAck、PreparationClosure，不修改已确认公共基线。

已知事实：关闭ACK与准备核销是两个条件。既有SQL要求固定cut中的每个准备均有有效证明，且完整集合封存后才能关联pd_close_completion；已尝试准备不符合never_attempted。（来源：[准备核销SQL](../c08-controller/prepare-deny-storage.sql)、[现有字段Schema](../c08-controller/ipc-journal.schema.json)。）

本轮推荐并验证的候选接线如下：

- 从实际go_close、pd_member、ep_request完整授权、原ENCODE_PACKET与ep_revocation构建DENY_ENCODING。引用授权、原请求帧摘要及撤回版本，不以新生成的替代原件冒充历史来源。请求、领域行及日志seal同事务保存。
- 每个DENY只登记一次入流尝试。ACK必须匹配完整运行域、准备ID、请求Ref、原message与帧摘要；满足尝试时刻≤生效时刻≤接收时刻。按完整线路字节和4字节长度前缀验收，拒绝非规范JSON及重复键。首次会话已结束时只存historical，不能形成当前证明。
- 核销在BEGIN IMMEDIATE内读取固定cut全部成员和固定登记head。已尝试准备必须有未撤回、已提交applied的DENY ACK；未尝试准备使用实际请求、撤回和登记head形成never_attempted证明。写入完整PreparationClosure、逐成员coverage、closure_commit与close_completion后才返回。SQL完整差集校验拒绝漏成员、漏写和把已尝试准备伪装为从未发送。
- 同一请求、ACK和完成结果重试只查原，不刷新时间、序号或预算。ACK重试必须为同一线路原件；提交观察不确定时停止，重新读取持久结果。证明撤回、原关闭ACK撤回或会话结束使当前完成资格失效，历史完成保持，不能自动重建或恢复。
- 本地候选限制最多4096个cut成员及登记项、16MiB核销正文；超限失败，不截断。这只是有界离线参考实现，尚非生产P0容量证明。完整历史登记上限的长期分段与回收仍待设计；不得将其当作无限运行保证。

验收夹具先建立两个真实持久准备，再保护关闭：一个已有编码与入流尝试，另一个尚未尝试。前者经DENY ACK、后者经never_attempted共同形成核销。检查逐写异常、逐表缺写、单成员遗漏、提交前后观察故障、错误回复绑定、未来或过早生效、序号跳跃、线路异常、容量拒绝及证明失效。不改变持有人、protected控制状态，不退款、不产生最终许可。

故障顺序：保护与撤回持久化 → CLOSE_GATE入流尝试和合成written → CLOSE_GATE_ACK → DENY预约 → 单次尝试和合成written → DENY_ACK → 全成员核销。任一事务失败回滚本事务；已提交的前序事实保留。核销前撤回DENY证明则拒绝提交；核销后撤回则保留历史、移除当前有效资格。先结束会话再收到ACK只能记历史，后结束同样取消当前完成资格。

交付：[参考模型](authorization_prepare_closure_model.py)、[检查器](check_authorization_prepare_closure.py)、[报告](authorization-prepare-closure-report.json)。报告的输入摘要绑定实际SQL、Schema、参考模型和夹具版本。

剩余事项：本轮正向提供者只覆盖deny_ack与never_attempted；released与retired仍必须接通实际释放/监督退役完整证据，不能缩减为不支持这些需求。完整T5恢复、最终T2、真实worker唯一出口、可信端点/单调时刻、物理终止、完整P0与磁盘容量及登记历史回收继续待完成。written与ACK由合成夹具注入，SQLite通过不证明实际发送、设备行为、崩溃恢复或直播验收。阶段0未关闭，业务实现未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_prepare_closure.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_prepare_closure.py --check-report
```
