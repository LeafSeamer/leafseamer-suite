# 跨域恢复与退役撤回的提交边界

状态：内部离线验收，approved=false；接续[跨域保护](DOMAIN_PROTECTION.md)，不放行最终发送或改变已确认公共基线。

已知事实：恢复与退役撤回writer都自有BEGIN IMMEDIATE事务；授权编码入口要求cn_live_command当前成立。上一轮跨域换域后的旧命令不能在新出口再造准备，实际返回encoding_origin。（来源：[准备事务](authorization_prepare_closure_model.py)、[恢复writer](recovery_close_choice_model.py)、[退役撤回](supervisor_retirement_adoption_model.py)、[编码入口](typed_encoding_path_model.py)。）

本轮执行边界：撤回先提交，恢复须失败且不留下go_recovery或新快照；恢复先提交，随后撤回取消其当前资格，已存历史仍可查原。竞争者遇SQLite writer锁必须整体退出，重试重新读取当前依据，不允许继续使用先前的资格结果。同ID历史重试不产生写入，也不重新取得恢复资格。

WAL读事务可以继续看见撤回前的旧有效视图，这是本地实验观察到的快照隔离行为。该读结果只供展示或历史读取，不能跨事务缓存为开放、接管或发送依据。需要变更的writer须另起自有事务并核验当前原件；不得接管调用者的旧读事务。最终发送仍受原有四项阻断约束，完整AdmissionSeal路径尚未完成。

当前域非空准备正例仍未完成：必须先以有效新授权接通重新开放及继续运行，再登记新命令/attempt与新域编码准备。禁止通过修改cn_live_command视图、移除守卫、复制旧准备或仅把绑定换成新出口来制造正例。下一步应把重新开放、新grant采用、普通新命令和准备核销串成同一验收链；旧域已有准备由完整退役集合覆盖，但不能代替当前域非空验收。

交付：[验收](check_domain_recovery_races.py)、[报告](domain-recovery-races-report.json)。使用同进程的两个独立SQLite文件连接，在DELETE/WAL两模式下控制提交交错，并重新连接确认已提交失效及历史保存。未执行真实进程终止、断电、文件系统故障、多进程竞争、线路或设备动作；不得把重新连接等同崩溃恢复验证。

本轮实际51项检查通过，使用266表组合。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_domain_recovery_races.py --report`。报告显式保留nonempty_current_domain_preparation_verified=false、process_crash_verified=false、full_reopen_verified=false；当前检查通过不能关闭这些剩余事项。
