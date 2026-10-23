# 准备关闭完成的实际应用绑定

状态：待审阅的237表内存SQLite候选。在[RUN资源235表](RUN_RESOURCE.md)之后增加两表，生成[组合SQL](controller-preparation-completion.sql)。不修改旧候选、业务服务或公共API批准版本，保留四个最终发送阻断。

## 已知事实与本轮分析

已知事实：原准备契约规定closing→closed，终态不能复活，applied回执保留；closed要求耐久protection_ref，但不代表在途资源clear。原cp_completion只要求非空BODY及事件/准备关闭外键，尚无实际ce_application引用；RUN当前资格已由pd_valid_application与ra_current_status提供。（来源：[准备契约](../c04-preparation/README.md)、[原准备SQL](../c04-preparation/preparation.sql)、[保护交付SQL](protection-delivery.sql)。）

实际反例：在原235表完成真实cp_close、完整cut和目标结果，但不插入ce_application，旧complete仍成功写入closed。新候选同样输入必须拒绝。该结果仅是内存SQLite约束证据，不是生产故障记录。（来源：[检查器](check_preparation_completion.py)、[报告](preparation-completion-report.json)。）

本轮推荐：历史状态与当前保护资格分离。closed及原applied_receipt永久保留，证明撤回不虚构closed→closing或closed→applied；新增当前保护状态及失效事件，消费者必须合取当前有效完成。资源占用继续由原资源权威判定，不能为得到closed而释放hold，也不能把closed当作恢复授权。

## 字段、来源与读模型

| 对象 | 字段及约束 |
| --- | --- |
| pc_binding | completion_id与cp_completion双向外键，后者延迟到事务提交；fence_id、receipt_id、原receipt_body精确绑定当前有效应用；binding_body、audit_body保留声明及审计 |
| pc_status_event | (completion_id,revision)唯一；state为applied/indeterminate，revision仅1/2；fence_id与run_status_revision精确外键指向ra_status_event，二者与绑定和事件状态一致 |
| pc_qualified_binding | 原ce_fence.close_id必须等于cp_completion.close_id；有效准备Closure、完整出口与当前RUN资格均成立；不可用同RUN的另一HTTP保护或另一close操作代替 |
| pc_valid_completion | 已完成cp_commit、完整绑定、当前资格、初始事件均成立，且无失效事件；只用于当前关闭资格，不授予设备发送 |
| pc_current | 保留cp_current全部历史字段，另提供protection_revision和protection_state；closing→pending，其他未closed状态→not_applicable，closed依据当前证据投影applied/indeterminate/unconfirmed |
| pc_run_risk | 按完整origin authority/database/run及generation上界连接原cr_risk_hold，返回completion_id、hold_id、command_id、device_id；仅表示已登记风险，不声明设备当前实际空闲 |

pc_binding不能在原cp_commit之后补写。完成源必须是本cp_close的真实应用，不能伪造HTTP ProtectionRequest来通过关联；应用已有的准备完整集合与普通/取消许可覆盖继续生效。binding_body中的语义声明、摘要、授权和真实原件认证仍由可信提供者核验；SQLite只核已投影关系和字节相等，不把任意非空BODY当认证。

pc_status_event同时是不可变的可重读投递事实；审计经completion→cp_event→cp_commit→cp_audit以及pc_binding追溯，原件/失效原因经ra_status_event追溯。投递身份使用Controller完整authority/database命名空间、completion_id、revision，不能只用本库ID。实际序列化、共享消息日志及发送/确认消费者尚未实现，不能把此表算作跨库通知已交付。

旧cp_current仅保留历史账本语义。GUI/API的当前保护结论必须消费pc_current或pc_valid_completion，不能仅检查state=closed或ce_application存在。closed+indeterminate表示曾完成、当前证据已失效，必须维持暂停和保护；unconfirmed用于无法证明一致性的读模型缺口，同样不能放行。保护修订不改写准备的历史revision，两种修订不得混用。

## 事务和故障时序

1. cp_close及同事务RUN deny/cut先持久化；真实完整准备Closure、逐出口结果及ce_application随后提交，不能跨IPC等待持有写事务。
2. 完成事务写cp_event(closed)、cp_completion、pc_binding、cp_audit、cp_notification，最后写cp_commit(complete)。最后提交再次核当前应用，不只相信较早绑定检查。
3. cp_commit触发同事务pc_status_event修订1。缺任一必需写入、逐写主动异常或状态事件失败，整个完成事务回滚，准备仍closing。
4. 完成前发生准备DENY ACK、采用RUN ACK或监督退役证明撤回：绑定或最终seal拒绝closed。绑定后、seal前撤回也必须拒绝；同事务失败会回滚本次撤回写集，writer须进入既有数据库故障保护，不能继续发送。
5. 完成后撤回：原ra_status_event修订2触发pc_status_event修订2，与原撤回、RUN失效、资源依赖扇出共享事务。完成之后、同事务COMMIT之前撤回也保留两事件，最终读模型只能indeterminate；失效事件写入失败回滚整个撤回事务。
6. 同RUN另一应用或另一close证明撤回不误伤本完成。精确原件才是依赖边；禁止凭设备相同批量撤回，也禁止复用另一个仍有效回执。
7. 提交响应未知按原完成ID/事件查原，已保存的两条状态事件可重读；不能重放设备动作。closed不复活，后续重新布防仍须新准备身份/代次及完整恢复资格。查询原记录和通知网络服务未实现。

关闭墓碑、RUN拒绝下界、原applied回执、历史应用和资源hold均保留。测试中closed可以与取消独立hold同时存在；撤回也不会删除该风险，不会隐式创建release/recovery。空风险结果不是资源已核销、设备无在途动作或允许恢复的证明。

## 验收与限制

```text
python docs/contracts/c08-controller/build_preparation_completion.py --check
python docs/contracts/c08-controller/check_preparation_completion.py --report
python docs/contracts/c08-controller/check_preparation_completion.py --check-report --staged
```

报告覆盖完整237表的真实cp_close来源、实际编码准备DENY/Closure、两出口应用、另一个有效HTTP/close原件反例、三类撤回及顺序、完整写集缺写和逐步异常、状态生成失败回滚、终态不可复活、保留资源占用、不可变及外键检查。原235表缺口在本轮实际复现，不以旧用例名字当证据。

原件和权威BODY是合成前提；资源用例使用未发送的取消独立hold。普通及取消在途许可集合为空，没有移除四个最终阻断来制造已发送历史。close先到的完整新组合用例、非空普通/取消传输综合历史、真实writer/消费者、IPC、并发、磁盘崩溃、NTP、设备操作未验证；SQLite内存通过不等于制品或运行批准。

剩余冻结：将新读模型/状态事件、RUN来源清单及真实提供者归并唯一SDK；真实P1计划引用及P4准备消费者；全部关闭来源与剩余消息的共享日志、AUTH/TIME、完整AdmissionSeal/Guard/预算/时间及跨库恢复。阶段0仍未关闭。
