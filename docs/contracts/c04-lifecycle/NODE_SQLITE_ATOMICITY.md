# 固定驱动的原子失败与进程竞争

状态：DF04／DF05候选验收补充，approved=false。沿用[制品及线程边界](NODE_SQLITE_DURABILITY.md)，不修改业务服务或已批准基线；验收桥不是产品可信writer。

已知依据：[跨域取消模型](retired_cancel_model.py)在同库事务中生成八条完整参数化写入，包含两份出口目标、准备成员、跨域退役证明和两处seal。[新增检查器](check_node_sqlite_atomicity.py)把相同真实写集交给固定Node24.22.0／better-sqlite3 13.0.3，每个测试进程内仅一个存储线程；不使用内存锁模拟数据库竞争。报告保留每项实际错误码、制品身份、输入和写集摘要。

官方事实：SQLite的独立连接通过事务隔离未提交写入；WAL旧读事务在其他连接提交后升级为writer可以得到SQLITE_BUSY_SNAPSHOT，必须结束旧快照后另起事务。事务发生错误时也不保证整笔事务自动回滚，应检查实际事务状态。（来源：[SQLite隔离](https://www.sqlite.org/isolation.html)、[事务错误处理](https://www.sqlite.org/lang_transaction.html#response_to_errors_within_a_transaction)。）本次实际结果记录于[验收报告](node-sqlite-atomicity-report.json)，不以文档描述替代运行。

| 验收分支 | 期待结果及比较范围 |
| --- | --- |
| DELETE／WAL逐条写入后主动异常，共16个位置 | 返回测试异常、明确结束未决事务，另一进程重开后272张表逐值等于写前，无部分写集 |
| DELETE／WAL各漏掉一条写入，共16个位置 | 真实约束拒绝执行或提交，不能以通用测试异常冒充约束命中；回滚后全表不变 |
| COMMIT返回成功，随后测试响应生成失败 | 回传错误但inTransaction已false，不伪造rollback；另一进程观察到全部已提交内容，盲重放原INSERT受约束拒绝且不改原件 |
| 第一进程持有BEGIN IMMEDIATE，第二进程尝试写入 | 第二writer真实获得SQLITE_BUSY；读连接只见旧已提交值。第一连接关闭回滚后，第二进程用新事务完成完整写集 |
| WAL读快照建立后另一进程提交，再升级旧快照 | 获得SQLITE_BUSY_SNAPSHOT，回滚旧读事务；新事务读到完整新原件，不把旧快照资格当作当前writer资格 |

主动异常与真实SQLite提交I/O错误不同：这里的提交回执丢失在实际COMMIT成功之后注入，只验证不能将调用层错误一律解释成回滚。未注入磁盘满、写入／同步错误、断电或驱动提交结果未知；这些仍需固定VFS故障测试。测试桥可显式回滚仍处于事务中的测试连接，但产品处理未知结果必须按原operation查原、保持自动化门关闭，不能复制本测试的盲重放反例作为重试方案。

基于事实的实施要求：写入异常先确认事务状态并结束旧事务，禁止把旧快照延续成新写入资格；重新开始时必须重新核对授权、时钟、完整来源及拒绝水位。SQL约束和串行化只证明存储层范围，不能替代完整Node语义检查器；独立进程竞争也不证明真实服务监督器、全部P0容量或自动化恢复正确。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_node_sqlite_atomicity.py --runtime <隔离制品目录> --report`。同目录制品与校验要求沿用已有检查器，原归档／原生文件不进入成果提交。失败保留实测报告并非零退出；`--check-report`只校验输入绑定。共用验收桥变动后须实际重跑既有六个进程终止切点，并重新绑定其报告。旧Python／SQLite3.50.4的1224负面证据不受本次结果覆盖，阶段0及生产放行继续未关闭。
