# 监督退役原件采用与旧出口禁写

状态：内部设计候选，approved=false。接续[监督完整原件来源](../df02-supervisor/RETIREMENT_SOURCE.md)，不改变已确认公共基线。

已知事实：ce_exit已有runtime_binding_body，但此前类型化夹具仅保存占位BODY。退役采用不能从来件反向补造启动身份。既有cu_revocation支持撤回退役证明，ce_retirement保持不可变；证明失效与允许旧进程重新发送是两个不同判断。（来源：[既有登记模型](typed_gate_path_model.py)、[控制器候选布局](controller-typed.sql)。）

本轮候选增加RuntimeExitBinding与RetirementAdoption字段、两表sr_adoption/sr_commit和读写适配器。完整启动绑定必须在ce_exit首次登记时写入：包含实际Binding、可信监督来源身份、完整意图、AdmissionReceipt、准入授权证据Ref及正文摘要。读取时逐项核对scope、controller/worker boot、IPC/device session、设备、时钟域、member、制品、组和原意图摘要；不提供事后覆盖入口。真实准入审批与认证仍须独立完成，授权Ref不是自证有效的凭据。

采用入口接收已打开的受信监督SQLite连接及证据ID，调用来源读取器取得同一快照，并将完整意图和准入回执与已登记出口逐字关联；不接受任意网络Bundle重算摘要后直接采用。候选中的连接来自合成夹具；真实监督库打开、路径权限、认证导出通道及防回滚身份尚未验收。

控制器在自己的BEGIN IMMEDIATE中重读出口绑定并要求设备处于protected，写sr_adoption、完整ce_retirement和sr_commit后才返回。双向延迟外键及seal守卫拒绝半边采用。已采用的同出口、同监督身份与同证据ID仅查本地原件及当前资格，不再读取监督库；来源后续关闭或暂不可访问不刷新历史。首次采用竞争若发现同键已提交，则核对完整不可变原件，允许仅快照中的运行阶段变化，不允许证据内容替换。两库不构成分布式事务：读取的是已提交不可变原件，控制器提交不确定只查询本地原键，不重建来源事实。

旧会话禁写从已封存退役采用派生，对该session所有后继ij_write_attempt生效，包括设备字段为空的CLOSE_GATE。撤回通过既有cu_revocation取消sr_current资格，但不删除sr_commit、ce_retirement或旧会话禁写墓碑，因此撤回不能复活旧worker。这里没有制造新的ij_end时间：监督观察域与旧会话域的tick不能直接比较，采用不伪造旧域时刻。

采用不退款、不改变持有人和protected状态，不生成准备closure或恢复许可，也不将已发送命令改为失败/未发送。retired准备核销及关闭完成的替代来源将消费本采用记录和当前资格，仍待后续接通；不能仅见ce_retirement就宣称整设备恢复安全。一个worker对应多个出口时，旧session统一停止写入，各出口的完整采用与集合核销仍需逐项覆盖。

交付：[字段生成器](build_supervisor_retirement_adoption.py)、[Schema](supervisor-retirement-adoption.schema.json)、[附属SQL](supervisor-retirement-adoption.sql)、[参考模型](supervisor_retirement_adoption_model.py)、[检查器](check_supervisor_retirement_adoption.py)、[报告](supervisor-retirement-adoption-report.json)。夹具在首次INSERT时注入完整合成启动绑定，监督原件在真实15表保存，控制器使用257表组合；它不证明真实启动审批、HMAC、OS终止或IPC执行。

剩余事项：真实启动绑定writer及审批当前性、受信监督连接提供者、控制器退役采用撤回的保护传播全链、同worker多出口完整集合、retired准备证明与替代关闭完成、后继新出口准入、完整T5/T2与P0验证。阶段0未关闭，业务实现未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_supervisor_retirement_adoption.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_supervisor_retirement_adoption.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_supervisor_retirement_adoption.py --check-report
```
