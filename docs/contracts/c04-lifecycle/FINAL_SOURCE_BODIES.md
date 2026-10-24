# 最终来源的完整存储正文

状态：内部候选，`approved=false`。在[资源关系解析](FINAL_RESOURCE_SOURCE.md)上增加[具名Schema](final-source-bodies.schema.json)、[生成器](build_final_source_bodies.py)、[正文核验](final_source_bodies_model.py)和[检查器](check_final_source_bodies.py)。不变更公开HTTP/IPC版本及既有DDL。

## 已知事实与方案

上一候选可核对实际行、归属外键和风险全集，但控制、Ownership及资源快照的BLOB列仍可保存合成占位正文；非空正文及digest列不能证明字段、摘要和来源一致。Ownership已经有完整候选定义，控制和快照的物理字段则尚未形成同一完整正文。（来源：[资源来源说明](FINAL_RESOURCE_SOURCE.md)、[Ownership定义](../c08-controller/hold-ownership.schema.json)、[开放存储](../c08-controller/open-storage.sql)。）

本项复用原Ownership Schema，增加内部存储正文及独立来源回执格式。每种持久正文必须是JCS规范字节，拒绝重复键、非有限JSON数值、额外字段及超16MiB正文；先验证Schema，再排除本对象顶层摘要字段计算摘要，与正文和SQL摘要列同时对账。之后从物理行重建全部业务字段，拒绝“正文和摘要一致但与列不符”。

## 具名格式

| 对象 | 对账与引用 |
| --- | --- |
| ControlStorageRecord / control-storage-body/1 | 绑定ct_state全部控制状态字段及ct_change的scope、设备、kind、运行域和采样tick；record_digest自摘要。与公开ControlRecord分开，不更改公开格式 |
| OwnershipReceipt / ownership-source/1 | source_id/revision、provider_id、sampled/expires及完整OwnershipContent；receipt_digest对应ow_source.source_digest。content不包含未来OwnershipRef，避免摘要环 |
| Ownership | 沿用hold-ownership/0.1.0-draft.1；完整identity、hold、控制、运行域和acquired与来源回执相同；source_receipt_ref精确指向已验证回执 |
| ResourceSafetyCut / resource-safety-cut/1 | 从scope、设备和go_hazard指定revision读取实际head；零代次必须无head，非零必须有对应行。Ref id由scope/设备确定，revision及摘要覆盖实际切点，不接受调用者替填 |
| ResourceSnapshotRecord / resource-snapshot-body/1 | 绑定完整出口、控制授权及状态Ref、安全切点Ref、所有来源ID、时窗、provider_id和完整已排序hold观察；evidence_digest对应go_snapshot.evidence_digest |

所有计数仍为严格十进制字符串，不转浮点。Snapshot中的hold/owner/原控制Ref从实际归属与成员行读取，逐项核验Owner完整正文及回执；列表排序固定按hold_id，重复成员拒绝。历史快照使用其实际safety_revision读取历史cut；最终采用时另要求前态、后态与当前hazard切点相同。

`read`先验证当前及授权控制原件、目标Ownership和完整ExecutionIdentity，再验证前后资源快照，随后调用原关系解析器。它生成control、ownership、resource_before、resource_after和resource_safety五种投影。`verify`逐项核对投影和Seal.inputs，返回`stored_bodies_and_relationships_valid_requires_current_providers`。

## 明确的验证范围

正确自摘要不证明签发者授权。provider_id仍须由本地可信提供者解析，不能凭正文声称的名称信任它。本轮没有签名或真实身份验证，也没有把历史来源回执当成本次授权。ResourceSafetyCut证明本库hazard行的精确身份与版本，不证明其上游风险分类来源真实；cr_hold自身正文、完整控制授权决定和其他最终来源仍需各自核验。

测试在创建合成fixture时生成新正文，并让相关外键引用使用实际新摘要；没有更新历史行、移除守卫或修改既有生成SQL。新严格路径直接拒绝旧占位正文，不隐式补齐它。完整242表普通编码链验证了真实存储的完整控制和空资源正文；非空Ownership、快照及五角色解析使用182表既有子域。完整242表hold/Ownership/T2正向事务仍未执行，不能混淆两者。

验收包括具名Schema、重复键、非规范字节、列摘要错配、完整ExecutionIdentity换摘要、重算投影后的替换攻击，以及实际保存错误snapshot正文并重算digest仍被列对账拒绝。所有Controller最终issue仍为零，四个临时最终签发阻断保持。

后续须继续接通当前授权、能力参数、GateAccess、Guard、逐传输预算、时间及拒绝账本等来源，组装完整普通与取消T2，再验证提交未知、入流前复核、worker一次消费和SEND_REPORT。阶段0未完成。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_final_source_bodies.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_source_bodies.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_source_bodies.py --check-report
```
