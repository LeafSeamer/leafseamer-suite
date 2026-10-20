# 服务订阅局部候选

[C05第9节SS01—SS06](../../rebirth-c05-event-sync-design.md#9-服务订阅细化与局部机器候选)的附属资料，版本`service-subscription/0.1.0-draft.1`，尚未批准或归并到公共draft.4／IPC0.3。不是可部署SDK或生产订阅实现。

[service-subscription.schema.json](service-subscription.schema.json)是本批有限格式的唯一源：七种顶层对象包含服务订阅视图、attach、attached、ACK、快照应用确认、同步检查点和失步通知，另有owner、binding及计数等局部定义。root oneOf拒绝未知消息；完整manifest／分页、类型化server.data、HTTP／OpenAPI以及consumer槽管理关联尚未生成，不能把局部Schema当完整C05。

owner不含session，内部认证为mTLS服务身份。实际对端、当前配对、授权、规范来源完整性及持久状态不能靠线字段自证。[cases.json](cases.json)中的peer布尔值和consumer_state_preserved等都是**人工可信前提**，不属于API；它们只让参考检查针对固定条件评估字段关联，未证明真实证书、DB状态或完整事务。

[check_candidates.py](check_candidates.py)执行27个结构正反例、25个attach及20个ACK关联例，预期独立写在资料中。ACK例比较保存映射／前驱、last_sent、当前代际及摘要；摘要是合成64位hex，只比较不计算JCS。attach例是**新attempt**的单次状态快照判定，不执行attempt墓碑／幂等分支、并发CAS、generation分配、网络、重连流或业务触发。结构接受大整数不证明每条生命周期路径都已支持它；生产解码仍须DF01严格入口。

在Suite根目录使用已有契约虚拟环境：

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-subscription/check_candidates.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-subscription/check_candidates.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-subscription/check_candidates.py --check-report --staged
```

首条全部预期通过才写[reference-report.json](reference-report.json)，绑定Schema、用例、检查器、本README及C05／DF06设计稿六份输入。后两条只比工作区／暂存区原始字节，不重跑检查，不证明报告声明完整或运行真实性；此报告不在顶层旧十报告清单内，须单独核对。真实TLS、SQLite、浏览器／WS、故障传播和设备执行数均为零，SST01—SST12与EV01—EV36运行验收仍待实施。
