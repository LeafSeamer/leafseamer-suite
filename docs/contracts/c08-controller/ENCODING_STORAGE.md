# 编码准备的持久登记与恢复候选

状态：设计候选，未批准部署。[生成器](build_encoding_storage.py)把[194表范围库](controller-scope.sql)与[八表附属约束](encoding-storage.sql)组合为[202表候选](controller-encoding.sql)。旧候选保持原样，四个最终签发阻断保留；本轮不实现业务服务或设备操作。

## 事实与设计分析

已知事实：IPC0.11已将仅编码授权与最终Guard分开。旧ce_packet只绑定attempt、exit、primitive及BODY；取消已有cc_prepare/cc_packet，但没有同版EncodingAuthorization、原响应和缓存容量的强制联接。（来源：[编码授权](ENCODING_AUTHORITY.md)、[原执行表](fence.sql)、[取消准备表](cancel-closure.sql)。）

基于上述事实，本候选增加普通/取消共用的准备登记、编码入流尝试、原响应和独立接收提交。取消cc_prepare与新登记双向延迟外键配对；旧两类packet入口都必须找到同一准备证据，不能跳过仅编码授权直接升级为待发送packet。它仍不等于完整T2/AdmissionSeal；新T2的实际时刻、全部当前授权与资源等约束继续依据上一轮方案核验。

## 字段与写集

| 表 | 字段与约束 |
| --- | --- |
| ep_limit | 当前候选单Controller活缓存预算，固定profile三元Ref、max_live_prepares、max_live_bytes和原profile。此版不提供热换限额，变更流程仍须另行冻结，不能通过再插一条profile获得第二份额度 |
| ep_request | prepare_id、kind、实际command_id、普通proposed_attempt_id或取消cc_prepare、namespace及完整Requester、原请求digest、exit、primitive、authorization_id/digest/BODY、原消息ID/seq/digest/BODY、max_bytes及created/expires。普通不引用未来attempt行，取消取自身RequestKey |
| ep_request_commit | 与request双向配对；可信committed_tick、验证原件、审计及outbox。取消还与原cc_prepare同事务；事务失败全部回滚，不分配ci_issue或设备预算 |
| ep_send_attempt | 每prepare最多一条、固定attempt_id、实际入流前tick及请求摘要。先可靠提交，再交唯一出口；它只表示编码可能发生，不能表示已送达或已完成 |
| ep_reply | 精确prepare、出口、原reply_to、授权id/digest、响应消息ID/seq/digest/BODY、received_tick；prepared才有packet、原字节、Evidence，failed/rejected不带成功字节。每prepare只保留原终结响应 |
| ep_receive_commit | 与reply双向配对；prepared/failed/historical、可信提交tick及验证审计。prepared要求当前未撤回/未退役/未关闭且未过编码截止；迟到原响应可保存historical，不能转为prepared |
| ep_revocation | 原准备的永久撤回、原因审计及保护outbox；不抹旧响应，不自动释放设备hold或缓存预算 |
| ep_release | 引用已撤回prepare；仅允许未创建send_attempt或同一exit的可信监督退役证据。删除或重写历史被禁止；它只释放活缓存逻辑预留，不能声称磁盘物理字节已删除 |

三个常规写集为“request/取消prepare/commit”“入流前attempt”“reply/receive_commit”；取消cc_prepare内原outbox是同一编码请求的投影，不是第二个发送任务，唯一调度入口是ep_request_commit。登记和接收先后采用独立事务，不跨IPC等待持有写事务。所有时间和seq在库中为补零U20，线上格式不变。数据库中的两个方向消息唯一约束只覆盖本子域，**不能替代全部48帧的共享序号分配及入站日志**。

ep_request_source从实际ca_request_key或cv_cancel_key和namespace取完整issuer/epoch/principal，并核command与exit属于同设备。它不以字符串摘要代替授权服务；完整EncodingAuthorization和原帧仍须先按IPC0.11严格解码、JCS、动态参数Schema、来源与当前凭据核验，才允许写入。SQLite的非空BODY检查不证明这些外部事实。

## 故障与恢复

- request事务未提交：无可调度准备；同请求冲突不自动生成新身份。
- request已提交但无attempt：可以证明此日志未调用编码；进程重启仍不自动续投，须按当前身份撤回并显式重建准备。
- attempt已提交但响应未知：只查询原worker缓存；缓存缺失/进程退出走退役。不可重做相同prepare，不能从超时推导未调用。
- 原响应重复：查询原记录并比较完整原件；新message_id、不同正文或不同seq不能覆盖原终结响应，冲突的通道保护及全消息审计仍须统一日志实现。
- 接收commit失败：reply和接收资格均回滚；COMMIT结果未知时查原，不补造成功。这里的主动异常实验不能证明真实掉电行为。
- 截止等号、撤回、取消all关闭、出口退役先到：只能保留历史，不能新增prepared资格。已经prepared的视图没有实时now；最终T2必须另核授权期限，不能直接把视图当发送许可。
- 同exit退役允许活缓存预留释放，但不清命令终态、风险hold或已入流设备副作用；退役后迟到响应只进入historical。

## 容量及剩余接口

请求登记按max_bytes先预留活缓存空间；同事务累计槽数和字节，缺写/失败不耗额度。成功、失败或到期本身都不退款，避免worker仍持有字节或编码任务时反复超额。预算与实际磁盘留存、CPU时间、全消息窗口和设备发送预算分开；本实验不把库中仍存在的原字节当作已回收磁盘。

**正常会话内的精确缓存释放协议仍待补齐**：必须定义请求/ACK，绑定prepare原件和所有正在编码/使用字节的工作，确认不再有消费者后才能退款；丢ACK保持占用，重复只回历史，旧释放不能影响新准备。当前仅实现有证据的未尝试与退役分支，是过渡候选，不能作为要求用户反复重启的最终产品方案。活缓存限额的平滑调整、持久字节归档/删除与GC、完整授权提供者、接管/各类关闭与准备全集联接、共享消息序号，以及最终T2/SDK仍属于原C02/C03/C08剩余事项。

## 验收边界

[检查器](check_encoding_storage.py)在完整202表内存库上执行两种准备的配对缺写/逐步异常回滚、原请求主体、原响应关联、期限等号、撤回与迟到、不可变历史、预算边界及恢复分类；不关闭旧触发器，不绕过外键。合成BODY可通过作为明确的限制反证，JSON验证和SQL写集尚未接成真实writer。

真实HTTP、IPC、授权服务、监督退役、并发、磁盘崩溃和设备均未执行；内存引擎版本只作报告，不批准产品SQLite。复验命令：`python docs/contracts/c08-controller/build_encoding_storage.py --check`，`python docs/contracts/c08-controller/check_encoding_storage.py --report`。`--check-report --staged`仅检查暂存原字节绑定，不重跑验收。
