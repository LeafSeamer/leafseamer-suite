# 命令修订、固定终态与资源联接候选

状态：待审阅。`command.sql`在[66表资源组合](RESOURCE_STORAGE.md)之后增加11表，形成77表设计实验。本文件是持久化映射，不是生产迁移或完整公共CommandRecord，不改变已确认draft.4。124项生命周期快照、272项资源实验与本组合320项检查分别记账。

后续[命令HTTP候选](../c02-command-view/README.md)补齐完整公开投影、取消及证据七接口，并修正本SQL中Resolution枚举：与既有Schema一致采用succeeded/failed/cancelled/not_sent，未知观察不伪装成确定核对。新增4项检查只证明枚举和固定终态；取消/公开修订/证据索引DDL仍未加入77表。

## 1. 已知约束与本轮补充

已确认的固定终态、独立Resolution、手动优先和暂停锁存继续适用。现有资源层已经独立核验全部历史传输，但资源释放不能单独把unknown对外改成clear，也不能越过命令层放行下一个设备写。（来源：[生命周期](LIFECYCLE.md)、[资源存储](RESOURCE_STORAGE.md)。）

本轮补充两个**内部存储操作候选**：`prepare`登记编码准备的attempt并发布仍queued的后继State；`observe`接收报告或附加历史事实而不改变phase/outcome。两者不能套用旧Transition.kind接受集，须在下一统一SDK候选显式加入和验证；本轮不暗改旧Schema。prepare不是dispatch，不获取hold，也不能把编码成功当设备发送。

## 2. 物理关系

| 表 | 内容与提交关系 |
| --- | --- |
| cm_policy | 同T1固定完成政策、required_completion、retry政策、max_attempts及原截止；由command关联原受理，不复制可变裁决 |
| cm_validation | 同command的可信转换/完成/失败/取消/核对提供者原件；subject身份和摘要、固定policy、来源及提供者引用 |
| cm_decision | 固定kind、achieved、effect、retry政策或resolved_outcome；与相同命令、政策及subject的提供者绑定 |
| cm_attempt | ce_attempt的命令内顺序及首次prepare修订；上限16，初次计入；旧attempt释放且retry状态成立后才允许下一attempt |
| cm_revision | U20严格后继、previous revision/digest、操作身份、完整transition_digest与独立state_digest、State字段、终态锚、Resolution和decision；只增且与commit双向配对 |
| cm_revision_attempt | 每次修订的全部已登记attempt，双向差集核对；顺序从cm_attempt.ordinal投影 |
| cm_revision_release | 只增的已发布释放引用；旧引用不能被下一修订丢弃，clear还要逐hold核当前有效释放 |
| cm_resolution | 独立U20序号、原terminal_revision、新published_revision、resolved_outcome及resolver；只能由reconcile修订选中 |
| cm_report_receipt | `(worker_boot_id, ipc_session_id, worker_report_id)`为接收身份；内部stored_report_id指向ce_report，绑定同命令及本次State修订 |
| cm_commit | 同库审计和outbox、操作身份与State修订；提交后才可发送REPORT_STORED |
| cm_dispatch_binding | 新hold与本次dispatch修订双向检查，不能让T2仅写hold/permit却漏掉命令状态 |

线上十进制字符串仍不补零；数据库延续U20补零排序。State和Resolution各自精确加一，使用两段十位整数求后继，避免将U20整体CAST为SQLite整数。报告原始身份不等于内部存储ID：不同worker/IPC可使用相同本地report_id；重复原身份同摘要只查原结果，异摘要为协议冲突。查询前先验证历史出口/当前读权限，不能因人员退出丢失已知发送事实。

## 3. 写集

**T1受理**：在原ca_commit之前保存cm_policy、初始revision=1、可信转换原件和cm_commit；缺一不能提交。初始queued/pending/not_sent/clear，没有终态或Resolution。原受理Ref保持不变。

**编码准备**：同事务保存cm_attempt、ce_attempt及prepare修订和commit；编码返回的packet可以随后独立登记，失败返回也不虚构packet。完整attempt集合同步发布，未派发不占设备。允许的重试必须先有独立安全失败/释放证明和retry修订，再登记新的attempt；登记不刷新原截止。

**T2发送**：资源准入先读取命令当前queued、未锁存且资源clear；其他曾持有该设备的命令若仍unresolved也阻止准入，即使资源子域已有释放记录。hold/许可/传输提交及dispatch_binding与dispatching修订同事务；提交后才允许唯一发送出口消费许可。首许可在事务内看到的新hold会暂时遮蔽旧clear投影，SQL使用同事务的待提交dispatch关联识别这一情况；不得将该例外用于终态或协议重传。

**T6报告**：先登记原报告身份，再写ce_report原件及派生保护、decision/Resolution/释放（需要时）、后继State/全部attempt与累计释放引用、审计/outbox。报告只能绑定未提交的本次修订；不能先确认报告、后补State。重复报告查原commit，不重新发送设备命令。

**核对与释放**：先保存同command的resolution decision与独立Resolution，再由reconcile修订引用；Resolution指向该修订且修订必须选择它，禁止孤立解释。unknown可以在核对与独立释放同事务后clear，但phase/outcome/terminal_revision不变、暂停锁存不清。也可先核对而仍unresolved，随后release修订清理；succeeded同样不自动clear。

所有BODY、来源时效、JCS及精确业务守卫仍需真实提供者。SQL验证结构和物理关联，不能把一条伪造`cm_validation`变成合法授权。转换提供者必须使用固定政策、完整历史效果及原时钟域/截止，核验safe_failure、取消、block/expire的未发和关闭证明；本轮没有以SQLite wall clock取代NTP设计。

转换提供者的subject_digest绑定完整转换内容，至少包括原StateRef、kind、after State、decision/Resolution和释放引用、完整attempt/资源cut以及审计/outbox引用；只排除转换自身摘要字段，保留嵌套内容。state_digest另对完整State计算，用于下一次CAS，不能将二者混用。物理表的投影字段须由同一已验证内容导出；SQL中两个摘要相同的合成夹具不证明实际JCS或字段一致性。

## 4. 当前投影与迟到保护

`cm_latest`是最高已提交不可变State；`cm_current`只暴露资源与保护仍相容的当前版本。迟到屏障ACK或证明撤回可能先独立持久化：若旧clear与新风险矛盾，或新设备保护尚未反映为暂停锁存，当前投影暂不可发布，历史快照仍保留。writer必须优先补protect/observe修订，不能动态改写旧State的字段和摘要。

下一统一HTTP候选应把该短暂情况明确为`503 state_projection_pending`及可重查提示，不返回旧clear冒充当前状态，不允许GUI自动补发写操作。可靠事件只发布已提交后继修订；临时保护由独立通路优先广播。此错误模型、公共CommandRecord投影和通用保护outbox仍须同版归并。

正常取消、结束及超时后，即使hold仍未关闭，也禁止新permit；已有在途只按证据核对。永久关闭旧hold、终态禁止重试、Seamer暂停锁存是三条独立条件。完成证据的层级必须达到固定required_completion；packet ACK、同值观察、当前连接或提供者JSON形状不构成效果证明。

transport只消费当前attempt的进入传输事实；同command先前已释放attempt的in_flight历史不能推进新attempt。有限快照模型与本SQL均补充此检查及正反例，不改变此前合法发送证据的保存。

## 5. 验证与剩余冻结事项

[check_command.py](check_command.py)使用77表内存组合与人工预期，检查：

- T1、prepare、T2、报告和T6逐写缺失与主动异常的全表回滚。
- 固定终态、原terminal_revision、独立Resolution修订、CAS与暂停锁存。
- 成功仍unresolved、低完成层级拒绝、unknown缺Resolution不能clear。
- 资源子域已释放但命令状态未提交时，另一命令仍不可取得hold。
- 原报告身份/出口错配、重复身份、查原不再发，以及不可变记录保护。
- 显式retry政策与预算、同command新attempt、完整历史效果/释放引用保留。
- 迟到失效使旧当前clear不可发布，随后保护修订恢复保守投影。

可信提供者和BODY仍为夹具；这里不证明真实并发、磁盘/WAL故障、IPC、REPORT_STORED网络时点或设备效果。原时间/权限提供者、全部图形化参数验证及完整CommandRecord投影均须实现后按各自计划验证。

仍需实施前收敛：将prepare/observe及state_projection_pending纳入统一SDK；完成证据原件撤回与命令保护的统一索引；通用保护outbox及其他屏障DDL；命令GET/取消/证据HTTP和转交关联。已有固定终态/资源物理关系不再列为“尚无DDL”。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_command.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_command.py --check-report --staged
```
