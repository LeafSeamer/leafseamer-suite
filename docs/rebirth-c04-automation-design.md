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
- 本轮仅设计文档与来源核对；EX01—EX32未执行，未创建新Schema或引擎，未启动服务、数据库或设备，未提交／推送。
