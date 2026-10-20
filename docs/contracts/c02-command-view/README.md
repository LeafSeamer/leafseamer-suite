# 命令读取、取消与证据 HTTP 候选

状态：待审阅，`command-view/0.1.0-draft.1`。本轮补齐七个管理HTTP操作及公开CommandRecord投影，依据[既有命令契约](../../rebirth-first-loop-contract.md)、[受理身份](../c02-admission/README.md)、[生命周期](../c08-controller/LIFECYCLE.md)和[77表存储](../c08-controller/COMMAND_STORAGE.md)。生成源为[build_contracts.py](build_contracts.py)，不修改draft.4或IPC0.6，不实现服务。

## 1. 本轮裁决与跨项修正

已知事实：旧公共CommandRecord包含请求身份、目标、actor、origin、接管版本、取消、完成、attempt及证据；上一轮State只是领域子对象，不能直接替代完整GET。原受理裁决固定初始CommandRef，当前修订不应反向改变它。旧Resolution及生命周期Schema均只有`succeeded|failed|cancelled|not_sent`，上一轮命令SQL却误用了unknown。（来源：上述三个契约及[旧唯一模型源](../df01-source/source/public.schema.json)。）

本轮修正SQL的Decision/Resolution枚举，恢复既有四个值。未知观察保留为证据/observe，不生成确定Resolution。`not_sent`仅由提供者证明全部历史尝试未发送后产生，不能由最后一个attempt未发、杀进程或JSON字段推断；其持久化不改变原unknown，也不自动clear。新增SQL检查只证明枚举与持久关系，真实证明仍由提供者负责。

推荐将公开命令记录定义为**不可变完整修订**：metadata、State、attempt视图、取消摘要及证据索引在同一writer切点封存。任何可见字段变化都产生新State/record修订，取消受理也必须同事务发布observe修订。GET不得把历史State与当前取消状态临时JOIN成伪快照。cm_revision只存领域State；后续[持久化候选](STORAGE.md)新增14表，与77表组合为91表，分别保存公开投影、取消账本和证据索引；不是已实现HTTP服务。

## 2. 操作与身份

所有路由以Controller为authority，要求精确`X-LeafSeamer-Contract`，所有响应`Cache-Control: no-store`。两服务静态代理路由不合并身份空间。写入口不得自动重试；查询失败和not_found均不授权重发。

| 方法与`/api/v1/commands/{command_id}`后缀 | operationId | 成功模型与含义 |
| --- | --- | --- |
| GET 空后缀 | getCommand | CommandRead，view=current；当前投影不可发布则503 state_projection_pending，不返回旧clear |
| GET /revisions/{revision} | getCommandRevision | CommandRead，view=historical；固定历史，不授当前派发或恢复资格 |
| POST /cancel | cancelCommand | 首次持久受理202 CancelReceipt；同身份同内容200原回执，不表示设备停止 |
| POST /cancellations/lookup | lookupCommandCancellation | CancelIdentity→found/原回执、not_found/null或indeterminate/null；不创建取消 |
| GET /cancellations/{cancellation_id} | getCommandCancellation | 当前CancelOperation；不是原受理回执的可变替身 |
| GET /evidence | getCommandEvidence | EvidencePage；必填state_revision和limit=1..64，后续传cursor |
| GET /evidence/{evidence_id}/revisions/{revision} | getCommandEvidenceRevision | 固定EvidenceRecord白名单视图；与当前有效性分开 |

getCommand、cancelCommand、getCommandEvidence明确替换旧同路径操作，其他四项为新增。新取消请求使用完整expected_state_ref代替裸expected_revision；旧请求不回退解析。getCommandEvidence不接受旧动态翻页语义；完整证据body按下文具名类别保留，不能公开提供者秘密或原始设备包。

权限顺序：先确认当前认证/authority/version，再核目标设备和用途，最后查对象、当前投影及身份结果。human须具备目标设备的command.read、command.cancel或command.evidence.read；取消另需Origin/CSRF校验及获准人员角色。接管人员可按当前设备范围保护性取消旧持有人的命令，不强制原actor仍登录。service仅限受信配对Seamer自身来源的automation，不能借同组织名取消其他来源或手动命令。读原结果仍核当前权限；原动作grant到期不妨碍当前有权主体收紧取消。

主体配置是服务可信状态；OpenAPI中的humanBearer/serviceBearer两分支不允许客户端选择自己的角色。面板只能通过既有宿主代理和当前委托，不能持service凭据调用。仅有command.read不能读证据页；内部ProviderReceipt、原始授时和监督材料不在公开返回闭包中。历史身份足以验原报告，不自动授予当前读取权。

## 3. 完整记录与旧字段映射

| 原字段/职责 | 新位置与固定约束 |
| --- | --- |
| command_id、revision | 根与state同值；记录每个修订只发布一次，不用取消独立修订替代State修订 |
| request_identity、content_digest、admission | request_identity含新版RequestKey及request_digest；initial_command_ref固定受理版本1，policy.admission_ref指不可变裁决；content摘要不再复制第二个可漂移字段 |
| target、actor、origin、accepted_at | 完整保留原受理metadata；actor不是当前登录者，原身份不随接管变化 |
| run_binding、automation_binding | automation必有且保留来源链，manual为null；不接受客户端省略或改绑 |
| dispatch、control_binding | 固定原排期/截止配置与控制版本，读取不刷新期限或替换成当前持有人 |
| phase/outcome、effect/resource、reason、暂停、terminal | 完整State子对象；state_ref摘要绑定原State，不能用record_digest替代 |
| completion、retry_policy | completion与State证据Ref对账；policy固定完成/释放/retry政策、预算和原deadline Ref；OBS首闭环仍max_attempts=1 |
| attempts | 按cm_attempt.ordinal完整排序；保留全部attempt、原packet引用、多出口身份、协议请求ID、发送时间及证据引用；不只投影当前worker |
| cancellation | null表示无取消；否则固定该命令修订时的operation_ref、state、future_writes及reason；详细进度由独立GET查询 |
| completion_evidence、resource_release_evidence、resolution | State保留完整引用，实际对象进入同修订evidence_index及分页；Resolution独立序号和原terminal锚保持 |

record_digest=JCS(完整CommandRecord仅删除其自身record_digest字段)的SHA-256；State没有内嵌摘要，state_ref.digest直接对完整State计算。两摘要用途不同。initial_command_ref仍指受理时的历史初始对象，不冒充当前完整记录摘要。所有摘要带sha256前缀；保留业务字符串和嵌套同名字段，不做递归删键。严格Counter来自生命周期候选；借用的Actor/Dispatch/RunBinding仍有旧版词法，最终统一SDK必须显式修订，不能称本批已完成全SDK严格解码。

当前投影依据cm_current及完整投影提交关系；迟到风险/撤回使旧clear失效时，GET current返回503及retry_action=read_current。调用方可以查询，不能据此重发写。历史GET可返回当时clear，但明确historical；GUI必须同时展示历史标识，当前控制按钮使用另行验证的当前状态。响应超容量整项拒绝，不能截断attempt或隐藏风险证据后仍标完整。

## 4. 取消身份、回执和时序

CancelKey复用受理的七元命名空间，operation_id固定cancelCommand；目标command_id不扩唯一键，参与内容摘要。同键改目标必须冲突。context_id只查受信命名空间，不进入摘要；request_epoch映射该context_epoch，issuer_epoch保留。CancelContent为scope、URL command_id、完整expected_state_ref和reason；前端不能提交scope/actor/取消模式/自报结果。

同一身份先核当前权限及历史命名空间归属，再查原持久结果，之后才执行新请求的context有效期、CAS和容量判断。原结果存在时不因旧CAS/TTL已过而另建取消；同键异摘要409。查原没有记录只报告not_found；存储不可靠则indeterminate。提交结果未知时必须查原，不以换context、换key或换cancellation_id重新发取消设备指令。

推荐每个父命令只有一条取消操作历史，数据库对父command建立唯一约束。新身份对已有取消返回409 cancellation_exists，由有权调用者从命令摘要读取原operation；不会把他人的回执私有命名空间移交给当前人员。协作取消的失败/未知靠核对补事实，不通过换身份重新发送。未来确有安全重试需求时必须另版增加固定取消retry政策及显式重试授权，本候选不暗授这一能力。

新受理事务必须原子写入：CancelContent与Key、初始CancelOperation、不可变CancelReceipt、精确命令拒绝标记、该命令全部已登记attempt/准备/重传入口的捕获切点、observe后继修订、审计及保护outbox。只有事务提交才202。拒绝标记永久阻止该命令新的普通许可；已经离开出口的写仍可能执行。若存储无法可靠提交，按既有Q52关闭写入，不能谎报取消受理。

`CancelReceipt.initial_operation_ref`固定取消操作修订1；`accepted_state_ref`是提交前CAS目标，`CancelOperation.command_state_ref`是该操作进展提交时关联的后继State，不能混用。取消独立revision精确加一；current GET与命令摘要可因各自查询时刻不同而不同，但每个引用指向自己的固定版本。

CancelOperation携带原CancelIdentity，不回指完整CancelReceipt摘要，避免“回执含初始操作摘要、初始操作又含回执摘要”的循环。先封存初始操作，再生成回执；两者同事务可见。后续操作修订保持原identity、命令和mode。命名空间授权必须核对精确issuer/issuer_epoch/principal/request_epoch历史归属，不能仅用一个“允许查原”的布尔值放行任意key。

状态含requested、confirmed、unsupported、failed、indeterminate、too_late：

- requested仅表示可靠受理；future_writes=pending表示完整关闭仍在处理。
- confirmed须可靠后续写关闭和模块声明的取消标准证据；未发路径须覆盖全部历史，不能只看最后一次许可。
- unsupported表示固定能力只支持发送前取消而原命令已发送；仍保留观察及资源，不能把unknown改成failed。
- failed是明确取消操作失败；indeterminate是取消效果不确定，保持保护并查原。后续有可靠证据可从indeterminate追加确定状态，不得回到requested或重发设备动作。
- too_late须已有原命令确定完成的证据；不能因phase=finished/unknown便判太迟或没有影响。
- confirmed/unsupported/failed/too_late为取消操作的固定结论；后续证据追加，不能把同操作重开requested。future_writes已可靠closed不能改回pending；新发现旧证明错误沿独立失效/保护链处理。

原命令尚未终结时可按确认标准转cancelled；已经finished则phase/outcome/terminal_revision不变，必要时追加Resolution。取消确认和资源释放分开；原unknown可以在取消confirmed后仍unresolved、paused_latched。接管effective也不能替代取消确认。

协作式取消是可能改变设备的控制动作，必须使用固定取消政策、完整父命令绑定及独立的一次性许可。不能复用旧动作permit，也不能绕过77表“终态禁止普通许可”触发器。**本批未定义这个保护执行分支的完整IPC/DDL**：下一统一执行契约须明确cancellation_id、parent command/hold、guard、单次发送意图及取消完成证据映射；在它完成并验收前不得启用cooperative。此处是待完成全功能设计，不是将原有协作取消范围删除。OBS首闭环仅before_dispatch_only。

## 5. 证据快照和游标

EvidenceIndex绑定同StateRef的固定snapshot_ref及完整total。初页只读取该修订已封存的清单，不因GET分配证据序号或混入迟到事实。每项按`(source_ref.id, source_ref.revision数值, kind)`唯一排序；同逻辑ID若不同类型须有类型前缀，单对象URL因而无歧义。next_cursor只在还有成员时非null；空快照返回空items和total=0。每页上限64，总数使用U20，不通过SQL 64位整数截断。

游标由服务签名/认证，绑定authority/database、command、snapshot、StateRef、主体及授权修订、契约版本、下一offset、limit和有效期；不是客户端自报可信字典。每页重新鉴权。授权修订变化或错主体/limit/snapshot拒绝；过期410 snapshot_gone，可重新读取同一历史修订首屏，不切到最新修订。游标没有设备写权，不能放入URL的bearer凭据。签名key及TTL取部署秘密/容量profile，具体库与生产数值尚未批准。

EvidenceRecord公开五类：原结构化observation、命令级decision、release、resolution、invalidation。source_ref绑定各自持久原件；view_digest绑定完整白名单视图，二者不混用。原observation保留原会话/协议请求关联及OBS结构化完成包；不返回原始packet字节、ProviderReceipt或采集凭据。invalidation含subject_ref、reason及protection_ref。合法字符串不证明脱敏，实际投影提供者须执行既有秘密策略。

历史证据在撤回后仍可审计读取；读取历史原件不表示它当前有效。当前Command必须先根据全部失效和资源风险重新核验，迟到新事实进入新的State/索引。分页集合由存储提供者封存并保存，不以调用方给定total、items或重算摘要作为完整性证明。

## 6. 故障、验证及后续映射

| 故障/竞争 | 必须结果 |
| --- | --- |
| 完成与取消同时到达writer | 按串行顺序保存事实；完成先确定则不把succeeded覆盖为cancelled，取消受理本身不抢占完成结果 |
| 取消事务提交后丢响应 | 查原回执，不另发取消；取消效果未知保留indeterminate |
| 旧context到期后重查原请求 | 当前有权时返回原回执；新身份仍需有效context/CAS |
| 人员退出或服务配对被撤回后轮询 | 当前权限拒绝；历史worker发送证据接收不因此丢弃 |
| 迟到原报告推翻旧clear | current503直至保守新修订可发布；历史记录保留且不可当READY |
| 两页之间新证据/撤回到达 | 原快照成员不变；新状态另建索引，不能拼页后宣称最新完整 |
| 跨command/服务重放cursor或重算证据摘要 | 所有者/原件/游标绑定校验拒绝，不因结构通过取得可信身份 |
| 取消成功但资源证据缺失 | 保留unresolved与暂停锁存，不能释放另一命令的写资格 |

[check_contracts.py](check_contracts.py)执行生成字节、Schema、OpenAPI、公开投影和合成关联；[reference_model.py](reference_model.py)用字典模拟串行原子受理，可信授权、时钟、closure与证据均为人工前提。它不执行真实HTTP、CSRF/TLS、签名游标、SQLite、完整取消IPC、并发或设备。

公开修订/取消Key及receipt/证据索引已有[91表组合候选](STORAGE.md)，396项内存检查另记于storage-report，不扩大本HTTP的160项覆盖。后续仍需取消保护执行IPC/一次性许可、closure及证据原件完整FK；统一SDK/权限矩阵/面板方法及GUI迁移；严格数字和时间模型统一。已有七接口及固定投影规则不再作为“完全没有格式”的缺口。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-command-view/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-command-view/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-command-view/check_contracts.py --check-report --staged
```
