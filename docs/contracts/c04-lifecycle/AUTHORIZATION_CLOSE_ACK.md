# 认证关闭ACK与准备核销分界

状态：内部设计候选，approved=false。接续[有序关闭预约](AUTHORIZATION_CLOSE_DISPATCH.md)，不修改已确认的公共基线，不执行产品IPC。

已知事实：当前CLOSE_GATE_ACK只有close_id与closed_device_ids，不携带“所有准备均已核销”的证明。既有pd_close_completion还要求完整PreparationClosure；go_close_ack本身不能替代它。（来源：[当前IPC候选](continuation-binding-ipc.schema.json)、[准备核销SQL](../c08-controller/prepare-deny-storage.sql)。）

本候选采用以下持久化和当前资格规则：

- 接收完整线路字节，校验4字节大端长度前缀、上限、规范JSON与当前IPC Schema；按原dispatch读取固定请求、会话及入流尝试。ACK的设备字段为null，body的设备集合必须恰好覆盖原单设备请求，不能漏目标、加目标或换close_id。完整运行域与reply_to必须匹配，收到时刻不得早于原尝试。
- `ij_frame → authorization_close_ack → go_close_ack（仅当前）→ ij_commit`同事务保存。新增ACK行与日志seal采用反向延迟外键；当前采用还要求实际go_close_ack配对。旧领域守卫保留，已有握手等其他消息不被通用成功分支绕过。
- 会话未结束且该close仍对应当前protected控制状态时，ACK记applied；否则记historical，仅保存原件。applied仅表示该ACK被本地采用，不证明设备动作结果、资源清理或全部准备核销。observer_ref目前是合成可信入口引用，端点真实性仍待运行时实现。
- 同close_id重复必须有完全相同的原线路字节和observer_ref，只读取原回执，不刷新接收时间、增加日志或重新采用。新message_id的重复回复按冲突停止处理，不能占新seq后替换历史ACK。
- `authorization_close_usable_ack`实时要求原close仍为出口最新关闭、活会话、已提交applied日志及未撤回ACK。采用入口另要求当前protected控制状态；后续合法恢复改变控制记录不自行抹去已采用证据，否则恢复会使自身依据失效。结束、更新关闭或撤回发生在采用之后，原回执仍保留，但当前资格立即消失。pd_close_completion和新恢复目标都核对此资格，go_valid_recovery也动态排除已经失效的认证关闭证据。

候选入口：[生成器](build_authorization_close_ack.py)、[附属SQL](authorization-close-ack.sql)、[生成日志扩展](authorization-close-ack-journal.sql)、[Schema](authorization-close-ack.schema.json)、[参考模型](authorization_close_ack_model.py)、[检查器](check_authorization_close_ack.py)、[报告](authorization-close-ack-report.json)。实验在254表关闭预约布局上追加一表；安装核验既有日志触发器及恢复视图精确内容，不是生产迁移。

故障与验收：写集中任意缺写、逐步异常、提交前失败均不得留下半条ACK；提交后回执丢失只能查原。错误会话、reply、设备集合、长度、JSON重复键及接收时间拒绝。会话结束前后的两种顺序都必须使最终当前资格失效；历史ACK不能直接补go_close_ack。非空准备cut缺证明、将已尝试准备写成never_attempted均不得核销。原持有人和protected状态保持，不产生新permit或自动恢复。

恢复前后态的视图依赖另以最小关系夹具隔离验证，只证明采用条件与后续证据可用性的分离，不证明完整T5事务、生产恢复或设备行为。

剩余事项：端点与单调时刻的真实提供者、worker实际CLOSE_GATE行为、DENY/Release/监督退役完整证明提供者、准备核销的正向全链、完整P0和磁盘预算、真正恢复及最终T2仍待完成。本轮只验证合成ACK通过实际SQLite约束后的持久化与失效传播，不声称真实IPC、设备关闭、并发崩溃或直播验收通过；阶段0未关闭，业务实现未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_authorization_close_ack.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_close_ack.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_close_ack.py --check-report
```
