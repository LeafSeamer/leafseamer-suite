# 当前命令投影与人员／服务订阅交接

本交接固定 SDK 两次提交，接续[传输契约交接](../sdk-transport-handoff/README.md)。已完成当前命令到快照的字段映射、人员／服务 owner、HTTP、双向帧及恢复次序的候选设计；尚未形成可广告的完整契约组合，没有开始业务实现。历史传输交接仍按其固定提交解释。

| 轮次 | 固定成果 | 已有离线证据 |
| --- | --- | --- |
| 1/3 | SDK [`cf36c1b`](https://github.com/LeafSeamer/leafseamer-sdk/tree/cf36c1bf53b1de4e015684f20ea4010a82518082)，[当前命令投影](https://github.com/LeafSeamer/leafseamer-sdk/blob/cf36c1bf53b1de4e015684f20ea4010a82518082/contracts/event-projection/README.md) | 86 个模型、134 项检查；保留取消不确定与过晚、unknown 清资源后的暂停锁存，以及完整原件引用 |
| 2/3 | SDK [`fc71409`](https://github.com/LeafSeamer/leafseamer-sdk/tree/fc714097df98be3d7ffe2be714b96222d75a511b)，[订阅通道](https://github.com/LeafSeamer/leafseamer-sdk/blob/fc714097df98be3d7ffe2be714b96222d75a511b/contracts/event-channel/README.md) | 122 个模型、15 项操作、294 项检查；86 个投影定义原样复用，人员 8 项与服务 7 项操作使用各自认证入口 |
| 3/3 | Suite 本交接 | [manifest](manifest.json)与[检查器](check_handoff.py)核对固定 Git 原件、报告全部输入、来源锚点、模型等价及认证／路由关系；[报告](report.json)记录核验范围 |

交接检查不把两轮用例数量相加成新的系统覆盖率，也不把串行内存模型称作数据库、浏览器或设备验收。134／294 项行为检查在本轮实际复验；固定提交的独立导出复验另记本地审计结果，不混入本报告的静态检查数量。

## 跨项裁决与适用边界

1. **C01／DF01**：86 模型投影图完整嵌入 122 模型通道图，保留各自具名摘要表示。快照与通道使用裸 hex，命令原件 Ref 使用 `sha256:` 前缀；不得因算法相同全局替换。完整原件摘要由完整来源核验，裁剪后的公开投影不能独立证明原件真实性。
2. **C05**：先核 Ready，再 attach／attached，随后应用完整快照并确认；ACK 覆盖 sync.ready 才标记 live。换代后旧页、释放及 ACK 都拒绝；重复 attached 不能重置客户端状态。ClientOrder 只验证绑定和次序，尚未实现完整页面／数据消费者。恢复不能依客户端自报较大水位跳过服务器确认点。
3. **C07／C09**：人员 owner 绑定 issuer／epoch／session，服务 owner 绑定配对及服务身份；人员注销不撤组织服务订阅。服务入口固定 mTLS，不能退回人员 bearer。`status.read` 不独自授予 commands 读取；逐资源 selector、投影 profile 及来源可发布性仍需真实提供者。人员票据绑定具体订阅，一次秘密丢失不恢复。
4. **C02／C03／C04／C08**：命令快照保留原命令归属、修订与取消语义，unknown 清资源不恢复自动化；不能以当前控制持有人重写历史。来源 Ref 与发布资格是独立条件，结构合法不证明设备效果、完整准入或发送许可。
5. **C12**：新 `event-channel/0.1.0-draft.1` 首帧和 `snapshot-projection/0.2.0-draft.1` 根须进入新的完整选择组合。15 项通道操作是替换候选，不能直接加到旧 179 项上宣称已有 194 项统一操作；旧 `/events`、票据、订阅和快照路径需要明确替换映射及双 authority 裁决。`integration1` 不得原地接受新帧，`x-advertisable=false` 保持。

上述裁决依据两份固定 SDK 规范及[来源锚点](manifest.json)。这两份候选均为 `approved=false`、`runtime_ready=false`；旧 draft.4 原件保持，设计归并不等于用户批准新的运行基线。

## 剩余设计交付及实施验收

| 原编号 | 实施前仍须交付 | 实施后验收 |
| --- | --- | --- |
| C01／DF01 | 全部跨域 Ref／数字／语义调用点及具名摘要；合并完整选择、路由替换与客户端生成来源 | TS／Ajv、原始 wire、JCS／大整数跨语言及两平台消费 |
| C05 | 其余十一类最新领域投影、selector／profile 机器注册；完整页面／帧消费者与 canonical_trigger 来源资格 | 权限收窄、重连、背压、持续来源与真实网络顺序 |
| C07／C09／DF04 | owner、Context、票据、订阅代际、发送映射与 ACK／pin 的精确 DDL／原子写集；真实提供者接口 | 票据消费竞争、提交后 101 丢失、发送点与崩溃恢复 |
| C12／A01—A22 | 双 authority 完整 API／通道选择、代理路由及升级保留组合 | 浏览器、认证撤销、服务并发、部署与全功能设备回归 |

这些项目保持各自原编号，不新建重复待办体系。阶段 0 尚未关闭；全系统设计完成后再进入业务实现。

## 复验

依赖复用既定离线契约验证环境。

```text
docs/contracts/.venv/Scripts/python.exe -I -B docs/contracts/sdk-event-handoff/check_handoff.py --sdk <SDK仓库> --report
docs/contracts/.venv/Scripts/python.exe -I -B docs/contracts/sdk-event-handoff/check_handoff.py --check-report
```

核验读取固定 Git blob，不读取 SDK 未提交工作副本。反例覆盖报告替换、重算摘要后的案例伪标、遗漏输入、模型漂移、服务认证降级、路由遗漏、候选错误广告、旧选择复用和非法路径／浮动提交。`--check-report` 仅核本仓输入绑定，不替代重新执行行为用例。

本轮为当前周期第 3/3 轮；提交完成后先推 SDK，再推 Suite，并分别核对本地 HEAD、origin/main 和 GitHub 实际 main。仅提交成果，既存本地治理资产、运行日志与秘密不夹带；本轮不部署、不操作真实设备。
