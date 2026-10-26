# 跨域取消的并发与重开验收

状态：内部设计候选的验证补充，approved=false。仅使用独立临时数据库和本检查器启动的 Python 测试进程；不操作业务数据库、真实监督进程或直播设备。

已知事实：跨域取消切点与退役证明撤回分别由同库 BEGIN IMMEDIATE 事务写入。历史 read 可以保留已提交拒绝原件，live读取必须检查退役集合当前有效。只读快照不能替代最终 writer 的重新取证。（来源：[跨域模型](retired_cancel_model.py)、[监督撤回模型](supervisor_retirement_adoption_model.py)、[快照准入组合](command_snapshot_model.py)。）

本轮验证以 DELETE 与 WAL 两种日志模式、synchronous=FULL 为本机测试配置。两个独立连接使用零等待超时，使竞争顺序可重复：

| 时序 | 必须观察到的结果 |
| --- | --- |
| 取消writer先持锁，撤回writer尝试写入 | 撤回写入被排他；其他连接查无all只说明尚不可见，不证明取消已回滚 |
| 取消先提交，撤回随后提交 | 历史切点完整可读，live资格拒绝，不删除拒绝墓碑 |
| 撤回writer先持锁，取消writer尝试写入 | 取消不能在旧资格下写入；撤回提交后重试必须重新读取并拒绝 |
| WAL读事务先建立快照，再由另一连接撤回 | 旧读事务仍可能返回旧资格；升级写事务失败，结束旧事务后的新writer必须拒绝 |

实际终止验收使用父子进程握手，只有子进程确认达到指定屏障且仍存活时，父进程才终止自己创建的测试writer。屏障不自动超时放行，不根据日志文件猜测进度。每种日志模式分别覆盖：写入退役成员后、写完取消seal但尚未提交、SQLite提交成功但尚未向调用者返回。

前两个切点终止后应回滚全部未提交写集，完整逐表值与初始快照一致；同ID随后可以正常完成。第三个切点终止后必须保留全部已提交切点及拒绝水位，同ID仅查原，不追加撤销或重发。每次均重开数据库、检查完整性与外键，再执行276表恢复来源链；再次关闭重开后仍须重建相同非空命令拒绝快照。

首次打开必须无I/O错误才计入立即重开通过。本机探针已观察到 SQLite 3.50.4 的 WAL 首次重开报 SQLITE_IOERR_TRUNCATE；官方定义仅说明VFS调整文件大小失败，不能据此认定损坏原因或归因于某个进程。检查器记录实际错误码并关闭失败连接，稍后另开连接只作数据完整性取证，不把后续成功覆盖首次失败。存在该错误时 all_passed=false、immediate_reopen_verified=false，并保留失败用例，检查器以非零状态退出；--check-report只验证输入绑定，另行回显报告是否通过。生产自动恢复资格不得关闭。（来源：[SQLite官方错误码](https://www.sqlite.org/rescode.html#ioerr_truncate)、[本轮报告](retired-cancel-durability-report.json)。）

后续须在已冻结生产原生制品、实际Windows／Linux VFS与监督启动流程复验；先确认是否仍复现，再定位文件、共享内存和关闭顺序。不得为取得绿灯而删除日志／共享内存文件、放宽同步级别、无限重试或继续使用失败连接。这里没有采纳新的生产自动重试策略，也没有证明本机验证运行时等价于生产SQLite制品。

报告只记录实际观察到的本机 Python／SQLite 版本、日志模式、测试writer终止次数及输入摘要，不记录用户路径或进程标识。文件系统及SQLite正常工作时的进程终止，不等于断电、磁盘损坏、真实服务监督恢复或设备状态恢复；不据此证明生产制品可发布。Windows和Linux发行制品仍须分别验证，当前报告平台以实际结果为准。

验收入口：[检查器](check_retired_cancel_durability.py)；[结果与输入绑定](retired-cancel-durability-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_retired_cancel_durability.py --report`。既有[跨域来源契约](RETIRED_CANCEL.md)保持不变，最终OPEN/Ready、第三域采用、混合准备完整轨迹和真实授权／时间来源继续待完成。
