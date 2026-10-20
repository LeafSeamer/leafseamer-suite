# 面板订阅 HTTP 与消费映射候选

版本 `panel-subscriptions/0.1.0-draft.1`，待审阅，不切换公共 SDK 权威。本稿衔接[channel0.2](../c09-panel/CHANNEL_V02.md)、[面板HTTP](../c09-panel-service/HTTP_STORAGE.md)及[出口持久化](../c09-panel-storage/README.md)，只新增设计资料和离线验证。

## 1. 已知事实与推荐方案

既有通道定义19个可订阅读取方法：17种完整投影、2种失效通知；写、确认、preflightRun和previewRecovery不可订阅。ProjectionAck摘要覆盖完整host.projection，含GUI分配的channel_sequence；服务端投影本身不足以重算该摘要。既有订阅关闭不推进acked、不取消命令。这些均来自上述已保存契约，本稿不把候选通过当作产品批准。

推荐分离服务端不可变投影包与宿主完整帧。服务端给投影包编号及摘要；GUI保持原完整帧，转交面板ACK时附上该帧及投影包摘要。服务端核对原包、绑定和摘要后提交消费。此证据仍依赖已认证可信宿主，不能独立证明物理浏览器收到、渲染或用户看到，也不替代设备完成或C05持久摄取。

首期通过有界HTTP读取已发布投影包，最多每批8项；不新增任意WS代理或由面板直连服务。已有C05来源流用于填充权威投影，不能把GUI轮询作为新的设备采样／自动化trigger。投影频率与窗口沿channel候选，实际吞吐和性能仍需C12验证；后续推送传输须保留同样身份、窗口与撤销边界。

## 2. 五个接口及身份

所有路径以`/api/v1/panel-sessions/{session_id}/subscriptions`为前缀，两authority各自提供，不能跨服务代理。GET要求当前目标human bearer、精确Origin及已登记gui_instance_id；POST同时要求绑定auth_session的CSRF。面板iframe不能取得凭据，HTTP头不下发面板。错误及成功均no-store，错误不透传上游文本。

| 方法与后缀 | 输入与返回 | 语义 |
| --- | --- | --- |
| POST 空后缀 | CreateSubscription → 201／重复200 SubscriptionRecord | 创建唯一订阅；登记出口关联、内容摘要、预算与初始pending；不得调用业务方法或生成展示句柄 |
| GET `/{subscription_id}` | 无body → 200 SubscriptionRecord | 只读状态及消费／关闭引用；响应丢失后查原身份，不创建新订阅 |
| GET `/{subscription_id}/frames` | after_sequence、limit → 200 ProjectionBatch | 只读已经持久发布的完整包；不分配序号、不创建baseline、不推进ACK。GET不能用来续租 |
| POST `/{subscription_id}/ack` | AcknowledgeProjection → 200 SubscriptionRecord | 核对原包与完整宿主帧／面板ACK，累计消费；重复不增加窗口额度 |
| POST `/{subscription_id}/close` | CloseSubscription → 202／重复200 SubscriptionRecord | 只关闭此订阅，返回唯一close_operation_ref；停止发布、排空未释放队列、形成保护通知后closed，不等待页面ACK |

GET query 的gui_instance_id只是关联值，不是认证。frames额外要求after_sequence（规范非负十进制字符串）和limit（1—8）。当前after必须等服务器acknowledged_sequence；过期或超前返回409，客户端查原record，不把409当失步已恢复。空数组只表示当前无新持久投影，不证明设备状态正常。

SubscriptionIdentity使用authority_service_id、database_instance_id、issuer_id、issuer_epoch、auth_session_id、panel_session_id、document_generation、subscription_id八元。服务端从认证与Session推导前七元，核对body/path；不能只用subscription_id或把activation加入唯一键。完整SubscriptionIntent包含identity、activation_ref、method、target_handle、resource_ref和规范typed arguments，摘要为完整Intent的JCS SHA256裸64hex。gui_instance_id、delegation_ref和HTTP请求关联信息不进内容摘要，但每次请求必须验证当前资格；续租／新委托不改变原意图。

同身份不同内容409；同内容仅返回原状态，gap/closed不复活，不重置序号或预算。订阅与原面板委托同寿命，scope／Registry／Bundle变化关闭挂载后重建，不能原地替换参数。19个方法前缀须匹配authority角色；target_handle和resource_ref须与登记目标一致，不能以GET路径绕对象权。

历史SubscriptionRecord可由有当前对象读权的可信宿主读取，字段按当前权限过滤且无投影值。frames与ACK仅原active挂载、原auth_session及当前委托可用；新登录会话能看历史不等于接续旧投影。失去权限或挂载关闭后，frames拒绝并不返回旧内容。GET404或POST503不证明未发生，创建／关闭／ACK响应未知时查原record，不自动换ID重做。

## 3. 投影发布、摘要与宿主映射

ProjectionEnvelope字段：protocol_version、identity、activation_ref、projection_exit_ref、source_projection_ref、projection_sequence、method、kind、reason_code、value。两ref分别指已登记local_projection出口和经过当前字段过滤的权威快照记录；不能直接暴露原设备协议、秘密或原始C05消息。EnvelopeRecord包含完整envelope及其JCS SHA256裸hex envelope_digest，摘要不递归删除任何字段。

包从已有权威快照构建，在同writer复核授权、安装／挂载、激活、来源版本与预算后一次提交。同一订阅sequence从1连续增长；projection模式首包baseline，后续update；invalidation模式仅invalidated且value=null。本接口只交付这三种数据通知；gap/closed由状态与保护通知处理，不伪造空baseline。未发布的快照可合并，已发布包永不改写。来源没有可用证据时保持pending或进入gap，不能凭缓存补出“新鲜”数据。

SubscriptionRecord区分published_sequence与acknowledged_sequence。published是服务持久编号，不声称GUI已发送；GUI沿channel保留自己的sent/acked。服务容量计入全部已发布未消费包，包括尚未通过HTTP交付的包，避免HTTP响应丢失绕32窗口。订阅退役可释放窗口，但不推进acknowledged_sequence。各服务字段仍用十进制字符串，比较不得转浮点。

ProjectionBatch字段identity、activation_ref、after_sequence、published_sequence、has_more、frames。一次数据库快照内返回从after+1起连续的最早未消费前缀，数量≤limit≤8；has_more按该快照高水位判定。GET期间不可将不同snapshot的计数和内容拼接。响应释放前再次核对拒绝状态；已进入HTTP/代理传输的数据无法撤回，可信GUI收到后仍核对当前挂载再转交面板。

宿主将envelope的activation_ref、subscription_id、method、projection_sequence、kind、reason_code和value原样映射到host.projection，再填当前PublicBinding及全通道输出channel_sequence。不得用source_projection_ref替代value，也不向面板暴露HTTP内部identity、出口或来源引用。包重复到达时复用已保存的原帧映射，不分配第二个channel_sequence重新发送；本地保留信息丢失或导航后关闭旧通道，不能重新包装旧包继续。

本HTTP接入的宿主须对每个挂载串行处理出站帧和入站ACK。映射按(subscription identity,projection_sequence)唯一，保存envelope_digest、完整帧、frame_digest及GUI实际发送状态；只有已发送帧的原面板ACK才能向服务报告。channel序号属于全通道，不能仅由单个订阅检查其全局连续性。服务核对宿主提交的完整帧及原包；全通道source/port／方向序号验证仍由可信宿主承担。

## 4. ACK与关闭事务

AcknowledgeProjection包含gui_instance_id、delegation_ref、identity、envelope_digest、frame及panel_ack。frame必须通过现有Projection Schema，panel_ack必须是ProjectionAck而非普通panel.ack。服务核对：原包identity与activation、完整PublicBinding、订阅和method、序号与kind/value/reason_code、完整帧JCS摘要等于panel_ack.projection_digest，以及包摘要等于原权威记录；重算被篡改内容的摘要也不能通过原记录比对。

累计ACK目标必须仍在保留窗口，`acked < target <= published`，且从acked+1到target的发布记录完整。该范围只证明服务记录连续；实际宿主按channel只在连续接收/投递/消费后提交，不能把服务记录存在当面板消费事实。提交一次推进acknowledged_sequence、退役相应窗口、保存last_ack及audit。last_ack含sequence、envelope_digest、frame_digest和固定ack_ref；与原记录相同的最新ACK重复只返回原消费事实，不延租或再次释放槽。

低于已确认高水位的ACK返回409 stale，不再读取已回收内容来猜其正确性；等于高水位但摘要不同也409。gap/closing/closed期间新ACK拒绝，不恢复资格或改变acked；关闭前已经提交的last_ack历史仍可查询。last_ack只保留当前确认点，旧内容保留策略沿DF04，不因需要幂等永久积累所有大帧。

关闭先在GUI停止转交该subscription，再由服务同writer置closing、固定close_operation_ref、撤销未释放包及保护通知，最终closed。只关闭一个订阅不能关闭同owner的其他订阅或整个local_projection出口；安装／挂载撤销仍按上一轮完整目标集处理。通知丢失也保持关闭，不能等待面板ACK才释放保护资源。已受理命令、控制holder和组织run不受单订阅close影响。

close仍要求当前有效的宿主认证、原owner身份及关闭权限，但不要求投影租约、安装批准或挂载仍active；过期不应阻止收拢资源。human凭据本身无效时由内部过期／撤权保护路径关闭，不能为此绕认证。重复close返回已固定的原操作和原因，不覆盖首个原因或生成新操作；它与同ID改订阅内容的conflict规则分开。

提交结果未知只查询原记录；COMMIT前回滚和COMMIT后丢响应分别保留原语义。服务重启不恢复旧active通道或重播旧包，按照挂载运行域变更关闭旧订阅；旧数据仅供当前授权的历史查询。跨authority各有独立会话及订阅，没有跨库原子ACK。生产表需增加envelope、宿主映射与last_ack关联，尚未把上轮局部SQL冒充完整迁移。

## 5. 验收与未完成项

| 编号 | 故障或边界 | 断言 |
| --- | --- | --- |
| PSH01 | 19种合法读取与16种不可订阅方法 | 类型及模式精确；预检、恢复预览不能借订阅重复调用 |
| PSH02 | 同ID改参数／激活或closed后重建 | conflict或原终态，不重置计数 |
| PSH03 | HTTP响应丢失／重复页／after超前 | 只读原前缀，映射不重发，不分配新序号 |
| PSH04 | 换页面、authority、出口或value后重算摘要 | 与权威快照关联失败，不能靠摘要自洽放行 |
| PSH05 | panel.ack、错误完整帧digest、跳过缺失发布记录 | 拒绝消费，不释放窗口 |
| PSH06 | 最新相同ACK重复、旧ACK、错内容同序号 | 幂等原结果或409，不产生额外额度 |
| PSH07 | 撤权／关闭与响应释放、ACK提交竞争 | writer排序；关闭后无新合法转交，传播窗口内已发字节不承诺撤回 |
| PSH08 | 一页两订阅关闭其一、服务／GUI重启 | 另一订阅独立；旧映射不恢复，设备命令不取消 |
| PSH09 | 32窗口／256ID／8活跃／64KiB／保护槽耗尽 | gap或关闭且保留未消费高水位，不丢包后伪称连续 |
| PSH10 | 真实Origin/CSRF、宿主port验证与字段提供者 | 真实服务、浏览器和负载取证，不能由合成标志代替 |

本轮[Schema](subscriptions.schema.json)／[OpenAPI](subscriptions.openapi.json)由[唯一生成源](build_contracts.py)生成，[检查器](check_contracts.py)和[参考报告](reference-report.json)记录213项检查；每个结构用例同时对照独立Schema与OpenAPI内联模型的接受结果。格式采用[OpenAPI3.1.1官方规范](https://spec.openapis.org/oas/v3.1.1.html)，内联只支持本批固定本地资源闭包，不是通用Schema转换器。

本轮人工正反例只验证结构、固定本地引用闭包、合成上下文关联、分页及有限消费状态。无真实鉴权、投影来源、宿主发送、SQLite并发、网络或设备运行。动态value仍需批准Bundle二次校验，静态Schema不证明脱敏；本批不重复实现前轮Bundle验证器。报告绑定15份输入原字节，修改说明文稿也需要重新生成。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-subscriptions/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-subscriptions/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-subscriptions/check_contracts.py --check-report --staged
```

当前候选只有五个新增接口，未并入旧14接口或SDK操作矩阵；安装生命周期接口、全部字段提供者、订阅生产DDL、公共版本归并及PSH01—PSH10真实运行仍待完成。独立报告不在顶层旧十份报告清单内，字节检查不重跑用例，也不批准方案或关闭阶段0。
