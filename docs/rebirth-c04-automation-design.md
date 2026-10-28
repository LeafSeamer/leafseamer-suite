# C04：自动化定义、发布、执行与恢复设计

日期：2026-10-17。状态：**AR01—AR06为待审阅推荐，不是用户已确认的新基线**。本文落实已确认Q17、Q37—Q51、Q57、Q72；不修改公共draft.4／IPC 0.3，不实现业务引擎。涉及DF01／DF04／DF06的部分依赖各自候选，归并前须统一审阅。

责任：SDK定义类型、比较语义及编译输入契约；Seamer拥有定义、分析、触发决策、实例与执行账本；Controller拥有设备写出口及真实完成／释放证据；GUI展示预检、抑制、暂停和恢复计划；Suite维护组合与验收。单个OBS演示不替代18个旧bundle的全部能力设计。

## 1. 已知事实与缺口

以下事实由当前[Schema](contracts/draft4/first-loop.schema.json)、[Seamer OpenAPI](contracts/draft4/seamer.openapi.json)、[旧关联校验器](contracts/draft3/validate_contracts.py)和[已确认约束](rebirth-design.md#5-seamer-规则状态机与执行)核实；缺口为据此作出的工程分析。

| 当前事实 | 需要补齐的边界 |
| --- | --- |
| Definition.oneOf包含rule和state_machine；Predicate封闭且有六种比较；parameters允许开放Payload | 条件并非任意脚本，但field路径、类型、missing/null、组合及参数引用没有完整执行语义 |
| StepGroup区分顺序与必需并行；转换三阶段均RequiredStep | 校验还需完整引用、唯一ID、图无环、顺序一致性、隐式读写及全部后继闭包 |
| DefinitionRecord和RunRecord固定definition_id/version，proof另含绑定 | 无optional动作的定义也需要固定编译版本、模块和执行输入，不能只依靠proof字段 |
| RunRecord有active_execution_id；RunCreate允许按版本创建实例 | 一个run内部唯一不等于同定义所有run之间唯一；不同版本不能绕过Q50 |
| Preflight含run_revision、observed_at及检查结果 | 还需权威输入摘要、失效条件与单调有效期；passed不构成永久许可 |
| rule可64组×64步；转换每阶段64步；证明后继最多256项 | 合法结构不必然可编译为完整证明；不能截断后继、静默分批或只检查前256项 |
| definition_digest递归遇到step_id即排除independence_proof；proof检查也递归识别该字段 | 开放业务参数中的同名键会被误删或误识别；属于投影语义缺陷，不能作为等价迁移暗改 |

投影最小反例：`parameters.nested={"step_id":"business-data","independence_proof":"business-a"}`与值为`business-b`的对象不同，旧投影却相等。已有离线源码投影核对不代表运行端漏洞利用、完整定义验证或JCS碰撞；这是投影丢信息，不是SHA-256碰撞。

## 2. AR01：有限表达式、类型及静态引用

推荐采用具名版本的有限AST。保留平坦状态机、无嵌套状态／并行状态区域；禁止任意脚本、动态代码、网络查询、随机值、隐式当前时间和动态路径。以下是下一版候选表示，不是当前Schema已支持的字段。

| 节点／值 | 候选字段及语义 |
| --- | --- |
| literal | `{kind:literal,value:JsonValue}`；保留模块原始JSON，包括同名step_id／independence_proof |
| ref | `{kind:ref,source:event/observation/machine/step_result,binding_id,pointer}`；binding_id在固定输入表中解析，不能凭设备显示名称猜目标 |
| compare | `{kind:compare,operator:eq/ne/lt/lte/gt/gte,left,right}`；两侧类型、单位由绑定Schema确定 |
| all／any／not | `{kind:all/any,items:[...]}`或`{kind:not,item:...}`；all/any必须非空；旧conditions数组明确映射all，空旧数组对应显式常量true |
| exists／is_null | 读取一个ref；区分权威快照内字段不存在、显式null、快照不可用三个结果 |
| parameter_binding | `{target_pointer,value:literal/ref}`；目标为能力参数Schema允许的路径；禁止重复或父子重叠目标，不修改能力／设备身份 |

路径采用JSON Pointer字符串形式，`~1`后`~0`解码，不做Unicode规范化；对象键`01`可存在，数组索引`01`非法。项目候选只允许发布时确定的路径，禁止URI fragment、数组追加`-`、原型链读取及动态插值；根路径仅可引用被批准Schema完整限定的值。路径标准本身不规定本项目的类型、权限或失败策略。（来源：[RFC 6901第3、4、7节](https://www.rfc-editor.org/rfc/rfc6901.html)。）

eq/ne只比较同类型标量，null只与null或is_null配合；类型不符为unknown，ne不能把类型错误当true。对象／数组整体eq暂不开放，必要业务通过有限字段表达式或已审阅模块能力表达，不能自动转成JSON字符串比较。数值比较按能力Schema的数值类型与单位；精确整数串按数学整数比较，禁止转Number；普通字符串不冒充数字，字符串大小排序不开放。合法有限浮点按既定binary64语义，不能借比较引入NaN／Infinity；金额等精确小数须单独类型，不能隐式处理。

结果为true／false／unknown。not unknown=unknown；all有false则false、否则有unknown则unknown；any有true则true、否则有unknown则unknown。引用不存在时，exists=false；字段明确存在且null时exists=true、is_null=true；比较缺失为unknown；整个来源缺失、过期或失步时exists/is_null同样unknown，不能用not exists绕过来源保护。表达式的诊断与输入足迹完整记录，不能因短路遗漏编译依赖。独立安全门控始终单独检查，any为true也不能豁免撤权、失步或过期。

parameter_binding在创建单次执行时解析为固定参数，并按能力Schema二次校验；后继引用前序结果则在该步就绪时只解析一次并固定摘要。前序结果引用仅允许成功且有批准证据的输出；失败、未知或尚未就绪不能用默认值替代。参数中的event值可保留为触发时输入；observation前提必须在实际派发时按其新鲜度重验，不能把旧参数快照当实时设备状态。

首轮编译预算候选：单表达式深度16、节点256；单定义表达式总节点16384、总步骤4096；超过则发布拒绝并指出路径，不截断。它们是待压测的有限上限，不是吞吐或安全时延承诺。全部旧能力的运算、映射、相对等待和引用需求仍须逐项盘点；若不能表达，先补有限类型与用例，不能据此删掉旧功能或偷偷开放脚本。

## 3. AR02：发布产物、完整依赖图和证明容量

推荐将执行程序与证明分开保存，消除循环摘要及递归按字段名删除。下一版候选字段如下。

| 对象 | 必需绑定 |
| --- | --- |
| CompiledProgram | dsl_version、compiler_version、definition_id/version、program（类型化步骤／转换／表达式／参数模板）、input_bindings、policy_ref、graph_digest |
| PublishedArtifact | artifact_id、program_digest、bindings_digest、proof_refs、manifest_digest、发布者与审核记录引用；不可变 |
| InputBinding | binding_id、authority_id、registration_id/revision、controller_id（设备来源时）、provider/device/capability及目录修订、参数／结果Schema摘要、模块产物和足迹版本 |
| DefinitionMetadata | definition_id、metadata_revision、name/description/layout；不参与执行程序摘要，改变执行语义必须新发布 |
| CompileDiagnostic | code、definition_path、related_paths、budget_kind/limit/observed（超限时）；不返回设备秘密或完整私密参数 |

program_digest覆盖完整CompiledProgram但不含自身，program内**不含受信proof引用**；字面量中的同名键全部保留。proof绑定program_digest与bindings_digest，PublishedArtifact再绑定proof_refs及其摘要，形成单向依赖。manifest_digest只排除自身；它不是制品文件hash。布局说明独立元数据不能携带执行配置。JCS仅规范化已选数据，投影边界由版本化协议规定。（来源：[RFC 8785第3节](https://www.rfc-editor.org/rfc/rfc8785.html)。）

草稿CAS保存→解析与类型校验→生成完整执行图→检查足迹来源及容量→分配候选发布版本并固定输入→产生program和proof→在短事务复核草稿修订／输入修订并保存不可变发布产物。期间任何执行相关输入改变均拒绝本次发布；版本分配允许留空号，不重用旧发布身份。重复幂等发布返回同一产物，不重算替换旧版本。发布不布防、不安装设备写许可。

图校验必须包含：定义内step_id、transition_id唯一；state引用合法；depends_on无重复、存在、无自环／环；依赖只能指向执行上可先完成的节点，拒绝后向等待造成顺序死锁、跨并行成员等待和跨互斥转换引用。状态图可以循环，但一次转换的动作图必须有限无环。前序结果、谓词、目标状态约束、参数绑定和资源别名形成显式或隐式边；全部可能后继按可执行顺序闭包分析，不仅遍历用户depends_on。普通顺序次序本身不等于“必须前一步成功”的语义依赖；显式depends_on及结果引用则要求成功，不能被optional例外跨越。

F07的独立性条件不变：失败步所有可能写／失败写与整个后继闭包的读／写／资源／前提／目标约束无交叠，且无成功解锁或分支选择依赖。未知足迹、动态别名或未证明模块语义为unknown；模块自报complete不能当证据。并行组必须所有动作pairwise可证明独立，全必需；首期接管仍整设备，不能用细资源证明降低接管范围。

容量修订推荐：下一版将单定义总步骤显式限制4096，Proof.successor_step_ids上限提升到4096、ActionBinding上限随最大唯一动作引用提升到4096，仍受整个产物字节／节点／编译成本预算约束。现有256项上限不能容纳的optional继续定义在旧基线下明确拒绝发布，不能隐式改为stop。大型证明可在存储层分块，但权威根摘要覆盖完整有序集合且缺块即失败；公共SDK首版不暗引入可截断分页证明。精确字节预算与C05容量profile统一后才冻结，当前不据此声称全部4096步组合都可发布。

graph_digest的候选输入为具名graph_version、按step_id的JCS字节排序的节点、按(from,to,edge_kind)各字段JCS字节顺序排序且去重的边、固定资源别名表引用；拒绝重复节点，不把排序顺序当执行顺序，后者由程序结构保留。边种类区分sequence、requires_success、data、guard、resource；闭包和proof摘要绑定同一完整图。资源前缀按规范化路径段判交叠，不将device/a与device/ab误当父子。

DF01的“源等价搬迁”仍先保持旧接受集／摘要；本节修复属于**随后显式版本修订**。旧definition、旧proof及其摘要只按原版本审计，不能重算后冒充原发布。新运行禁止降级混用。proof检查只能走Schema定义的步骤路径，不递归扫描parameters中的保留词。

## 4. AR03：实例、触发决策与唯一仲裁

推荐把run定义为持续实例，execution定义为一次触发的执行，step_execution按(execution_id,step_id)记账。状态机business_state持续保存；初始state建立不隐式执行设备enter动作，初始化设备必须独立可审阅计划。rule和状态机成功执行后默认回armed等待新事件；completed表示显式结束实例，不能把一次成功误认为永久结束。最后一次execution_summary保留，下一次执行有新ID。

| 候选附属记录 | 字段与持久边界 |
| --- | --- |
| ActivationSlot | authority_id、definition_id、active_run_id/null、definition_version、revision；同一定义跨版本共享一个槽，多个未布防草稿run可以存在 |
| TriggerDecision | decision_id、inbox_ref、seamer_receive_seq、run_id/revision、definition_version、artifact_digest、snapshot_digest、result、reason_code、execution_id/null |
| EvaluationSnapshot | snapshot_id、event_ref、固定来源／观测修订与年龄证据引用、business_state/revision、运行域、求值结果及诊断；跨设备只读快照不声称物理同时 |
| ExecutionBinding | execution_id、run_id、artifact_digest、触发决策、固定参数摘要、arm_generation、grant_refs、源状态修订、计划及期限 |
| Preflight附属记录 | preflight_id、上述执行输入绑定摘要、run_revision、clock_domain、issued_tick_ns/expires_tick_ns、逐目标检查及失效原因 |

inbox接收身份、receive_seq分配、去重及来源失步按C05／DF06统一。对一个实例按receive_seq串行求值；输入观测与决定属于同一逻辑版本，不能在扫描转换过程中读到一半新状态。首次有效事件仅产生一个持久决策；decision、execution创建、活动槽CAS和审计同一Seamer事务。事务冲突重新读取同一事件，不改变既有已提交决策，也不再创建第二执行。按UTC重排会改变语义，因此禁止。

未布防／暂停／接管期间只更新观测及审计；busy（含延迟等待、派发、证据等待及未完成恢复）记录suppressed_busy，不排队、覆盖或中断现有执行。因为保护或忙碌而抑制的事件，恢复后不得重新解释为新触发。重复投递只返回原决策。活动槽在paused及未决恢复时仍被占用；显式退役前停触发、核对旧在途及释放旧许可，随后CAS换版本，不能新建run绕过暂停。

转换候选必须from_state匹配且trigger身份匹配。按固定快照求trigger条件与guards，二者合并成三值结果：无true且全false为no_match；有unknown且无true为evaluation_unknown并暂停；有true时取最高priority，最高true并列则暂停。任何priority不低于最高true的unknown都使胜者不确定并暂停；低于胜者的unknown不改变唯一胜者，但相关安全门控仍单独执行。不能用transition_id、列表顺序或先到线程破并列。

preflight到期、域／能力／授权／接管／来源／程序／运行修订改变即失效；arm消费在事务中重新核对权威绑定，成功仍只可靠受理，逐Controller安装applied才具备运行资格。观察快照不是跨服务锁，最终出口仍复核。业务NTP失效不直接使纯相对规则停用，身份和来源新鲜度的独立约束仍有效。

## 5. AR04：边沿、稳定窗、延迟与反馈

本节保留原候选的执行起点延迟解释；第11节提出显式两种锚、提交后锚记录及direct_successor窗口的新版本推荐。尚未批准，不静默改变program旧候选；正式冻结以统一审阅后的版本为准。

阈值检测候选固定`enter_threshold,reset_threshold,comparison_direction,stable_for_ms,max_sample_gap_ms,rearm_policy`，单位／范围来自能力Schema；上升触发必须reset<enter，下降相反。初次布防、重连或来源变更的快照只建立baseline，要求先观察到reset区域再接受新的enter边沿。稳定窗要求起点合格、持续收到间隔不超限的新鲜样本、末样本合格且当前仍新鲜；计时器到期不证明两次采样间设备从未变化。无法提供足够采样证据的能力不得宣称连续稳定保证，显示实际采样保证范围。

候选延迟节点为`delay_ms,max_lateness_ms`，以本执行触发决策提交后的本地单调起点计算due及deadline；0延迟立即就绪。delay>=0，max_lateness>0；允许派发区间为[due,deadline)，等于deadline过期。等待本身不占设备资源许可，但占执行活动槽；每步派发才申请新许可。延迟是已批准执行的一部分，入窗时原事件须有效，后来不能机械地用原event TTL取消合法延迟；派发时重新核对当前前提、全门控及自身deadline。参数引用event仍取固定原值。

任何暂停、接管、撤权、存储失败、时钟域失效或进程重启使待发延迟锁存取消，不能在恢复后“补剩余几秒”或补错过动作。恢复计划若包含新的相对等待，须显式新执行、展示新起点及新截止；不能复用旧排期场次。绝对UTC场次的时窗、DST和导入边界继续由C06定稿，不混同相对延迟。

规则、已验证因果链、设备三层预算固定policy_ref并参与发布绑定；计数不能靠新run_id、切版本或新来源boot绕过。无可靠causation的事件不得猜成自身反馈而丢弃，应计入规则与设备预算；缺因果不能获得无限独立链预算。越限锁存暂停相关自动化、保留原因，不主动黑场或静音。设备预算由Controller按实际目标汇总所有自动化，Seamer负责规则及链预算；跨服务预留失败只减少可用额度，不能放行未记账发送；取消预留不退款已发动作计数。重启未布防，人工恢复必须重建受控预算基线，不自动清零后续跑。

## 6. AR05：执行终态、并行失败及恢复提交

状态转换保持validating→exit→transition→enter→commit。业务状态、执行结果、设备观测三者独立：执行中business_state仍是源状态；全部required完成且F07 R5成立才提交目标。所有动作成功但提交未证实时执行进入需要核对状态，不能重发设备动作或直接报完成。

顺序规则optional失败继续仅限F07批准失败类、资源clear、当前完整独立证明和所有门控有效。unknown／blocked／expired／cancelled及保护故障始终暂停；retain_success不将failed改为succeeded。并行任一失败后停止后续组及尚未发送成员：Seamer停投递，同时请求Controller取消并核对已受理未发命令；尚未收到取消确认不能写“未发送”。已越出口的成员继续观察，仅按能力提供的安全取消处理。并行partial/unknown不自动补偿，不宣称跨设备原子。

| 事件 | 实例／执行结果 | 后续动作 |
| --- | --- | --- |
| 新有效触发且槽空闲 | armed→running，新execution | 固定计划后逐步派发 |
| 所有required成功，optional允许失败 | running→armed；succeeded或completed_with_failures | 只接受之后的新事件；不补busy期间触发 |
| required失败／未知／保护失效 | running→paused，保留failed/unknown/blocked | 停止新增派发，核对在途；不得自动armed |
| 显式disarm | 先关闭触发并处理写闸／在途 | 完整核对后disarmed；未决时维持paused并展示原因 |
| 重启 | 旧执行保留历史，实例未布防／暂停 | 未完成执行及延迟不续跑，未知先核对 |
| resume | 沿F07 R1—R5新恢复operation/execution/generation | 消费一次、新命令身份、成功保留、旧unknown不改终态 |
| retire／换版 | 先停触发，核对旧执行及许可，CAS释放槽 | completed后新run显式布防；不自动继承旧业务状态或权力 |

恢复使用[F07既有R1—R5](rebirth-f06-f07-design.md#52-sqlite-事务与跨服务边界)，并把artifact_digest、ActivationSlot revision和TriggerDecision引用纳入预览依赖。R2消费仍paused；R3全部目标准备成功才ready；R4不自动重做成功／未知；R5在单一Seamer事务提交业务状态、执行结果与固定event_id的outbox。状态已提交但事件未发只重传同事件；提交不确定先按唯一执行查询。远端先发生而通知后到的接管／外部变更仍有传播窗口，迟到证据触发偏离与暂停，不能篡改历史或承诺物理原子。

## 7. AR06：修订交付与故障验收

下一公共版本须统一交付AST／绑定／发布产物／激活槽／求值快照／预检期限／延迟与预算模型、容量上限、步骤路径限定proof校验及摘要投影；API创建／发布／arm／查询／恢复响应与错误一并更新。IPC设备写路径继续F02唯一出口；不得把Seamer表达式或第三方脚本发送给出口执行。是否新增IPC载荷只由确切新增门控绑定决定，不为文档编号强行升版。

候选错误分类：结构／类型／图非法与超编译预算为422（含稳定code和路径）；修订／激活槽冲突409；过期预检／绑定／证据412；请求字节过限413；运行容量429；关键存储或保护不可用503。既有身份错误401/403保持；只读权限不足不得通过诊断泄漏完整参数。这些映射需下一版OpenAPI明确，当前不声称已存在。

所有用例均为**待执行设计验收**；下面的期望是人工规范，不是测试报告。

| ID | 故障／输入 | 必须观察的结果 |
| --- | --- | --- |
| EX01 | 字符串"10"与整数10、false与0比较 | 类型错误unknown，不隐式相等；诊断指向表达式 |
| EX02 | null、权威字段缺失、来源整体过期 | exists/is_null三者可区分；过期不变成not exists成功 |
| EX03 | all(false,unknown)、any(true,unknown)、not unknown | 分别false、true、unknown；独立安全门控不被true绕过 |
| EX04 | 对象键a/b、~1、数组01索引、动态路径 | 固定Pointer正确解码；非法索引／动态引用发布拒绝 |
| EX05 | 大整数串9007199254740992与9007199254740993 | 精确比较不相等，不经Number舍入 |
| EX06 | 参数中含step_id／independence_proof业务键 | 新投影保留差异；不误当ProofRef；旧版本仍按旧摘要审计 |
| EX07 | 步骤重名、缺依赖、自环、间接环、前向等待 | 发布逐项拒绝并给路径，不部分发布 |
| EX08 | optional后第300步才读取其可能失败写 | 新完整闭包拒绝独立；旧容量不能截断为通过 |
| EX09 | 模块更换、别名变更、缺足迹／隐式参数引用 | proof stale/unknown；不能后台重证后自动继续 |
| EX10 | 发布期间草稿CAS失配／能力修订变化 | 不提交混合产物；同幂等重试只取既有结果 |
| EX11 | 仅布局变更与动作参数变更 | 前者metadata revision；后者必须新发布及显式运行切换 |
| EX12 | 两run／两版本同时抢同定义槽 | 仅一方成功；暂停的旧run不能被新run绕过 |
| EX13 | 重复事件／入库后响应丢失／事务回滚 | 最多一个持久execution；回滚不留活动槽残影 |
| EX14 | busy时连续事件、之后恢复idle | 记录抑制且不补执行；观测状态仍更新 |
| EX15 | 两个最高true优先级相同 | 锁存暂停，不按ID或线程选择 |
| EX16 | 高priority unknown、低priority true | 暂停；低priority unknown与唯一高true则可选高true但仍过保护门控 |
| EX17 | 两来源UTC倒序但接收顺序已确定 | 按receive_seq处理；重放不改变已提交决策 |
| EX18 | 预检通过后过期／接管／模块更新 | arm拒绝；尚未到期也不能借旧passed越权 |
| EX19 | 布防首快照已高于阈值、重连仍高 | 不伪造边沿；看到reset再enter才候选触发 |
| EX20 | 稳定窗中样本断档／来源boot变化 | 候选失效并按失步保护处理；timer本身不触发 |
| EX21 | 合法相对延迟超过原event TTL | 原事件有效受理且自身窗内、前提门控有效才可发；不因旧TTL机械取消 |
| EX22 | due前／due等号／deadline等号 | 依次等待／可申请派发／expired；无负延迟隐式立即执行 |
| EX23 | 等待期间接管／重启／恢复后原due已过 | 旧延迟不复活；新计划不能补旧绝对场次 |
| EX24 | 未标causation的反馈、多run尝试绕预算 | 规则和设备总预算生效，不能因无链身份无限发送 |
| EX25 | 并行A失败时B已受理未发、C已发送 | B须出口取消核对；C继续观察；不能宣称整组无副作用 |
| EX26 | optional明确failed但后继依赖其输出或同资源 | 拒绝继续；未知及保护失败无optional豁免 |
| EX27 | 两操作者不同幂等键消费同恢复预览 | 一个R2成功，另一冲突；已成功步骤不重发 |
| EX28 | 各Controller准备只部分成功 | 仍paused并核对撤销；不投递设备写，预览保持已消费 |
| EX29 | 设备全部成功、状态提交前崩溃 | 核对原执行及证据；显式reconcile_commit，不重发设备动作 |
| EX30 | 状态已提交、outbox发送前崩溃 | 同完成事件重传；业务状态只增加一次修订 |
| EX31 | 远端接管先发生、通知在业务提交后到 | 保留已提交历史，标记偏离并暂停；不声称无传播窗口 |
| EX32 | 表达式／证明／整个产物超限 | 在发布／受理前明确拒绝，不截断、不隐式降语义 |

验证顺序：先固定正反例和原始输入、再Schema与编译器差分；随后模拟器故障、SQLite并发／崩溃、Controller最终发送竞态；最后隔离OBS及各模块真实设备。每项记录artifact/DSL/模块版本、注入点、命令身份、状态、发送计数与证据；不以AST参考程序代替业务引擎验收。

## 8. 剩余冻结事项及本轮边界

- AR01—AR06需审阅，依赖的DF候选不视为自动接受；全旧能力盘点决定有限DSL是否还需具名运算，未盘点不宣布全功能覆盖。
- [C05候选设计](rebirth-c05-event-sync-design.md)已细化完整事件同步、失步／去重／保留、观测快照和全局容量；[C06候选设计](rebirth-c06-schedule-design.md)已细化导入、日历、跨版场次、激活受理及逐步窗口。ES／SCH推荐待审阅，需联合归并受理、来源观察、资格锁存及总预算；候选文档不代表依赖已冻结。
- 下一版SDK源须同时修订投影、proof路径、命名空间、容量及运行绑定，提供新旧版本差分与拒绝混投用例；DF01等价提取不能掩盖语义修复。
- 最初一轮仅设计文档与来源核对；后续机器资料见第9节。EX01—EX32的完整运行验收仍未执行，未启动服务、数据库或设备。

## 9. 程序、依赖图和证明的机器候选

2026-10-18补充，仍待审阅。[C04程序候选](contracts/c04-program/README.md)给出唯一格式源及Schema，覆盖有限Condition／Value、InputBinding／ActionBinding、Rule／平坦StateMachine、Action／DelayStep、AliasTable、CompiledProgram／Graph／IndependenceProof／PublishedArtifact与CompileDiagnostic。版本为`automation-program/0.1.0-draft.1`，不改旧公共格式，不切SDK权威，不实现业务引擎。

与AR01—AR02的具体衔接如下：

- compare的`value_type`是编译后显式类型及单位，必须与已批准输入projection一致；不是按字符串内容推断类型。参数槽的类型与路径同样经批准，最终替换后的参数仍须完整能力Schema验证；参考模型不冒充通用Schema类型推导器。
- 图只从程序的具名步骤路径派生，literal及parameters不参与AST／Proof识别。sequence次序与requires_success分开；结果参数及谓词产生data／guard边。全部后继由完整图遍历，模块不能提供一个缩水集合绕过失败依赖。
- 资源别名采用固定的一次路径段替换，重叠逻辑前缀及递归映射拒绝；完整绑定必须覆盖所有允许参数的最坏情况足迹。除后继正常写外也核对failure_writes，属于保守新增候选；未批准或不完整足迹为unknown。
- program摘要覆盖完整CompiledProgram，保留所有业务同名键；proof绑定program／bindings／graph，manifest只排顶层自身摘要。发布产物准确覆盖全部optional继续步骤，并行成员必须完整合格且两两独立；新摘要不能继承旧批准或混投旧proof。
- 全定义4096步和后继4096容量保持；候选增加16MiB程序JCS字节、131072边、1048576资源比较及每类足迹256上限。Delay候选为至多24小时、迟到窗1—60000ms；均待与总容量profile统一审阅，超限拒绝、不截断，不承诺所有上限组合可发布。

人工正反例实际检查三值／类型、Pointer、全图与后继、合法状态循环／非法动作依赖、并行约束、绑定变化、业务键摘要差异、失败继续及发布证明覆盖；包括4096步以及第301步才出现依赖。来源、批准和完成证据仍是合成前提，报告与六份输入原字节绑定。这些只推进EX01—EX09、EX26和EX32的离线子条件，不能将EX完整用例标为已执行。

剩余归并明确为：ActivationSlot／TriggerDecision／EvaluationSnapshot／ExecutionBinding及preflight／delay／预算的机器记录，创建／发布／arm／查询／恢复的HTTP与IPC绑定、完整Seamer DDL和旧功能逐项DSL表达覆盖；全部设计候选还需统一审阅。真实参数赋值／Schema二次验证、可信提供者、产品编译执行器和故障验收属于后续实现及验证，不以本轮参考模型代替。

## 10. 活动槽、触发与恢复生命周期机器候选

2026-10-18补充，仍待审阅。[生命周期候选](contracts/c04-lifecycle/README.md)新增独立Schema／24操作OpenAPI，给出草稿与metadata分离、不可变发布版本、活动槽、run、preflight、逐Controller准备、decision／snapshot／execution以及恢复预览／操作。版本为`automation-lifecycle/0.1.0-draft.1`，不修改已确认公共基线；第9节的对应机器记录与HTTP缺口由本批推进，不再笼统列作尚无格式。

发布请求选择可由草稿直接取得的content／selection摘要，服务端解析真实绑定并重新编译；不要求GUI提交尚未存在的完整bindings_digest，也不接受客户端编译产物来批准自身。arm受理先占跨版本活动槽但保持disarmed，全部新代次／目标grant的可靠回执完成才armed。恢复R2仍paused且一次消费，R3只到ready；失败、提交未知和迟到回执不使旧操作自动重启。相同操作预期产生的grant变化与独立接管／组织撤权分开核对。

新候选明确disarm完成后保留本run活动槽，retire完整核对后才释放；服务只获本组织暂停权限，disarm／retire／resume由具名人员权限承担。纯无设备动作允许零Controller目标准备，但来源、组织授权、存储和执行状态门控仍必须成立，不伪造grant填旧最小数组。这些是待审阅的具体衔接，不等于旧API已经支持。

Decision按服务／数据库／run与inbox身份唯一；busy、inactive及序号不高于高水位的旧事件都记录抑制且不补执行。snapshot→decision（预分配execution_id）→execution绑定消除摘要环，并核对版本、源状态及选中转换的目标。R5以当前执行／源状态／arm代及成功证据提交业务状态和固定outbox事件；重复确认只返回原结果，不重放设备动作。

独立参考检查只覆盖格式、关联和有限串行原子步，未执行真实HTTP、身份提供者、SQLite并发或设备。仍须完成发布实际编译事务／完整目标与转换集提供者、R4逐步命令和延迟／边沿／预算机器记录、全部Seamer DDL、C05/C06来源／时窗及公共SDK/IPC同版归并；EX／AU完整运行验收未执行，C04与阶段0不关闭。

## 11. R4、逐步提交与延迟／边沿／预算机器候选

2026-10-18补充，仍待审阅。[执行候选](contracts/c04-execution/README.md)提供ExecutionStart、PauseLatch、StepPlan／StepRecord、CommandSubmission、ExecutionAnchor／StepReady／DelayRecord、WindowTranslation、EdgePolicy／State／Sample／Decision、BudgetPolicy／Charge和ExecutionRuntimePolicy的独立Schema。R4以精确run/slot/operation修订、准备回执和已核对latch集合开始；reconcile_commit始终无设备派发资格。先持久化提交标记再允许一次发送路径，标记后崩溃和lookup未发现均不得重发。

新增延迟语义是显式版本修订：保留execution_admitted偏移，新增step_ready顺序等待。普通触发／恢复统一用提交返回后的ExecutionAnchor，不伪造数据库提交瞬间或恢复operation。direct_successor窗口对直接动作持续约束到Controller出口，对后继等待则在其StepReady事务内消费依赖边；不会永久叠加所有旧截止。跨域挑战和批准速率界只产生保守窗口，网络耗尽／无法证明采样因果时拒绝，不直接比较两机tick。

边沿须先有合格live reset，稳定窗只由新鲜采样推进；busy／inactive边沿也消费，持续高值不补发。预算按稳定definition／可信链或组织无因果桶／物理设备分层，profile变化和重启不清账，已扣不退款，超限锁存。摘要分离运行策略与独立BudgetLimit，阈值policy亦按完整摘要绑定。上述是候选规则，权威采样、因果来源、完整图调度、各类账本及跨服务预算尚未实际实现。

XRT01—XRT12补足崩溃切点、两种等待、边沿与预算绕过等待运行验收。局部参考检查不证明物理时钟、网络、SQLite并发或设备。剩余设计聚焦完整Seamer DDL与依赖边消费、内部窗口／预算／拒收协议、C05/C06及公共SDK同版关联和全部数值codec覆盖；不再把R4／延迟／边沿／预算笼统列为没有记录格式，但C04及阶段0仍未关闭。

## 12. 恢复核心的SQLite布局与原子提交

2026-10-18补充[16表恢复核心候选](contracts/c04-storage/README.md)，具体映射R2消费预览、持久恢复锁、R3逐目标准备、R4开始及精确latch清除、R5状态／执行结果／固定事件。普通触发的旧执行可被恢复预览引用；新execution不会覆盖旧unknown。SQL同时记录固定scope、不可变发布版本、跨版本活动槽、远端证据身份和不可复用事务／事件。

预览和operation、新execution和operation、start和两侧引用、commit和execution、事务和event分别配对提交；paused／indeterminate不自动释放锁，release须独立核验证据。所有U20都保留十进制TEXT，精确+1由可信writer核验。外键仍不能证明完整语义，因此本批同时给出FK合法但run投影不一致的恢复保护反例，而不是用建表成功宣告原子执行已经实现。

本批为候选布局及实际内存SQLite验证，不是生产迁移。命令提交与执行锚由第13节继续补齐；普通触发受理、发布编译、delay依赖消费、edge/budget完整账本和跨项机器协议仍需归并；C04、阶段0及项目均未完成，业务实现仍未开始。

## 13. 执行锚与单次命令提交的持久化

2026-10-18新增[执行层字段与故障时序](contracts/c04-storage/DISPATCH.md)及9表SQL，与第12节基础16表组合为`automation-storage/0.1.0-draft.2`。计划集合、StepPlan、ExecutionAnchor、StepReady、StepRecord、CommandSubmission、attempt、最终裁决、步骤终态分别持久化；不是公共契约升级或生产迁移。普通触发与恢复各自绑定真实来源，只有原受理/R4提交明确返回后才采样并保存锚，重启不能补锚续跑。

PLAN封存先于running；READY固定一次就绪时间；SUBMISSION固定完整原请求身份；ATTEMPT提交后只允许当前活路径尝试一次调用。唯一键不含request_digest，因此同key换内容冲突；标记后的崩溃、响应丢失与not_found均仅查原身份。永久拒收须由Controller在原受理账本内排他裁决并保留墓碑，其完整远端接口/事务尚未归并，不能用普通HTTP错误或context撤销代替。

新增SQL要求ready/submission/attempt/裁决/终态两侧引用成对提交，步骤不能自造accepted；accepted也不能直接通过R5。迟到accepted可以补原command归属，但已unknown步骤不可重开。接管或取消请求不构成取消完成证据；合格取消终态可以保存，R5仍拒绝取消步骤。所有required成功、无未决只是R5结构门槛，optional failed还须Q72证明及资源释放；BODY与权威来源由writer验证。

独立212项内存/合成检查覆盖两种锚、正常等待证据路径、六阶段逐写回滚、半边关系COMMIT拒绝、保护与原身份冲突、未知不重发及R5阻止假完成。普通触发前态为人工构造，未实现inbox/TriggerDecision受理；未运行网络、真实并发、磁盘或设备。下一步仍为普通触发/发布事务、delay依赖边和edge/budget账本、Controller裁决接口以及C05/C06/SDK同版归并，候选与阶段0保持未关闭。

## 14. 普通触发批次、世代水位与执行发布

2026-10-20补充，待审阅。以[C05第12节](rebirth-c05-event-sync-design.md#12-规范摄取的完整扇出与原子受理)作为规范摄取与扇出全集的唯一设计入口。**当前事实：**生命周期候选仅有数字last_receive_seq，纯参考模型把单run原子性作为前提；恢复／执行25表未持久普通inbox、完整TriggerDecision或run接收水位。下面是下一版修订，不用新语义重新解释旧记录。

| 候选修订 | 精确约束 |
| --- | --- |
| RunRecord.last_receive_cursor | 替换裸last_receive_seq；绑定本地scope／ingest_epoch／sequence。新建run取得当前epoch基线，初始可为0；换代只能在显式重建基线事务改绑定 |
| RunIngestBaseline | `run_id,revision,receive_cursor,source_baseline_refs,established_by_operation_ref,baseline_digest`；固定布防／恢复时不补历史的下界，与arm_generation和预检绑定 |
| EvaluationSnapshot.receive_cursor | 替换receive_seq；附`match_set_ref,run_revision_before,ingest_revision_before,slot_revision,source_revision_refs`；完整rule结果或当前state全部转换，不接受客户端给定缩水集合 |
| TriggerDecision.receive_cursor | 同snapshot和IngressCommit；保存`ingest_revision_before/after,run_revision_before/after`及match_set_ref。suppressed允许无求值snapshot，但仍记录前态、游标与明确原因 |
| RunIngestProgress | 独立`ingest_revision,last_receive_cursor,baseline_ref`；每个新规范事件的目标决定均精确+1，duplicate不变。生命周期run.revision仅按既有运行语义变化，避免把无匹配遥测变成每次都作废预检的隐式规则 |
| ExecutionBinding／TriggerDecisionRef | 原origin_kind=trigger保持；绑定精确decision身份／digest及完整摄取游标，source_state、artifact、arm_generation与固定input_snapshot必须相等；恢复来源仍用operation/start，不伪造trigger |

独立ingest_revision意味着所有使用事件水位的预检、布防／恢复基线、snapshot及CAS必须显式绑定它；不能只检查run.revision。普通无匹配事件不必使管理元数据编辑失败，但旧布防／恢复预检依赖水位时必须失效。该字段是新增候选，不在原RunRecord塞入未定义属性。

完整fanout中的每run至多一个决定；同事件可对不同定义的run各自产生execution，跨定义设备互斥仍由Controller管理。判定顺序保留当前契约：原身份查旧 → 同epoch水位检查 → busy → inactive → 保护 → 固定快照及槽核对 → 全部转换三值选择。epoch不符先走基线失效／保护，不能当suppressed_obsolete比较数值；观察到更高水位但无法找到原决定时先查GC下界，不能以max(seq)补一条新accepted。

对accepted执行，先预分配execution_id，再固定snapshot与decision摘要，然后产生ExecutionBinding、完整选中路径和全部StepPlan／waiting StepRecord。第13节PLAN在普通触发路径中并入同一摄取事务，封存完整计划后才能提交running及active_execution_id；不得先提交accepted再异步补计划。恢复路径仍按原R2—R4，不因这一归并改变ready与running边界。空动作计划若被定义允许，也必须显式封存空集合，不能把漏计划误作空执行。

COMMIT返回后当前活路径才取得并保存ExecutionAnchor；它不在trigger决定事务内伪造提交后时间。锚保存前再次核对run／execution／domain及保护；失败不否认原事件受理，也不能把失败锚任务放入可自动重试的设备队列。新进程看到accepted但无锚，按恢复库存进入保护和显式核对，不重采当前时间续跑旧执行。

epoch换代不能通过给所有run的sequence写0完成。短事务关闭旧epoch、发布新epoch及失效门控，使旧绑定run均不具备派发资格；完整依赖集合进入保护账本，已有execution及提交保持原origin。随后显式预检／恢复在writer内取新epoch当前水位和来源baseline，建立RunIngestBaseline及新arm_generation；新快照、旧epoch事件或同事件重投均不得执行。远端许可关闭确认和本地epoch关闭仍分别取证。

EN01—EN24覆盖正常、busy、空匹配、多run回滚、世代与提交未知；其中EN11/12保留现有优先级三值语义，EN17验证执行锚，EN21验证回滚后不得升级旧事件。已有299／225／118项生命周期／执行／程序检查本轮只回归旧范围，不包含这些新事务或字段。机器Schema、完整DDL、边沿／预算消费和最终SDK/IPC归并继续推进，C04及阶段0未关闭。


## 15. 普通触发摄取候选的存储衔接

2026-10-20补充。**已知事实：**[C05候选](contracts/c05-ingress/README.md)为第14节增加独立摄取进度、复合游标、完整匹配集和决定的机器格式，且以ingress_execution将普通trigger执行双向绑定到实际决定。40表组合中的合成检查证明本写集可保存完整决定及PLAN，并在任意受测写语句后回滚全部表；不再仅靠伪造trigger_ref前态测试执行层。

**推荐衔接：**INGRESS_RUN使用独立ingress_run_audit，保持旧transaction_record.phase枚举不变；每个accepted的旧PLAN审计/outbox仍在同次COMMIT。执行锚另开事务的兼容检查通过，但SQL不证明采样实际发生在COMMIT后。受理不授设备许可，合成保护结果仅检查paused投影，完整pause_latch及来源依赖保护仍需下一版设计和检查。

本轮三值选择与完整转换集合的关联检查使用人工求值结果，不实现AST、权威读取或完整调度。run与进度精确加一由参考语义检查验证，SQL只验证词法、前态及单调和必要投影。旧299／225／118项各自继续作为历史范围回归，不能计入新的EN运行验收。延迟依赖消费、edge/budget、发布/布防全集、真实接管并发和最终SDK/IPC归并仍未完成。

## 16. 来源暂停的代次绑定与恢复消费

2026-10-20补充。**已知事实：**当前RunGrant绑定run_id/arm_generation，CommandRequest带RunBinding，但进入ExecutionGuard的AuthorizationBinding只保留grant及arm_generation，未携带完整Seamer scope/run/execution。旧撤销selector也没有run范围。来源保护若只停止新触发，已提交给Controller的queued命令仍缺少统一精确拒绝依据。（来源：[draft.4模型](contracts/draft4/first-loop.schema.json)、[C05第14节](rebirth-c05-event-sync-design.md#14-来源失效完整依赖保护与恢复门槛)。）

**推荐衔接：**新版本从可信ExecutionBinding派生AutomationOriginBinding，贯穿CommandRequest、Controller持久准入、ExecutionGuard、DispatchPermit和IntentRef；不能由客户端独立选择origin、run或generation。Controller核对当前配对Seamer、固定准备记录、RunGrant和请求绑定一致，字段缺失或旧worker未协商新能力则拒绝自动化准入。manual为null，不因该字段新增而继承自动化服务权限。

SourcePauseLatch绑定保护plan及被拒绝的代次；暂停不增加arm_generation，而是保存单调deny_through_generation。prepare和command及最终Lsend都拒绝≤下界的代次。此前prepared/queued但未越出口的工作须精确取消/屏障；在途和unknown继续保留，不能将暂停、worker退出或保护applied改写成动作失败/资源已清理。已completed的历史run不倒改状态，其未清执行只能进入完整性核对。

依赖登记不仅是trigger集合，还包括guard/parameter/edge/schedule和旧execution/recovery的输入pin；新Controller准备意图发送前必须先登记目标。先登记的prepare即使响应丢失也要被屏障覆盖；只保存收到的grant会遗漏晚到资格。重基线后旧事件、延迟、边沿及busy抑制仍不能复活。

恢复预检增加SourcePauseResolution：精确未清latch、新来源baseline/floor、完整Controller回执和实际资源证据、依赖索引与source修订、run/ingest/slot前态及拟用新代次。R2锁住恢复，R3安装新代次，R4在同writer复核当前完整latch集合后清理并开始新execution；新fault或新target使旧预检失效。SourcePauseResolution不塞进旧只接受ReleaseEvidenceRef的字段，须在下一版以具名恢复证据分支归并；旧格式不暗改。

局部字段与有限判定见[保护候选](contracts/c05-protection/README.md)。它不实现AST/真实Controller授权、R2—R4或物理事务；PFT01—PFT18与EN对应的运行验收仍待后续实现。活动槽、手动接管、其他来源/授权latch继续独立生效，本轮不批准新候选或关闭C04。

2026-10-20后续[IPC0.5归并候选](contracts/c05-protection/PROTOCOL.md)已给出CommandRequest/RunBinding/RunGrant及Guard/Permit/IntentRef的来源字段和21帧格式。定义版本使用正十进制计数，不再把旧RunBinding的Version与新程序计数拼接；保护HTTP仅两个内部操作，公共准入与准备账本的完整归并仍待交付。开闸完整拒绝快照不能清旧下界，RUN_FENCE只拒原代次，不恢复运行或释放资源。141项新参考检查非真实执行、权限或并发证明。

## 17. 来源依赖提取与扩展准入归并

2026-10-29采用现有AR01—AR06及程序／生命周期方案，按Q72保留有限表达式、显式引用、完整图和失败继续规则；本节关闭C09所列“完整来源依赖如何提取”的算法缺口，不新增另一套执行器或证明格式。输入来自固定CompiledProgram、批准InputBinding／ActionBinding、资源别名与能力足迹、C06已发布场次绑定及当前来源注册；模块、面板或事件payload不得提交自报完整的依赖列表代替这些权威原件。

### 17.1 发布与布防的完整集合

先按Schema定义的程序结构访问rule、每个state及transition、sequence／parallel、全部action与delay；仅在具名Condition、Value及parameter_binding节点解析ref。遍历所有分支，包括当前false／unknown、未选中的转换和可选步骤，不以运行时求值或当前状态裁剪集合。literal及原始parameters的任意嵌套JSON保持业务数据，不递归识别其中同名binding_id、step_id或source_key。

| 依赖类别 | 提取规则 |
| --- | --- |
| trigger | 全部声明的触发InputBinding及注册槽，包含设备事件和C05的data_source分支，不限最近匹配事件 |
| guard／edge | 全部条件ref、边沿／稳定窗及其基线来源；即使短路求值未读取也保留静态依赖 |
| parameter | 每个parameter_binding的源ref；由能力定义要求的观测前提、参数范围与完整最坏足迹一起归并，不从本次值推断只有一项资源 |
| step_result | 先验证完整动作图无环，再递归并入被引用步骤的全部输入／证据来源和资源依赖；不把中间结果当独立无来源常量 |
| machine | 绑定本run业务状态的权威revision与状态Schema；若该状态声明额外外部依据，沿已发布输入绑定归并，不能隐藏在未声明JSON内 |
| schedule／time | 固定场次、激活、日历与逐步窗口的来源；绝对时间策略进入独立时间依赖，不能因为没有trigger就遗漏 |

先形成按注册级输入槽归一的静态集合，再在arm／恢复事务中把每个槽解析到当前完整SourceStreamKey和SourceBindingRef，保留二者的对应关系。设备与data_source分别按C05第17节核对target；未注册、歧义、越权、未知动态路径、缺完整足迹或超过现有图／保护容量均拒绝，不截断后给完整证明。静态集合、完整解析集合、artifact与目录／批准修订进入同一预检依赖摘要，任何来源变更使旧预检失效。

### 17.2 writer顺序与历史输入

Seamer writer将依赖索引、run／arm_generation、输入基线、活动槽和准备意图登记一起提交，之后才能向Controller发送prepare。登记的是所有可能使用的Controller目标，不只是已返回grant的目标。来源失效与此事务共用当前修订核对：失效先提交则arm拒绝；arm先提交则完整登记被后续保护捕获。远端prepare响应晚到也不能使旧代次恢复有效。

execution受理与恢复预留时分别固定完整输入pin；由step_result传递的来源也进入pin，不能仅保留本次触发源。当前定义换版或run停用不能删除历史依赖；只有相关设备提交、资源、恢复和远端准备均已核销，且保留策略允许，才移除活动索引边，历史原件仍可查询。旧数据无法证明提取完整时扩大保护并维护核对，不能宣称“查不到边所以没有影响”。

一般面板结果的C09读集也由可信宿主从方法固定的权威原件列表提取权限／来源依赖；它只保护结果释放，不替代本节的运行保护索引。安装批准、目录、来源注册、credential或映射失效均先关闭相关读集及新资格，再清理缓存。两个索引用途不同，不能将35方法的一次读集完整当成整个run依赖完整。

### 17.3 Q72与实施出口

转换的exit／transition／enter及parallel全部required；简单sequence只有显式非required动作、明确failed、资源已clear、当前完整独立证明同时成立才可继续。证明覆盖全部后继的data／guard／resource及failure_writes，不只检查下一步；unknown／blocked／expired／cancelled及任何保护故障均不豁免。Literal中的同名键不改变摘要或proof识别，新增来源分支不扩展服务手动控制权限。

SDK实现同版类型／摘要和完整生成，Seamer实现上述遍历、解析、索引与业务writer，Controller继续验证可信ExecutionBinding／准备／RunGrant及当前完整最终门控，C09数据源worker仅采集。验收加入仅guard引用、仅参数引用、step_result多跳、未选转换、历史execution／recovery、prepare响应丢失、来源换代与arm竞争、payload伪造同名键及超限全集；复用EX／EN／PFT原用例，不以另建局部参考包装作为实施前置。本轮未实现编译器、数据库业务事务或真实保护传播，C04其余跨域持久关联仍按统一清单核对。

## 18. 组织运行批准与目标范围认可

2026-10-29采用，落实[Q57](rebirth-design.md)、[DF06第11节](rebirth-df06-internal-trust-design.md#11-首期主体政策与身份权威定稿)及[准备契约](contracts/c04-preparation/README.md)。当前panel4的preparation__S0_ApprovalRef只有kind／scope／object_id／revision／digest，没有对应组织运行批准正文；GrantIntent只有裸principal_id，且其parameter_constraints引用带max_age_ms的观察Predicate而非命令参数限制。本节关闭这些关联缺口及人员管理入口，旧机器制品不暗改。ServiceApproval继续归签发Controller，RunApproval归Seamer，目标范围认可与实际RunGrant归各Controller；任何单个“批准”标签都不代表设备ready。

### 18.1 不可变正文及独立状态

以下正文使用SDK具名类型、严格U20、规范JCS及sha256摘要；Ref摘要覆盖完整正文，正文不包含引用自身的Ref或自身digest。首次生成的对象revision为1；正文不可原地改，修改内容或延长期限创建新proposal、endorsement和approval身份，旧引用不改写。revoked／expired不复活，replacement_ref只关联新对象，不更改原终态。对象状态另由带status_revision的View表达，不能用状态修订重算原正文Ref。所有数组按具名完整身份排序且唯一，不按显示名去重。

| 对象／权威 | 完整字段组与用途 |
| --- | --- |
| RunApprovalProposal，Seamer | scope、proposal_id、revision、run_id、definition_id／definition_version、artifact_ref、program_digest、bindings_digest、dependency_footprint_ref、service_principal、source_service_approval_ref、controller_targets、validity、proposed_by、created_authentication_ref。每target包含controller_scope、device_actions、parameter_constraints；来源ServiceApproval引用只记录批准来源，运行时还核当前交集 |
| RunApprovalEndorsement，目标Controller | scope、endorsement_id、revision、proposal_ref、origin_scope、run_id、service_principal、controller_target_digest、device_actions、parameter_constraints、validity、endorsed_by、authorization_basis_refs、created_authentication_ref。对固定proposal与本Controller目标范围的组织认可，不是RunGrant、prepare回执或发送许可 |
| RunApproval，Seamer | scope、approval_id、revision、run_id、proposal_ref、artifact_ref、program_digest、bindings_digest、dependency_footprint_ref、service_principal、source_service_approval_ref、controller_endorsement_refs、validity、approved_by、approval_operation_id、created_authentication_ref。controller_endorsement_refs完整覆盖proposal中的Controller集合；纯无设备定义允许两者均为空 |
| RunApprovalView／EndorsementView，原authority | object_ref、status_revision、state、replacement_ref或null、revocation_operation_ref或null、current_eligibility、reason_code或null。state为active／revoking／revoked／expired；current_eligibility为eligible／blocked／unavailable，只表示本对象当前核验，不证明全系统可执行 |
| RunApprovalOperation，实际受理authority | scope、operation_id、kind、request_identity、request_digest、run_id、proposal_ref、approval_ref或null、endorsement_ref或null、state、targets、result_ref或null、reason_code或null。kind为approve／revoke_approval／revoke_endorsement；state为accepted／applying／applied／indeterminate，targets逐服务保存target_scope、purpose（close_controller／notify_seamer）、state（pending／applied／indeterminate）及receipt_ref或null；approve种类targets为空，逐目标认可放在批准正文中 |

Principal一律是issuer_id／issuer_epoch／principal_id完整身份；proposed_by、endorsed_by、approved_by是当次当前human，service_principal必须是与origin_scope绑定的已配对Seamer专用service。created_authentication_ref和authorization_basis_refs指向受限审计原件，公开View只给获授权引用，不返回token、session秘密或认证快照原文。

proposal的controller_targets由可信编译器遍历完整固定artifact、所有状态／分支／动作及第17节依赖足迹，不能只看本次选中路径。每Controller最多256项device_actions及64项parameter_constraints，总Controller最多256；超限整项拒绝，不遗漏未来分支。device_actions沿现有DeviceActionScope及精确能力版本，参数限制改用下述ActionParameterConstraint，不支持任意脚本或宽泛通配。动态参数必须在发布Schema及批准参数限制内，每次受理和最终发送再次核验；批准不把未知未来参数自动变成允许。proposal／endorsement／approval的validity使用新具名RunApprovalWindow，仅含有限not_before／not_after并要求not_before<not_after，由DF06认证时钟严格判断；不借业务NTP或浏览器时间延长。

**参数限制的类型裁决。** 旧preparation__S3_Predicate含device_id、field、operator、value、max_age_ms，属于观察条件，不能靠字段名parameter_constraints解释成命令参数授权。新`ActionParameterConstraint`封闭包含device_id、action_id、capability_version、parameter_pointer及rule；parameter_pointer为动作参数内的规范JSON Pointer，无通配，须在固定能力Schema中可定位。rule为封闭三分支：`{kind:"equals",value}`含完整Schema合法JSON值；`{kind:"one_of",values}`含1—128个JCS互异的合法值；`{kind:"range",minimum,maximum}`含有限数值边界，闭区间且minimum≤maximum，只适用于能力声明的有限数值参数，单位／量化仍由能力规定。分支禁止混字段，不作字符串转数字、默认值补齐或布尔转换；缺路径拒绝该动作。equals／one_of的单值上限64 KiB，整体仍受1 MiB批准正文预算。−inf、mute及带标签值可按其原Schema精确匹配，不能塞进有限range。

同目标／Pointer多个条件按交集处理，不按数组后项覆盖；不同Controller同名device_id不合并。controller_constraints请求项固定controller_scope和constraints数组，必须精确指向编译足迹内动作；未提供限制只表示仍受能力及当前组织／本地权限边界约束，绝不等于绕过它们。目标认可时对本地可授限制做保守包含证明：有限集逐值验证，闭区间比较同类型／同单位边界，组合按固定Pointer的合取；对象父子约束或其他形式不能证明包含时拒绝，不假定Schema等价。空交集或范围不被本地人员／服务政策覆盖时整项拒绝，不静默裁剪批准范围。运行时再核全部原条件及当前授权交集，静态包含证明不代替实际参数验证。

新类型同步进入proposal、endorsement、RunApproval所引用范围、GrantIntent、RunGrant、本地可授策略、授权使用证据及最终参数检查；同一选择只有一个具名定义。原Predicate继续用于观察／guard并保持max_age语义，不给旧运行资料重算摘要。SDK生成明确迁移，不接受两种parameter_constraints联合而让调用者任选较宽分支。

### 18.2 提案、逐目标认可与人员批准

1. 人员在Seamer创建proposal，提交已发布artifact、预期run修订、目标服务主体及请求的有限窗口／按controller_scope分组的参数限制。Seamer核当前run.approve和对象范围，读取原发布产物与完整依赖生成真实目标集合；主体批准不能覆盖或版本／绑定不一致时拒绝。浏览器不能上传一个删去设备的“编译结果”。创建proposal只冻结审阅输入，不更改run、当前approval或布防状态。
2. GUI分别向目标Controller提交proposal_ref，以该目标audience的人员凭据、近期认证、grant.manage及精确设备／动作／参数范围请求endorsement。Controller通过已配对Seamer的受保护内部读取获取proposal原件、重新核scope／摘要／服务身份／完整本地目标，与本地当前可授范围及有效窗口逐项比对；任何缺项或超权整项拒绝，不裁剪后仍引用原proposal。不同目标可由各自有权人员认可，不能由Seamer冒充他们签发。
3. 目标writer在同一事务保存不可变endorsement、当前状态、原请求唯一结果、授权审计、历史目录及通知。相同proposal／本目标／固定内容只能有一个当前有效认可；重复请求返回原结果，已撤或过期的认可不复活，需要新proposal。认可本身是有限组织授权，人员退出／会话到期／停用不自动撤销；实际服务批准、本地组织策略或该认可被撤则独立保护。
4. 人员在Seamer提交固定proposal及完整endorsement_refs。Seamer核当前人员run.approve、近期认证、expected_run_revision及expected_prior_approval_ref，逐目标通过固定配对通道取原件和当前状态；检查每项归属、同proposal、完整范围和窗口。无可靠当前证据不得批准；异步读取不放进本地writer事务，提交时复核本地版本及证据有效界。批准事务保存新RunApproval、当前指针、结果、审计／目录／outbox，并增加run revision，使旧preflight失效。相同proposal只产生一个approval身份。
5. 跨服务不是原子提交。Seamer的applied只证明本地批准已持久化，不能宣称各目标仍可用；远端认可在读取后被撤，后续prepare／派发按目标当前状态拒绝并保护。部分认可或响应丢失只查原记录，不替其他目标认可，不自动布防。没有最终Seamer批准，任何孤立endorsement都不能签发RunGrant。

新批准或替换批准只在run处于disarmed或paused、没有活动执行／待决arm或recovery、旧代次全部准备已关闭且相关资源已核对时提交。替换先明确撤销旧批准并完成固定目标传播，再批准新proposal；不存在热替换批准使旧执行悄悄扩大范围的路径。紧急撤销随时允许，不等待资源clear；恢复、补偿及未知核对另行处理。人员批准后仍须另行preflight／arm，服务不能调用这些人员动作；批准者离职只提示维护责任交接，不静默改approved_by或转移授权。

### 18.3 管理与内部读取接口

以下为新选择生成输入，均返回no-store。公共管理写以context_id引用本authority的RequestContext，并携带idempotency_key；本节独立去重键固定`(authority_service_id,database_instance_id,issuer_id,issuer_epoch,principal_id,request_epoch,operation,idempotency_key)`，context_id用于当前身份／范围／期限核验，不进入该键。request_digest覆盖operation、规范路径与完整语义body，仅排除顶层context_id及idempotency_key；不递归删除同名参数。先在当前读权下查同键结果，异内容409；新操作才做CAS。context过期／请求域关闭不能创建新动作，同键查原不恢复旧资格。

| authority／方法与路径 | 输入、权限及结果 |
| --- | --- |
| Seamer POST `/api/v1/runs/{run_id}/approval-proposals`，createRunApprovalProposal | context_id、idempotency_key、expected_run_revision、artifact_ref、service_principal、validity、controller_constraints；human＋run.approve＋近期认证；201返回完整proposal及Ref |
| Seamer GET `/api/v1/approval-proposals/{proposal_id}`，getRunApprovalProposal | run.read及对象范围；返回固定proposal，不重新编译／抓源 |
| Controller POST `/api/v1/run-approval-endorsements`，endorseRunApproval | context_id、idempotency_key、proposal_ref；human＋grant.manage＋近期认证及本目标范围；201返回EndorsementView及原件Ref，不含设备许可 |
| Controller GET `/api/v1/run-approval-endorsements/{endorsement_id}`，getRunApprovalEndorsement | grant.read及对象范围；返回EndorsementView及允许读取的完整正文 |
| Seamer POST `/api/v1/runs/{run_id}/approvals`，approveRun | context_id、idempotency_key、expected_run_revision、expected_prior_approval_ref或null、proposal_ref、controller_endorsement_refs；human＋run.approve＋近期认证；202返回RunApprovalOperation |
| Seamer GET `/api/v1/runs/{run_id}/approval`，getCurrentRunApproval | run.read；返回RunApprovalView及正文，尚未批准为明确null，不虚构默认active |
| Seamer GET `/api/v1/run-approvals/{approval_id}/revisions/{revision}`，getRunApprovalRevision | run.read及原对象范围；不可变正文，历史可读不代表当前有效 |
| Seamer POST `/api/v1/run-approvals/{approval_id}/revoke`，revokeRunApproval | context_id、idempotency_key、approval_ref、expected_status_revision、reason；human＋run.approval.revoke＋近期认证；202返回保护传播操作 |
| Controller POST `/api/v1/run-approval-endorsements/{endorsement_id}/revoke`，revokeRunApprovalEndorsement | context_id、idempotency_key、endorsement_ref、expected_status_revision、reason；human＋grant.revoke＋近期认证；202返回本目标保护及通知操作 |
| 两服务 GET `/api/v1/run-approval-operations/{operation_id}`，getRunApprovalOperation；POST `/api/v1/run-approval-requests/lookup`，lookupRunApprovalRequest | 当前领域读权＋对象范围；lookup只接受原完整请求身份，不创建新管理请求。返回原操作／受理结果或明确unknown，unknown不是可重发证明 |
| Seamer GET `/internal/automation/approval-proposals/{proposal_id}`，readApprovalProposal；GET `/internal/automation/run-approvals/{approval_id}/revisions/{revision}`，readRunApproval；GET `/internal/automation/run-operations/{operation_id}`，readRunInitiator | 仅proposal／approval目标中的已配对Controller，automation.prepare.read；分别返回原件及当前状态，或与当前prepare绑定的生命周期原件及人员发起者审计引用。按DF06当前用途和响应释放门核验，不开放公共代理 |
| Controller GET `/internal/automation/run-approval-endorsements/{endorsement_id}`，readRunApprovalEndorsement | 仅原origin_scope的配对Seamer，automation.prepare.read；原件及本地当前状态／拒绝下界，不允许任意Seamer枚举 |
| Seamer POST `/internal/automation/run-approval-endorsements/{endorsement_id}/revoked`，notifyRunApprovalEndorsementRevoked | 仅原目标Controller的automation.protect；输入endorsement_ref、原Controller撤销操作Ref、proposal_ref及固定拒绝修订，核原件后持久拒绝该proposal的新批准并关闭所有已派生approval／运行目标，返回持久通知receipt；不凭客户端自报revoked撤别的目标 |
| Controller POST `/internal/automation/run-approvals/{approval_id}/revoke`，applyRunApprovalRevocation | 原Seamer的automation.protect；输入固定revocation_operation_ref、approval_ref、endorsement_ref、本目标完整preparation／grant／代次引用及request_digest；本地先持久拒绝该approval，再按已有RUN_FENCE关闭匹配资格；202及可查原receipt |

认可撤销通知以(Controller scope,原撤销操作Ref,endorsement_ref)唯一，同键异内容拒绝，重送只返回原持久receipt；通知已提交但响应丢失不创建第二次保护。内部撤销以`(origin_scope,revocation_operation_ref,controller_scope)`唯一；同身份异内容拒绝，重送只返回原记录。原结果由GET `/internal/automation/run-approvals/{approval_id}/revocations/{revocation_operation_id}`（getRunApprovalRevocationReceipt）查询，实际配对origin及原完整操作Ref共同核验；请求与回执包含原完整目标集合及pending／applied／indeterminate，不因断线删目标。接收方可从本地账本扩充遗漏的匹配准备以保护，但必须记录发现，不按来报空集合直接applied。新数据域或不能证明退役旧域时不以404结束传播。

公共401／403按身份／范围，404隐藏不可见对象，409同键异内容或状态冲突，412预期修订／批准前提失效，413大小，422非法范围／窗口，429额度，503认证／权威／关键持久化不可证明。批准新权限不从definition.edit或管理员显示名推导。每份proposal及endorsement／approval公开正文上限1 MiB，超过目标项／字节预算整项拒绝；内部原件按同一上限，不能缩减后重算摘要假装原件。创建与保护查询沿现有独立容量路径，真实负载验证后才宣称该profile适用于发行。

### 18.4 准备、派发与撤销关联

下一完整选择将GrantIntent的裸principal_id替换为完整`principal`，必须逐项等于proposal、RunApproval、endorsement和实际服务认证主体；RunGrant的issuer／principal由目标根据实际已认证服务及指定签发者记录填写，不能由请求自报或把本地Controller身份替代主体签发者。GrantIntent继续使用既有Validity，其not_before／not_after必须在RunApprovalWindow内，authorization_policy_revision取目标当前本地授权政策且prepare同writer再次比对；该政策修订不属于跨目标共享窗口，也不把它与任何expires_at字段混用。现有PrepareRequest.approval_ref固定指向本节RunApproval正文；其artifact／run／definition／origin_scope、grant_intent的全部device_actions／ActionParameterConstraint必须与本目标endorsement逐项一致，validity的时间窗必须落在其完整批准窗口内，不用相同digest字符串替代解析与当前授权。

生命周期原件增加不可变initiator（完整human Principal）及initiator_authorization_ref，由Seamer从本次真实arm／resume认证写入，不能接受GUI或service自填。目标Controller在prepare时经readRunInitiator取得与operation_ref同一原件，核签发者当前资格及本地对应运行／设备范围；Seamer自己的run.arm／run.resume权限也仍核验。这次权威核验使用真实生命周期原件及签发者／本地人员权限提供者，不把PrepareRequest中的人员字段当认证证明；相关当前使用证据归已有DF06授权来源链。当前布防／恢复发起者不能借另一个人的历史批准授出自己没有的范围。批准、认可及布防的人员身份分别记账，不把三者混成service_principal。

Controller创建grant前在同writer重核本地endorsement未撤／未过期、实际配对Seamer、原approval及当前服务授权、本地策略、完整目标和控制前提；新RunGrant正文增加approval_ref及endorsement_ref，旧原件不补字段；本地Grant登记真实两个引用，grant／PreparationReceipt／审计／目录一次提交。current证据取值沿DF06有界查询与释放规则，不能从成功读取开始无限缓存。最终每次派发再核当前grant／认可拒绝下界和授权交集；RunApproval不是绕过holder、ready、资源、时间或最终permit的独立发送许可。

人员退出／会话过期／停用不撤已成立的组织批准、endorsement和健康运行grant；后续自动派发核当前专用service及组织资格，不连续要求历史approved_by／endorsed_by／initiator会话在线。新的arm／resume仍需新的当前人员动作与权限，不能复用旧人员认证引用。服务批准减权、本地目标收权、组织批准／认可到期或显式撤销则按Q57停止相关新派发、失效待发并解除布防，在途及unknown保留。

Seamer撤销先在本地writer永久拒绝approval身份、关闭本run新准备／执行资格，捕获proposal全部目标加既有prepare／grant／历史执行pin的并集，保存RunApprovalOperation及完整保护outbox。目标即使尚无grant也持久拒绝该approval_ref，防止撤销先到、迟到prepare重新签发；不得用旧RevocationSelector的grant字段冒充尚不存在的grant。每目标完成本地拒绝、实际RUN_FENCE及持久receipt后才applied，全部原目标完成才全局applied。认可单侧撤销先保护本地匹配grant，再通知Seamer关闭该批准及完整运行目标；通知未知保留indeterminate，不能声称其他目标也停了。

到期在每次使用时比较认证区间，后台任务仅补持久传播，不是唯一失效机制；过期不可因时钟回拨恢复。批量撤销人员关联自动化沿这些明确approval操作逐项提交，不依赖人员停用事务成功后全体自动撤权。更换来源、定义版本、动作范围、参数条件或有效窗口均新proposal并重新认可，旧Ref／拒绝下界／在途账本不会迁入新对象。

### 18.5 持久与验收出口

Seamer产品库保存proposal正文、approval正文及独立状态／当前run指针、proposal到approval唯一关联、管理去重／operation、完整目标和保护outbox。Controller保存endorsement正文／状态、proposal与本目标唯一关联、approval拒绝记录、grant到approval／endorsement强关联及撤销receipt。所有新增原件与各自状态、去重、审计和C05目录在所属writer同事务；远端引用不伪造跨库外键。提交未知查原，不能先返回201／202再补认可或目录；关键记录丢失保持保护。

原子写集归入DF04：Seamer批准提交增加run revision并失效旧preflight；撤销的本地拒绝／固定目标／outbox同写；Controller endorse与自身权限切点同写，grant与认可／拒绝状态同一准备事务核验；认可撤销与本地grant拒绝／保护意图同写。恢复旧库更换scope，旧proposal、认可和批准只作历史，不由改JSON的scope复活；要在新域运行须重新批准并处理旧域残余。

此节完成正文、人员／内部API、全部目标关联、身份／期限及失败处理的设计，SDK统一生成、服务writer与GUI批准页转实施，不再新建同义批准参考包。验收必须覆盖无设备定义、未选分支含设备、同principal_id不同issuer、错误Seamer、少／多endorsement、超出ActionParameterConstraint、人员退出后健康自动化继续、新arm仍需当前人员权限、纯服务增权不扩旧批准、部分认可／撤销、先撤后prepare、批准／准备与收权交错、COMMIT未知、过期回拨、跨库恢复及资源unknown不可替换批准。当前没有运行以上产品／数据库／设备用例，C04其他关联及整体阶段0仍按统一清单核对。

## 19. 首期执行、来源恢复与继续运行的持久关联采用

2026-10-29。本节关闭统一清单1.4的C04其余跨域持久关联核对项。**当前契约事实：**panel4已有准备、摄取、执行及continuation接口，但lifecycle__EvaluationSnapshot仍为裸receive_seq，RecoveryPreview没有SourcePauseResolution分支，continuation的Request.actor只有issuer_id／principal_id；不能靠短名相同或旧Ref存在声称这些字段已归并。（来源：[固定SDK模型](https://github.com/LeafSeamer/leafseamer-sdk/blob/aff5ccbb75b6140109f948f81284785c75e46d1e/contracts/panel-wire/contract/models.schema.json)、[继续运行协议](contracts/c04-lifecycle/CONTINUATION_PROTOCOL.md)。）

**本项目采用：**复用第14、16—18节和[C05第20节](rebirth-c05-event-sync-design.md#20-跨服务保护观察与恢复采用)，完整接入同一Seamer业务writer。既有源码中的合成provider前提须由真实受权原件提供者实现，旧参考库不等于产品组合库，也不要求先新增另一组参考表才能开始实施。

### 19.1 唯一原件与提交顺序

| 阶段 | 原件来源及本库提交 | 失败或跨服务边界 |
| --- | --- | --- |
| 发布／布防 | 完整artifact、AST依赖、RunApproval／目标Endorsement、当前人员与服务主体；预检固定run／slot／ingest／source前态、完整目标及保护预算 | 发布产物及全部未选分支仍参与依赖，缺目标不批准；人员会话退出不撤既有组织批准，但新布防须当前人员权限 |
| 准备 | P1准备登记、原请求及Controller目标先于HTTP；Controller签发的prepare／grant回执归该Controller，Seamer保存完整scope及摘要和已观察状态 | accepted不等于applied，响应未知不删目标；当前资格须核原准备、控制／授权及组织批准，不能以本地缓存或请求正文自授 |
| 规范摄取／PLAN | 同一IngressCommit固定全集、每run唯一决定、完整EvaluationSnapshot、execution／StepPlan、waiting记录、活动槽、容量及审计outbox | 全目标同COMMIT；busy或抑制不排队补跑，回滚后的旧事件不能重新升格；与来源保护同writer排序 |
| ANCHOR／READY | 原受理或R4提交可靠确认后的当前活路径固定ExecutionAnchor；步骤就绪及边沿／延迟／预算只按原计划、域及依赖建立 | 崩溃缺锚不补采当前时间续跑，换域取消旧等待；相对延迟和绝对排期取交集 |
| SUBMISSION／ATTEMPT | 固定CommandSubmission的完整Controller scope、RequestKey、content摘要、ExecutionBinding／step及原目标；持久一次调用尝试后才网络发送 | 回应丢失只按原请求查准入账本；not_found、超时、403或503都不授权重新调用设备动作；永久拒收必须有Controller原排他裁决 |
| 步骤证据 | Controller命令／attempt及Completion、Release、resolution归其原authority；Seamer只保存核验原件与精确关联，迟到事实追加历史 | accepted不是succeeded，resource clear不是步骤成功；原unknown不可借新请求重跑，证据撤回使依赖失效并保护 |
| R5／T7 | 固定执行及业务状态CAS、完整步骤集合、当前来源／授权／保护、资源与采用证据、slot释放、审计outbox同COMMIT | 状态转换／并行全required；Q72仅允许已声明独立可选步骤明确failed且资源清理证据完整。unknown、取消或接管不豁免；设备副作用不随业务事务回滚 |

RunRecord、EvaluationSnapshot、TriggerDecision及预检／恢复基线统一采用第14节的receive_cursor={scope,ingest_epoch,sequence}、独立ingest_revision及RunIngestBaseline Ref；旧last_receive_seq／receive_seq不作为新执行分支。只有同scope同epoch才比较序号，run.revision与ingest_revision各自推进，不能用无匹配遥测隐式修改运行生命周期。普通触发ExecutionBinding来自原决定，恢复来自原operation／start，二者不可互造来源。所有具体CommandRef归目标Controller，不能把Seamer execution ID当其命令ID。

任何远端原件读取均在writer事务外以当前配对和对象用途取得；进入本库提交时重新核完整绑定、已知撤回下界、所依赖前态及有效期限。网络查询成功不形成跨库原子快照；新收到撤回与本地消费同writer排序，已经在远端或本地提交的事实保留历史并按政策追加保护，不倒改为“从未发生”。远端未知状态不补造有效receipt。

### 19.2 SourcePauseResolution的独立恢复位置

生成具名SourcePauseResolution与其Ref，所有者为Seamer scope。正文为id／revision、run_id、latch_ref、rebaseline_ref、fence_receipt_refs、resource_resolution_refs、new_arm_generation、preflight_ref、resolution_digest；采用C05第14.2节已有语义，数组是精确完整目标集合而非任意客户端提供的证明列表。fence_receipt_refs解析相应Controller原回执及C05当前观察修订；resource_resolution_refs仍解析实际设备资源证据，不能被保护applied替代。

RecoveryPreview新增source_pause_resolution_refs，封闭的具名Ref数组；没有来源latch时必须为空，有来源latch时与预检捕获的完整未清集合逐一对应。RecoveryPlanItem.evidence_refs继续只承担每步CompletionEvidence，不混入SourcePauseResolution，也不把source resolution填入ReleaseEvidence字段。DependencyBaseline新增ingest_revision／receive_cursor、dependency_index_revision及latch_set_digest，固定这次预检的一致点；相应摘要随新选择明确更新，旧预览不静默升级。

无环生成顺序为：当前事实及latch集合→Preflight→SourcePauseResolution→RecoveryPreview→人员恢复操作／R2→各目标R3准备→R4消费。Preflight只绑定原事实，不反向含未来Resolution或Preview摘要；R4在独立消费行记录cleared_start_id，不修改Resolution正文加入未来start。R2仍paused；R3不代表运行开始；R4重新核当前完整latch／source baseline与floor、保护观察修订、依赖／ingest／run／slot前态、资源和人员权限，新generation严格高于已知deny，原子记录精确消费并启动新的execution。新fault／target／撤回先到则旧预览失效，不清无关latch。

重基线只使来源可观察，不能恢复原运行。基线、连续delta及ready仍保留原拒绝floor和gap；旧closed key不重开。源同步、Controller保护applied、资源clear及run可恢复四者分别验证。历史SourcePauseResolution可读，不作为当前新恢复的通行凭据。

### 19.3 恢复完成后的继续运行

采用既有CONTINUATION／BINDING／PROTOCOL／TRIGGER链，关闭旧恢复准备仅覆盖单execution却直接回armed的冲突。恢复步骤完成后，原recovery准备和grant保持不变；在原准备之下由各目标Controller另签run_generation且activation=adoption_and_r5的continuation grant。完整目标来自批准的继续运行计划，不缩成刚执行过的恢复步骤子集；缺原准备的新增目标或动作须重新预览和新代次，不能扩大旧grant。

新完整选择将两服务continuation Request.actor改为完整human Principal（kind、issuer_id、issuer_epoch、principal_id）；与request_epoch所属的持久身份、当前人员审批及固定Request摘要一致，不从正文自授权限或补当前epoch。approval_ref仍指这次具体继续运行确认，组织RunApproval及各Endorsement另外由原准备和新grant链核验，互不替代。新grant的被授权主体仍是配对Seamer服务，不能将审批人员写成automation服务或反向把服务当恢复人员。变更后的摘要与版本显式更新，旧两字段actor只读历史。

Seamer保存同一transfer的完整Controller Receipt集合后才能封存Adoption；恢复R5同时核采用、原执行完成、当前资格及全部前态，才释放恢复互斥并回armed。之后普通trigger使用新的ExecutionBinding及continuation grant；原recovery execution仍是历史。现有八个内部操作及三元／带kind Ref的显式转换直接采用，不另开继续运行入口；FinishRecord.commit_body_digest仍只摘要原body，不能替代完整R5及执行原件。HTTP found、Finish非空或收到最后一份Receipt均不等于当前资格。

Controller撤回先关闭其新受理／attempt／许可资格并产生原撤回通知；Seamer按原Controller scope验证，和完整准备失效计划、run／来源锁存及预算消费同事务。两边传播窗口保留，旧命令／R5历史不改写；收到通知不重跑恢复动作或退款旧保护账户。新execution、完整动作槽及新目标在出现可发资格前计入既有WORKLOAD_BUDGET／实例预算，不能先发前半计划再发现剩余保护额度不足。

### 19.4 实施与验证出口

SDK生成上述精确差集，Seamer实现单writer及真实原件提供者，Controller实现原准备／grant和准入查询，Suite组合身份与保护路径，GUI按历史与当前资格分别呈现。执行器、数据库组合、网络和两平台运行均为实施或验收任务，不因它们尚未写完而继续将本节关联列作未定义。

A05—A08／A13／A14须验证：跨scope同ID拒绝、不同ingest epoch拒比较、全目标摄取缺写回滚、锚前崩溃不续跑、命令响应丢失不重发、来源Resolution不能作Completion／Release、R4期间新fault拒旧预览、continuation actor错epoch拒绝、少一Receipt不能Adopt／R5、保护撤回先后两种顺序及Q72完整前提。当前仅设计定稿与固定Schema核对，未运行这些产品用例；全系统阶段0仍须其余条目共同满足。
