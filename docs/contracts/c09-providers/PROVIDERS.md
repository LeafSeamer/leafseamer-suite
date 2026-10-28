# 面板提供者读集协议候选

本稿补齐C09的进程内提供者协作接口，固定SDK `aff5ccbb75b6140109f948f81284785c75e46d1e` 的panel4完整选择，沿用其中35方法、23结果变体、181顶层字段和14类提供者分工。`approved=false`、`runtime_ready=false`；不增加公开HTTP、IPC或面板帧，不修改既有契约选择。来源及字节身份见 [sources.json](sources.json)，行为参考见 [readset.py](readset.py)，实际结果见 [report.json](report.json)。

## 读取计划与信任入口

可信宿主先按完整请求与当前权限生成只读计划，再构造 `ReadSet(context, expected_sources, source_validator, result_validator)`。面板不得提供读取计划、来源对象、验证器、通过标志或票据。内部摘要仅绑定字节，不能证明批准；宿主必须先核验原始安装、激活、授权、文档代次及请求归属。

`context` 为封闭对象：`selection`是当前完整选择；`authority`为该方法的controller或seamer角色；`method`是固定35方法之一；`request_id`标识本次宿主读集；`input_digest`绑定完整已校验方法输入；`public_binding_digest`、`activation_digest`、`installation_digest`、`approval_digest`、`authorization_digest`分别绑定完整原件的JCS／SHA256小写64位摘要；`scope`包含目标authority_service_id和database_instance_id。服务角色与实际服务身份的映射由可信路由配置核验，不能由面板选择。`request_id`不是新的领域写请求，读取失败不重新受理写操作。

方法决定唯一结果变体和完整字段分组。直接字段由`root`读取者负责，其原件模型必须为该变体规定的source_model；其余字段严格分派给14类具名提供者。`root`是直接读取入口，不是新增第15类派生提供者。缺字段、多字段或跨组提供字段均失败，不合并未知字段。

`expected_sources`必须精确包含该方法实际需要的全部分组。每组是有序、非空的 `{model, ref}` 列表；root恰好一个。model为当前选定契约的模型名，ref采用当前ObjectRef七字段：authority_service_id、database_instance_id、entity_kind、entity_id、entity_epoch、revision、content_digest。身份字符限英数、点、下划线和连字符，最长128；revision为无前导零十进制字符串、最长20；content_digest为完整来源值规范字节的64位SHA256。原件内部有自身摘要时，两者分开，不能把内部摘要当整份原件摘要。

同组不允许重复对象／epoch／revision。所有来源必须属于context的同一权威数据库；跨服务来源必须先由该权威的正式采用协议登记为本地不可变事实及撤销依赖，再列入读集。直接把远端对象放进列表、共享snapshot_id或重算摘要均不形成原子读资格。没有正式采用证据就整体不可用。

生成expected_sources时须在目标数据库一致读取事务内收集精确原件，并登记授权和生命周期失效依赖；事务结束只释放读取锁，不延长有效期。当前版本参考模型校验调用方固定的来源列表，尚未实现该事务、依赖监听或跨服务采用机制，不能把构造成功称为取得当前读权。

## 接口、状态与预算

| 接口 | 输入和成功结果 | 失败行为 |
| --- | --- | --- |
| `ticket(provider)` | 返回与本读集、该分组绑定的进程内不透明Ticket，每组仅签一次 | 未登记组、重复签发、截止或关闭均拒绝 |
| `provide(ticket, sources, fields)` | sources逐项含model/ref/value，必须精确等于计划身份，整值摘要及来源模型验证通过；fields恰好等于分组字段 | 合法票据提交中任何失败关闭整个读集，清空已收集值；不能返回部分结果 |
| `fail(ticket)` | 已签出的提供者明确报告无法完成，关闭读集 | 不接受伪造或已消费票据 |
| `seal()` | 全分组齐备、无在途验证，执行完整结果验证器后返回单次Candidate | 缺组时保留读取状态供其余组完成；验证失败、失效或截止则关闭 |
| `consume(context, candidate)` | 精确复核当前上下文，返回一次完整结果字典 | 错上下文关闭；跨读集候选、重复消费、撤权或截止拒绝 |
| `invalidate()` | 可信宿主收到授权、激活、导航、来源生命周期、配置或采用撤销后立即关闭 | 幂等清空票据及结果，不等待慢校验器 |

状态为reading→validating→sealed→consumed，任一有效阶段均可进入invalid；不复活、不重签、不刷新截止。单组提交在锁外校验并在回写时复核状态，最终结果验证同样在锁外执行；因此撤权不会等待慢适配器完成。无效外来票据不消费合法票据，合法票据中途失败则整组失败。Candidate和Ticket不能序列化或从同形JSON重建。

实验预算：每组最多64来源，整读集最多256来源，最多14派生组加root；普通值最多262144规范字节、32768节点、深度48；来源集合和累计分组最多1048576字节，最终结果仍最多262144字节。数组不能为适应预算而截断。每读集使用同进程单调时钟，期限1—2000毫秒；到期等号与观测到倒退均关闭，不把tick换成UTC或在重试时续期。这是候选预算，尚未批准为生产容量profile。跨进程时钟不可直接复用。

## 14类提供者的输入与不可省略的核验

所有行都适用上述来源列表、完整字段组和最终复核。返回fields只包含该方法在 [固定字段登记](source/bindings.json)中分配给本组的字段，不能用下表扩展输出。

| 提供者 | 必须读取的权威事实 | 必须保持的关系与失败语义 |
| --- | --- | --- |
| session | 当前会话、安装审批、功能、预算及会话用量 | 方法功能取批准交集；只返回该会话预算，用量不能因预算下降归零 |
| page | 固定目录或证据快照、过滤条件、limit、cursor及会话句柄登记 | 保存句柄与读取快照一致且不续期；失败不能暴露cursor或返回伪末页 |
| dynamic | 安装批准的完整Schema、Profile、字段权限与精确来源值 | 调用当前动态校验器；缺根／容器／叶权限整值不可用，不强转或裁剪完整编辑内容 |
| visibility | 完整目标集合、当前对象及字段可见性 | 隐藏项保留has_hidden，不泄漏数量，也不能通过删项宣布风险消失 |
| identity | 完整issuer／epoch／principal及当前查看者关系 | self/other/none不得按裸principal_id匹配；受限标签不作为身份凭据 |
| control | 当前控制原件、操作目标、gate及全部在途／未决引用 | ready必须来自当前同代完整关联，历史effective不能延续当前资格 |
| command | 命令State、取消、处置、完成及资源证据精确原件 | 受理不等完成；unknown即使资源clear也保持锁存，不能删原因 |
| definition | 原事务草稿或固定发布原件、元数据、制品及编译证明 | 当前／历史发布读取分开，完整PublishedVersion精确匹配；不能取最新草稿补齐 |
| execution | 同run／slot、原操作、完整执行命令登记及恢复计划 | 活动槽修订独立于run修订；已终结命令也属于完整集合；不能由unresolved推导全部 |
| targets | 当前run代次所有准备／保护目标及两代GrantRef | 保留pending/applied/closing/closed/unknown；两代grant不合并，本地关闭不代表远端保护完成 |
| handle | 原预检／恢复记录及会话、激活、原截止登记 | 返回固定不透明句柄；换代或到期拒绝，不通过重新展示续期 |
| deadline | 原clock域／epoch与issued/expires、同域可信now | 先整数判截止，剩余毫秒向下取整；未知为null而非新授权，不能转为UTC |
| vocabulary | 固定受控原因／标签词表和原状态 | 未知内部文本映射有限unavailable，不返回异常细节，不把unknown改为成功 |
| proof | 原definition/version/proof登记、精确修订和完整证明 | program/bindings/graph摘要一致，verdict来自原证明，不采信面板自报 |

source_validator必须按当前选定的具体模型校验来源，并核领域语义／关联；返回True才通过。result_validator必须校验完整当前结果结构、动态字段批准、跨字段领域规则及总预算；返回True才通过。两接口失败必须抛出异常或返回False，不能用空对象替代。直接字段由参考模型逐路径从root原件取值并比较规范字节；派生字段语义仍由各提供者及最终验证器承担。

现有publication-current和panel-current已提供发布两个槽位的隔离参考，可以作为definition／dynamic适配基础；其余表中来源读取、Schema批准与领域语义适配尚未完成。本读集协议不会把这些职责声明自动变成已实现提供者。

## 最终释放与持久化边界

消费Candidate仅返回进程内值，不调用网络发送。生产宿主必须将consume、当前授权／导航／来源失效复核与唯一输出Gate的入队判定置于同一可证明串行边界；入队之后尚未发送的字节仍按Gate规则失效，已进入传输层字节不可撤回。不能先consume再无条件排队。下述协调器实现已登记依赖在本进程内的失效串行边界；最终发送衔接、worker硬内存限制、全局并发调度和真实权威事件监听尚未实现。

读集本身不持久化Ticket或Candidate，进程重启后全部丢弃。页／评估句柄由其权威存储按独立接口原子保存；领域写入已提交时，读集失败不回滚业务操作，也不能换新请求重发。对面板仅使用当前通道允许的有限不可用状态，内部异常及来源原件不会直接进入响应。

正常轨迹：可信宿主核当前会话和请求→在一致读取中固定来源列表→按方法取得root与全部提供者票据→每组提交精确来源和字段→完整结果验证→最终Gate内重新检查并单次消费。故障轨迹：root已返回、dynamic校验中撤权→invalidate立即关闭→迟到校验返回不能写入或封装→已受理领域操作仍可按原请求查询。

## 通用读集验证

```text
python -B docs/contracts/c09-providers/check_readset.py --sdk <SDK仓库> --report
```

检查固定Git原件、当前模型中全部35方法对应结果的字段集合，实际运行全部14分组的合成读集；覆盖替换来源、错字段、单次票据、部分失败、截止等号、时钟倒退及两个真实线程撤权场景。测试来源和结果采用显式合成const Schema，不声称已验证真实领域适配器。数据库、网络、浏览器、设备、生产审批和最终输出Gate运行计数均为零，阶段0继续开放。

## 固定模型配置与动态批准

[typed_validators.py](typed_validators.py)提供固定panel4模型配置，加载的原始models.schema.json必须与 [typed-sources.json](typed-sources.json)中的完整字节摘要一致；不接受改写后的字典、旧选择或未知模型回退。1463模型全部引用使用本地闭包，资源解析拒绝网络获取。来源按指定模型做实际JSON Schema及format验证；结果按方法唯一变体验证完整结构，并执行已有的时钟区间、命令锁存、预检和恢复显示不变量。

```python
contract = Contract(models_bytes, selection)
readset = contract.readset(
    context, expected_sources,
    dynamic_validator=approved_dynamic,
    source_guard=current_source_and_rights,
    result_guard=complete_domain_relations,
)
```

配置始终绑定精确method。即使controller与seamer返回同形MetaView，也不能把一方已绑定的验证器用于另一方法。source_guard(context, model, value)与result_guard(context, view, value)必须由可信宿主明确提供并返回True；缺守卫不能构造此配置的读集，结构合法也不能绕过守卫拒绝。守卫负责来源当前性、授权、完整领域关联和本地采用事实，可闭包绑定该一致读取中的完整计划及不可变原件。底层`Contract.validate`只提供结构检查，不独立证明这些事实。

动态入口dynamic_validator(method, JSON Pointer, kind, value)只在静态结构通过后调用，必须明确返回True。位置包括能力actions的参数／结果SchemaRef、triggers的载荷SchemaRef与状态SchemaRef；观察`/values`的QualifiedValue；草稿／发布的完整`/content`与`/metadata`；恢复每一步的每条evidence_summaries与非空parameters_summary。kind分别为schema_ref、qualified或raw。缺入口或任一项拒绝使整个结果不可用；空恢复证据列表及null参数依旧由静态模型和领域守卫判断，不制造虚拟摘要。定义的layout即使为空也需要当前批准，不能借静态开放对象默认放行。

该入口应连接当前批准Schema、字段权利及来源适配器，不能注册无条件返回True的生产策略。校验器拿到的是副本，不能通过改值实现隐式裁剪。上述检查发生在读集封装阶段；封装后的撤权仍必须触发invalidate，并在最终输出Gate复核，不把本配置宣称为已接通发送门。

```text
python -B docs/contracts/c09-providers/check_typed.py --sdk <SDK仓库> --report
```

[typed-report.json](typed-report.json)单列真实模型检查：全部35方法／23变体、181项缺字段反例，以及Meta、公开时钟、Observation、DraftRecord四类完整来源样例；这不代表1463模型均完成领域行为验收。三个读集正例中，观察值实际连接固定SDK动态提供者并运行两个Schema子进程，验证错误类型、缺字段权利和撤权拒绝。其余动态位置使用显式合成策略；领域守卫采用合成的精确原件／结果批准，未接真实审批或数据库读取事务。通用357项报告仍独立保留，不能把两个报告的数量当成全部生产提供者完成度。

## 进程内依赖失效协调

[coordinator.py](coordinator.py)的Coordinator由可信宿主独占。宿主在一致读取之前登记每个当前权威代次的清理回调，取得不透明Dependency，并为读集提供完整依赖集合。Dependency只证明登记身份，不证明权限；来源、导航、安装、批准及授权代次的真实核验和无丢失事件订阅仍由宿主负责。不得在原件读取后才补订阅，也不能把已撤销权威重新登记为新代次。没有真实订阅的宿主不能以本参考宣称生产撤权已经接通。

```python
coordinator = Coordinator()
approval = coordinator.register(dynamic_authority.revoke)
reading = coordinator.begin(
    [approval, source_lifecycle, navigation],
    lambda: contract.readset(context, expected_sources,
        dynamic_validator=approved_dynamic,
        source_guard=current_source_and_rights,
        result_guard=complete_domain_relations),
)
# 只通过reading提交各组、封装和消费；失效事件先调用coordinator.revoke(approval)。
```

begin先检查依赖及容量并保留构造名额，然后在锁外调用可信build；build只能返回全新、尚未签发任何票据的ReadSet。返回后重新检查依赖，任何构造期间失效均拒绝迟到结果。构造器不得保留底层读集用于另行交付；托管对象不是不可信Python代码的隔离沙箱。真实动态权威也不能绕过协调入口直接撤销或交付，否则该协调器无法观察事件。

ManagedReadSet提供ticket、provide、seal、consume和close。除consume外的慢校验在协调锁外执行，依靠底层读集回写时复核失效。托管调用遇到任何异常都会关闭本次读取并释放容量，包括过早seal的不完整结果；这比基础读集的可继续收集语义更严格。调用者应先收齐全部组，并在退出时用close释放未完成读取；没有后台到期扫描。consume在同一协调锁内核登记依赖并单次消费，无论成功或失败都移除读取，不允许换上下文重试。

revoke先在协调锁内移除该依赖并关闭所有关联读取，包括封装后的候选和构造中的保留项，再在锁外执行登记的清理回调。清理异常仅报告dependency_cleanup，依赖保持关闭；重复撤销不重跑回调。无关依赖的读集不受影响。close永久关闭协调器、失效全部读取并逐一执行所有剩余清理，即使一个清理失败也继续其余清理。与已在另一线程执行的清理不会重复调用，close不是等待那些线程结束的屏障。

最多64个读取名额、256个依赖名额、每个读集16个不同依赖；可下调，不能上调。被撤销但尚未返回的构造仍占读取名额，尚未完成的清理仍占依赖名额，防止通过重复撤销绕过在途容量。此上限只覆盖一个Coordinator实例，不能代替宿主全局调度或线程／worker硬限额。可信单调时钟须为快速本地读取，不得在持锁消费期间等待外部服务。

串行规则是明确的：撤权先取得协调锁，则相关读取不能消费；消费先取得锁，则该次本地返回可以完成，随后撤权不追回已经返回的值。慢外部清理不会推迟本地失效。返回值后的网络入队、缓存或重试仍必须经过正式输出Gate，本参考不提供排队或发送API。源数据库事务和外部事件之间的原子关系也不由此进程锁证明。

```text
python -B docs/contracts/c09-providers/check_coordinator.py --sdk <SDK仓库> --report
```

[coordinator-report.json](coordinator-report.json)记录157项检查：35方法托管消费、选择性依赖撤销、失败关闭、名额回收和6个实际线程场景，包括8线程竞争同一候选。固定SDK动态权威实际运行3次Schema子进程；测试明确展示基础ReadSet没有外部事件订阅，并验证登记后的动态权威在封装后撤销会同时关闭本地交付及SDK权威。领域守卫仍采用显式合成批准，事件由测试宿主显式触发；真实事件监听、生产鉴权、最终输出Gate、数据库、网络、浏览器和设备运行计数均为零，approved=false和runtime_ready=false继续保留。

[完整面板结果与局部释放边界](DELIVERY.md)进一步将读集消费与不可变host.result入队放入同一协调锁，来源依赖延续至队列释放。完整帧绑定原请求、激活及方向序号，并实际校验64KiB上限；慢资格重读、非阻塞出口和撤权具有明确顺序。两个真实本机TCP场景仅证明该局部明文出口，浏览器MessagePort、其余帧、保护队列和产品最终输出Gate仍待接线。
