# 完整快照投影候选

[C05第10节SP01—SP06](../../rebirth-c05-event-sync-design.md#10-完整快照交接的字段与事务细化)的附属设计资料。`snapshot.schema.json`是本批唯一格式源：十二种SnapshotView、Manifest、PageResponse及三类server.data载荷；业务draft.4／IPC0.3保持原样。版本为snapshot-projection/0.1.0-draft.1，尚未批准、生成SDK或进入生产。

具名投影与完整领域记录分开：命令保留结果／资源状态及受限关联，运行保留布防代际／暂停／恢复投影，场次分别保留admission、资格锁存及execution结果。它们不是原管理响应的任意字段裁剪。所有静态对象拒绝额外字段；只有QualifiedValue.value是绑定已批准Schema的动态位置，结构通过后必须二次校验，未知Schema引用拒绝。Schema本身不能验证当前身份、目录批准、信息脱敏或字段事实来源。

`cases.json`有十二类正例与结构反例、完整Controller／Seamer／空集合及错页／错代／错摘要案例，另含重新计算全部公开摘要后仍应拒绝的语义错配。`check_snapshot.py`计算JCS页／manifest／data摘要、集合计数／顺序／跨页唯一性、水位与有限领域关联；预期独立手写。data报文采用entry对象承载entry_kind与payload，payload_digest对entry做JCS；不是对连接envelope计算摘要。

参考检查中的authorized、domain_current、当前generation、deadline_tick、预期scope／schema和required_refs均是人工可信前提，**不是API字段**。Schema摘要／对象摘要和采样引用包含合成占位；检查器比较批准引用，不验证第三方制品或来源采样。required_refs只验证给定的必需本地引用身份／revision，不自动推导完整闭包或证明外部对象内容；source.event的origin_digest／age_evidence只描述及绑定字段，尚未重算完整DF06来源投影或验证真实年龄证据。不能把参考判定当作生产鉴权、完整业务状态机、SQLite事务或网络时序实现。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-snapshot/check_snapshot.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-snapshot/check_snapshot.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-snapshot/check_snapshot.py --check-report --staged
```

报告绑定本README、Schema、人工用例、检查器和C05文稿五份输入；后两条只比原始字节，不重跑用例。此报告独立于旧十份报告及c05-subscription报告。原始wire严格解码／预算、HTTP与WS同版归并、完整对象与授权关系、实际数据投影／保留GC、SNP01—SNP16仍须后续交付或运行验证；这些用例的静态通过不证明阶段0或C05已关闭。
