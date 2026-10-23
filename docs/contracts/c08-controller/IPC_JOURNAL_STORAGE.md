# 共享IPC日志的SQLite候选布局

状态：设计候选，未经产品冻结；不修改已确认的draft.4／IPC0.3。前置为[共享消息协议](IPC_JOURNAL.md)及[207表释放布局](ENCODING_RELEASE_STORAGE.md)。本轮在完整旧布局上组合十二表，共219表；不创建业务数据库或迁移旧数据。

## 当前交付与适用范围

已交付的SQL事实：握手、普通／取消编码、释放、OPEN_GATE和GATE_FENCE共八类领域记录强制引用同一双向日志。原字段、原业务守卫与最终准入阻断保留。52种消息的方向和响应类型均登记；尚未迁移的领域效果只允许明确拒收记录，不能用一个通用effect_body假冒真实提交。控制／AUTH／TIME／RUN／取消完整屏障及DENY/PreparationClosure的领域写集仍须逐项归并。

上述范围是分轮实施设计的边界，不是最终产品范围缩减。完整收敛以[总清单](../../rebirth-design-closure.md)为准；本候选不可用于直播部署。

## 表与原子写集

| 对象 | 内容与约束 |
| --- | --- |
| ij_type／ij_reply_type | 52类型方向、允许响应类型及保护容量类别；由固定生成器封存，运行时不能修改或补类型 |
| ij_session／ij_exit | Controller/worker启动、IPC会话、单调域、描述摘要与设备出口的精确绑定；一个会话可包含多个设备 |
| ij_frame／ij_commit | 两方向独立连续正U20、同方向唯一message_id、原wire/帧/正文及各摘要；日志与领域seal双向配对 |
| ij_write_attempt／ij_write_result | 入流前持久尝试、完整写入或不确定；先前每个出站序号必须完整写入才可开始下一帧 |
| ij_end | 当前会话永久终止；不能通过恢复数据库或旧ACK删除终止历史 |
| ij_handshake／ij_rejection | 握手协商原件及明确未处理领域的拒收事实；拒收不是领域成功 |
| ij_encoding_frame | 从ep_request拆出的最终编码帧预约，绑定原prepare与授权，不重新消耗活字节预留 |

编码准备登记只保存逻辑候选和稳定message_id，不再保存seq或完整帧。唯一发送器选中候选时，同事务写`ij_frame → ij_encoding_frame → ij_commit`；此后不能退款重用序号。发送前同事务写`ep_send_attempt → ij_write_attempt`，二者的prepare、frame、attempt_id与tick必须相同。真实I/O在提交之后，未开始I/O也不得以“应该没发”重置已记录的尝试。

原编码回复为`ij_frame → ep_reply → ep_receive_commit → ij_commit`；日志disposition必须与领域采用／历史一致。普通和取消编码分别核对四种成功／失败类型。旧ep_reply的rejected不能当作worker发来的编码失败：PREPARE_PACKET_REJECTED是Controller发出的另一类消息，完整迁移时单独建领域映射。

释放请求为`ep_revocation → ij_frame → er_request → er_request_commit → ij_commit`。释放ACK为`ij_frame → er_ack → er_adoption → ep_release → er_ack_commit → ij_commit`；退役后的迟到历史省略新adoption和退款，仍绑定已提交的监督退役退款。日志不能比领域先封存，任一边缺失都拒绝整个事务。

OPEN和GATE_FENCE分别配对原dispatch/request及原evidence/ack；ACK入库与之后ready／scope／换闸采用分开。日志已记录为historical的ACK不能采用。结束在采用之前发生则采用失败；结束在采用之后发生则候选视图立即失效，原控制记录仍作为历史保留。候选视图不是产品当前时间或最终发送许可。

## 连续性、恢复与容量

正常序号以20位补零TEXT存储，外部仍使用规范十进制字符串。两个十位段递增，避免把U20强转成SQLite有符号整数；首序号为1，方向内不跳号、不回绕、不删除历史。会话内所有设备共享方向水位，独立worker会话有独立水位。

同message_id重投必须先查原，校验原wire及原对象完全相同；数据库的唯一键只阻止重复写入，不能代替可信解码器的重复判断。缺号或内容冲突由运行端终止会话，不通过跳号自动修复。已预约帧最终条件失效也终止会话，不能发一个无意义占位帧填号。OPEN／换闸发送前重核原计划及严格截止，编码通过原准备守卫，清理请求通过原退款／退役守卫。

`ij_recovery`只提供恢复分类：拒收只查拒收，入站查原提交；已结束的出站永不重播；完整入流不证明对端处理；尝试过但结果未知只能查原或监督退役。COMMIT响应未知时先确认原事务，禁止重复执行写集。实际进程重启必须在接受新工作前终止所有旧会话；同一条旧进程连接不能被重建的内存对象接续。此启动算法及磁盘故障尚未实现。

部分帧不确定写入须同事务保存ij_end与uncertain结果；前缀未完成，后续普通帧不能开始。数据库不可写时，本布局不要求先写ij_end才紧急关闭；运行时先按volatile_close协议停止正常资格，数据库恢复后补终止历史。SQL实验没有执行紧急流或监督退役。

每会话总帧数和wire总字节有硬限额，普通帧不能占保护预留；保护消息仍受总上限约束。历史不随缓存退款回收。达到限额不能无限扩大，需停止接受正常工作并安全退役/建立新会话。实际磁盘占用、索引及frame/body重复存储开销必须由独立存储预算控制，wire字节计数不冒充磁盘预算。

## 验证与剩余冻结项

复验命令：

```text
python docs/contracts/c08-controller/build_ipc_journal_storage.py --check
python docs/contracts/c08-controller/check_ipc_journal_storage.py --report
python docs/contracts/c08-controller/check_ipc_journal_storage.py --check-report
```

检查运行于完整219表的`:memory:`数据库，开启外键和递归触发器，不停用原守卫。覆盖普通／取消编码、释放、开放和换闸各写集缺写及逐步异常全库回滚、跨领域／跨设备序号冲突、原回复与方向错配、先尝试后接收、半帧阻止后续发送、结束与迟到采用、双边尝试绑定、截止等号、保护容量及全部新增表不可变。精确数量和输入摘要见[报告](ipc-journal-storage-report.json)。

仍需完成：所有其他消息的领域迁移；DENY与完整准备Closure的同库反向配对；关闭/接管各seal完整关系；AdmissionSeal及Guard/预算/时间、RequestKey和SDK统一源；真实编码器、可信身份／时钟／JCS／wire解析器与同字节流唯一写出口。测试中的BODY和摘要是合成前提；SQL验证投影相等，不验证摘要密码学真实性。不得据此宣称IPC、并发、断电恢复、设备效果或直播安全已通过。四个最终准入阻断保持，阶段0仍未关闭。
