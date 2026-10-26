# 完整恢复前态的同库时间来源

本候选将[时间下界来源](../df03-service/GATE_SNAPSHOT_SOURCE.md)接到[命令快照](COMMAND_SNAPSHOT.md)之后，复用现行IPC字段，`approved=false`。Controller原276表与时间存储14表组合为290表；不是完整采集器27表组合或生产迁移，不解除最终发送阻断。

## 1. 关联契约

`open_time_source_model.for_open(db,recovery_id,fence_id,now,expected_provider_domain,retained)`必须在调用者事务内执行，依次取得完整恢复/控制/资源/换闸、运行拒绝和命令拒绝原件，再读取完整worker RuntimeExitBinding，最后从同一库当前时间State重建确定性GateSnapshot。

资源快照持久`time_snapshot_id`必须等于重建快照ID。来源在恢复快照**首次写入之前**选择并登记，不允许把已有`pending.time`改写成新ID，或在读侧自动用最新ID替换错误历史。按具名算法生成的ID包含完整Domain和State Ref，因此仅相同time_generation不够；State更新同样使旧选择失效。

worker启动原件重新核Schema、自摘要、物理出口列、scope、启动意图、准入回执及共享clock_domain_id/descriptor_digest。提供者Domain保持独立身份，两者公共scope/时基必须一致。`expected_provider_domain`仍是可信监督解析器的输入契约；本轮测试显式使用合成提供者Ref，不宣称已经有实际time_provider启动原件或当前活性证明。

返回值新增`reference_time_snapshot`和`originals.worker_runtime`，保留原有完整来源与控制/闸前态。它不是OpenProposal、GateAccess、ACK或ReadyCommit；不消除授权来源缺口，也不把资源恢复完成视为已允许发送。

## 2. 时序与原子性边界

| 顺序 | 必须结果 |
|---|---|
| 时间State封存 → 恢复选择该快照 → 同库OPEN前态读取 | 精确返回已登记的时间快照，控制仍protected、闸仍fenced |
| 恢复选择 → 时间失效提交 → OPEN前态读取 | 拒绝旧time_snapshot_id，即使原资源恢复和命令拒绝快照仍合法 |
| 时间失效任一步异常 → 整个失效事务回滚 | 全290表保持原值；原时间来源仍可读，不留下半个head或新Binding |
| 失效先发生 → 新恢复首次选择unavailable State | 带提高的floor进入前态，Anchor为空；不能由此取得UTC资格 |
| WAL读事务A建立旧快照 → writer B提交失效 → A继续读 | A可能仍返回旧前态；这是旧读事务的事实，不是实时资格 |
| A结束旧读事务 → 最终writer事务重新读取 | 必须拒绝旧时间选择，不能沿用上次查询结果 |

故障轨迹不通过关闭WAL、删日志或将SQL读结果标成实时布尔值解决。首期同一Controller writer负责时间State和最终OPEN相关记账；消费者必须在真正的最终事务中调用联合读取器。这个纯读取函数不能识别所有调用方是否持有正确的最终写锁，也不能提供数据库提交之外的OS实时性，实际writer和监督闭锁仍须联接。

恢复选择本身可以引用之后过时的历史快照；最终OPEN不得采用它。当前恢复写集不因为本轮实验就获得新的TIME原子保护能力。时间Invalidation与实际设备保护cut、完整库存及outbox的同事务配对仍按DF03第17节补齐；测试中的保护Ref是合成前提，不能当设备已关闭证明。

## 3. 验证与剩余冻结项

[检查器](check_open_time_source.py)使用完整跨域取消准备与恢复路径作为种子，运行/命令拒绝快照均非空；时间State从collecting开始，无原始采样时不虚构qualified。另一个正例在恢复前提交unavailable State。专项包含290表真实组合、来源精确绑定、占位引用拒绝、完整worker原件、8个逐写故障全库回滚、失效后查原，以及隔离临时SQLite文件上两条真实连接的WAL旧快照反例和最终writer重读拒绝。

[报告](open-time-source-report.json)分别标记已验的同库读取、WAL边界和未验的真实提供者、TIME保护原子性、完整OPEN及设备行为。上一轮48项时间元数据检查仍覆盖qualified/Anchor及Invalidation错绑，本轮不复制另一套来源实现。局部加载器改用按文件定位的唯一模块名，避免完整组合导入时误用同名`reference_model`；原字段和算法不变。

下一步必须完成时间提供者完整运行绑定/当前资格、采集与批准原件的完整writer、TIME保护同库seal，随后与授权来源一起生成完整OpenProposal/Dispatch/ACK/Adoption及最终发送许可。上述项目未完成前，本读取器只能作为设计验证组件，不应接入真实直播发送出口。
