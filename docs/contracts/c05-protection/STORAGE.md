# P1 来源保护持久化候选

状态：离线设计候选，`approved=false`。对应[C05来源保护](README.md)与[DF04存储设计](../../rebirth-df04-storage-design.md)，不改变已批准的draft.4／IPC0.3，不是生产迁移或业务服务。所有实验只用内存SQLite。

[build_storage.py](build_storage.py)原样组合C04恢复、执行、C05摄取和两类P4接收布局，再追加[storage.sql](storage.sql)，生成[63表布局](seamer-protection.sql)。旧接收器独立实验仍可导入计划；新组合的sp／po计划必须反向引用同库P1，不能孤立提交。对旧合法历史追加布局仅是测试装配，不是产品升级方案。

## 固定集合与字段

| 记录 | 必需字段及约束 |
| --- | --- |
| p1_dependency | 连续内部sequence、source/run、owner_kind及原run/execution/recovery引用、发布artifact摘要。一个来源的全部登记并集决定保护run，不取当前事件匹配集 |
| p1_preparation | 连续sequence、run/generation、Controller完整scope、preparation_id、mode/execution、request摘要、binding/request/outbox/audit正文。先持久登记后发送；响应未知不得删记录。arm登记仅允许armed；恢复登记要求run仍paused且dispatch关闭，原操作preparing、同执行prepared、原目标pending，不能在启动后补造 |
| p1_fault／p1_plan | 检测域与序号唯一、fault正文、来源前后修订/状态、原sequence/floor、两登记水位、全部成员数量、固定plan正文及摘要。fault、plan、commit双向约束，精确重复只查原，相同检测身份换正文拒绝 |
| p1_run／dependency_member／execution_pin | 精确run前态、generation、暂停后修订及独立latch；全部来源依赖与选中run的所有历史执行固定。旧unknown仍保留，completed不复活、不增加修订 |
| p1_controller／preparation_member／submission_member | 按run及Controller完整scope去重，将所有准备和历史提交求并集。planned、响应未知以及旧代次都不能省略；每成员必须指向同run/scope目标 |
| p1_commit | 来源变更、完整成员、暂停锁存、两类接收计划、审计和通知全部具备后才能封存；成员封存后不能补写，原记录不可更新/删除 |

scope始终包含authority与database。正文中的绑定关键字段与规范列逐项核对；同数替换不是集合相等。完整JCS、摘要真实性、发布工件的依赖语义及旧恢复Controller标识到scope的映射仍由可信提供者验证，SQL不能凭自洽正文证明它们。

## 原子写集与故障时序

1. `BEGIN IMMEDIATE`后查重复fault，并读取来源前态、登记水位、完整依赖/run/执行/准备/提交。
2. 写fault、plan及全部成员，固定每个Controller操作身份与内部拒绝操作outbox。两种接收计划都取同一P1成员。
3. 来源转desynchronized；已quarantined不得降级，closed不再执行UPDATE。保留contiguous_sequence与reject_floor，不推测丢失事件、不重新解释旧摄取决定。
4. 非completed run精确增加一次修订，暂停且关闭dispatch；各run增加独立source_fault锁存。completed保持原终态，但旧准备/提交仍保护。
5. 封存sp、可选po计划，最后写p1_commit及审计/通知，COMMIT确认后才允许异步发送。接收或发送期间不持有写事务。

来源/run修订最大为20位十进制字符串；SQL按两个10位段计算精确后继，不经浮点。达到最大值后拒绝本次新保护事务，进入容量/身份耗尽的运行处置仍待服务提供者落实。内部登记sequence采用有配置总数上限的SQLite INTEGER，不是对外U20。

每次新增fault重新固定完整目标并追加锁存。各已封存plan取代次最大值形成拒绝下界；旧generation的step_ready、command_submission、submission_attempt及execution_start不能再写入，新准备也不能登记。准备中发生fault后，迟到回执可保留，但原R4不能越过新锁存或直接重用被拒代次。已有提交与执行终态不改写，保护完成不表示资源clear，也不授予恢复权限。

`p1_pending_dispatch`只是“尚未观察到applied或已观察失效”的重查目标。P4单条applied不证明通知流持续健康；旧成功迟到不能覆盖更高失效修订。HTTP sp同键矛盾目前拒绝但未持久隔离，准备po沿用首冲突持久隔离。二者不能被描述成相同完成度。

## 验证方法及剩余边界

[check_storage.py](check_storage.py)直接运行[参考写集](storage_model.py)与SQLite触发器，保留旧恢复和提交约束；缺写、写后异常、身份/水位错配、集合替换、超限均比较完整数据库快照。179项检查结果见[报告](storage-report.json)。正例覆盖同Controller多个run、completed旧准备、旧unknown执行、响应未知提交、空匹配集与零依赖计划、20位末值及P4乱序。恢复夹具先执行原R2，再登记准备，之后才执行原R3/R4；另测准备途中故障和迟到回执，未卸载守卫。P4消息为显式合成原件，仅证明绑定与接收联接，不替代此前Controller原件导出实验。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/build_storage.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_storage.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_storage.py --check-report
```

本轮缩小的是P1持久集合与P4计划来源缺口，尚未关闭以下门槛：

- 依赖编译器、正常启动/恢复准备的真实登记提供者与权威撤回；原R2和新增准备登记还未封成同一个双向强制提交。P1遇到未登记的旧R2目标会拒绝，而非忽略；正式实现须消除这段不完整窗口，并规定登记失败时的本地闭锁。不得借本测试前态宣称产品已能安全启动。
- P0完整预留、所有登记正文/元数据/回执的容量、WAL与物理磁盘及执行时限。当前只限制记录数、每计划run/Controller数和选定正文之和；不是全服务容量证明。
- source baseline／resolution、新代次恢复R4、timer/edge、AUTH/TIME及完整AdmissionSeal/Guard/预算/时间同版联接。
- 完整HTTP请求和认证、消息输送、流健康/游标、GUI/API消费者、唯一SDK源与跨服务撤回传播窗口。
- 实际进程并发、磁盘崩溃恢复、NTP、平台、网络及设备测试；本报告均记为0，阶段0仍开放。
