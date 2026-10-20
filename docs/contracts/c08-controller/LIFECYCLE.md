# 命令终态、资源裁决与迟到证据

状态：待审阅，`controller-lifecycle/0.1.0-draft.1`。本候选明确终态与资源裁决的字段、可信输入、转换及持久写集，供下一统一SDK和Controller存储归并。局部模型由[build_lifecycle.py](build_lifecycle.py)生成；不修改已确认draft.4，不新增可运行服务。

## 1. 已知约束与本轮推荐

已确认约束：finished后不改phase/outcome；unknown可以追加resolution，只有独立释放证据齐备后才clear；接管effective、命令完成与资源可写分开；条件重试只允许尚未终结的命令。OBS完成四帧只适用于已批准的Cut场景；当前值相同、连接重建和监督退出均不是通用释放证明。（来源：[F02/F03](../../rebirth-f02-f03-design.md)、[F06/F07第3节](../../rebirth-f06-f07-design.md)、[DF04第4节](../../rebirth-df04-storage-design.md)。）

当前存储事实：[fence.sql](fence.sql)将发送核销分成never_sent和effect_resolved；迟到in_flight可推翻前者。`ce_open_permit`用于运行来源保护，只枚举automation，不是手动与自动化共享资源仲裁的全集；`ce_settlement`本身不验证模块证据BODY。[尝试附属层](BARRIER_ATTEMPTS.md)已经保留迟到ACK强证据，但没有完整终态/资源领域表。

推荐：**固定公共终态、只增证据、独立资源裁决、当前写入资格**四条线分别维护。释放必须覆盖该命令全部已签发传输及可能继续写的准备/重传入口。全局资源仲裁同时覆盖manual和automation，禁止直接复用仅自动化的`ce_open_permit`作为整机空闲判据。

若释放后迟到in_flight推翻旧never_sent核销，保留原释放历史并重新列入风险占用。此时另一命令可能已经取得整设备hold：不能为了“唯一活跃hold”拒收迟到事实或删除新hold；应保护关闭该设备，保留两份风险占用，逐许可核对。正常取得新hold的事务必须排除当前所有风险占用；迟到事实导致的冲突是可见保护状态，不是正常多持有人模式。

## 2. 字段及权威来源

| 模型 | 关键字段及所有者 |
| --- | --- |
| Policy | command_id、authority/database scope、device_id、不可变admission_ref、required_completion、completion/release/retry政策Ref、max_attempts、original_deadline_ref、whole_device冲突范围；Controller在受理时固定 |
| State | command/scope、revision、phase/outcome、effect/resource状态、暂停锁存、reason_code、terminal_revision、resolution_ref、完成/释放证据Ref和attempt_ids；Controller单writer发布 |
| Transmission | permit/transmission/attempt身份、原PacketRef、出口记录Ref、issued_revision、disposition及settlement_kind/ref；从所有历史attempt的持久登记及证据生成，不由worker提供“完整集合” |
| ResourceCut | cut_id、command/scope/device/hold、issued_cut_revision、完整attempt_ids及transmissions、cut_digest；同writer冻结，含已核销历史传输，不只列当前未决 |
| ReleaseEvidence | evidence_id、同命令/库/设备/hold、cut_ref、kind、固定policy_ref、future_writes_closed_ref、settlement_proof_ref、evidence_digest；模块/维护提供者取证后由Controller验证并保存 |
| DecisionEvidence | completion/failure/cancellation/resolution类别、原command/scope、完成政策及可选retry_policy_ref、全部attempt集合、achieved、effect、resolved_outcome和摘要；安全重试断言另绑定固定retry政策，不能把packet ACK直接归入completion |
| ProviderReceipt | receipt_id、scope/command、精确subject_digest与policy_ref、accepted/rejected/indeterminate、具名claims、source_refs、record_revision；只从可信提供者持久存储读取 |
| Resolution | resolution_id、command/scope、original_terminal_revision、独立递增revision、resolved_outcome、evidence_refs、resolver_ref与摘要；解释旧终态，不替换旧终态 |
| Transition | operation_id、expected_state_ref、转换kind、after快照、可选decision/release/resolution及audit/outbox Ref；同库原子提交描述，非公开写接口 |

Ref采用`id/revision/digest`，指向同拥有库的不可变记录版本；PacketRef保留IPC0.6原`packet_id/packet_digest`，不凭空增加packet修订。出口Ref是对既有不可变`ce_exit`记录的内部引用，记录修订固定1；完整出口身份仍包含原boot、IPC、设备session和clock，不能用一个Ref省略核验。ResourceCut的记录revision与issued_cut_revision分开，后者允许0。

Policy的admission_ref映射新版不可变RequestAdjudication，而不是可变Command状态；原adjudication引用始终不随State修订变化。State初始revision=1，后继严格U20加一；terminal_revision首次finished时等于该次State.revision，之后永不更换。Resolution.revision独立从1递增，不能拿State修订冒充。整数线上严格十进制字符串，数据库仍按既定U20补零策略；本局部检查不等于全SDK原始JSON解码完成。

所有摘要使用JCS/SHA-256与`sha256:`前缀。对象摘要只排除自身摘要字段，不递归删同名业务字段；expected_state_ref.digest覆盖完整原State。ResourceCut.transmissions按permit_id唯一升序；attempt_ids采用持久attempt序号顺序且不重复，集合须与权威登记完全相同。引用摘要可由攻击者重算，因此仍需核原拥有者、固定政策、完整集合与可信来源。

## 3. 提供者职责和失败结果

| 提供者 | 必须输入与成功输出 | 失败处置 |
| --- | --- | --- |
| 发送/集合提供者 | 所有command/attempt/packet/permit、原报告/屏障/监督记录、writer切点；产出完整ResourceCut和当前尝试的未发分类 | 缺页、缺原件、错出口或无法证明完整时indeterminate；不得用空集合清理 |
| 后续写入关闭提供者 | 当前控制/拒绝状态、全部旧出口、未消费许可、准备缓存及协议重传源；产出绑定同cut和hold的future_writes_closed证明 | 只关调度、只断socket或新worker报告未收到都不足；保留unresolved并关闭新写入 |
| 完成提供者 | 固定完成政策、目录/profile、精确原请求与协议会话及采集顺序；产出具名completion断言 | 仅结构合法或当前值相同不产accepted；明确失败和缺证据分开 |
| 释放提供者 | 完整ResourceCut、后续写入关闭证明及固定release政策；核对所有传输核销和设备内仍可能继续的影响 | module_settled或maintenance_settled须同时排除未来延迟影响；监督组为空不能单独产生这两个断言 |
| 安全失败提供者 | 固定retry政策、错误码、完整既往效果、原期限和剩余预算；另取资源释放证明 | failure_confirmed不等于safe_failure；未知和保护失效不成为可重试错误 |
| 核对提供者 | 原终态版本、全部旧事实、新观察的会话/因果证据、当前有权resolver | 只追加解释；证据不足仍unresolved，不自动重开原命令或解除Seamer锁存 |

ProviderReceipt没有“公共输入自报durable=true即可授权”的路径。相同JSON经HTTP或worker传入仅是候选材料，真实实现必须按内部对象授权读取批准提供者记录、核对来源内容、固定政策和采集时序。参考器的provider_receipts只是人工可信上下文，不能证明这些提供者已经实现。

政策被撤回后不得凭旧许可产生新设备写；历史强发送事实仍保存。旧效果/释放证明若被新证据推翻，追加失效和保护事实，不删除原记录。验证已知发送事实所需的历史身份，与授权新的设备控制分开；不能因当前人员退出而丢弃仍影响直播安全的报告。

## 4. 转换与重试

| 转换 | 必需条件与结果 |
| --- | --- |
| dispatch | 原queued、未锁存、无冲突、当前门控及原截止通过；T2持久许可后dispatching/pending/possible |
| transport | dispatching且存在同命令可靠in_flight事实；进入awaiting_evidence，不能仅凭IPC投递成功 |
| complete | dispatching或awaiting_evidence，固定政策确认达到required_completion；finished/succeeded，但无释放证据仍unresolved |
| fail | 有明确failure_confirmed；finished/failed，保留partial/possible等效果；不要求假装无副作用 |
| timeout | 派发后证据期限到且无确定结论；finished/unknown，锁存；queued超时走expire |
| cancel | 纯queued且无任何历史传输时，持久阻止派发后cancelled/not_sent；有历史传输则核当前取消政策和全部影响，不抹除历史效果 |
| block/expire | 当前尝试已关闭且完整未发；按原因终结，先前attempt效果仍保留；当前尝试有未知则不能伪装blocked/expired未发 |
| retry | 尚未finished，明确失败且另有safe_failure、批准retry政策/错误码、尝试预算、原期限、当前门控和独立释放证明；同command回queued，下次另建attempt并重新T2 |
| reconcile | 已finished，核对原terminal_revision并追加Resolution；phase/outcome及暂停锁存保持 |
| release | 已finished且独立释放证据齐全；原unknown还必须已有Resolution；不改变outcome |
| protect | 保持原phase/outcome，锁存并发布当前风险资源状态；不伪造设备完成 |

三个完成层次继续为sent、acknowledged、effect_verified；它们表示固定政策下的完成标准，非任意协议ACK可升级。重试的初次尝试计入max_attempts，排队和backoff不刷新原截止；本参考器只核剩余预算快照，不实现预算计费。OBS首闭环的retry_policy_ref为空且max_attempts=1。

effect_status保留命令全部历史影响，不能用最后一次not_sent覆盖先前发送；partial与verified不是简单升级关系。本轮有限参考汇总优先保留partial，其他证据提升仍须完整政策判断。真实提供者必须区分“完整动作效果已验证”和“仅某个primitive已验证”，不能把单primitive结果放进命令级verified输入。

## 5. 释放与冲突规则

never_sent只允许完整集合中每项都有可靠not_sent及never_sent核销，且所有尚可触发后续写的入口已关闭；集合为空仍需要真实切点及关闭证明。module_settled和maintenance_fenced均需要完整核销与独立settlement_proof，不能把ce_settlement中任意非空BODY当作证明。

对整体unknown允许Resolution说明后来确认的结果，并在独立释放证据齐备后clear；原outcome仍unknown，原终态时间/版本保持。对于succeeded且required_completion仅sent，资源可以继续unresolved。资源clear不等于READY或拥有控制权，每次新派发仍核当前holder、授权、时间、deny和预算。

整设备hold正常准入排除manual和automation全部当前风险占用。纯queued只保存claim、不独占设备；T2建立hold。若重试前释放旧hold，下一attempt仍需重新竞争并取当前控制资格。参数/profile未来支持细粒度时沿Q35路线图增加经过审阅的重叠判定，不直接取消整机互斥。

迟到证据推翻never_sent时，当前占用视图从原完整关联重算；风险重复占用不会丢弃。先经独立保护通路关闭派发，再持久异常、影响集合及新保护操作；若关键存储失败，沿Q52停写。已经发出的另一命令仍按事实核对，不能宣称冲突发现时已经追回设备副作用。effect_resolved若已包含同传输的独立效果排除证明，迟到的重复发送观察本身不推翻它；证明本身失效另走显式失效记录。

## 6. 与SQLite写集的归并约定

本节定义下一DDL必须实现的物理关系。本轮没有新增或运行该DDL，不扩大既有51表检查范围。

| 对象/事务 | 物理映射和提交要求 |
| --- | --- |
| 初始Policy/State/claim | ca_command_initial保持不可变；新的command_policy及command_revision(rev1)、resource_claim、审计/outbox与T1受理同事务；ce_command绑定相同command/device |
| 当前State | command_revision主键(command_id,revision)，只增；command_current只读已提交最高修订；command_commit与revision双向延迟FK，commit同时要求审计/outbox |
| T2活跃hold | resource_hold绑定command/device及固定whole_device范围；单writer检查全部风险占用，hold、attempt/permit/guard/预算及dispatching修订同事务；准备纯编码不能提前消费许可 |
| 证据接收 | receipt主键保留(worker_boot_id,ipc_session_id,report_id)，同内容只查原；evidence按命令/attempt/出口/政策复合绑定，迟到原件只追加 |
| 核销与释放 | settlement_validation将ce_settlement绑定已验证证据；resource_release及release_member绑定完整ResourceCut，两向差集后封存，release不可先于证据/审计提交 |
| Resolution/T6 | Resolution、command_evidence、后继State、资源结果、暂停锁存与审计/outbox同事务；双向延迟FK和封存完整性检查阻止缺写；提交后才REPORT_STORED |
| 迟到失效 | 追加release_invalidation/protection记录；保留旧release及当前另一hold。正常hold准入唯一性通过完整风险视图与串行writer保证，不用会拒收迟到事实的简单partial UNIQUE替代 |
| 恢复 | 从全部原记录重新验证当前风险集合；不以存储State.resource_status=clear作为唯一准入事实，不恢复旧可发送队列或消费旧许可 |

接受集统一时还需将State投影回完整CommandRecord，并保留身份、控制绑定、取消状态、完整attempt及版本等未在本局部复制的字段；不能把局部State直接当公共GET响应。所有新增表、command查询/取消/证据HTTP、其他三类屏障及P1/P4仍由原关闭清单追踪。

## 7. 故障与验收

| 场景 | 必须结果 |
| --- | --- |
| 成功证据已收，释放证据缺失 | succeeded与unresolved可同时成立，禁止同资源新写 |
| ACK/当前值存在但提供者无法确认因果 | 不生成accepted完成/释放回执，保留unknown |
| 原unknown后得到完整迟到效果 | 原terminal不变，追加Resolution；有独立释放才clear，自动化仍锁存 |
| 释放集合少一个旧重传，攻击者重算摘要 | 与权威完整集合比对拒绝 |
| 同证据ID/摘要借另scope、hold或policy | 拒绝，摘要相等不构成授权 |
| 明确partial失败，但没有safe_failure | 可failed，不可自动retry |
| 重试预算耗尽、期限等号或新接管 | 拒绝新attempt，不能刷新截止或原控制版本 |
| release后另一命令已持有资源，迟到旧in_flight | 两份风险关联都保留，保护关闭，不能靠约束冲突丢事实 |
| T6写入中异常或提交结果未知 | 未提交不确认报告；结果未知查原事务，不重复设备发送 |
| 数据库重开显示clear但证据/成员缺失 | 领域核对失败，保持关闭；integrity_check成功不足以放行 |

[参考检查](check_lifecycle.py)实际执行Schema和合成快照判定，预期独立手写；报告绑定原始输入。[参考模型](lifecycle_model.py)不运行数据库、WAL、并发、真实提供者、IPC、时钟或设备。T1/T2/T6缺写与掉电实验需下一DDL及实现阶段分别执行，本轮不以布尔快照替代这些证据。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_lifecycle.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_lifecycle.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_lifecycle.py --check-report --staged
```
