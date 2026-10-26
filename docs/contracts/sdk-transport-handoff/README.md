# HTTP／worker共源与HTTP／WS选择的固定交接

本交接消费SDK两个固定提交，更新Suite的当前设计状态；不复制SDK生成物、不回写历史源、不修改业务代码，不批准新运行协议。旧[资料迁入交接](../sdk-handoff/README.md)及其报告按旧提交当时的输入解释，本包是当前交接入口。

| 周期轮次 | 固定提交与交付 | 已有证据 | 边界 |
| --- | --- | --- | --- |
| 1/3 | SDK [`9eb9cf5`](https://github.com/LeafSeamer/leafseamer-sdk/tree/9eb9cf5ec9715ce9290279d973c69a5c03a271a5)，[共源包](https://github.com/LeafSeamer/leafseamer-sdk/blob/9eb9cf5ec9715ce9290279d973c69a5c03a271a5/contracts/integration/README.md) | 128个公共命令模型与完整464模型的同名项等价；1263模型／177操作／52帧，1441项离线检查；独立检出941项通过 | HELLO／ACK能力及通道关联通过仍是closed，不授发送；52独立结构帧不是可重放完整会话 |
| 2/3 | SDK [`c372565`](https://github.com/LeafSeamer/leafseamer-sdk/tree/c37256500c43092b145feebd026e273c5a2667f4)，[选择规范](https://github.com/LeafSeamer/leafseamer-sdk/blob/c37256500c43092b145feebd026e273c5a2667f4/contracts/negotiation/PROTOCOL.md) | 1269模型／179操作，Context、人员票据和WS首帧绑定同一选择；1755项离线检查及独立检出复验 | 不是生产SDK；串行消费模型不证明真实数据库并发、认证来源或浏览器行为；worker wire未改 |
| 3/3 | Suite当前交接提交 | [manifest](manifest.json)固定47份SDK文件实例、45个报告输入及258个来源锚点；[检查器](check_handoff.py)读取真实固定Git对象并验证模型变化、数量及选择摘要 | 不把报告数量当作全系统验收完成，不证明远端推送；推送由执行结果另核 |

原共源包包含175个普通HTTP和两个WS操作；选择候选新增两服务各一个发现入口，共179项（Controller91／Seamer88）。其中39个旧基线协议定义（38响应＋Meta）改为候选ID，连同Context／票据和WS根共44个原定义变化，新增6个选择相关定义；464个command命名空间定义保持相同。当前选择为`leafseamer.api.v1.integration1`，精确摘要见manifest及固定SDK selection文件，不以短版本号判断兼容。

## 跨项审阅结论

1. **C01／DF01**：传输选择已有字段与失败规则，同ID资料不可替换、未知选择不回退、保留旧组合不得挤掉查原／取消／恢复依赖。Context固定选择，幂等身份不增加契约摘要分区；换版本不产生自动重投授权。跨域Ref、数字接受集、语义规则调用点与具名摘要仍未完成，不把现有局部Schema版本全文改成一个字符串。
2. **F02／F03、C02／C03／C04**：worker0.14的52帧共源已交付，HELLO强制23项与ACK强制30项的差异由子集关系额外约束。两帧Schema通过不等于握手成功，握手成功也不等于开闸、业务授权或完成证据。其他监督、bootstrap、导入、面板和采集通道分别保留权威身份，仍待归并。
3. **C07／C09**：显式选择保留所有原认证方案和对象约束，不开放内部操作。人员WS票据不伪造service会话；首个201返回秘密、重复200仅返回非秘密绑定的规则保留。实际签发、撤销、Context存储选择和票据原子消费仍需接入可信writer。
4. **C05**：WsReady只确认传输组合，之后的旧数据payload图不是当前命令／控制权完整投影。完整快照、游标世代、双向ACK、订阅owner及权限映射仍须联校；不能因首帧通过宣布订阅live。
5. **C12／DEP02**：新增宿主内`/.well-known/leafseamer-contracts`必须经过既有外部静态service前缀；已在[部署设计](../../rebirth-c12-deployment-design.md)补精确路由及认证Controller选择。否则多服务管理origin会有发现目标歧义。选择头重复性不能在代理中静默丢失，票据token不得回显或进日志。本轮未生成／运行nginx配置。

以上是已有推荐的具体化和关联裁决；两份候选尚未获用户批准为新运行基线，已批准draft.4原件保持。实现后证据另列，不因缺真实设备就重新把已明确的字段方案记成无设计。

## 后续冻结与验收交接

| 原编号 | 实施前仍须交付 | 实施后验证 |
| --- | --- | --- |
| C01／DF01、SV02／SV03 | 跨域Ref、严格数字接受集、全量语义调用点、导出／权限／具名摘要联合包及候选审阅 | TS生成与Ajv、原始报文、JCS及大整数跨语言、两平台消费 |
| C05／C07／C09 | 当前事件与快照投影、owner／授权矩阵、面板方法及生命周期缺失API | 认证提供者、撤销传播、浏览器隔离、背压和双向订阅 |
| F02／F03、C02—C04／C08、DF04 | 其他IPC通道绑定；选择、Context与票据写入现有存储的精确列／原子写集；完整OPEN与许可来源链 | 唯一出口、真实并发票据、消费提交后101丢失、进程与磁盘故障 |
| C12、DEP02及A01—A22 | 静态发现／认证／API／WS路由、保留组合及升级依赖的交接；完整设计未决清零 | nginx配置检查、重复头、未知service拒绝、版本组合及全功能回归 |

下一轮优先收敛当前事件／授权投影与公共类型引用，避免继续累积“结构上能生成、语义上仍错版本”的独立包。最终消费版本必须同时覆盖实际接受集、权限、具名投影和摘要／DDL，不能仅替换info.version。全系统设计尚未完成，业务实现阶段保持未开始。

## 核验与推送

```text
docs/contracts/.venv/Scripts/python.exe -B docs/contracts/df01/check_reference_vectors.py
docs/contracts/.venv/Scripts/python.exe -B docs/contracts/sdk-transport-handoff/check_handoff.py --sdk <SDK仓库> --report
docs/contracts/.venv/Scripts/python.exe -B docs/contracts/sdk-transport-handoff/check_handoff.py --check-report
```

核验器读取固定Git blob，回绑两份SDK报告完整输入，验证8个规范产物字节摘要和JCS manifest选择摘要，并从真实模型／路由计算统计。258锚点包含249个Suite和9个SDK来源。11项负例覆盖篡改报告、漏输入、重算摘要后的数量伪标、选择／规范替换、非法路径和浮动提交。它不重新执行SDK的1441／1755项历史行为检查，也不把独立复验与主验收相加虚报覆盖。DF01固定参考向量因设计稿更新实际重跑，仍不是产品工具链验收。

检查需要既定rfc8785参考依赖；`--check-report`只核本仓输入。旧报告按各自提交原件核验，后续文档变化不改写其历史结论。本周期先推SDK main的两次提交，再推Suite当前提交，之后逐仓核对HEAD、origin/main与GitHub实际main引用。只提交成果，既有未提交治理资产、日志和运行秘密不夹带；发布、部署及真实设备操作不在本轮授权范围内。
