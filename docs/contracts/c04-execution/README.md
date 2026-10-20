# C04：恢复开始、逐步执行及时间与预算候选

`automation-execution/0.1.0-draft.1`，**待审阅、未批准**。已知依据是[C04原设计](../../rebirth-c04-automation-design.md)、[F07 R1—R5](../../rebirth-f06-f07-design.md)、[C06逐步窗口](../../rebirth-c06-schedule-design.md)和[生命周期候选](../c04-lifecycle/README.md)。以下字段、事务与公式是据此提出的项目设计；[参考模型](reference_model.py)只对人工可信前提作有限检查，没有实现服务、采样、数据库或设备I/O。

[唯一格式源](build_contracts.py)生成[Schema](execution.schema.json)。旧公共draft.4／IPC0.3、program和lifecycle候选均保持原字节；本目录不声明旧HTTP已返回新增记录，也不向Controller直接混投新Guard。正式归并须提升DSL／运行契约版本，把ExecutionRuntimePolicy的引用纳入CompiledProgram与ExecutionBinding摘要，并按所有delay step／threshold binding逐项核对覆盖、无重复／多余及类型单位。

## 1. R4必须有独立开始记录

ExecutionStart保存scope、start_id、operation_id、run_id、精确execution_binding_ref／plan_ref、expected_operation_revision、run_revision_before/after、slot_revision、prepared_targets_digest、cleared_latch_refs、clock、start_tick_ns、mode和start_digest。`start_digest`只排顶层自身；上述全部字段由Seamer从已消费预览及R3结果取得，不能由浏览器声明一个“当前可信时间”或任意要清除的原因。

PauseLatch以不可变latch_id区分同一reason的多次故障，记录产生时run revision及核对引用。新候选不能再只凭字符串`failure`去清除所有同名暂停。cleared_latch_refs是预览批准且当前仍精确相等的集合，固定按scope/object_id/revision/digest排序；任何新接管、撤权或证据变化都使本次开始失败。source／目录／组织／控制、完整Controller目标及新grant仍分别复核；准备时产生的预期变化不能吸收外部变化。

R4短事务：当前认证／存储→查询原start→对run／slot／operation CAS→核对唯一active execution与ready、新授予回执、旧资源核对及完整固定计划→核对预算／来源／相对或绝对时窗→只清除已核对latch→保存ExecutionStart、run revision+1、run=running、清active_operation_id、operation进入running或reconciling、审计与固定outbox。同execution至多一个start；换start_id不绕唯一性。提交前崩溃没有可执行资格；提交结果不确定只查询，重启默认关闭，不自动续跑已开始步骤。

`mode=execute`只允许计划中明确的新动作；`mode=reconcile_commit`禁止所有设备写，run可running但dispatch_eligible=false，operation=reconciling。完成后仍走R5全required证据／源业务状态CAS及当前门控，同事务提交execution、业务状态、operation=completed和固定outbox。不得借R5把未执行的动作标成功。只有已证明完成且缺本地业务提交的计划可用此模式；旧failed/unknown终态不改。

R4发现实际门控失效后持久化operation=paused，不能等门控变好自动再开始；存储无法写时先关闭进程内资格，恢复后不自动解锁。无权查询的请求直接拒绝，不靠未认证输入修改别人的运行。参考模型不实现权限撤销传播；可信撤销处理器仍须主动锁存关闭，而不是等待下一次R4调用。

## 2. 逐步计划与一次提交

StepPlan由完整程序／图和批准恢复计划产生：execution_id、step_id、phase、group_id、group_mode、ordinal、required、execution_binding_ref、runtime_policy_ref、payload和plan_digest。payload具名分支为action、delay、retain_success、reconcile_commit。Action绑定精确action_binding_ref、Controller/device、固定parameters_ref／parameter_schema_ref、completion_policy_ref、supersedes_command_ref、budget_charge_refs及可空schedule_window_ref。前序结果引用只在有批准成功证据后解析一次；完整能力Schema二次验证成功才固定参数，不用默认值代替未知结果。

计划只包含本次选中转换或规则的可执行路径；由编译产物重建完整顺序、requires_success/data/guard依赖，不能信任调用方省略步骤。状态机按exit→transition→enter→commit，顺序组按ordinal，必需并行组只能启动同组中依赖已满足的成员。并行首个失败使组停止新受理，已提交成员按各自原command核对；尚无本地command_ref不证明远端未受理。成功retained保留原command及证据，永不生成新提交。

StepRecord保留plan_ref、revision、state/outcome、submission_ref／command_ref、完成证据和result_ref。终态、资源释放与结果可供后继使用分别判断；result_ref只在批准成功证据存在时可用。wait/ready尚无副作用证据；submission_pending代表本地已承诺提交意图；accepted只证明Controller可靠受理；awaiting_evidence不代表失败；indeterminate不允许按“未发送”继续。

CommandSubmission绑定整个远端请求身份：target_scope、issuer、principal、request_epoch、operation=createCommand、idempotency_key和request_digest；参数、step_plan引用不可变。accepted／rejected必须保存同Controller scope的adjudication_ref，绑定原身份的持久受理／最终拒绝依据；单个布尔标志不作为生产证据，完整回执内容与权威查询仍待内部协议归并。context/token是临时运输凭据，不保存到此记录或日志。状态更新后submission_digest覆盖当前完整记录，**request_digest不随查询或state变化**，不能拿两个摘要互换。

| 本地状态／事件 | 允许动作 |
| --- | --- |
| planned | 新鲜前提、参数、全部预算和时间窗口仍合格；事务写attempt_clock/tick及attempt_recorded后，仅当前活进程的该路径允许一次发送调用 |
| 标记持久后、实际调用前崩溃 | 不能证明没调用；重启只查询原身份，不重发设备请求 |
| 响应丢失／timeout／lookup not_found | indeterminate；not_found不是未来不受理证明，不换key重试 |
| 当前可信应答accepted且完整身份匹配 | 绑定精确Controller scope的command_ref；后续只查询／收集原命令证据 |
| 最终拒绝且有持久拒绝证明 | rejected；不把普通HTTP错误或中间代理失败当永久拒绝 |
| 原命令未知／需要人工重做 | 原请求永久拒收／传输退役、原命令resolution及资源释放分别取证后，新预览新执行，显式supersedes；旧成功不重放 |

“一次调用”只是模型边界，不证明网络至多到达一次。服务客户端／代理必须关闭隐式写重试；Controller自身原请求幂等、永久拒绝依据和所有写出口屏障仍是必需。原请求已在网络中但lookup尚未见到时，不能用连接关闭单独证明设备无效果；缺Controller原身份拒收证明或原命令核对结果时保持未知。该拒收／取消关联仍须进入公共接口和IPC，不能从本Schema推断已实现。

## 3. 延迟锚点与最终发送窗口

现有AR04把delay锚在执行触发受理时刻；它表达执行偏移，两个5秒节点不必累加。这与“顺序等待”容易混淆。推荐新ExecutionRuntimePolicy逐step显式选择`execution_admitted`或`step_ready`，编辑器默认顺序等待使用step_ready；前者仍保留以表达同执行的固定偏移。旧program候选继续按原execution_admitted解释，不能静默改默认或原摘要；新语义须另版发布。

ExecutionAnchor统一记录anchor_id、revision=1、scope/execution、origin_ref、clock、anchor_tick和摘要；普通执行origin_ref为TriggerDecision，恢复执行为本次ExecutionStart，不给普通触发虚构恢复operation。锚在受理／R4提交返回成功之后采样，再由短事务固定；锚未可靠保存前不能派发，任一切点崩溃默认暂停，不能猜测SQLite实际提交瞬间或复用旧触发时间。R4内start_tick是开始事务的观测值，不替代这个提交后锚。

step_ready在依赖／前置阶段第一次可开始且execution锚已保存时，由Seamer短事务记录不可变StepReady（ready_id、revision=1、scope/execution/step、step_plan_ref、clock、ready_tick、dependencies_digest和ready_digest），重复唤醒不重置；两个5秒顺序等待的第二锚在第一步完成后才建立。并行成员各自就绪；先完成成员不让后续组提前开始。

DelayRecord保存scope、execution/step、execution_anchor_ref、anchor_ref、policy、clock、anchor、due、deadline、state、revision和digest。anchor_ref按模式指向ExecutionAnchor或StepReady，核对scope、ID/revision/digest、execution/step与同域tick，不能只比较两个数值相等。`due=anchor+delay_ms×10^6`，`deadline=due+max_lateness_ms×10^6`，全部为精确U20纳秒文本，计算溢出拒绝。0延迟可立即就绪，但仍不能越过保护。允许窗口`[due,deadline)`；等待占execution槽，不提前占设备资源。elapsed只解锁计划进度，不独自授权设备写。

DelayPolicy的window_scope固定direct_successor：执行图上的直接后继是动作时，ActionPlan.delay_window_refs完整绑定这些窗口，直到最终Controller出口仍取交集；直接后继是另一个delay或其它无设备写节点时，在本地StepReady事务于窗口内消费该依赖边，再建立后继自己的锚。不能把所有历史delay截止永久叠加到后续所有动作，否则两次顺序等待会被第一窗误杀；也不能在动作本地排队时就丢弃窗口。多条当前直接等待依赖及C06绝对窗口取交集，消费键为(delay身份,successor step)，状态与StepReady或命令绑定同事务。完整依赖边消费记录与最终Guard关联仍待DDL／IPC归并，参考模型只检查单窗口及两种锚的算术。

暂停、接管、撤权、关键存储故障、域变更或重启使未消费等待cancelled／保护锁存；时间经过或新登录不恢复。新的恢复等待要显示新锚及截止，重新批准；绝对排期的原场次锁存仍不可复活。event固定参数不受原event TTL机械取消，但来源前提、grant、实际发送时间继续重验。

跨服务不能直接比较Seamer和Controller tick。推荐WindowTranslation用Controller挑战往返绑定Seamer的同一delay记录、execution/step、原due/deadline、源和目标clock、两个批准速率profile及原始采样。设Controller发送挑战／收到应答为p/q，Seamer在收到挑战后、回复前的单调样本为s，源时钟速率误差界rs、目标rt（相对真实经过时间，均小于1），则本设计推导的保守窗口为：

```
target_not_before = q + ceil(max(0, due-s) × (1+rt)/(1-rs))
target_deadline   = p + floor((deadline-s) × (1-rt)/(1+rs))
```

所有量按纳秒及精确有理数处理。deadline<=s、p>q、区间为空、域/profile变化、challenge或采样因果不可信时拒绝。公式的成立依赖两个时钟在覆盖区间内的速率界以及采样确实位于往返中，**不是本轮测得的物理保证**；NTP UTC准确度不能替代单调速率profile。无合格profile时不开放跨宿主延迟派发。最终Controller许可还须交集自己的命令TTL、授权／证据期限及C06绝对窗口；不把Seamer进程“已elapsed”当设备已按时发出。新采样可减少保守余量，但不得修改原源deadline或复活已锁存过期步骤；实际出口仍查当前同一窗口绑定。

## 4. 边沿及稳定窗的记录

EdgePolicy包含方向、enter/reset raw、单位、stable_for_ms、max_sample_gap_ms及reset_required。此局部格式／参考向量使用已批准codec的精确整数raw；不能据此删除其它已承诺数值类型，后续正式数值Schema与全部设备codec映射仍须统一。上升reset<enter、下降reset>enter；阈值无隐式量化。

EdgeBinding固定scope/definition/run/arm_generation、source注册及revision/epoch、clock和policy_ref；EdgeState记录revision、needs_reset/armed/tracking、last_sequence／sample_digest／sample_tick、candidate_since及last_decision_id。EdgeSample绑定observation与age evidence，包含live/baseline/reconcile分类，不能仅凭“收到时间近”认定新鲜。

初次／新来源／新布防进入needs_reset；baseline和reconcile只更新基线，不能充当已观察reset的live样本。先有合格live reset才armed，进入阈值区开始tracking；在enter与reset之间的样本终止稳定候选，但仍保留已观察reset资格。每个样本必须通过权威年龄、单调tick与递增sequence检查；连续样本间隔允许等于max_gap，但当前年龄必须严格小于max_gap。样本缺口、倒退、不可用或过期清候选并触发运行保护，不能靠下一条高值自动补满时间。

稳定窗只能在新的合格样本到达且累计样本跨度足够时完成，定时器不能独自触发；这证明所见采样满足条件，不证明样本间连续物理信号。形成edge同时消费本次边沿、回needs_reset；busy／未布防时也保存suppressed决策并消费边沿，恢复后保持高值不补触发。新reset之后才允许下一次edge。

完整实现必须在同一个Seamer事务提交EdgeState CAS、EdgeDecision、TriggerInbox/Decision及可选execution，更新last_decision_id；上游样本重复返回原决策。参考模型只计算检测状态及结果码，不实现这组事务、完整来源提供者或旧decision存储；同sequence异内容拒绝，换source_epoch须显式新baseline而不能重置去重后重放旧样本。

## 5. 规则、链与设备预算

BudgetKey绑定拥有者scope、organization、namespace、stable_subject_id、unit。definition按稳定definition_id计execution，不含run/version；verified_chain只接受可信因果注册；无可信因果归入组织级unattributed_chain，不能为每条未验证事件分配无限新链。device以Controller批准的物理device_id计command，别名不能分桶。namespace、subject、unit由可信提供者选择，模块或请求不可任意指定来逃避。

BudgetPolicy为固定key、独立BudgetLimitRef及window_ms／limit／max_live_charges；BudgetLimitRef.digest覆盖这三个数值字段，其内容不反向引用ExecutionRuntimePolicy，避免自引用摘要。ExecutionRuntimePolicy整体摘要覆盖delay／edge／budget清单；BudgetCharge绑定key／limit ref、charge_id、execution/step、amount、clock、charged_tick和charge_digest。定义预算unit=execution且step_id=null；动作预算unit=command且step_id非空。各单位分别核算，不能相加比较。

采用同域滚动窗口`(now-window,now]`，量限与活跃记录数都有限；候选结构上限4096次／窗口、窗口1ms—24h只作为有限格式范围，不是生产默认或吞吐承诺。实验用10ms/2次仅用于边界向量。首次记账同writer事务，重试同charge返回原记录、不重复扣减，也不自动成为新的发送许可；同charge异内容拒绝。改变limit/profile需显式迁移与重预检，不能换版本清账。

规则／链预留先于Controller受理，Controller设备预算与其T1命令受理同事务；各方不具分布式原子性。后端失败可能留下已扣的保守额度，不向未记账发送放行。未发送、取消、失败、已发或未知都不退款；计数仅按已批准窗口自然老化，原请求身份／charge墓碑仍留存。超限同时锁存相应自动化，窗口移动不自动解锁；人工恢复重建绑定但保留有效窗口内已扣额度。域切换或无法证明经过时间时不得把旧账自动归零，需明确维护基线与停用边界。

真实持久实现须以稳定key查账及原身份墓碑，不能把保留的历史charge无限装进内存。本参考模型只用有限夹具dict保存全部记录；历史归档、去重floor、预算迁移及跨服务预留/拒绝回执仍需完整DDL/IPC归并。图文实时输出和只读遥测不是command额度，保护查询有独立保留资源，不能被普通动作耗尽。

## 6. 故障与验收交付

以下XRT是**待运行**的验收规格，扩展既有EX/AU/CT，不将离线结果登记为真实系统已通过。

| 编号 | 故障或边界 | 必须取得的证据 |
| --- | --- | --- |
| XRT01 | R3 ready后新增同reason接管latch | R4不清新latch，不发送，保留原preview已消费 |
| XRT02 | R4提交前／后崩溃、响应丢失或换start ID | 一个start／execution，原结果可查，重启关闭，旧步骤不续跑 |
| XRT03 | reconcile_commit误含动作 | 拒绝；纯核对只提交原效果证据与业务状态，无设备intent |
| XRT04 | 本地提交标记后、HTTP写前／后崩溃 | 原身份查询；not_found不授权重试，迟到受理仍归原step |
| XRT05 | 并行一成员失败且另一成员尚无回执 | 停新成员，查原身份／取消核对；不据本地空command推断未发 |
| XRT06 | 顺序两个5秒、执行偏移两个5秒、零等待 | 锚符合固定新版策略；重复唤醒不延后截止 |
| XRT07 | RTT耗尽、速率界失效、跨域tick、等于截止 | 最终Controller拒发；elapsed不能绕窗口；真实采样因果和平台速率另验 |
| XRT08 | 延迟中接管／存储失败／重启／排期过窗 | 旧等待锁存取消，显式恢复不能复活原场次 |
| XRT09 | 高值baseline、样本缺口、稳定窗定时器、同序号异内容 | 无伪边沿；缺口保护；只有合格live采样完成稳定窗 |
| XRT10 | busy期间触发、恢复后持续高值 | 原边沿抑制且消费，必须重新reset后才产生新触发 |
| XRT11 | 新run／新版／无因果事件／device别名绕预算 | 稳定桶不变；超限锁存，原charge不退款，不影响保护保留额度 |
| XRT12 | 跨服务部分预留、账本COMMIT未知、重启／换profile | 保守扣减与原身份查询，未记账不发，旧计数不自动归零 |

离线检查使用手写预期验证Schema、摘要错配、R4／单次提交、相对与跨域窗口算术、边沿采样及滚动计数。授权、完整计划、Controller目标、速率与证据真实性均为人工前提，未执行完整DAG调度、采样因果、状态提交事务或真实并发。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-execution/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-execution/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-execution/check_contracts.py --check-report
```

报告绑定8份原始输入，可加--staged只核对暂存字节，不重跑。完整Seamer表／唯一性与外键、运行对象查询投影、C05完整输入提供者及EdgeDecision事务、C06 ScheduleGuard、预算／时间翻译内部消息和公共SDK同版归并仍须完成。本轮推进这些记录的具体格式与规则，不关闭C04或阶段0。
