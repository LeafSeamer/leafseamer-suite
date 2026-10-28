# panel4 消费者与浏览器交接

本交接固定 SDK `db5634272a0082b625e53b6bb96e94ecfecd78bc`，将当前完整选择、静态正文消费者、HTTP 适配器和类型客户端对齐。所有成果保留 `approved=false`、`runtime_ready=false`，阶段0继续开放。完整选择和293个Git原件摘要见[manifest](manifest.json)，交接检查见[报告](report.json)。

| 固定成果 | SDK提交 | 证据范围 |
| --- | --- | --- |
| 完整选择与静态正文 | [144d0ff](https://github.com/LeafSeamer/leafseamer-sdk/commit/144d0ff68021cf8e6d1137fc61e699a12141ab02) | panel4包含1463模型、201操作、52类worker消息、35面板方法及19类面板帧；修正worker消息表的模型引用闭包。224主检查、233契约检查及8775运行断言 |
| HTTP信封 | [db56342](https://github.com/LeafSeamer/leafseamer-sdk/commit/db5634272a0082b625e53b6bb96e94ecfecd78bc) | 248主检查、12076运行断言、218面板断言及10次回环；实际旧输入／结果SchemaRef拒绝，已受理但投影不可用仍保留受理事实 |
| 类型客户端 | 同上 | 两端各1463模型、197普通HTTP调用及4项WS元数据；224主检查、26逐行类型负例、862运行断言、2次基础与105次面板回环。类型不表达全部if/then约束，完整正文仍由运行校验负责 |

三包共有707项按包Git绑定，去重并加入提供者原件后固定293个文件。上述SDK报告按固定提交核验，本次Suite检查不将读取它们称为重跑。旧events2正文／HTTP／类型消费者仍只接受其原选择；新消费者拒绝events2、panel3及ID／摘要混搭。旧完整候选及旧报告保持各自历史身份。

## 本轮实际浏览器验收

[浏览器记录](browser-report.json)来自本机 Chrome 156.0.8078.48，固定浏览器与Node可执行文件摘要。普通模式与COOP／COEP跨源隔离模式各运行页面及模块Worker：普通上下文各8755条断言，隔离上下文各8855条，合计35220条；普通模式每上下文明确跳过100项不可用共享缓冲检查，隔离模式不跳过。页面动态代码、内联脚本及Worker动态代码均被CSP禁止。

四个上下文均运行当前静态根接受集、460条面板报文、当前与历史选择构造边界、转移缓冲保护以及35方法客户端收发。合成服务实际使用固定HTTP适配器解析请求；每上下文105次，共420次本机HTTP交换，覆盖正常回执、不可用投影、旧输入发送前拒绝、旧结果收到后拒绝且不重试。33项实际请求资源逐字节绑定；仅对通用测试中不可用的SharedArrayBuffer负例加能力判断，转换前后摘要均记录，不修改SDK原件。

这些结果证明指定Chrome与受控合成服务下的消费者行为，不证明产品GUI、跨窗口／port身份、真实授权、真实业务或设备效果，也未验收WebSocket升级。首次Edge独立进程启动退出，未产生Edge通过记录。

## 提供者采用边界

[提供者探针](check_providers.py)实际执行六项检查，结果见[记录](provider-report.json)：发布原件仍绑定panel3，改为panel4后即使重新计算记录摘要仍被拒绝；动态提供者接受原上下文并明确拒绝panel4。不会因为三个消费者已重建就把这些提供者标为兼容。

后续须为发布原件、动态批准Bundle及来源／值关联分别完成当前完整选择迁移，保留不可变历史原件；继续收敛真实投影、最终输出Gate、完整提供者接口与DDL、校验器内存硬限额及全局调度。生产授权和业务实现尚未开始，全系统设计完成门槛仍以[readiness 6.1](../../rebirth-readiness.md#61-全系统设计完成门槛)为准。上一交接的历史证据可从[固定Suite提交](https://github.com/LeafSeamer/leafseamer-suite/tree/65a8eb5650ce0599b1e7d5f7a120967662404aed/docs/contracts/sdk-wire-handoff)查阅。

## 复验

```powershell
python -I -B docs/contracts/sdk-panel-handoff/check_handoff.py --sdk <SDK仓库> --snapshot
node docs/contracts/sdk-panel-handoff/run-browser.mjs --snapshot <输出快照> --browser <Chrome可执行文件> --profile <全新配置目录> --output docs/contracts/sdk-panel-handoff/browser-report.json
python -I -B docs/contracts/sdk-panel-handoff/check_handoff.py --sdk <SDK仓库> --probe-providers --report
python -I -B docs/contracts/sdk-panel-handoff/check_handoff.py --check-report
```

浏览器复验需要允许本机回环连接。使用Suite既有Python验证环境与SDK固定Node版本；不安装依赖或包脚本。最后一条只检查输入绑定，不重跑浏览器或提供者。当前周期为SDK完整选择、SDK信封／客户端、Suite交接三轮，审计后按SDK→Suite推送 `main`，每轮各保留一次提交。
