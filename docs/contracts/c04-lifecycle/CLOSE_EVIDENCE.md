# 关闭原件访问与健康出口恢复

状态：内部离线候选，approved=false。只扩展参考模型，不改变已确认公共契约，不开始业务实现。

已知事实：普通健康出口与认证故障关闭各自持久化完整请求、ACK及日志，原SQL已按close_id禁止重复来源。准备核销和RecoveryCloseChoice此前直接读取认证关闭表，健康出口因此不能进入同一消费链。（来源：[普通关闭](GATE_CLOSE.md)、[准备核销模型](authorization_prepare_closure_model.py)、[恢复模型](recovery_close_choice_model.py)。）

本轮方案：新增[关闭原件访问层](close_evidence_model.py)，只根据数据库内唯一dispatch来源选择读取器。调用者不能指定来源，来源缺失拒绝，双来源歧义拒绝；不从失败读取退回另一协议，不消费占位ACK。既有认证路径在未安装普通关闭表的数据库仍按原契约工作。当前资格按对应来源的usable视图计算，ACK身份必须属于同一close。

准备核销保留完整selector、registry与prepare证据规则。恢复公开形状仍是worker_ack或supervisor_retired；worker_ack内部可引用普通或认证ACK原件，引用摘要和采用ID逐项核对。会话结束、ACK撤回使普通关闭的准备核销和恢复资格同步失效；历史记录保留，重复请求只查原并返回当前资格，不重新采用。

本轮验收使用健康新时钟域、完整注册关闭ACK、空cut与非空旧注册表；新ACK核销与旧worker退役集合共同封存恢复。覆盖逐写故障、缺写、提交前后观察故障、外事务拒绝、撤回先于消费和消费后失效、历史查原及来源歧义。提供者、监督启动和会话仍为合成；空cut验收不能证明新域非空prepare链，SQLite提交观察故障不能证明进程断电恢复。

恢复封存之后仍保持protected，四个最终发送阻断保留。完整GATE_FENCE、OPEN_GATE、新grant、新命令与attempt、新域非空准备及最终AdmissionSeal仍待设计与验收。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_close_evidence.py --report`。实际结果与输入摘要见[验收报告](close-evidence-report.json)，用`--check-report`核对报告输入。本轮不涉及线路写出或设备动作。
