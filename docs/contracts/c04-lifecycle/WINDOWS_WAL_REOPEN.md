# Windows WAL 重开错误的原生证据

状态：DF04／DF05设计验证补充，approved=false；未改业务服务、设备协议或已批准的draft.4／IPC0.3。

已知事实：本机Python3.14.0／SQLite3.50.4在独立测试writer终止后的WAL首次重开可返回1546（SQLITE_IOERR_TRUNCATE）。[既有报告](retired-cancel-durability-report.json)保留当时73通过、2失败的结果；本次独立[原生诊断报告](windows-wal-reopen-report.json)记录自己的实际结果，不覆盖既有失败。两者均由[完整取消持久性验收](check_retired_cancel_durability.py)运行276表恢复链，未用单表样例代替业务契约组合。

新增[验收器](check_windows_wal_reopen.py)在父测试进程的SQLite公开VFS v3接口中包装SetEndOfFile，实际调用原函数一次，原样返回结果并保存／恢复线程错误码；仅失败后读取文件角色与当前文件位置，finally恢复原函数指针。不向子进程注入诊断，不更换引擎、不修改映射、不删除WAL或SHM。包装可能改变时序，因此报告只证明此次被观察的错误，不能当作生产性能或无干预时序证明。（来源：[SQLite VFS公开接口](https://www.sqlite.org/c3ref/vfs.html)、[Microsoft SetEndOfFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setendoffile)。）

本次已观察到的失败是共享内存文件角色shm、requested_size=0、Windows错误1224。1224的官方名称为ERROR_USER_MAPPED_FILE，表示存在用户映射节而不能完成请求；SetEndOfFile使用当前文件位置作为新文件大小，映射存在时有关闭映射的要求。这里不能把主数据库mmap_size=0等同于WAL共享内存没有映射。（来源：[本次报告](windows-wal-reopen-report.json)、[Microsoft错误码](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--1000-1299-)、[SQLite WAL索引](https://www.sqlite.org/wal.html#implementation_of_shared_memory_for_the_wal_index)。）

基于事实的分析：该证据把失败对象收敛到SHM截断，尚未识别映射所有者、生命周期或根本原因；不能归因为特定安全软件、主数据库损坏或某个产品引擎缺陷。SQLite3.50.4公开实现的winLockSharedMemory在取得DMS排他锁后尝试将SHM截零，winHandleTruncate直接传播失败；这与观察相容，但没有调用栈证据，不能将相容性当作已证实的完整调用链。（来源：[对应版本公开实现](https://raw.githubusercontent.com/sqlite/sqlite/version-3.50.4/src/os_win.c)。）

诊断报告仅输出允许的测试case、打开序号、database／wal／shm角色、请求大小和数值错误；不保存真实路径、PID、句柄或本机错误消息。打开序号1是建库，序号2是终止后的首次重开；一次打开的失败处理／关闭可能重复产生原生事件，因此事件数不等于失败用例数。检查器核对DLL与Python查询到的source_id和版本，记录DLL摘要；这绑定本机诊断产物，不等于验证候选better-sqlite3发布产物。诊断函数指针必须恢复，回调异常或接口不支持直接失败，不把未知角色解释成SHM。

| 放行事项 | 验收与不通过时行为 |
| --- | --- |
| 原生错误定位 | 每个首次失败保留阶段与SQLite错误；原生事件按打开序号关联，未知文件角色或没有事件不能推定1224 |
| 数据完整性 | 仍跑DELETE／WAL、FULL、6次真实测试writer终止、未提交全库回滚、已提交拒绝切点保留及276表来源重建；稍后重开仅取证，首次失败保持失败 |
| 固定生产制品 | 在候选Node／better-sqlite3精确版本和制品摘要上独立复验；记录实际SQLite source_id、编译配置、VFS和驱动，不将Python版本升级当作产品已修复 |
| Windows监督生命周期 | 用拟发布的真实监督与存储线程流程验证退出、连接关闭、重开；证明旧写域已退役与证明SHM可重开是两个门槛，不能相互代替 |
| Linux与故障恢复 | 单独测试目标Linux发行制品、进程终止、COMMIT观察丢失及故障存储；不能由Windows结果推定 |

推荐保持既有关闭策略：首次重开I/O错误时自动化门保持关闭、状态为恢复待处置，不签发OPEN／Ready或重放设备命令。没有新增生产自动重试策略，不以等待100ms、删除SHM/WAL、降低FULL或替换返回值作为修复；既有100ms后重开仍只供完整性取证。下一步先完成固定生产运行时的同类复验，再决定是否需要调整监督清理流程或驱动选择；涉及已批准恢复语义的变化须单独审阅。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_windows_wal_reopen.py --report`。运行失败仍写实际报告并非零退出；`--check-report`仅核输入绑定。当前没有真实服务崩溃、断电、直播设备或生产制品放行证据，阶段0继续未关闭。
