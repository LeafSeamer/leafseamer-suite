# 完整恢复链的时间提供者来源

本候选基于已有模型的分析与推荐，approved=false。它将[30表提供者采用](../df03-provider/README.md)接到原276表恢复链，形成306表Controller离线组合；原[290表时间来源](OPEN_TIME_SOURCE.md)保留历史，不修改其输入接口或报告。当前生产业务未实现，本候选不签发OPEN或设备许可。

## 1. 直接读取同库完整来源

[读取器](open_provider_source_model.py)不接受调用方expected_provider_domain。它从当前ts_head读取封存State，以其runtime_binding_ref查唯一tp_adoption，重建完整ProviderRuntime、Channel、Configuration、初始State、固定存储身份和四份bootstrap交付正文，再核完整Domain、配置引用及时间代次。

随后沿用完整恢复、非空运行／命令拒绝快照及worker启动原件读取，要求资源快照首次登记的time_snapshot_id与当前确定性下界精确一致。worker与time_provider保留独立member_boot_id及运行Ref；仅共享authority/database和完整时钟域身份，不能把worker的Ref冒充提供者。

新增返回的originals.time_provider_adoption与originals.time_state供审阅、查原及后续writer复核，time_source_provenance只表达来源分支，不是新的发送许可字段。不把这些辅助字段直接加入已批准API或IPC。

## 2. 提供者资格与拒绝下界分离

| 分支 | 读取条件 | 能证明的内容 |
| --- | --- | --- |
| current_adoption | 现行State为collecting／qualified，完整采用仍有效且Binding精确相等 | 当前SQLite快照中的采用关联，不证明OS活性、当前批准或UTC可用 |
| withdrawn_floor_only | 现行State为unavailable；撤回、完整Invalidation、同一commit、后继Binding、STOP意图及交付正文逐项匹配 | 保留历史来源和提高的minimum_time_generation，仅用于拒绝旧时间资格 |

两个分支都核source/profile/policy/approval引用及完整Domain等于采用时原件，时间代次不得低于初始值。撤回分支还要求Invalidation.old_binding等于原采用Binding，当前State正是该撤回产生的后继；不接受无采用记录、不同域、无撤回原件或任意大代次替代证据。

提供者撤回后，df03-provider.current继续拒绝。新的floor_source允许读取已封存的拒绝元数据，但不会将历史提供者复活；新采样和UTC资格仍关闭。无需UTC的即时控制可以在重新选择该下界并通过全部既有恢复／授权／出口条件后继续，不能因NTP不可用而无条件禁用，也不能绕过设备保护。本轮只验证恢复前态读取，不证明完整重新开放或即时控制实际执行。

撤回前登记的资源快照因time_snapshot_id已过时而拒绝；在撤回完成后首次登记的新恢复可选择提高后的下界。禁止读取器覆写旧快照、补齐占位值或偷偷替换Domain。接收端若已保留更高下界，拒绝回退。

## 3. 事务和故障时序

完整来源须在最终writer拥有的同一BEGIN IMMEDIATE事务中重读，再执行后续发送准入写集。函数只能检查处于事务中，不能从SQLite连接标志证明调用者持有正确writer资格。WAL旧读事务可能在另一连接完成撤回后继续看见先前采用，这不是最终资格；释放旧读快照后重新取得writer并重读，必须拒绝旧恢复选择。

| 时序 | 必须结果 |
| --- | --- |
| 采用已提交，恢复首次选择当前时间ID | 完整worker／provider原件和非空拒绝来源可共同读取，设备仍protected |
| 旧恢复已选择时间ID，随后提供者撤回 | 旧恢复读取因ID过时拒绝，不改历史 |
| 撤回先提交，再首次登记恢复 | 可读取unavailable的提高后下界，无Anchor且不授UTC |
| 撤回十步任一步主动异常 | 全306表回滚，原恢复引用保持有效 |
| WAL读者持旧快照，另一连接撤回提交 | 旧读仍可见先前采用；最终writer重读必须拒绝旧选择 |
| 已保留更高时间代次 | 拒绝下界回退 |
| 首次持久时注入错误采用Ref、Invalidation Ref、原因或存储身份并重算摘要 | 完整关联读取仍拒绝，不以摘要一致替代原件关系 |

## 4. 验证与剩余接线

[检查器](check_open_provider_source.py)从真实完整合成恢复夹具取得其监督数据库，在该域首次登记独立time_provider意图、挑战、观察和回执，再执行完整采用。所有身份在首次写入前选定，不替换已有worker、恢复或监督历史。报告见[验收结果](open-provider-source-report.json)。

原采集布局本轮实际并入306表，但没有采样、报告入站或真实Channel交换；核心启动Ref、间隔、配置批准及TIME保护Ref仍为显式合成提供者。监督读取后退役与核心采用的竞争、当前授权来源、TIME保护对全部依赖者的原子传播、实际OPEN／ACK／Ready及最终许可仍未完成。磁盘断电、跨进程故障和设备未验，阶段0未关闭。
