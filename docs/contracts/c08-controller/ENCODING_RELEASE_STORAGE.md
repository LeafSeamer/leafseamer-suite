# 编码释放的同库写集候选

状态：设计候选，未批准部署。[生成器](build_encoding_release_storage.py)将[202表编码库](controller-encoding.sql)与[释放约束](encoding-release-storage.sql)合为[207表候选](controller-encoding-release.sql)。只修改设计资料及离线验证，不实现业务服务，不解除四个最终准入阻断。

## 事实与设计分析

已知事实：[释放契约](ENCODING_RELEASE.md)要求永久撤回准备、唯一设备出口安装墓碑、等待编码和全部消费者退出，再以精确原ACK归还活缓存预留；上一版SQL仅支持从未尝试及监督退役两条释放路径。（来源：[编码存储](ENCODING_STORAGE.md)与[旧SQL](encoding-storage.sql)。）

本候选把正常释放接入原ep_release唯一prepare账本。退款始终由未释放预留集合派生，不另维护可重复增加的余额。ACK确认的是本机编码缓存清空，不确认设备未执行；命令终态、资源hold、设备发送预算和不可变字节历史均不由这条写集删除或改写。

## 字段和强制关联

| 对象 | 新增或关联字段 |
| --- | --- |
| ep_limit | max_metadata_prepares：每个精确exit的终身准备元数据槽数，含已释放准备；与全Controller活槽/活字节额度分开。当前为固定profile，不提供热改限额 |
| ep_request | reservation_id/revision/digest：与EncodingAuthorization和ReleaseAdoption的编码预留Ref对应，ID唯一、修订固定1；完整正文与投影相等由可信写入提供者验证 |
| ep_revocation | revocation_id/revision/digest与revoked_tick，修订固定1；撤回时间不得早于原准备提交。保留原单调deny通知，不把通知当作设备副作用已结束 |
| er_request | 唯一release_id及revision/digest，唯一prepare、精确exit、原授权/原ENCODE身份与摘要、撤回Ref、selected_tick及完整请求消息ID/seq/digest/BODY。必须存在原编码send_attempt；未尝试直接沿用本机never_attempted退款，不向不知原请求的worker索取成功ACK |
| er_request_commit | 与request双向配对；committed_tick、验证审计和单一释放outbox，outbox_body必须等于原完整帧。不得以另外一个帧替换已选原件 |
| er_ack | 唯一ACK身份与原release/prepare/exit、原请求Ref/reply_to/frame_digest、disposed/received时刻、三项清空事实、原响应消息ID/seq/digest/BODY及可信验证记录；与ack_commit双向配对 |
| er_adoption | 唯一adoption及prepare、精确ACK/release、原预留三元Ref和原max_bytes、接收/提交时刻及BODY审计；与ep_release双向配对 |
| er_ack_commit | released或historical；released必须精确引用同一adoption且与其提交时刻一致；historical必须已经按同exit监督退役完成退款，没有新adoption |
| ep_release | 新basis=worker_released及worker_adoption_id；与从未尝试/监督退役互斥，prepare仍唯一。反向延迟外键不允许仅写ACK、仅写adoption或仅退款就COMMIT |

库内tick与seq用补零U20，线上不改格式。原请求绑定的exit行固定完整两boot、IPC/device session和时钟域，scope沿原prepare的Controller数据库身份；SQL不从BODY重新解析这些字段。此处增加`selected <= request_committed <= disposed <= received <= adoption_committed`的持久顺序约束，清理不受旧编码expires_tick限制，也不产生新的发送授权。

## 原子写集与恢复

1. **永久撤回与请求封存**：若准备尚未撤回，同事务写ep_revocation、er_request、er_request_commit及其审计/outbox。已经有精确撤回事实时复用它，不另建第二份撤回。原deny通知与释放请求用途不同，前者保护未来使用、后者等待全部字节消费者归还，不能将两个outbox调度成两次编码。请求封存前若退役或已有退款，则整个请求写集拒绝，改查原退款事实。
2. **正常ACK采用**：可信入站先校验IPC0.12及JCS、原Binding/帧关联、消费者证据和时间，再在同一writer事务写er_ack、er_adoption、ep_release和er_ack_commit。每个外键配对及最终seal均通过才提交；缺失审计原件同样失败。COMMIT结果未知只查同一release/ACK/adoption，不重建ID或重复记账。
3. **退役先退款、ACK迟到**：先用同exit监督证明写原ep_release；之后只写er_ack与historical ack_commit。原ACK仍留证据，但不创建第二次退款。ACK先退款时退役证据可另存历史，退款分支必须查原并保持既有记录。

er_recovery区分“已有ACK”“已有退款”“退役但退款事务尚未完成”“同会话查询或重投原释放帧”。最后一项只适用于可信提供者确认原Controller/worker/session仍存活且绑定一致的会话内恢复；该字符串本身不是进程重启后的重放权限。换boot、缓存丢失或通道冲突必须走监督退役，不构造新成功ACK。请求重投仅使用原完整帧，仍不重做设备动作。

保存原ACK但未提交采用的半状态不对外发布。响应丢失后查原返回同一记录，不推进时刻；无记录仍属未知，不能据此释放额度。内存实验仅覆盖主动回滚和“成功COMMIT后丢响应再查询”，没有模拟真实SQLite COMMIT的I/O未知或掉电。

## 准备使用方及容量

原ep_open_request/ep_prepared_candidate永久排除ep_revocation，因此新编码、响应采用及两类packet注册均拒绝旧准备。已登记packet保留为历史；新增er_packet_revoked映射和四个守卫分别保护普通/取消许可插入与最后提交，包括协议重传。最终业务T2仍需完整AdmissionSeal、Guard、时间和预算，旧四阻断一直保留。worker的Guard安装、排队任务和真实buffer借用属于IPC0.12执行要求，本SQL不能代替这些运行侧检查。

元数据槽在每次ep_request创建时计费，释放活缓存不归还；首次编码已为释放元数据预留位置，正常清理不再申请普通槽。计数按精确exit，只有完整关闭与退役并创建新session后才能取得新的会话预算。老会话历史仍在磁盘，不能把按会话重置当作全局持久字节GC；跨会话持久容量、控制通道窗口及实际allocator预算仍须在统一消息/存储层落实。本候选数量上限仅结构边界，不是生产profile批准。

编码与释放两子域的出站消息ID/seq及入站消息ID/seq均双向检查冲突；两个方向独立。完整50帧的序号单调分配、去重、消息审计与原件冲突处理仍须统一日志，不能仅凭局部唯一键声称已完成。

## 故障验收及限制

[检查器](check_encoding_release_storage.py)从完整207表建立普通和取消夹具，不停用外键或旧守卫；覆盖三写集逐项缺写及逐步主动异常、原件与额度错配、期限外清理、未知编码结果、迟到响应、双方向序号冲突、退款两种顺序、活额度复用、元数据限额和不可变历史。全库快照用于证明失败无半边写入，命令/资源及设备预算表另比对保证正常退款不改它们。

真实原件、授权、时间和退役均使用合成前提；非空BODY与清空布尔字段即使通过SQL也不能证明其真实成立。完整准入及所有屏障准备全集、共享消息日志、SDK归并和真实提供者尚未完成，阶段0未关闭。真实服务、IPC、并发、磁盘故障及设备验收均未运行；内存SQLite版本仅报告，不批准产品制品。

复验：`python docs/contracts/c08-controller/build_encoding_release_storage.py --check`；`python docs/contracts/c08-controller/check_encoding_release_storage.py --report`。`--check-report --staged`只核对声明输入与暂存字节，不重跑检查。
