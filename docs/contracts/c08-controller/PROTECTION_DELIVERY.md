# RUN保护应用的当前资格与P4接收候选

状态：待审阅，`protection-delivery/0.1.0-draft.1`。在[230表候选](PREPARE_DENY_STORAGE.md)后加载[Controller补充SQL](protection-delivery.sql)，得到232表；[Seamer接收SQL](protection-receiver.sql)为另一个数据库的5表实验。不是产品数据库迁移，不改变已确认公共API或IPC基线。

## 事实与本轮推荐

已知事实：`ce_application`保存不可变历史回执及原outbox；上轮`pd_valid_application`只合取准备Closure。当前仓库没有完整P4接收服务，不能以一次字符串替换宣称接收、撤回传播和恢复已实现。（来源：[原执行表](fence.sql)、[准备组合器](build_prepare_deny_storage.py)、[DF04第16节](../../rebirth-df04-storage-design.md#16-来源保护的持久所有者与四个事务)。）

本轮推荐：历史回执、Controller当前资格、Seamer已观察状态分开。原历史不改写；资格失效必须同事务留下可投递的状态修订；P4持久接收完整来源身份和原件引用，按最高修订汇总。它们均不清理资源、不解除latch、不授权重新布防或设备发送。

## Controller存储与消费路径

`ra_qualified_cut`逐个固定ce_target核验原ce_target_result及ce_result_binding。worker_ack必须有原ce_barrier_ack且没有新的ra_barrier_revocation；supervisor_retired必须有原ce_retirement且未被cu_revocation撤回。原cut完整集合、普通及取消覆盖检查保持。`pd_valid_application`现在同时依赖该集合和当前有效准备Closure；P3插入时重新核验，不能在采用结果后、提交应用前撤回证据再借旧检查过关。

新增两个不可变表：

| 表 | 字段与来源 |
| --- | --- |
| ra_barrier_revocation | barrier_id精确FK原RUN ACK；reason_body、audit_body必需。只能追加，不能借通用control ACK身份撤回另一类消息 |
| ra_status_event | (fence_id,revision)唯一；revision=1/applied/initial或2/indeterminate/失效原因；cause_kind、cause_id指向原closure、采用的RUN ACK或退役出口 |

本候选把同一不可变application的失效定义为永久：最多两个修订，不存在修订3恢复为applied。新取证及增强保护须另建原有新操作／新cut，不能改写原ce_application。其他API版本计数继续按各自契约处理，本模型的两态修订不能推广到整个项目。

ce_application的AFTER触发器写初始事件，三类撤回的AFTER触发器追加失效事件。事件不能脱离原件直接伪造；通知写入失败使整个源事务回滚，真实writer随后必须执行已有的内存关闭和监督保护路径，本轮未执行该运行路径。多个原因不会重复产生修订2，但全部撤回原件仍保留，可通过ra_invalid_evidence查到完整原因集合。

| 消费者 | 本轮规定的唯一用途 |
| --- | --- |
| 历史审计、原回执字节、原接收重复查原 | ce_application和ra_status_event；明确标历史，不代表当前资格 |
| Controller当前保护查询、准备closed所需应用资格 | ra_current_status与pd_valid_application；不能使用历史行存在性 |
| 待发送保护通知 | ra_status_event原身份及修订；重投不换身份。每次状态查询走ra_current_status，不把排队旧事件改称当前快照 |
| Seamer P4原件接收 | sp_observation及sp_observation_commit；确认只表示接收事务已提交 |
| Seamer/GUI汇总 | sp_observed_summary；显示已观察状态和每目标修订，不能隐藏未收到目标 |
| 恢复、重新布防、最终发送 | 原有独立当前验证与屏障流程；本候选没有可授予恢复资格的视图 |

`ra_current_status`在资格与最高事件不一致时不返回applied；读取方报indeterminate并调查存储一致性。没有application但已有保护请求时继续按原P2显示accepted/fencing，不能把未查询到当前应用当作not_found或允许重发设备动作。prepare close来源也有内部资格与事件，但不是保护HTTP operation；本轮HTTP片段导出明确拒绝该来源，不能伪造ProtectionRequest。

## 可校验状态片段

[Schema](protection-delivery.schema.json)选择具名Observation验证。它是已有鉴权和时间上下文包络内的状态片段，不是新的裸HTTP响应，也未替代旧ControllerRunFenceReceipt。

| 字段 | 约束 |
| --- | --- |
| contract_version | 固定本候选版本；不能作为已批准SDK版本发送 |
| binding | controller_scope、origin_scope、operation_id、run_id、deny_through_generation、selector_digest、target_set_digest全部必需；与P1封存目标逐字段相等 |
| fence_id、cut_ref | 原切点身份及cut_body精确字节SHA-256；cut_ref.id必须等于fence_id |
| receipt_ref | 原ce_application receipt_id及receipt_body精确字节SHA-256；失效不替换原回执 |
| prepare_closure_ref | 原prepare_closure_id及其已存规范摘要；两修订必须同一个原件 |
| status_revision、state | 字符串1/applied或2/indeterminate；拒绝数字、前导零及其他修订 |
| cause | initial绑定fence_id；prepare_closure绑定准备Closure；其他原因绑定采用ACK／出口，Controller原件资格另验 |
| observation_digest | 除自身外完整片段的JCS SHA-256，前缀sha256；缺字段、额外字段或重新摘要后的作用域错配均拒绝 |

`bytes_digest`特意指精确字节摘要，不能替换为JCS摘要；外层observation_digest与原prepare_closure规范摘要也不能混用。代次在线上为1至20位十进制字符串；SQLite原补零U20仅在边界转出，不经过浮点数。原件BODY的真实性、规范内容及摘要是否确由可信提供者形成仍是原始约束，外层校验不能替它背书。

## P4独立数据库与传播窗口

sp_plan、sp_target、sp_plan_commit导入已核验且封存的P1完整目标。计划有固定target_count、plan_digest、原正文；目标有不可变binding正文，提交按集合计数封存。空集合必须由P1依赖索引证明确实为空，不是超限后截断。此导入仍是明确的合成信任边界，完整P1 fault/latch/outbox及其真实外键尚未联接，不能把接收表反向当作P1已实现。

P4写集为sp_observation→sp_observation_commit（audit/outbox），双向外键防止只存一半。接收者先验证当前认证Controller域、Schema及JCS摘要，再与固定目标binding和已知原件身份比较。同(plan,target,revision)同规范正文只返回原接收结果；异正文拒绝。不同修订也不能替换cut/receipt/Closure。接收revision2可以先于revision1；后到历史只补原件，不降低sp_current_observation。完整目标全部已观察applied才汇总applied，任一indeterminate优先，缺项保持pending。

Controller提交失效与Seamer接收之间没有跨库原子性。若最新通知尚未到达，Seamer仍可能保留旧已观察applied；这不是远端持续有效的证明。断流、游标缺口、当前身份不能验证时显示未确认并按原规则维持暂停。恢复必须重新取得当前完整证据、处理源基线/资源/latch及最后发送检查，不能凭旧回执或一次HTTP查询获得无限期资格。本轮不实现通知服务、流健康/游标持久化或恢复消费者，因此不宣称实时跨库一致。

新增RUN ACK撤回目前联接状态资格与通知，不等于已把所有曾依赖该ACK的资源核销/恢复引用传播到统一资源失效账本；该依赖联接和其他AUTH/TIME权威保持为缺口。已有最终准入四个阻断继续存在，不以这次P4实验解除。

## 故障验证与交付范围

```text
python docs/contracts/c08-controller/build_protection_delivery.py --check
python docs/contracts/c08-controller/check_protection_delivery.py --report
python docs/contracts/c08-controller/check_protection_delivery.py --check-report --staged
```

[报告](protection-delivery-report.json)绑定完整输入。实验使用真实SQLite内存事务：三类撤回、先撤回后应用、通知失败回滚原事务、同修订冲突、丢响应查原、先失效后历史、完整目标汇总、跨域/跨run/错cut及缺原件。第二Controller目标是显式合成输送夹具；没有启动第二Controller进程。P1导入来源、认证身份、部分原件BODY同样是合成前提。真实IPC、并发writer、磁盘崩溃、鉴权、通知网络、NTP及设备验收均未执行。

剩余冻结：P1导入替换为真实计划外键、准备closed与恢复消费者接入当前资格、RUN ACK撤回到资源证明的依赖传播、剩余消息共享日志、AUTH/TIME、完整AdmissionSeal/Guard/预算/时间，以及唯一SDK契约源。阶段0未关闭。
