# 监督退役完整原件来源

状态：内部设计候选，approved=false。落实[释放与退役分界](../c04-lifecycle/AUTHORIZATION_PREPARE_RELEASE.md)，不改变已确认公共基线。

已知事实：监督日志已有15表、不可变原件、完整退役成员和不可逆状态约束，但原SQL实验使用合成BODY占位；SQL通过并不证明BODY与投影列相符，也不证明OS实际清空。（来源：[监督日志](journal.sql)、[既有检查器](check_journal.py)、[监督日志说明](JOURNAL.md)。）

本轮交付的是监督库内的同一快照读取与完整关联校验。调用方必须提供由可信配置取得的host_installation_id、incarnation_id、service_id、database_instance_id及os_provider_id；这些不能取自待验证bundle后原样回填。读取入口自行开启只读事务，不接管外部未提交事务，失败不交付证明，不修改来源库。

读取并核对：

- journal_meta与control_scope的宿主、incarnation、服务及数据库身份；旧运行域与观察运行域的完整ClockDomainDescriptor、JCS摘要和SQL投影。
- 已封存confirmed_empty退役原件、全部retirement_target、终态launch_state及完整启动意图。runtime_domain要求域已retired且覆盖所有历史launch；member_group要求精确唯一目标。超过候选256项边界失败，不截断日志中的4096项物理上限。
- 已准入成员的AdmissionReceipt、bootstrap身份、member_boot、channel、artifact、进程观察引用与原准入窗口。未准入成员保持null，不制造已准入事实。这里重核持久引用和内容关系，不重新证明原HMAC或OS进程实例真实性。
- 新Observation候选要求精确provider、旧域、观察域、containment代次和完整成员集合，启动入口关闭、组归属明确、成员枚举完整、存活进程数与开放端点数均为零。观察原件与退役证据必须引用同一完整集合；当前监督日志每条退役证据对应一个聚合OS观察，不能额外加入未关联观察。
- observed_tick只与可信调用方指定的同一evaluator_domain中的now_tick比较，不与旧域的admitted_tick比较。旧域tick15与新域tick2是合法组合；错误域或未来观察拒绝。

[Schema](retirement-source.schema.json)由[生成器](build_retirement_source.py)导出，包含SourceIdentity、Observation和Bundle。Bundle保留完整旧/观察域描述、退役原件、成员意图与准入回执、观察原件、所读取SQL行的journal_snapshot_digest及整体bundle_digest。摘要仅绑定内容；它不是签名、认证通道或防回滚证明。不得把从不可信网络取得且自行重算摘要的Bundle当作可信退役授权。

[参考模型](retirement_source_model.py)和[检查器](check_retirement_source.py)使用真实15表SQLite与完整规范JSON。正例覆盖单组和双成员全域退役、两个独立时钟域、稳定重复读取；反例覆盖错误宿主/数据库/provider、遗漏成员、未清进程或端点、错误启动回执、非规范JSON、超限和读取事务失败。OS内容仍由合成夹具注入，没有启动或终止实际进程。

控制器后续采用契约：以受认证来源及已登记的运行域/成员绑定接收Bundle，精确核对writer_exit与member_boot、设备集合、旧会话和旧域；先持久退役采用及撤回依赖，再形成retired准备证明。关闭完成来源必须显式选择worker ACK或supervisor退役，不能把结束的旧会话ACK重新标活。该替代完成与新出口准入仍待实现，本轮不会写ce_retirement、退款、恢复控制或解除最终发送阻断。当前核销的活会话规则保持。

剩余冻结事项：认证导出通道与防回滚身份、控制器RuntimeBinding的完整成员来源、退役采用/撤回事务、替代完成选择、不同观察域的长期历史有效性、超过256成员的有界分段、真实OS提供者及故障验收。阶段0未关闭，业务实现未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/build_retirement_source.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/check_retirement_source.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/check_retirement_source.py --check-report
```
