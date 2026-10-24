# 公共命令消费包与SQLite逐字段核对

本包为设计候选，`approved=false`。提供[单一类型图](command-contract.schema.json)、[公共命令OpenAPI](command-contract.openapi.json)、[完整IPC入口](command-contract-ipc.schema.json)及[消费清单](command-contract-manifest.json)。它统一命令领域的消费入口；全系统SDK、业务服务及最终发送准入仍未完成。

## 已知事实

旧受理API和命令读取API分别内嵌旧AutomationOriginBinding；上一轮继续运行绑定已进入IPC，但没有进入这两个API。当前SQLite参考库的`execution.binding_body`只有decision、artifact_digest和plan_digest，`command_submission.request_body`只有动作、设备、value及局部continuation。两者均不能通过新版完整Schema。`command_submission`的唯一身份还没有持久化issuer_epoch。（来源：[生成器](build_command_contract.py)、[实际库核对器](command_storage_mapping.py)和[验证报告](command-contract-report.json)。）

实际执行的plan_digest绑定含继续运行关联的完整execution_plan_set正文；获批continuation_plan_ref.digest绑定转交前的原批准步骤，两者用途不同。上一轮合成ExecutionBinding直接使用后者，不能据此证明真实SQL完整等价。新核对器要求执行绑定引用实际执行计划的摘要，同时在ContinuationSelection中保留批准计划Ref，不要求两份不同正文摘要相等。

## 单一消费入口

[生成器](build_command_contract.py)从已确认的局部候选建立一张类型图。九个旧别名精确重定向至同一CommandRequest、CommandContent、RunBinding和AutomationOriginBinding；不会凭类型名字后缀批量替换。OpenAPI的components由该图的可达闭包派生。IPC入口全部52帧直接引用该图，消费者使用清单登记的本地文件解析器，不能访问示例域名下载Schema。清单绑定每份产物摘要、输入摘要、导出和全部操作。

旧API的scope会拒绝实际数据库名`controller.db`，故本包将八处明确的公共Scope定义归并到转交的CN__Scope，并把读取侧RequestKey/RequestIdentity归并到受理侧原定义。新版本允许已确认的带点身份，仍拒绝斜线、末尾换行和超长值；旧API文件和历史接受集保持不变。这一修订不扩大全局所有ID词法，也不改变现有IPC各字段的语义。

SDK开发者只能从清单选取该包的导出，不得拼接旧API中的同名类型。生成文件不手改，入口变更后重生成并检查摘要与引用闭包。这里没有运行TS类型生成、Ajv编译或HTTP客户端生成；这些仍按[DF01](../../rebirth-df01-sdk-freeze.md)工具锁执行，不把JSON Schema验证冒充可发行SDK。其他Seamer、身份、时间、订阅等领域尚未纳入本包，`scope=command-api-and-ipc-only`明确此范围。

公共API十个操作完整保留：受理、查原、永久拒收、当前/历史命令读取、取消受理/查原/进度、证据分页/原件读取。HTTP版本头统一为`command-contract/0.1.0-draft.1`；内部对象保留各自明确版本，未重命名历史原件。原认证分支、CSRF、响应码、权限扩展及no-store规则保留；本包不提供新身份权限。IPC仍为0.14，必须协商continuation_grant_binding，类型的语义没有另一次修改。

旧版本保留历史查读能力，不能用旧API头向新接口提交或把缺失的新绑定字段填空。业务服务的路由版本分派、请求字节限额与跨语言严格解码仍须实现和实测；静态OpenAPI通过不证明这些运行行为。

## 新版SQLite写集契约

[逐字段映射](command_storage_mapping.py)覆盖ExecutionBinding、CommandRequest和RequestKey全部39个顶层字段。嵌套对象必须按完整Schema保留，不能将局部字段相等视作整个对象等价。新布局必须满足：

1. PLAN同一事务在执行正文中封存完整类型、真实决定Ref、编译产物Ref、输入/参数快照Ref、计划时受监督时钟、完整新grant及目标清单。`execution.binding_body`保存完整JCS正文，`binding_digest`仅排自身顶层字段；其他列逐项相等。缺编译产物身份或时钟原件时不能先提交后补写。
2. `execution.plan_digest`与`execution_plan_set.plan_digest`均对实际完整计划计算；批准计划Ref单独保留在ContinuationSelection。`source_state`与原状态机列一致，rule才为null。触发决定必须属于同一execution/run。
3. SUBMISSION同一事务持久完整CommandRequest及完整RequestKey。request_digest只对CommandContent计算，排顶层context_id、idempotency_key、correlation_id；幂等键仍由RequestKey约束，不能因不进内容摘要而忽略。transport正文必须原样保存以支持审计。
4. 新增issuer_epoch持久列，唯一键为`(target_authority,target_database,issuer_id,issuer_epoch,principal_id,request_epoch,operation_id,idempotency_key)`。target_scope在SQL拆成两列；不能漏epoch，也不能加入设备/正文摘要把同键异内容变成第二次写。所有相关外键、查原、受理、拒收和Controller七元语义身份须同步升级。实际旧提交键带`sha256:`，与RequestKey词法不符；全新提交按`cmd_`加JCS({execution_id,step_id})的SHA-256十六进制生成，在原目标和主体命名空间内唯一，创建后固定。已经尝试的旧请求不得改键重试；本轮正例仅演示新写集，不是旧行转换。
5. Controller的ca_request_key.content_body保存同一完整CommandContent；cn_command的归属和摘要、ce_command及旧守卫中的`$.continuation`路径须统一迁到`$.automation_binding.continuation`，只允许完整原件关联，不再依赖registration_id出网。Guard、Permit和Intent对同一命令内容与新执行Ref重核。该更改必须与Seamer成套验证，不能只替换JSON路径后声明兼容。
6. 保留既有事务seal、准备归属、预算、审计/outbox、不可变性及崩溃时查原。新布局只面向新版干净库；旧数据不自动迁移，不重写已提交摘要。需要人工分析旧库时保留原版工具，绝不能向缺字段填默认控制版本、当前时间或空条件。

旧合成fixture的issuer_id和request_epoch也超出RequestKey原词法。它们是测试身份，不据此扩大全局命名空间接受集；新提供者必须在创建命名空间时使用契约合法ID并保留原件，不能运行时改名。新写集正例使用明确的合法合成命名空间，旧库差异仍登记，不声称原身份已转换。

核对器的`typed_projection_valid`只证明完整输入、列投影及选定原件一致，不是完整AdmissionSeal。完整提供者真实性、当前授权、预算、时钟及唯一出口门槛继续由最终事务核验。正例使用明确标注的新写集合成输入；实际三库仍保留原字节，旧正文不能直接出网的反例必须通过。

## 验收与剩余实施

[检查器](check_command_contract.py)验证生成可复现、API结构、全部认证/响应码、每个API类型与单一图一致、52帧引用解析、新转交/准备/手动正例、旧绑定拒绝、39字段覆盖及实际SQLite六类差异。另检验完整写集正例、错issuer_epoch/主体/幂等键、错执行列、把批准计划摘要当执行计划摘要、错决定与计划正文、把合成正文嫁接到旧行、运输字段及嵌套同名字段摘要规则。

当前未实施新版SQLite DDL和完整writer迁移；报告的`storage_migrated=false`是发布阻断，不是通过检查后的豁免。下一项必须把上述新布局和writer同时落实到候选组合库，逐写注入故障，验证新请求从计划、提交到Controller查原/拒收的完整路径，再归并最终AdmissionSeal。全系统SDK生成、真实HTTP/IPC和设备验证仍未执行，业务代码未修改。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_command_contract.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_command_contract.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_command_contract.py --check-report
```
