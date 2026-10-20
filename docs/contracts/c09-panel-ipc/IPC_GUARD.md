# 面板执行绑定与精确撤销 IPC 候选

本稿衔接[C09 PD05](../../rebirth-c09-extension-design.md)、[HTTP与事务](../c09-panel-service/HTTP_STORAGE.md)及[F04/F05](../../rebirth-f04-f05-design.md)。候选版本`ipc/0.4.0-panel-draft.1`不是已确认的新公共基线；旧draft.4／IPC0.3、channel0.2及HTTP候选文件保持原字节。本轮只交付设计、机器格式和离线检查，不实现业务worker或网络服务。

## 1. 原基线缺口及本轮范围

当前ExecutionGuard仅有人员／服务授权绑定，RevocationSelector只有session/principal/credential/grant/extension/trust；它们不能唯一识别同一安装打开的两个页面。原IntentRef也没有ipc_session_id和controller_boot_id，不能单靠worker_boot_id判断“新连接从未收到”是否等于原连接未发。（来源：[固定公共源](../df01-source/source/public.schema.json)、[IPC源](../df01-source/source/ipc.schema.json)。）

本轮给出完整19帧的候选IPC，使用新版本及必选特性`panel_execution_binding`、`panel_scoped_fence`。新增特性缺失即保持关闸，禁止向旧worker降级发送面板命令。模型生成源为[build_contracts.py](build_contracts.py)，生成[binding.schema.json](binding.schema.json)与[ipc.schema.json](ipc.schema.json)。未变领域模型继续引用固定旧源；新公共版本的整体迁移另行归并。

## 2. 从受理来源到唯一发送出口

ExecutionGuard增加`admission_origin=panel|non_panel`、`panel_binding`。non_panel必须null，panel必须完整PanelExecutionBinding：

| 字段 | 来源与约束 |
| --- | --- |
| context | channel0.2 Guard：panel_session_id、document_generation、panel_delegation_ref、installation_ref、approval_ref、auth_session_id、完整request_identity及activation_ref |
| principal_id、extension_instance_id | 当前human主体及已批准模块运行实例；分别匹配AuthorizationBinding.principal_id与extension_instance_id |
| artifact_digest | 原安装批准的固定制品摘要，不能由模块自报新版本替换 |
| scope_ref、policy_ref | 受理时固定授权范围与策略；scope revision必须等ActivationRef.scope_revision |
| lease_revision、lifetime | 原受理记录的租约修订、同域hard/lease deadline；接受之后的renew不改写旧绑定或延长旧许可 |

这个完整对象的JCS SHA256为`panel_binding_digest`，使用`sha256:`前缀。其内部channel引用沿用原裸hex，不能混淆或统一去前缀。Guard摘要是完整Guard去掉**顶层**guard_digest后的JCS SHA256，新增字段必须参与；不能递归删除同名业务字段。Permit和IntentRef新增同样的admission_origin与nullable panel_binding_digest；GUARD_ACK回显panel_binding_digest。DISPATCH仍通过permit和guard_digest绑定完整Guard，不再复制另一份panel payload。

admission_origin来自authority已经持久化的受理来源，不接受客户端选择。签发许可时读取原request／command映射；若它来自面板，不能将panel_binding改null并重算摘要来伪装成non_panel。worker安装时核对可信入站许可快照、Guard及摘要，最终发送前再检查同一缓存Guard和许可；独立组织automation合法使用non_panel，其来源不能从某个GUI登录会话继承或被普通关闭撤销。

panel绑定要求AuthorizationBinding为human、manual、有人员session、无grant／arm；issuer/epoch、audience、principal、auth_session、extension实例、批准revision、安装／批准／scope／policy的authority与database必须相互一致。安装实体ID与运行实例ID是不同概念，不要求字符串相同；authority保存批准到实例的关系。reference-check的“权威快照”由合成夹具给出，不能当作实际数据库或权限证据。

生命周期期限与Guard的clock_domain_id／descriptor_digest一致。最终发送要求now严格小于authorization_deadline、panel hard、panel lease及原send_window.latest，且满足所有既有设备／接管／资源／NTP条件；等号拒绝。旧许可不能借新租约、重发GUARD_INSTALL或新页面激活延长。若原受理绑定在排队期间到期，保持原请求记录并按领域失败规则处理，不自动换身份受理。UTC显示不是worker延长许可的依据。

## 3. 两类面板selector与安装、人员撤销

RevocationSelector候选为旧六类与以下两个封闭分支的联合：

| kind | 精确字段与拒绝语义 |
| --- | --- |
| panel_session | authority_service_id、database_instance_id、issuer_id、issuer_epoch、auth_session_id、panel_session_id、document_generation；命中后该挂载永久拒绝新执行，没有可用更高revision复活的入口 |
| panel_delegation | 同一完整挂载身份，再加delegation_id、revision_floor；匹配委托revision < floor时拒绝，等于floor只是未被本下界拒绝，仍需全部当前授权 |

revision_floor是最低可接受新修订，禁止写成<=；面板关闭使用永久panel_session selector，不能仅抬高委托revision再把同页面放行。selector的规范摘要是完整selector的JCS SHA256，含kind及完整权威身份，使用sha256:前缀。对象ID不可复用，跨database恢复不命中旧许可也不说明旧副作用不存在。

原session selector的target_id仍指human auth_session，不改成panel_session。普通关闭仅命中一个完整挂载；同安装第二页面或独立组织run不被误撤。安装／批准撤销在authority按索引枚举全部受影响面板，生成对应永久selector；后台模块沿原extension selector另行关闭。这个fanout与目标注册／许可签发必须在同writer串行，缺完整归属时扩大为保护性CLOSE_GATE，不能靠漏项声称精确撤销完成。安装fanout与全部后台领域模型的持久表仍属于后续完整DDL。

已认证的精确关闭下界先禁止新工作，即使持久化暂时失败也不在内存回滚开放；对外acknowledged／applied仍必须可靠保存。新连接先同步当前拒绝集合，再允许安装Guard和OPEN_GATE。旧“active”或旧GUARD_ACK不能降低拒绝下界；重复安装同Guard只核对，不再次执行或刷新截止。

## 4. AUTH_FENCE及完整覆盖

沿原信封绑定controller_boot_id、worker_boot_id、ipc_session_id、device_id和运行域，AUTH_FENCE与ACK新增selector_digest，并支持新selector联合。目标仍逐设备／worker／连接世代核对，不以某一ACK替代全部目标。AUTH_FENCE没有改变control_version或holder，也不恢复暂停的组织run。

IntentRef除原permit/command/attempt/dispatch_intent/worker/device_session/guard/domain字段外，增加controller_boot_id、ipc_session_id、device_id、admission_origin、panel_binding_digest。完整未核销清单包括旧连接和旧worker的许可。Controller按原Guard摘要及持久绑定判断selector是否命中，并冻结切点、匹配清单与ledger_digest；不能信worker自选清单。ledger_digest继续为按permit_id升序的完整IntentRef数组JCS SHA256，重复permit直接拒绝。较大账本不得截断；256项预算在签发前预留，超限走保护，不把分页未齐算完整覆盖。

| 顺序／证据 | ACK coverage分类 |
| --- | --- |
| 同当前完整发送世代、屏障先安装且确定从未接收 | not_sent / never_received |
| 同当前完整发送世代、已接收但可靠未消费 | not_sent / discarded_unconsumed |
| 已进入设备传输 | in_flight / transport_entered |
| 无法确定或属于旧controller／worker／IPC／device_session／运行域 | unknown / send_uncertain，不能由新进程自证未发送 |

ACK coverage必须恰好覆盖固定清单、每个完整IntentRef相等；invalidated_permit_ids恰为not_sent集合，in_flight和unresolved为对应command_id去重并集。同一command的不同permit可使其同时出现在两者，不能互相抵消。applied_authorization_revision不得低于目标修订；收到更高修订也不能改变原operation、barrier、selector、切点和ledger摘要。已经可靠记录transport_entered的许可不得被never_received降级。

ACK只证明该目标出口已经应用拒绝并交付覆盖快照；worker无本地权威库，因此不新增一个自报durable=true来替代Controller提交。服务验证并持久化ACK、selector、覆盖、audit／outbox后才能更新HTTP逐目标evidence_ref。HTTP acknowledged仍不等于设备停止、控制ready或资源释放。ACK冻结后的迟到完成报告以独立证据入账，不能改写原coverage摘要；新worker发来的旧世代ACK只可作历史资料，不能让当前目标完成。

重连同一worker_boot_id仍须新ipc_session_id，原连接许可已失效；EOF后没有“续传旧DISPATCH”机制。新worker导入旧未核销账本，只能保守unknown；监督器的旧进程终止证明另行关联，证明进程已死也不证明设备未执行。接管FENCE／TIME_FENCE的Coverage引用同样使用扩展IntentRef，避免面板路径成为账本遗漏入口。

## 5. 崩溃与故障时序

1. PS6关闭事务已提交、IPC尚未送达：本地拒新受理和签发，目标仍pending；预留通道重送同operation/barrier/selector，不能换目标清单。传播窗口内先于屏障到达的发送仍记in_flight，不承诺零窗口。
2. worker已应用屏障、ACK丢失：同会话重复AUTH_FENCE返回冻结覆盖，不重算成空清单；连接失效则重新导入原账本并保守核对。
3. ACK已收、落库失败：不返回durable applied，保护保持；重查原operation，禁止复用旧许可或在HTTP把operation当closed成功。
4. 面板A关闭而B仍活动：只有A匹配Guard被丢弃；B仍需当前接管与资源资格，不能仅因selector不命中就自动发。若A遗留未知与B同资源冲突，B继续受资源保护。
5. 新worker声称未收到旧permit：按旧完整世代拒绝not_sent结论，保留unknown；只有独立可靠核销证据才能解除资源未决。
6. 撤权时读取／投影释放：authority先关闭受影响pending请求、preview及projection出口；它们不是设备permit，不塞进open_intents。HTTP关闭目标须同时覆盖本地释放出口与worker屏障；本批IPC格式不能单独证明服务端订阅已经停止。

## 6. 验证与剩余冻结

本目录参考检查使用人工完整账本、批准和身份快照，实际计算JCS摘要并检查跨对象绑定、精确选择与覆盖集合、两种发送／屏障顺序及迟到消息。不得把合成上下文中的true或哈希提升为真实权威、设备效果或磁盘耐久。原19类消息均有新候选结构正例；旧IPC拒绝，非面板合法路径保留。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-ipc/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-ipc/build_cases.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-ipc/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-ipc/check_contracts.py --check-report --staged
```

[参考报告](reference-report.json)记录102项检查，绑定本目录7输入与固定旧源／通道4输入，共11份原始字节。用例生成物必须重读JSON后再变异，避免Python共享对象引用同时改动“待测消息”和“权威快照”。同command两许可的in_flight与unknown并存、第二页面不在A关闭切点、重算摘要仍错身份、旧连接ACK和完整世代变化均有反例。`--check-report`只检查字节，不重跑；本报告不在顶层旧十份报告清单内。

19帧的旧路径回归只验证新版结构，未迁移原全部语义判定；本批增量检查没有执行真实权限取证、完整资源占用、NTP或发送窗口判定，不可单独用作生产放行器。Guard摘要到持久许可／对象归属的真实索引、selector集合的完整同步及所有写出口覆盖仍需实现后运行取证。

后续运行验收PIF01—PIF08：两页面同设备精确隔离、所有异步协议出口含重传、关闭／发送竞争实测上界、ACK落库故障、同worker重连、进程替换与监督器证明、安装撤销完整fanout、GUI投影和设备目标联合关闭。均未运行。完整SDK版本归并、非面板模块安装归属、撤销/目标索引及订阅出口DDL仍须完成，不关闭全系统设计阶段。
