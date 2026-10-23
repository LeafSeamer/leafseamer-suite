# draft.4纯数据源等价提取候选

本目录是[DF01第10节](../../rebirth-df01-sdk-freeze.md#10-完整机器数据的等价提取实验)的可复验资料，尚未切换SDK权威源，不生成TS产品SDK。来源为Suite固定提交`595a6b772fed2dce48e3a28511111b41ad3e7fc3`的六份draft.4文件；历史文件未改。该来源定位在2026-10-20经34文件逐字节对账后统一，机器输出和历史验证接受集保持原样。SDK仓库已有的未提交治理文件不在本轮修改范围。

`source/`是本实验的独立纯数据输入：公共Schema只保存一份，IPC保持原$id及外部引用；两份HTTP骨架保存除components.schemas之外的所有字段；52条route投影配方只保留分组、位置、主成功状态和旧安全类别，其余四字段从HTTP骨架派生；fixtures保持160个公共例、24个IPC例、48个关联例原样。schema-registry中的185项只用于复现历史components，不授予公开导出资格。source-manifest列源文件原字节摘要、来源commit、六份预期输出及尚未提取的内容，不包含自身hash；外层报告绑定manifest。

三个工具分工明确：

- [extract_candidate.py](extract_candidate.py)：一次性读历史六份文件，先验证重组字节一致，再写**不存在的新目录**；从不执行旧生成器。输入commit是来源声明，由检查器回读Git固定提交核对，非签名。
- [assemble_candidate.py](assemble_candidate.py)：只依赖Python标准库及source目录，注册本地Schema引用、检查元数据和投影，重组六份文件。可输出至不存在的新目录；不访问网络或Suite历史Python模块。
- [check_candidate.py](check_candidate.py)：与固定Git提交及当前历史文件逐节点/逐字节对账，执行16个变异拒绝和5个路径拒绝；复制重组器/source后以Python `-I`在两个新目录生成并比对，随后使用历史验证器复验232例。后一步仍依赖Suite及既有验证环境，不伪称语义实现已经独立。

在Suite根目录执行：

```powershell
python docs/contracts/df01-source/assemble_candidate.py
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_candidate.py
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_candidate.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df01-source/check_candidate.py --check-report --staged
```

`--report`在所有检查通过后更新[extraction-report.json](extraction-report.json)。`--check-report`只核对已声明输入原字节；暂存区模式读取Git index，不重新运行生成或用例。此报告与音频候选报告一样有独立入口，不在顶层原十份报告列表中。报告不含临时目录或个人路径；完整输入集合包含源与工具以及历史报告声明的验证输入。

限制：本次是Windows上Python参考重组，未运行Linux、npm闭包安装、Ajv、TS消费或浏览器CSP。未提取semantic-rules、digest-projections的完整实现映射、wire profiles与公开/内部导出政策；没有SDK发布物。Revision尾部换行、字符串-0等历史接受规则保持原样，不借源迁移修协议。重组器仅适用于这批受检的固定结构，不能当作通用OpenAPI/Schema转换器或不可信模块Schema解析器。

材料仍适用Suite的LICENSE与THIRD_PARTY_NOTICES；manifest中的许可来源路径用于追溯，不是可独立发布包的完整许可清单。迁入SDK前须随源补齐相应声明及外层批准记录。当前source是候选，不与Suite历史源双向同步，也不宣告任何后续DF/C方案已获批准。

后续[语义、投影与出口追踪](SEMANTIC_TRACE.md)独立记录13个历史判定入口、13种投影、232例实际分层及4个已知缺口探针。新追踪报告有单独复验入口，未加入source/等价输入或更改六份输出；函数进入与Schema引用闭包均不表示产品规则已完整覆盖或导出获准。

[语义注册元数据候选](SEMANTIC_REGISTRY.md)进一步给出模型/实例路径双边界、条件选择器、可信上下文与四类结果的局部Schema。独立检查器实际执行47项注册、23项结果及8项合成选择器检查；包内8个业务向量仍为未执行计划，不计入78项。报告需独立运行`check_semantic_registry.py --check-report [--staged]`，不在原十报告清单内。当前无生产语义实现、完整调用点映射或SDK权威切换。

[完整导出候选](EXPORTS.md)按8个入口登记71个HTTP／WS操作、185个公共模型及42个IPC本地模型。`./models`只含166个外部协议可达类型，两个孤立公共模型保留但不导出；浏览器/Node用途不决定主体权限。独立运行`check_exports.py --report`执行全清单对账及46个资料正反例，`--check-report [--staged]`仅核对九输入字节。未生成或测试实际SDK包、浏览器导入或服务端鉴权。

[逐操作主体候选](AUTHORIZATION.md)补71操作、105分支及43个具名守卫；service手动控制收紧、服务准备权限及人员发布/布防/恢复均明确为新增推荐。独立运行`check_authorization.py --report`执行结构、源对账及36项元数据正反例，`--check-report [--staged]`核对九输入。它不是生产鉴权器，文中18条真实授权/竞态用例仍为计划；注销、服务身份生命周期、配对、服务订阅及面板委托接口须另版完整归并。
