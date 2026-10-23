# 面板服务端 HTTP 与事务候选

本稿细化[C09 PD03—PD05](../../rebirth-c09-extension-design.md)与[channel0.2](../c09-panel/CHANNEL_V02.md)，版本为`panel-service/0.1.0-draft.1`。这是待审阅的设计和离线参考，不是服务实现；不修改已确认draft.4／IPC0.3，也不批准部署或设备操作。

## 1. 权威与信任边界

Seamer和Controller分别在自己的authority、数据库与唯一writer上提供同一接口族；一次面板会话只有一个目标authority。跨服务界面创建两份独立会话，不以同名session或GUI库代替目标权威。每次调用使用目标单audience的human bearer、精确GUI Origin；POST还需与该auth_session绑定的CSRF值。三者共同要求，不允许任选一个。bearer/CSRF不进入URL、面板、审计或幂等摘要；服务按当前角色、对象权限、安装批准、scope和委托交集重新鉴权。OpenAPI中的security声明不实现这些检查。

`gui_instance_id`只是已登记宿主实例的关联值，不是认证因子。创建时由认证上下文派生authority_service_id、database_instance_id、issuer_id、issuer_epoch、principal_id、auth_session_id；body中的安装／scope／配置引用只作期望，必须从当前权威记录核验。origin从固定管理配置选择，不能接受任意URL、HTML、网络代理目标或安装包自报权限。服务依赖可信宿主正确处理窗口、nonce、端口与用户确认，HTTP不声称证明物理点击。

浏览器通道丢失、宿主刷新或服务运行域重建后不恢复旧port或自动提交写队列。原请求可由可信宿主历史页按当前读权查询；旧委托不转移给新面板。服务内部保存的完整Session、Lifetime、Preview及委托引用只供可信宿主，不按原样传给iframe。

## 2. 完整接口族

Schema唯一生成源为[build_contracts.py](build_contracts.py)，生成[service.schema.json](service.schema.json)和[service.openapi.json](service.openapi.json)。OpenAPI包含14个操作，两authority复用；它是新增接口族，未并入旧71操作矩阵。所有成功和错误响应都要求`Cache-Control: no-store`；路径ID与认证、body完整身份交叉核验。JSON严格入口和原始字节预算继续由DF01约束，结构校验不代替它。

| 方法与路径（均在`/api/v1`下） | 请求／成功响应 | 事务及查询语义 |
| --- | --- | --- |
| POST panel-sessions | CreateSession → 201 HostSession | 创建固定scope、硬截止、单调时基与委托；持久管理操作身份，同内容重试返回200原回执 |
| GET panel-sessions/{session_id} | 无body → 200 HostSession | 只读当前会话和关闭operation引用；关闭记录不是设备停止 |
| POST …/{session_id}/handshake | Handshake → 200 HostSession | created CAS到handshaking，固定handshake_id与channel_id；nonce只在宿主内存，不持久化或记录摘要 |
| POST …/{session_id}/prepare-activation | PrepareActivation → 200 HostSession | handshaking CAS到schema_loading，权威选择完整Registry／Bundle／scope revision，分配唯一ActivationRef；静态上下文可bundle=null |
| POST …/{session_id}/activate | Activate → 200 HostSession | schema_loading CAS到active；固定激活引用及宿主的ready报告必须相符；无Bundle要求ready_digest=null，有Bundle必须等manifest_digest |
| POST …/{session_id}/renew | Renew → 200 HostSession | active且未到期；expected_lease_revision CAS；硬截止、激活、scope不变，旧预览不延长 |
| POST …/{session_id}/requests | Invocation → 200/202 RequestReceipt | read返回200，write首次可靠受理202；host_confirm仅登记pending_confirmation并返回200，不能直接消费确认；同内容只返回原记录 |
| GET …/{session_id}/requests/{request_id} | 无body → 200 RequestReceipt | 从原会话推导完整八元身份；不产生请求、结果句柄或副作用；当前不可见统一404 |
| POST …/{session_id}/confirmations | ConfirmInvocation → 201 ConfirmationRecord | 仅8个host_confirm方法；从原固定intent创建唯一offered预览，可原子创建pending请求或接续同内容pending记录；重复200不刷新截止 |
| GET panel-confirmations/{preview_id} | 无body → 200 ConfirmationRecord | 可信宿主查原预览；不恢复消费资格，不重新生成预览 |
| POST …/{preview_id}/commit | ConfirmationCommit → 202 RequestReceipt | preview消费、原请求accepted、领域受理／恢复消费、audit和outbox同事务；重复200原记录 |
| POST …/{preview_id}/cancel | ConfirmationCancel → 200 RequestReceipt | offered→cancelled并关闭pending；已经consumed返回409，查询原请求，不伪报取消成功 |
| POST panel-sessions/{session_id}/close | CloseSession → 202 LifecycleReceipt | 本地先禁新代理，authority同事务设拒绝状态、固定目标集合、撤销未消费预览与pending请求、audit/outbox；重复200原操作 |
| GET panel-session-operations/{host_operation_id} | 无body → 200 LifecycleReceipt | 认证会话＋已登记gui_instance_id查询原管理操作，解决创建／续租等响应丢失；不再次延长租约 |

GET管理操作额外要求`gui_instance_id` query；这是关联字段而非秘密。当前auth_session与原会话不同时，该管理查询不能接管原宿主操作；管理员历史读取另沿审计权限。GET Session／Request的历史读取可由新的human auth_session在拥有当前对象读权时执行，不能因此获得旧写资格。

`HostSession={session,lifetime,delegation_ref,handshake_id?,channel_id?,close_operation_ref?}`，后三字段显式null而非省略。Session沿0.2固定结构；prepare阶段将ActivationRef持久化后再交付Bundle，activate不重新选择版本。再次prepare、不同Registry或不同channel不能原地替换激活；需关闭重建。LifecycleReceipt保存操作发生时的session_ref及phase与逐目标状态，不直接返回旧的“active会话快照”当当前状态；宿主收到迟到回执后还要GET Session核对当前revision。

方法前缀必须匹配目标authority角色，Controller不能接Seamer方法或反向代理它。关闭允许发生在created／handshaking／schema_loading／active任一阶段，因此关闭记录可尚无握手或激活引用；handshake_id和channel_id必须同为null或同时存在。运行中权限撤销走保护路径，不等待正常close接口的human凭据恢复。

## 3. 两种幂等身份与结果投影

管理操作唯一键为`(authority_service_id,database_instance_id,issuer_id,issuer_epoch,auth_session_id,gui_instance_id,host_operation_id)`；method/path/规范body是内容，不进入唯一键。先在当前读权限下查同键，摘要不同409，已存在时返回原回执，不再CAS或延时。新操作才复核执行权限。POST body中的host_operation_id不进入内容摘要；操作名、精确path及其余body全部进入JCS摘要。GET无副作用，404不证明原提交从未发生。

业务面板请求仍使用八元PanelRequestIdentity；activation_id、委托revision和method只进入内容，不进入唯一键。Invocation传`intent`，其normalized_arguments是宿主声称的规范输入，服务器仍按Registry的精确SchemaRef、方法Schema、动态批准Schema和具名缺省规则重算。拒绝“显示旧值、发送时补新默认”的变化。摘要固定为完整规范Intent的JCS SHA256；不纳入通道序号、correlation或租约revision。secret_ref可绑定版本，秘密值和低熵秘密hash不得进入Intent。

RequestReceipt字段：identity、intent_digest、method、activation_ref、state、reason_code、accepted_result_ref、projection_state、projection。state为accepted/pending_confirmation/rejected/cancelled。accepted必须有可靠本地结果引用；读取结果也登记具名结果记录，预检／恢复展示句柄与该记录同事务，不能在重复读取时重新生成。非accepted的引用及projection必须null。projection_state为available/unavailable/not_applicable：仅accepted可用前两种；available必须是该方法对应的TypedValue，unavailable只隐藏当前不可重建／不可授权的投影，不抹除受理事实。accepted_result_ref仍须当前读权，不能跨租户暴露存在性。受理引用固定，不以之后的对象revision覆盖；当前状态另由具名投影提供，不改原受理身份与领域终态。

`accepted`只表示方法受理或读取完成，不能当设备效果；`unavailable/unknown_outcome`是HTTP故障知识状态，不写入持久请求终态冒充拒绝。提交结果不确定返回503，客户端只查询原身份，不因503或404自动重POST、换ID、重弹确认。领域命令unknown仍保留原命令记录及资源未决。

错误词表：400 invalid_request；401 authentication_required；403 authority_denied；404 not_found_or_invisible；409 conflict；410 expired；413 payload_too_large；429 capacity_exceeded；503 source_unavailable或unknown_outcome。均不透传上游错误文本。409已消费／版本过期不表示业务没发生；只有原记录能解释。自动重试写关闭，Retry-After不构成重发许可。当前权限允许历史查询时，已accepted请求不因session后来过期而改写成410。

## 4. SQLite记录及原子提交

生产DDL仍待完整DF04归并；[storage-probes.sql](storage-probes.sql)仅为本轮局部约束探针。全部八元身份列NOT NULL、精确复合UNIQUE；内部request_pk仅作join代理，不能替代外部唯一身份。preview通过(request_pk,session_key)复合FK绑定归属，避免把另一个会话的预览接到合法request_pk。一个请求最多一个preview、一个领域受理引用。accepted请求指向本地受理记录；预览consumed与该引用一致，延迟FK在COMMIT时检查。不能用NULL绕复合FK。（依据：[SQLite外键文档](https://www.sqlite.org/foreignkeys.html)。）

| 事务 | 同一COMMIT内的必需写入 | COMMIT外边界 |
| --- | --- | --- |
| PS1创建／管理 | session、delegation、固定批准／时基、管理幂等记录、audit | 不建立设备连接或发送业务动作 |
| PS2请求 | 原身份＋规范摘要、权限与版本快照、领域受理或pending／拒绝记录、audit、必要outbox | 设备发送只由最终出口另行取permit；只读外部采样先取有年龄证据的快照，再在事务复核其版本 |
| PS3预览 | pending request＋唯一preview、创建时lease期限、固定展示及摘要 | 展示发生在COMMIT之后，不能向外泄漏未提交预览 |
| PS4确认 | 复核当前授权／时基／session／预览与目标版本、pending→accepted、offered→consumed、领域操作／RecoveryPreview一次消费、audit/outbox | 不在事务内跨HTTP调用另一个服务，领域插件只能提供同writer本地受理钩子 |
| PS5取消 | offered→cancelled及pending→cancelled、audit | 不取消已accepted业务；需独立具名取消动作 |
| PS6关闭／撤权 | session拒绝下界、精确selector、固定完整目标集与operation、offered→revoked及pending→rejected、audit/outbox | 逐目标屏障异步确认；离线目标保留，既有accepted和unknown不改写 |

每个连接在事务外设置并验证foreign_keys=ON；使用明确短写事务和受影响行数检查。SQLite同一时刻只有一个写事务；BEGIN IMMEDIATE可能返回SQLITE_BUSY，不可把它当已受理或未执行的设备证明。持久化、fsync与WAL故障沿DF04，不能由本次内存数据库推出。（依据：[SQLite事务文档](https://www.sqlite.org/lang_transaction.html)。）

关闭与确认按同writer先后线性化：确认先提交，则关闭捕获已受理操作／permit，屏障核对后效；关闭先提交，则确认拒绝，预览不可复活。跨authority的撤销不承诺全局瞬时原子；目标注册、许可签发和本地关闭捕获需在同writer串行，目标ACK必须核对operation及selector摘要。超时保留indeterminate，不能因为零个已知ACK宣称没有影响。

候选每会话最多256个尚需核对的目标世代，包含仍在执行和订阅的旧worker世代，不能只数在线节点。容量在注册新目标／签发许可前预留，满额先拒绝新增工作；关闭不得截断目标列表或因普通请求配额耗尽而丢弃保护记录。目标完成前保留其槽；生产全宿主预算、保护保留量及更大部署分页方案仍归C12审阅。

## 5. 时间、恢复及保留

时间门控同时检查已确认UTC区间政策和原运行域单调deadline：严格now < min(hard,lease,preview)，等号拒绝；时钟域改变或无法证明期限时禁止新执行，UTC显示不延长许可。renew使用原host_operation_id核对已提交结果；同一次续租重送不以新now重算。新有效租约不延长既有preview.deadline。counter以十进制字符串存储，SQL比较采用受检十进制规则，不转浮点或按无补零文本排序；本轮探针刻意只用小整数模拟时序，不声称覆盖完整U20计算。

崩溃点：COMMIT前全部回滚；COMMIT后响应前崩溃保留accepted和consumed，按原身份读取；COMMIT结果未知不执行补偿重发。重启不复活原port或时基资格，对旧active会话进行拒绝与精确屏障恢复；历史查询仍保留。备份恢复生成新database_instance_id，旧请求不存在不证明从未执行。不得以新库或新session重播旧意图。

活跃session、未决请求、preview、接受结果及关闭目标通过FK RESTRICT保留；不做级联删除或清理唯一身份来重用ID。终态过了保留期可删除展示内容，保留摘要、归属和不可重做墓碑直到原身份生命周期结束。具体留存预算和安全回收与DF04/C12一并冻结，当前不能宣称完整生产DDL完成。

## 6. 验收与剩余冻结

本轮检查覆盖14路由与逐接口Schema、35方法的真实静态输入绑定、错误状态、SQL复合FK／唯一性／一次消费、取消和关闭的串行先后、事务注入回滚及提交后响应丢失的查询。参考检查器只连接`:memory:`，不接收外部DB路径，不接入网络或设备。模拟故障是主动异常与读回，不是杀进程、掉电或磁盘耐久试验。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-service/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-service/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-service/check_contracts.py --check-report --staged
```

[reference-report.json](reference-report.json)记录191项：145个Schema及OpenAPI投影接受集对照、17个合成关联、6个HTTP元数据反例、23个SQLite内存探针。每个Schema例同时验证独立Schema和OpenAPI内联投影；这不是通用bundler证明，生成器仅处理本批固定本地引用闭包。报告绑定17输入，不在顶层旧十份报告清单中；`--check-report`只比较字节，不重跑用例。OpenAPI3.1.1结构由已锁定验证器检查。（格式依据：[OpenAPI3.1.1规范](https://spec.openapis.org/oas/v3.1.1.html)。）

运行验收PST01—PST08仍未运行：①两个真实并发请求同identity仅一个受理；②撤权与确认两个顺序及发送出口窗口；③进程杀死在提交前后；④SQLITE_BUSY／IOERR／FULL和回执未知；⑤真实Origin／CSRF／audience与宿主刷新；⑥续租响应丢失与跨时基；⑦完整关闭目标集及迟到／伪ACK；⑧领域更新、RecoveryPreview和panel_request同库事务及全量真实投影。

剩余设计：上述逐操作权限与新接口纳入下一版SDK单一源；完整Delegation与撤销selector/Guard合并到IPC；订阅／句柄和所有领域表完整DDL；实际字段提供者、动态DSL及能力Schema、运行容量与留存profile。现有通道校验不被本批覆盖声明替代，本批不自动关闭C09或全系统阶段0。
