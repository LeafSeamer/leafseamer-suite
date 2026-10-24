# 最终准入封存字段与事务边界候选

状态：`approved=false`，内部版本`final-admission/0.1.0-draft.1`。交付[字段生成器](build_final_admission.py)、[Schema](final-admission.schema.json)、[跨原件检查](final_admission_model.py)、[向量](check_final_admission.py)和[报告](final-admission-report.json)。本批不更改HTTP或IPC接受版本，不解除四个临时最终签发守卫，不启动业务实现。

## 已知事实与本次方案

现有设计已明确编码授权先于最终Guard，普通首次hold与传输在同一个T2写集生成，保护取消使用独立执行hold。现有`FinalizationLink`仅是顺序实验投影，缺完整封存格式；238表布局仍以四个`cu_*_gate`守卫阻止最终许可及提交。因此固定库存的prepared/观察正例不能作为完整发送链证据。（来源：[编码授权](../c08-controller/ENCODING_AUTHORITY.md)、[最终准入设计](../c08-controller/FINAL_ADMISSION.md)、[238表布局](controller-attempt-inventory.sql)。）

本次方案将最终封存的固定字段、每个输入的原件身份与读取切点明确列出；为普通与取消分别建立完整角色集合。跨原件检查只证明这些对象相互一致，返回`cross_object_binding_valid`。该结果不证明授权、来源真实性、完整参数合法性、资源安全、NTP误差或预算足够，也不是可发送凭据。四个阻断只有在同版完整SQL写集和全部准入判定接通后才能替换为等价守卫，不能先删除再补。

## 封存字段

| 字段 | 精确含义 |
| --- | --- |
| seal_id/revision/format_version | 内部封存身份，revision固定1，不能覆盖或补写历史 |
| transaction_id | 本Controller唯一writer的一次T2事务身份；重试必须重新读取切点，不能借另一事务投影 |
| binding | 完整scope、Controller/worker/IPC/出口/设备会话及受监督时钟域 |
| identity | 既有ExecutionIdentity；普通用command/attempt，取消用command/cancellation/execution，Requester取实际当前请求来源 |
| command_state_ref | 本次读取的命令前态；取消不要求父命令恢复为pending |
| permit_id/transmission_id/issued_revision/ordinal | 本次许可及传输身份、全局issue直接后继、包内逐传输序号；Counter为严格十进制字符串，支持超过2^53 |
| transmission_kind/previous_permit_ref | initial的ordinal必须0且无前驱；protocol_resend绑定完整前一封存Ref，并取得新许可、传输身份、Guard、PermitAuthority和预算 |
| packet_ref/encoding_packet_ref | 前者为packet_id/packet_digest，后者为编码记录三元Ref；必须显式映射，不能混用两种格式 |
| hold_ref/hold_transition | create仅允许普通initial；普通复用及取消必须保留完整前后hold集合。create时仅增加本次hold，不得移除或重标旧风险 |
| inputs | 下表具名投影Ref，完整id/revision/digest；普通18项、取消额外3项，条件字段必须明确null或Ref |
| selected_tick_ns/sealed_tick_ns | 同一受监督域的选取与最终封存采样；封存前须重新判定，不接受客户端时间 |
| send_window | `not_before=max(各下界)`、`before=min(各上界)`，半开区间；允许提前封存等待计划窗口，但授权、闸和预算本身必须在封存时已有效，且不能已到before |
| seal_digest | 只排本对象顶层seal_digest后JCS；不包含自身提交观察、未来ACK或SEND_REPORT |

输入Ref指向本地**归一化投影记录**，不冒充原领域正文的Ref。记录封闭为`role/ref/source_ref/scope/transaction_id/body`；投影摘要覆盖除ref外的全部字段，包括原source_ref、角色和读取事务。原领域摘要仍按其具名投影规则核验，不能把“对完整原件再次SHA”当作原领域self-digest。`body`按每个角色分别闭合，保留完整binding和本次identity；该identity表示本次消费主体，资源列表中的旧OwnershipRef仍指旧主体，不能据此重标旧hold。投影器必须从实际原件导出这些字段并验证当前资格，禁止HTTP、worker或插件提交投影即被当作可信来源。

## 输入原件、所有者与重核责任

| inputs角色 | 当前事实来源与必须补接的责任 |
| --- | --- |
| origin | ca_request_key/ca_adjudication和普通执行/继续运行来源；取消取自身取消RequestKey与cg_plan，不借父actor |
| capability | 批准能力、参数Schema、primitive计划与编码profile；须证明编码采用的是原命令固定参数，不只比较字符串版本 |
| encoding | ep_reply与ep_receive_commit的完整成功原件及不可变字节；绑定授权、prepare、原请求/响应、packet记录、当前出口与TTL |
| authorization | 当前凭据、对象范围、批准能力与用途交集；人员、service、面板等分支各走已定义来源，不能从origin标签猜权限 |
| control | ct_current_state/go_authority；pending操作拒绝，完整holder及epoch/version与Ownership/PermitAuthority/Access一致 |
| gate_commit/gate_access | 普通go_ready或取消gs_scope_commit及其实际Access；当前打开的闸与精确执行范围匹配，不能仅有历史OPEN_ACK |
| ownership | ow_record/ow_commit及原来源回执；hold归属不因控制权返回同一人而更新 |
| permit_authority/guard | 本次完整主体投影与最终Guard；引用先前独立原件，不反向引用Seal，Guard ACK在T2之后 |
| budget | 同次传输新扣费原件，含本permit与全局issue；不得拿父许可的扣费回执供重传复用，不因ACK失败自动退款 |
| time | 本次传输的单调截止及按需reference-bound证明；普通排期、条件年龄和能力要求与取消独立时间政策分别求交，不能借父排期或OS UTC |
| resource_before/resource_after | go_snapshot与真实风险hold全集；前态用于开放基础，后态用于本次新增hold封存；全部旧成员、分类和归属不得丢失 |
| resource_safety/gate_safety | 各自当前安全代次；普通分配只变resourceRef，不能借本次签发抹去已推进的安全代次 |
| run_deny/command_deny | 当前完整拒绝快照与实际来源绑定；版本相等只是绑定条件，仍须执行适用的拒绝集合判定 |
| ordinary_closure | 仅取消：cc_valid_closure的ordinary关闭原件；还须确认all未关闭、Plan未停止 |
| protection_assessment | 仅取消：gs_assessment及批准策略；绑定完整后态风险，父unknown保持原样，无关风险继续阻断 |
| primitive_dependency | 仅取消：当前primitive及全部祖先成功/撤回链证明；不是只检查紧邻前驱，必须属于同执行与本次传输 |

上表的物理位置依据现有[范围存储](../c08-controller/scope-storage.sql)、[归属存储](../c08-controller/ownership-storage.sql)、[编码存储](../c08-controller/encoding-storage.sql)与[最终准入](../c08-controller/FINAL_ADMISSION.md)。Schema中的投影字段是待落实的本地适配契约，不宣称这些现有表已经输出了该投影。精确提供者、时间政策计算和设备/扩展适配不能以投影字段齐全替代。

## 无环写集与三个重核时点

1. **T2封存**：BEGIN IMMEDIATE读取命令前态、控制及完整资格。分配全局issue、逐传输扣费，普通首次创建hold/Ownership，复用路径核原归属。写完整Guard、PermitAuthority、传输、后态风险快照和Seal；全部新行及公开命令修订必须同事务闭合。Seal引用的Guard尚未安装，不要求未来ACK存在。后续DDL必须用延迟关系保证每个issue恰有一个Seal、每个Seal恰有对应ordinary/cancel传输提交，漏写、重复和末尾撤回均失败。
2. **Controller入流前**：只有可靠确认committed，才进入当前资格复核；比对运行域、会话、控制、撤权、拒绝快照、两安全代次、范围及原字节。安装Guard，精确ACK可靠保存后，再选DISPATCH/RESEND_DISPATCH。原编码TTL是T2采用约束，已封存后不能把过期当成重发许可；实际发送仍按原窗口和当前撤回判定。提前封存不能在not_before之前入流。ACK等待不得持有写事务。
3. **worker写前**：在同一设备仲裁器中复核当前Guard、闸/范围、会话、各保护及实际tick，再消费一次permit并调用I/O。新保护先到则拒绝；设备调用先到则保留可能已发。不能将Controller提交或入流作为设备未发的证明。已入流前缀遵守[有序出口](../c08-controller/GATE_ORDER.md)的传播窗口。

`CommitObservation`向后引用Seal，字段为observation_id、transaction_id、scope、seal_ref、permit_id、outcome、observed_tick_ns、observer_ref和observation_digest。committed只转入`committed_requires_recheck`，rolled_back为`no_issue`，unknown为`quarantine_lookup_only`。观察来源必须是本地writer/存储恢复器；网络回复不能自行证明提交。相同事务结果未知时只查原，不重试设备动作；重启后查到旧提交仍不得重放许可、Guard或OPEN。

## 故障与验收边界

本批167项离线检查验证普通/取消、手动/自动化及重传的8个正例，重算摘要后错事务/错scope/错主体、跨控制代次、漏旧风险/重标父unknown、重复hold、范围错用、packet格式错配、逐传输预算、超过2^53的issue、窗口交集/截止等号、编码在封存前过期、提交未知与未来ACK引用拒绝。普通提前封存的正例仍要求最终两端等待窗口，未把它当作设备执行。

本批检查的是归一化投影之间的关系。所有本地提供者同时伪造而保持一致仍能通过，是明确限制反证；不能把该检查器直接包装成生产`can_send()`。单个投影没有字段表达完整授权/拒绝/预算/时间策略，完整原件由source_ref另行解析和判定，这些判定须在三个重核时点按职责执行。

仍需完成：各角色从原领域Schema/实际行的完整投影器及提供者鉴权；seal/issue/hold/budget/传输/公开修订的同版DDL与writer；按原SEND_REPORT生成固定库存的实际SQL完整正例；提交未知、并发撤权及真实WAL恢复；最终唯一出口与worker的完整时序测试；SDK归并、平台、OBS及其他设备验收。当前四阻断原样保留，阶段0未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_final_admission.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_admission.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_admission.py --check-report
```
