# 安装0.2：角色解析、审批与启动绑定

版本`extension-installation/0.2.0-draft.1`是待审阅候选，归并[0.1安装格式](README.md)、[角色／导入候选](../c09-artifact-import/README.md)及[DF02运行域设计](../../rebirth-df02-runtime-design.md)。以下为项目方案，不是实际服务、监督器或设备行为；保留原0.1、公共draft.4和IPC0.3原字节。

## 1. 版本和唯一源

[build_v02.py](build_v02.py)复用原唯一定义源，只显式修订本批字段，生成[Schema](installation-v02.schema.json)及[OpenAPI](installation-v02.openapi.json)。角色格式直接从artifact候选提取固定具名闭包，旧安装Ref投影为本地同形模型；不联网取Schema，不把生成投影当第二源。实际SDK源迁移仍按DF01统一进行。

15个管理HTTP操作采用必需头`X-LeafSeamer-Contract: extension-installation/0.2.0-draft.1`。版本不匹配拒绝，不能先按新版失败再试旧版，也不能给无头客户端默选0.2。该头选择候选接受集，不代替人员认证、Origin或POST CSRF。旧服务是否继续提供0.1由发布组合显式声明；本资料不部署双协议运行。新增内部启动模型不导出到管理HTTP components。

## 2. 从制品到新实例的接口衔接

| 入口／对象 | 0.2具体变化与权威 |
| --- | --- |
| POST extensions/stage | context、slot_ref、expected_slot_revision、source；source为intake/intake_ref或retained/content_ref两分支。两者都分配新installation_id；后者只复用当前仍合格的制品，不复用旧实例或审批 |
| POST extensions/{installation_id}/resolve | 新增ResolveRoles：context、expected_installation_revision、configuration_ref、bindings。模板从该实例已验证manifest取得，客户端不能上传permissions。成功返回ResolutionView{resolution_ref,record} |
| PermissionReview / Review请求 | 新增role_resolution_ref；review仍固定requested/proposed权限、配置、安装及内容摘要。requested来自该解析的精确输出，proposed只能收窄 |
| Approval | 新增role_resolution_ref与permissions_digest；approved_permission_ids从review.proposed选择，不回查宽模板。既有Approve请求用permission_review_ref已传递完整关联，无第二份可由客户端替换的resolution参数 |
| InstanceView | 新增可空role_resolution_ref，表示当前选择；新解析不会原地改旧解析。已有批准后改配置／解析必须退役旧实例并新建候选 |
| Enable | 改为context、expected_slot_revision、target_installation_ref、approval_ref、dependency_plan_ref，与Activate同形但用途和源槽位条件不同 |
| PlanSelection | enable与activate一样固定新target，reuse_content_ref在0.2恒为null；复用内容已移到stage。upgrade仍显式旧source和新target；uninstall没有新target |
| LookupResult | 新增ResolutionView分支；查询原管理identity的固定结果，保持当前身份鉴权，不重新解析或生成新实例 |

**修正旧enable冲突**：停用后的旧review绑定旧installation，不能给未来新ID直接使用。GUI先以retained source stage新候选，再resolve、review并展示精确差异，当前人员approve后执行enable。相同内容和范围可在同一GUI确认流程完成，服务端仍生成新审批；不能因用户点击一次就迁移旧permit、secret grant、PanelSession或来源证据。未确认的预备候选保持不可执行，取消按原operation清理；槽位removed不能作为恢复入口。

同slot允许多个未激活候选，但生命周期激活槽仍一次一个；stage采用当前revision CAS，已受理结果先于新CAS查询。resolve/review只能在未激活候选进行，不修改运行中实例的当前配置或范围。解析和审阅提交推进相应安装revision，但内容Ref与当前CAS修订分离；审批引用的不可变安装内容不能因正常状态变迁被改写。

## 3. 不可变关联与摘要

RoleResolution沿artifact候选：resolution_id、authority/database、installation_id、manifest/artifact摘要、配置、bindings、permissions及resolution_digest。ResolutionView的Ref为role_resolution，object_id等resolution_id，digest等resolution_digest，权威／数据库也相同。revision由服务登记，不由客户端选择。记录本身的摘要仅排顶层resolution_digest，不排任何嵌套字段。

PermissionReview摘要仍只排顶层review_ref/content_digest，因此新role_resolution_ref进入摘要。提交时校验review与解析的配置、安装、manifest、artifact、requested_permissions全部一致，再校验收窄关系。Approval同时固定review_ref与role_resolution_ref，所选权限按request_id ASCII排序后组成完整Permission数组，`permissions_digest=SHA256(JCS(该数组))`。数组包括收窄的scope及purpose；不能只hash ID，也不能从manifest重新展开覆盖收窄。

0.2明确采用artifact候选的`artifact_set_digest=SHA256(JCS(FileInventory))`，files按file_id排序。早期C09第15节的“按路径排序清单”不再适用于此版本；文件原字节hash与整包hash仍分别核对。该修正与本版本一起适用，不重解释旧收据。

## 4. 扩展启动意图及授权

ExtensionLaunchIntent是DF02 LaunchIntent的**worker分支候选扩展**，保留launch_id、service_id、supervisor_instance_id、runtime_generation、member_id、role=worker、artifact_manifest_ref、containment_ref、device_ids和policy_revision，并新增ExtensionLaunchBinding。core/time_provider引导继续按DF02，不强塞安装审批；纯静态panel也不伪造worker进程，以安装／挂载链单独激活。

ExtensionLaunchBinding必含installation_ref、approval_ref、review_ref、role_resolution_ref、configuration_ref、intake_ref、platform_profile_ref、host_installation_id、host_trust_epoch、manifest_digest、artifact_set_digest、entry_id、permissions_digest。外层artifact_manifest_ref指Node／原生启动层等**完整运行组合**的批准清单；内层manifest_digest指该扩展包，两者不同用途，不要求摘要相等。entry_id只能由已验证manifest的worker入口选择，不能传任意路径、argv或环境变量。

device_ids是当前权威资源图与批准范围给出的完整启动设备集合，按ASCII排序且唯一。不能只从device_scope字段取集合而漏掉helper、secret关联或隐式物理足迹；本参考以人工完整集合为前提，不实现资源图提供者。启动意图摘要按完整对象JCS计算，对象不自带摘要字段；原DF02的bootstrap/proof/receipt均绑定此新完整摘要，禁止剥掉extension_binding后沿用旧摘要。

LaunchAuthorization由当前核心权威在启动事务签发：authorization_ref、launch_id、完整intent摘要、installation/approval/resolution refs、permissions_digest、supervisor_instance_id、fence_revision及Lifetime。Ref.digest对删除顶层authorization_ref后的完整对象JCS取hash；Ref本身不是bearer token，只能经DF02已认证的核心通道交付及核对。它不签发设备permit，也不能代替OS成员身份。

fence_revision属于当前supervisor的启动准入状态。监督器先接收并确认当前完整拒绝下界／允许快照，再接受对应revision的授权；没有完成同步时新spawn关闭。撤销以安装／批准／publisher等完整作用域更新该下界，旧授权即使未到期也不得新消费。启动意图固定，短期授权可在**尚未尝试创建**且当前权威重新通过全部检查时续签；这不能清除creation_attempted、原进程记录或旧拒绝。

Lifetime的clock为当前监督域中双方已确认可比较的单调域，tick单位为纳秒；不相同则拒绝，不能把远端时刻直接与本地减法。候选授权寿命上限2秒，`issued <= now < deadline`，到期等号拒绝。验证实物采用前批VERIFY_MATERIALIZATION：intake、目标authority、两个摘要、trust epoch、challenge和launch_intent_digest必须逐项一致，使用其原5秒本地challenge窗口；实际加载前仍验证当前信任和保护内容根。两个窗口各自成立，不能用较长窗口延长另一个。

授权撤销传播不是瞬时全局原子：核心提交撤销到监督器收到fence之间，已有短授权可能已经创建**closed**进程。核心不能据旧回执发布active，必须按现状退役；进程不得连接设备或取得permit。保护完成须确认准入关闭及全部已创建成员退役，不能仅依赖授权过期。平台调度／传播及关停延迟仍须验证，不承诺创建动作与业务SQLite原子。

## 5. 事务、一次创建和未知恢复

| 顺序 | 同一权威事务及外部边界 | 失败处理 |
| --- | --- | --- |
| stage | 当前管理identity、slot CAS、新installation及内容来源／审计同库；实物从宿主只读核验 | 提交未知查询原identity，不重新分配实例；内容不存在不能自动下载 |
| resolve/review | 事务外有界读取角色证据，事务内重核对象及配置修订，登记不可变解析／审阅；没有网络或模块执行 | 证据过期／对象变更拒绝，不把partial集合批准 |
| approve | 当前人员权、固定review/resolution、选中收窄权限及全局拒绝下界同writer串行；登记Approval和摘要 | revoke先提交则拒绝；approve先提交则纳入撤销完整捕获 |
| launch prepare | 固定plan、源关闭／退役／资源核对、owner/出口预登记、新launch_id/intent、授权与outbox同库 | 提交失败不发spawn；outbox重送只查询同意图，不能分配新launch_id |
| supervisor register/create | 当前核心通道、fence、短授权、实物及保护配置核对；监督器记录registered，再在OS创建前记录creating/creation_attempted=true | creating之后丢回执不可再create；创建时即纳管，组／进程证据按DF02 |
| admit | 完成OS及bootstrap核验后回admitted_closed；核心再次核当前审批／拒绝和完整绑定，持久RuntimeBinding后才发布active_closed | 批准失效或COMMIT未知保持closed并核对／退役，不能因回执到达补开闸 |

LaunchRecord与不可变Intent分开，状态为registered→creating→awaiting_bootstrap→admitted_closed；关闭走retiring→retired。创建前拒绝可为rejected；创建之后未知为indeterminate，不能伪装为“未创建的拒绝”。runtime_binding_ref只有有真实准入证据才存在；retired必须retirement_ref。记录中的gate_state固定closed，表示安装启动交付的初始状态，不投影后续业务gate。

同(supervisor_instance_id,launch_id)只登记一个固定意图，重复消息同摘要只查询原记录，异摘要冲突。registered且可靠证明尚未进入creating时可沿同意图创建；creation_attempted=true后重送、进程退出或组为空都不能再次创建，新的恢复须新实例、新审批及新launch意图。已退休记录重复查询仍返回退休历史，不成为创建许可。

监督器的本机launch journal保存固定意图摘要、目标组、creation_attempted和本次OS绑定；它是运行监督恢复日志，不持有或写业务SQLite。启动后发现日志缺失、写入不可靠或旧域归属不明时关闭准入并执行DF02整域恢复，不能重建空日志当从未创建。日志耐久profile、受限存储实现及OS实测属于实施交付；没有可靠证据就indeterminate。业务库与该日志不跨库原子，查询／核对和保守退役解决中间态。

## 6. 验收与复验

正常轨迹：retained stage新实例→resolve→review→approve→enable固定target→launch登记→实物challenge→短授权／fence→一次创建与bootstrap→核心复核→active_closed。故障轨迹：创建成功回执丢失→原launch查询→旧组核对；撤销已提交则关闭／退役，不能换ID再起第二个进程。

| ID | 运行验收规格，全部未执行 |
| --- | --- |
| LACT01 | 旧enable字段和无版本头不能被0.2接受；不回退旧语义 |
| LACT02 | 同stage身份重送只返回原新实例；旧disabled installation永不复活 |
| LACT03 | 解析后改配置、角色对象修订、manifest或内容，旧review/Approval拒绝，即使重新计算公开摘要 |
| LACT04 | 收窄cache quota或设备集合后，启动批准摘要使用收窄内容；不能只按request_id恢复宽范围 |
| LACT05 | approve与revoke两种提交顺序均捕获全部相关实例；不能在撤销后另签同失效范围 |
| LACT06 | 错目标／角色解析／trust epoch／运行组合／entry或实物challenge，原launch不启动 |
| LACT07 | 短授权到期等号、跨域、旧fence拒绝；保护通道不能被普通启动队列饿死 |
| LACT08 | registered与creating前后断电、OS创建成功回执丢失，不多建第二进程；缺证据保持unknown |
| LACT09 | 撤销传播窗口中已创建进程保持closed，核心不发布可用并完成退役，不把过期当空组证据 |
| LACT10 | 进程已退出／组为空仍不复用同launch创建；新恢复保留前任退休和未决资源依赖 |
| LACT11 | Bootstrap HMAC与Receipt必须覆盖新增extension_binding摘要；剥离或借core角色绕安装拒绝失败 |
| LACT12 | 核心保存RuntimeBinding失败或提交未知，不OPEN_GATE、不自动化恢复；按原launch和operation核对 |

[check_v02.py](check_v02.py)的191项检查覆盖Schema/OpenAPI接受集、版本头、角色到review/approval及完整启动关联、重算摘要反例、局部账本和串行故障步骤。上游解析提供者为人工前提，本批不重跑所有manifest语义，也不运行真实HTTP、SQLite、IPC、OS或设备。原0.1检查独立回归，未将其未覆盖语义冒充新验证。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-installation/build_v02.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-installation/check_v02.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-installation/check_v02.py --check-report --staged
```

[独立报告](reference-v02-report.json)绑定10输入字节，staged检查只核提交材料不重跑。后续[监督器候选](../df02-supervisor/README.md)已给出bootstrap／启动准入IPC、journal布局与局部SQL探针：监督器返回AdmissionReceipt，核心持久化后才形成这里的RuntimeBindingRef，二者不混用；原LaunchRecord格式不改。完整生产DDL、真实字段提供者、保护容量批准、统一SDK和平台验收仍待完成；不把局部格式或参考检查当C09/DF02全部关闭。
