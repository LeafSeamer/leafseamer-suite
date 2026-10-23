# 面板逐操作策略候选

[C09第9节PD01—PD06](../../rebirth-c09-extension-design.md#9-面板委托与可信宿主确认细化)的局部资料。`operation-policy.json`登记当前71个操作的面板用途，`policy.schema.json`为本批格式唯一源；approved／runtime_approved／authority_switched均固定false。它不是PanelSession或消息协议的完整Schema，也没有生成代理、浏览器组件、OpenAPI或生产鉴权。

六类用途为21项panel_read、6项panel_write、8项host_confirm、10项host_transport、9项host_account和17项unavailable。前35项有唯一method_name，host_confirm只允许提出intent；其余不成为面板RPC。计数与35个方法名是资料完整性检查，不代表安装批准或当前人员有权调用。host_transport的上游票据／context不下发面板；所有响应须另行具名投影，forward_raw_response固定false但尚未实现过滤器。

[检查器](check_policy.py)直接解析两份HTTP骨架，与既有授权矩阵独立对照operationId／permission／source_pointer；每行再核对主体human分支、内部mTLS隔离和具名敏感操作。CONFIRM／WRITE等集合及计数是独立审阅预期，不是未来服务的第二份策略源。新接口或取舍改变需版本化审阅，不能只改预期使检查变绿。

[28个手工变异例](cases.json)覆盖漏项、伪操作、源摘要／权限错配、把布防／恢复／接管降成直接写、暴露token／内部／provider／容量入口、方法重名、原始响应透传和伪批准；另含全部禁止的退化方案，防止以删去面板功能换取通过。它们只验证元数据，不执行跨窗口消息、当前权威取证、确认消费、数据库并发、接管或设备动作。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_policy.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_policy.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_policy.py --check-report --staged
```

首条通过后写[reference-report.json](reference-report.json)，绑定本目录五份输入、C09设计稿和三份来源共九输入；后两条仅比较工作区／暂存区原字节，不重跑检查。新报告不在顶层旧十份报告清单内。PDT01—PDT16及原MX／UIT运行验收仍未执行；下一版需归并完整PanelSession／Delegation／Preview、RequestActor、双向帧、撤销selector、执行guard及DDL。

后续[会话与调用信封候选](CHANNEL.md)已有独立Schema、合成检查及六输入报告，覆盖窗口握手、端口调用和固定预览关联。它不改变本操作策略源或28项用例计数；完整逐方法结果、订阅、HTTP／IPC及DDL仍未归并，不能混用两份报告的验证范围。

[35方法字段规范](METHODS.md)进一步给出完整顶层输入、96个HTTP字段的归属、21个结果白名单及展示句柄的事务边界。独立输入Schema和74项离线检查覆盖方法结构与来源，报告绑定九输入；结果Schema／投影、句柄权威绑定与运行行为尚未验证。该批不改变本策略或会话报告的计数，也不把旧SyntheticArguments提升为产品参数。

后续[21类结果机器候选](RESULTS.md)将白名单落实为Schema，117项合成检查覆盖35方法结果映射和结构／有限上下文关联；六输入报告独立复验。未知终态、隐藏未决、旧接管ready及定义完整性分开处理，合法字符串仍可能携带未经脱敏内容；结果过滤器、真实权威和SchemaBundle尚未实现。此前“结果Schema未验证”仅描述输入批次的范围，不覆盖本结果批次。

[SchemaBundle候选](BUNDLE.md)补充四种局部交付消息、批准绑定、本地引用闭包及有界容量，109项离线检查覆盖73个Bundle例／14个信封例／22条轨迹。`bundle.schema.json`采用channel0.2候选号，旧0.1文件原样保留；完整Active／Request／Result尚未联合归并。此批不是生产加载器，不改变前四批报告的计数或验证范围。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_bundle.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_bundle.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_bundle.py --check-report --staged
```

Bundle报告独立绑定BUNDLE／Schema／用例／检查器四输入，后两命令只查字节。缓存可复用内容但不复用权限，ready不授权执行；实际过滤、模式执行预算、浏览器／服务端权威和设备运行仍未验证。

[channel0.2归并候选](CHANNEL_V02.md)将19种窗口／端口消息、35方法的输入结果、Registry与ActivationRef及动态Bundle入口连在同一版格式中，并区分17个投影订阅、2个仅失效通知和不可订阅的预检／恢复预览。168项参考检查覆盖145个帧／上下文例及23条订阅轨迹；独立报告绑定15输入，不自动合并前五批报告的覆盖声明。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/build_channel_v02.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_channel_v02.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_channel_v02.py --check-report --staged
```

新版允许点号Id以匹配领域身份；原0.1不修改。失步／关闭释放流控槽不推进消费ACK，同ID不复活。当前只有合并格式和离线参考，完整字段提供者、真实浏览器／服务端事务、HTTP／IPC／DDL仍未实现或验收。
