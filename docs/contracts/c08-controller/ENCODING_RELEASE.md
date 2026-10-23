# 正常会话内编码缓存释放候选

状态：设计候选，未批准部署。配套[Schema](encoding-release.schema.json)、[完整50帧IPC0.12](encoding-release-ipc.schema.json)及[离线模型](encoding_release_model.py)。本轮不改变[202表布局](controller-encoding.sql)，不解除四个最终签发阻断，不修改业务服务。

## 已知事实与设计分析

已知事实：[编码存储候选](ENCODING_STORAGE.md)仅允许从未尝试或同出口退役后归还活缓存预留；成功、失败、超时都不退款。编码原请求与原响应已不可变，普通与取消共用容量；[编码授权](ENCODING_AUTHORITY.md)明确同packet可被多个独立传输许可使用，已提交设备预算不能自动退款。（来源：上述本仓设计与[encoding-storage.sql](encoding-storage.sql)。）

基于这些事实，本候选补一条不退出worker即可完成的单准备释放链：Controller永久撤回该准备的未来使用→worker在唯一发送出口安装该prepare的拒绝墓碑→等待编码任务和字节消费者退出→删除活字节→回原ACK→Controller同事务保存ACK、采用及预算释放。它不取消已进入传输的设备效果，也不把unknown变成not_sent。已经失效的用户凭据不阻止可信Controller完成这项单调清理，但客户端不能直接调用内部释放IPC。

## 精确对象与IPC

| 对象 | 字段与含义 |
| --- | --- |
| ReleaseRequest | release_id/revision=1、完整Binding、prepare_id、encoding_authorization_ref、encode_message_id、encode_frame_digest、revocation_ref、selected_tick_ns、request_digest。绑定原ENCODE完整帧及授权；不要求已知packet，因此编码响应未知也能清理 |
| ReleaseAck | release_ref、完整Binding、prepare_id、release_message_id、release_frame_digest、disposed_tick_ns，以及固定released、encoder_quiescent=true、consumers_quiescent=true、cache_empty=true。三个事实只由可信worker的真实生命周期证据产生，合法布尔字段不证明它们真实成立 |
| ReleaseAdoption | adoption_id/revision=1、完整Binding、prepare_id、release_ref、ack_message_id/ack_frame_digest、encoding_reservation_ref、reserved_bytes、received_tick_ns/committed_tick_ns、adoption_digest。额度取Controller原预留，不从ACK自报数量取值；每prepare最多一次退款 |

Ref复用id/revision/digest，Binding包含scope、两boot、IPC与设备session、writer_exit及单调时钟域。对象摘要仅排自身顶层digest后JCS，完整帧摘要包含type/message_id/reply_to/seq及body；不混用两个摘要。严格U20沿用编码授权候选，时间要求`selected <= disposed <= received <= committed`；跨域不比较tick。清理没有资格续期或普通发送截止：编码授权到期后仍允许释放，不能把清理TTL当额度回收证明。

新版`ipc/0.12.0-encoding-release-draft.1`保留48帧全部语义，新增`RELEASE_ENCODING`（Controller→worker，reply_to=null）与`RELEASE_ENCODING_ACK`（worker→Controller，精确reply_to）。握手新增必选`encoding_release_after_quiescence`；两新帧的seq为严格正U20，旧帧的历史词法未在本候选顺带改变。旧0.11不降级混投。ReleaseAdoption仅内部持久对象，不导出IPC。

## 唯一出口与消费者边界

1. Controller用同一个writer提交ep_revocation、ReleaseRequest、审计和单一释放outbox，禁止新编码、T2、Guard安装及重传选择该prepare。该事务必须和最终T2共用串行顺序：T2先提交则其历史仍参与完整屏障；释放先提交则T2拒绝。未入流的旧发送计划被淘汰，已入流的传播窗口保留。
2. worker验证当前认证Controller通道及完整原ENCODE关联，在最终设备出口与消费permit的相同串行域安装永久prepare墓碑。新借用和新ENCODE拒绝。已经排队但尚未借用字节的任务不算活消费者，却必须在执行时检查墓碑；不得在队列外偷偷保存裸字节引用。
3. 编码中任务先标为discard-on-completion，等待其实际返回并释放临时字节；不把发出取消信号当退出。所有编码任务和传输/协议重传/库内部buffer引用必须在同一borrow登记簿里持有令牌。原生调用已经进入设备传输时，可以仍为in_flight或unknown；只要它归还本机字节引用，就可结束borrow，但不能由此清除设备风险。
4. 两类活计数均为零后，清空活packet及临时编码字节，固定disposed_tick并保存原ACK，才允许应答。release可以在prepared、failed、rejected、编码结果未知时完成；未知身份或缺失原ENCODE缓存不能伪造成功，须进入会话故障/监督退役分支。不会自动重新编码。
5. 同一释放原帧重投只返回原ACK或继续等待，不重新安装、不改tick。相同release_id或prepare但正文不同是冲突；保护通道并保留预留。正常响应缓存仍按独立消息预算管理，清理路径预留控制消息空间，不能因普通队列满而永远进不了释放。

释放阻止旧packet的后续重传。因此**普通维护清理只能在策略确定不再需要该packet的未来传输时发起**；主动中止/接管可以先永久关闭使用，但设备效果与核对继续按原生命周期走。消费者只在持有令牌期间使用buffer；假如第三方库无法证明已归还全部引用，该适配器不得签发released，转超时告警及监督退役。这个要求不能以“全部动作禁止”替代完整适配。

## 容量与持久映射

活字节及活准备槽归还，与不可变请求/响应/ACK墓碑及审计留存分开计量。每个ENCODE在开始前已为去重/释放元数据和控制应答预留独立预算；释放不再临时申请普通任务槽。该元数据预算不因退款清零，同prepare在当前会话中永不重用。元数据满时停止新增准备，待完整关闭/退役后轮换会话；它不是每次成功编码都必须重启的缓存策略。持久磁盘归档/GC与完整共享消息账本继续按原C08/C12门槛归并，不能把本模型的有限字典当无限容量实现。

在202表的下一版统一布局中应增加release_request/原ack/adoption配对关系，并扩展ep_release的basis为精确`worker_released`：

- 请求与ep_revocation、原ep_request_commit、原授权及encoding_reservation配对；选定后不可重标或复活，原outbox只发该原帧。
- ACK持久记录与adoption、ep_release、审计同事务提交，反向延迟FK防半边退款；完整帧及JCS须可信提供者先验证，SQL只约束投影。
- ep_release唯一prepare约束使worker ACK与监督退役退款互斥。收到旧ACK仍可存历史，不能退款新prepare或新会话额度。释放数量取原max_bytes；新准备使用新身份。
- COMMIT结果未知仅查原，不重复加余额；额度由未释放预留集合派生，不维护可被重复加回的独立余额。旧packet映射必须同时检查未撤回；最终T2/Guard/唯一出口都使用同一prepare拒绝事实。

本轮将请求、ACK、采用及有限消费者模型落实为机器资料；上述SQL联接**尚未实施**，202表旧ep_release仍不接受worker_released。下一轮把这些关系和失败写集落实到同库候选，不能用仅ACK结构正确代替退款事务。

## 故障及验收

| 切点或反例 | 必需结果 |
| --- | --- |
| 请求事务回滚/提交未知 | 回滚无释放outbox；未知只查原，不发新清理或重复退款 |
| 最终发送先于墓碑 | 已消费传输保留历史，等待其本机borrow归还；不追溯声称未发 |
| 墓碑先于编码/Guard/发送/重传借用 | 拒绝新借用，不生成新设备调用；旧GuardACK不能复活 |
| 编码未结束或任一借用者仍存活 | 不发ACK、不退款；单纯超时不能把计数置零 |
| 编码完成与释放交错 | 丢弃结果字节并归还编码令牌，确认零消费者后才能ACK |
| 原ACK丢失、原请求重复 | 返回完全相同原ACK，disposed_tick不前移；Controller只采用一次 |
| 重算摘要但换prepare/授权/原ENCODE/域/预留 | 拒绝，摘要完整不能代替来源与归属 |
| ACK保存或adoption提交失败 | 不退款；原ACK仍可查询，不重做设备动作 |
| worker进程退出或缓存丢失 | 原会话不可继续证明；监督退役另核，重启不恢复旧prepare |
| 退役退款后迟到ACK、或ACK退款后退役 | 保留历史且额度不二次增加；命令终态/风险hold不改变 |

[检查器](check_encoding_release.py)使用人工预期验证结构、原件关联、双消费者交错、重复清理、故障和容量复用；完整旧48帧通过仅表明结构继续可表示，不证明旧全部业务语义或新IPC已运行。模型假定可信原件与串行原子步，没有实现完整共享序号日志、线程、真实第三方buffer、SQLite事务或监督退役。真实运行、并发、磁盘、设备验收均未执行，阶段0未关闭。

复验：`python docs/contracts/c08-controller/build_encoding_release.py --check`；`python docs/contracts/c08-controller/check_encoding_release.py --report`。报告字节绑定核对不重跑验收。
