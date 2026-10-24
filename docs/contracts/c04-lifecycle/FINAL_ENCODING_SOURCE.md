# 最终封存的编码原件解析

状态：候选，`approved=false`。接续[编码持久化](TYPED_ENCODING_PATH.md)与[最终封存](FINAL_ADMISSION_STORAGE.md)，增加[同库解析器](final_encoding_source_model.py)和[验收检查](check_final_encoding_source.py)。现有242表DDL及四个最终签发阻断不变。

## 已知事实与本次连接

原`final_admission_model.verify`只核验调用方提供的18/21种投影彼此相容，不能证明它们来自持久原件。实际编码链已经保存完整请求、响应、EncodingEvidence、packet与不可变字节，但尚未接到最终封存的来源读取。（来源：[跨原件检查](final_admission_model.py)、[编码适配器](typed_encoding_path_model.py)。）

本次`read`要求已有writer事务，从`ep_prepared_candidate`定位原请求，再读当前命令、namespace、continuation和会话。它重跑现有编码响应验证，同时将实际接收tick用于重建历史证据；当前封存tick只用于资格和有效期判定，不改写历史接收时间。重建结果与实际`ep_reply`、入站日志、`ce_packet`全部命名列对账；出站日志重新核对完整规范帧、长度前缀、字节与SHA-256。领域接收commit及双向日志commit必须存在且时序有效。

然后读取实际命令初始正文、请求身份、prepared状态和当前命令状态，核摘要、attempt成员及未终结状态；还要求当前普通ready候选及计划、闸租约、资源快照未过期。当前外部提供者继续从受信调用者取得，不能把日志中的历史`validation_body`拿来代替当前授权、时钟或传输实例。

`planned`每次重新读取上述原件，逐项比对Seal中的binding、ExecutionIdentity、命令前态以及origin/encoding两个完整投影，之后才交原18角色关联检查生成附属写集。调用方改source_ref、延长TTL后重算所有摘要仍会失败。选择后的撤权、结束会话、撤回OPEN_ACK及命令前态推进不能靠旧投影越过最后读取。

## 明确的引用映射

| 引用 | 来源与摘要 |
| --- | --- |
| command_ref | ca_command_initial的command_id/revision/command_digest，先核实际正文摘要 |
| command_state_ref | cm_latest中的command_id、去补零revision、state_digest，先核实际状态正文 |
| attempt_ref | id取cm_attempt.attempt_id、revision=1；摘要取`attempt-source/1`描述，覆盖scope、command_id、attempt_id、十进制ordinal、prepared_revision及prepared_state_digest |
| identity.source_ref / origin.source_ref | id取ca_request_key.key_id、revision=1；摘要取`request-source/1`描述，覆盖scope、key_id、完整RequestKey及request_digest |
| encoding.source_ref | 实际EncodingEvidence的evidence_id/revision/evidence_digest，重建完整历史证据后使用 |
| encoding.packet_record_ref | packet_id、revision=1、packet_digest，明确映射自原TransportPacket，不能混用packet字节SHA |

两个`*-source/1`是本地派生来源描述，不冒充旧表整行摘要或旧协议已有的自摘要。规范字段由解析器构造并在返回结果中完整保留，以JCS计算摘要。投影Ref覆盖来源描述Ref、角色、读取事务及具名正文；换事务会生成新投影身份，历史源Ref不变。待SDK归并时须将这两种描述纳入具名Schema；当前只用于内部候选适配。

## 事务及故障边界

唯一writer应在BEGIN IMMEDIATE内读取、调用planned、写完整领域组并最终提交；解析器不自行打开事务、不提交、不执行I/O。Python的in_transaction只证明存在事务，不能证明其取得模式，BEGIN IMMEDIATE由调用者保证。封存期间外部提供者变化仍需真实提供者的代次或栅栏保证，本模型不能为数据库以外的状态提供原子性。

正例使用实际完整242表和已持久的类型化编码请求/响应，将两个解析投影送入完整18角色检查，返回19条附属写入。其余16角色仍是合成向量，未运行完整hold、Ownership、预算、Guard和许可的T2正向写集。不得将“生成封存写集”描述成“持久封存成功”。

反例覆盖原件与仅自洽投影的差异、接收/选择/封存时间边界、当前提供者失效、实际传输实例变化、grant/编码/会话/OPEN_ACK撤回、命令修订推进、持久正文损坏及缺packet映射。全程保留SQL守卫，解析失败不写库；已保存字节与历史证据保留。

后续必须继续补接另外16个具名来源与完整T2领域写集，再验证最后撤权竞争、发送前复核及SEND_REPORT库存。本项未完成阶段0，未验证真实身份/时钟/设备、进程崩溃或实际IPC。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_encoding_source.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_encoding_source.py --check-report
```
