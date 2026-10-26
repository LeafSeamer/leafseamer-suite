# 固定Node候选制品的取消写集持久性

状态：DF04／DF05设计验证补充，approved=false；不改变已批准契约，不是业务服务实现或生产发行批准。

已知事实：候选组合为Node24.22.0／better-sqlite3 13.0.3，已在[工具链设计](../../rebirth-toolchain-lock-design.md)登记。本轮使用官方下载物做隔离加载，实际查询SQLite version／source_id／compile_options和每连接PRAGMA，不采用网页值补齐。固定平台入口`lib/win32-x64.js`直接加载包内`prebuilds/win32-x64.node`，不走缺预编译文件时的构建目录回退。（来源：[官方包定义](https://raw.githubusercontent.com/WiseLibs/better-sqlite3/v13.0.3/package.json)、本次下载包源码与[验收器](check_node_sqlite_durability.py)。）

制品核对分层：Node压缩包SHA-256比对[官方清单](https://nodejs.org/dist/v24.22.0/SHASUMS256.txt)，npm tarball SHA-512比对[此前登记元数据](../toolchain/metadata-observation.json)；执行前逐字节核对已解包node.exe、驱动lib全部文件、package.json和win32-x64.node与归档原件。报告保留归档／原生文件摘要、版本、实际引擎和编译配置。下载物及原响应仅留本地忽略目录，不提交到成果仓库；未执行npm安装脚本、隐式编译或全局升级。HTTPS来源与摘要一致不等于完成签名、构建来源和动态依赖闭包审查，报告明确未验证密码签名。

实际测试范围：从[跨域取消参考模型](retired_cancel_model.py)生成合法seed及八条完整参数化INSERT写集，由[Node验收桥](node_sqlite_worker.cjs)在专用worker_thread中执行BEGIN IMMEDIATE、全部写入和COMMIT。参数显式保留BLOB与整数；全表读回的整数以十进制字符串标记，避免JS Number损失精度。Python负责测试进程握手和终止，每个Node进程只有一个持有数据库连接的存储线程。仅接受带专用标记的临时case.sqlite，始终保留FULL、外键和递归触发器。

| 切点与配置 | 必须验证的结果 |
| --- | --- |
| DELETE与WAL各自after_member | 子进程确认事务内已写退役成员后仍存活，再真实终止；目标引擎重开后全表值等于写前 |
| DELETE与WAL各自after_seal | 最后seal已写但未提交；终止后全部写集回滚，不只比较关键行数量 |
| DELETE与WAL各自after_commit | 提交后屏障终止；目标引擎全表值等于参考模型完整提交后的值 |
| 每个首次重开 | 使用预先启动、已握手的独立检查存储线程，在确认writer进程退出后发送打开请求；不以新启动解释器的耗时作为等待策略 |
| 每个恢复来源 | 目标引擎先完成完整性、外键和逐表值检查并关闭；随后由Python参考模型核对同ID查原或重新提交，再重建276表恢复来源 |

首次重开失败必须在报告中保持失败；100ms后再次打开仍仅作完整性取证，不能覆盖失败，也未被批准为生产重试。桥的消息调度和线程调度仍有自然延迟；通过只证明该制品在本机本次六个时序中完成这些验收，不证明任意时间窗口都可重开，更不能由新引擎单次通过断言旧1224根因已修复。

验收桥只执行参考模型已经校验、生成的固定合法写集；未把完整鉴权、时钟、JCS、当前资格复核和命令状态机移植成Node可信writer。恢复来源重建由Python参考模型执行，不能冒充Node实现通过；测试进程及专用线程也不等于已冻结真实服务监督器。数据库布局用现有合成提供者生成，未操作直播设备。

基于事实的实施边界：独立存储线程、显式平台加载、全部写集单事务、每连接配置回读及BLOB／大整数保真可以作为后续实现要求。实际产品仍须把同一语义放入完整Node writer，并完成其并发、取消、COMMIT结果不明和真实监督恢复测试。Windows／Linux／容器分别验证，Argon2、时钟、更新签名、发行安装及动态依赖资格不得由本报告顺带放行。

复现：先在独立目录准备上述官方归档、SHASUMS256.txt及其原样解包文件，再执行`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_node_sqlite_durability.py --runtime <隔离制品目录> --report`。报告绑定当前检查器、桥、文档、全部参考来源和元数据；`--check-report`只核输入，不重跑或验证当前磁盘制品。未通过时保留报告并非零退出；报告为本次实测值，阶段0继续未关闭。
