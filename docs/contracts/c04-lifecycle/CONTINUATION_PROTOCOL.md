# 继续运行内部API与引用衔接候选

状态：`approved=false`，协议`run-continuation-http/0.1.0-draft.1`。本轮将[三库参考链](CONTINUATION_TRIGGER.md)落成[具名Schema](continuation-protocol.schema.json)、[Controller OpenAPI](continuation-controller.openapi.json)、[Seamer OpenAPI](continuation-seamer.openapi.json)、[参考投影与校验](continuation_protocol_model.py)及[离线检查](check_continuation_protocol.py)。旧原件`run-continuation/0.1.0-draft.1`逐字段复用，公共draft.4／IPC0.3及旧API保持原版。

## 已知事实与设计判断

已知事实：现有转交Request/Receipt/Adoption与SQL均使用`scope/id/revision/digest`引用；公共准备/命令中的部分引用还含`kind`并使用`object_id`。原`transition_commit.commit_digest`只摘要其`commit_body`，不覆盖整行；转交Request.actor没有issuer_epoch。[原件源](build_continuation.py)、[持久writer](continuation_storage_model.py)、[公共准备](../c04-preparation/preparation.schema.json)及[命令身份](../c02-admission/admission.schema.json)提供这些事实。

基于这些事实，本候选保留原件格式，显式定义引用转换和认证提供者要求。不同格式不得直接互换，局部摘要不得升级成整份提交证明，人员字段不得成为请求自授身份。当前SQL投影可验证原件关联；HTTP、中间件、远程权威查询和真实身份隔离尚未实现。

## 八个内部操作

路径前缀均为`/internal/automation/continuations`，在各自服务上独立解释。所有请求必须有精确`X-LeafSeamer-Contract`，所有响应`Cache-Control: no-store`。mTLS服务身份还须配对关系、当前权限、origin归属及目标数据库身份，OpenAPI security声明不替代实现。

| 服务及POST后缀 | 输入与输出 | 权限；结果与重试 |
| --- | --- | --- |
| Controller 空后缀 | IssueInput → ControllerRecord | automation.prepare；201首次持久签发、200原件；未知后只查原 |
| Controller /lookup | LookupInput → ControllerLookup | automation.prepare.read；200查询，不写、不补签 |
| Seamer 空后缀 | IssueInput → SeamerRecord | automation.continuation.manage；201登记、200原件；无grant或R5含义 |
| Seamer /lookup | LookupInput → SeamerLookup | automation.continuation.read；200本地一致快照，只供所属origin |
| Seamer /receipts | ReceiptInput → ReceiptAck | automation.continuation.notify；配对的签发Controller仅报告自身原件；201记录、200原件，不返回其他Controller回执 |
| Seamer /adoptions | AdoptionInput → SeamerRecord | automation.continuation.manage；201完整采用、200同采用；当前完整资格和CAS须再核 |
| Seamer /finish | FinishInput → SeamerRecord | automation.continuation.manage；201原R5持久完成、200同R5；未知后查原，不能重跑恢复动作 |
| Seamer /withdrawals | WithdrawalNotice → WithdrawalAck | automation.continuation.protect；202已记撤回与保护计划、200同通知；允许同身份保护重投，不表示保护applied |

IssueInput含`protocol_version,target_scope,request`；ReceiptInput与AdoptionInput同样封装对应完整原件。LookupInput含`protocol_version,identity`，TransferIdentity精确为`target_scope,origin_scope,transfer_id,request_digest`。FinishInput另含`adoption_ref`，必须解析成该transfer的已持久采用，不能由调用者指定另一个release或execution。版本头和外层protocol_version都不得从旧原件版本猜测。

所有写入口先校验当前读取授权和对象归属，再查不可变身份。相同原件可在旧动作授权失效后返回历史；没有原件才执行新写入的当前授权/时间/容量/审批和原写集检查。参考`validate_issue`专门检查新签发，不替代此查原分支。相同身份换完整正文或摘要409，不能换ID绕过同run/generation唯一约束。未找到只描述本次读取，不是永久拒收证明；存储不可读为indeterminate，不能伪造not_found。格式/鉴权/容量错误及503均不证明请求永远不会生效。

IssueInput的JCS上限270336字节，其他请求20480字节，单响应1048576字节；内层Request仍262144字节、Receipt/Adoption仍16384字节，原Controller/设备数量上限保持。网关还须在JSON解析前限制原始字节，完整输出超过上限返回容量错误，不能截断回执数组。这些是候选profile，未作生产容量承诺。

## 身份与提供者边界

origin类操作的实际配对调用者必须属于Request.origin_scope；Controller通知则必须来自对应controller_scope，Seamer根据本地rc_target解析registration_id，不接受客户端指定本地注册键。所有查询在读取前及响应释放前核当前权限，不能凭历史grant、相同用户名或请求里的actor返回数据。

Request.actor是审批归属信息。新签发的可信namespace提供者须将`request_epoch`唯一解析为`issuer_id,issuer_epoch,principal_id`及有效状态，再与不可变审批人员原件比较；epoch变化不能默认继承。同代次转交身份还受origin数据库与run/generation约束，不能因换epoch重签。该提供者须有持久发行历史与永久拒绝边界，现有SQL未建立这份身份注册表；本轮测试提供合成上下文，不能据此关闭身份生命周期缺口。历史读取只要求当前读取权与真实历史归属，不强求旧审批或namespace仍active。

Seamer投影包含Request、按Controller scope排序的已观测Receipt数组、可空Adoption和可空FinishRecord，所有投影固定`qualification=not_asserted`。Adoption非空时必须收齐全目标；Finish非空时必须有Adoption及实际R5封存原件。历史R5即使随后撤权也不改变，禁止GUI据found/finish直接显示当前可运行。

FinishRecord明确为`commit_id,execution_id,adoption_digest,commit_body_digest`。最后一个字段只表示原commit_body摘要；跨服务最终发送还须通过可信Seamer提供者读取完整执行/采用/R5原件，不能拿这个局部摘要作为所有提交列的完整Ref。普通CommandContent仍按原规则只去顶层运输字段，授权引用和动作参数必须参与最终摘要。

## 撤回通知与命令引用

WithdrawalNotice含TransferIdentity、controller_scope、receipt_ref、revocation_ref和notice_digest。notice_digest是排除自身字段的JCS SHA-256；revocation_ref指向该Controller的实际cr_revocation原件。参考投影将原件BLOB逐字段转为小写hex，再以JCS摘要，包含transfer_id及原proof/audit/outbox完整字节；不得改成只摘要proof_body。该投影没有暴露原proof正文，真实传输必须由可信查询提供者取证。

Seamer验证通知与实际原件完全相等，解析本地registration，再调用已有带预算撤回writer。同一事务封存cn_withdrawal、PQ完整计划及实际差集预算，成功后才返回WithdrawalAck；ack仅含通知身份、摘要和protection_plan_id，固定recorded/not_asserted。重复通知返回同ack且不重复扣账。ReceiptAck同样仅证明该Controller回执已记录，activation固定not_asserted。通知丢失时Controller本地已拒绝新受理/attempt；Seamer通过可靠重投/查原收敛，恢复、接管和在途完成仍走原保护协议。通知不提供新的设备操作或复活grant接口。

CommandGrantBinding从实际submission、cn_step、Receipt、Adoption和R5产生，包含origin_scope/run/generation、execution/step/submission/device，以及transfer/adoption/receipt/grant/plan六类明确引用。内部registration_id留在Seamer。转换公共Ref时必须由调用点固定语义：grant_ref→kind=grant，计划/采用等只有在真实制品提供者注册后才可转换为kind=artifact；id映射object_id，其余字段原值保留。不得猜kind或把局部R5摘要映射为完整artifact摘要。

本轮只交付这些引用的具名候选与SQL投影，没有直接向旧CommandRequest塞入continuation字段。统一版必须将CommandGrantBinding归入execution_binding_ref解析的不可变正文，更新ExecutionBinding/Guard/Permit/Intent及SDK同版来源，并重算完整命令摘要。现有旧对象`additionalProperties=false`继续拒绝额外字段，旧recovery grant仍不得用于新execution。该归并是下一项明确交付，不能凭本轮两份OpenAPI宣布公共命令或SDK已经统一。

## 故障与验收

| 场景 | 必须结果 |
| --- | --- |
| 签发持久成功后丢响应 | 当前有权查同原件；不重签，不换ID |
| 部分回执、已采用未R5、R5后撤权 | 三种历史投影明确区分，均不自带当前执行资格 |
| issuer换代、冒充origin或别的Controller | 即使原件摘要正确也拒绝；读/写均核范围 |
| 伪造撤回Ref并重算notice_digest | 权威原件比对失败，不写PQ、不扣预算 |
| 撤回提交后丢ACK/重复通知 | 查询或重投同原件，保留同计划，预算只扣一次 |
| 无法读取持久库、半份采用/R5或错摘要 | 不产生成功原件或伪not_found；保留未知并报警核对 |
| 引用字段同名但不同kind/摘要范围 | 拒绝隐式转换，保持未解析，不开放最终出口 |

离线报告见[验证结果](continuation-protocol-report.json)。检查包含完整Schema/OpenAPI、缺字段/额外字段、实际三库登记→签发→采用→R5投影、身份反例、撤回原件对接和重复扣账、实际普通提交引用；合成认证条件不能证明真实鉴权。未运行HTTP、网络乱序、权限撤销竞态、服务、磁盘崩溃或设备。阶段0未关闭，下一步继续同版执行绑定归并、身份提供者与完整容量方案。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_continuation_protocol.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_protocol.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_protocol.py --check-report
```
