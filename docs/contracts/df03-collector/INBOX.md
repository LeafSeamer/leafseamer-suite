# 采集器入站去重与效果原子提交候选

日期：2026-10-23。本文基于[0.2机器协议](channel-v02.schema.json)和[25表日志组合](JOURNAL.md)审阅，给出待审阅推荐。`collector-inbox/0.1.0-draft.1`增加tc_inbox/tc_inbox_seal形成27表，生成物为collector-storage-v02.sql；不改旧25表文件，不修改14帧协议或业务代码。

## 1. 已知差异与显式修正

已知事实：0.2的核心出站集合是ACCEPT、CONFIGURE、POLL、REPORT_STORED、QUERY_CAPTURE、COMMIT_STATUS、STOP；采集器出站集合是HELLO、CONFIG_ACK、POLL_ACK、CAPTURE_REPORT、CAPTURE_STATUS、QUERY_COMMIT、STOP_ACK。旧journal.sql却把QUERY_POLL和QUERY_COMMIT列作核心出站，不能直接接入真实协议。（来源：[协议生成源](build_contracts.py)、[0.2投影](build_channel_v02.py)、[旧SQL](journal.sql)。）

本次组合显式将旧SQL的QUERY_POLL替换为QUERY_CAPTURE，将核心出站QUERY_COMMIT替换为COMMIT_STATUS。替换只在固定SQL源的四处枚举/查询预算引用发生，原文件保留供差异复验。查询帧预算覆盖核心发出的QUERY_CAPTURE与COMMIT_STATUS；采集器QUERY_COMMIT的受理与固定响应同事务，响应额度不足则不产生半边成功，关闭通道并监督退役。不得将旧SQL的枚举视为协议扩展。

## 2. 全部消息关联

| 采集器到核心 | reply_to目标 | 持久效果 |
| --- | --- | --- |
| HELLO | null | 可信监督身份及严格握手后，登记观察；本方向第一帧且仅一次 |
| CONFIG_ACK | 本channel已尝试的CONFIGURE | 固定观察，不因configured自授资格 |
| POLL_ACK | 本channel已尝试的POLL | 固定观察，reserved不等于已发网络包，rejected不直接清未知槽 |
| CAPTURE_REPORT | null | 首次Capture与原件/裁决/回执队列/活动核销同事务；已有精确Capture只记录历史引用 |
| CAPTURE_STATUS | 本channel已尝试的QUERY_CAPTURE | reported按Capture路径；reserved/consumed/cache_missing仅观察，不重发、不核销 |
| QUERY_COMMIT | null | 固定COMMIT_STATUS与入站处理同事务；known只返回原回执，not_found不授权重发 |
| STOP_ACK | 本channel已尝试的STOP | 首次原ACK与入站同事务；重复精确原ACK只记录历史引用，不覆盖closed_tick |

核心出站ACCEPT必须回复HELLO，REPORT_STORED回复首次Capture所属的CAPTURE_REPORT或CAPTURE_STATUS，COMMIT_STATUS回复QUERY_COMMIT；其余四种出站reply_to必须null。tc_frame新增reply_to列，以channel和消息身份作外键，不把另一方向相同message_id当作同一对象。响应到达时可早于本机written落盘，但原请求attempt必须已持久；响应不是重新尝试发送的许可。

## 3. 两表、唯一writer及固定结果

tc_inbox保存channel、该方向sequence、message_id、kind、reply_to、效果类别、Capture/STOP/响应序号投影、原始完整帧字节及可信验证回执。tc_inbox_seal保存同一主键与固定处理结果；双向延迟外键使任意一半都不能单独提交。sequence精确+1且不回绕，message_id在channel内唯一。首次Capture及首次STOP_ACK各只有一个origin记录；后续不同序号携带同一领域对象只能引用已封存的原效果。

处理顺序为：有界分帧 → 严格JSON/版本/方向/Schema → 当前可信端点和运行域 → 序号/消息身份检查 → BODY及Ref与固定原件二次核验 → 事务内重新核资格 → 写入站和全部领域效果 → 封存 → COMMIT → 对外观察或发送。解码、当前端点、词法、JCS、Blob及时间质量仍来自明确的可信提供者；SQL列和非空verification_body不证明这些事实真实成立。只有正常提交后才可看到本次结果，事务内查询不对外发布。

首次Capture要求tc_inbox先入事务，随后原ts_capture/Blob/Verification/Anchor/State及REPORT_STORED、tc_release和ts_seal，再写tc_inbox_seal。同poll第二Capture不能借另一个消息身份更新旧裁决。首次STOP_ACK要求入站先登记，再保存精确tc_ack，最后封存；未知操作继续占额度。QUERY_COMMIT先登记目标响应序号，写精确COMMIT_STATUS及reply_to，再封存；已提交响应字节固定，即使之后原采样获得新信息也不改旧查询结果，新的查询是新的消息和序号。

**重复与冲突**：同channel/sequence/message_id且原帧字节完全相同，经过当前连接身份验证后只读原固定结果，不能再执行Capture提交、重写ACK、重开资格或新增REPORT_STORED。同序号/消息身份不同内容为identity_conflict，缺号为sequence_gap；均关闭通道、保持不确定结果并退役。不同序号携带相同Capture时，必须比较完整原Capture及摘要，SQL的capture_existing关联本身不足以证明相等；更换报告内容不能被当作合法重试。

核心已经生成REPORT_STORED但对端仍保留原件时，不通过新REPORT_STORED越过旧序号；采集器可以发送有界QUERY_COMMIT，核心返回新COMMIT_STATUS并携带同一CommitReceipt。旧回执是否已进入流的结论仍受唯一发送日志约束，不能在新连接重放旧队列。当前完整连接已丢失时，历史查询只用于恢复核对，不再通过旧channel授新采样资格。

**崩溃边界**：事务未提交则接收/领域效果整体不可见，重启先关闭旧资格、恢复账本和退役，不因查不到记录就重新请求网络采样。事务已提交但进程未反馈，只查原结果。数据库提交未知期间停止处理新帧，先核精确入站身份；只有明确找到封存结果才返回历史，否则维持保护。来自退役channel的迟到字节，只能由可信接收提供者证明其原身份及取得时序后保存不合格历史，不能把一个新的未认证连接当作原channel；SQL仍不验证该时序前提。

## 4. 有界性与停止优先

tc_policy新增max_inbox，限定每channel普通持久入站数，重复相同帧的只读查原不增加计数。首次STOP_ACK另有一个保留槽，由每channel唯一STOP和唯一新ACK共同限制；新的序号重复ACK仍计普通预算。普通预算耗尽后不能无限保留不同查询或历史重述。

保留槽不允许跳过有缺口的前缀，也不保证每次故障都能得到ACK：若前一普通帧无法完整处理、接收容量已损坏或实际存储无法落盘，关闭通道并走监督退役。网络原件/失败/保护的磁盘保留空间仍由实际容量profile保证；本SQL的逻辑行数上限不等于磁盘或内存验收。

## 5. 验收与剩余边界

`check_inbox.py`核对机器协议全部14帧的方向和reply_to必要性、SQL两方向枚举，再执行27表内存约束：Capture/STOP_ACK/QUERY_COMMIT逐写缺失和主动故障回滚；响应绑定错误、未attempt响应、序号缺口、消息ID复用、同身份异字节、重复Capture/ACK固定结果、QUERY_CAPTURE首次找回报告、cache_missing不释放，以及普通满额与STOP_ACK保留槽。预期由人工给出，消息BODY及提供者均为合成，不执行产品严格解码器。

本候选定义完整入站持久所有者和失败规则，但尚未与实际IPC reader、Schema验证器、字段提取和业务writer端到端连接。27表不等于完整Controller/Seamer库，TIME设备屏障、密钥及容量profile、跨服务时间字段和统一SDK仍需归并。真实网络/并发/磁盘崩溃/设备未运行，历史25表269项不能充作本候选的完整回归证明。
