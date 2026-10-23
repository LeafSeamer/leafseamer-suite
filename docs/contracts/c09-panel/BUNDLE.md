# 面板 SchemaBundle 候选

状态：设计候选，未批准、未实现产品加载器。本稿与[bundle.schema.json](bundle.schema.json)、[人工用例](bundle-cases.json)、[离线检查器](check_bundle.py)共同细化 C09；不改已确认 draft.4／IPC 0.3，也不把现有 channel 0.1 消息悄悄扩字段。

## 1. 范围与来源

Bundle 用于能力参数、动作结果、状态、触发载荷及完整定义的批准展示 Schema。35 个方法的基础输入／21 个结果模型由 SDK 随 GUI 固定交付；`registry_ref` 绑定该基础 Registry 版本。Bundle 不是模块任意注册 HTTP 方法的入口，也不把全部公共／内部模型交给面板。

**规范事实**：JSON Schema 的 `$id` 是标识符，不保证可网络下载；引用可由预注册资源解析。将引用内联或改写为 `allOf` 可能改变语义，同一实例上的无限递归需要防护。（来源：[2020-12 Core §8.2.1、§9.1—9.4](https://json-schema.org/draft/2020-12/json-schema-core)）

**本项目推荐**：宿主先从批准安装产物取得已审阅的完整面板 Schema 文档，再按当前字段权限和能力版本选择 Bundle。不得把原始设备 Schema 临时删字段后沿用旧摘要／批准。专用投影文档须有自己的身份、版本和批准；功能不能因通用表单不支持而静默消失，须提供批准的专用面板或可信宿主入口。

## 2. 固定身份与字段

| 对象 | 字段及语义 |
| --- | --- |
| Manifest | `format_version,bundle_id,bundle_revision,registry_ref,scope_revision,profile_ref,dialect,resources,exports,manifest_digest`；完整对象封闭 |
| ResourceDescriptor | `schema_id,document_digest,canonical_bytes,chunks[]`；每块 `index,byte_count,digest`，index 从 0 连续；规范分块为每 16384 字节一块，末块可短 |
| Export | `binding_key,purpose,schema_ref`；purpose 为 parameters/action_result/state/trigger/definition；同 binding_key 不重复 |
| SchemaRef | `schema_id,definition,schema_digest`；definition 精确选择文档根 `$defs` 的一个具名 Schema；digest 覆盖完整文档，不是子树 |
| ProfileRef | `profile_id=panel-form-jsonschema-1,revision,digest`；绑定已批准规则与验证器配置；此摘要不证明批准来源 |

`schema_id` 限定 `urn:leafseamer:panel-schema:<Id>`。Manifest 不含端口或文档代次，投递信封含完整 PublicBinding。`resources` 按 schema_id、`exports` 按 binding_key 的 ASCII 顺序排列；不接受重复身份或同 URI 不同内容。数组次序纳入摘要，接收端不排序后宽容接受。

文档严格 UTF-8 JSON → JCS 字节 → SHA256；大整数遵守 DF01 字符串策略，不允许超安全整数借浮点解析改变值。文档不压缩；chunk 是这些字节的连续片段，逐块标准带 padding 的 base64，全部拼接后才解 UTF-8（可在多字节字符中间分块）。Manifest 摘要为删除**顶层** manifest_digest 后的 JCS；资源和 export 不反向含 Manifest 摘要，避免循环定义。

批准校验在可信宿主进行：当前安装批准仍有效、完整 Manifest 摘要／registry_ref／scope_revision／profile_ref 与权威预期一致、exports 完整匹配当前设备及能力版本的 binding_key 映射。Manifest 不自带可信布尔值。读缓存不授权限；即使重算全部公开摘要，批准或 scope 不匹配仍拒绝。合法 title／description／enum／const 字符串仍可能含秘密，完整批准与脱敏审阅不可由 Schema 合法性替代。

## 3. 本地 Schema profile

采用 2020-12 固定方言；每文档根 `$schema` 可省略但若有须完全匹配，根 `$id` 可省略但若有须等 schema_id。禁止嵌套 `$id`／`$schema`、`$dynamicRef`／`$dynamicAnchor`／`$vocabulary`、未知 keyword，以及 Schema 位置的 `$comment/default/examples` 和内容解码关键字。禁用默认值注入、类型强转、删除额外属性和编译期执行扩展。

允许普通 `$ref`、简单 ASCII `$anchor`、标准类型／数值／字符串长度／对象／数组断言、逻辑与条件应用器、readOnly/writeOnly/deprecated/title/description。`pattern` 与 `patternProperties` 的表达式必须在精确 profile 的批准列表中；`format` 也按同一 profile 的固定名称和实现映射批准，不加载网络词表。离线检查只核对批准名单，不执行这些模式或证明跨语言含义等价；生产编译和验证须隔离 worker，有时间／内存／步数预算，超限拒绝而不是当 valid。

只遍历真正的 Schema 位置：map 为 `$defs/properties/patternProperties/dependentSchemas`，array 为 `allOf/anyOf/oneOf/prefixItems`，single 为 `items/additionalProperties/propertyNames/contains/not/if/then/else/unevaluatedItems/unevaluatedProperties`。`const/enum` 中的 `$ref` 是实例数据，properties 中名为 `$ref` 的属性也不是引用关键字。

真实 `$ref` 只可指向本资源片段或 Bundle 中完整 URN，禁止相对路径、HTTP、file 及缺失资源。片段支持严格百分号 UTF-8 解码、JSON Pointer 的 `~0/~1` 和已登记锚点；目标必须是真正 Schema 位置，不能指向 enum/const 内即使长得像 Schema 的数据。所有资源必须从 exports 所在文档经真实引用可达；每个已交付文档的所有 Schema 位置均受检，包括未使用 `$defs`，不得附带无关资源。

普通引用以及 allOf/anyOf/oneOf/not/if/then/else/dependentSchemas 构成的同实例环拒绝；经 properties/items 等下降到子实例的递归可保留，但仍受运行实例深度和执行预算保护。不能将“禁止所有环”当作完整定义语言交付。

## 4. 投递与激活

本批新增四种局部消息，协议标为 `panel-channel/0.2.0-draft.1`：`host.bundle_offer(manifest)`、`host.bundle_chunk(bundle_id,manifest_digest,schema_id,index,content_base64)`、`panel.bundle_ready(bundle_id,manifest_digest,registry_ref,scope_revision)`、`host.bundle_revoke(bundle_id,manifest_digest,reason_code)`。全部携带 PublicBinding 和每方向 channel_sequence；不得向 0.1 接收者混投。

完整新版 channel 的后续候选见[CHANNEL_V02](CHANNEL_V02.md)：新版 `host.active` 通过ActivationRef固定 `bundle_id,manifest_digest,registry_ref,scope_revision`，方法调用及结果绑定同一激活的 Registry 和动态 exports。旧 Active 无这些字段，不能上线时临时附加。本Bundle批次只机器定义四种消息；其离线轨迹的 activate/use 仍是模型动作，新增完整帧与联接由0.2独立报告验证，不改变本批109项的覆盖范围。

状态序列：inactive → staging → verified → ready_reported → active；任一错误 → failed；revoke／scope 变更／关闭／文档换代 → revoked。初次加载不开放表单；更新先关闭旧 Bundle 使用资格，新 Bundle 验证成功后才能重新激活。每会话最多一个 staging；不得并行拼接不同 Manifest。

接收先验当前端口、方向、PublicBinding、序号和消息字节预算，再暂存。序号严格增长，不接收相同序号重放；不同新序号投递同一 index 且同字节可幂等去重，仍计流量预算。同 index 异内容、未知 index、错摘要或多余块拒绝。缺块不能 verified；所有块收到不代表 ready。宿主收到 ready 后重新核对权威批准／scope 再激活，面板自报 ready 不能授予执行权。普通传输 ACK 只确认接收，ready 只说明 Schema 加载，不代表命令、设备或数据库完成。

撤销在宿主权威处立即停止接受新调用，不能等待面板收到通知。已受理命令仍按原生命周期查询和核对，不因 Bundle 关闭变成未发送；不重放旧输入或写队列。缓存只保存字节，下一会话重新核对完整绑定和批准；无法抹掉此前已显示的数据。失效通知可能晚到，服务端最终受理仍须重查权限和版本，不能靠浏览器撤销提供原子保证。

## 5. 容量候选与故障验收

实验上限：文档 256 KiB／16 块，块 16 KiB；每 Bundle 32 资源、128 exports、累计文档 1 MiB、累计 64 块；Manifest 及每个完整 JSON 消息 64 KiB。JSON 容器深度最多 64；每文档 Schema 节点 4096、全 Bundle 8192、真实 refs 4096。超限完整拒绝、不截断。分块总数独立受限，许多小文档不能借总字节低绕过帧预算。参考检查对消息使用规范化后的字节计数；生产还必须在解析前按实际线字节限流，不能让空白膨胀绕过。运行还须冻结 staging 超时、重复帧流量、worker CPU／内存与全会话并发预算；本批未作性能批准。

一个 Bundle 覆盖一个当前授权表单上下文；大模块可以按当前选定能力拆成独立上下文并各自重新激活，不能拼接多个不完整 Bundle 后声称某个 Registry 已整体批准。完整定义编辑所需闭包必须整份可见且合格，超限则需批准的新预算或专用入口，不能裁剪后保存。

| 验收场景 | 必须观察的结果 |
| --- | --- |
| 外部 URI、缺依赖、指向实例数据、重复锚点、同实例环 | 离线拒绝；生产不发出网络／磁盘读取 |
| 重算摘要但安装撤销、scope／Registry 改变 | 仍拒绝；不得只检查内容完整性 |
| 缺块、同序重放、同块异内容、错代次 | 无激活；错误进入 failed，须新会话重新交付 |
| ready 后撤权，再 activate/use | 拒绝，旧 ready 不恢复资格 |
| 重复块用新序号、乱序 index、UTF-8 字符跨块 | 完整校验后可通过；不把单块当文本解析 |
| 子实例递归、const 的假 ref、普通业务字段名 `$ref` | 合法 profile 可通过，避免过度拒绝导致功能退化 |
| 合法 description 含合成敏感字样 | 结构检查可能通过；作为限制反证，必须保留人工／权威投影审阅 |

## 6. 已执行与待归并

运行 `docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_bundle.py --report` 生成[bundle-report.json](bundle-report.json)。`--check-report`／`--check-report --staged` 只核对本稿、Schema、用例和检查器四输入原字节，不重跑用例；该报告独立于顶层旧十份清单。

109项包括73个Bundle结构／闭包／批准例、14个信封例及22条人工轨迹。检查器实际计算 JCS、文档／块／Manifest 摘要、引用闭包与同实例环，按人工可信上下文检查批准，并运行有限投递轨迹；没有浏览器、真实身份、服务端事务、worker 沙箱、任意 Schema 实例验证或设备测试。可信权威由夹具假定，完整新版 channel、Registry 导出生成、实际过滤器、宿主加载器、HTTP／IPC／DDL 和原始输入预算仍待联合归并及运行验证，不能把本批当作完整 SDK 或运行批准。
