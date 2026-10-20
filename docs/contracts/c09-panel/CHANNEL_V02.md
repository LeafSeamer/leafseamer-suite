# 面板 channel 0.2 归并候选

本稿归并窗口握手、单次调用、SchemaBundle和只读投影；仍未批准，不改变公共draft.4／IPC0.3或旧channel0.1。生成源为[build_channel_v02.py](build_channel_v02.py)，输入沿用既有channel／Bundle／方法／结果资料；生成[channel-v02.schema.json](channel-v02.schema.json)和[method-registry-v02.json](method-registry-v02.json)。方法与结果不复制模型，使用固定本地注册资源引用；生产SDK权威仍未切换。

## 1. 本轮解决的衔接

- 新通道Id统一允许点号，与方法和结果的device.1等身份一致，旧0.1不改接受集；所有窗口和端口帧以及PublicBinding必须同为0.2，旧协议拒绝，不降级重试写。
- Registry逐一绑定35方法的输入和结果完整文档JCS摘要及根$defs入口、用途和subscription_mode；Registry摘要是整个registry对象的JCS，含revision和按method排序的完整列表。port只公布当前authority／scope允许的子集，不能把子集重新摘要冒充完整Registry。
- 新Active／Request／Query／Result／Intent／Guard均绑定ActivationRef。Bundle不再塞入旧Active附件；四种Bundle帧继续引用上一批唯一源。
- accepted结果必须有按该方法验证的TypedValue；其他结果必须null。结果增加method，必须关联宿主记录的原request_id和激活身份，不能仅凭返回方法名选Schema。accepted仅为方法受理／读取结果，不改变Command的完成语义。
- 动态SchemaRef的definition精确选择Bundle文档根$defs入口，联合参考例不再以旧根Schema映射替代。方法静态模型、动态批准入口及实际值三层校验；未授权字段不能因为顶层参数容器开放而通过。

## 2. 激活、身份与查询

ActivationRef完整字段为`activation_id,registry_ref,scope_revision,bundle_ref`，bundle_ref为`{bundle_id,manifest_digest}`或null。静态方法上下文可无Bundle，不能制造无关空Schema凑数；任何需要动态能力／定义的输入或结果必须有当前完整批准Bundle。一个PanelSession只激活一次；scope／Registry／Bundle改变或原激活失效时关闭旧会话，创建新PanelSession与文档代，不在原激活上升级权限。续租不改变ActivationRef。

窗口ready→challenge→reply→port仍遵循原来源窗口、精确origin、随机nonce及单次端口转交约束；port不代表active。有Bundle时：宿主校验批准产物→offer／chunk→面板校验→bundle_ready→宿主复核批准→active。无Bundle时宿主只可激活静态上下文。Session增加schema_loading及nullable activation_ref；权威状态转移和ActivationRef须落同一会话记录，不能用面板自报ready生成批准。

宿主在记录Request前核对端口、PublicBinding、方向序号、ActivationRef、target_handle、方法允许子集、精确TypedValue引用、方法输入与动态Schema，以及当前身份／对象权／租约。人工确认仍由Intent／Preview的原流程消费；Intent新增ActivationRef进入原intent_digest，因此旧预览不能在新激活下使用。Guard固定相同引用；完整ExecutionGuard／IPC selector及DDL仍待跨服务归并。

请求唯一身份仍为原RequestIdentity，不把activation_id加进幂等主键来允许同request_id重新执行。原身份、不同方法／参数／激活内容返回conflict；同内容只查询原记录。旧激活／新页面查询不得把旧写入重新投递。端口Query仅查询本激活记录；激活失效后在可信宿主历史入口按当前读权查看，不将旧完整结果推给新权限视图。未找到或不可见并不证明未受理，未知仍保留核对状态。

Result的reason_code使用有限词表：ok、needs_host_confirmation、user_cancelled、authority_denied、activation_stale、schema_invalid、target_changed、conflict、not_found_or_invisible、source_unavailable、capacity_exceeded、expired、unknown_outcome、protocol_error。accepted只配ok，pending_confirmation只配needs_host_confirmation，cancelled只配user_cancelled；unknown_outcome只配unavailable。rejected不能伪称已取消已受理业务；其余失败码与HTTP逐操作映射仍须归并，不能搬运上游ERROR.details。

## 3. 只读投影订阅

新增panel.subscribe／panel.unsubscribe／panel.projection_ack及host.projection。Subscribe复用相同方法输入与target_handle/resource_ref/activation_ref，以subscription_id替代request_id；方法必须在已批准Registry且subscription_mode不为none。订阅建立不执行新的业务操作，也不重复生成预览或展示句柄。

| 范围 | subscription_mode | 行为 |
| --- | --- | --- |
| 写及host_confirm，seamer.preflightRun、seamer.previewRecovery | none | 不可订阅；后两者虽为panel_read，仍会生成预检／恢复展示绑定，禁止循环生成 |
| controller.listDevices、controller.getCommandEvidence | invalidation | 仅发invalidated，无页面内容／上游cursor；GUI按原分页入口重新读取，不拼接不同目录版本 |
| 其余17个panel_read | projection | 首帧baseline，后续update为完整具名View；不是差分patch，不直接转发C05或设备原始帧 |

Projection字段：`public_binding,channel_sequence,activation_ref,subscription_id,method,projection_sequence,kind,reason_code,value`及protocol_version/type。projection_sequence自1严格连续，按订阅独立；baseline/update携带Registry绑定的TypedValue，其余invalidated/gap/closed只能null。method及activation须等原订阅，所有输出在取值／释放前重新检查当前读权和字段投影。失去Schema闭包或权限不得继续释放旧缓存数据；Capability Schema变化导致激活关闭并重建。

这是一条GUI当前状态投影流，不承诺捕捉每次设备事件，不作为自动化trigger或完整审计。合并中间观察只能在未发送前进行；发送后序号不可改写。来源gap／unavailable必须保留原View状态，不能将“面板收到一帧”解释为来源已恢复。各View的来源年龄／证据约束仍由对应权威提供者落实。

ProjectionAck绑定subscription_id／activation_ref／已发送projection_sequence和该**完整Projection帧**JCS摘要，累计确认不超过已发送高水位；只能命中仍保留且摘要一致的帧。旧确认不得推进高水位，重复确认不提供新窗口额度。它只表示面板消费展示，不是durable_ingest、设备完成或业务状态提交。普通panel.ack只管传输，不能释放投影消费窗口。

订阅状态为pending→live／invalidated→gap／closing／closed；baseline只能首次序号1，update不能先于baseline。gap、closed不复活，同ID重订不能清空高水位；重建用新ID和新baseline。退役为gap／closed时释放该订阅的流控槽，但不推进acked；墓碑保留已发送与已消费高水位，不能解释为遗失内容已被消费。这样旧失步订阅不会永久占满新baseline的窗口。Unsubscribe先到closing，关闭通知形成后到closed；只停止投影，不取消命令或释放控制权。宿主会话关闭／撤权立即停止新释放，不能等面板ACK；已受理请求和在途设备操作保持原记录。

## 4. 容量和失效时序

候选上限：每面板8个活动订阅、全部订阅合计32个未消费投影、256个已使用订阅ID；64 KiB完整帧（解析前线字节和规范化字节均有限），每会话每秒20个普通投影，关键关闭／gap沿既有保护队列。额满不丢旧帧后继续声称连续：标gap、停止该订阅新数据并保留有限核对信息；没有保护槽时关闭该通道。ID留存额满则关闭会话，不清理墓碑来复用身份。生产测量、时限和全宿主限额仍需C12联合profile，不宣称这些候选是性能保证。

故障验收：①bundle_ready早到／错摘要不得active；②active后撤权，再到达请求拒绝且已受理命令不改写；③旧Active或旧Result晚到丢弃，保留原身份查询；④结果返回其他方法或Schema引用拒绝，不回退原响应；⑤订阅重放、序号跳跃、错ACK摘要／代次、满窗口均不能恢复连续资格；⑥预检／恢复预览及任意写方法不能借订阅重复执行；⑦分页invalidated只触发重新读取，无自动写；⑧实际浏览器转交端口数量、origin/source、导航与worker安全另做运行验收。

## 5. 参考验证和剩余工作

`build_channel_v02.py --check`核对生成字节；`check_channel_v02.py --report`运行35方法的真实候选输入和结果联接、动态Bundle入口、帧结构及有限激活／订阅轨迹，并写[channel-v02-report.json](channel-v02-report.json)。本批168项包括145个帧／上下文例（其中70个为35方法的输入与结果正例）及23条订阅轨迹。`--check-report`及`--check-report --staged`只核对15份声明输入原字节，不重跑。检查器本地注册资源，无网络retriever；所有权限、目标目录、批准和原子执行仍是人工前提。

本批不自动迁移旧98例、117例的可信上下文，也不声称完整语义运行。合成Definition只批准一条固定规则，真实完整DSL投影、全部动态能力Schema及字段提供者尚未完成。完整PanelSession／Delegation／Activation／Request／Preview／Subscription的HTTP、撤销IPC与DDL、所有视图的受控词表和来源取证、GUI加载／渲染及真实时序仍需后续归并。完整通道格式已给出，不等于C09、全系统设计或产品实现已完成。
