# 开放所需运行拒绝快照的持久来源

状态：内部候选，approved=false；设计与离线验证，不改变旧批准基线。

已知事实：运行拒绝账本已有全局snapshot_revision、每个来源/run的deny_revision、严格递增generation和已提交视图。命令取消账本cv_cancel_deny只有command_id与cancellation_id，cc_cut的物理列也没有独立deny_revision；当前IPC要求命令快照包含该修订与完整cut_ref。（来源：[运行账本](../c08-controller/common.sql)、[取消布局](../c08-controller/cancel-closure.sql)、[当前IPC](continuation-binding-ipc.schema.json)。）

本轮完成运行快照：按已提交全局水位读取每个(origin authority, origin database, run)的最大generation，以该三元组的二进制字典序输出完整集合；二十位整数转换为规范十进制字符串，全程不经浮点。空账本是revision=0的空集合。Schema及JCS摘要使用当前IPC定义，非法历史标识不能靠转换悄悄通过。

新增rs_snapshot与rs_commit两表，capture在BEGIN IMMEDIATE内读取原账本并双向封存。入口与最后seal都核当前水位和成员数量；同事务中途推进账本使本次捕获回滚。原件不可改删；重复snapshot_id只查旧原件，返回是否仍为当前，不刷新旧水位。读取按原水位重建历史完整正文，即使同数量且重算摘要的替换也不能成为可信来源。SQL计数和外键不替代正文验证；任意绕过适配器写入的正文须在读取时重新核对。

读取边界为同一SQLite事务。for_open从恢复资源原件取得run_snapshot_id，读取原快照并核当前水位及controller_scope；新拒绝即使不增加成员数量也使旧开放来源失效。旧原件仍可审计，不回放旧权限。两表复用既有账本，在健康恢复链中组合为271表；本模块不创建OpenProposal、OPEN_GATE或最终许可。

容量使用IPC既有4096成员上限与16MiB原件存储上限，超过即拒绝；完整IPC帧还有独立字节预算，运行快照单独合格不证明组合帧可发送。来源请求、外部授权、启动与时间提供者仍为合成，未证明生产真实性。

44项局部检查通过，包括4096完整捕获和4097拒绝、同数量新floor失效、重算摘要错成员、逐写／缺写／提交观察故障与历史查原。既有来源66项及共库布局262项实际回归通过。集成正例在最初preflight登记前选用当前Schema接受的数据库身份，并按组合布局同时写入来源的签发cut与准备cut；旧含点号的非法scope另有拒绝例，不转换已经持久化的身份或放宽Schema。

命令快照的下一步方案：为每设备建立不可回退的快照水位，将已受理取消和ordinary→all阶段推进纳入同库序列；逐命令deny_revision与完整cut原件绑定。已受理但没有完整cut的取消必须使OPEN来源不完备，不能被过滤成空集合。all阶段保留ordinary前序，不以回执撤回或取消终态删除拒绝墓碑。此为待落实的候选方案，当前没有该账本或命令快照提供者；也不能用记录数量或issued_revision冒充deny_revision。后续须与取消受理／cut的真实写集和同版Schema一起验证。

交付：[SQL](run_snapshot.sql)、[来源模型](run_snapshot_model.py)、[验收](check_run_snapshot.py)、[报告](run-snapshot-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_run_snapshot.py --report`。验收区分运行快照持久化、开放前态接线与尚未执行的命令快照、授权、参考时间、完整OPEN及真实设备验证。
