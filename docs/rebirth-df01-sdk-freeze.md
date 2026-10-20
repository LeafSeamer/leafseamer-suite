# DF01：SDK契约源、生成工具链与跨语言规范化冻结方案

日期：2026-10-17。用户已同意公共 `1.0.0-draft.4`／`ipc/0.3.0-draft.1` 归并基线。本轮更新设计与离线验证资料，不迁移SDK源、不安装工具链、不生成产品SDK或修改业务代码。下文D1—D6为本轮推荐，版本候选不等于发行物或运行验证已批准。

## 1. 已知事实及本轮发现

项目当前的draft4生成器读取draft3生成物，判定器继续复用旧轮Python规则；SDK仓库仍是施工入口。当前已有185个公共类型、19类IPC消息、71个HTTP／WS操作和232个离线用例。这些是迁移的核对基线，不是SDK已拥有唯一权威源。（项目依据：[生成资料](contracts/draft4/README.md)、[归并审阅](rebirth-draft4-review.md)）

官方 `openapi-typescript@7.13.0` 的peer约束为 TypeScript `^5.x`，并使用JS编译器API；不能按前稿的6.0试验起点直接宣称兼容。它生成声明，不替代运行校验；条件分支、整数精度及ref兄弟约束仍需单独验证。（来源：[固定版本package](https://raw.githubusercontent.com/openapi-ts/openapi-typescript/openapi-typescript@7.13.0/packages/openapi-typescript/package.json)、[固定版本转换实现](https://raw.githubusercontent.com/openapi-ts/openapi-typescript/openapi-typescript@7.13.0/packages/openapi-typescript/src/transform/schema-object.ts)）

JCS采用UTF-16代码单元的对象键排序及UTF-8输出，保留数组顺序和Unicode原形式，数值遵循ECMAScript binary64；普通JSON.parse会覆盖重复键。因此原始JSON入口、Schema、语义和JCS必须分层，不能只调用JSON.parse后计算摘要。（来源：[RFC8785](https://www.rfc-editor.org/rfc/rfc8785)、[ECMAScript JSON.parse](https://tc39.es/ecma262/multipage/structured-data.html#sec-json.parse)）

本地审阅发现三个必须显式登记的边界：Revision最多20字符，并非uint64；有符号纳秒允许字符串`-0`且正数可有25位；现有Python Schema校验器实际接受Revision `"1\n"`，因为正则末尾`$`允许终止换行前匹配。最后一项是需要修订的词法缺口；不能在源提取的同版本等价报告中隐藏它。（项目依据：[Schema](contracts/draft4/first-loop.schema.json)、[参考报告](contracts/df01/reference-report.json)）

## 2. D1：唯一权威源与迁移切换

推荐权威归属为 **leafseamer-sdk仓库中的版本化、纯数据契约树**。单一来源不等于一个文件，更不等于只保留Schema。建议目录如下；本轮仅定义目标，尚未创建产品目录：

```text
contracts/source/<contract-release>/
  public.schema.json          公共模型，保留draft4原有$id及约束
  ipc.schema.json             IPC本地模型及对公共模型的引用
  http/controller.operations.json
  http/seamer.operations.json 请求/响应、参数、headers、security及WS升级完整声明
  semantic-rules.json         规则ID、对象边界、错误码、执行责任及用例映射
  digest-projections.json     每种摘要的投影、排除字段、顺序与缺省处理
  exports.json                对外/内部导出、模型根、协议及特性矩阵
  fixtures/                  固定正反例及权威预期；不可由被测实现反推
  source-manifest.json        文件路径及SHA-256、来源版本、许可与批准记录
tools/                       固定的生成/检查程序及配置
generated/                   生成物，只能由上述输入与工具链产生
```

不能仅复制现有routes.json：该表未独立承载全部WS升级、安全方案、headers及其他OpenAPI元数据。迁移必须从两份完整OpenAPI与生成源提取这些声明，逐操作对账。SchemaDescriptor等模块动态Schema仍由注册的能力约束二次校验；它不允许模块覆写首方协议模型。

迁移顺序固定为：

1. 记录draft4六份机器输入的逐文件SHA-256及232例预期、规则／摘要投影清单，保存历史归档。
2. 在SDK中提取自包含源，消除任何对Suite Python历史、外部主分支和本机绝对路径的生成／运行依赖。提取阶段保持原$id、协议版本和语义，不顺手修协议。
3. 两边生成物按解析后的完整JSON逐节点比较，不忽略约束、注解、安全或错误响应；本轮目标优先逐字节复现。若只有格式变化，必须单独列出字节差异及JCS内容摘要，不能以“相同模型数量”代替等价证明。
4. 旧正反例全部复验，新增关键字／原始输入／跨语言用例；出现接受集合变化则停止等价切换，登记新协议修订，不能把旧失败改为通过凑数。
5. 只有源提取与生成验收都通过，才能把SDK版本发布为权威。Suite通过精确契约版本、发布文件摘要及来源commit引用；旧Suite生成器降为归档复验入口，禁止双向同步编辑。

SDK包版本、公共协议版本、IPC版本、工具链版本四者独立记录。一个兼容组合清单精确绑定它们；预发布协议不按“同major大概兼容”放行。正式npm scope和发布权限留待核验，不占用或发布包名。

## 3. D2：固定生成链与候选版本

以下是已核验官方标签／声明的**待实测候选组合**；下载包integrity、完整传递锁、Node二进制校验和各平台实际安装尚未完成。

| 用途 | 精确候选 | 依据及冻结边界 |
| --- | --- | --- |
| 构建运行时 | Node 24.22.0、内附npm 11.19.1 | [Node发布](https://nodejs.org/en/blog/release/v24.22.0)、[随附npm](https://raw.githubusercontent.com/nodejs/node/v24.22.0/deps/npm/package.json)；不将本机24.11.1试验记作此组合验收 |
| 生成器编译器 | TypeScript 5.9.3 | [官方标签](https://raw.githubusercontent.com/microsoft/TypeScript/v5.9.3/package.json)；满足生成器^5.x，替代前稿6.0候选起点 |
| HTTP类型生成 | openapi-typescript 7.13.0 | [官方标签](https://raw.githubusercontent.com/openapi-ts/openapi-typescript/openapi-typescript@7.13.0/packages/openapi-typescript/package.json)；传递的Redocly与helpers也必须锁定 |
| HTTP薄客户端 | openapi-fetch 0.17.0 | [官方标签](https://raw.githubusercontent.com/openapi-ts/openapi-typescript/openapi-fetch@0.17.0/packages/openapi-fetch/package.json)；不自动授予重试或设备完成语义 |
| Schema／standalone | Ajv 8.20.0、ajv-formats 3.0.1 | [Ajv发布](https://github.com/ajv-validator/ajv/releases/tag/v8.20.0)、[formats清单](https://raw.githubusercontent.com/ajv-validator/ajv-formats/v3.0.1/package.json)；使用同一Ajv解析实例 |
| JS JCS | canonicalize 5.1.0 | [正式Release](https://github.com/erdtman/canonicalize/releases/tag/v5.1.0)、[固定标签](https://raw.githubusercontent.com/erdtman/canonicalize/v5.1.0/package.json)；ESM、Node≥22，npm下载物完整性仍未核验 |
| 另一语言参考检查 | Python rfc8785 0.1.4 | 既有[验证依赖锁](contracts/requirements-validation.lock.txt)；这是另一语言实现，不能声称算法来源完全独立 |

生成器固定5.9.3不限制协议消费语言，也不强制未来服务代码永远使用该编译器。消费项目至少用5.9.3验证声明；6.x／7.x等新增消费组合必须另测，不能用peer override或`--legacy-peer-deps`伪装组合兼容。

构建锁定清单必须包含：lock_schema_version、source_release与源文件hash、完整git commit、Node版本／平台文件hash、npm版本、package-lock SHA-256、直接及传递依赖的version／resolved／integrity、工具源码及配置摘要、投影规则版本、导出名映射、输入／输出文件hash、许可清单、测试报告和批准状态。未验证值保留“待核验”，禁止使用假的零hash填成release-ready。

生成顺序：检查封闭引用图与源清单 → 组装两份自包含OpenAPI及IPC类型投影 → openapi-typescript输出声明 → Ajv2020预编译各模型根 → 构建少量手写门面与语义校验 → 全套验收 → 生成制品清单。IPC-only类型可使用components-only投影，不能捏造HTTP路径，也不能反过来以OpenAPI投影替代IPC原Schema。

所有 `$id` 是标识符；建立显式 `$id → 本地文件` 映射，拒绝未知远程ref、越界路径和主机路径。所有引用预注册，禁止运行时网络拉取Schema。生成产物无日期、随机值和绝对路径；UTF-8、LF、确定性文件顺序。两次干净生成及Windows／Linux生成均需字节对比；安装阶段与生成阶段分开取证。不要以一次npm ci成功宣称可复现。

## 4. D3：校验与生成不得改变输入

推荐 `Ajv2020` 专用入口，`strict:true`、`strictRequired:true`、`validateFormats:true`、`coerceTypes:false`、`useDefaults:false`、`removeAdditional:false`、`code:{source:true,esm:true}`；formats选full模式且只注册实际使用项。编译警告作为失败逐路径处理，不整体关闭strict。（来源：[Ajv严格模式](https://ajv.js.org/strict-mode.html)、[选项](https://ajv.js.org/options.html)、[standalone](https://ajv.js.org/standalone.html)）

draft4的`/$defs/SchemaDescriptor/properties/document`使用`type:[object,boolean]`。推荐允许`allowUnionTypes:true`，同时生成前lint将这个例外**仅限该路径与该集合**；新增union须审阅。若其余strictRequired／strictTypes失败，先给具体路径和语义等价证据，禁止猜测全部条件分支都失败，禁止自动删关键字“修复”。源提取等价检查与后续严格模式修订分别记账。

standalone可能保留Ajv runtime／format helper依赖，必须检查生成imports及最终依赖清单；浏览器使用构建后的ESM入口，禁止引入Node原生库、fs或运行时Schema编译。无unsafe-eval的CSP实测是独立用例，不能以code.esm=true推定通过。（来源：[standalone说明](https://ajv.js.org/standalone.html)、[formats兼容说明](https://ajv.js.org/guide/formats.html)）

类型较宽可接受，但必须标注“需要运行验证”；Schema不能因TS类型较宽而放松。输入／输出都验证；WS升级不替代每条事件验证。2026-10-18修正：客户端须有界读取原始响应bytes后严格UTF-8解码，不能先用response.json或text解析模式；后者也可能丢失非法字节证据。204等无体响应独立处理，错误体不当成功数据解析。具体入口及新增候选见第8节。（依据：[Fetch Body](https://fetch.spec.whatwg.org/#body-mixin)、[Encoding](https://encoding.spec.whatwg.org/#interface-textdecoder)）

语义层包含摘要、域、关联、年龄及版本等纯判定；授权权威、事务、真实屏障和设备效果仍属于服务。生成TS声明或校验函数不生成状态机、重试和设备执行器。

## 5. D4：JCS、原始输入与摘要投影

推荐顺序：有界原始bytes → 严格UTF-8与JSON token／键对解析 → Schema形状 → 跨字段语义及注册能力Schema → 指定摘要投影 → RFC8785 JCS → UTF-8 bytes → SHA-256。

入口必须在丢失信息前拒绝重复的**解码后键名**、非法UTF-8、孤立代理项、非有限数字；按I-JSON入口拒绝Unicode非字符。JSON.parse后的reviver、Ajv以及JCS库均不能恢复被覆盖的键。Python参考检查先decode('utf-8')，不能依靠json.loads(bytes)自动接受其他编码。（来源：[RFC7493 §2](https://www.rfc-editor.org/rfc/rfc7493)、[Python json](https://docs.python.org/3/library/json.html)）

SDK门面只接收已验证的纯JSON DTO；Date、Map、Set、BigInt值、undefined、稀疏数组、访问器、自定义toJSON、循环引用和其他可执行对象不进入摘要。原型特殊键按数据处理，不能通过赋值污染原型。上游canonicalize会处理toJSON和undefined，项目必须先门控，不能借其便利转换改变签名输入。（来源：[固定实现](https://raw.githubusercontent.com/erdtman/canonicalize/v5.1.0/lib/canonicalize.js)）

每种摘要使用具名函数和投影注册项，禁止公开一个可随意调用的“删掉所有digest字段再hash”工具：

| 摘要 | 冻结投影 |
| --- | --- |
| descriptor_digest | 排除自身及派生clock_domain_id；其余完整保留 |
| profile／evidence／guard／preview digest | 各自只排除本对象指定摘要字段；保留嵌套digest和域引用 |
| sample_digest | 完整ClockSample，包含evidence／profile引用 |
| content_digest | 按操作既有请求身份投影；只排除指定顶层字段，acquireControl的force缺省规则单独登记 |
| ledger_digest | 按既有permit_id顺序规范排序、拒绝重复后JCS；不是任意数组通用排序 |
| definition／bindings／plan | 逐项搬迁原有投影和排序规则，保持independence_proof排除及action_bindings顺序的原规则 |
| 制品文件hash | 原始发布文件bytes的SHA-256；不能拿JCS内容hash替代文件完整性hash |

C04补充发现：原definition投影递归删除带step_id对象的independence_proof，会误伤开放业务参数；proof扫描也可能误识别同名键。上表只约束**源提取等价阶段**，不主张永久保留该缺陷。[C04 AR02](rebirth-c04-automation-design.md#3-ar02发布产物完整依赖图和证明容量)推荐下一版分离program与proof，并限定Schema步骤路径；需显式协议修订与新旧差分，不能在draft.4里悄然修正。

空白和对象键排列不同可得同一摘要；null与缺失、数组换序、组合／分解Unicode、不同十进制字符串必须保持可区分，除非指定投影明确排除。既有sha256输出不加新前缀参与计算、不改盐；类型隔离通过具名接口和协议上下文达成，新增密码学域分隔需新协议版本。

## 6. D5：大整数和精确算术

普通JSON integer受字段范围及安全整数边界约束，必须从原始token证明其数学值可接受。整数路径中的`1.0000000000000001`不能先舍入为1；`9007199254740993`不能舍入后通过。`1.0`与`1e0`的数学值是安全整数，可规范为JCS的1，除非字段明令禁止该词法。扩展模块需要小数时明确声明binary64近似语义；金钱／精确十进制量采用带格式和量纲的字符串，不通过浮点猜回原值。

wire上的revision、sequence、tick及纳秒继续保持字符串；TS生成DTO是string，验证后可用带品牌类型标示用途。TS计算用BigInt，Python用int/Fraction，其他语言用满足范围的整数或大整数。SQLite映射不在本轮擅自改成INTEGER，超出有符号64位的字段由DF04单独冻结。禁止Number、parseInt和double中转；日期转换只能在证明范围后执行。

| 类别 | 本次迁移保持的draft4规则 | 后续建议 |
| --- | --- | --- |
| Revision及旧tick引用 | `^(0\|[1-9][0-9]*)$`，最多20字符 | 不是uint64；最大可表达99999999999999999999，增长溢出须拒绝，不环绕 |
| NF无符号ns | 同词法，最多24字符 | 不强制截成64位；平台读数较小不改变wire范围 |
| NF有符号ns | `^-?(0\|[1-9][0-9]*)$`，总长最多25 | 当前允许字符串-0；提取时保留，后续显式版本修订才禁止-0及统一符号外位数 |
| JSON整数 | 字段范围与±9007199254740991交集 | 保留token证据，Schema单独无法证明未发生舍入 |

字符串`-0`和`0`在draft4中是两个不同摘要输入，即使内部算术都为零也不得自动重写。建议下一次协议修订采用`^(0\|-?[1-9][0-9]*)$`并明确定义幅值上限；这是**待确认的收窄**，本轮不改已确认Schema。20／24／25字符边界同样不允许迁移时暗改。

上述数学词法还必须做**全串匹配**，不能仅依赖`$`。推荐下一版用末尾负向全字符断言，例如无符号`^(0|[1-9][0-9]*)(?![\s\S])`，并以尾部LF／CRLF反例验证Python与JS。所有安全相关的Id／Digest／Revision／ns正则都按同一方法盘点；本轮只证明Revision已有此缺口，不声称已修复其他字段。源提取可以保留draft4复验，但**正式SDK放行前必须完成显式协议修订及其接受集差异测试**。不对输入trim后再计算摘要，也不通过修改旧fixture掩盖差异。

时间算术以精确整数／有理数实现；统一正分母，定义数学floor_div和ceil_div，显式覆盖负数。JS BigInt除法朝零截断，不能直接代替floor；所有中间量精确，最后按DF/NF规则向外舍入。采样年龄严格小于阈值、误差允许等于阈值、排期右界等号拒绝的规则保持不变。

## 7. D6：验证矩阵和放行条件

每条用例记录输入原始bytes、适用模型／版本、预期失败层、canonical bytes／摘要或数值预期、实际工具版本和结果。预期由人工审阅后固定，不在运行时用被测实现生成。库合规和项目wire配置分组：通用JCS允许的binary64样本不自动成为项目整数许可。

| 编号 | 用例 | 通过条件 |
| --- | --- | --- |
| SV01 | SDK独立clone，无Suite源码和网络ref | 完整生成成功，封闭源图无外部构建依赖 |
| SV02 | 185类型、19消息、71操作及全部安全／错误／WS声明对账 | 无漏项、逐节点等价；数量相同仅为辅助 |
| SV03 | 原draft4全部232例与对应结构／语义分层 | 预期不变；不得把语义例误计成Ajv自动证明 |
| SV04 | 双次干净生成、Windows／Linux、不同目录／locale | 文件字节相同，无时间及主机路径漂移 |
| SV05 | 精确npm锁、严格peer、空缓存受控安装 | 无浮动解析／绕peer，工具与依赖完整性可追溯 |
| SV06 | 原Schema与派生OpenAPI／IPC类型视图 | if/then、ref兄弟约束、oneOf、未知字段接受集不变 |
| SV07 | Ajv运行编译与standalone对同例比对 | 结果一致且输入未被改写；未知format／keyword/ref失败 |
| SV08 | TS消费编译的正例和@ts-expect-error；TS可赋值而Schema非法 | 声明适用边界明确，运行负例仍拒绝 |
| SV09 | Node／浏览器ESM与CSP无unsafe-eval | 实际加载通过，无原生/fs/动态编译依赖泄漏 |
| SV10 | HTTP／WS原始重复转义键、畸形UTF8、数字token | 在解析信息丢失前拒绝；204和错误体独立 |
| SV11 | 数字键10/2、U+10000与U+E000排序、嵌套数组 | 与固定canonical UTF8及SHA-256完全相同 |
| SV12 | NFC/NFD、null/缺失、数组换序 | 不错误合并不同摘要输入 |
| SV13 | binary64位模式／指数边界／负零、非有限数 | 符合JCS；Python int与float语义差异单列 |
| SV14 | 2^53±边界、20位Revision、24/25位ns、非规范词法 | 无Number往返；保留draft4范围和-0字符串原值 |
| SV15 | 负偏移、1ns外推、floor／ceil、上限等号 | 两语言精确结果一致，溢出失败不环绕 |
| SV16 | 所有具名摘要投影及重算摘要后的错配 | 投影一致，错误身份／域／引用仍拒绝 |
| SV17 | toJSON、getter、undefined、稀疏数组、原型特殊键 | SDK门面不执行或悄悄改写这些输入 |
| SV18 | 模块动态Schema的大小／深度／正则与ref边界 | 不进入无界编译，严格注册审批及隔离预算 |
| SV19 | 依赖版本、Schema、规则或projection单项变更 | 变更分类准确；阻断静默混搭及旧写降级 |
| SV20 | 打包安装后的SDK脱离开发树，校验生成文件篡改 | 消费只需发布包；hash不符拒绝，不读Suite回退 |

本轮附[固定向量与参考检查](contracts/df01/README.md)，只核验部分JCS、字符串边界及数学规则；它们不等于SV01—SV20全通过。正式SDK选择成熟JCS库；旧validate_vectors.cjs的小型递归排序器只保留历史用例角色，不升级成生产实现。

正式SDK放行需同时具备：用户确认推荐、源提取等价报告、精确锁及制品来源、生成／校验／消费报告、跨语言固定向量、浏览器CSP和平台构建证明。2026-10-18第8/9节补出严格解码路径、有限预算、完整生成元数据及拒绝规则的具体候选；这些设计待审阅，实际npm闭包、Ajv派生视图、各语言适配与数字新版修订仍未完成。GUI已有[精确候选](rebirth-toolchain-lock-design.md)，不再视为未选型。设计定稿门槛与正式SDK运行放行分开，不要求产品未实现前先通过运行验收。

## 8. D3—D5补充：严格入口的具体候选

本节是基于规范与现有契约的工程推荐，尚未批准或实现。选用SDK内小型、迭代式原始JSON审计扫描器，加平台JSON.parse构造值及Ajv派生校验；不选择让第三方宽松解析器替换协议语法。扫描器只承担语法/字符/重复键/预算/数字token留存，不实现Schema、授权或执行器；JCS继续使用既定库。新增扫描器属于需要独立差分与模糊测试的安全边界，不能因代码少便省略验收。

### 8.1 输入、阶段及字节所有权

建议内部入口为`decodeWire(bytes, modelRef, profileRef, dynamicSchemaRef?)`，结果只返回不可变DTO或结构化错误。模型、预算与动态能力Schema引用由可信路由/批准目录选择，不能由请求体自行声明以扩大限制。入口先复制或转移原始缓冲区所有权，拒绝SharedArrayBuffer及可并发变更视图；扫描、构值、摘要必须使用同一份未改写输入。token表只在本次校验内有效，不进入日志、事件或公开响应。

顺序固定：入口媒体类型/长度/权限预算 → 原始bytes上限与BOM检查 → fatal UTF-8解码 → 完整JSON审计扫描 → JSON.parse同一文本（无reviver） → 带token上下文的Schema与能力Schema → 关联语义/具名投影/JCS。扫描失败不构造DTO、计算可受理摘要或产生设备命令。入口鉴权/限流可以在读取前拒绝，错误优先级不承诺向未授权用户揭示报文细节。

HTTP客户端使用Response.body有界读取并及时cancel，不能只信Content-Length，也不先执行无界arrayBuffer；Node服务禁止中间件预先json/text转换。首期业务JSON请求不接受Content-Encoding压缩，响应读取限制按实际解码后bytes计；代理与浏览器内部解压内存不由SDK完全控制，发布验证须单独覆盖。无体状态不得送JSON解析器，错误响应同样有界。（Fetch的text使用平台UTF-8 decode；Encoding默认替换错误，fatal才报错，BOM还可能被去除。来源：[Fetch](https://fetch.spec.whatwg.org/#dom-body-text)、[Encoding](https://encoding.spec.whatwg.org/#interface-textdecoder)。）

网络入口显式拒绝开头EF BB BF；解码使用`TextDecoder('utf-8',{fatal:true,ignoreBOM:true})`以保留而非暗吞BOM，再由入口规则拒绝。拒绝BOM是本项目候选收紧，RFC8259允许接收器选择忽略，不能声称标准强制拒绝。字符串内部U+FEFF按普通字符保留。（来源：[RFC8259 §8.1](https://www.rfc-editor.org/rfc/rfc8259#section-8.1)。）

WS text只在完整消息重组后校验；服务端库必须在重组中限制帧和消息，首期不协商压缩。浏览器收到的text已由WS实现做UTF-8处理，SDK再检查字符、JSON和编码后的字节预算；不能声称SDK能在浏览器分配消息前拦截。二进制帧除非特性明确注册，否则拒绝。IPC按长度前缀限制后读取，拆包/粘包不改变JSON消息边界。（UTF-8错误须失败连接的规范依据：[RFC6455 §8.1](https://www.rfc-editor.org/rfc/rfc6455#section-8.1)。）

### 8.2 扫描器与精确数字守卫

扫描器采用显式容器栈：object的key/colon/value/comma-or-end状态，array的value-or-end/comma-or-end状态；只允许一份根JSON及末尾JSON空白，拒绝尾逗号、注释、拼接根和截断。每个object维护独立解码键集合，重复比较不做NFC/NFD转换。键和值均拒绝孤立代理及非字符U+FDD0—FDEF、各平面末尾FFFE/FFFF；合法代理对先组合为scalar。JSON Pointer保留空键并转义`~`、`/`，数组序号为十进制；`__proto__`等作为自身数据属性，不走对象赋值合并。（字符和重复键依据：[RFC7493 §2](https://www.rfc-editor.org/rfc/rfc7493#section-2)。）

每个数字保留`instance_pointer`、原始半开字节区间、token文本、符号、有效数字及十进制指数。按JSON数字文法扫描，不调用parseInt/parseFloat猜前缀；先计token长度和指数预算，再进行数学判定。将系数尾零消去后，以小数位数和指数计算是否为数学整数；比较位数及字典序即可先拒绝超安全范围，禁止按攻击者指数构造巨大的10的幂。`1.0`/`1e0`可作为整数，`1.0000000000000001`不可。

所有数字先要求转换后的binary64有限；非零数学值转换为0推荐拒绝为`number_underflow`，这是项目候选收紧，不是JCS原规则。普通number字段明确接受binary64近似，精确十进制必须使用带单位字符串；不对所有number强套安全整数范围。integer字段额外要求原始数学值为整数且绝对值不超过9007199254740991，之后再受字段minimum/maximum约束。JSON number的-0按JCS成为0；字符串"-0"仍按所属协议版本处理。

**类型归属不得用字段名或一次预选分支猜测。** 推荐生成仅供SDK校验的私有Schema视图，在每个含integer类型的子Schema挂接原始整数守卫；守卫位于相同的if/then/else、allOf/anyOf/oneOf、ref分支中，nullable的非数字值不调用。含number的union不误收紧成integer；共享ref以同一转换规则处理。模块提供的Schema同样受批准编译流程，不能上传自定义守卫代码。公共权威Schema不含私有关键字，生成清单记录源JSON Pointer→派生节点及转换器摘要。

候选实现使用Ajv的code关键字及`passContext:true`传入请求专属只读token表，关键字按instancePath查原始token；缺表/缺路径一律失败，不能回落到舍入后的值。禁止全局currentTokens、异步共享上下文或修改输入；按原分支组合求值，失败分支不产生资格。Ajv官方提供自定义关键字/上下文/standalone机制，但**尚未验证本组合中ref、条件、生成代码的上下文传播**；SV07/SV10必须覆盖运行编译与standalone差分，失败则修订该适配，不能删除守卫放行。（来源：[Ajv options](https://ajv.js.org/options.html#passcontext)、[keywords](https://ajv.js.org/keywords.html)、[standalone](https://ajv.js.org/standalone.html)。）

开放Payload先保留数字token，随后按精确能力Schema二次校验；没有获批Schema的设备写参数不受理。SchemaDescriptor.document自身是JSON数据，内部minimum/enum等数字不能靠外层integer路径自动覆盖，必须在动态Schema批准时验证其数值表示及语义。SDK接受同进程对象的便利门面只面向可信调用代码；不能承诺检测任意Proxy而完全不触发其陷阱。不可信模块只跨受限bytes边界，深冻结DTO也不代替进程隔离。

### 8.3 有限预算与失败

候选`sim-df01-wire-v1`仅用于故障夹具：普通HTTP/WS单消息65536 bytes、深度32、总值节点16384、每object成员4096、单键解码UTF-8 1024 bytes、单字符串解码UTF-8 32768 bytes、数字token128 ASCII字符、指数绝对值4096；含根容器深度从1计，标量根深度0，键不计值节点。所有上限允许等号、超1拒绝；原始总字节含空白/转义，token不含周围空白，解码字符串上限与原字节上限都检查。没有限制用null/0/Infinity关闭的模式。

这些值与C05普通消息、F04深度候选对齐，**不批准生产吞吐或承诺全部4096步定义都能放入64KiB**。snapshot页、定义/证明发布和IPC各有独立有限profile，由可信操作绑定；同一入口同时适用的预算取最严格者。大型产物不能借普通命令接口绕过限制，完整发布字节预算仍随C04/C05联合归并。不得默默截断、自动分拆执行或按客户端字段切换大profile。

内存累计计原bytes、解码文本、键集合、token表、DTO及生成校验开销，不只计网络体积。扫描器按输入字节/解码字符/节点操作计步，每4096单位检查取消并让出执行；在独立有界worker池处理大消息，保护IPC有独立预留通路。候选普通解析deadline100ms，由本地单调时钟计，自开始处理到完成；超时取消不能受理，非实时停发保证。发布profile必须测最坏内存、CPU、worker排队及保护通路延迟，未达标时收紧容量或优化，不能直接把此实验值作为生产配置。

错误内部形状为`{stage,reason_code,byte_offset?,instance_pointer?}`，偏移从0计，EOF指向总字节数；只返回首个确定错误，不暴露原文/重复键名/秘密。公有响应按已确认错误模型映射，安全路径使用已登记字段名或省略；不可直接输出攻击者键组成的pointer。UTF-8/JSON/词法错误归无效输入，预算超限归容量拒绝；上游响应非法是SDK协议错误，不是服务已拒绝或命令失败。已提交写操作遇非法响应仍须查询原operation，禁止因此重发。

## 9. D1—D2补充：生成元数据的完整性

当前源码对账：routes有52条九字段定义（common17、Controller21、Seamer14），展开后69个普通HTTP操作，加两服务各1个WS升级即71；WS的安全/Origin/子协议/票据及帧引用不在routes中。首次issueWsTicket的201秘密响应与重复200绑定响应、登录Set-Cookie/X-CSRF-Token/Cache-Control均须保留。公共Schema的86个integer和5个number节点包含条件重复约束；number实际用于JsonValue及ClockStatus两个字段。CapacityStatus.usage的used/limit没有maximum，SDK安全整数守卫仍适用。IPC evidence payload的空对象Schema另受allOf分流，不能当作最终无约束；SchemaDescriptor.document才是待二次批准的开放文档。（来源：当前[路由](contracts/draft4/routes.json)、[Controller OpenAPI](contracts/draft4/controller.openapi.json)、[公共Schema](contracts/draft4/first-loop.schema.json)、[IPC](contracts/draft4/ipc.schema.json)；本轮只读逐节点核对。）

权威HTTP源推荐保存完整OpenAPI文档骨架，包括root、Path Item、Operation和所有非schemas components；`components.schemas`只由公共Schema导出映射生成，不手写第二份模型。第2节的`http/*.operations.json`据此包含完整骨架，而非routes九字段表。保留所有headers、参数required/style/explode、requestBody、各状态/content、security、servers、tags、描述、x-*及WS升级声明；空security与继承security不能混同。原完整OpenAPI留作迁移对账输入，生成时不得从旧Python补默认值。

| 源记录 | 必须字段与关联规则 |
| --- | --- |
| source-manifest | source_release、schema_dialect、public_protocol、ipc_protocol、文件path/role/原始sha256、上游来源及许可引用；自身不列自身hash，外层批准记录绑定整个manifest |
| schema_registry | 唯一$id→本地file；export_name→model_pointer、public/internal可见性；ref解析封闭、同$id不同内容拒绝，内部类型不得意外公开 |
| http_binding | service、operation_id、HTTP源path及operation_pointer、request/response各自wire_profile_ref、semantic_rule_ids；唯一键为(service,operation_id)，共用操作在两服务分别绑定 |
| ws_binding | service、upgrade_operation_id、subprotocol、双向message_root及wire_profile_ref、ticket/ACK语义规则、关闭原因映射；HTTP101不能代替帧契约 |
| ipc_binding | ipc_protocol、message_kind、方向、message_root、wire_profile_ref及semantic_rule_ids；与全部19类历史消息对账，新增另版 |
| digest-projections | projection_id/version、input_model_ref、精确字段路径/缺省/排序/排除规则、规范化算法及fixture_ids；不允许递归按字段名删除；历史有缺陷投影只在等价包保留 |
| semantic-rules | rule_id、输入根/关联引用、失败码、执行层、fixture_ids、实现符号映射；代码实现由规则追踪，纯数据说明不冒充可运行判定 |
| generated-manifest | 原始源清单hash、完整工具锁hash、编译器/转换器配置hash、输出path/role/hash、源节点→输出节点映射、验证报告引用；生成记录与输入源分开，避免循环hash |

公开/内部、HTTP/WS/IPC目录都以具名根注册，不把所有$defs自动导出。每条操作必须有唯一匹配，不存在的模型/方向/profile/规则、重复操作、漏WS、未消费源字段或意外输出均令生成失败。输出只允许清单里的相对POSIX路径，拒绝穿越、绝对/盘符路径和大小写碰撞；禁止运行时fetch外部ref。生成清单的原始文件hash与JCS业务内容hash分栏，任何生成物改动须重生成而非手修。

等价提取时须如实记录draft.4尚无客户端ACK帧，`client_message_root=null`表示该历史入口不接受应用层客户端帧；不能捏造ACK模型凑成完整双向协议。C05下一版再显式增加客户端帧及规则，不能把这个null继承为新版已完成。候选夹具里的fixtureWsUpgrade是合成关联标识，不声称它是现有operationId；实际源节点解析及全覆盖对账仍须执行SV02。

附[候选输入描述Schema与正反例](contracts/df01/decoder-design.schema.json)用于校验预算、HTTP/WS绑定的**局部格式和关联规则**；不是完整OpenAPI替代物、完整source-manifest或产品解码器。原始报文用例独立登记，当前只核验夹具格式/数学预期及描述元数据，不声称报文已被SDK正确拒绝。

本轮新增放行细项仍归SV02/SV07/SV10/SV14/SV16/SV18：无效UTF-8不能被text模式修复；分片代理对/UTF-8截断/BOM；重复转义键；integer条件及oneOf分支保留；ref/嵌套数组token定位；两并发上下文互不污染；number下溢；预算等号/超1；缺/错操作绑定和双向WS遗漏；源节点映射覆盖；错误响应不重发。实际SDK/Ajv/CSP/并发及压测均未运行，新推荐审阅和完整机器归并仍是实施前设计门槛。

## 10. 完整机器数据的等价提取实验

2026-10-18补充：[df01-source候选资料](contracts/df01-source/README.md)将已确认draft.4的完整机器数据拆为公共Schema、IPC、两份完整HTTP骨架、历史route投影配方、Schema注册表及原始fixtures。数据源中的公共模型只保存一次；重组时映射到两份OpenAPI components。SDK当前存在既有未提交治理文件，本轮实验放在Suite，不移动或提交那些改动，也不切换权威源。

**本轮事实**：候选重组与固定Suite提交的六份原文件逐节点相等且原字节相等；185个公共模型、19类IPC消息、52条逻辑route展开69个HTTP操作，另含两个WS升级。完整HTTP骨架保留WS两个普通字符串Schema引用、Origin、票据子协议、空security及同一对象内cookie/CSRF组合、响应headers和非统一错误集合；没有自动补x-permission或路径前缀。原232例经原历史验证器复验通过。报告逐文件记录节点计数、字节摘要和空差异列表，不用数量相等替代逐项比较。（依据：[检查器](contracts/df01-source/check_candidate.py)、[实际报告](contracts/df01-source/extraction-report.json)。）

**设计收敛**：HTTP操作骨架是请求/响应/安全/描述等元数据的唯一来源；历史routes只是兼容投影。配方保留`service/method/path/primary_success_status/legacy_security_label`，其余operation_id/request/response/permission取骨架。bootstrap/login均为空security，不能从空数组推断两者等同；旧安全类别作为独立投影元数据保留并与真实声明交叉检查。所有共用操作在两服务分别派生再比对；WS显式另查，不强塞进没有对应字段的旧routes。

两个全新临时副本只带标准库重组器与候选source，以Python `-I`各生成六份相同输出。它证明当前机器上的独立数据重组，不证明SDK独立clone后完成生成/校验，也不证明跨Windows/Linux可复现。16项变异覆盖遗漏WS、cookie安全、描述/响应头/Origin变化、模型约束与$id漂移、未知引用、重复route、第二份手写模型、未消费元数据、错误公开导出标记及改写fixture预期；另有5项路径拒绝。全部期待保持历史摘要，不按变异输入重算预期凑通过。

尚未迁出的部分在source-manifest显式列出：语义规则实现及符号映射、完整具名摘要投影、HTTP/WS/IPC wire profiles、公开/内部导出政策、TS/standalone生成及产品工具锁。现有232例中的语义部分仍依赖Suite历史Python。185个历史components不等于185个公开SDK类型，SchemaRegistry中的legacy投影表不得成为exports批准。当前引用遍历仅针对核对过的历史结构；未来带任意Schema数据的开放字段不能未经审批套用该参考转换器。

因此SV02的历史机器数据对账已取得具体证据；SV01、SV03的独立语义验收、SV04跨平台及其余产品放行项仍未通过。下一步按同一固定提交整理规则/投影的完整追踪并划分公开/内部根，再迁入SDK独立仓库作受控切换；后续词法、时间模型和业务契约修订仍需另版审阅。源提取不改变已确认协议或替代用户对新方案的确认。

## 11. 语义迁移与导出边界的证据

2026-10-18补充：[语义追踪资料](contracts/df01-source/SEMANTIC_TRACE.md)登记13个历史判定入口、12种摘要及1种身份规范化投影，并将232例逐case_id追踪到实际进入的函数。实际计数为160公共、24仅结构IPC、48关联；公共6个语义反例全部集中于descriptor/profile/evidence。撤权匹配、容量决策、恢复单次消费等8个历史入口未被此批调用，相关历史独立用例不能因文件hash已绑定就视为执行。（依据：[实际报告](contracts/df01-source/semantic-trace-report.json)、[规则入口表](contracts/df01-source/semantic-trace-map.json)、[投影表](contracts/df01-source/digest-projection-map.json)。）

新增4个独立探针证实：开放parameters的descriptor_version或kind可令旧语义抛KeyError，同名窗口可误触发拒绝；CatalogBinding重复scene_id且UUID不同可通过当前归并入口。报告的通过仅表示复现历史行为，未修复缺口。推荐新版以具名模型/声明路径绑定规则，停止在开放参数或动态Schema正文中猜测首方对象；显式接入目录唯一性，定义投影也改按步骤路径，均登记接受集合或摘要变化而不暗改draft.4。

公开HTTP/WS联合62个根可达166模型，内部9根可达24、IPC外部15根可达31；仅内部/IPC可达17个，另有AuthorizationSnapshotResponse、RunGrant未被入口引用。WS扩展是普通字符串，不能仅扫$ref。推荐据逐项名单建立public/internal/ipc独立exports；未引用类型不自动删除或导出，公开类型不等于匿名权限，开放Payload内容须另作输出控制。当前报告只证明静态引用关系，未批准最终导出清单。

生产语义注册项与四类结果边界、实施绑定、可信上下文和错误脱敏方案详见追踪资料末节。13个函数入口不是完整原子规则表，相关夹具也不是13种投影各自的完整差分向量；本轮只检查其定位且保持原232预期。D1的语义实现迁出、D4的独立投影向量、全部历史安全集向新协议适配仍未完成；新推荐须审阅，C01不因本报告通过而关闭。

## 12. 语义注册、选择器与评估结果候选

[局部格式设计](contracts/df01-source/SEMANTIC_REGISTRY.md)与[Schema](contracts/df01-source/semantic-registry.schema.json)将第11节推荐落实为可校验元数据。规则固定具名根、修订、有限selector、阶段、可信provider/policy、reason/location和计划实现/向量。生产制品尚不存在，绑定显式标planned，不使用虚构hash冒充可执行实现。

**新增设计收敛**：Schema路径与实例位置同时限制开放参数；CommandRequest.allOf/then对parameters的具名约束不能绕过动态能力校验。选择器保留if真假、anyOf/oneOf分支及它们所在数组实例位置，完整根验证仍先于语义。可选字段缺省或分支不适用表示不调用规则，不伪造valid；多个成功分支按规则/修订/实例去重。可信上下文缺失不补默认许可，校验异常不变成设备failed或写重试；结果只返回登记的reason/location，禁止回显动态键或原始异常。

**实际证据**：[报告](contracts/df01-source/semantic-registry-report.json)记录47项注册、23项结果及8项合成选择器检查，共78项。四条示例规则的八个业务向量仅列计划，实际生产规则执行数为零；检查器没有执行目录唯一性或完成SP缺口修复。参考检查器只处理显式支持的Schema结构和列明的开放边界，未证明全部导出根/别名的覆盖，也未实现分支求值、跨语言生成或上下文取证。

完整原子规则及调用点、开放边界全覆盖、投影独立向量、生产实现与新版本接受集仍是C01/SV01/SV03/SV16的剩余门槛。候选推荐保持待审阅；全系统设计完成前不进入业务实现。

## 13. 完整导出清单与客户端用途

[导出候选设计](contracts/df01-source/EXPORTS.md)及[逐项清单](contracts/df01-source/exports-candidate.json)覆盖当前71个HTTP／WS操作和227个具名模型（185公共、42IPC）。推荐显式8子路径：seamer、controller、provider、seamer-controller、internal/controller、internal/seamer、ipc、models；没有根通配导出。Seamer与Controller普通入口分别26/33操作，provider两项、Seamer到Controller授权一项、内部九项；IPC包含19消息根及73个依赖模型，models纯类型入口为166项。两个无入口公共模型保留但不导出，所有共享模型仍来自同一源。

**主体边界**：非/internal和bearer并不证明可供任意浏览器主体调用。updateRunGrant已有配对Seamer提交语义，provider发布须绑定登记来源；revokeRunGrant不能被推定为service-only。issueToken仍是人员会话换取目标服务短期令牌，不能创建组织服务身份。当前WS票据只适用于人员会话，Node消费环境不让service伪造session；第三方面板继续使用具名委托桥。候选的入口划分不修改服务器权限，也不把缺失的逐操作主体约束视为已冻结。

**实际验证**：[导出报告](contracts/df01-source/exports-report.json)逐项核对操作、安全声明、源Pointer、入口与模型闭包；46个正反资料例覆盖漏项/内部暴露、cookie与CSRF误拆、WS漏根、Schema数据中的伪ref、共享参数覆盖与封闭component引用。引用提取按Schema关键字，而非递归搜所有字典的$ref；公共/内部/IPC公共依赖与前一独立追踪报告集合对账。另一次只读源解析核对71个操作和227个模型无缺项，不借调用本检查器生成期望。

剩余放行项是批准用途策略、完整主体/委托与语义规则绑定、实际生成声明/校验器/JS后的传递依赖及负向导入、浏览器CSP和平台测试。当前sdk_builds/browser_import/authorization运行检查均为零，不因完整静态清单通过宣布SDK可用或全系统设计关闭。

## 14. 逐操作主体、凭据与目标守卫

[授权候选](contracts/df01-source/AUTHORIZATION.md)、[Schema](contracts/df01-source/authorization.schema.json)及[完整矩阵](contracts/df01-source/authorization-candidate.json)将当前71操作细分为105分支、43个具名目标/用途守卫。每条保存精确源位置和权限，分支认证与HTTP骨架核对；SDK可导入不再被误作服务可调用。新增策略待审阅，原draft.4和exports源不改。

推荐manual/接管/转交仅human，service设备写经配对Seamer＋automation＋当前RunGrant；后台KEY通过provider事件触发。服务可按明确目标授权编辑草稿、创建未布防run、只读预检及有限暂停，定义发布/布防/恢复需人员明确操作。Schema旧接受集允许service＋manual，因此此项须另版显式收紧，不能称旧方案早已禁止。provider.publish仍保留服务来源输入，不能混同publishDefinition。

当前Session/人员票据链不伪造service会话；createRequestContext仍可供service，但绑定权威主体凭据链、audience、操作交集及委托。普通退出不应要求auth.manage，候选单独给出自身会话注销边界；新主体视图、组织服务凭据、配对、服务订阅、面板委托六类缺口列入下一版归并，未伪造现有端点或宣布完整身份生命周期已交付。

[离线报告](contracts/df01-source/authorization-report.json)包含36项元数据正反例及九输入绑定；真实认证、权限取证、并发撤销、接管与设备执行均为零。文中18条运行轨迹仅作实施验收计划。完整API/IPC/DDL及新接受集仍需联合归并和审阅；此批只关闭“现有操作没有逐项主体候选”的资料缺口，不关闭C01/C07或全系统设计。
