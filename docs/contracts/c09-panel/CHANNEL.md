# 面板会话与调用信封候选

`channel.schema.json`是panel-channel/0.1.0-draft.1的唯一格式源；[C09第10节](../../rebirth-c09-extension-design.md#10-面板会话与调用信封的机器候选)规定消息使用条件。根Schema只接受WindowFrame、PanelFrame、HostFrame，服务端Session／Intent／Preview／Guard等必须选择具体defs验证，不能作为面板消息发送。旧draft.4／IPC0.3不变，当前候选尚未批准。

定义四种窗口握手消息、四种面板端口消息及三种宿主端口消息，并分开人员会话、面板会话、文档代、目标authority和委托。Request的TypedValue仅是二次Schema校验入口，**不是全部35个方法的参数及结果模型已经完成**。既有operation-policy保留完整71项用途覆盖；本批合成registry只选择其中三个真实方法名演示输入绑定及跨目标拒绝，SyntheticArguments不是这些方法的产品Schema。逐方法参数、结果脱敏、订阅投影、HTTP与IPC及DDL仍需同版归并。

`channel-cases.json`保存独立手工预期。检查器核对结构、合成窗口身份／nonce、端口及当前代际、方法用途、目标和动态输入；确认分开intent_digest与完整不可变preview_digest，实际计算JCS并拒绝摘要重算后的身份错配。可信宿主、人员权限、来源窗口、当前时钟域／截止和registry批准均为人工前提，不是对外API布尔字段。SchemaRef及ObjectRef摘要为占位，未验证真实制品、授权或对象内容。schema的Origin仅是字符串，精确规范origin与独立来源由部署批准及浏览器运行验证。

有限轨迹假设每步已在同一writer原子执行，只检查commit／cancel排列、关闭后禁止新消费及历史查询；不运行SQLite，不证明并发、崩溃恢复或最终设备写屏障。uncertain轨迹的known_acceptances=0仅表示没有已知成功回执，实际可能已受理，必须查询，不能当never_accepted。ACK目前只有字段及规范说明，未模拟保留窗口、计数释放或背压；原始JSON文本／UTF-8／深度预算也尚未执行完整DF01解码器。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_channel.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_channel.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_channel.py --check-report --staged
```

报告绑定本说明、Schema、人工用例、检查器、operation-policy及C09稿六份输入；后两条只比较原字节，不重跑。它独立于原28项操作策略报告和旧十报告清单。浏览器、真实身份、数据库、设备运行均未执行；离线通过不关闭C09或批准面板运行。

后续[CHANNEL_V02](CHANNEL_V02.md)已归并完整窗口／RPC／Bundle／只读投影消息与35方法，采用新文件和独立报告。旧0.1及本98例保持原接受集和合成上下文，不代表新版19种消息或完整方法联接已经由本报告覆盖。新版仍是设计候选，HTTP／IPC／DDL及真实运行尚未交付。
