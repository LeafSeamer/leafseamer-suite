# 继续运行转交的两侧持久化候选

状态：`approved=false`。承接[转交契约](CONTINUATION.md)，本轮[组合器](build_continuation_storage.py)分别在既有完整109表Seamer和230表Controller布局上追加8表、5表，得到117表与235表。提供[Seamer增量SQL](continuation-seamer.sql)、[Controller增量SQL](continuation-controller.sql)、[参考writer](continuation_storage_model.py)、[离线检查](check_continuation_storage.py)和[报告](continuation-storage-report.json)。组合器直接调用原生成器，不维护另一份复制的完整SQL；报告绑定全部实际输入。旧生成产物及公共协议不变。

## 已验证事实

检查在三个独立内存SQLite连接中执行：一个Seamer、两个Controller。来源故障保护→baseline/delta/ready→新代R2/R4→恢复步骤完成→请求登记→两Controller签发→完整采用→R5已经走通。R5保存具体采用摘要并释放恢复锁；原Controller准备/grant字节不变。原prepare close经现有RUN_FENCE、准备cut及最后seal写入，关闭前后均不能产生可用转交。真实ct_state修订改变后cr_current失效。（证据：[检查器](check_continuation_storage.py)、[输入绑定报告](continuation-storage-report.json)）

**普通trigger完成链仍未交付。** 本轮保留`rs_plan_preparation`和`flow_submission_target`对recovery execution的限制，新trigger明确在完整计划seal处被拒绝。这样不能被描述成完整直播恢复成功；下一轮必须把独立继续运行grant及采用引用接入新执行、提交和Controller命令，并补成功正例。

## 本地原子写集

| 域 | 新表 | 事务作用 |
| --- | --- | --- |
| Controller | cr_limit、cr_issue、cr_device、cr_commit、cr_revocation | issue保存请求/目标、独立grant和Receipt；全部设备绑定实际ct_state；最后commit封存审计/通知；反向延迟FK禁止缺seal提交 |
| Seamer请求 | rc_limit、rc_request、rc_target、rc_request_commit | 同run/generation唯一请求，全部目标引用原p1_preparation；数量须同时等于Request目标集及本代完整准备集；最后seal重核恢复运行及资格 |
| Seamer观测 | rc_receipt | 单行保存来自已封存Controller原件的回执与审计；一行INSERT即为此步原子单元，省略该行不会留下半份观测 |
| Seamer采用 | rc_adoption、rc_adoption_commit | 完整回执集、run/slot/operation三项CAS、release原件和最后seal；采用不修改run或释放锁 |
| R5关联 | rc_r5_link | 与原transition_commit、execution/run/operation终态、release证据、恢复锁释放、flow_commit_seal同事务；缺关联或release正文不一致则整笔失败 |

所有新增历史表禁止更新/删除。SQL验证作用域、准备模式、原execution、代次、完整设备集合、控制原件修订、当前applied/close/RUN_DENY及各seal的精确关系；writer还负责完整Schema、JCS摘要、真实授权/时间/资源提供者。两者分工不意味着可绕过writer直接接收任意SQL正文。

Controller的`cr_current`只投影已封存且当前未关闭、未被RUN_DENY覆盖、未撤回、所有设备仍指向原ct_current_state并处于自动控制且无pending操作的资格。原close和控制修订不需覆写Receipt就能使该视图失效。`cr_revocation`为每份转交保留唯一不可变撤回原件；它的写入只收紧资格，不能重签或退款。真实身份提供者向撤回事实的认证适配、通知Seamer并形成共享PQ保护扣账，仍需下一轮接线。

Seamer的`rc_recovery_current`还要求恢复锁持有、run/generation/活动execution一致、operation处于running或reconciling、步骤已完成且成功、没有未清latch、来源同步、未被本地DENY覆盖、目标仍observed_applied。关系模型和SQL均不会把来源变绿解释为运行恢复完成。

本轮成功路径的步骤集合为reconcile_commit；state_machine的writer保留原业务状态CAS写集，但尚无专门成功用例，不声明该分支已验。必需步骤失败及可选失败继续的判定仍由已有执行契约负责，本候选不增加新的失败继续规则。

## 查原、迟到和跨库失效

`register/issue/adopt/finish`提供当前读取权限下的同原件查原路径，已提交结果不因写权限变化重新执行。相同身份异正文拒绝；签发响应丢失只读原Receipt；R5响应丢失只读已封存R5，不再次执行恢复步骤。

`receive`直接核对可信Controller连接中已封存请求/目标/回执原件及scope，不要求历史回执仍active。因此撤权后迟到的真实回执可以补入历史，但不会创建Adoption或R5。采用与R5分别重新读取当前Controller资格和外部前提；历史存在不代表当前资格有效。

本候选没有分布式事务。Controller已签发后Seamer失败，不回滚或删除Controller历史；任一目标失败时Seamer不采用完整集合。Controller在远端核验之后发生变化仍有竞态，最终设备出口必须自行重核当前控制/授权及关闭；本轮未连接该出口，也不能用三个串行内存连接冒充并发证明。

## 容量与保护库存

cr_limit与rc_limit是不可变普通存储逻辑上限，分别约束签发总数和转交总数；已有历史占位不退款。每Controller准备最多签发一次，每Seamer run/generation最多转交一次。正文继续使用请求262144字节、Receipt/Adoption各16384字节及完整目标上限；审计/通知分别限制1024字节。撤回每份已签发资格最多一条，不争夺新的签发名额。

这些约束只证明有界数量及单行部分字节上限，**不证明完整CostManifest、物理空间预留或新增对象已经纳入全部保护成本**。本轮不新增设备命令、不产生DispatchIntent、不放开普通trigger；原准备沿原close链关闭已经验证。后续启用新grant命令前，必须把新执行/命令归属、撤回通知、共享PQ关闭及预算扣账一起接入；不得使用会漏新预算的旧withdraw入口。总容量/GC仍是阶段0未闭项。

## 实际验证与未验范围

检查覆盖请求、签发、采用和R5的每个写项省略及每个写后异常，回滚后比较全库快照；单行回执观测另外检查省略无副作用。还覆盖原准备不变、两侧查询幂等、采用三项CAS、重算摘要后的错绑、SQL列错配、撤权后历史查询、晚到回执不激活、真实控制修订变化、原close→RUN_DENY以及所有连接外键检查。

测试为内存SQLite、串行执行和公开合成身份/时间/资源输入。未运行磁盘/WAL故障、进程崩溃恢复、并发连接竞态、身份提供者、NTP、HTTP/IPC、正常新trigger的完整链或真实设备。普通命令引用与保护预算接线、真正接管屏障完成后资源核对以及最终SDK归并仍须落实；阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_continuation_storage.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_storage.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_storage.py --check-report
```
