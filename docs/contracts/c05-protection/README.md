# 来源保护与运行代次屏障候选

状态：待审阅设计候选，批准为false。权威说明是[C05第14节](../../rebirth-c05-event-sync-design.md#14-来源失效完整依赖保护与恢复门槛)、[C04](../../rebirth-c04-automation-design.md)及[DF04](../../rebirth-df04-storage-design.md)。本目录补普通摄取失败后的保护和恢复关联，不改变draft.4／IPC0.3，不实现服务或设备控制。

后续[HTTP与21帧IPC归并候选](PROTOCOL.md)已连接运行身份、面板路径、拒绝快照与两个保护操作，使用独立0.2／IPC0.5版本和报告。本页原0.1模型及131项参考检查保持原范围；后续归并的排序及每目标容量修订不能倒写成原包络已经支持。

[build_contracts.py](build_contracts.py)生成[protection.schema.json](protection.schema.json)和[run-fence.schema.json](run-fence.schema.json)，前者为`source-protection/0.1.0-draft.1`局部模型库，后者仅是两种IPC正文的离线包络。完整设备IPC信封、方向/序号/握手、HTTP OpenAPI和数据库DDL仍待统一归并。Id/U20/Ref/Scope从[摄取候选](../c05-ingress/ingress.schema.json)复制结构，不修改该来源。

## 模型边界

| 模型 | 具体用途及不包含的保证 |
| --- | --- |
| SourceFault／Gap | 当前可信检测域、来源身份、原因、已知区间或未知缺失；未知不是零。来源换代关闭旧key，新key初始baseline_required |
| SourceProtectionPlan／RunProtectionTarget／ControllerTarget | 完整来源依赖并集、run前态、旧执行pin及所有可能接受旧代次的Controller准备目标；不是当前事件的匹配集合 |
| SourcePauseLatch／SourceProtectionRecord | 本地持久事实、远端应用和未决项分开；旧事件决定不改写，重复fault不重复锁存 |
| AutomationOriginBinding／OriginExtension | Seamer authority/database、run、定义、execution及arm_generation一直绑定到发送；manual必须null，字段本身不授信 |
| RunGenerationSelector | 对同origin_scope/run，拒绝`generation <= deny_through_generation`；其他run及manual不匹配。不匹配不代表其他门控已通过 |
| ProtectionRequest／ControllerProtectionRecord | Seamer请求Controller拒绝旧代次，以及accepted/fencing/applied/indeterminate状态；202仅可靠受理，applied必须有回执 |
| RunFenceBody／RunFenceAckBody／RunIntent／RunCoverage | Controller冻结切点、完整旧世代intent、worker覆盖及绑定摘要回显；旧出口不能凭新连接证明never_received |
| ControllerRunFenceReceipt | 关键应用事务后的Controller事实；applied可仍有in_flight/unknown，不是资源clear或自动恢复 |
| SourceRebaselineReceipt／SourcePauseResolution | 同key新基线及floor、保留gap、精确latch/回执/资源/预检、新代次；只为显式恢复提供证据，不直接启动执行 |

SourceProtectionPlan中的latch_id预分配；Latch再引用完整plan摘要，plan不反向嵌入latch摘要，避免循环。ControllerTarget按`(controller authority,database,target_id)`固定排序，RunProtectionTarget按run_id排序；不存在的旧执行或Controller不能通过删掉引用“修复”全集。

RunFence账本按`(controller_boot_id,worker_boot_id,device_session_id,ipc_session_id,permit_id,dispatch_intent_id)`字典序固定，coverage逐项回显相同顺序和完整身份；该顺序只用于规范摘要，不规定设备动作的执行顺序。账本完整性仍由Controller当前及历史出口记录证明，不能由worker自报数量替代。

数组4096/256仅为本局部格式的传输硬边界，实际profile还必须约束全批字节、全部run/旧执行/出口数和writer时间，并在产生可保护资格前预留P0预算。超限关闭准入或进入维护，不截断保护集合，也不因省略历史目标放行。

## 摘要、作用域及两个服务的事务

所有摘要为`sha256:`加RFC8785规范字节的SHA-256。fault/plan/latch/target/receipt/resolution仅排除自己的顶层摘要字段；selector摘要覆盖完整selector，automation_binding摘要覆盖完整具名对象，targets_digest覆盖完整排序targets。不得递归删除业务同名键。

ProtectionRequest.target_set_digest覆盖本请求Controller和selector所对应的完整ControllerTarget数组。不能把全Seamer的隐藏目标列表发送给无关Controller；其回执回显该范围摘要，Seamer按固定plan子集核对。此摘要不代替Controller自身的完整出口账本ledger_digest。紧急保护没有可靠plan时，仍由已绑定准备记录构造本Controller子集；protection_ref必须为null，不能制造持久引用。

候选服务接口为`POST /internal/automation/protections`及`POST /internal/automation/protections/lookup`。前者接ProtectionRequest，返回ControllerProtectionRecord；后者只按完整origin_scope、operation_id、selector_digest和target_set_digest查询原操作。两者都要求配对mTLS、`automation.protect`及精确origin所有权；秘密不进请求身份。lookup不创建新操作。当前只有字段与行为设计，未生成OpenAPI或运行鉴权。

幂等键为`(controller_scope,origin_scope,operation_id)`；同键异selector/目标摘要409并保留原件，不能修改原操作。合法重复保护可返回原操作；新更高deny下界是新operation，按max合并，不能降低已有下界。请求已知未提交或结果未知时也只可查原／重投**拒绝操作**，绝不沿这条例外重发设备动作。人工恢复必须另走预检与准备。

Seamer持有SourceFault、依赖索引、ProtectionPlan、latch与outbox；Controller持有run拒绝下界、prepare准入墓碑、命令/intent切点、完整出口覆盖及应用回执。Seamer不能直接写Controller账本。worker ACK不是Controller已落盘；Controller applied也不是Seamer已记账。P1/P2/P3/P4每个本地原子边界见DF04。

## 参考检查和准确范围

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_contracts.py --check-report
```

[check_contracts.py](check_contracts.py)使用人工源/目标集合及出口事实，检查必填和额外字段、重新摘要后的集合/作用域/代次错误、完整coverage、旧worker不能自证未发、Controller持久回执、单调故障合并和有限恢复门槛。P1使用私有副本模拟原子提交，七个主动故障切点只证明该有限模型不发布半批，**没有运行SQLite、进程或真实并发**。恢复同样只是有限前提判定，不执行R2—R4。

报告绑定本目录5文件、摄取Schema和4份关联主稿，共10份输入；`--check-report --staged`仅核对暂存字节，不重跑。该报告不属于旧顶层十份清单。

原0.1的Command/Guard/Permit/IntentRef、握手及保护HTTP缺口由[后续候选](PROTOCOL.md)推进；全部公共命令/Prepare接口及SDK统一迁移仍缺。P1—P4物理DDL及实际字段提供者、重基线操作及跨source_epoch替换链、P0额度/超时/监督器紧急保护、provider回执持久布局与GC继续待交付。原18模块和两平台范围保持；PFT01—PFT18运行验收、生产服务/鉴权/网络/磁盘/设备执行数均为零。
