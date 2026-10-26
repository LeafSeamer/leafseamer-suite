# 命令拒绝水位与原提交的原子绑定

状态：内部候选，approved=false；仅设计SQL和离线参考模型，旧批准基线不变。

已知事实：cv_cancel_deny是永久普通命令拒绝墓碑；cv_cancel_commit完成受理，cc_cut_commit封存ordinary/all切点。原物理表没有独立命令快照水位，cut_revision指向签发水位，不能冒充deny_revision。（来源：[取消存储](../c02-command-view/storage.sql)、[切点存储](../c08-controller/cancel-closure.sql)、[当前IPC](continuation-binding-ipc.schema.json)。）

本候选用一张cd_event表接入原写集：原受理提交语句自动追加accepted事件；原ordinary/all切点提交语句自动追加相应事件。新增失败使原事务整体失败，不要求调用方另外记得写一次拒绝日志。每设备snapshot_revision从1严格递增；accepted即产生ordinary拒绝代次1，此时cut_pending=true；ordinary切点落库保持deny_revision=1但推进快照水位；all切点递增deny_revision到2，再推进快照水位。同一父命令只允许一次取消、每取消最多ordinary/all两阶段，所以此版本每命令的deny修订恰为1/2；未来增加阶段须修订契约，不能复用终态或签发计数。

同设备三个事件示例：accepted(snapshot=1, deny=1, cut=null) → ordinary(snapshot=2, deny=1, cut=ordinary原ID) → all(snapshot=3, deny=2, cut=all原ID)。两个命令独立维护deny修订，共享设备快照顺序。all必须指向同取消的ordinary切点。取消终态、关闭回执撤回和完成观察均不删除墓碑或降低水位；它们影响其他资格，不恢复普通发送能力。

安装在BEGIN IMMEDIATE内检查没有既存取消并创建扩展；不为旧历史猜造先后顺序，不提供产品迁移。外事务、关闭外键或递归触发器均拒绝安装。水位以20位十进制TEXT保存，两段十位整数运算避免转REAL或越过有符号64位；下一值超过20位则拒绝提交，进入保护并退出writer的运行时策略仍须接入。表记录不可改删，来源唯一，读取双向核对完整来源集合与连续事件序列。

materialize在同一SQLite事务中按指定历史水位生成来源索引，按parent_command_id排序，保留全部已受理命令。4096是当前IPC完整快照容量；超过时来源读取失败，不能截断，也不能因此拒绝记录新的保护请求。complete_cut_ids遇到任何cut_pending即拒绝，成功也仅返回待核验cut ID，不生成IPC DenySnapshot、不把旧占位BODY当成完整原件、不产生开放许可。

一致性边界：历史索引稳定，当前资格还要与最新设备水位相等；相同成员数量的ordinary/all推进同样使旧索引失效。WAL读事务只保证其快照内部一致，另一writer提交后旧读事务仍可能报告“当前”；最终OPEN/发送准入必须在新取得的写事务或已有唯一writer串行边界内重读，不能跨事务缓存本函数的current布尔值。

98项故障及边界验收覆盖实际119表取消布局叠加本表、原受理和两阶段切点逐写回滚、事件插入故障使源提交回滚、源重复、历史与同数量推进、取消终态墓碑、两设备独立水位、真实4096／4097容量、双连接DELETE/WAL提交可见性与writer争用、WAL旧读视图以及提交观察丢失前后查原。临时磁盘库重开验证持久保存，未模拟进程强杀、掉电或生产恢复。当前269表恢复链可加载本扩展，与运行快照扩展一起实际组合为272表；该组合仅空取消来源，不能作为非空重新开放完成的证明。旧两阶段关闭251项和运行快照44项相关回归通过。

剩余冻结事项：完整CancellationBinding、Cut/CutTarget与受理/目标/传输原件的逐字段核验，ordinary/all前序原件重建，以及完整DenySnapshot的封存、历史查原和OPEN前态引用仍须完成。源索引有cut_id不证明该cut正文完整或可信；下一步须拒绝旧占位原件，并给出实际非空正例。授权与时间来源、Ready/Scope采用和最终AdmissionSeal继续保留原阻断。

交付：[SQL](command_deny.sql)、[来源读取](command_deny_model.py)、[验收](check_command_deny.py)、[报告](command-deny-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_command_deny.py --report`。
