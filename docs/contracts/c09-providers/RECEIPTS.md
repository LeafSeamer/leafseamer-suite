# 请求回执与无投影结果

[receipt_delivery.py](receipt_delivery.py)补齐当前host.result的无完整投影分支，与 [Delivery](DELIVERY.md)共用通道身份、方向序号、容量、期限、撤权及单次出口。它只读取原请求状态，不包含业务提交、重新消费确认或补发命令入口。approved=false、runtime_ready=false；固定受理／投影分离规范见 [receipt-sources.json](receipt-sources.json)，结构来源仍为同一panel4完整模型。

## 权威读取及身份绑定

可信宿主调用enqueue_status，提供当前完整上下文、原panel.request、当前认证核验得到的完整RequestIdentity、当前会话与账本读取依赖，以及status_reader。后者接收上下文和原请求的副本，在当前读权下返回封闭记录：invocation和observation。它必须从受控账本及权威服务取证，并核验target_handle与原target_ref的映射、资源与策略／能力引用、当前主体、可见性和查询权限，不能直接包装面板提交的JSON或回显调用者自报结果。

适配器实际验证完整Invocation及RequestReceipt模型；原意图身份必须逐字段等于独立提供的RequestIdentity，包含authority_service_id、database_instance_id、issuer_id、issuer_epoch、auth_session_id、panel_session_id、document_generation和request_id。服务／数据库、面板会话／页面代次和请求ID还必须与当前上下文及公共绑定一致。原意图method、normalized_arguments完整TypedValue及activation_ref必须等于原请求；委托和非空目标引用属于同一authority/database。Schema允许的空target_ref保留为null，不伪造目标对象；其他领域条件仍由可信reader核验。

服务回执的identity、method和activation_ref必须精确匹配原意图，intent_digest必须等于完整原意图的JCS／SHA256摘要。重新计算摘要也不能跨认证会话、页面、服务或数据库。accepted_result_ref若存在，必须属于相同authority/database；它和内部identity、意图摘要、委托、策略、能力以及原回执正文都不下发面板。

首次成功入队的状态观察固定该原请求的完整意图摘要，后续查询不能换目标、委托、策略、能力、认证身份或其他原意图字段，即使新回执重新计算了一个合法摘要也拒绝。该登记与已有256个原请求ID限额共同约束；它不代替真实持久账本的原意图不可变规则。

status_reader负责提供有当前读权的事实，不接收通过标志。抛出异常时关闭通道，不自动将异常映射成unknown_outcome或rejected。能否报告有限的unavailable观察必须由可信读取器明确判断；无法核验当前查询权时停止输出，而不是借错误回执泄漏原请求存在性。

## 两种观察与五类状态

| observation | host.result结果 | 语义 |
| --- | --- | --- |
| kind=receipt，原回执accepted／unavailable | accepted、ok、projection_state=unavailable、result=null | 保留已受理事实；当前完整投影不可用 |
| kind=receipt，原回执pending_confirmation | pending_confirmation、needs_host_confirmation、not_applicable、null | 仅原8种确认方法合法，不表示确认已消费 |
| kind=receipt，原回执rejected | rejected、原有限拒绝原因、not_applicable、null | 原请求被权威拒绝，不用传输错误代替此事实 |
| kind=receipt，原回执cancelled | cancelled、user_cancelled、not_applicable、null | 原确认流程已取消，不把已受理命令改为取消 |
| kind=unavailable，可信读取器明确提供有限原因 | unavailable、原原因、not_applicable、null | 当前没有可用受理结果，不证明业务未发生 |

receipt观察严格只有kind和receipt两个字段。accepted回执必须有合法accepted_result_ref；其余服务状态的结果引用和projection均为null。服务回执中的available投影被明确拒绝，必须走完整读集校验和Delivery.enqueue，不能借状态入口透传原始值。

unavailable观察严格只有kind和reason_code，原因限定conflict、not_found_or_invisible、source_unavailable、capacity_exceeded、expired、unknown_outcome、protocol_error。全部状态的14种公开原因有明确分支，不接收上游details、异常文本或任意reason。状态与原因不相容时拒绝；完整输出还须通过当前host.result模型和64KiB帧限额。

## 状态、依赖和截止不可偷换

完整投影入口和回执入口共享本通道已知受理状态。pending_confirmation可在权威新证据下继续待确认或变为accepted、rejected、cancelled；accepted、rejected、cancelled不能回到其他业务状态。拒绝／取消原因稳定；第一次实际读到的accepted_result_ref固定后不能替换。完整投影入口仅建立accepted事实，不凭输出值猜造内部结果引用。

若本通道已经知道accepted，随后模糊unavailable观察不能覆盖它：适配器关闭本通道，保留已交付历史，不发送新的不确定状态。只有独立、当前有读权的accepted/unavailable回执可以明确表达投影暂不可用。这样不会从旧缓存猜测新的权限，也不会把业务已受理改写为未知或未发生。关闭通道后的历史查询遵循宿主现有入口，不能复活旧PublicBinding。

投影来源失效和账本查询权失效是不同依赖。只有投影源失效、当前会话和账本读权仍有效时，可信宿主可以在投影入队前通过新的账本读取返回accepted/unavailable。不得为保留错误通知而省略真正适用的授权或可见性依赖。若已有排队帧、通道构造依赖或会话已被撤销，沿用整个通道关闭规则，不以无投影结果重新开门。

一次状态读取从开始即固定本进程单调期限，实验预算1—2000毫秒。读取期间会话／账本依赖保持登记，慢reader在锁外执行；返回后重核依赖、原请求关联、身份留存、容量和截止，再在协调锁内登记不可变帧。期限不从读取完成时重算，排队和阻塞也不续期。后续显式查询可建立新的当前读取窗口，不能借此续期已经排队的旧结果。

序号、状态登记和排队提交共用同一锁；并发构造不能各自分配同一方向序号。对面板报告accepted不推进领域操作或设备状态。返回值的展示、传输ACK、ProjectionAck及真实持久事务仍属于各自协议，不能从本地帧生成成功推断它们已完成。

## 验证范围

```text
python -B docs/contracts/c09-providers/check_receipts.py --sdk <SDK仓库> --report
```

[receipt-report.json](receipt-report.json)使用固定35方法及完整模型，覆盖5类结果状态、8种确认方法、有限原因、跨身份／意图错绑、无投影受理、投影旁路拒绝、两个入口之间的状态回退拒绝、原截止和实际线程中撤销慢账本读取。完整帧不含内部原件字段；合成账本提供者没有业务提交入口。

本报告实际运行的是模型、字节和进程内协调检查；账本、认证及对象权限来源为显式合成提供者，数据库、网络、浏览器、设备及生产Gate运行计数均为零。另有[账本只读快照](JOURNAL.md)独立运行隔离文件SQLite和一致读取验证，其领域writer及认证仍为合成配置。生产账本接入、真实事件订阅以及其余窗口／端口帧仍待接线，阶段0继续开放。
