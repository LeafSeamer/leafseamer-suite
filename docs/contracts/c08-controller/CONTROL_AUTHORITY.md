# 控制权、转交与已预留版本契约

状态：待审阅，`control-authority/0.1.0-draft.1`。这是既有C02/C03与C10缺口的归并候选，尚未替换draft.4、生成产品SDK或实现服务。

已知事实：旧公共契约有六项控制操作，TransferOffer仅用principal_id且未关联接受后的ControlOperation；F02/F03要求pending后冻结旧待发、完整屏障及可靠T4才effective，T5另外建立ready；DF04要求pending/indeterminate单设备排他，普通重启保留持有人。（来源：[旧HTTP](../draft4/controller.openapi.json)、[F02/F03](../../rebirth-f02-f03-design.md)、[DF04](../../rebirth-df04-storage-design.md)、[C10](../../rebirth-c10-gui-design.md)。）

基于这些事实，推荐以下完整身份与版本规则。这里的引用摘要和布尔取证前提不自行产生权威。

## 身份与生命周期

- 人员身份为`issuer_id/issuer_epoch/principal_id`完整三元组。持有人、邀请发起人与目标均用该身份；会话和GUI实例不成为持有人身份。退出、会话过期及邀请过期均不释放控制权。只有有权人员使用可信宿主发起控制操作，service不能借manual接口接管。
- RequestKey为`target_scope + issuer_id + issuer_epoch + principal_id + request_epoch + operation_id + idempotency_key`，不含context_id或内容摘要。控制请求的operation_id使用本候选的HTTP符号；不能把createCommand命名空间直接挪用。服务从已认证上下文取得身份、scope和request_epoch，不接受客户端自填权威。
- RequestReceipt不可变，保存完整身份、规范内容摘要和初始资源Ref；重复请求先验证当前读取权限、主体/命名空间归属与规范内容，再查原结果，最后才考虑新操作的CAS/TTL。不同摘要同Key冲突，旧结果不能因当前版本改变而重做。lookup不受理新工作，not_found不许可更换键重试。
- ControlRecord增加`reserved_version`；`effective_version <= reserved_version`。每次新pending在T3预留`reserved+1`，旧pending重建屏障沿用原目标版本。失败后预留号仍消费，后续新操作可以跳过版本，绝不重复使用可能已到worker的版本。达到U20上限需维护，不能回绕。
- `pending/indeterminate → effective`仅在该操作仍占设备pending槽、原期望持有人/epoch/生效版本未被替换、当前目标授权有效且完整屏障可靠提交时发生；`effective/rejected`为操作终态。indeterminate只表示尚不能确定，不清pending槽。目标授权失效可显式拒绝并清pending，但闸保持protected，reserved不回退，旧持有人只是历史有效限制，不能因此继续写。
- 同设备至多一个pending或indeterminate，包括紧急接管；竞争返回409。紧急权限允许抢占已生效持有人，不允许绕过未决屏障。未来若增加未决操作替代，须另立带完整旧出口核对的协议，首期不隐式覆盖。

## 转交与期限

TransferOffer固定`transfer_id/scope/device/from_principal/target_principal/expected_control/lifetime/reason`；状态`offered/accepted/expired/cancelled`，accepted必有不可变`accepted_operation_id`。每次修改保存新revision/digest，接受后邀请不再因TTL变成expired。对邀请的接受只发生一次；另一请求键的再次接受409，同键查原Receipt。

Lifetime由Controller当前受监督域的`clock_domain_id/descriptor_digest/issued_tick_ns/expires_tick_ns`提供。接受条件是同域且`issued <= now < expires`；普通重启若域确实仍可证明可比较，可以按原期限检查，换域或不可证明则旧offered标expired、reason=clock_domain_changed，不用新域tick换算续期。相同控制epoch和持有人仍保留。绝对UTC显示由参考时钟计算，不能代替单调期限；GUI展示缺参考UTC时允许null并标unavailable，不因此阻止即时人工接管。这里不新增NTP依赖。

`offer_ttl_ms`继续接受旧Duration的1至86400000范围；这是契约接受界，不是推荐用户保留一天的邀请。调用方可选更短期限，服务器容量/租期profile后续不得无版本说明地缩窄既有接受集。force缺省按false进入规范内容，显式false与缺省值相同；紧急抢占另核非空理由和独立权限。

创建邀请不占pending槽、不换版本、不关闸。接受在同一T3写集完成：邀请accepted及operation关联、RequestReceipt、pending槽、版本预留、fencing、queued阻止、完整切点/屏障outbox及审计。发起人与目标在接受时均重新核验当前授权；目标必须为实际登录接受者，from必须仍是当前持有人，expected_control精确匹配。邀请期间发起人仍可操作，已有其他pending则拒绝接受。发起人可取消尚offered邀请；取消不影响控制权。过期和取消后不能复活。

## 公共HTTP与字段迁移

[build_control_authority.py](build_control_authority.py)是本轮唯一局部定义源，生成[模型](control-authority.schema.json)与[OpenAPI](control-authority.openapi.json)。六个旧方法/路径整体替换，新增`getTransfer/cancelTransfer/lookupControlRequest`三个入口；旧文件保持原样。完整统一SDK生成时必须登记这些替换及授权、面板方法和快照投影迁移，不能“新解析失败再试旧版”。

控制查询保留revision、control_epoch、effective_version、mode、pending_change、gate_state及在途/未决列表；holder改完整三元组，增加reserved_version。ControlOperation的target不再只含holder_id，结果通过`effective_control_ref`精确指生效历史记录，历史effective不表示当前持有人。TransferOffer公开其固定字段、单调期限、接受操作关联；原expires_at展示字段单独在GUI参考UTC投影计算，不由服务拿墙钟判邀请有效。

全部接口要求精确`X-LeafSeamer-Contract`；GET要求人员bearer和当前对象读取权，POST另要求CSRF与可信Origin。三个控制写及offer/accept/cancel只接收输入，不接受barrier、holder结果、durable、ready或reserved。新建返回202与不可变RequestReceipt；相同请求返回200同Receipt。409是版本/竞争/已消费/内容冲突，403为权限拒绝，503只允许查原，不授权重新执行。lookup必须当前可读原对象；秘密、内部ACK及完整权限证据不公开。

权限保留原六项`control.read/acquire/release/transfer/accept`对应关系；新增getTransfer与lookup使用control.read，cancelTransfer使用control.transfer且只能原发起人取消。force=true始终另需control.emergency和实质理由，不因当前automatic而绕过。（来源：[主体矩阵](../df01-source/authorization-candidate.json)。）权限名不替代对象归属。同键查原仍须认证、CSRF/Origin和当前读取权，但不要求旧邀请仍未到期或旧CAS仍当前；过期请求上下文不能用于新受理。

## 同库持久映射与开放衔接

| 记录 | 主键与必须冻结的关联 | 提交约束 |
| --- | --- | --- |
| control_device | scope/device；epoch、effective_version、reserved_version、完整holder、mode、pending_operation_id、record_revision/digest | 单writer CAS；reserved和revision精确递增，普通重启不能改epoch或holder |
| control_record_history | scope/device/record_revision唯一，完整ControlRecord及record_digest | 与当前指针同事务追加，旧记录不覆盖；ControlOperation.effective_control_ref及OpenPlan.control引用精确历史原件 |
| control_request | RequestKey完整列唯一，request_digest、原内容、initial_result_ref | Key无digest；与首次结果、审计/outbox同事务；保留墓碑不重建身份 |
| control_operation / revision | operation_id及revision；kind/requester/expected/target、状态、最新barrier选择及effective_control_ref | 单设备未决槽；目标版本唯一且不回退。每次状态变更与device及审计/outbox/receipt同事务 |
| control_transfer / revision | transfer_id及revision；双方完整身份、原expected、原lifetime、状态、accepted_operation_id | offered只一次终结；accepted与T3 pending必须双向配对，不容许接受邀请却没有控制操作 |
| control_barrier_selection | operation_id/attempt及原完整切点、原ACK集合/监督退役/validation的精确Ref | 只采用该操作当前尝试；未决恢复不另预留版本，旧ACK只补历史；完整覆盖不能靠布尔字段或数量替代 |
| control_effective_commit | operation_id唯一、生效历史ControlRecord Ref、选择Ref、事务/审计/outbox | T4同时完成状态、许可归类及结果；历史不可变，effective不是ready |

上述是完整列与写集设计映射，尚未创建物理DDL。必须接入137表共享签发、资源、普通与取消完整覆盖，不另建第二权威账本。受理授权失败在T3前不消费版本；T3 COMMIT不确定先保护并按RequestKey查原，不能基于“响应失败”复用版本。T4不确定保留pending/保护；查到已提交结果只恢复历史显示，新启动仍须新gate安装。

OpenPlan的`state_refs.control`使用当前ControlRecord完整Ref；`basis.kind=activation`指已effective的ControlOperation修订，target/control_epoch必须与当前ControlRecord一致。资源恢复与gate恢复分别沿[OPEN_PLAN](OPEN_PLAN.md)，不能再做一次控制转交。T4之后gate_state固定protected；T5独立核验OpenPlan、原ACK及当前控制/资源/权限后才发布ready。拒绝操作、授权撤回、资源失效、换域/出口以及新pending均使旧Plan失效。lease续约不延长邀请或人工持有期。

## 故障与验收

必须验证：接受的每一写入前故障全回滚；提交后响应丢失同Key查原；双人接受仅一操作；接管抢在接受前使旧邀请失效；同名不同issuer拒绝；TTL等号/换域不接受；ACK丢失保持indeterminate且不复用目标版本；目标撤权后拒绝保持protected；旧尝试ACK不能生效；当前完整尝试可从indeterminate核对；普通重启保留持有人且ready作废；已经effective只恢复gate；释放变automatic/null但不恢复自动化或补排期。

[参考模型](control_authority_model.py)只对复制的字典提交，可信授权/屏障/存储提交由合成上下文提供，故障通过主动异常回滚副本；它不是SQLite执行器，不证明真实CAS、完整屏障、鉴权、磁盘或设备。报告按输入原字节绑定，正反例独立给预期；实际SQLite逐写故障、并发、HTTP、IPC和设备验收均未运行。本轮关闭的是上述公共字段与状态语义缺口，完整DDL及其取证映射仍须继续归并。

大对象断言在报告中记录完整比较的布尔结果，不重复嵌入整个合成状态；具体构造与预期由已绑定检查器复现。邀请、操作和控制修订的真实同库历史及完整屏障提供者仍须另行实现，副本模型通过不证明这些原件已落盘。
