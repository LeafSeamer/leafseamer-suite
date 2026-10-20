# DF01导出清单与浏览器边界候选

本稿把[历史引用图](SEMANTIC_TRACE.md)落实为覆盖当前全部HTTP／WS操作、公共模型和IPC模型的[候选清单](exports-candidate.json)。此为待审阅SDK接口组织方案，`approved=false/authority_switched=false`；不修改draft.4、不改变服务端权限、不发布npm包。包名和npm scope尚未占用，以下仅为包内子路径。

## 已核对事实

当前HTTP骨架只有security与x-permission等声明，没有完整的主体种类或浏览器使用策略。bearer和非/internal都不能证明只准human或只准service。Controller有39个操作（含1个WS升级、5个internal），Seamer有32个（含1个WS升级、4个internal）。当前两份骨架的普通公开闭包与WS合计166个公共模型；17个公共Schema模型仅由内部／IPC引用，2个无入口引用。IPC有19消息根及42个本地模型。清单逐项保存名称、源位置和使用入口，不以数量替代覆盖。（来源：`source/http/*.operations.json`、`source/public.schema.json`、`source/ipc.schema.json`及本目录独立导出报告。）

当前`updateCatalog/ingestEvent`声明provider.publish，DF06要求登记provider及令牌主体绑定；机器契约尚未明确human禁止。`updateRunGrant`已有配对Seamer提交的设计语义，但`revokeRunGrant`不能仅因同属grant路由就推定service-only。`issueToken`位于/auth/service-tokens，现有cookie+CSRF要求表示人员会话申请目标audience的短期访问令牌，不是GUI创建组织service身份。故本候选记录的是**客户端用途**，不是凭路径命名新增主体授权。（项目依据：[DF06](../../rebirth-df06-internal-trust-design.md)、[首闭环契约](../../rebirth-first-loop-contract.md)、当前HTTP骨架及相关模型；主体约束还须与身份注册规则联合归并。）

## 推荐入口

| 子路径 | TS消费环境候选 | 操作与模型范围 |
| --- | --- | --- |
| ./seamer | 浏览器、Node | Seamer普通客户端，排除两个provider写入口，保留事件订阅 |
| ./controller | 浏览器、Node | Controller普通客户端，排除updateRunGrant和internal，保留人员授权操作及revokeRunGrant |
| ./provider | Node | Seamer的updateCatalog/ingestEvent；用于受信任来源适配，原始设备trigger先由模块/Controller适配，不能绕来源资格直接伪造事件 |
| ./seamer-controller | Node | Controller的updateRunGrant；供配对Seamer桥接自动化授权 |
| ./internal/controller | Node | Controller五个internal操作，独立mTLS传输配置 |
| ./internal/seamer | Node | Seamer四个internal操作，独立mTLS传输配置 |
| ./ipc | Node | 19消息根及其完整本地/公共类型闭包；不提供设备写socket、许可签发或屏障实现 |
| ./models | 浏览器、Node，纯类型 | 非internal HTTP／WS可达的166模型，含provider DTO；可表达数据不等于可取得凭据或调用服务 |

没有根路径通配re-export；上述8个入口显式枚举，不输出`./*`。共享模型由同一源生成，客户端类型可以引用共享内部声明文件，但不能把全部公共Schema或IPC类型自动合并到浏览器门面。公共模型保持原名，IPC本地类型采用`Ipc`前缀，避免未来同名模型碰撞；IPC消息union拟用IpcMessage，生成时须再次检查符号冲突。两个无入口公共模型AuthorizationSnapshotResponse和RunGrant保留在版本源中，标记retained_unexported；不自动删除，也不借孤立类型新增HTTP端点。

provider与seamer-controller的Node限定是首期TS产品支持范围和误用预防建议，非语言限制或网络安全边界；未来Python等消费相同协议和主体约束。首方GUI通过Seamer管理自动化，由桥生成RunGrant。管理员撤销操作保留既有权限检查，不能因为门面可导入就放行。若后续要支持浏览器内可信provider，必须显式审阅主体、短期凭据和来源绑定，不能直接使用长期服务秘密。

普通客户端同一路由可以承载不同主体用途，例如submitCommand的manual/automation分支；Node运行环境不自动授予automation身份。当前openEvents的WS票据只适用于人员会话，Node客户端也不能以service token伪造session；服务订阅须另版协议。第三方面板只能使用宿主的具名委托桥，不能因为浏览器SDK可导入便取得任意HTTP、宿主票据或长期凭据；C09面板模型尚未进入当前源，不在本清单中伪造端点。（依据：[draft.3 M06](../../rebirth-draft3-review.md)、[扩展设计ME07](../../rebirth-c09-extension-design.md)。）

Node官方说明exports可限制正常包子路径解析，但不是强封装，绝对路径仍能加载文件。因此生产浏览器产物还必须检查传递imports、Node内置模块、内部客户端/运行时校验器是否混入，并执行打包及CSP验证；树摇优化不构成隔离证明。Node专用入口不给通用default回退到内部实现，浏览器构建禁止解析到这些入口。此处未生成或验证实际package.json、JS/声明产物。（来源：[Node v24.22.0 packages文档](https://raw.githubusercontent.com/nodejs/node/v24.22.0/doc/api/packages.md)，Package entry points与Conditional exports。）

## 来源完整性与生成规则

清单包含固定source输入摘要、每条操作的service/method/path/operationId/源Pointer/transport/effective security/permission，以及每个入口的根与完整闭包。WS的ticket-binding和frame扩展作为具名根单独消费；101不是普通JSON响应，不能漏掉WsFrame。security显式空数组与继承必须原样区分，cookie和CSRF仍在同一个Security Requirement中，不能被拆成二选一。

Schema引用遍历只处理Schema位置的标准子Schema关键字，不把const/default/examples中的字典键`$ref`当引用。当前不支持嵌套$id、动态ref或非具名目标；出现这些结构时停止生成并扩展设计，而非跳过。OpenAPI查询只读取请求、响应、参数及响应头Schema，处理Path Item共享参数与操作同名参数覆盖；component参数/请求体/响应/响应头引用只在当前文件内解析，环和未知引用拒绝。callbacks、webhooks、Path Item引用等未交付能力显式拒绝，不能默默漏项。

主清单以当前源原字节绑定；修改源后不能只重算摘要使旧批准继续生效。闭包投影和操作分组变化须给差分并审阅。检查器不加载外部Schema，不运行源文件中的脚本。公开闭包含Payload/JsonValue，所以不能证明真实响应无内部证据或秘密；服务端仍按具名响应投影、字段脱敏和动态Schema限制处理数据，不能把本清单当数据流安全证明。

## 复验与冻结门槛

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_exports.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_exports.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_exports.py --check-report --staged
```

默认检查完整清单与当前源的逐项一致性，并运行独立预期的变异及小型引用图探针。报告保存全部入口根/闭包及差异，不生成SDK。源观察从完整HTTP骨架和Schema得到；已固定历史追踪报告另作独立公共/内部/IPC集合对账，不能用同一算法生成候选后只与自己比较。

检查器内POLICY是本轮人工审阅的操作用途预期，用于拒绝未分类或漏分类的操作，不是未来生产生成器的第二份权威配置。未来生成只消费已批准exports源，测试预期独立维护；当前所有操作恰好归属一个客户端入口，./models与./ipc不含HTTP操作。实际检查包含24个清单正反例、10个Schema位置探针、12个OpenAPI引用探针；它们只证明资料和参考提取行为，不证明生成后的JS模块隔离。

冻结前仍需批准用途划分、补完整主体约束与语义调用点、wire profile、摘要向量及全部动态开放边界；在实现期验证8入口实际exports/类型/传递依赖、打包、负向导入、两平台和CSP。当前实际SDK构建、浏览器导入、内部传输、身份和设备运行检查均未执行，清单通过不关闭全系统设计或项目目标。
