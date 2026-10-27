# 投影注册与持久化交接

本交接接续[事件通道交接](../sdk-event-handoff/README.md)，固定 Profile／Selector 注册与真实 SQLite 写集两轮成果。它补齐具名注册正文和局部持久化方案，阶段 0 尚未关闭，业务实现尚未开始。

| 轮次 | 固定成果 | 已有证据 |
| --- | --- | --- |
| 1/3 | SDK [`fbe2499`](https://github.com/LeafSeamer/leafseamer-sdk/tree/fbe249961a97e2d28c3d50b1d5ee8e27dbca54be)，[注册候选](https://github.com/LeafSeamer/leafseamer-sdk/blob/fbe249961a97e2d28c3d50b1d5ee8e27dbca54be/contracts/scope-registry/README.md) | 126 模型、12 类视图注册、207 项检查；其中 122 项为原通道定义等价核对 |
| 2/3 | SDK [`d26c499`](https://github.com/LeafSeamer/leafseamer-sdk/tree/d26c4996854e945074cb0c4fa6a6eeb7e0b8e29e)，[持久化候选](https://github.com/LeafSeamer/leafseamer-sdk/blob/d26c4996854e945074cb0c4fa6a6eeb7e0b8e29e/contracts/scope-storage/README.md) | 7 表、226 项检查、40 条逐写入故障路径及 3 个真实磁盘场景 |
| 3/3 | Suite 本交接 | [清单](manifest.json)、[检查器](check_handoff.py)与[报告](report.json)固定 Git 原件、完整报告输入、来源锚点、模型与权限关系及验收边界 |

207／226 项是各自范围内的检查数量，不能相加为系统覆盖率。本轮另外从固定提交独立导出并复验这两组检查，结果留在本地审计；交接报告只计固定原件及关系核对，不把读报告计为执行行为测试。

## 归并裁决

- **C01／DF01**：原 122 个通道定义原样保留，增加 Profile、CollectionRule、Selector、Window 四个类型。视图图摘要取固定图原始字节，注册 Ref 摘要取完整正文 JCS，Scope 摘要仍取原完整 ScopeSpec；这些摘要对象不互换。本包不新增管理端点，不自动形成完整可广告的选择。
- **C05**：有限 selector 只允许明确实体集或全部当前授权实体；明确实体集中任一成员失权即整体拒绝。固定历史窗口保留窗外当前与未决对象，容量不足整体拒绝。canonical_trigger 要求完整规范来源集合，不以窗口缩减。12 类视图已有注册，不代表其余 11 类旧领域字段已经更新。
- **C07／C09**：批准 Ref、Grant 和实际认证上下文来自不同的可信输入，客户端自算摘要不构成批准。每次释放重核当前授权修订和先前计划；Profile 撤销使依赖 Selector 失效，旧安装回执仅为历史事实。真实身份提供者和撤权传播仍须完成。
- **C08／DF04**：对象或墓碑、操作、审计、通知和封存同事务，双向延迟外键拒绝漏写提交。启动绑定服务／库／角色，不把不同服务对象装入同一发布库。通知意图不证明送达或出口已关闭；关闭重开不等于进程强杀或断电。

以上依据固定 SDK 正文、SQL、参考模型和报告，全部候选仍为 `approved=false`、`runtime_ready=false`。真正数据库检查已经执行，不再标成“数据库全部未验”；完整生产库、产品驱动、迁移与耐久运行验收仍未完成。

## 最终释放边界与后续工作

已验证事实：WAL 的旧读事务可继续看到另一连接撤销前的资格；尝试将该旧读升级为 writer 得到 `SQLITE_BUSY_SNAPSHOT`。新 `BEGIN IMMEDIATE` 重读会拒绝已撤销资格，但返回后数据库锁已释放。（来源：固定 SDK [检查器](https://github.com/LeafSeamer/leafseamer-sdk/blob/d26c4996854e945074cb0c4fa6a6eeb7e0b8e29e/contracts/scope-storage/check.py)。）

基于该事实的设计要求：最终释放必须与本机撤权门的关闭具有明确顺序，覆盖已排队页、帧、重连及旧授权计划；不能把一次数据库读取当作持续资格，也不能持写锁等待网络。目前这一门尚未实现，本交接不补造已完成声明。

| 原编号 | 实施前剩余设计 | 后续运行验收 |
| --- | --- | --- |
| C05／C07 | 撤权到最终释放的本机门与通知确认顺序；权限来源、页／帧完整消费者及其余 11 类当前领域映射 | 撤权与发送竞争、慢消费者、断线重连和来源持续性 |
| C08／DF04 | 将本次 7 表与 owner、Context、票据、订阅代际、发送映射、ACK／pin 的完整写集归并；恢复及迁移策略 | 产品 SQLite 驱动、崩溃／断电、完整备份恢复 |
| C01／DF01／C12 | 对原 179 项操作和 15 项通道候选显式裁决替换，形成包含注册图的新完整选择；严格数字、摘要及其余语义调用点 | TS／Ajv、原始 wire、浏览器、两平台和代理组合 |

以上保持原 C／DF 编号和完整交付范围。下一轮优先推进最终释放与撤权排序这一已有明确反例的缺口，不重复建设注册正文或局部 SQL 写集。

## 复验与交付

使用既定资料验证环境：

```text
docs/contracts/.venv/Scripts/python.exe -I -B docs/contracts/sdk-scope-handoff/check_handoff.py --sdk <SDK仓库> --report
docs/contracts/.venv/Scripts/python.exe -I -B docs/contracts/sdk-scope-handoff/check_handoff.py --check-report
```

检查读取完整提交 ID 的 Git blob，拒绝浮动引用与非规范路径；变异例覆盖模型漂移、图字节错配、权限降级、未决遗漏、静默截断、报告虚报和运行边界伪标。`--check-report` 仅核本仓输入摘要。

本轮按既有授权完成一次 main 提交，再依次推送 SDK 与 Suite，并核对实际远端 main。发布、部署和真实设备操作不包含在本交接内；成果提交不夹带本地治理资产、日志或秘密。
