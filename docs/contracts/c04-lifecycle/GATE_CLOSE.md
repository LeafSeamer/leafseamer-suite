# 健康出口的独立关闭原件

状态：内部候选，approved=false；不修改已确认公共基线，不解除最终发送阻断。

已知事实：既有完整关闭请求依赖authorization_clock_protection，其来源是认证时钟故障计划；新健康出口的注册关闭没有这类故障记录。旧首次开放夹具中的close_ack只保存合成占位正文，不能充当完整关闭原件。（来源：[认证关闭writer](authorization_close_dispatch_model.py)、[首次开放夹具](typed_gate_path_model.py)。）

本候选增加GateCloseDispatch与GateCloseAcknowledgement。关闭请求直接引用不可变go_close的完整摘要、首次绑定出口、固定会话、同域准备cut、完整CLOSE_GATE帧及线路摘要。必须当前protected、最新关闭、会话未结束且worker未退役；不用伪造认证故障。与既有认证关闭入口按close_id互斥，同一次关闭不能通过两个入口重复排队。

ACK要求完整长度前缀及JCS、固定会话与请求reply、精确单设备覆盖、严格日志序号和已登记写尝试。同ID重复只查原，不重新排队、写线路、刷新时间或再采用。当前条件失效时迟到ACK只入历史；关闭证据撤回、会话结束或worker退役取消当前资格。已采用正文与go_close_ack及日志同事务保存，缺写不能提交。

本轮只交付独立关闭请求和ACK。准备核销、RecoveryCloseChoice的类型化读取仍绑定认证关闭访问器，后续必须统一为按持久原件类型选择的访问层，再串接健康新出口恢复、GATE_FENCE、OPEN_GATE及新grant。不得使用占位ACK、虚构认证故障或省略准备核销来跳过该缺口。

交付：[Schema](gate-close.schema.json)、[SQL](gate-close.sql)、[完整安装布局](gate-close-journal.sql)、[请求模型](gate_close_dispatch_model.py)、[ACK模型](gate_close_ack_model.py)、[验收](check_gate_close.py)、[报告](gate-close-report.json)。身份、监督启动和接收观察仍为合成，未执行线路和设备动作，业务实现尚未开始。

本轮实际66项检查通过，使用268表组合，覆盖无新认证故障的关闭、精确原件引用、错域/reply/设备/序号拒绝、非规范线路、请求和ACK逐写/漏写回滚、提交前后观察故障、迟到历史ACK及证据撤回。旧认证关闭与新入口的互斥拒绝原因已单独断言。当前只有合成写尝试与ACK，不声称线路实际写出或物理关闭完成。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_gate_close.py --check`；`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_gate_close.py --report`。准备核销访问层与完整重新开放仍为未验项。
