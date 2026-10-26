# 退役worker完整关闭集合

状态：内部候选，approved=false；不改变已确认公共基线。接续[退役采用](SUPERVISOR_RETIREMENT_ADOPTION.md)。

已知事实：原pd_close_completion及go_recovery_target强制绑定go_close_ack，原准备核销的committed_tick没有独立时钟域字段；监督退役的评价域可以不同于旧worker运行域。因此不能伪造旧ACK或将新域tick填入旧准备记录。（来源：[原关闭存储](../c08-controller/open-storage.sql)、[原准备存储](../c08-controller/prepare-deny-storage.sql)、[监督来源](../df02-supervisor/RETIREMENT_SOURCE.md)。）

本轮方案使用独立RetiredCloseSet：completion_id、revision、anchor_exit_id、worker_identity_digest、排序targets及completion_digest。每个target包含完整binding、首次runtime_binding_ref、retirement_adoption_ref、最新close_ref、cut_ref、prepare_head及全部preparations。每个准备项保存原authorization、撤回及编码帧的Ref，basis固定retired；不存在完成tick。完整原件已经在同一控制器库提交，BEGIN IMMEDIATE内核对并封存的数据库先后关系构成此处的因果依据，不比较监督域和旧worker域的数值时间。

集合范围为同一库中worker_boot_id、clock_domain_id、descriptor_digest相等的全部出口，跨controller boot、IPC和设备会话仍必须覆盖。各出口完整source、launch intent及AdmissionReceipt必须逐字一致，否则按启动身份冲突拒绝；绝不因同boot字符串而拼接不同来源。上限256个出口、全集合4096个准备及16MiB规范正文，超限整笔拒绝。每个出口必须已被保护、已采用当前有效退役原件、具有最新关闭记录与已封存cut，且cut覆盖此出口全部历史准备，不因准备已释放或从未发送而漏项。

一项已封存退役采用即对相同worker运行身份永久禁止新出口、新IPC会话、新准备和所有会话的ij_write_attempt。证明撤回不会删除此墓碑。它不能撤回此前已经进入I/O的字节，不得将未知命令改为未发送；真实进程与句柄终止仍由监督提供者保证。

写集为rcs_completion、每个rcs_target、rcs_commit，延迟外键要求完整seal。SQL核对目标正文、精确准备集合与原撤回/帧引用；读取器进一步校验Schema、摘要、完整启动身份及全部原件。相同completion_id只查原，不能更换anchor或刷新已失效记录。任一出口退役证明撤回，或出现更新关闭记录，整个集合的rcs_current和retired_close_usable立即失效；历史正文保持可查。当前资格不依赖后续设备仍为protected，避免合法恢复使自身依据失效。

故障时序：

1. 两出口只有一个采用完成：停止同worker所有会话发送，但完整关闭集合不成立。
2. 全部采用后封存集合：逐写异常或遗漏成员整笔回滚；提交观察丢失按completion_id查原，不能重复执行设备动作。
3. 完成后一个证明撤回：整集合不可用于恢复，旧worker仍永久禁写；新ID不能绕过撤回。
4. 新运行域观察值3、旧关闭值200：可以完成数据库核销，不产生跨域时间大小比较。

本轮离线交付：[Schema](retired-close-set.schema.json)、[SQL](retired-close-set.sql)、[参考模型](retired_close_set_model.py)、[验收检查器](check_retired_close_set.py)、[报告](retired-close-set-report.json)。70项检查通过；双出口夹具同时覆盖非空和空准备集合，两个真实SQLite文件连接验证撤回先占writer锁、完成被拒、重试重读失效资格的顺序。未执行真实IPC、操作系统提供者或设备测试。既有业务文件不修改。

下一步必须把恢复目标显式改为worker_ack或supervisor_retired二选一，统一校验各设备完整最新关闭集合，并将任一证明失效传播到恢复seal、后继准入和保护计划。此处只提供独立关闭完成证据，尚未替换go_recovery_target、放宽旧ACK会话要求或签发发送许可；不将独立资格通过等同于恢复完成。原准备核销路径保留，待统一消费时归并，不生成并行的假ACK。真实准入认证、来源连接、容量物理预算、完整T5/T2和P0仍需后续完成。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_retired_close_set.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_retired_close_set.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_retired_close_set.py --check-report
```
