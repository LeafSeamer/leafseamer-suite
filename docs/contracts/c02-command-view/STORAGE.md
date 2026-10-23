# 命令公开修订、取消与证据的持久化候选

状态：待审阅，`command-view-storage/0.1.0-draft.1`。本稿细化[七接口契约](README.md)，将[77表命令组合](../c08-controller/COMMAND_STORAGE.md)与[storage.sql](storage.sql)的14表组合为91表。它是设计用候选布局，不是生产迁移，不改变draft.4或IPC0.6。

已知事实：原命令表已固定终态和State修订，资源表可因迟到事实或原件撤回遮蔽旧当前投影；原HTTP候选要求完整CommandRecord与固定证据清单。以下是针对这些约束的持久化推荐，实际服务、可信提供者、磁盘耐久及设备均未实现。（来源：[command.sql](../c08-controller/command.sql)、[resource.sql](../c08-controller/resource.sql)、[command.schema.json](command.schema.json)。）

## 1. 物理映射与所有权

所有表属于Controller同一数据库和唯一writer。依次加载controller、fence、barrier-attempt、resource、command及本SQL；不重复加载原scope。事务外开启`foreign_keys`及`recursive_triggers`。线上Counter保持无前导零十进制字符串，库内排序字段使用20位补零文本，不转换为有损浮点。零用于空集合、offset和许可高水位，修订从1开始。

| 表 | 契约映射与约束 |
| --- | --- |
| cv_metadata | 原受理identity、actor、target、origin、dispatch及来源链的固定metadata；与初始公开修订双向配对 |
| cv_record | 完整CommandRecord及record_digest；同command/revision唯一，与cm_commit和State摘要配对 |
| cv_evidence | 五类EvidenceRecord及原件/视图分别存储的摘要、内容和验证记录；命令所有权不可换 |
| cv_snapshot / cv_snapshot_member | 同StateRef的固定manifest与完整有序成员；数量、双向集合差集及ordinal逐项核对 |
| cv_cancel_key | 原七元命名空间加cancelCommand/idempotency_key；摘要不是唯一键的一部分 |
| cv_cancel | 每父命令唯一取消，固定mode、CAS目标、政策和完整捕获切点 |
| cv_cancel_revision | 操作独立修订、state及future_writes；与发布它的State修订同提交 |
| cv_cancel_receipt | 原回执仅引用初始操作摘要；后来进展不改变原回执 |
| cv_cancel_deny | 精确父命令永久拒绝新普通attempt/hold/permit，不能作为设备关闭证明 |
| cv_cancel_attempt / cv_cancel_target / cv_cancel_permit | 全部已登记尝试、该设备全部登记出口世代及全部历史许可，包含已核销许可 |
| cv_cancel_commit | 取消受理审计和保护outbox，封存捕获集并校验初始回执配对 |

14表均只增，禁止UPDATE、DELETE及REPLACE覆盖。`cv_history`读取已提交修订；`cv_current`必须联接`cm_current`，不得用`max(revision)`绕过风险遮蔽；`cv_cancel_current`选择已提交操作最高修订。对外查询均在独立读取事务看已提交快照，writer不能把自身尚未COMMIT的视图用于HTTP响应。

## 2. 原子写集与摘要顺序

| 写集 | 同事务必须持久化 | 提交后动作 |
| --- | --- | --- |
| 初始受理 | 原T1全部记录、metadata、空或完整证据快照、公开revision1及cm_commit | 才返回原受理裁决；不因生成公开记录派发设备 |
| 普通状态/证据修订 | 原生命周期写集、需要新增的EvidenceRecord、完整快照和CommandRecord、cm_commit | 发布固定修订通知；GET本身不创建修订 |
| 取消受理 | 当前权限与历史namespace核对后CAS；Key/Content、固定取消、deny、完整attempt/exit/permit切点、requested/pending操作1、observe后继State及公开记录、原回执、审计/outbox | COMMIT成功才202；outbox只传播保护/查询，不自动重发设备动作 |
| 取消进展 | 可靠提供者原件、操作精确后继、必要证据、新State和完整公开修订、原状态提交审计/outbox | 查原能读新进度；原CancelReceipt不动 |
| 迟到事实/失效 | 原资源/报告事务先保守记录风险；能构造完整新State时同提交公开修订，否则当前视图暂时隐藏 | current返回503及read_current；历史仍可读，不返回旧clear冒充当前 |

取消受理捕获`ce_permit.issued_revision`的全库高水位；封存时再次核对高水位未变，三类成员各作双向差集。出口集合保守覆盖该设备所有已登记世代，不仅当前连接。一个writer串行化新许可和取消：许可先提交则必须进入cut；取消先提交则新普通许可拒绝。编码准备未知仍受已登记attempt/出口覆盖；迟到packet或report可落库，不获得新permit。

同事务先计算固定metadata及State，再计算证据视图、manifest及取消操作，最后计算完整record与原receipt。State不引用record摘要，操作只携带原CancelIdentity而不反向引用receipt，避免摘要循环。SQL保存摘要和原字节但不计算JCS；提供者必须重新核验JSON与关系，不能将非空BODY当作证明。

每个cm_commit必须已有匹配的cv_record和snapshot；新证据必须绑定尚未提交的State修订。快照精确包含该命令截至本修订的全部公开证据版本，按`(id, revision数值, kind)`排序。已经封存的快照或State不能补写成员。新证据/撤回另建修订，旧分页不受影响；超容量整体拒绝，不能截断集合。分页签名游标由HTTP层绑定固定snapshot和当前权限，不写证据序号。

## 3. 取消单调性及恢复

首次操作只能`requested/pending`，其command_state_ref引用CAS目标的后继State。操作revision精确加一，前序必须已与State提交配对；不能在同事务塞入未提交前序，再借不可见视图绕过单调检查。之后State修订必须前进，每个State最多对应一个取消进展。

`indeterminate`不能回`requested`；`confirmed/unsupported/failed/too_late`固定结论不能改写，已`closed`不回退。`confirmed`须closure和result两份验证记录；其他确定结论须result。原件真实性、时效和全出口覆盖由下述提供者负责，SQL非空检查本身不证明设备关闭。发现旧证明错误时保留原历史，追加失效及独立保护，不复活取消操作或普通许可。

原命令finished后，取消进展只能按既有observe/reconcile等规则附加事实，不改phase/outcome/terminal_revision，不清暂停锁存。原unknown即使取消confirmed仍可能unresolved；资源释放另走完整关闭、核销、Resolution及T6。OBS首闭环只支持before_dispatch_only；cooperative需要新的保护动作许可，不能复用普通命令许可或绕过终态禁发。

重启先恢复永久deny和未完成保护outbox，再允许普通受理/发送。提交前失败全部回滚，存储不可靠按既有写闸规则关闭；COMMIT结果未知先查原Key，不重建取消。COMMIT成功丢响应返回原receipt；outbox送达未知只查原保护尝试/持久ACK。新进程、连接或context不能抹去旧许可与风险。namespace关闭只阻新受理，不删除回执；当前有权查原仍须核对原namespace归属，人员退出不丢弃原worker事实。

## 4. 提供者与尚未完成的归并

| 责任 | 必须验证的输入与失败结果 |
| --- | --- |
| 身份/权限提供者 | 当前human或受信Seamer来源、精确历史namespace和设备用途；错误拒绝，不以旧grant当当前权限 |
| 公共投影提供者 | 原受理metadata、完整State/attempt历史、固定取消修订、结构化证据白名单、JCS及当前失效；不完整则不发布current |
| 取消保护提供者 | 固定父命令/政策、捕获切点、全部出口关闭、原ACK/退休证明、确定取消结果与时效；不足保持pending/indeterminate，禁止推断成功 |
| 证据提供者 | decision/release/resolution的本库原件id、revision、command及摘要；observation原会话来源和invalidation主体/保护关联；错误拒绝或追加保守保护 |
| 分页提供者 | 固定完整manifest、当前读取权限、主体/授权修订、limit及游标签名/期限；错误返回既定错误，不能切换新快照 |

SQL已对decision、release及resolution建立物理来源关联；invalidation验证同命令subject，observation与保护Ref仍由BODY承载。来源Ref与view_digest分开保存，不把白名单投影摘要当作原件摘要。合法JSON字符串也可能含秘密，真实过滤必须另验。

后续[IPC0.7候选](../c02-cancellation/README.md)已提供取消cut、ordinary/all关闭、协作执行/许可和完成证据格式；仅all关闭映射公开future_writes=closed。91表保持原普通许可布局，未假称已运行新增保护分支。剩余设计冻结项：普通/保护共享签发分配器、保护执行物理写集与closure/result原件FK；observation/失效保护原件的完整持久映射；其他三类屏障与通用保护outbox；统一SDK及权限/面板迁移、容量/留存/归档规则。该91表组合推进公开持久化缺口，不代表Controller所有表或全系统已关闭。BODY提供者的设计和实现状态分开，未定义来源链的部分仍是设计缺口。

## 5. 故障验收与复验

[check_storage.py](check_storage.py)仅连接`:memory:`。预期成员人工列出，不从待测视图生成；缺写和逐写主动异常核对全部91表。396项检查包括初始公开修订、排队/在途取消及进展、证据同提交，CAS/高水位/回执错配，禁止新增普通许可，未提交前序，固定终态、未知后确认，完整快照/排序/跨命令/旧页冻结，三类原件关联和撤回遮蔽，以及14表实际非空时的UPDATE/DELETE/REPLACE拒绝。

报告保留“非空合成BODY可通过SQL”的限制反证。全部检查通过不证明真实权限、JCS提供者、取消发送、进程崩溃、线程竞争、WAL、磁盘断电或设备效果；这些运行检查均未执行。实际SQLite版本记录于报告，不当作产品引擎批准。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-command-view/check_storage.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c02-command-view/check_storage.py --check-report --staged
```
