# 发布原件与当前面板提供者交接

当前成果固定 SDK `aff5ccbb75b6140109f948f81284785c75e46d1e`，保留 `approved=false`、`runtime_ready=false`。阶段0继续开放，尚未接入生产审批、业务执行或设备。固定提交、245个去重 Git 原件及469项按包输入绑定见 [manifest](manifest.json)。

| 成果 | 固定提交 | 已验证范围 |
| --- | --- | --- |
| 当前发布原件与历史升级 | [ca785b2](https://github.com/LeafSeamer/leafseamer-sdk/commit/ca785b21ce17a1a906c9c6d8082f65596f183f9e) | 当前写入使用panel4；历史panel3必须经显式历史入口读取。保留原BLOB、拒旧writer新增和重标记录，完整PublishedVersion关联不退回最新草稿。292项基础检查及74项升级检查，DELETE／WAL真实磁盘与存活旧连接覆盖 |
| 当前动态值与发布来源适配 | [aff5ccb](https://github.com/LeafSeamer/leafseamer-sdk/commit/aff5ccbb75b6140109f948f81284785c75e46d1e) | 当前选择／Registry／Bundle绑定；发布content与metadata从已提交原件读取，再逐节点检查字段权限及当前批准Schema。332项基础检查、59项发布检查、30次实际校验子进程及1个WAL磁盘场景 |

Suite 的 [交接检查](check_handoff.py) 从固定 Git 对象构造独立快照，实际重跑两包完整检查，并比较产生的报告与固定报告逐字节一致；[本轮报告](report.json)记录这次运行。基础计数包含输入字节核验，不能全部视为业务断言。测试库及运行日志位于隔离快照的logs目录，不对实际项目数据库执行迁移。

当前面板可以在当前批准下读取原panel3历史发布内容，但不会修改历史选择。来源引用须绑定scope、definition、version与完整记录摘要；生命周期epoch仍由可信宿主提供。未提交记录、完整发布身份不匹配、错误摘要、缺任意根／容器／叶字段权利、Schema不满足以及撤权均拒绝，不能通过裁剪或强转通过。连接必须由可信存储实例提供且串行使用。测试中的完整值const Schema是显式合成批准，不是生产自动审批。

这是两个发布槽的来源接线。其余动态来源适配、真实安装审批及当前读权、生产发布与产物／请求／审计同事务、最终输出Gate、校验器硬内存限制及全局调度仍待完成。普通动态提供者不替调用方证明实际来源；当前成果不意味着所有提供者已完成迁移。

[上一轮浏览器交接](https://github.com/LeafSeamer/leafseamer-suite/tree/ffbbbff196a13a9f477db9bee83ffd1066f0b815/docs/contracts/sdk-panel-handoff)固定在其原Suite提交，保留35220条Chrome页面／Worker断言及420次合成服务HTTP交换。这些是历史运行记录，本轮未重跑浏览器、HTTP或设备。旧交接的提供者拒绝结果描述其固定旧SDK；新提供者以本轮独立目录及选择绑定交付，不覆盖旧包或旧报告。旧交接对门户文档的报告绑定应在该历史提交复验。

```text
python -I -B docs/contracts/sdk-publication-handoff/check_handoff.py --sdk <SDK仓库> --report
python -I -B docs/contracts/sdk-publication-handoff/check_handoff.py --check-report
```

第一条实际执行两包检查，要求固定提交可从SDK main追溯并使用具备jsonschema、referencing、rfc8785的Python环境。第二条仅检查报告输入一致，不运行行为。全系统完成标准仍以 [readiness 6.1](../../rebirth-readiness.md#61-全系统设计完成门槛)为准。
