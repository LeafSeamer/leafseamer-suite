# F01—F07 整体一致性审阅与 draft.3 归并

- 日期：2026-10-17；用户已同意 F06／F07 推荐方案，本轮明确授权归并协议与校验资料，暂不修改业务代码。
- 已知项目事实：Q1—Q72、F02／F03、F04／F05、F06／F07 的推荐方向已确认；这些确认不等于运行验证或发布批准。
- 本轮工程结论：归并公共 `1.0.0-draft.3` 与 `ipc/0.2.0-draft.1`。文件位于 [draft3](contracts/draft3/README.md)，公共 draft.2 及三个候选目录保留作历史依据，不覆盖旧生成物。
- 后续确认：用户已同意draft.3／IPC 0.2、TS01—TS05及NF01—NF03。当前入口转到[draft.4／IPC 0.3审阅](rebirth-draft4-review.md)，显式归并运行域和NTP误差证据；本版host_boot_id不能填运行nonce，本目录机器文件保留历史。TV／PF计划与F01—F07运行验收未关闭，未修改业务代码。

## 1. 版本、依据与适用范围

本轮历史审阅基线为draft.3，后续运行域修订以draft.4审阅为准。不是同时运行两套可互投写请求的协议。预发布版本须精确协商，服务拒绝旧写协议／不完整worker特性；没有承诺draft.2客户端可直接发送draft.3。HTTP `/api/v1` 保留，服务部署及Meta明确协议版本，正式稳定版再制定升级兼容矩阵。

Schema 采用 JSON Schema 2020-12，OpenAPI 保留3.1.1并将每个服务的模型内联；IPC使用本目录公共Schema的版本化引用。条件约束与跨记录判定分开，不把 additionalProperties=false、readOnly或摘要当作身份授权。（表示规则来源：[JSON Schema 官方规范](https://json-schema.org/draft/2020-12/json-schema-core)、[OpenAPI 官方规范](https://spec.openapis.org/oas/v3.1.1.html)；本项目状态与保护语义来自已确认设计。）

候选来源：[首闭环](rebirth-first-loop-contract.md)、[F02／F03](rebirth-f02-f03-design.md)、[F04／F05](rebirth-f04-f05-design.md)、[F06／F07](rebirth-f06-f07-design.md)。生成器读取旧定义源并显式叠加差异；报告记录源摘要，发布前SDK需提取独立发布源，不能让可变Suite历史成为运行依赖。所有脚本只生成／验证协议文件。

## 2. 实质冲突及归并结论

| ID | 跨项问题 | 已落实处理 | 剩余证明 |
| --- | --- | --- | --- |
| M01 | unknown固定unresolved，与迟到证明可清资源冲突 | 原outcome保留unknown、暂停锁存；clear要求resolution及独立ResourceReleaseEvidence引用，且属于原command/attempt | 模块实际释放策略、来源和维护证据有效性 |
| M02 | 身份只有裸principal_id，而F04按签发域区分 | Actor、Session、RequestIdentity、RequestContext、RunGrant加issuer_id/epoch；Actor记录local_subject_id；SubjectRecord提供完整身份映射 | 签发方配对、权限与映射持久化 |
| M03 | global authorization_revision误当注销即全设备关闸 | 保留出口整体版本；AUTH_FENCE只安装selector拒绝下界，不修改持有人／control_version，不提高普通出口粗版本去阻断独立主体 | 真实撤销传播和最终出口排序 |
| M04 | 守卫只有代际，worker无法核算时间 | GUARD_INSTALL安装样本与排期守卫，DISPATCH绑定guard_id/digest；最终发送重新计算UTC区间及单调期限 | 两平台时钟、sample来源与负载预算 |
| M05 | 时间失效不一定换代 | TIME_FENCE允许old/new generation相同，按策略关闭相关绝对许可；恢复仍不补发旧场次 | 真实质量失效传播／锁存 |
| M06 | WS继承普通bearer升级不能落实浏览器路径 | 明确升级仅用单次票据子协议；URL无凭据；服务只回显固定子协议；签发用目标服务bearer | 浏览器／代理header脱敏、单次消费与撤销 |
| M07 | OBS模型存在但没有执行引用链 | SceneRef带集合代际／绑定修订；CompletionEvidence挂typed bundle，CommandRecord保存证据；查询端点及typed IPC候选 | 实际OBS组合、四帧顺序、资源释放与视觉验收 |
| M08 | EffectFootprint.action_ref字符串与公共ActionRef对象同名异义 | 改为action_id，完整ActionRef及产物／控制归属放ProofActionBinding；旧read_set/write_set为同源投影，分歧拒绝 | 足迹真实性、隐藏副作用及有限DSL |
| M09 | proof只有revision，不能定位发布证明 | StepDefinition改proof_id＋revision引用；DefinitionRecord携带权威证明；绑定定义／模块／目录／别名／分析器 | 发布时重算闭包及权威存储检查 |
| M10 | 恢复只有preview摘要、状态ready缺证据 | RecoveryPreview包含snapshot＋计划；resume返回RecoveryOperation；targets记录baseline→target及逐目标可靠receipt | SQLite CAS、跨服务准备、撤销和崩溃实验 |
| M11 | 202、applied、ready、设备效果与业务提交混用 | 各自保留；412表示前提失效；Error可引用existing_operation_id；恢复消费不复开finished命令 | HTTP丢响应、事件重传、真正幂等身份行为 |
| M12 | 通用幂等响应可能再次泄露单次票据 | 票据仅首次201返回；同身份200只返回WsTicketBinding，无secret，相关响应全部no-store | 浏览器丢响应、代理缓存与日志脱敏 |

这些是已确认约束的字段衔接与保守修正，不改变整台设备手动优先、未知不重放、失败不自动回滚、错过排期不补播、状态转换／并行全必需的方向。

## 3. 公共对象及端点引用链

- 身份：PrincipalRef是 `(issuer_id, issuer_epoch, principal_id)`。控制holder_id、requested_by和转交target_principal_id等历史命名的控制主体字段均解释为**目标服务本地不可复用subject ID**，通过 `/subjects/{subject_id}`解析完整身份，不是裸外部principal_id；后续SDK命名整理不得改变映射。跨issuer同名不等价，重建签发世代不继承旧授权。
- 能力：ActionDescriptor → EffectFootprint；SceneRef → 本设备CatalogBinding的collection_ref、generation、binding revision、catalog revision；`/devices/{device_id}/scene-catalog`返回目录。目录不是锁，旧会话失效仍按F06处理。
- 证据：CommandRecord → completion_evidence／resource_release_evidence；`/commands/{command_id}/evidence`分页查询。OBS成功必须存在可核验bundle，公共证据durable=true；worker候选durable=false，Controller核对并落库后才转公共证据。bundle的evaluation_tick及帧tick同属worker启动时钟域，Controller不能拿自身tick与它比较；Controller另审报告新鲜度与持久化结果，迟到只resolution。
- 事件：EventEnvelope → EventAgeProof，event_id/provider_boot_id/source_sequence必须一致；“unproven”结构可接收用于显示，不能触发需年龄证明的规则。OBS无可信发生时刻的事件不因接收新鲜而升级证据。
- 证明：StepDefinition.independence_proof → 发布DefinitionRecord的IndependenceProof。输入定义只引用证明，客户端不可提交verdict为自身授权；服务端发布／布防／失败继续均重新核对。
- 恢复：`/recovery-preview`返回RecoveryPreview(snapshot,plan,observations)；`/resume`返回202 RecoveryOperationResponse；`/recovery-operations/{operation_id}`查询受理后的真实进展。proposed_step_ids必须等于计划execute_new步骤顺序；成功保留、只提交、停止都不能悄悄变成设备写。
- 容量：CommandRecord.admission绑定已接受command及reservation；管理PUT只接受具有验证引用的release_candidate配置，结构存在不等于引用真实有效。实验profile仍是测试数据，不能作为生产批准。

归并bootstrap、登录、刷新、服务定向令牌、受保护introspect、授权撤销及查询、WS票据、时钟评估、容量查询／管理。bootstrap只接受一次性部署能力；登录只接受登录证明；Cookie刷新／令牌签发要求CSRF和精确Origin；introspect要求已配对mTLS并对audience授权；普通控制仍使用定向不透明bearer。Cookie的Path=/auth，Secure、HttpOnly、SameSite=Strict；登录／刷新通过响应头返回会话绑定CSRF值，不放进普通事件。令牌／票据响应必须no-store并脱敏。授权撤销端点由签发方提交或转交配对权威，目标服务不能伪造issuer_commit_revision。

只有浏览器人员会话使用当前WsTicketBinding，服务主体不伪造session接入；内部服务事件提交继续受保护HTTP入口，独立服务订阅协议若增加须另版本化。第三方面板只走宿主受限桥，不取得宿主票据／长凭据。

## 4. IPC 与发送顺序

13个原消息升级信封版本，另加GUARD_INSTALL、GUARD_ACK、AUTH_FENCE、AUTH_FENCE_ACK、TIME_FENCE、TIME_FENCE_ACK，共19类。HELLO／ACK协商 execution_guard、scoped_authorization_fence、clock_generation_guard、typed_obs_evidence、recovery_single_consume；ACK缺必需特性不开放写入，不能协商失败后偷偷降级。

顺序：持久化intent／guard → GUARD_INSTALL → 匹配GUARD_ACK → DISPATCH → 最终出口复核控制、精确撤销下界、授权截止、时钟与场次、资源、容量及一次消费 → 最多一次发送。GUARD_ACK只证明安装，不能代替OPEN_GATE_ACK、设备ready或授权事实；重复消息只返回原安装事实，不能续期。守卫摘要JCS排除guard_digest，其余全部固定；content_digest仍按既有请求身份投影，二者不能互换。

绝对守卫安装样本和ScheduleGuard，同域／同代／同策略才可用，发送处按F05完整UTC误差区间重算；样本过期或窗口进入时门控失效锁存，不能刷新样本复活旧permit。首次样本不足以覆盖排期未来时，直到近派发且有新鲜样本才分配新许可，早期排队不提前创建长期有效permit。即时动作sample／schedule均null，仍检查认证时钟与授权截止。

AUTH/TIME屏障ACK回显operation、barrier、策略／selector、切点及摘要，coverage必须与所给完整账本严格相等，命令清单是coverage投影。服务必须在构造清单前按权威guard索引取完所有匹配intent；worker也核对自己的匹配项，不能只证明“给我的列表都处理了”而忽略未列出的许可。旧worker意图不能自称未发。对外applied还需要固定目标集覆盖及Controller持久化receipt，worker ACK没有durable授权。

全局authorization_revision只代表Controller整体保护代际；选择性撤销更新selector拒绝下界及匹配guard，不强迫所有无关permit匹配一个新全局值。TIME_FENCE同代失效同样有效，old=new不是无操作。CLOSE_GATE仍用于存储／失控进程等整体保护，不能替代普通会话精确撤销。

## 5. 摘要、证明与恢复事务

proof.definition_digest固定为发布Definition的JCS摘要，递归去除每个StepDefinition的independence_proof引用，避免证明引用与定义摘要循环；其余参数／动作／谓词／顺序均保留。bindings_digest投影固定为：definition_id、definition_version、definition_digest、按ActionRef JCS字节序排序的action_bindings、dependency_graph_digest、dsl_version、generator_version、alias_revision。重复ActionRef禁止；每个绑定包含controller_id/control_epoch、目录、模块产物、manifest、semantics和参数Schema摘要。任何变化使旧proof失效，未知依赖不降级为空集合。

RecoveryPlan数组顺序有意义，plan_digest是整个计划JCS摘要；snapshot.preview_digest覆盖snapshot除自身摘要外全部字段。有效期在同Seamer启动单调域判断；重启旧预览全部作废。CAS消费同时保存请求身份、run revision、新execution／generation、计划、单次消费与审计；旧请求同键同内容按当前权限查询原操作，不因预览已过期重做。不同键竞争只能一个成功，不扩展旧场次或预算。

RecoveryPlan和RecoveryOperation分别保存固定target_controller_ids，操作targets必须完整覆盖；RecoveryTarget明确execution_id等于本操作new_execution_id。只吸收绑定本operation的grant／arm变化，不吸收同时发生的外部接管／撤权。准备不发送设备写，全部目标准备可靠后才ready；partial/indeterminate不把预览变回可消费。每条新命令仍有最终门控，跨Controller不存在原子提交保证。

Seamer业务状态提交保持F03/F07事务边界：所有必需证据、源state revision、definition及execution匹配且无已知暂停门控才提交；不确定提交先查记录。设备成功但业务未提交只允许明确reconcile_commit，已提交未发事件仅重传固定event_id。远端变更尚未传到Seamer的窗口不能被本地事务消除。

## 6. F01—F07 当前状态与冻结余项

| 项 | 本轮完成 | 正式冻结仍缺 |
| --- | --- | --- |
| F01 | 下一版统一Schema、两份自包含OpenAPI、明确引用／错误／安全方案，旧版本隔离 | SDK语言和代码生成器往返测试、解析器数值与格式完整测试、稳定兼容策略及发布提取 |
| F02 | 19类IPC、guard安装及精确屏障、typed候选证据、配对反例 | 两平台真实IPC／监督器／唯一出口、消息丢乱重、真实socket与进程活性验证 |
| F03 | 原T1—T8与恢复R1—R5语义统一，原终态／资源／outbox不混淆 | SQLite引擎／驱动版本、fsync/WAL、锁竞争、磁盘满／损坏、备份恢复及不确定COMMIT实验 |
| F04 | 完整签发域身份、端点安全方案、精确撤销、票据挂接 | 认证／TLS／密码与秘密库、配对／轮换、浏览器及跨服务撤销实测 |
| F05 | 样本／守卫／年龄证明／容量与实际入口绑定 | 真实NTP／认证时钟隔离、精度及跳变、发布容量／保护窗口／留存预算 |
| F06 | 目录代际及typed完成／释放证据进入公共与IPC | OBS实际包与内嵌协议组合、UUID目录变化、错误白名单、Cut及其他profile释放策略、视觉证据 |
| F07 | 权威证明引用、恢复计划／逐目标准备、单次消费及状态提交衔接 | DSL及足迹生成器实现审阅、完整依赖闭包、真实并发CAS／崩溃和外部前提竞争 |

这些余项分两类：**实施前必须冻结**的语言／库、SDK生成策略、目标OBS组合、足迹DSL与发布验证计划；**实现后才能取证**的故障、真实并发、性能和设备验收。本轮不以尚无实现的运行证明阻止整理契约，也不把规范校验当正式发布准入。

## 7. 本轮验证与交付限制

新增人工正反例覆盖旧版本拒绝、身份来源缺失、旧SceneRef、许可缺guard、伪持久化、事件年龄错绑、足迹分歧、proof／plan摘要变更、恢复target串接、unknown清资源但保留暂停、OBS跨时钟域及授权／时间屏障漏项。每个HTTP请求／成功响应模型、每个IPC消息类型都有正例；结构、跨字段、跨消息分别判定。

实际数量及输入摘要见[归并报告](contracts/draft3/validation-report.json)。旧各轮检查单独运行，不被本报告替代。未运行服务、SDK客户端、浏览器、真实IPC、SQLite、NTP、并发压力或OBS；FC／FT／FA／TB／OB／AU运行验收均未执行。离线人工模型不能证明权威数据真实、物理副作用原子或直播零事故。没有修改业务实现、提交、推送或部署。
