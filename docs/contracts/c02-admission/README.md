# 命令受理、查原与永久拒收候选

状态：待审阅，`command-admission/0.1.0-draft.1`。落实[C04提交与未知恢复](../c04-storage/DISPATCH.md)的远端裁决缺口，保持[准备候选](../c04-preparation/README.md)、[保护IPC](../c05-protection/PROTOCOL.md)的执行门控；不修改旧公共版本或业务代码。

## 1. 身份冲突与明确映射

已知事实：旧公共 RequestIdentity 使用 service_id/context_epoch/context_id/issuer_epoch 等字段；C04 的持久 RequestIdentity 使用 target_scope/request_epoch/operation_id，且没有 issuer_epoch。HTTP operationId 为 submitCommand，而 C04 固定 operation_id=createCommand。两者不能靠同名类型或字符串直接拼接。（来源：[公共源](../df01-source/source/public.schema.json)、[执行模型](../c04-execution/execution.schema.json)。）

推荐新 RequestKey 精确为 target_scope、issuer_id、issuer_epoch、principal_id、request_epoch、operation_id=createCommand、idempotency_key。target_scope 为 Controller 的实际 authority/database；request_epoch 映射受信上下文的 context_epoch；issuer/principal 从当前认证及上下文取得。context_id 仅用于查找上下文，不进入持久唯一键。issuer_epoch 必须进入键，防止身份库换代后同名主体碰撞；C04 SQL和SDK统一版须共同增加此列，旧表不自行兼容新请求。

operationId=submitCommand 是 HTTP 操作名称，持久 operation_id=createCommand 是固定动作身份，两者在此显式一对一映射；lookup/reject不能改原 operation_id 为自身操作名。key不含 request_digest，也不包含transport凭据、correlation_id或context_id。

RequestIdentity = key + request_digest。摘要为 JCS(CommandContent) 的 SHA-256，带 sha256: 前缀。CommandContent 从[新CommandRequest](../c05-protection/protocol.schema.json)只去掉顶层 context_id、idempotency_key、correlation_id；嵌套同名字段保留，automation_binding及完整执行参数参与摘要。版本由命名空间绑定及必需协议头校验，不允许相同上下文混用不同写契约。

## 2. 三个公共操作

| POST接口 | 结果 | 认证/授权 |
| --- | --- | --- |
| /api/v1/commands | CommandRequest→RequestAdjudication；首次accepted202；原持久accepted/rejected200 | bearer；human/manual，或已配对seamer服务/automation。当前device.command及全部准备、运行、人工接管、时间/资源门控 |
| /api/v1/commands/lookup | RequestIdentity→found/adjudication、not_found/null、indeterminate/null；200 | 当前command.read；限有权读取的原主体命名空间及设备范围，lookup本身不创建记录 |
| /api/v1/commands/reject | RejectRequest→RequestAdjudication；可靠完成200 | 当前command.cancel；human只拒收自己命名空间，seamer只限自身组织自动化。原动作grant/上下文到期不阻止当前有权主体收紧拒绝 |

所有操作要求精确 `X-LeafSeamer-Contract`，响应 no-store。仅有mTLS不代替公共bearer；服务身份必须是受信注册seamer，不能body自报。面板调用仍经宿主代理及精确委托/来源核验，不能借用户同名主体跨面板调用；本候选不授面板新的直接接口。

RejectRequest包含完整原RequestIdentity、CommandContent和不可复用rejection_operation_id；不携带旧context/token。服务按原持久提交标记及受信namespace解析身份；人员按受信历史context/命令来源解析。请求body不证明原命名空间所有权，旧凭据失效时仍需要当前读/保护授权和可验证的历史归属链。历史归属无法证明时拒绝，不能凭同名principal恢复权限。

拒收不是撤销已受理命令。原key已accepted且摘要一致时只返回原accepted裁决，调用者继续原command查询/取消和资源核对；不得改写为rejected，也不得把“拒收接口200”展示成动作已停止。没有原件时才建立永久rejected墓碑。已有key而摘要不同时409，保留原件，不泄露其他对象。

普通认证/格式/容量错误没有永久拒收含义，返回400/401/403/409/413/422/429/503及受限Error；返回错误不能创建“durable=true”伪证据。新提交门控不通过且未形成可靠裁决时保持未知/拒绝响应，查原或显式reject；不以普通4xx证明未来迟到副本不可能被受理。

## 3. 同一writer的持久裁决

| 操作 | 同一Controller短事务中的写集 |
| --- | --- |
| accept | 重新鉴权/门控及容量预留；查完整key；若未存在，插入不可变accepted裁决、初始command及准入绑定/准备引用、审计和固定event outbox，再提交；提交成功后才允许排队 |
| reject | 当前保护授权及历史归属核验；查相同key；未存在则插入不可变rejected墓碑、拒收操作结果、审计/outbox；已存在则仅绑定此次拒收操作到原裁决，不改变它 |
| lookup | 当前读取授权；读取原裁决及提交引用，响应释放前复核权限；未知存储状态返回indeterminate，不制造not_found |

受理与拒收必须竞争同一唯一键并在同一writer顺序中裁决，不能各有一张互不排他的去重表。accepted必须有真实初始CommandRef，rejected必须为null；裁决与初始command双向提交，不能先回202再补command。拒收操作另以(target_scope,当前操作主体身份,rejection_operation_id)幂等，原identity/content全入其摘要；同拒收操作换目标409。不同拒收操作可指同一原key，结果仍是同一不可变裁决。

RequestAdjudication含 adjudication_id、revision=1、identity、decision、command_ref、commit_ref和adjudication_digest。command_ref绑定**初始受理版本的不可变快照**，后续命令状态修订不能改变裁决摘要；commit_ref由Controller持久writer签发，不由调用者填写。adjudication_digest只去掉顶层自身。lookup只返回裁决，不在摘要里嵌入可变命令状态。

accept先提交→reject只能取得accepted；reject先提交→迟到submit只能取得rejected；未提交前崩溃→无成功回执，重新查原；提交后丢响应→查原返回同一裁决。结果未知时不得重发设备命令或换key重做；reject可以同身份重投，因为它只禁止未来受理，不产生设备动作。存储故障先关闭准入，不保证数据库和远端设备物理原子。

不可变裁决不得TTL删除后复用key。容量不足在准入前拒绝并保护，不能删最老墓碑腾位。完整GC可将行归档为命名空间拒绝证据，但必须先证明旧namespace永久停止写入且保留归档查询/拒绝下界；该策略未冻结前禁止删除。备份恢复生成新database_instance/request_epoch并默认保护，不能把旧命名空间作为新活跃写空间；旧原件无法取证保持indeterminate，不能返回伪rejected来清资源。

## 4. Seamer、手动和运行结果的衔接

Seamer RequestAdjudicationRef必须匹配自身原submission的完整新identity及request_digest；accepted只绑定原command，rejected只封存原提交。StepRecord已unknown时迟到accepted仅补归属，不重开步骤。人工重新操作仍需原结果/资源核对和新的明确操作；拒收不自动批准新execution。

自动化受理还必须验证[准备记录与执行绑定](../c04-preparation/README.md#4-状态与命令受理衔接)，并持久化AutomationOriginBinding。manual绑定null，不能从自动化请求删除绑定后冒充人工；身份分支来自认证，面板来源来自宿主。完整运行来源继续进入Guard/Permit/Intent，不因此次HTTP裁决省略。

提交返回裁决是对旧CommandRecordResponse的版本化修改，GUI/SDK应以command_ref随后查询当前命令；完整GET/取消/证据响应及C04身份列仍须统一归并。候选中的方法、对象权及provider规则是设计要求，OpenAPI security声明和合成trusted字段不证明实际鉴权。

## 5. 故障验收

| 编号 | 情形 | 必须结果 |
| --- | --- | --- |
| ADM01 | submit与reject两种先后顺序 | 每个原key恰一不可变裁决；accepted不改成rejected |
| ADM02 | accept提交后响应丢失 | 查原返回原CommandRef，不创建新命令 |
| ADM03 | reject先提交，迟到旧/不同context请求 | 同原key永不创建命令；context变化不扩唯一键 |
| ADM04 | 相同key换摘要或重算参数 | 409保留原件；digest不是唯一键的一部分 |
| ADM05 | 普通503/429、lookup未找到 | 不当永久拒收；不重发动作 |
| ADM06 | 错issuer epoch、Controller库或原主体 | 拒绝命名空间错配，即使摘要合法 |
| ADM07 | grant到期、保护身份仍有效 | 可以收紧原身份；不能受理新设备动作 |
| ADM08 | 伪造commit/初始CommandRef或篡改裁决再摘要 | 与权威记录不符则拒绝 |
| ADM09 | 查询已撤权或面板越委托范围 | 不返回原对象；旧token/context不授查询权 |
| ADM10 | 恢复旧备份或墓碑容量耗尽 | 保护并保留未知，禁止复活命名空间或删除墓碑 |
| ADM11 | 旧Step已unknown，迟到accepted | 只补提交归属，旧终态不变 |
| ADM12 | 嵌套同名context_id或proof业务字段 | 参与摘要；只排顶层运输字段 |

Schema/OpenAPI与参考检查器验证结构、投影、合成权威关联及两个串行竞争顺序；没有运行HTTP、生产writer、数据库并发/掉电或设备。ADM01—ADM12运行验收待执行。完整Controller物理DDL、命名空间签发/历史归属provider、公共其余路由和SDK最终统一版仍待完成，不关闭全系统设计阶段。

[参考报告](reference-report.json)记录92项离线检查，绑定本目录5份输入与3份来源Schema原始字节。`python build_contracts.py --check`核生成一致；`python check_contracts.py --report`执行参考检查；`python check_contracts.py --check-report --staged`只核对暂存输入，不重跑。参考模型用独立字典副本表示串行原子步及响应丢失，未执行数据库事务或真实网络故障。

## 6. 受理子域物理布局

后续[存储候选](STORAGE.md)提供11张表及双向提交约束，将namespace、原请求键、不可变裁决/初始命令、容量预留、commit、拒收操作、审计和通知落实到[SQL](admission.sql)。历史归属与当前权限的提供者输入/输出和失败边界具体化；关闭namespace不关闭当前有权保护，也不撤回已发送命令。该候选细化第3节，不等于完整Controller迁移、执行器或SDK归并。

[独立存储报告](storage-report.json)记录159项内存SQL检查，包含逐写缺失/主动异常、同键两种裁决顺序、跨key错配、issuer换代、关闭后拒收及删除/REPLACE反例。原92项报告仍只覆盖原范围；二者均不证明生产并发、磁盘耐久、真实鉴权或设备效果。
