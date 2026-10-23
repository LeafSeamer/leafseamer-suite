# C04 程序、依赖图与证明候选

`automation-program/0.1.0-draft.1`，**待审阅、未批准**。落实[AR01—AR06](../../rebirth-c04-automation-design.md)中程序与证明部分，保留已确认Q72的失败继续范围。唯一格式源为[build_contracts.py](build_contracts.py)，生成[program.schema.json](program.schema.json)；旧draft.4／IPC0.3及DF01等价提取不变。本文没有生成HTTP、启动引擎或切换SDK权威。

## 1. 类型和引用

Condition有布尔literal、compare、all/any/not及exists/is_null；Value只允许literal/ref。compare新增显式`value_type={kind,unit}`作为编译后的类型证据，必须与绑定中选定projection完全相同；不能凭字符串内容猜数值。integer_string采用`0|-?[1-9][0-9]{0,19}`，非uint64，不接受负零、前导零或指数；binary64沿用DF01原始数字入口，Python参考不接收超过安全整数范围的原生int。普通string不得大小比较；json类型可作参数值但不可整体比较。布尔／null／string／json的unit必须null；数值单位精确匹配且不自动换算。

InputBinding绑定权威、来源注册、Schema内容及投影路径、类型和读取足迹；step_result另绑定producer_step_id，必须指向action且schema_ref与该动作result_schema_ref完整一致，delay没有可引用结果。ActionBinding绑定Controller／物理设备／模块／能力／目录、参数与结果Schema、可赋值槽和足迹。均是编译产物的固定输入，不是客户端声称拥有权限的凭据。`trusted_digests`只在离线夹具模拟权威已批准的完整对象摘要；产品需从C09/DF06取得真实、当前批准及参数覆盖证明，不能接受发布请求自带该集合。

JSON Pointer按`~1`后`~0`解码，禁止fragment、追加`-`、动态插值及原型属性路径；对象`01`合法，数组`01`拒绝。只读本对象自有属性，不做Unicode规范化。路径允许空键但必须在已批准projection/slot中；根引用必须批准整个Schema限定值。字段缺失与null和来源不可用三分；来源失步、过期、前序未成功／没有合格完成证据均unknown，不以默认值替代。all/any完整计算依赖，短路不删足迹。（依据：[RFC6901 §3—4](https://www.rfc-editor.org/rfc/rfc6901.html#section-4)；路径禁止项与三值策略为本项目候选。）

parameter_bindings只改`parameters`内批准槽，不能修改设备身份；目标重复或父子重叠拒绝。非结果引用按执行创建快照固定，结果引用在步骤就绪时一次解析；最终参数仍须完整能力Schema二次验证。当前参考检查只核固定槽／类型／引用和重叠，**没有实现模板赋值、完整动态参数Schema验证或任意Schema到projection的推导**。这些具体实施要求不因参考检查通过而消失。

## 2. 完整程序与图

Rule保留最多64组×64步，组为sequence/parallel。StateMachine为平坦states与transitions，转换含exit/transition/enter三个有序阶段，各最多64步；状态转移允许循环，动作执行图不允许循环。DelayStep显式绑定0—86400000ms及1—60000ms的迟到窗，这两个上限是新实验预算候选，未证明设备吞吐或批准生产参数。延期、重启及恢复仍执行AR04，不因Schema合法而续跑。

全定义step_id唯一，transition_id唯一；InputBinding和ActionBinding各自命名空间唯一，引用字段决定查哪一表。输入producer必须存在；依赖只能来自同一执行分支的更早步骤。并行全required且不互等；转换全部required；任一parallel组存在时，整条规则不能使用continue_if_independent。空转换动作允许纯状态变更，但仍需要授权、来源门控和R5原子提交；初始state不执行隐式enter动作。

图从程序结构派生：sequence组逐步相连，组间连接上组全部末端与下组全部起点；各转换分别形成分支。显式depends_on生成requires_success；结果参数生成data；结果谓词生成guard；已证明资源重叠生成resource。依赖指向后方、同并行组或其它转换均拒绝。任何合格后继通过上述完整图遍历获得，调用方不得提供一个缩小后继集合当输入。

Footprint包含reads/writes/failure_writes/resources/preconditions/target_constraints和safe_failure_classes。每个绑定须有经审阅的完整最坏情况足迹，覆盖该动作所有允许参数；若只能按具体参数求足迹，则须在固定参数后重新形成绑定及证明，不能拿通用模板摘要冒充覆盖。输入projection读足迹也进入步骤。任何动态别名、未知副作用或缺失权威证据使资格unknown。

AliasTable是一次替换的逻辑路径段→规范物理路径段表；逻辑前缀互相覆盖及映射到任何逻辑前缀均拒绝，防歧义和递归。物理目标可相同，借此揭示同一硬件资源。资源按路径段判前缀，`device/a`不与`device/ab`相交。别名表本身和完整动作／输入绑定均需要权威批准，哈希相同不证明真实硬件拓扑。

Graph排序：节点按step_id的JCS字节；边按from/to/edge_kind各字段的JCS字节比较，去重。排序只用于摘要，执行顺序仍在program；alias_table_ref摘要覆盖完整entries。图只含ID／边与别名引用；足迹内容由完整program和bindings摘要覆盖。

## 3. 摘要、证明与发布

| 摘要 | 精确输入 |
| --- | --- |
| program_digest | 整个CompiledProgram，含program、全部输入／动作绑定、别名表、policy与graph_digest；没有自身字段 |
| bindings_digest | 对象`{input_bindings,action_bindings,alias_table}`，数组保持记录顺序 |
| graph_digest | 完整规范Graph |
| proof引用digest | 完整IndependenceProof |
| manifest_digest | PublishedArtifact仅排除顶层manifest_digest，保留所有嵌套值 |

使用JCS后SHA256，wire摘要带`sha256:`前缀。业务literal和parameters中的`step_id`／`independence_proof`／`kind`都原样保留，不能递归删键或当程序节点。program不内嵌受信IndependenceProof，proof再绑定program/bindings/graph，manifest最后绑定proof_refs，依赖没有摘要环。bindings数组换序会改变program身份；graph节点排序不等于所有对象随意重排。（依据：[RFC8785 §3](https://www.rfc-editor.org/rfc/rfc8785.html#section-3)；具体投影是本项目版本化规则。）

证明输出由完整后继、当前绑定和足迹重新计算：证据未批准或任一相关足迹不完整→unknown；失败步骤有success/data/guard依赖，或其writes/failure_writes/resources与任何后继读／写／失败写／资源／前提／目标约束重叠→dependent；否则independent。包括后继failure_writes是保守新增规则，避免仅正常路径无写而后继失败路径发生冲突。

PublishedArtifact必须覆盖每个continue_if_independent步骤，不能少、重复或多附不对应步骤的proof；proof必须当前且independent，引用按(id,revision)读取并核对完整内容摘要。并行成员全部足迹合格且两两无交叠才可发布，未知不能当“未发现冲突”。required顺序步骤允许因模块尚有不确定结果而采用stop政策，但其能力本身仍需批准。参考生成器版本为reference-model-1，仅该生成器的输出与独立预期对账，不充当任意第三方编译器认证。

运行失败继续还须：simple_sequence、optional、明确failed、批准失败类、资源clear且释放已证、全门控与绑定仍当前。proof不能覆盖unknown／expired／cancelled／blocked，也不能替代最终出口许可。触发条件的true与独立安全门控分开；并行失败、成功后提交不确定及人工恢复继续执行AR05/F07，离线证明不赋予恢复许可。

## 4. 有界处理和故障轨迹

单表达式最大深度16（根为1）、节点256（含ref和比较操作数，literal.value不是AST）；定义全部表达式加参数绑定值节点最多16384；总步骤4096；后继数组4096；action/input bindings各4096。独立候选另限制完整program的JCS字节16MiB、图边131072、资源路径比较1048576次，每动作每类足迹256、别名256。到限拒绝而非截断，不承诺所有4096步组合都可发布；最终须与C05/DF01容量profile统一。当前JSON入口仍为离线Python解析，未实现生产线字节预算／重复键／Unicode扫描器。

正常轨迹：固定草稿和绑定→类型／图检查→计算完整后继及proof→权威再次核验→发布短事务复核CAS→保存不可变artifact；发布不布防。异常轨迹：首optional影响直到第301步才被读→完整图发现dependent→拒绝发布继续政策，不能只取前256个后继；模块或别名变更后重新计算公开摘要也不能通过旧批准，旧运行暂停等待重新预检。运行时接管或撤权后即使proof仍independent也停止新增发送。

提交未知时只查询原发布幂等记录，不重新分配旧身份；发布竞争、跨版本ActivationSlot、事件／快照、preflight、延迟锁存和R1—R5仍需下一批HTTP/IPC/DDL同版绑定，本目录尚未覆盖这些运行记录。旧proof只按旧版本审计，不能重新计算后伪称原发布内容。

## 5. 复验与验收边界

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-program/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-program/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-program/check_contracts.py --check-report
```

[参考模型](reference_model.py)不连接网络、不加载模块、不实现设备出口或业务引擎；[检查器](check_contracts.py)的预期手写，涵盖三值／类型、Pointer、图约束、别名、完整后继、摘要保留、资格与失败继续。4096步边界与第301步依赖实际派生；fixture的图摘要只用于构造，关键图边、后继和判定另有独立预期。报告绑定六份原字节，可加`--staged`核对暂存内容；此操作不重跑用例，不在顶层历史十份报告检查器覆盖内。

这批检查只推进EX01—EX09、EX26和EX32的离线子条件；EX全部业务／并发／崩溃／设备验收仍未执行。输入类型和足迹可信性由夹具模拟，未实现真实批准提供者、完整参数验证、TS生成、SQL或跨进程时序。AR候选仍待审阅，C04及阶段0不关闭。
