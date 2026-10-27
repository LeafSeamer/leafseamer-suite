# SDK完整正文入口与投影交接

本交接固定SDK `7675185575d014d6138c8283dd16eacb94dbd46d`及其十个前序成果提交，供Suite核对实际交付与阶段门槛。当前仍处阶段0：以下均为隔离参考实现或候选契约，未批准为运行协议，未交付生产SDK或业务服务。旧交接保留各自固定提交的历史边界；当前进度以本交接和[readiness 6.1](../../rebirth-readiness.md#61-全系统设计完成门槛)为准。

## 固定成果

各报告的检查数包含结构、输入绑定、反例或运行检查，不能相加作为全系统覆盖率。manifest固定每份报告及其全部输入，共756项文件绑定；同一文件在多个包中的绑定分别保留。

| 成果 | SDK固定提交 | 实际证据与限制 |
| --- | --- | --- |
| 最终释放门 | [cfa5649](https://github.com/LeafSeamer/leafseamer-sdk/commit/cfa564928b3d1046ad82294b636837dc0c8feadf) | 84项检查、2个线程排序场景、1个本地明文socket及1个SQLite文件场景；最终重核与撤权共用Gate。交给传输不等于对端收到或应用，部分／不确定写关闭队列而不重发 |
| 同机owner与恢复 | [b740e4a](https://github.com/LeafSeamer/leafseamer-sdk/commit/b740e4a80d448e0e4b5577d5bf51252bdee96ff8) | 129项、5表journal、6个SQLite场景、Windows上2次子进程强杀；独占锁与固定锁根绑定。Linux运行和掉电未测，不证明跨机唯一 |
| 订阅释放与ACK | [0cd5a9c](https://github.com/LeafSeamer/leafseamer-sdk/commit/0cd5a9c5401652690bf2375e43c64f57b4053394) | 138项、40个SQLite场景、4个线程失效场景；实际完整交付后推进sent，ACK只消费交付映射；同步屏障ACK前暂停新帧。同一订阅换代先关闭旧会话 |
| 快照消费者 | [306ef42](https://github.com/LeafSeamer/leafseamer-sdk/commit/306ef42e89d0177c602907c44ab86b6547673575) | 113项、12类实体、6表、34个SQLite场景和8个原子故障点；完整分页与摘要校验后同事务替换投影并记录ACK；返回UI的副本仍需清理 |
| 增量消费者 | [6f95e03](https://github.com/LeafSeamer/leafseamer-sdk/commit/6f95e03df6337678990636b0318f17c074237f58) | 127项、12类实体、3表、25个SQLite场景和3个原子故障点；对象／墓碑、frontier和ACK同提交，精确重复不重放。projection_applied不等于durable_ingest |
| 完整事件选择 | [8bb3c36](https://github.com/LeafSeamer/leafseamer-sdk/commit/8bb3c36cac42e0ee42d023249b2884ea57a49afc) | 2808项、1351模型、201操作（Controller 102／Seamer 99）、52类worker帧、44项共享定义等价；完整选择仍不可宣告为已批准协议 |
| 严格JSON字节入口 | [5a05080](https://github.com/LeafSeamer/leafseamer-sdk/commit/5a0508016e63efc8d4baad9cd4f56c54f7bd5598) | 649项，含30项原始入口计划、200项生成差分、64项并行及22项跨语言数字检查、146个整数节点；数字对照运行版本为Node 24.11.1／Python 3.14.0 |
| JavaScript入口 | [f409799](https://github.com/LeafSeamer/leafseamer-sdk/commit/f409799ceb7a04c0b9fc9606a2c48cd22d308128) | 1951项包含555项依赖文件绑定，并非1951项行为；345项跨语言、200项生成与64项异步检查，Node 24.22.0 |
| 静态校验入口 | [f21ca37](https://github.com/LeafSeamer/leafseamer-sdk/commit/f21ca37a745dd00513ac7d26e7bd59d1e75b9dc6) | 380项主检查、Node和浏览器各331项记录，限5个明确根；没有运行时动态代码生成 |
| 完整正文路由 | [0feafae](https://github.com/LeafSeamer/leafseamer-sdk/commit/0feafae946ecd3aaa24af1309606cdf7d7c9f181) | 163项主检查、2413项独立绑定和2529项跨语言根消息；静态运行7861项，覆盖201操作、52消息、281根。HTTP参数、头和身份权限不由正文通过推定通过 |
| 完整浏览器／Worker | [7675185](https://github.com/LeafSeamer/leafseamer-sdk/commit/7675185575d014d6138c8283dd16eacb94dbd46d) | 144项收据检查；真实浏览器普通／跨源隔离模式各含页面与Worker，普通上下文各7767项且各跳过100项不可用共享缓冲检查，隔离上下文各7867项且不跳过，实际累计31268项。严格CSP阻止eval与内联脚本，17项资产固定 |

前九项为此前已提交成果的集中交接；当前三轮周期是SDK完整正文路由、SDK完整浏览器验证和本Suite交接。第三轮审计后按SDK→Suite推送main。具体身份和统计来源是[manifest](manifest.json)绑定的SDK报告原件；本仓[报告](report.json)只声明本轮实际核验。

## 当前门槛

| 分类 | 已有成果与剩余工作 |
| --- | --- |
| 设计未决 | C01仍需完整语义调用点、跨域引用、权限／面板映射及其他独立通道归并；C05／DF04仍需真实领域来源及资格契约、规范摄取与执行关联、完整生产DDL／GC／迁移方案；C07、C09—C12等实质取舍继续按全系统关闭清单审阅。局部候选通过不能批准全部系统 |
| 实现任务 | 严格解码、完整正文静态路由、浏览器适配和局部快照／增量／释放参考实现已有证据，不再从零建立；TS客户端、HTTP参数／头适配、产品权限提供者、实际HTTP／WS／TLS最终出口、真实业务持久化和GUI投影清理尚未交付 |
| 运行验收 | 历史局部SQLite、Windows子进程、socket和浏览器证据各有明确范围；Linux owner锁、生产并发与故障、TLS缓冲、完整迁移／备份恢复、掉电及真实设备仍未验。后续运行项目不能反向要求在阶段0先完成业务实现 |

完整事件图覆盖12类Record结构，不证明全部领域来源、权限和完整性提供者已经接入。快照／增量ACK证明投影应用，不能触发自动化或解除暂停；规范摄取仍按独立durable_ingest边界。局部journal、消费者与增量表数不能简单相加为生产数据库清单。释放门依赖所有撤权、换代及出口遵守同一门；已交给传输的字节不可撤回。

下一步按[统一关闭视图](../../rebirth-design-closure.md#11-当前关闭状态优先于历轮进展中的旧待办)收敛尚未定义的跨模块契约和实质取舍；已有参考实现只补缺失关联。达到readiness 6.1后按既有授权进入业务实现，不把本文视为阶段放行。

## 复验

在Suite中使用已安装`rfc8785`的Python，SDK路径必须是具有固定提交的真实Git仓库：

```text
python -I -B docs/contracts/sdk-wire-handoff/check_handoff.py --sdk ../leafseamer-sdk --report
python -I -B docs/contracts/sdk-wire-handoff/check_handoff.py --check-report
```

首命令从Git对象读取11个固定提交、核对报告与全部输入、提交祖先关系、完整选择的JCS摘要和模型／根数量，并独立从路由断言重建四个浏览器上下文的检查摘要。包括报告漂移、计数伪改、漏模式、Worker失败、共享缓冲跳过伪标、资产变化及非法路径／浮动提交的反例。它不运行历史11套行为测试，也不重新启动浏览器；历史运行证据来自固定报告。第二条只核对本Suite的输入绑定，不替代第一条或运行验收。
