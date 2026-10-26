# SDK独立契约资料的固定提交交接

本交接登记已经完成的资料迁入和接口机械归并，替换“SDK仍为空入口”的现行描述；不关闭阶段0、不批准新的运行协议，也不启动业务实现。权威状态仍由 [DF01](../../rebirth-df01-sdk-freeze.md)、[收敛清单](../../rebirth-design-closure.md#12-已有http与ipc的归并裁决)和 [readiness](../../rebirth-readiness.md#61-全系统设计完成门槛)共同约束。

| 本周期轮次 | 仓库／提交 | 已交付及证据 | 尚不代表 |
| --- | --- | --- | --- |
| 1/3 | SDK [`9bfe014`](https://github.com/LeafSeamer/leafseamer-sdk/tree/9bfe014d3730e83442b5fe062f40b56463eeb68a) | [独立draft4源](https://github.com/LeafSeamer/leafseamer-sdk/blob/9bfe014d3730e83442b5fe062f40b56463eeb68a/contracts/draft4/README.md)；九份原件、六产物字节／节点等价、原232例、16变异与5路径拒绝；Windows独立干净检出通过 | 语义实现已迁出、TS客户端已生成或跨平台SDK验收 |
| 2/3 | SDK [`027f1fc`](https://github.com/LeafSeamer/leafseamer-sdk/tree/027f1fc75d9113da9dd5dae93e075ca3082e5e4e) | [接口归并预览](https://github.com/LeafSeamer/leafseamer-sdk/blob/027f1fc75d9113da9dd5dae93e075ca3082e5e4e/contracts/composition/README.md)；927模型、15输入、177操作、27替换、6退役；235项离线检查及独立检出通过 | 统一wire协商、IPC、授权或服务运行已经冻结 |
| 3/3 | Suite本交接 | 修正当前设计状态、输入选择和责任归属；[manifest](manifest.json)固定SDK提交与文件摘要，[报告](report.json)核验真实Git对象、源锚点、统计及本仓文档绑定 | 发布、部署、真实直播设备验收或项目完成 |

SDK第一轮和第二轮的报告按各自提交当时的文件核验，不能拿最新工作区替换历史输入；当前SDK main必须包含两个指定提交。Suite不复制SDK生成物形成另一个可编辑源，保留旧draft4、提取实验和固定源锚点作对账。SDK中的composition是新候选的审阅输入，后续字段与协议修订在SDK中演进；Suite更新设计依据和消费版本引用。此交接不是Git submodule，也不修改其他三个仓库。

## 已关闭与未关闭的设计项

已完成DF01的独立纯数据归属和旧基线等价迁入，以及C01归并规则中的双authority分离、显式替换／退役、模型来源追踪和完整操作元数据保持。控制权server前缀挂载及同名Schema属性的引用转换已有具体规则和回归用例。

以下仍归原编号，不另起一套待办编号，也不把运行验收提前变成设计门槛：

| 原编号 | 下一份必要交付 | 设计关闭证据 | 实施后证据 |
| --- | --- | --- | --- |
| DF01、C01、SV02／SV03 | 统一版本头与正文接受集、精确跨域Ref及严格数字词法、逐规则调用点和具名摘要投影 | 同版源与正反例；不得以旧解析失败后回退旧协议 | 原始报文、JCS/大整数跨语言、TS/Ajv和浏览器消费 |
| C02／C03／C04、F02／F03 | 以当前IPC0.14和52帧为worker输入，其他通道分别绑定方向、身份和握手 | 单一SDK源导出的Schema/OpenAPI/IPC及完整引用；接管／取消／继续运行关联反例 | 真实唯一出口、进程崩溃、持久事务及在途命令竞态 |
| C01／C05／C07／C09 | 授权、导出、面板方法及快照投影同步，包括摄取操作改名 | 所选177项操作逐项映射、无悬空旧引用，不把模型闭包当公开权限 | 真正身份签发、撤销传播、跨服务会话与浏览器隔离 |
| DF04、C04／C08 | 统一具名正文／摘要／DDL映射与完整事务写集 | 每字段来源、主外键和失败时序；不可补默认身份或空凭据 | 磁盘WAL、掉电、备份恢复及完整服务集成 |
| readiness 6.1、A01—A22 | 汇总其余C01—C12与DF设计未决，保留用户需决定的实质取舍 | 全量需求→契约→五仓→验收追踪，设计未决清零 | 全功能、平台、部署和真实设备验收 |

执行顺序为先统一已选模型的语义与通道，再补尚无机器模型的设计；SDK基线旧源不重做迁移。候选或新行为的批准记录仍须明确，不能由本交接推断用户同意全部未来修订。

## 核验与推送边界

```text
docs/contracts/.venv/Scripts/python.exe -B docs/contracts/sdk-handoff/check_handoff.py --sdk <本地SDK仓库> --report
docs/contracts/.venv/Scripts/python.exe -B docs/contracts/sdk-handoff/check_handoff.py --check-report
```

第一条按固定Git提交核SDK两份报告的输入、Suite来源原件与交接统计，不执行SDK或服务业务；报告保存相对路径和摘要，不保存宿主路径或原始日志。第二条只核本仓报告绑定。235项SDK行为资料检查及原232例的实际执行记录来自对应固定提交，不声称本检查器重新执行它们。

本周期依次推送SDK main的两次提交，再推送引用它们的Suite main。推送前逐提交检查公开内容、秘密格式、私人路径、历史禁入提交及报告绑定；推送后核对本地HEAD、origin/main与GitHub实际引用一致。文档中的提交链接是固定交付引用，推送成功仅由执行结果确认，不以链接存在的写法代替验证。其余已有未提交治理文件继续保留，不随本周期夹带发布。
