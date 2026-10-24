# 继续运行执行绑定与完整IPC归并候选

状态：`approved=false`，具名契约`continuation-execution/0.1.0-draft.1`，IPC为`ipc/0.14.0-continuation-draft.1`。交付[具名Schema](continuation-binding.schema.json)、[完整IPC](continuation-binding-ipc.schema.json)、[导出清单](continuation-binding-manifest.json)、[单一生成器](build_continuation_binding.py)、[关系子检查](continuation_binding_model.py)和[正反例](check_continuation_binding.py)。旧公共draft.4、IPC0.3及后续0.13候选原字节保持不变。

## 已知事实与依赖分析

已知事实：[上一轮CommandGrantBinding](continuation-protocol.schema.json)含submission_id，实际命令提交在执行计划持久化之后产生；[原ExecutionBinding](lifecycle.schema.json)先保存固定计划摘要与grant引用。当前[完整IPC0.13](../c08-controller/journal-ipc.schema.json)已有52帧，普通TransmissionPermit的transmission.intent引用IntentRef，其中已含automation_binding及其摘要，不需要另建一份平行Intent身份。

基于这些事实，将整个CommandGrantBinding嵌回ExecutionBinding会形成提交身份依赖环。本候选分离执行级完整目标清单与命令级选择；submission_id保持在后续命令/提交映射中。Intent沿原逐传输身份扩展已有AutomationOriginBinding，保留重传的原dispatch_intent_id、独立permit_id和ordinal语义，不新增可能冲突的Intent编号。

## 同版字段与无环生成顺序

| 对象 | 新字段或引用 | 约束 |
| --- | --- | --- |
| ExecutionBinding | binding_version、authorization_mode、continuations | preparation时清单为空；continuation时必须是新trigger，含完整目标清单，不能是原恢复execution |
| ContinuationTarget | controller_scope、selection、device_ids | 按Controller scope升序唯一，与转交Request完整目标和设备严格一致，最多32个Controller |
| ContinuationSelection | transfer_ref、adoption_ref、receipt_ref、grant_ref、plan_ref、parent_preparation_ref | 全部为原件scope/id/revision/digest，不含本地registration或submission；必须对应同一次已采用转交 |
| AutomationOriginBinding | binding_version、authorization_mode、continuation | 原origin/run/definition/generation/execution/step/logical_action及execution_binding_ref保留；preparation为null，continuation必须选本Controller那一项 |
| CommandRequest / CommandContent | 沿automation_binding引用新选择 | manual仍为null；run_binding必须使用新grant而非原recovery grant；完整选择进入内容摘要 |
| ExecutionGuard / TransmissionPermit / IntentRef | 沿同一个AutomationOriginBinding定义接入 | 三份必须逐字段一致；Intent及GUARD_ACK原automation_binding_digest覆盖完整新版绑定 |

固定顺序：批准未封装计划→Controller转交及Receipt→Seamer完整采用→原恢复R5→新执行完整ExecutionBinding与摘要→新请求的execution_binding_ref→CommandContent摘要及提交身份→Guard摘要→Permit及IntentRef→完整帧与共享日志摘要。任何阶段不得把后面尚未分配的提交身份或完整帧摘要放回前一阶段。

ExecutionBinding.grants只列新继续运行grant，顺序与continuations一致；旧parent准备独立保留，不能改成arm。binding_digest排自身顶层字段后JCS；CommandContent只排顶层context_id/idempotency_key/correlation_id；guard_digest排自身；Intent/ACK的automation_binding_digest覆盖完整绑定。不得递归忽略嵌套同名字段，也不得只摘要grant ID而漏采用、执行或计划。

执行绑定引用显式为kind=execution_binding、scope/object_id/revision/digest，revision为正U20。origin_scope及该Ref使用已有转交Scope，run/execution/step/logical_action身份沿用转交ID词法，正确承载实际数据库名和生成身份中的点；不再误套原保护通用Ref的窄ID表达式。其他旧字段词法不在本候选中全局扩大，无法按旧词法表达的身份必须在编译/发布阶段拒绝并报告，不能改名后失去原件关联。最终全系统ID词法和单一SDK源仍需逐节点统一，不能将局部格式对齐视作已经完成。

## Guard、许可与Intent的关系门槛

[子检查](continuation_binding_model.py)核对实际转交原件全集、采用引用、新执行、指定Controller/设备、固定步骤和参数；同时核对请求run_binding、Guard中的完整服务issuer/epoch/principal/audience、新grant ID/revision/generation，以及Permit/Intent/ACK的permit、command、attempt、session、guard和绑定摘要。重算摘要不能修复错误原件或偏离固定参数。

新执行完整正文须由可信Seamer提供者给出，不由命令提交者自报。Controller必须独立核对当前grant、采用/R5、身份、控制、来源、时间和预算；原件历史相等不代替当前资格。测试中的当前grant可从真实候选SQLite的cr_current取得，cr_revocation提交后该事实为false；其他权威前提仍为明确合成输入。

本轮**不是完整最终AdmissionSeal**：编译后的完整ExecutionBinding正文、动作资格/参数提供者、精确Controller/worker当前域、逐传输预算、packet原字节和原件撤回仍须在同writer和最终唯一出口联合重核。子检查返回binding_valid只证明这条授权关系，不能调用发送、解除四个既有最终签发阻断或宣布设备ready。旧119/236表中的简化binding_body和请求投影尚未迁移成本候选的完整格式，SQL类型化等价与最终写集是下一项必交付。

## 完整IPC兼容边界

保留0.13全部52种帧、方向、reply_to、durable/volatile_close规则、共享方向日志、取消、编码与释放及保护覆盖。所有帧版本同时推进0.14；HELLO和HELLO_ACK新增必选能力continuation_grant_binding。版本或能力不足时不建立该执行通道，不以旧格式投递新绑定。

GUARD_INSTALL、DISPATCH、RESEND_DISPATCH、IntentRef和ACK通过同一局部类型引用取得新版绑定，避免逐帧手抄产生差异。普通和重传都必须使用当前独立许可及精确Guard；旧packet复用不授新主体发送权。本轮保留手动和preparation分支形状，取消执行仍按自己的Requester与独立Plan，不偷用父普通命令的新授权。

本轮52帧测试是**结构兼容检查**：在旧公开合成夹具上明确升级版本和绑定格式，不宣称运行了52帧真实服务或重放完整协议。继续运行正例另外核对请求/Guard/Permit/Intent/ACK之间的语义关系；旧所有屏障运行轨迹仍需服务实现后联合验收。

## 故障验收与剩余交付

- 旧版本、缺握手能力、漏授权模式/选择字段、manual夹带自动化选择：结构拒绝。
- 执行仅列部分Controller、复用恢复execution或旧grant、请求选择错Controller/设备：原件关系拒绝，不静默裁剪。
- Grant/Adoption/Receipt/plan任一引用改变并重算摘要：与可信完整原件不符时拒绝；不能凭两份同样伪造的数据互相证明。
- 参数修改并重算CommandContent、同名主体换issuer_epoch、Intent或ACK引用旧许可：拒绝。
- Controller实际撤回：新授权链失效；历史原件保留，原在途与资源仍沿已有保护结算。
- 顶层运输字段变化不改CommandContent；嵌套同名业务字段改变必须改摘要。

[报告](continuation-binding-report.json)绑定新资料及所用旧输入字节，明确最终AdmissionSeal、真实运行及设备检查均未执行。当前执行完整正文和完整传输对象仍含合成提供者字段，不能将实际SQL转交引用测试扩大成全库字段迁移成功。下一轮必须补同版公共命令接口、SDK可消费来源与SQL映射的具体对账，继续身份/时间/容量/GC及最终签发全写集收敛；阶段0不关闭，业务代码未改。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_continuation_binding.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_binding.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_binding.py --check-report
```
