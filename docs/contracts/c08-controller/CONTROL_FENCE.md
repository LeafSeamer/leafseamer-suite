# 控制接管切点、完整屏障与生效提交候选

状态：待审阅设计资料，不是生产迁移。组合[控制受理148表](CONTROL_STORAGE.md)与本轮13表为161表；旧候选文件原样保留。本稿落实控制受理后的切点、原ACK及T4关联，继续遵守全系统方案完成后再业务实现的阶段边界。

已知事实：共享库已有普通/取消统一签发水位、资源占用与撤回、控制版本预留和不可变历史；此前148表不能发布effective。[生成器](build_control_fence.py)现在明确升级控制事件接受集，实际约束及检查以[SQL源](control-fence.sql)、[组合产物](controller-control-fence.sql)与[检查器](check_control_fence.py)为准。原件BODY、摘要和提供者在检查中均为合成前提，不构成真实取证。

设计选择：T3冻结完整签发切点；T4发布控制权生效并保持protected；设备资源清理和T5开放仍独立。控制屏障用于禁止旧资格继续发送，不能撤回已经送入设备传输层的字节，也不能把接管成功等同于设备当前状态已知。

## 字段与所有者

| 表 | 字段与关联 |
| --- | --- |
| cu_cut | operation_id、同受理change_id、device_id、共享issued_revision、cut_digest/body与审计；水位取普通及取消同一ci_issue，在插入和T3封存均核验 |
| cu_target | operation/exit唯一；引用ce_exit完整core/worker/IPC/device会话与运行域原件。保留本设备全部历史出口，含无许可及已退休出口，以保存退休依赖 |
| cu_member | operation/exit/permit、切点entered_known；两类未可靠核销许可共用ci_issue身份，双向差集证明不漏项、不添项 |
| cu_queued | operation/command、before_revision和blocked_revision；cu_cut插入时从同库前态自动捕获未签发queued，不能由调用者省略 |
| cu_delivery | barrier_id、attempt/operation/exit、target_gate_revision、完整请求摘要/原件及唯一outbox；每次尝试每活出口一条，尝试封存后不能增补 |
| cu_coverage / cu_ack | 每许可分类及typed proof；原ACK绑定epoch、安装版本、闸修订、共享水位、切点摘要和生效tick，并保存提供者验证/审计原件；覆盖与ACK双向提交 |
| cu_authorization | 生效change/operation、完整目标人员身份、同domain/descriptor、issued/expires、当前授权提供者及快照原件；与cu_effective双向配对 |
| cu_selection | 生效change/operation/exit，二选一当前attempt的原ACK或该出口退休证据；全集封存后不可增补 |
| cu_effective_member | 每个切点permit的T4冻结分类，全部成员恰好一次；原ACK不被该派生分类覆盖 |
| cu_effective | change/operation/attempt、同change的ct_state、完整选择清单摘要/原件及验证；每operation最多一份，发布须同ct_commit |
| cu_revocation / cu_protection | typed ACK/退休来源撤回及审计；同事务产生全部受影响活出口的待保护目标，新增出口补捕获。目标行不冒充实际关闸ACK |

库内版本、水位和tick仍为20位补零TEXT，线上不使用该补零格式。ACK版本等字段通过与受约束源字段精确相等检查；生效时间的真实采样、跨原件域绑定与完整JCS验证属于可信提供者义务，不由非空BODY证明。

## T3、原ACK和T4写集

T3使用单writer的`BEGIN IMMEDIATE`。追加原控制受理写集、操作及attempt；插入cu_cut时自动冻结queued清单，保存全部目标和未核销普通/取消许可，逐活出口保存FENCE请求及outbox，将每个queued命令追加blocked终态、锁存及完整公开修订；最后ct_commit封存并COMMIT。缺一条queued终结、cut成员、活出口delivery或原受理审计通知均拒绝。仍有未发prepare的queued也不能跳过终结；普通准备到最终IPC的完整原件映射另见剩余项。

只有当前可靠、已封存且未失效的完整资源核销才能从许可切点省略；单条settlement、worker退休或命令终态不够。所有出口仍保留目标，因此退休证据撤回不会丢失控制依赖。每出口ordinary和cancel各最多256，完整清单超过上限拒绝，不截断。已持久cut不可重新按当前剩余许可缩减；重取证沿用原cut、operation和目标版本，仅追加attempt及delivery。

原ACK接收为独立事务：先存完整coverage，后存cu_ack；失败整体回滚。epoch、目标版本、gate revision、cut摘要和共享水位必须回显一致。切点已经记录in_flight的成员不得降级。允许旧attempt的迟到ACK进入历史，其in_flight事实立即参与普通/取消统一分类，不等待该ACK被T4采用。not_sent必须由同一已绑定出口的未消费/未收到事实提供，不能因新worker缓存为空而制造；SQL中的provider_ref为待实现提供者引用，不自行证明这一事实。

T4同样在单writer事务中执行：旧pending仍是本operation、原epoch/effective version/holder未被替换、当前操作仍pending或indeterminate且采用最新attempt；当前授权完整身份正确且`issued <= now < expires`，release核原requester，acquire/transfer核target。目标选择与cut双向完全相等，后出现而未被cut覆盖的活出口阻断T4；必须先可靠退休该出口，不能暗改原cut补目标。所选ACK已退休、已撤回或属于旧attempt均拒绝；退休证明不能伪造未发分类。

成员分类先保留任何可信历史in_flight；否则退休分支为unknown，其余采用所选原ACK分类。插入cu_effective时检查一次，在最后ct_commit前完整复核，防止选择后出现新出口、退休、撤回或迟到强事实仍按旧分类生效。新ControlRecord和操作effective事件、选择/分类原件、授权、审计及通知同事务；holder/effective version精确改为预留目标，reserved不变，pending清空，gate保持protected。初始HTTP Receipt仍指向原受理修订1，不能覆盖成当前状态。

## 撤回、资源与恢复

迟到控制ACK的in_flight可以推翻依赖never_sent的普通或取消资源核销，通过现有cr_release_invalidation与ro_incident链同事务重开全部受影响hold、写关闭通知；失败回滚原ACK与保护，不留下已接受事实却漏保护的半边状态。effect_resolved核销不因单纯“曾发送”直接失效。

ACK撤回保留其历史in_flight；not_sent不再贡献当前分类。对撤回当时已经存在、覆盖该not_sent许可且依赖never_sent的核销，保守追加`control_ack_revocation`失效来源，即使另有未发证据也须重新取证。只影响当时的旧核销；后来独立验证的新完整核销可以成立，旧失效与保护仍保留，不能自动恢复开放。真实提供者必须证明新证据独立可靠，不得仅换id复用撤回证据。

已采用的ACK或退休证据撤回，使cu_valid_effective不再发布该生效证据，并向该设备活出口写cu_protection；退休证据自身被撤回的旧出口也纳入保护。历史holder和控制版本不可回退；恢复须新的完整关闭/核对和开放流程，不能删除撤回记录。当前没有cu_protection消费或解除的完整DDL，它是持久待办而非已执行FENCE。

崩溃恢复只读取已封存cut、attempt、原ACK和effective。T3提交前异常不消耗新版本；T3提交后响应丢失查原Receipt。ACK已提交但T4未提交时重新核当前条件；T4提交后丢响应读取历史生效记录，不能再预留版本。unknown重取证不重放动作，旧出口无法证明安全时继续protected。真实掉电恢复与多进程竞态尚未执行。

## 与IPC及最终发送的边界

[IPC0.8](../df03-service/ipc.schema.json)的FENCE/FENCE_ACK仍是线协议来源：operation/epoch/version/gate/shared cut、attempt binding与原件摘要映射到上述记录；cu_member中的ordinary/cancel分别映射逐传输两清单，ACK分类分别映射普通及取消coverage。ce_exit提供完整出口身份。原件provider仍须验证完整帧、方向、当前会话与运行域、双清单规范摘要、普通open_intents到逐传输的关联，不能只凭本轮关系列通过就接受IPC。

本轮在普通和取消许可**插入与最终签发提交**均检查控制闸。已有控制记录或正在构造控制cut时，没有ReadyCommit的候选库拒绝新许可；之前已持久签发的许可与其历史事实保留。这是T5尚未归并的临时门槛，不能作为最终功能删减、永远禁用控制、可部署方案或运行验收。

剩余冻结项：

1. [OpenPlan/Dispatch/ACK/ReadyCommit](OPEN_PLAN.md)完整持久化及动态有效性，统一control/gate/资源/权限与普通及取消最终签发。替换上述临时门槛，保留传播窗口和四个顺序点。
2. 控制保护目标的完整发送尝试、关闭ACK、恢复消费与原有ro关闭链统一；补退休证据撤回后的新证明身份及恢复，不复活旧出口资格。
3. AUTH/TIME等其余屏障同库归并，完整IPC原件和提供者、普通prepare/编码清单、DecisionEvidence、容量预留与GC规则；每目标256并非生产吞吐批准。
4. 统一Schema/OpenAPI/IPC/SDK及GUI映射，逐字段真实writer与严格解码/JCS、可信时钟/授权/监督器；不凭合成BODY关闭这些工作。
5. 实现阶段执行并发writer、进程退出/重启、产品SQLite驱动和磁盘故障、真实IPC与设备验收。阶段0关闭不要求提前完成实现验收，但必须先补全上述未定义的设计。

## 复验与实际证据

在仓库根运行`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_control_fence.py --check`和`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_control_fence.py --report`。`--check-report --staged`只核暂存字节，不重跑用例。结果与完整输入摘要见[报告](control-fence-report.json)。

检查只连接`:memory:`，预期集合人工给定；完整T3、queued终结、ACK与T4逐条缺写和主动异常比对全161表，另验证当前身份/TTL、晚强事实、退休/撤回、签发最终检查、不可变封存及实际256/257条容量边界。全部内存库再检查外键与完整性。SQLite版本仅记录本机检查环境，非产品引擎批准；这些结果不是真实并发、磁盘、IPC、鉴权或设备证据。
