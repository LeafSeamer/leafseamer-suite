# 编码授权与最终签发的无环顺序候选

状态：设计修订候选，未批准部署，业务代码未修改。本文件补齐[最终准入](FINAL_ADMISSION.md)与[逐传输编码](BARRIER_ATTEMPTS.md)之间的顺序，不取代完整AdmissionSeal。配套[局部Schema](encoding-authority.schema.json)和[完整48帧IPC0.11](encoding-authority-ipc.schema.json)；旧IPC0.10及194表原样保留，四个最终签发阻断不解除。

## 已知事实与分析

已知事实：旧ENCODE_PACKET要求guard_id/guard_digest，ENCODE_CANCEL_PACKET要求guard_ref；最终PermitAuthority又引用packet_ref和Ownership。普通cr_hold_commit要求存在同attempt的传输提交，Ownership与hold配对；最终准入稿要求同一T2事务创建首次普通hold。F04要求先持久intent、再安装Guard，ACK后才DISPATCH。（来源：[IPC0.10](gate-renewal-ipc.schema.json)、[归属Schema](hold-ownership.schema.json)、[资源SQL](resource.sql)、[F04第3节](../../rebirth-f04-f05-design.md)。）

基于这些事实的分析：如果把旧编码请求的guard引用解释为同次最终Guard，就形成“先有packet才能封存最终Guard/Ownership，先有最终Guard才能编码packet”的环。把未提交的hold伪称已封存、提前签发占位permit，或跨worker等待时持有写事务，都不能解决契约矛盾。本轮显式拆分仅编码授权，并保留F04的持久化→安装Guard→ACK→发送顺序。此修订不自动获得用户对新机器基线的批准。

## 原件及字段

| 对象 | 内容和权威边界 |
| --- | --- |
| EncodingAuthorization | authorization_id/revision=1、完整Binding、Target、Requester、admission_source_ref、authorization_snapshot_ref、capability_ref、primitive_id、primitive_plan_ref、transport_profile_ref、content_digest、encoding_reservation_ref、max_bytes、created_tick_ns、expires_tick_ns、authorization_digest |
| Target | ordinary：command_ref和proposed_attempt_id，cancel相关Ref必须null；cancel：command_ref/cancellation_ref/execution_ref，proposed_attempt_id必须null。普通attempt ID只是不可复用的准备标识，尚不代表已派发attempt或hold；父命令终态不代替取消RequestKey |
| EncodingEvidence | 不可变三元Ref；精确授权Ref、Binding、prepare_id、request/response消息ID与各自完整JCS摘要、packet_id/packet_digest、原字节SHA-256与长度、可信接收tick。单向引用，不反向包含未来permit、Guard或AdmissionSeal |
| FinalizationLink | 顺序实验用的已提交投影：permit_id/issued_revision、Binding、EncodingEvidenceRef、AdmissionSealRef、GuardRef、GateAccessRef、OwnershipRef、BudgetChargeRef、控制/授权/两安全Ref、packet双字段、committed_tick和发送半开窗口。它不是完整AdmissionSeal或新线上消息，也不能仅凭字段齐全签发 |

Ref均比较完整id/revision/digest，禁止把三元Ref直接赋给旧ContentRef；投影到旧ContentRef时显式取object_id=id和digest，原revision继续由EncodingAuthorization保留。摘要仅排自身顶层摘要字段后JCS；bytes_digest另取**原字节**SHA-256，不对设备字节做JCS。计数使用严格U20字符串；max_bytes沿用既有单packet结构上限65536，真实profile可以更窄，不能把它当生产吞吐批准。

EncodingAuthorization由Controller在核对实际受理来源、当前凭据和对象权、批准能力/参数Schema/编码profile、目标出口、准备容量后持久签发。worker只能从已认证的当前Controller通道接收，禁止面板、Seamer或模块自填权威。手动/自动化及面板/非面板来源仍须原用途权限交集；授权不会因“只编码”而放宽对象读权或秘密投影。取消取当前取消Requester，不能继承父actor。来源/凭据/出口失效、all关闭或准备取消后不再接受新编码，旧已保存响应仅作历史。

仅编码允许从固定命令、计划、已采集状态和编码profile计算不可变字节；**不得写设备、握手、自动重连、隐式请求新状态或执行厂商库重试**。需要设备交互才能取得的前置状态必须通过既有受控路径先取得，不能藏在编码回调中。可信模块仍需合规实现和运行验收；此字段不是恶意插件沙箱。编码容量预留覆盖CPU、内存、原字节留存和并发任务，独立于设备发送预算；编码失败不消耗全局ci_issue或生成发送许可，但应按其自身容量政策归还/保留准备槽。

## 完整IPC修订

- 版本为`ipc/0.11.0-encoding-authority-draft.1`，48种消息全部同版，握手新增必选`encoding_authority_before_issue`。旧字段不降级解析，未支持的worker不能接入写路径。
- ENCODE_PACKET删除guard_id/guard_digest；ENCODE_CANCEL_PACKET删除guard_ref；两者新增完整encoding_authorization。普通请求仍保留原命令和计划/profile，取消仍保留唯一execution_ref；这些重复字段必须与授权逐项相等，不能各用不同来源。
- PREPARE_PACKET、PREPARE_CANCEL_PACKET、PACKET_ENCODING_FAILED、CANCEL_ENCODING_FAILED和PREPARE_PACKET_REJECTED增加encoding_authorization_ref，reply_to仍精确关联原消息。失败原件不能被转换成成功证据。
- worker对同prepare_id保存不可变请求和原结果；相同重投只查缓存，冲突关闭通道。缓存丢失不重新编码同准备身份，Controller按未知准备处理并清理/退役；编码没有设备副作用也不授自动设备重试。
- 最终GUARD_INSTALL/CANCEL_GUARD及其ACK、DISPATCH/RESEND_DISPATCH保持完整旧语义，本轮只解决其前置编码引用。ENCODE响应绝不能直接被发送器读取为DISPATCH。

## 顺序与事务边界

1. **准备事务**：保存仅编码授权、稳定prepare_id、原请求正文、出口和容量预留，确认提交后才入ENCODE队列。不得分配ci_issue。无跨IPC等待的未提交SQLite事务。
2. **编码接收事务**：先严格解码和验证当前来源，再核原请求/响应/目标/各世代、授权截止、profile及字节；保存完整报文、原字节和EncodingEvidence。接收时刻来自可信收包者，`created <= request <= received <= current < expires`，截止等号拒绝采用。普通proposed_attempt_id在此仍只是预留ID。当前实现的局部模型不验证完整参数资格提供者。
3. **最终T2写集**：在BEGIN IMMEDIATE内读取当前普通ReadyCommit或取消ScopeCommit与完整前态；重核编码授权仍有效、实际命令/取消执行及primitive来源、当前授权/控制/全部保护。按既有方案同事务创建普通首次hold、Ownership及后态资源快照；取消复用自身Plan对应hold。计算新全局issue、每次传输独立预算扣费、最终Guard完整原件、PermitAuthority、AdmissionSeal及消息意图，一次封存提交。不能要求该seal依赖尚未发生的Guard ACK。各原件仅向前引用；Guard不反向包含SealRef，Seal引用Guard内容及准备证据。
4. **安装最终Guard**：仅当T2结果可靠确认且当前资格仍满足，唯一有序出口才发GUARD_INSTALL或CANCEL_GUARD。精确ACK包括原guard、permit或execution、当前运行域/会话、内容与范围回显，可靠保存后才进入发送候选。ACK等待期间不持有SQLite写事务。ACK迟到或原件撤回只留历史。
5. **设备发送**：先核当前控制/范围/授权/两安全代次、完整Guard、packet原字节、逐次预算回执和实际当前时间；UTC子条件仅在能力要求时执行，普通排期另验，取消不继承父排期。之后在设备唯一串行出口先消费permit再调用I/O。ACK不代替这一步，入流后的撤销传播窗口仍存在。

编码后的参数/计划/profile、scope或出口不能被替换；编码证据过期后在新T2不得采用。T2已可靠封存的编码证据保留为历史，不因编码TTL经过而抹去已经签发的intent；后续发送由原有更严的Guard/发送窗口及当前撤销约束裁决，不能延长窗口。协议重传复用同packet原字节及原准备证据，但需要新permit、新issue、新Guard和新预算，且完整准入证明其适用性；禁止自动把旧准备用于新设备session。

COMMIT失败全回滚；COMMIT结果未知则隔离该候选、禁止安装和发送，只查原记录。查到历史提交不等于重启后可以继续投递。消费前失败可留未发证据，消费后I/O或报告故障为unknown；无完整屏障证明不能改称not_sent。设备预算已提交即不因Guard失败、超时或未知自动退款；准备缓存释放与实际风险hold释放分别取证。已入流消息由既有完整屏障覆盖。

## 故障与验证

| 场景 | 必需结果 |
| --- | --- |
| 编码成功，T2未开始或明确回滚 | 没有issue/设备预算/发送；准备字节不是许可 |
| 编码请求携最终Guard/Ownership/permit | 新版Schema拒绝，避免重建依赖环 |
| 重算授权摘要，但与持久原件或Requester不符 | 拒绝；摘要正确不授来源权威 |
| 响应错reply_to、授权Ref、出口或packet字节 | 不形成可采用EncodingEvidence |
| 编码截止等号、接管或凭据失效先到 | 拒绝T2采用；后续恢复不续旧准备 |
| T2未知或进程重启 | 不安装Guard，不按发送outbox补投；历史许可参与屏障核对 |
| T2成功，GuardACK缺失/错引用/迟到 | 不DISPATCH，预算不自动退回 |
| 精确GuardACK后控制或安全代次推进 | 最终出口拒绝；普通ready不替代取消范围，反之亦然 |
| 同permit重复或消费后故障 | 只回原结果，设备调用最多一次；未知仍未知 |
| 协议重传复用预算或issued_revision | 拒绝，新传输必须独立扣费与签发 |

[检查器](check_encoding_authority.py)验证新Schema、完整48帧结构、编码授权与实际合成报文/原字节关联、独立人工预期的顺序和失败分支。400项检查覆盖三种失败响应、重算摘要后的证据错配、T2期限等号及编码后撤权；首次保存证据和新T2均重核原请求/响应及当前编码授权，重复历史查询不恢复新签发资格。已提交后经过编码TTL的正例仍须独立最终窗口和当前资格。最终提交投影及这些权威仍由人工上下文提供，检查器不执行完整Guard/AdmissionSeal、授权服务、编解码器、SQLite、真实IPC、并发、磁盘或设备。全部可信上下文一并伪造可通过是明确记录的限制反证，不代表生产准入。

剩余工作继续归属C02/C03/C08：普通逐出口准备及其容量/取消/入站去重DDL，完整AdmissionSeal/Guard/预算/时间提供者同库联接，全部关闭来源与全消息序号账本，以及统一SDK源归并。本轮关闭“编码是否必须先有最终Guard”的设计歧义，不能据此解除194表四阻断或宣布阶段0完成。

复验：`python docs/contracts/c08-controller/build_encoding_authority.py --check`；`python docs/contracts/c08-controller/check_encoding_authority.py --report`。报告绑定检查只比较声明输入的原字节，不重跑用例。
