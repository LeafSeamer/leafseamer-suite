# 认证故障的关闭日志预约

状态：内部设计候选，approved=false。延续[设备保护事务](FINAL_AUTHORIZATION.md)，不改变draft.4／IPC 0.3，不提供产品IPC或设备调用。

已知事实：共享IPC日志已经提供双向连续序号、总帧数/线路字节上限、普通消息不能消耗的保护预留，以及前序完整入流后才能尝试下一帧的守卫。其原领域映射尚未接入认证故障的CLOSE_GATE；保护帧预留也不等于完整P0成本、磁盘和时限预算。（来源：[共享日志布局](../c08-controller/IPC_JOURNAL_STORAGE.md)、[P0预算边界](ARM_BUDGET.md)。）

本候选将这条已持久化关闭链落实到实际日志：

1. 根据完整protection_ref读取不可变ClockProtectionCommit，选择唯一close_id，并重新核对原登记出口、会话和路由。无路由、会话结束或目标改变均要求停止出口，不改成另一会话发送。
2. 在同一writer事务读取会话出站水位，分配下一序号，生成符合当前continuation IPC候选的完整CLOSE_GATE；保存JCS正文、SHA-256以及4字节大端长度前缀后的线路字节。
3. `ij_frame → authorization_close_dispatch → ij_commit`同事务提交；新增领域行引用原设备保护、go_close及完整准备cut，反向延迟外键要求日志seal。固定生成器只扩展原ij_domain_seal的认证关闭分支，其余领域守卫保持，不解除四个最终许可阻断。
4. ClockCloseDispatch仅为queued，绑定保护Ref、关闭目标、原帧Ref、wire摘要/长度与选取tick。日志disposition=applied只表示此领域预约已提交，不表示worker已关闭。相同close_id重试只查原，必须匹配完整保护Ref，不重分序号、刷新时间或重复计费。
5. begin_write在独立事务登记一次ij_write_attempt。已有尝试只能lookup_only，不能获得第二次写线路授权。原共享日志检查前序完整写入、会话未终止及时间顺序；真实I/O只能发生在可靠提交之后，提交不确定要求停止并查原。本模型不执行I/O。

容量由实际ij_frame的总行数及wire_length消费，失败整事务回滚；普通日志不能占保护预留，关闭仍受总上限约束。满额时已预约关闭仍能查原。所有记录保持不可变，准备对象或缓存退款不能回收会话历史额度。容量实验的填充行是明确合成的拒收日志，只验证SQL计数守卫；真实关闭帧使用完整规范字节，不能据此宣称全部输入协议或负载验收通过。

实际交付入口为[生成器](build_authorization_close_dispatch.py)、[附属SQL](authorization-close-dispatch.sql)、[生成日志扩展](authorization-close-journal.sql)、[Schema](authorization-close-dispatch.schema.json)、[参考模型](authorization_close_dispatch_model.py)、[检查器](check_authorization_close_dispatch.py)与[报告](authorization-close-dispatch-report.json)。历史候选保持原字节，测试在253表上安装附属映射，形成254表实验。安装会核对固定上游触发器身份，不能用于任意生产数据库迁移。

验收覆盖完整线路帧、序号连续、同close幂等、逐写回滚和缺写拒绝、一次入流尝试、结束后禁止新预约/首次入流、满额幂等查原及保护预留。会话结束不生成ce_retirement、go_close_ack或pd_close_completion；在ACK、完整准备核销、资源与身份重新验证之前不得将queued解释成恢复资格。

剩余事项：真实唯一写出口与宿主采集/身份来源、完整P0 CostManifest和分层预留、磁盘/WAL预算、关闭ACK领域迁移及PreparationClosure仍待接通。当前选取tick是合成输入，不能据此证明真实时间顺序。实际线路、设备及崩溃恢复未验证；阶段0未关闭，业务实现未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_authorization_close_dispatch.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_close_dispatch.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_authorization_close_dispatch.py --check-report
```
