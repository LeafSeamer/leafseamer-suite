# 执行登记与运行保护切点

状态：`controller-execution-storage/0.1.0-draft.1`，待审阅的附属设计。按顺序加载 [controller.sql](controller.sql) 和 [fence.sql](fence.sql)，共46表；不是产品迁移或已实现服务。旧29表检查保持原覆盖，新增17表由独立检查器验证。

## 1. 已知约束与本轮推荐

既有设计要求完整历史出口、逐许可覆盖、提交后才发送、未知不重放；ATEM同一动作可有协议重传，一个动作也可能含多个primitive。（来源：[F02/F03](../../rebirth-f02-f03-design.md)、[C11视频控制第8节](../../rebirth-c11-obs-atem-design.md)。）

据此按 `command → attempt → packet/primitive → transmission permit` 分层登记。同一个packet的ordinal从0精确递增；不同primitive分别从0开始，每次传输分配全局issued_revision。协议重传绑定原packet和初次许可，不能借另一packet的父许可。ordinal的INT32上界只是存储范围，实际次数必须由批准profile及预算提供者收紧；实验重传次数不是所有协议的固定额度。

本候选只落实运行来源保护的持久集合和逐出口应用。人工接管、身份/时间撤销、设备资源释放、命令终态和完整发送调度仍使用各自契约；不能把RUN_FENCE结果冒充它们的实现。

## 2. 字段与真实提供者

| 表 | 关键字段及关联 |
| --- | --- |
| ce_command | 原初始command_id、device_id、origin；automation绑定已applied的prep_key/receipt_id，manual两者为空；binding_body保存完整原admission/run/grant绑定 |
| ce_exit | 不可变exit_id、device_id、controller_boot_id、worker_boot_id、ipc_session_id、device_session_id、clock_domain_id、descriptor_digest、runtime_binding_body |
| ce_attempt | attempt_id、原command_id、authorization_body、attempt_body；登记不等于已发送 |
| ce_packet | packet_id、attempt_id、exit_id、primitive_id、packet_body；BODY包含原设备会话、writer/socket域、不可变字节/hash/长度、协议包标识及profile，不能跨命令合包 |
| ce_permit | permit_id、packet/attempt/exit复合绑定、issued_revision、ordinal、kind、parent_permit_id、permit_body；线上U20进库存20位补零，不原样上网 |
| ce_transmission_commit | 与permit双向配对；guard_body、budget_charge_body、dispatch_intent_body和audit_body同一行，不允许孤立许可提交 |
| ce_report / ce_settlement | 原permit/exit的追加证据；核销分never_sent与effect_resolved。never_sent必须引用明确未发报告，不能覆盖已有transport_entered |
| ce_retirement | 原exit_id及监督证据；证明出口退役，不证明设备未执行或资源已释放 |
| ce_fence | 固定fence_id、protection_id或close_id二选一、issued_cut_revision及cut_body |
| ce_target / ce_item | 全部目标出口及ledger_digest；逐permit保留exit和切点entered_known，不使用“最新worker”替代历史集合 |
| ce_queued | 尚无attempt的原command及拒绝原因；永久阻止该命令后派，不伪造设备执行结果 |
| ce_cut_commit | 切点的audit/outbox同一行；与fence双向提交，并由原保护/close提交守卫要求存在 |
| ce_coverage / ce_target_result | 同出口完整覆盖加原始ACK或退役证据与审计，一出口一事务封存；不等齐全部出口才持久 |
| ce_application | 全部出口结果齐备后的固定receipt、audit和保护结果outbox；不写settlement，不释放资源 |

所有表append-only，连接必须开启foreign_keys和recursive_triggers；禁止UPDATE/DELETE/REPLACE。BODY非空只保证记录存在，真实身份、完整摘要、协议字节、权限、许可时限、预算计费与证据真实性必须由具名可信提供者验证。合成BODY通过不是这些验证已完成。SQL主键也不替代SDK完整词法校验。

单一Controller writer必须先登记所有发送出口；未登记出口永不可获取设备写句柄。监督器准入、唯一发送出口和完整OPEN_GATE快照共同保证该前提。直接读取SQLite或任意插入一条permit不构成发送授权。

## 3. 原子写集与屏障顺序

1. **T1受理**：原裁决/初始命令/容量预留、ce_command投影、原审计通知共同提交。没有自动化投影便不能提交accepted；运行拒绝下界也在本事务重查。
2. **T2传输登记**：复核完整guard、权限、会话、时限、资源和预算；首次按需写attempt/packet，再写ce_permit及ce_transmission_commit。许可与审计/意图/预算记录同事务。SQL仅约束预算BODY存在，真正预算余量/计费关联仍待统一提供者和完整DDL。commit成功后唯一出口至多发送该许可一次；不从此表扫描重放动作。
3. **P2拒绝与冻结**：BEGIN IMMEDIATE内写原保护请求或close、共享deny、来源target容器，再写固定fence、完整targets/items、queued阻止和cut_commit，最后写来源commit。出口、permit和queued与实时登记视图做双向EXCEPT；高水位必须精确相等。seal至来源commit之间禁止新增会改变集合的登记事实。漏一出口/许可、错来源集合、错entered快照均整体回滚。
4. **P3逐出口**：鉴别原出口身份和ACK/监督证据，写完整coverage，再写target_result及审计同事务。已持久单出口in_flight立即参与保守归类；其余出口未回执不使强证据暂时失效。
5. **P3汇总**：全部target均有固定结果且coverage完整，才单独写application与回执/审计/outbox。外部applied必须引用本提交。原准备closed仍需真实应用引用提供者核验；旧cp_completion的非空BODY并未由本候选补成完整外键链。

ce_expected_target包含匹配run/代次准备设备上所有未可靠退役的历史出口，以及仍有未核销许可的退役出口。ce_expected_item包含匹配来源且generation不高于floor的全部未核销传输。手动命令和其他origin/run不纳入运行许可集合。未开始attempt的已终止命令若仍在候选登记中，保守保留queued阻止事实，不由它改写原终态。

本候选每切点最多256出口、每出口256许可，超限拒绝整个事务，不截断；这只是存储候选上限，运行必须提前预留完整保护容量/P0应急通道，不能等到保护时才发现超限。P0容量及GC不是本轮已实现内容。

## 4. 原始覆盖与后到证据

切点已知进入transport的许可，任何出口结果都不能降为unknown或not_sent。退役证明只允许unknown或已有in_flight，不能凭新worker或组空返回not_sent。

当切点尚不知道发送结果，原ACK的覆盖快照保持不变；后到更强证据另写ce_report。当前归类按“任一可信transport_entered优先，其次可信not_sent，否则unknown”。晚到transport_entered使此前never_sent核销不再排除该许可，重新列入未决；随后如有真实无后效证明可另加effect_resolved。证明真实性及矛盾证据告警由提供者负责，不能吞掉矛盾。

最后一次重传未发只核销它自己的permit；原packet先前已发送许可仍未决。application只证明阻止后续发送和完成覆盖归档，不能清除既有设备影响。effect_resolved也不是命令成功或允许自动补发。

## 5. 故障与恢复

| 故障时点 | 持久结果与恢复 |
| --- | --- |
| T1/T2提交前 | 整个写集回滚；不能投递未提交许可 |
| T2提交后、发送前崩溃或提交结果不确定 | 先查原记录；没有可靠原出口未发证据就保留unknown，不能自动补发 |
| P2 seal后、来源commit前异常 | 原请求、deny、切点、queued、outbox整体回滚；已有更强deny不回退 |
| P2提交后、保护消息丢失 | 查同一固定cut并继续保护投递，不能重建不同集合或换回低floor |
| 一个出口ACK落盘后核心崩溃 | 重开读取已封存target_result，其余出口继续核对；已知in_flight仍保留 |
| 全部出口已落盘、汇总前崩溃 | 只补固定application事务，不再执行设备动作 |
| application后响应丢失 | 查原回执，不改覆盖或重新核销 |
| worker退役、新IPC连接建立 | 旧许可仍属于原exit；新出口必须加载完整deny，不能代旧出口证明未发 |

当前一个来源保护操作对应一个不可变cut；同cut的多次屏障尝试、worker缓存丢失后的新barrier_id/生效tick、完整IPC重传字段仍待下一版明确，不能声称当前表已覆盖该恢复路径。重启默认关闭；无法重建原屏障证据时保留unknown并走监督退役/人工核对。

## 6. 验证范围与下一步

[check_fence.py](check_fence.py)只打开内存数据库，显式给出目标集合及预期，不从待测expected视图生成预期。覆盖T1/T2/P2/单出口结果缺写、逐步主动异常及46表全库回滚，双保护入口、空目标、queued、历史出口遗漏、错高水位、单出口强证据、迟到证据、退役、逐primitive/逐重传和手动隔离。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_fence.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_fence.py --check-report --staged
```

报告绑定完整依赖输入；字节核对不重跑。内存SQLite不证明真实并发、WAL、掉电、网络、IPC、身份提供者或设备。实际引擎版本记录在报告中，不作为产品批准版本。

剩余冻结项：统一命令终态/资源与全部类型屏障DDL、真实guard/预算计费映射、同cut屏障尝试及C11逐传输IPC字段、P1/P4与P0/GC、SDK同版归并和真实提供者。DM3等多步骤动作沿用相同逐primitive登记原则，具体协议资格与效果证明继续归音频契约，不由本存储层授予。
