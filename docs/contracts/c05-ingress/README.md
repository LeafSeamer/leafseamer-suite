# 普通事件摄取候选

状态：设计候选，`runtime_approved=false`。版本`event-ingress/0.1.0-draft.1`，附属存储版本`ingress-storage/0.1.0-draft.1`。不替换已确认draft.4／IPC0.3，也不切换SDK权威。规范来源为[C05第12节](../../rebirth-c05-event-sync-design.md)、[C04第14节](../../rebirth-c04-automation-design.md)、[DF04第14节](../../rebirth-df04-storage-design.md)。

## 格式与引用

[build_contracts.py](build_contracts.py)是本候选唯一格式源，生成[Schema](ingress.schema.json)和[OpenAPI](ingress.openapi.json)。SourceBindingRef从[DF06](../df06/internal-trust.schema.json)取原结构。所有具名对象关闭额外字段；根禁止直接实例校验，必须选择`$defs`。计数用规范U20字符串；优先级为int32，不能把U20转为JS Number或SQLite INTEGER。

| 模型 | 必须绑定的内容 |
| --- | --- |
| Origin／SubmitEvent | 来源五元组、DF06绑定、event_id、source_sequence、批准Schema引用与payload；投递和年龄证据只属于传输，不接受provider自报live |
| InboxContent／FirstObservation | 固定来源正文和原摘要、首次受信接收clock/tick及投递/年龄引用；后到规范报文不延寿 |
| ReceiveCursor／RunProgress | authority/database scope、ingest_epoch、receive_sequence；独立ingest_revision与基线引用，不把摄取进度冒充run生命周期变化 |
| MatchSet | source_key、registry_revision、按run_id排序的完整targets；每项含definition/version、artifact及trigger_binding |
| EvaluationSnapshot | run与slot前态、ingest前态、业务状态、观察与输入引用、完整转换求值集合；规则结果和转换集合不可混用 |
| TriggerDecision | 固定输入/匹配集/快照引用、前后修订、结果、所选转换及预分配execution_id；仅accepted创建执行 |
| ExecutionPlanBinding | 决定、产物、游标、执行绑定与完整计划引用、步骤数及sealed；不是执行许可 |
| IngressCommit／CommittedBatch | inbox、匹配集和全部决定的清单与摘要、来源前后修订、汇总状态及通知身份；内部批次包含固定快照/执行绑定 |
| ProviderReceipt／LookupResult | 本事件回执、原身份摘要及duplicate；不包含run、全局游标或决定数量。查询可返回not_found、historically_closed、indeterminate，均不授权重触发 |

Ref的kind、scope、对象ID、revision、digest必须同时符合被引用对象；合法Ref不证明对象存在、当前授权或来源年龄。QualifiedValue必须用当前批准Schema二次校验。参考检查只核验明确列出的关系，不能推广为完整内部授权验证。

## 摘要投影与接口

统一使用`sha256:`前缀与RFC8785规范字节。除被明确指定的摘要字段，不递归删除同名业务键。

1. `origin_digest=JCS(Origin)`；排除的投递/年龄信息本就不在Origin中。
2. `content_digest=JCS(InboxContent去除顶层content_digest)`；不反向包含commit。
3. `targets_digest=JCS(targets)`，targets按run_id排序；本版ID仅ASCII。MatchSet引用的digest覆盖完整MatchSet（含targets_digest），revision取registry_revision。
4. `snapshot_digest`、`decision_digest`分别覆盖对象去除自己的顶层摘要字段；引用固定inbox和match_set。snapshot与decision为不可变单版对象，Ref revision固定1。
5. `decision_set_digest=JCS([{run_id,decision_id,decision_digest},…])`，按run_id排序；`commit_digest`覆盖IngressCommit去除自身摘要。execution预分配ID进入decision，但execution摘要不反向进入decision。
6. 通知预分配ID进入commit，通知载荷引用commit_id；实际通知载荷与审计正文的类型及摘要还需归并。

| 操作 | 认证／权限 | 返回边界 |
| --- | --- | --- |
| POST `/api/v1/providers/{provider_id}/events` | ProviderBearer + source.event.submit；服务端核对路径provider、当前来源注册及规范通道 | 首次可靠提交202；已有原提交200。未提交不能返回committed |
| POST同路径`/lookup` | ProviderBearer + source.event.read；当前调用者先鉴权 | 只读原身份；不分配新游标，不自动重新受理 |
| GET `/internal/ingress/commits/{commit_id}` | mTLS + ingress.internal.read及对象scope授权 | 内部完整账本，不可凭provider token读取 |

三接口均要求精确`X-LeafSeamer-Contract`版本头，所有响应no-store。认证和版本选择目前仅机器声明；未运行服务器中间件。duplicate是响应投影，不能写回固定回执或改变原决定；receipt_id必须为不泄露全局序列的不透明身份。共用OpenAPI包含内部components，权限边界靠服务器；provider响应引用闭包检查只证明静态类型隔离。

## SQLite原子写集

[ingress.sql](ingress.sql)在原[recovery.sql](../c04-storage/recovery.sql)16表及[dispatch.sql](../c04-storage/dispatch.sql)9表之后加载，新增15表，共40表。它是局部设计布局，不是产品迁移或完整Seamer数据库。

新增表为ingress_storage_profile、ingest_epoch、ingress_source、ingress_registry、ingress_listener、ingress_inbox、ingress_commit、ingress_target、ingress_snapshot、ingress_decision、ingress_execution、run_ingest_progress、ingress_notification、ingress_run_audit、ingress_charge。

同一短writer事务：固定来源前态和完整监听集合 → 分配批次/决定身份 → 每个目标保存快照与决定 → accepted写来源映射、execution、PLAN审计/outbox、全部步骤及状态并封存 → 更新各run及独立摄取进度 → 来源前沿/epoch游标/inbox升级 → 全批通知/容量记录/逐run审计 → 检查完整集合及投影后封存 → COMMIT。任何写语句后异常都回滚全部40表。单个run的no_match或抑制不使其他合格run失败。

本版采用独立`ingress_run_audit`保存INGRESS_RUN子账本，不修改旧transaction_record.phase枚举；accepted的PLAN仍使用旧审计/outbox表。数据库级根不伪造run_id。ingress_execution双向绑定原execution和决定，加载本附属布局后禁止裸trigger执行；后续恢复execution仍遵循原恢复路径。

封存必须显式检查：来源投影、当前epoch水位、监听集与target双向差集、决定覆盖、进度投影、accepted执行/计划/活动槽、保护结果暂停投影，以及通知、容量行和逐run审计。**不能仅依赖延迟外键声明判断完整性。**本轮参考引擎曾观察到缺通知行但COMMIT成功、之后foreign_key_check报错；新增显式封存检查后，该遗漏在封存时拒绝。此观察仅针对本组合与参考引擎，不据此推断其他SQLite版本行为。正式writer验收还须包含目标驱动与引擎的约束反例。

SQL约束与writer责任分开：SQL验证U20词法、单调水位、不可变身份、不可撤销锁存、集合和必要投影；精确加一、权威索引变更及revision同事务、当前授权/时效、全部AST和选中计划内容、预算实际计费、BODY/JCS一致性须由可信writer核验。参考SQL中的BODY为合成占位，不等于JSON到存储的端到端映射。SQL不能证明锚的时间样本来自COMMIT之后，须由执行流程及运行验收证明。

## 复验与剩余冻结

在Suite根目录运行：

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-ingress/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-ingress/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-ingress/check_contracts.py --check-report
```

[check_contracts.py](check_contracts.py)核验生成字节、Schema/OpenAPI、接受集、人工正反例、重新摘要后的错误关联、三值裁决、provider闭包和大整数；再调用[check_storage.py](check_storage.py)运行固定`:memory:`中的写集及主动异常。报告绑定13份原字节输入，`--check-report --staged`只比暂存区摘要，不重新执行测试。报告不在旧顶层十份清单中。

本轮覆盖EN01/02/03/05/07/08/09/10/11/12/13/15/16/19/23中的部分结构、串行模型或SQL约束，不宣称完整EN验收。busy等决定由夹具提供，未运行真实仲裁。真实线程竞争、磁盘掉电、生产WAL、认证/来源年龄、网络ACK、设备动作均未验；SQLite3.50.4是参考引擎，不是批准产品依赖。

仍需冻结：来源gap/冲突/关闭与完整依赖保护事务、pending超时/GC/floor及跨备份恢复、保护锁存本体与run投影、当前身份和时钟提供者、实际容量预算及writer超时传播、完整求值输入与计划内容、原子JSON→SQL映射、provider固定回执的独立持久布局、事件与edge/budget/场次的统一顺序、SDK/HTTP/WS/IPC总体归并。阶段0继续未关闭。
