# Controller 共库与公共运行拒绝账本

状态：待审阅，`controller-storage/0.1.0-draft.1`，仅设计与离线参考。组合[命令裁决11表](../c02-admission/STORAGE.md)、[准备关闭14表](../c04-preparation/STORAGE.md)及[通用运行保护](../c05-protection/PROTOCOL.md)。不是完整 Controller 数据库，也不是产品迁移；尚不包含执行/屏障全部表及P3应用回执。

后续附属候选：[执行登记与运行保护切点](FENCE.md)在本29表后增加17表，组成46表，落实逐primitive/逐传输许可、P2真实登记集合与queued阻止、P3逐出口覆盖和应用回执。347项独立内存检查通过。下文和原262项报告仍描述基础29表；完整资源/命令终态、其他屏障及同cut重试尝试尚未归并，不能据此称Controller完整实现。

## 1. 冲突与本轮具体裁决

已知事实：两个独立子域分别持有 `ca_scope`、`cp_scope`；准备的 `cp_deny_event`仅接受close来源，通用保护尚无对应SQL入口。直接把两份旧DDL拼接，会产生两套库身份，并使通用保护无法加入同一个拒绝账本。（来源：上述两份子域SQL与准备存储第3节。）

推荐在本组合中统一为 `controller_scope` 和 `run_deny_event`。独立子域原件继续保留，不能同时部署新旧表。新物理布局有29表：旧25表减2个scope、1个局部deny，再增加1个公共scope、1个公共deny及5个通用保护表。只有一个实际Controller authority/database和一个全表snapshot_revision；所有来源共用同一个writer。

| 原定义 | 本组合处置 | 不改变的语义 |
| --- | --- | --- |
| ca_scope / cp_scope | 删除两个表及其独立触发器；ca_namespace、cp_request的FK改指controller_scope | 恢复换库不得原地改身份；RequestKey仍包含issuer_epoch |
| cp_deny_event / cp_deny_current | 替换为公共run_deny_event和已提交视图 | floor只增，逐run与全表修订独立，完整启动快照不丢墓碑 |
| cp_deny_guard | 用共同来源/计数守卫替换 | close必须精确绑定原origin/run/代次，不能指另一准备 |
| cp_commit的拒绝存在性检查 | 可引用本close待提交行，或任一来源已提交的更强拒绝 | 未提交的另一操作不能作为持久保护证明 |
| ca_其余10表、cp_其余12表 | 保留约束和字段；只改上述公共身份/拒绝引用 | 受理与永久拒收排他、唯一签发、回执保留及关闭状态不变 |

`controller_scope.layout_version`标识该物理组合；HTTP contract_version仍在完整请求BODY中按具体操作验证，不能用物理版本替换协议协商。无旧数据迁移要求；本组合是新版空库候选，不自动转换旧NodeCG或此前实验库。

## 2. 通用保护的持久输入与写集

| 表 | 输入字段与拥有者 |
| --- | --- |
| run_protection_request | 内部protection_id、唯一origin authority/database/operation_id、run_id、generation、完整request_digest/selector_digest/target_set_digest、request_body；当前授权、registry快照及容量预留BODY；完整出口target_count |
| run_protection_target | protection_id/target_id唯一；完整出口身份、冻结许可账本及关联摘要的target_body |
| run_protection_commit | protection_id与固定Controller commit_ref_body；与request、audit、outbox双向提交 |
| run_protection_audit | 保护操作的脱敏审计BODY，不记录凭据或隐藏设备原文 |
| run_protection_outbox | 不可变事件ID与保护意图BODY，只投递相同RUN_FENCE/查原；不是设备命令队列 |
| run_deny_event | scope由本库固定；完整origin/run、floor、deny_revision、snapshot_revision；两种互斥来源：准备close_id/commit_id，或通用protection_id |

`ProtectionRequest.target_set_digest`对应Seamer提供的ControllerTarget子集，**不等于**Controller当前/历史出口的账本摘要。本表target_count是本Controller冻结出口数量；不能用HTTP数组数量替代它。registry_snapshot_body还须绑定Controller本地登记高水位与完整双向差集结果。SQL只保证提供的集合数量、唯一性与冻结，不从占位BODY证明全集。

P2在单个短事务内先复核当前配对权限/对象归属及固定原请求，然后写 request、完整 targets、必要deny_event、audit、outbox和commit；commit最后插入。既有同键请求先比较完整摘要，异内容409，原件只读返回。当前有保护权即可收紧，不要求旧RunGrant仍有效；拒绝操作的幂等重投不扩展到设备命令。

两种来源必须二选一，不能为通用保护虚构preparation，也不能为准备关闭虚构HTTP请求。来源三元组/代次须与原操作一致。新floor严格大于当前floor时分配全局snapshot_revision和该run的deny_revision各自的精确后继；相同或更低floor不新增deny行，但原保护操作、完整出口与审计仍分别持久。

本组合只补P2的请求、完整目标容器、拒绝权威及outbox持久结构。P2仍须与真实queued阻止、完整旧出口/intent登记及切点表同事务组合；P3的coverage/监督证据、应用回执与资源归类尚未在此定义。不能以本表已commit便对外宣称applied，不能以target_count=0跳过持久deny。

## 3. 可见性、启动快照与恢复

`run_deny_committed`只含其来源已配对提交的deny；`run_deny_current`取每个origin/run最高floor；`run_deny_snapshot_revision`取全部已提交记录的最高snapshot_revision，空表为20个零，线上转换为`"0"`。原准备的accepted/applied准入守卫改读该同一视图。旧accepted遇通用保护后不能签发，close遇既有通用保护则复用更强floor。

OPEN_GATE仍由同writer边界取得完整有序快照，并通过SDK计算规范摘要；这里的视图不是IPC消息，数据库padding不得直接发到线上。4096个run/每目标256许可及全批字节/P0预算沿用保护协议；超限保持关闭，不能删旧行或分页面开闸。新增run之前必须预留可保护容量，SQLite表能插入不等于产品容量许可。

提交前异常必须使请求、目标、拒绝修订、审计和outbox全体回滚。提交后回执丢失查原，不重新分配snapshot_revision。重启默认关闭，重投同一保护意图；新进程不能替旧出口声明not_sent。旧grant或applied回执仍为历史，不能恢复OPEN_GATE；in_flight/unknown不因保护登记而释放。

原裁决初始Command不含完整可查询的自动化运行投影，因此本组合**没有**用SQL替代Controller命令/最终发送门控。下一执行表设计必须把原admission_binding、准备、grant、run、epoch及permit绑定到这个共同deny权威，不能另建第三份floor。当前手动命令仍由其自身权限和资源门控判定，运行保护不改变holder/control_version。

## 4. 生成方式、验证与剩余门槛

[common.sql](common.sql)是新增公共结构唯一源；[build_layout.py](build_layout.py)只对两个固定输入执行上表声明的具名替换，使用SQLite完整语句边界保留CASE/触发器，不是通用SQL转换器。[controller.sql](controller.sql)是生成物，不直接编辑。原子域文件不修改；源布局变化使精确命中断言失败时必须重新审阅，不能跳过替换。

[check_layout.py](check_layout.py)实际加载生成的29表，262项检查通过：两子域原路径可提交、两类保护相互复用及交替抬floor、不同origin/run隔离、空出口仍拒迟到准备、完整写集缺写/逐写主动异常回滚、scope唯一与不可变、来源排他、状态可见性及目标冻结。混合入口故障从另一入口已有floor开始，逐切点核对旧权威和修订完整保留。它复用原参考器的合成写入步骤，预期结果独立手写；原159/430项另外在其原布局中通过，不称为全部在组合库中重跑。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_layout.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_layout.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_layout.py --check-report --staged
```

[layout-report.json](layout-report.json)绑定本目录五份资料、两个原SQL、两个原参考脚本及来源协议Schema，共10份输入（common.sql计入本目录五份，报告不绑定自身）。报告输入核对不重跑；原子域继续独立复验。内存SQL及串行先后顺序不证明真实并发、鉴权、完整目标提供者、WAL/磁盘、实际IPC或设备。

当前执行/保护进展及剩余项以[FENCE第6节](FENCE.md#6-验证范围与下一步)为准；P1/P4跨服务持久映射、来源重基线、P0/GC与SDK同版归并仍待完成。统一scope与deny的布局缺口由本组合推进，不能再要求各模块独立建立它们，也不能据此关闭全系统设计。
