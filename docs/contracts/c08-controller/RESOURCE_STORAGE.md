# Controller资源占用与释放持久化候选

状态：待审阅。`resource.sql`在现有51表之后增加15表，构成66表内存组合；不修改已批准公共协议，不是产品迁移，也不实现业务writer。语义依据是[LIFECYCLE.md](LIFECYCLE.md)；本轮落实其中资源关系，命令修订、Resolution/T6完整写集仍需继续归并。

## 1. 已知事实与本轮设计

既有`ce_current_disposition`汇总原报告、逐出口覆盖与尝试ACK，迟到in_flight优先；`ce_open_permit`仅用于自动化运行保护。原表中的非空BODY不证明提供者事实。（来源：[fence.sql](fence.sql)、[barrier-attempt.sql](barrier-attempt.sql)。）

本轮推荐新增独立资源层。正常T2同时获取整设备hold和传输许可；风险占用视图覆盖manual与automation。释放后旧强事实到达时，数据库原子保留原件、追加释放失效并锁存设备保护，允许旧hold和新hold同时出现在风险视图。没有会拒收迟到事实的“每设备一个风险hold”唯一索引；正常准入由单writer事务及完整风险视图保证。

这里的保护记录表示**Controller已持久锁住新许可**，不是worker已应用屏障，也不表示在途命令已撤回。实际收到强事实到落库之前须走既定独立保护通路；存储故障沿Q52停写。跨进程传播、完整目标屏障及设备效果仍需运行验证。

## 2. 十五表及权威边界

| 表 | 关系与责任 |
| --- | --- |
| cr_validation | 同controller_scope的可信提供者原件；固定purpose、subject_id/digest、command/device、policy/provider Ref与来源BODY |
| cr_validation_revocation | 追加原件撤回及审计，禁止修改/删除旧证明 |
| cr_claim | 与T1受理同事务的命令资源政策；无独占占用 |
| cr_hold / cr_hold_commit | 一个attempt对应一个整设备hold；双向延迟FK，封存要求已有传输和传输提交；审计/outbox同事务 |
| cr_hold_close | 固定hold的后续发送入口已关闭证明；只增，可在旧证明被撤回后追加新证明；关闭后永不再给原attempt签发许可 |
| cr_settlement_validation | 原ce_settlement与可信验证原件关联；非空旧BODY不直接获得释放资格 |
| cr_release | 绑定hold、command、当前全局issued水位、完整cut和独立释放提供者；kind与固定政策关联 |
| cr_release_attempt | 冻结该命令当时全部attempt及精确hold/关闭原件，不只列最后attempt |
| cr_release_member | 冻结该命令当时全部permit，包括历史已核销项；绑定具体核销验证 |
| cr_release_commit | 双向延迟FK及完整集合封存，附审计/outbox；少一项或跨命令拼接不能提交 |
| cr_release_invalidation | 首次失效原因与原report/barrier ACK/逐出口结果/验证撤回关联，形成设备保护锁存；后续原件继续留在源表 |
| cr_recovery / cr_recovery_member / cr_recovery_commit | 设备保护恢复候选；可信恢复提供者、全部历史失效集合、无风险占用及审计/outbox同事务；不等于重新布防或取得控制权 |

表内Ref和BODY是物理存储约定，线上完整Ref仍由SDK校验及解析，不能把policy_ref文本当权限。`cr_validation`只保存经可信writer验证后的accepted原件；rejected/indeterminate材料进入原证据/审计域，不写入这个可授资格的关系。SQL检查purpose、拥有者、subject摘要及政策对应；它不验证JSON/JCS、证书、来源完整性、设备效果或权限时效。非法调用者不能直接写库，Schema同形JSON不成为提供者。检查夹具中的`trusted.fixture`只是合成前提。

hold准入的当前控制、授权、NTP、预算、原期限、锁存与重试政策必须由真实writer在T2验证；`cr_validation`没有通用“永久准入授权”含义。其当前用途到本次事务为止，每次重传仍按IPC0.6重新校验守卫及预算，不能只因数据库外键合法继续发送。

## 3. 事务与集合规则

**T1**：现有ca_request_key/初始command/裁决/容量/审计/outbox，加ce_command和cr_claim；ca_commit的约束拒绝缺claim。资源层不替换原请求幂等身份。

**T2**：准备产生attempt/packet可以先独立保存。真正发送前，在同一writer事务验证当前上下文，保存可信准入回执、hold、permit、transmission_commit及hold_commit；后者要求真实登记的传输提交。任何缺写回滚，不把编码提案当发送。协议重传沿同attempt/hold、同packet的新permit，且仍受关闭与设备保护检查。

**关闭和核销**：提供者验证全部后续入口关闭后追加cr_hold_close；不是在插表时才开始假定worker已经关闭。旧attempt永久不能再签发permit。每个原ce_settlement单独关联验证；never_sent仍须当前not_sent，effect_resolved要求独立效果排除证明。监督退出本身不能填充效果证明。

**释放封存**：先写release、全部attempt和permit成员，再写release_commit；按同writer当前登记做双向差集，验证全局水位、每项关闭原件、核销原件及独立release原件。never_sent不接收effect_resolved冒名；module_settled/maintenance_fenced可混合两类已核销传输，但仍须独立整体证明。只是最后重传未发不能清理前一次传输。

**历史切点澄清**：完整集合是封存时该命令的全部历史，不是未来无限增长集合。旧attempt永久关闭后，后续合法retry使用新attempt和新hold，不追溯使旧hold的正确释放失效；新hold释放须再次包含全部旧attempt/permit。迟到事实或使用过的证明失效仍会推翻所有依赖该证据的旧release。上一轮模型对当前hold的current cut核验，与这里按hold保留历史cut的规则共同使用；不能把新attempt的出现本身当成旧证据造假。

资源层不单独授权retry，也不决定finished/unknown的公开状态：原unknown的释放对外clear必须与Resolution/T6提交绑定；本轮SQL仅证明资源子域，完整命令修订层尚未联接。因此不能直接把`cr_risk_hold`为空投影成公共Command.resource_status=clear或READY。

## 4. 迟到失效与恢复

以下三种已持久强事实均有数据库触发路径：原ce_report进入传输；ce_barrier_ack（包括未采用的旧尝试）；ce_target_result对应的覆盖。它们重新检查依赖release，追加cr_release_invalidation，与源记录原子提交。效果核销已经独立排除影响时，重复发送观察不会误推翻；只有该效果证明本身被撤回时重新保护。

提供者原件撤回逐项沿release、成员核销和成员关闭三类关系传播。恢复提供者原件撤回则直接使旧恢复覆盖失效，设备保护重新可见。原件/核销/释放/失效都不更新或删除；强事实接收不依赖当前操作者仍在线或仍有新控制权。

恢复必须先独立清理所有风险hold，再按设备冻结全部历史失效release的集合，双向差集封存。遗漏先前已经恢复的历史项也拒绝，避免同设备多次恢复时只取最后一条。新的失效不在旧恢复集合内，自动重新锁存；恢复原件失效亦不靠缓存状态位隐藏。恢复不会自动重启Seamer、重新签发旧permit或取消手动接管，后续写仍需当前完整准入。

失效行是派生保护事实，源记录本身含审计/证据；通用保护outbox到worker的连接、T6对外事件以及恢复操作的公共HTTP还待归并。这里不声称已完成真实P1/P3/P4传播。

## 5. 验证与故障验收

[check_resource.py](check_resource.py)只加载66表到内存，逐写删除或主动注入异常后比较全部表；按固定夹具运行两种串行顺序，不模拟磁盘掉电或真正并发。

| 验收场景 | 必须结果 |
| --- | --- |
| T1遗漏claim，T2遗漏hold或permit提交，释放/恢复缺写 | 整个事务不能提交或完全回滚 |
| 手动持有时自动化取得hold，及反序 | 两者共用风险集合并拒绝冲突 |
| 释放少一个历史attempt或permit、重算公开摘要 | 完整集合差集拒绝，不能靠摘要放行 |
| 释放后另一holder已开始，旧强事实迟到 | 两份风险占用保留，原件与保护同时可见 |
| 未采用的旧ACK迟到 | 照常保留强事实并保护，不因未采用而丢弃 |
| 仅源核销BODY存在、关闭证明缺失或绑定错设备/政策 | 不得释放 |
| 已有独立效果排除证明，重复进入传输观察到达 | 不误推翻有效核销 |
| 释放/关闭/核销证明被撤回 | 使用过该证明的release失效，风险与保护重新可见 |
| 新释放已清风险，但保护尚未恢复 | 仍拒绝新设备许可 |
| 恢复后新增失效，或恢复证明被撤回 | 原恢复不能覆盖新风险 |
| 恢复提交后响应丢失 | 查原恢复记录，不再发送旧命令 |

后续运行验收须分别证明：真实提供者取证、单writer隔离、存储故障关闭通路、REPORT_STORED时点、跨进程保护传播、磁盘/WAL恢复和实际设备效果。内存外键及integrity_check通过不证明这些事项。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_resource.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_resource.py --check-report --staged
```
