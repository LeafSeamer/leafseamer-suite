# 恢复后继续运行转交候选

状态：`approved=false`，内部版本`run-continuation/0.1.0-draft.1`。本轮给出可校验的[具名Schema](continuation.schema.json)、[生成器](build_continuation.py)、[关系判定模型](continuation_model.py)、[正反例](check_continuation.py)及[输入绑定报告](continuation-report.json)。公共draft.4／IPC0.3、原109表布局和旧报告不变。候选尚未完成数据库归并，不构成已实现的恢复闭环。

## 已知事实与推荐决策

现有准备有两种作用域：arm覆盖固定run/generation，recovery仅覆盖固定execution；原准备、回执及grant不可重写。同一Controller、origin、run、generation只能有一个准备身份。R5释放Seamer恢复互斥锁，但必须有准备转交或撤销核对证据。现有109表检查会拒绝恢复后的普通trigger，缺口真实存在。（来源：[准备约束](../c04-preparation/README.md)、[R5释放规则](../c04-storage/README.md)、[来源恢复串联](SOURCE_RESYNC.md)）

**推荐在R5前完成独立授权转交。** 保留原recovery准备及execution限制；Controller在原准备之下签发新的run-generation grant，Seamer收齐完整目标集合后持久采用。R5必须引用该采用原件，并重核当前资格；普通trigger使用新grant及采用原件。新grant同时依赖原准备的关闭、RUN_DENY和当前身份/控制权，不形成绕过准备的第二入口。

这是基于上述约束的候选设计。所有可信提供者在本轮模型中仍是合成输入；Schema通过和关系正例通过不证明Controller已经签发、Seamer已经提交R5或设备已经执行。

## 三份不可变原件

共用字段：`contract_version, origin_scope, run_id, generation, transfer_id, recovery_operation_id, recovery_execution_id, continuation_plan_ref`。generation及修订均为规范正U20十进制字符串；Ref为`scope/id/revision/digest`，Scope为`authority_service_id/database_instance_id`。所有对象禁止额外字段。根Schema故意拒绝所有实例，必须显式引用`$defs/Request`、`Receipt`或`Adoption`。

| 原件 | 专有字段与绑定 |
| --- | --- |
| Request | request_epoch、actor(issuer_id/principal_id)、idempotency_key、approval_ref、targets、request_digest |
| Target | controller_scope、preparation_ref、recovery_grant_ref、devices；每个Device含device_id、control_ref、authorization_ref、action_set_ref |
| Receipt | request_digest、controller_scope、receipt_id、revision=1、target_digest、preparation_ref、recovery_grant_ref、continuation_grant_ref、qualification_ref、receipt_digest |
| Adoption | request_digest、adoption_id、revision=1、expected_run_revision、expected_slot_revision、expected_operation_revision、receipt_refs、release_proof_ref、adoption_digest |

摘要为JCS编码后SHA-256，排除各对象自己的摘要字段。approval_ref指向人员批准原件，其subject是Request排除approval_ref与request_digest后的摘要，避免循环摘要。人员确认的内容因此包含固定继续运行计划、完整目标、当前控制/授权修订及幂等身份。Approval提供者必须校验当前人员身份和范围；只验证摘要不足以证明授权。

targets按Controller scope二元组升序唯一；devices按device_id升序唯一。完整目标由已批准继续运行计划展开并与当前受监督资源清单对照，不能把原recovery步骤的设备子集直接当作完整继续运行集合。每个目标仍必须属于本代已经存在的原准备；若继续运行需要未准备的新设备或动作，拒绝转交，走关闭核对和新代次预览，不临时扩充原准备。

preparation_ref、recovery_grant_ref及设备三类Ref均由对应Controller签发；approval_ref与continuation_plan_ref由origin提供。Ref中的scope不是请求者自选的信任根，须由现有连接/身份配置确定。Receipt新增grant_ref必须与原grant身份不同，且真实grant正文绑定请求、目标、计划、parent_preparation_ref、`scope=run_generation`和`activation=adoption_and_r5`。qualification_ref绑定当前受监督域及控制/授权资格快照；旧资格Ref不能代替发送时的新检查。

## 决策点和可见状态

1. **请求受理。** R4已经开始；run仍为running，恢复operation为running或reconciling，恢复execution仍running。全部必需步骤已有合格完成证据，未提交业务状态；原在途资源已核对，恢复互斥锁仍持有。完整目标、授权、来源、时间及容量合格后，保存唯一转交请求和审计/固定通知。GUI显示“恢复执行完成，等待继续运行资格”，不得显示恢复完成或接收普通trigger。
2. **逐Controller签发。** 核对原准备确为本恢复execution的applied、代次高于RUN_DENY、没有close、设备当前自动控制且无pending接管、审批和计划有效、域/时间/容量有效。在同一Controller事务新增独立grant、Receipt及seal/审计/固定通知。原preparation、recovery grant和回执字节不变。只签发资格，不开放设备出口，不发送恢复或普通命令。
3. **Seamer采用。** 每个回执可先保存为历史，但只有收齐按请求排序的全部回执、核对真实grant原件和当前资格后，才可写唯一Adoption。采用用run/slot/operation三项CAS；release_proof_ref必须覆盖本恢复执行、请求摘要、完整回执集、资源清理及保留的全部parent准备。原恢复锁继续持有，run不变armed。
4. **R5提交。** 当前步骤证据、业务状态CAS及原门槛之外，增加Adoption精确引用及当前资格检查。同一Seamer事务提交业务状态、execution succeeded、operation completed、run armed/dispatch eligible、恢复锁释放、采用引用、审计及固定通知。任意写项失败整笔回滚；Adoption本身不是R5成功证明。
5. **普通触发。** ExecutionBinding、完整计划seal、submission、attempt和Controller新命令受理都须引用同一采用和新的grant。当前普通执行必须属于同run/generation/plan；新grant不可拿来追发原recovery execution，旧recovery grant也不可用于普通执行。最终唯一出口仍核当前授权、控制、域、时间、关闭、预算与完整动作/参数资格。

跨Controller与Seamer不做分布式事务，也不承诺R5时所有远端状态永不变化。R5后的armed表示本地完成了采用，不保证之后设备一定可发送。Controller在采用之后发生接管/撤权，必须立即拒绝新命令并沿共享保护路径通知Seamer；Seamer收到后暂停。两者间隙由Controller唯一出口守卫封闭，不能靠Seamer缓存回执保证安全。

## 唯一身份、查原和失败

Seamer转交身份以`origin_scope/run/generation`唯一，同时保存`request_epoch/actor/幂等键`与transfer_id唯一映射。Controller以`origin_scope/run/generation/parent_preparation_ref`唯一，校验全局transfer_id及完整请求摘要。一次转交只能产生一个新grant和一个Receipt；不允许换ID或换幂等键在同代重签。采用以origin/run/generation唯一。

已提交原件响应丢失时，在当前读取权限下按原身份查询，返回原字节，不再次签发。历史查询与当前active资格分离；撤权/close后可以返回历史Receipt但必须拒绝采用和新命令。查原not_found不证明请求从未受理；不能自动换ID补签。确认需要中止时，向所有请求目标执行现有prepare close及完整RUN_FENCE，覆盖未收到回执的目标，之后等待保护观察与资源核对。

转交部分完成、超时或失败时，不提交R5、不释放恢复锁、不自动重跑已经完成的恢复动作。确定失败采用既有暂停/锁存事务并关闭完整目标；无法确定写入结果时保持恢复锁及证据，显示待核对。迟到Receipt只补历史，不清暂停锁存。可继续的暂时读取失败只重读同一原件；重新授权、换计划或换设备要求新预览/新代次，不在同代重开转交。

## 持久化映射与故障验收

以下是下一轮必须归并到真实组合布局的写集设计，不是本轮已经存在的表或触发器：

| 域 | 最小原子写集 | 必需约束 |
| --- | --- | --- |
| Seamer请求 | 请求原件、完整目标/容量占位、最后seal/审计/通知 | 唯一run/generation；绑定recovery operation、p1_preparation和固定完整计划；反向延迟FK确保不能缺seal提交 |
| Controller签发 | 新grant正文、Receipt、parent引用、最后seal/审计/通知 | 复用cp_request/cp_current及run_deny_current；控制/授权/域修订CAS；保留ce_run_command的全run保护归属 |
| Seamer采用 | 收齐的回执原件引用、Adoption及release证明、最后seal | 目标集合严格相等、三项CAS；R5必须引用，不能用旧synthetic release绕过 |
| Controller命令 | command/ExecutionBinding对continuation grant及adoption的明确引用 | 原ce_command只关联cp_receipt不足，须增加明确授权模式和引用，不能仅改Seamer计划guard |
| 撤回保护 | 共享PQ withdrawal/close及完整保护计划、预算扣账、最后seal | 不伪造source故障；不调用会漏新预算的旧withdraw writer；保护覆盖原恢复和后续普通执行 |

保护资源分开处理：恢复execution的设备在途hold必须可靠结束；原parent准备及run-generation grant作为持续运行资格保留。close原准备会使新grant一同失效，所以不能先close parent再宣称已转交。释放Seamer恢复锁不会释放尚未核对的设备资源；release证明必须列出清理项与保留项及其权威证据，不能只填kind=release。

| 故障时序 | 断言 |
| --- | --- |
| close先到，签发后到 | 无新grant；同代不可换transfer_id重开 |
| 签发提交后响应丢失 | 查询同一Receipt；没有第二次签发 |
| A已签发、B接管 | Adoption拒绝；A的历史不删除；全部目标进入关闭核对 |
| 已采用但R5前崩溃 | 查Adoption和R5原件，未提交R5则不能普通触发；当前前提失效走保护 |
| R5提交后响应丢失 | 查既有R5及采用原件，禁止重跑恢复动作 |
| R5之后Controller接管或撤权 | 历史查询成功但新命令拒绝；原在途命令按既有屏障结算 |
| 新代次到达后旧Receipt迟到 | 仅归档旧代，不开当前运行 |
| 缺任何seal或写后异常 | 所属本地事务整笔回滚；跨库已提交原件保留并可查原 |
| 满配目标、容量不足 | 请求签发前整笔拒绝；不得裁剪设备、挪保护预留或剔除未响应Controller |

## 容量和本轮验证边界

请求最多32个Controller、每目标最多256设备且全请求总设备不超过256；JCS编码请求最多262144字节，Receipt和Adoption分别最多16384字节。数量和字节限额均需检查，唯一身份历史不能删除来回收重签机会。每个run/generation只准一个转交；普通分区预留完整请求、全部回执、Adoption、索引、审计/通知和出站重投成本，保护分区另行覆盖新增grant和命令。上述上限是模拟候选值，不是生产容量承诺；完整CostManifest和GC仍未冻结。

本轮实际检查覆盖三份结构、缺字段/未知字段、重新计算摘要后的错绑、完整目标集合、CAS、旧grant复用拒绝、当前接管/撤权/close拒绝、历史查原及普通新execution使用新grant的**纯关系正例**。模型不保存原件、不实现SQL事务、不签发真实grant，也不执行HTTP/IPC。其`final_exit_verified`等字段是明确的合成权威前提，不是API参数或可接受的生产实现。

剩余必交付：在109表Seamer与当前Controller完整组合布局中实现上述写集及强约束，逐写遗漏/异常回滚、真实两库签发与采用、旧recovery限制保留、来源恢复→R2/R4→转交→R5→普通trigger→完整动作完成的成功链，以及接管/撤权/close在各切点的失败链。必须再核对新增对象纳入保护库存和预算。现有109表的越界拒绝继续保留；本轮关系正例不能替代该组合正例。真实并发、WAL/进程崩溃、平台、时钟和设备验收均未执行，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_continuation.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation.py --check-report
```
