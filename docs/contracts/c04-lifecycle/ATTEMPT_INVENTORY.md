# 固定attempt库存持久化候选

状态：`approved=false`。在[独立原件映射](ATTEMPT_PROJECTION.md)上追加[库存表与守卫](attempt-inventory.sql)，生成[238表组合](controller-attempt-inventory.sql)，提供[存储适配器](attempt_inventory_model.py)、[检查](check_attempt_inventory.py)及[报告](attempt-inventory-report.json)。没有修改旧组合DDL或业务服务。

## 事实与设计分界

原reader已有本地attempt_source接口，但上一轮来源仍由测试回调提供，固定库存并未保存。既有cm_report_receipt分别记录stored_report_id与worker_report_id，并以worker_boot_id、ipc_session_id、worker_report_id去重；两种报告ID不能视为同一个字段。本轮据此将投影来源分开记录本地report_id和原worker_report_id，不改变公共AttemptView。（来源：[命令存储](../c08-controller/command.sql)、[独立映射器](attempt_projection_model.py)。）

本稿是持久化设计和参考实现。完整性采集与固定历史读取使用实际SQLite表；原件资格、裁决有效性、脱敏和TIME投影仍依赖显式合成可信提供者。数据库保存这些证明输入不等于证明提供者已实现，非空JSON不授设备写权。

## 写集与封存

av_snapshot以(command_id, revision)唯一，关联同修订cm_revision、cv_record及cm_commit，保存inventory、结果选择、完整projection和provider四份正文及独立摘要。正文保持不可变，禁止UPDATE、DELETE、REPLACE覆盖；已公开修订不能补写库存。无attempt的受理历史不强制新建空库存。

唯一writer先保存本轮State、attempt关系和证据原件，再从实际库采集完整库存，重建公开attempts，保存公开快照及CommandRecord，然后保存av_snapshot，内部复核完整记录，最后写cm_commit并提交。任一步失败整笔回滚。最后cm_commit守卫再对attempt、packet、permit、报告、编码指派和公开证据作双向集合核对；采集之后增加的原件不能被旧清单遗漏。Schema/JCS和复杂正文关系由writer复核，SQL集合检查不能代替这些语义检查。

| 库存部分 | 本库实际来源 |
|---|---|
| State与attempt | cm_revision、cm_revision_attempt、cm_attempt和ce_attempt；prepared必须为原prepare修订 |
| packets | 同修订attempt关联的全部ce_packet，正文身份与packet/attempt/exit/primitive列一致 |
| assignments与exits | 已登记ordinary ep_request及其ep_request_commit，合并packet出口；包含尚未产出packet的编码指派，ce_exit保留原八字段身份 |
| transmissions | ce_permit完整TransmissionPermit及ce_transmission_commit的原intent，核列与正文关系；不把历史许可当当前发送资格 |
| reports | ce_report原正文及cm_report_receipt原会话、线路ID、正文摘要与归属修订；本地ID用于固定引用，线路ID只在原会话中唯一 |
| evidence | 截至该修订的完整cv_evidence；与同版公开证据快照成员核对，按原件ID与数值revision排序 |
| 有效性与TIME | 当次可信provider提供并绑定scope和StateRef；原件、选择、投影摘要一并封存，不能由HTTP传布尔值声明有效 |

成员数量在查询时限额，完整库存另核字节上限，四份正文合计另受max_bundle_bytes约束，超额全事务拒绝，不截断或省略原件。空集合字段仍须显式存在，提交点同时核对成员数量与双向集合，不能靠重复成员绕过差集。当前上限是参考包络，正式CostManifest、层级预留和GC仍未完成，不能以表中16 MiB结构上限声称生产容量已获批准。

## 历史读取

read/page适配器在已有读取事务内加载指定av_snapshot，核四份摘要，以固定ID重新读取不可变原件并核对正文，再交独立映射器重建公开attempts。packet、permit、报告及编码指派使用已封存ID集合，不能重新枚举最新全集污染旧修订；证据用不可变first_state_revision界定。无论最新worker如何变化，旧State不借新会话补字段。

来源接口禁止在事务外调用。公共读取沿用当前认证、授权、设备/来源范围及响应前复核；历史不因旧grant撤销而被删除，也不因此取得当前写权。内部writer可以在提交前验证库存，但公共reader仍拒绝writer事务响应。

## 故障时序与验收范围

- 采集或封存后崩溃、漏写库存或状态提交：关系及提交守卫拒绝不完整事务，参考检查逐写注入异常并核全库回滚。没有据此声称验证了进程断电或真实WAL恢复。
- 新证据另建公开修订：旧库存字节与旧record保持原样，新修订读取新证据，GET不补写库存。
- 新worker登记但未指派到旧attempt：旧投影不能增加该出口或借其会话替代原会话。
- 本地报告ID不同、线路ID相同：不同worker/IPC会话可以分别存在；同会话线路ID重复拒绝，不能靠改本地ID重复记账。
- 缺资格、错原件或超容量：不返回半份记录，不隐式回退到另一个修订，不把合成资格当成实际服务验收。

97项检查通过。实际238表正例覆盖prepared与后继观察修订、独立库存读取、分页期间新修订以及真实持久的合成decision证据；新出口登记同时履行原关闭义务与零准备cut。完整TransmissionPermit另有列/原intent/出口会话映射正反例，但不是数据库发送链。完整packet/permit/报告生产链未在此组合库跑通。最终发送守卫保持，未删除触发器或借手工导入伪造成功链。全部生命周期writer、真实AUTH/TIME资格、最终AdmissionSeal、保护传播与成本/GC、SDK/HTTP和真实设备验收仍待完成，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_attempt_inventory.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_attempt_inventory.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_attempt_inventory.py --check-report
```
