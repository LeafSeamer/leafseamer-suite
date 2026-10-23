# 控制受理与转交的持久化候选

状态：待审阅的设计资料，不是生产迁移。以[控制权契约](CONTROL_AUTHORITY.md)为字段与行为依据，在[137表共享Controller布局](PROTECTION_OUTBOX.md)后增加11表，形成148表组合。只使用原`controller_scope`，不另建authority或设备签发水位。全部系统方案完成后再进行业务实现。

已知事实：上一轮163项检查使用字典副本，并未执行SQLite；已有共享库保留普通与取消签发、完整RUN及取消关闭、资源撤回和保护通知。接管的完整cut、queued清单和逐出口采用尚未落入该库。（来源：[有限模型](control_authority_model.py)、[共享库生成器](build_protection_outbox.py)、[F02/F03](../../rebirth-f02-f03-design.md)。）

本轮设计选择：先把公共字段所依赖的控制历史、版本预留、邀请及接受操作、请求裁决和审计通知固定为可执行约束。新候选**不提供effective或ready的写入路径**；这是尚待完成的组合门槛，不能把永久阻断作为最终交付，也不能把本轮局部受理称为完整T3。接管完成与手动控制仍是首期必需功能。

## 表与字段所有者

| 表 | 不可变字段及约束 |
| --- | --- |
| ct_change | change_id、单库scope、device_id、精确递增sequence、previous_id、kind、必需成员身份及此次可信单调时钟观测；sequence是每设备写集顺序，不冒充ControlRecord.revision |
| ct_state | record_revision、control_epoch、effective/reserved_version、完整holder三元组、mode、pending_operation_id、gate_state、完整原件与摘要；只有控制记录变化才追加 |
| ct_operation | operation_id、初始change、kind、完整requester和target、expected_state_id、target_version、原offer、force与reason；新pending预留目标版本，后续历史不能更换目标 |
| ct_operation_event | operation/revision、pending/indeterminate/rejected、当前attempt、failure_code、完整结果原件与摘要；生效终态须后续完整屏障层另行接入 |
| ct_attempt | 不复用的attempt_id、operation、精确ordinal、所属change；重取证不再次预留控制版本，原尝试保留 |
| ct_offer | offer_id、原始change、双方完整身份、expected_state_id、domain/descriptor、issued/expires tick及理由；原件固定，不因当前控制修订变化而覆盖 |
| ct_offer_event | offer/revision、offered/accepted/expired/cancelled、accepted_operation_id及结果原件；接受事件与transfer操作必须同写集，终态不可改写 |
| ct_request | 完整人员身份、request_epoch、HTTP操作名、idempotency_key唯一；内容摘要不进入Key；保存原内容及初始结果的kind/id/revision/digest |
| ct_audit / ct_outbox | 同change审计与状态变更通知，通知ID唯一；这些通知不是已经构造完成的设备屏障消息 |
| ct_commit | 与change及审计/通知双向配对的封存记录；检查当前CAS、精确成员集、身份和全部状态关联后才发布当前视图 |

scope由单库`controller_scope`隐含加入RequestKey；device在请求内容中，不加入原契约未声明的Key。邀请创建/取消/过期推进写集sequence但不改ControlRecord.revision；retry仅改变操作修订和当前尝试。ControlRecord、operation及offer各自连续修订，不能混用计数器。

库内U20用20位补零TEXT，分为两个10位整数计算后继，避免超过SQLite有符号64位后转浮点。检查不只验证算术表达式，还把跨10位进位、跨2^63以及最后一个可预留版本写入真实SQLite表；耗尽拒绝，不回绕。wire词法仍按公共Schema，不把补零存储形式发送给客户端。

## 封存及故障顺序

写集使用`BEGIN IMMEDIATE`，追加header、相关历史成员、初始Receipt、审计/通知，最后插入ct_commit并COMMIT。header反向引用commit；commit检查成员全集并反向引用审计/通知。缺任一成员、遗漏封存、错误归属或错误CAS均不能提交。所有表拒绝UPDATE/DELETE，封存后禁止继续补成员。当前视图只选择已封存写集，数据库事务外可见性另由SQLite保证。

接受邀请必须同时满足原邀请仍offered、当前无pending、完整接受者身份与target一致、sender仍为当前holder、原epoch/effective_version不变、同domain/descriptor且`issued <= now < expires`。同版本普通重启可以增加ControlRecord修订；不因此废弃仍可证明有效的邀请。实际权限、域连续性和now的真实性由Controller可信提供者核验，不能接受HTTP自报值。

新受理保存pending、reserved+1和fencing，但effective_version及holder不变。未知保留pending并protected；明确拒绝清pending，保留reserved、holder及protected。重取证只允许indeterminate，新增唯一attempt，仍为indeterminate；它不宣称旧出口已经退役。恢复或新接管均不能复用历史版本或尝试身份。释放受理同样保留旧holder，后续完整T4才能变automatic/null。

邀请取消必须由原sender请求；到期或换域只终结offered，accepted不再过期。过期、取消和普通重启均不释放holder。force仍需服务核验control.emergency，本层只检查force字段、非空理由及抢占条件，不能把存有force=1当作拥有权限。

同Key重复由已鉴权服务先查ct_request并比较原内容，返回原初始Ref；SQL唯一键阻止第二裁决，但本检查器不实现HTTP查原。提交响应丢失只读原记录，不重新受理。提交结果不确定时不得把客户端超时解释为版本未消费。

## 本轮证据和剩余冻结项

生成源为[build_control_storage.py](build_control_storage.py)，产物为[controller-control.sql](controller-control.sql)，检查器为[check_control_storage.py](check_control_storage.py)。检查仅连接`:memory:`，启用外键及递归触发器，对11类写集逐语句缺写和主动异常检查全148表回滚，另验证竞争的两个串行顺序、接受身份/TTL/跨域、版本耗尽、完整历史、终态和封存约束。实际数量及输入字节摘要见[报告](control-storage-report.json)。

`bootstrap`是本轮参考库装载一个已存在ControlRecord前态的内部边界，允许测试人工holder和高位计数；它不是新的HTTP接口，也不批准任意导入持有人或旧数据迁移。完整产品初始化必须是新的automatic/null控制域，已有库只能通过受验证历史恢复，不得把本探针bootstrap当恢复绕过路径。

原件BODY与摘要在本轮为合成夹具，非空检查不验证JCS、Schema、权限、可信时钟或原件真实性。原结构到SQL字段的真实writer仍须逐字段映射。SQL事务检查不是磁盘崩溃或真实并发验证，本机Python所带SQLite不构成产品引擎批准。

下一次控制屏障归并必须同时完成，不能通过只写verified布尔值解除门槛：

1. T3与共享签发切点、完整queued/ordinary/cancel集合、全部旧出口及屏障outbox同事务；本轮ct_outbox只负责状态通知，不替代它们。
2. 接入实际attempt与ACK/退役原件、完整coverage及撤回依赖；未知重取证必须保留旧尝试强事实，不能只切当前attempt字段。
3. T4增加effective状态及不可变effective_control_ref，仍精确占pending且目标当前有权；同事务完成归类并保持protected。拒绝的授权证据也须精确绑定。
4. OpenPlan/Dispatch/ACK/ReadyCommit的完整DDL和当前control/gate/权限/资源关联；同步接入普通与取消最终签发守卫，验证旧许可传播窗口。原137表子域的许可入口不读取本轮ct_state，当前组合不得用于设备发送。
5. Schema/OpenAPI、GUI、面板和SDK同版映射，以及产品SQLite驱动、真实writer竞争、断电恢复和设备验收；不得用本轮约束通过代替这些证据。

复验：在仓库根使用`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_control_storage.py --check`和`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_control_storage.py --report`。`--check-report --staged`只核暂存原字节，不重跑测试。
