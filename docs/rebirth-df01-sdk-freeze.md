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

类型较宽可接受，但必须标注“需要运行验证”；Schema不能因TS类型较宽而放松。输入／输出都验证；WS升级不替代每条事件验证。客户端应保留原始响应文本进入严格解析层，例如使用库的text解析模式再走受控解码，避免默认response.json提前覆盖键或舍入整数。204等无体响应独立处理，错误体不当成功数据解析。（客户端选项依据：[openapi-fetch API](https://openapi-ts.dev/openapi-fetch/api)）

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

放行需同时具备：用户确认本轮推荐、源提取等价报告、精确锁及制品来源、生成／校验／消费报告、跨语言固定向量、浏览器CSP和平台构建证明。当前未闭合：实际npm完整性与传递锁、严格原始JSON解析器的选型／预算、全部Ajv编译差异、浏览器打包工具精确版本、各语言适配与有符号-0的下一版修订。它们是DF01的具体出口条件，不自动开启业务实现。
