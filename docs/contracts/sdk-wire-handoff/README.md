# SDK面板结果、完整选择与客户端兼容交接

本交接固定SDK `eef557ddfcf8cc53bf1c7258502e841b96accb1b`及其十六个前序成果提交，供Suite核对实际交付与阶段门槛。当前仍处阶段0：以下均为隔离参考实现或候选契约，未批准为运行协议，未交付生产SDK或业务服务。旧交接保留各自固定提交的历史边界；当前进度以本交接和[readiness 6.1](../../rebirth-readiness.md#61-全系统设计完成门槛)为准。

## 固定成果

各报告的检查数包含结构、输入绑定、反例或运行检查，不能相加作为全系统覆盖率。manifest固定每份报告及其全部输入，共923项Git文件绑定；同一文件在多个包中的绑定分别保留。另核对555项HTTP校验依赖与2,009项类型工具依赖的摘要记录，共2,564项；这些安装文件不在Git中，本轮未重新安装，不能计作已读取其实际字节。

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
| 完整HTTP信封 | [1c292c8](https://github.com/LeafSeamer/leafseamer-sdk/commit/1c292c88462013d3d7b9450dcbe91b84f0db90ca) | 44项主检查、9159项独立绑定、2204项参数变体；201操作、2148响应、58种参数定义，静态运行12076项及10次真实回环HTTP。原始路径／查询／头、精确选择和正文联合校验；不授予业务权限 |
| TypeScript与单次客户端 | [201f88b](https://github.com/LeafSeamer/leafseamer-sdk/commit/201f88b3ee60bf37ff8baabb70ba1ea1c840439e) | 223项主检查、862项运行断言、20条逐行编译负例和2次真实回环HTTP；两端各1351模型，197个普通HTTP调用，4个WS操作保留类型；递归类型通过严格编译。发送后失败或取消标记结果未知，不自动重试；生产鉴权与新客户端浏览器验收未执行 |
| 完整外层授权 | [436728a](https://github.com/LeafSeamer/leafseamer-sdk/commit/436728a3a113daebae502f8997f20f734942e5b6) | 655项静态检查，201操作／245分支、62登记守卫（61活跃）与12提供者；保留完整认证OR/AND、当前权限、对象与释放复核。票据签发显式绑定已有订阅；不执行真实鉴权或事务 |
| 面板当前输入 | [cf2d074](https://github.com/LeafSeamer/leafseamer-sdk/commit/cf2d074b0b8307d74a1ebec8b092f9d94d1f9dbf) | 771项格式及映射检查，35方法、28类领域规则及35完整HTTP合成映射；取消StateRef、完整转交主体、run/slot修订与句柄归属显式迁移。新0.3候选未安装，结果投影、真实句柄与确认事务未执行 |
| 面板当前结果 | [5209d06](https://github.com/LeafSeamer/leafseamer-sdk/commit/5209d06af1d91dbb41923d28f33943ed3c0158be) | 652项检查，21视图／23变体、35方法、181顶层字段来源及14提供者；Draft／Published及Grant／Lifecycle显式分型。真实投影、提供者、数据库、浏览器、网络、设备实测均为0 |
| 面板完整归并 | [eef557d](https://github.com/LeafSeamer/leafseamer-sdk/commit/eef557ddfcf8cc53bf1c7258502e841b96accb1b) | 5972项检查，1463模型、201操作（含4个WS）、35方法与19面板消息；输入／结果整文档SchemaRef、Registry及激活绑定固定。17投影订阅、2失效通知，写入与评估不可订阅；真实提供者与投影未运行 |

此前十五项保留各自固定提交的证据范围；当前三轮为SDK结果、SDK完整归并和本Suite交接，按SDK→Suite推送main。身份及统计来源为[manifest](manifest.json)绑定的SDK原件；[本仓报告](report.json)包含117项交接检查，[消费者记录](consumer-report.json)单独保存本轮实际运行的17项构造检查。

当前完整候选是`leafseamer.api.v1.panel3`，摘要`sha256:eba90989adcae8a5e5a8b361643f4a338b3f74bfec05cfbd778f368d68786963`。它归并当前输入／结果、Registry、Bundle、服务Intent／Receipt、激活和订阅，仍未批准、未安装且不可广告。存储与真实提供者不会因格式归并而自动完成。

| 消费者 | 当前绑定 | 对panel3的实际结果 |
| --- | --- | --- |
| 正文解码器wire-routing | events2 | 构造拒绝，须重建 |
| HTTP适配器http-envelope | events2 | 构造拒绝，须重建 |
| 类型客户端typed-client | events2 | 构造拒绝，须重建 |

三个入口均能用原events2选择构造，并拒绝panel3、错误摘要及交叉混用ID／摘要。本轮Node 24.22.0在禁止动态代码生成下执行，传输调用为0；构造成功不证明业务请求成功。固定快照文件与Node可执行文件摘要存于消费者记录，实际加载的是探针引用的模块。旧HTTP回环和四浏览器上下文记录仅适用于events2，不能视作panel3运行验收。

## 当前门槛

| 分类 | 已有成果与剩余工作 |
| --- | --- |
| 设计未决 | C01已有201操作外层授权及35面板当前输入登记，仍需完整语义调用点、跨域引用、真实提供者接口细化、动态Schema和不可变发布内容／metadata的持久关联与其他独立通道归并；C05／DF04仍需真实领域来源及资格契约、规范摄取与执行关联、完整生产DDL／GC／迁移方案；C07、C09—C12等实质取舍继续按全系统关闭清单审阅。局部候选通过不能批准全部系统 |
| 实现任务 | 严格解码、完整正文路由、HTTP参数／响应头校验、197操作TS客户端和局部快照／增量／释放参考实现已有证据；生产传输与鉴权提供者、WS客户端生命周期、协商预算接入、真实业务持久化、panel3静态消费者重建和GUI投影清理仍待交付 |
| 运行验收 | 历史局部SQLite、Windows子进程、socket和浏览器证据各有明确范围；Linux owner锁、生产并发与故障、TLS缓冲、完整迁移／备份恢复、掉电及真实设备仍未验。后续运行项目不能反向要求在阶段0先完成业务实现 |

完整事件图覆盖12类Record结构，不证明全部领域来源、权限和完整性提供者已经接入。快照／增量ACK证明投影应用，不能触发自动化或解除暂停；规范摄取仍按独立durable_ingest边界。局部journal、消费者与增量表数不能简单相加为生产数据库清单。释放门依赖所有撤权、换代及出口遵守同一门；已交给传输的字节不可撤回。

下一步按[统一关闭视图](../../rebirth-design-closure.md#11-当前关闭状态优先于历轮进展中的旧待办)收敛尚未定义的跨模块契约和实质取舍；已有参考实现只补缺失关联。达到readiness 6.1后按既有授权进入业务实现，不把本文视为阶段放行。

## 复验

在Suite中使用已安装`rfc8785`的Python，SDK路径必须是具有固定提交的真实Git仓库；Node需支持禁止动态代码生成选项：

```text
python -I -B docs/contracts/sdk-wire-handoff/check_handoff.py --sdk ../leafseamer-sdk --node /path/to/node --report
python -I -B docs/contracts/sdk-wire-handoff/check_handoff.py --sdk ../leafseamer-sdk --report
python -I -B docs/contracts/sdk-wire-handoff/check_handoff.py --check-report
```

首命令从固定Git原件生成隔离快照，实际运行17项客户端构造检查并保存独立记录；快照留在忽略的logs目录供核查。随后执行117项交接检查。第二条核对固定提交、全部文件摘要、来源原件、祖先关系、历史断言身份、完整选择JCS与制品字节、35方法SchemaRef和激活绑定、21视图字段来源及兼容矩阵，读取已有消费者记录而不重跑构造。主报告的selection_consumer_probe_rerun因此为false，不掩盖首命令单独记录的实际运行。

交接反例覆盖报告与资产漂移、漏模式、Worker失败、共享缓冲跳过伪标、非法路径／浮动提交、WS普通调用伪标、权限降级、输入和结果字段遗漏、未知提供者、自动安装、兼容资格伪改及探针记录漂移。历史17套SDK测试、依赖安装、浏览器和设备不在交接命令中重新运行。第三条仅核对本Suite输入绑定，不能替代前两条或运行验收。
