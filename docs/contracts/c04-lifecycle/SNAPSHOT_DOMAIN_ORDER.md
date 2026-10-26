# 快照提交序号与受保护换域

状态：内部候选，approved=false；接续[恢复依据二选一](RECOVERY_CLOSE_CHOICE.md)，不改变已确认公共基线。

已知事实：旧go_current_snapshot以sampled_tick全局排序，旧域1000会压住新域7；ct_change已有restart转换，保留控制归属与版本并强制protected。（来源：[开放存储](../c08-controller/open-storage.sql)、[控制存储生成器](../c08-controller/build_control_storage.py)。）

本轮候选增加gso_order与gso_transition。每个快照在原go_snapshot事务中自动取得单设备、单数据库连续U20提交序号；序号与时钟无关，不因进程换域清零。当前快照必须为已封存最大序号，且绑定当前控制域及descriptor。原快照seal继续要求当前控制记录、相同域、观测不早于当前控制tick，以及同域严格递增；旧域大tick不会使旧快照重新当前。序号和快照seal互相依赖，回滚不会消耗序号。

ProtectedDomainTransition保存换域ID、前后完整ControlRecord Ref、新ClockDomainDescriptor、可信提供者Ref和新域观测值。复用restart写集，持有人、模式、effective/reserved版本和未决接管原样保留，只增加记录修订并保持protected。非restart不得换域；已使用过的旧域身份不能再次启用。同ID查原，不允许更新descriptor、提供者或时间。描述符结构及摘要可校验，提供者Ref不自证真实性，真实监督域接入仍待交付。

本附属布局用于离线候选验证。安装只对每设备单一域、严格tick次序且全部封存的已有候选快照回填序号；多域或同tick历史按歧义拒绝，绝不猜测跨域提交顺序。不提供生产库迁移，旧版数据仍按既定方案作废。

跨域恢复还有独立约束：不能用新域时间重新派发旧会话关闭或生成其准备cut。完整有效退役集合应被保留引用，未能证明退役的旧出口须先完成监督终止；不能把新域tick写进旧域帧。现有授权保护writer还会展开设备全部出口，因此完整跨域恢复、主动保护传播和重新开放仍未闭合。本轮只证明换域及快照顺序，不伪造跨域保护成功。

交付：[Schema](snapshot-domain-order.schema.json)、[SQL](snapshot-domain-order.sql)、[模型](snapshot_domain_order_model.py)、[验收](check_snapshot_domain_order.py)、[报告](snapshot-domain-order-report.json)。启动、时钟提供者及快照内容仍为合成输入，没有真实设备测试，业务实现尚未开始。

本轮实际运行62项检查，覆盖263表组合、旧域1000到新域7、换域原件重复查询与篡改、六步写集故障和漏写、同域倒退、十进制低段进位、超过二进制浮点精确整数范围的序号、U20耗尽整笔回滚及不可变性。Schema序号从1开始，与SQL一致。布局锚点变化拒绝安装；本轮未运行多域旧历史回填反例、磁盘崩溃或真实并发验证，单连接事务结果不能替代这些验收。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_snapshot_domain_order.py --check`；`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_snapshot_domain_order.py --report`。报告绑定生成器、Schema、SQL、模型、验收与相关输入原件摘要。
