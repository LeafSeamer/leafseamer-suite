# 最终封存物理关系与提交查原候选

状态：`approved=false`。在[封存字段](FINAL_ADMISSION_SEAL.md)和[238表库存布局](ATTEMPT_INVENTORY.md)基础上增加4表，生成[242表候选](controller-final-admission.sql)。[参考适配器](final_admission_storage_model.py)提供封存写集及提交观察，[检查器](check_final_admission_storage.py)执行布局初始化、观察事务和SQLite实际锁竞争。业务服务未改。

## 已知事实与设计范围

当前全局`ci_issue`已经将普通/取消许可分支双向配对，但没有反向要求AdmissionSeal。四个`cu_*_gate`临时守卫仍拒绝最终签发；目前的完整记录夹具仅走受理、prepared和观察修订，没有建立完整开放闸、编码响应、hold/预算及最终发送链。（来源：[原组合](controller-attempt-inventory.sql)、[库存检查](check_attempt_inventory.py)、[控制屏障构建器](../c08-controller/build_control_fence.py)。）

基于上述事实，本轮明确新增持久约束和提交结果查原，不将观察表当成替代许可账本。四个临时守卫逐字保留。报告的`sql_positive_issue_path_executed=false`表示正常最终签发写集仍未跑通；初始化、拒绝不完整数据和查原测试通过不取消这一限制。

## 四表与双向闭合

| 表 | 身份与关系 | 写入时点 |
| --- | --- | --- |
| fa_seal | transaction_id主键，seal_id及permit_id各自唯一；完整(permit_id,issued_revision,kind)绑定ci_issue；关联命令前态、出口、hold、Ownership和资源前后快照 | T2内；seal_body保存完整规范正文，计数列为20位补零字符串，不转浮点 |
| fa_input | (seal_id,role)主键，投影身份在同seal中唯一；保存完整投影及原source_ref，列与正文逐项一致 | 同T2；普通18项、取消21项，禁止提交后增补 |
| fa_commit | seal_id主键，permit_id/outbox_id唯一，审计与发送候选outbox同存 | T2末尾；核完整输入集合、预算包络、领域提交及物理归属 |
| fa_observation | observation_id主键；保存完整candidate与CommitObservation，三种结果均不可改写 | T2结果判定之后独立短事务；不能在T2里制造“已经提交”的证明 |

生成器只对`ci_issue`增加指向`fa_seal`的三列延迟外键。Seal又反向引用`ci_issue`、对应普通/取消传输commit及`fa_commit`，所有新issue在COMMIT时必须闭合；没有一个“先提交许可，稍后补Seal”的窗口。首次普通hold/Ownership、后态快照、预算、Guard和公开命令修订继续属于同一T2领域写集，不能由此适配器另开事务分段保存。

fa_commit核普通/取消的实际permit、command/attempt或cancellation/execution、出口、hold与两份资源快照对应同一设备；同组完整输入的角色数量与双向集合一致。身体字段的Schema/JCS、当前资格、来源真实性及完整语义仍须可信writer验证。SQL的物理ID关系不替代所有source_ref的完整摘要对账，也不替代最后一刻的提供者复核。完整领域writer和逐角色投影器尚未接通，不能仅凭新增表存在宣布最终准入完成。

候选限制seal正文1MiB、每份投影16MiB、整组投影合计16MiB；这些是拒绝畸形/无限增长的参考包络，正式CostManifest、WAL开销预留和GC仍须归并。超限整笔拒绝，不能丢掉角色。四表禁止UPDATE、DELETE及REPLACE覆盖；GC须在后续版本用保留完整负面事实的方案设计，不能直接删墓碑恢复旧身份。

## 写集顺序

`planned()`先调用跨原件检查，只返回fa_seal及18/21条fa_input写入；它既不自行BEGIN，也不签发或执行I/O。唯一writer须在同一个BEGIN IMMEDIATE内读取实际原件及当前cut，运行所有准入判定，插入必要领域记录、上述封存行、领域传输commit、公开修订和`finish()`产生的fa_commit，最后COMMIT。领域行可按延迟FK调整无环次序，语义不能因排序改变。

Seal关联的命令前态和前态资源快照必须事先存在；首次hold、Ownership及后态资源快照允许在同事务完成。fa_commit不能缺对应普通或取消领域commit。读取上下文变化、插入异常、最后检查失败或明确COMMIT失败必须全量回滚。此接口只表达附属写集，尚无通过四个最终守卫的完整正向writer；不能把合成上下文加一个标志便替换守卫。

## 提交未知、查询与永久不重签

提交观察不能强制FK到fa_seal：事务回滚时本来就没有Seal，未知结果也不能事先假定存在。相反，`observe()`先严格校验候选和本库scope，再取得BEGIN IMMEDIATE的writer顺序，查询transaction_id、seal_id和permit_id任一身份：

1. 存在完整精确Seal、fa_commit、全局issue和正确领域commit：仅可记录committed，并返回原观察。该结果仍要求当前资格重核，不能授重新投递旧许可的权利。
2. 存在冲突或半边记录：作为损坏/身份冲突拒绝，不转换成rolled_back。
3. 查无Seal且无issue：在**同一事务**写rolled_back观察，并以transaction_id/seal_id/permit_id三种身份作永久不重签墓碑。本结果表示该逻辑候选没有持久许可且今后不能补签；不声称设备调用曾发生或某条历史COMMIT语句确实运行过。
4. 调用方仅保留未知事实时可以记录unknown。unknown也不授权重签；后续采用新observation_id查原，原unknown不变。同一observation_id重试只返回同候选、同observer的原结果，不刷新时间、不把unknown原地改成committed。

任何已观察的身份都不能新插fa_seal。查无后做墓碑与旧writer随后补交的竞争由SQLite写锁排序：旧writer还持有锁时，观察者得到busy，必须保持不确定；不能先用只读快照查无，然后在另一个事务写rolled_back。观察者先持锁并完成墓碑后，旧writer即使才开始执行，最终插Seal也会失败，全部领域写入随事务回滚。墓碑不阻止读取已经存在的精确历史提交。

存储不可访问、BEGIN失败、读取失败、COMMIT结果无法可靠确认时抛出异常，由外层锁存存储故障并隔离候选；不得返回一个推测的rolled_back。观察没有当前用户授权接口，observer必须来自本地唯一writer/恢复器，不能由HTTP参数或worker报告选择。真实恢复器的身份、进程活性与故障关闭仍须运行层实现。

## 已验证与未验证

43项检查通过。检查使用完整242表内存库受理真实类型化命令，并在同一布局保存提交观察；另将该库备份到临时磁盘SQLite，在WAL模式用两个独立连接验证BEGIN IMMEDIATE锁冲突，确认busy期间不记回滚、锁释放后可查原。临时文件只用于本次测试，结束后清理。

覆盖观察写后异常回滚、重复请求零写、观察者/候选冲突、unknown后新查原、三身份墓碑阻止后补签发、无原件不得自报committed、UPDATE/DELETE/REPLACE拒绝、跨库/时间错配、四临时守卫正文保持和全局issue反向FK。实际最终issue数量仍为0，这一点作为断言保留。

未运行完整普通/取消许可正向SQL写集、最后一次撤权与签发竞争、进程强杀/断电、真实磁盘WAL恢复、服务/worker/设备I/O。两个连接的锁实验不代表跨进程崩溃验收。下一项必须连接实际提供者、真实完整领域writer及SEND_REPORT库存链，再按完整正反故障时序决定如何替换临时守卫；阶段0保持未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_final_admission_storage.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_admission_storage.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_admission_storage.py --check-report
```
