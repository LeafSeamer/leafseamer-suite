# 同一物理闸的独立换代屏障

状态：设计候选，未批准运行。此稿补[限定取消范围](SCOPED_GATE.md)要求的新屏障来源；不改旧IPC0.9或182表，不建立第二物理写闸，不解除四个最终签发阻断。

## 已知事实与推荐

已知事实：原`go_gate_guard`只要求`cu_ack.gate_revision <= 新闸修订`，因而可以用同一旧ACK生成更高修订的新fenced记录。旧关闭ACK仅有设备集合，不能证明新的闸修订。控制FENCE还绑定接管操作、目标控制版本及完整许可覆盖，不能伪造一次接管来取得换闸资格。（来源：[旧SQL](open-storage.sql)、[IPC0.9](scoped-gate-ipc.schema.json)。）

基于上述事实，新增独立`GATE_FENCE / GATE_FENCE_ACK`，形成[IPC0.10完整48帧候选](gate-renewal-ipc.schema.json)。它只在新CLOSE已经确认后安装新的物理屏障身份，不改变持有人、控制版本、资源风险、取消结果或GUI ready，不替代CONTROL/AUTH/RUN/TIME及ordinary/all的许可覆盖。之后仍须完整普通ReadyCommit或限定ScopeCommit才能发OPEN并采用发送资格。

## 字段、消息与所有者

| 原件 | 必需字段与来源 |
| --- | --- |
| GATE_FENCE正文 | `request_id`作为新的屏障ID；完整`binding`；`control_authority_ref`；`before_gate_ref`（仅出口从未有闸时null）；精确`close_ack_ref`；`target_gate_revision`、新`gate_token`；`selected_tick_ns / expires_tick_ns / lease_until_tick_ns`；`request_digest` |
| GATE_FENCE_ACK正文 | 原`request_id / request_digest / binding`，精确`gate_revision / gate_token`，实际设备闸安装的`effective_tick_ns`，`state=fenced` |
| 共同信封 | 复用设备IPC完整域、两boot、session、device、方向序号和message/reply_to；ACK必须回原请求，不是当前状态查询 |
| SQLite原请求 | `gf_request`关联实际出口、旧go_gate、控制原件、原close ACK与当时安全代次；原正文、同事务outbox和审计；方向序号只作本子域唯一约束 |
| 原ACK及采用 | `gf_ack`保存原消息、可信接收tick及验证回执；`gf_commit`一次关联原请求、原ACK和新的go_gate；go_gate反向延迟FK保证不能只写闸记录；`gf_revocation`只追加撤回 |

JCS只排正文自身顶层`request_digest`，不递归删除业务同名字段。wire的U20不补零，SQL保持已有20位补零排序。请求必须满足`selected < expires <= lease`，实际采用要求`received <= committed < expires`；等号到期拒绝。ACK即使迟到仍可保存，但不能因此采用。有效时刻必须在选择与可信接收时刻之间，且处于同一受监督时钟域。

Controller单writer负责持久请求、选择与采用。唯一会话发送器分配**全消息**方向序号并按已持久前缀投递；当前SQL仅有本子域唯一键，不能宣称全消息有序日志已经完成。入流前复核当前控制、最新关闭、域、期限和本地安全代次；任一变化丢弃候选，已入流前缀仍保留既有传播窗口。

worker在同一设备串行闸核完整绑定、当前关闭原件及原闸身份，拒绝陈旧目标修订、旧token及到期请求。成功时保持物理关闭，清除旧Access/Guard，安装新屏障ID、修订和token，再缓存原ACK。没有收齐全部设备的CLOSE ACK，不得把某个设备投影冒充整个Controller已关闭。此消息不产生新的“未发送”或资源释放证明。

同请求ID与相同原字节重投只回缓存原ACK，不重新装屏障，不关闭后来合法OPEN，也不延租。ID换内容或方向序号冲突终止会话。缓存丢失不能猜ACK：终止旧会话并按监督退役流程重建；不自动执行旧OPEN或许可。一个关闭ACK只允许创建一个换闸请求；该请求未知时先查询/重投原身份，若需新的换代，先完成新的CLOSE与ACK。已有QUERY_BARRIER/BARRIER_STORED仍只服务原覆盖账本，不借用来查询本请求。

## 同库约束及故障顺序

[定义源](build_gate_renewal.py)生成[186表组合](controller-gate-renewal.sql)，新增四表，沿用共享go_gate。`control_barrier_id`与`renewal_id`严格二选一；公共`barrier_id`等于所选来源ID。控制来源必须精确匹配ACK修订，且同ACK只能创建一次fenced（后续ready投影保留同来源）。换闸来源必须匹配原请求目标、token、租约与旧闸，不允许凭更大的数值自造证据。

请求创建检查当前控制、无pending、完整域、同出口最新关闭及原ACK未撤回、旧闸和安全代次。目标修订严格高于该出口全部旧请求，token不得重复使用；未采用或未知请求也不退款这两个身份。原ACK只作历史绑定检查。采用事务写新go_gate及gf_commit，最后再次核当前控制、最新关闭、原安全代次、未撤回及期限；缺少任一半边不能提交。原ACK可提前独立落库，采用失败保留它供查原。

`gf_valid_fence`仅表示原物理屏障的当前可用来源，**不是发送资格**。正常资源恢复会推进安全代次，其后完整新快照/OPEN仍可使用同一已安装屏障；不得让旧请求在恢复之后才采用。后来新关闭、接管或原关闭/换闸ACK撤回会使原屏障来源失效。换闸ACK撤回同事务推进共享安全代次，使旧开放候选失效；实际关闭outbox仍须纳入统一保护来源，SQL标志不证明worker已关闸。

| 故障/反例 | 必须结果 |
| --- | --- |
| 重用旧控制ACK并提高闸修订 | 旧布局复现成功；新布局拒绝 |
| 请求后新关闭、接管pending、旧关闭ACK撤回或安全代次变化 | 不采用旧ACK，已持久历史不改写 |
| 新闸写入后、采用封存前证明撤回 | 整个采用事务回滚，不发布新fenced |
| ACK的reply_to、目标修订、token、出口、摘要或时刻错配 | 拒绝入库；重算公开摘要不提供可信原件资格 |
| ACK到期后到达，或COMMIT结果未知 | 迟到历史可保存；未知只查原，不自动重开或执行 |
| 普通/取消范围切换及第二次恢复 | 新CLOSE、新请求、新ACK、新修订/token；不能复用已消费的关闭证据 |
| ACK撤回发生在已OPEN之后 | 撤当前资格并安排完整关闭，保留已发生的设备影响和资源风险 |

## 验证与剩余联接

[检查器](check_gate_renewal.py)执行内存SQLite反例、原子配对/主动异常、期限等号、两轮换代、撤回和不可变历史，并验证完整IPC的结构投影。BODY、原消息真实性、JCS及observer资格仍由合成夹具代表；JSON与SQL并非真实提供者端到端。没有真实worker、网络、并发、磁盘故障或设备验收，参考SQLite版本不代表产品驱动批准。

后续沿现有收敛清单完成ScopeCommit/ReadyCommit分型、完整Assessment/AdmissionSeal、两安全Ref权威映射、统一关闭来源与全消息入站/发送日志、严格解码及唯一SDK源。换闸原件不替代这些准入条件，四个最终签发阻断保持；本候选不是最终功能降级或可部署中间版本。

复验：`python docs/contracts/c08-controller/build_gate_renewal.py --check`；`python docs/contracts/c08-controller/check_gate_renewal.py --report`。`--check-report --staged`只核声明输入原字节，不重跑测试。
