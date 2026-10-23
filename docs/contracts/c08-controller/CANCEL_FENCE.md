# RUN屏障取消传输覆盖与采用候选

状态：待审阅，99表离线组合。由`build_cancel_fence.py`将[94表共享签发](ISSUE_LEDGER.md)与`cancel-fence.sql`组合，输出`controller-cancel-fence.sql`，旧94表保留历史。移除旧的`ci_run_coverage_pending`临时阻断，以实际集合/ACK/采用约束替代；资源释放的取消分支阻断仍保留。

已知事实：IPC0.8的RUN_FENCE与ACK已有独立cancel_transmissions/cancel_coverage；旧51表屏障尝试只约束普通ce_item和ce_barrier_coverage，94表因此拒绝匹配取消的RUN封存。（来源：[取消IPC](../c02-cancellation/README.md)、`barrier-attempt.sql`、`issue-ledger.sql`。）本候选补该物理缺口，**不表示完整取消执行Plan、ordinary/all关闭、全部资源核销或TIME存储已经完成**，也不批准业务运行。

## 1. 精确选择与持久对象

| 对象 | 字段与关系 |
| --- | --- |
| cf_report | 服务器report_id、permit_id/exit_id复合FK、worker_report_id、disposition/proof、source_digest、原证据、验证回执与审计；同出口原报告身份唯一 |
| cf_settlement | settlement_id、permit_id、never_sent/effect_resolved、报告或屏障来源、验证回执与审计；never_sent必须指精确报告或已封存ACK的该permit且其当前事实为not_sent |
| cf_run_item | fence_id、permit_id、exit_id、entered_known；复合FK绑定真实取消传输及ce_target，与ce_cut_commit延迟配对 |
| cf_barrier_coverage | barrier/fence/exit/permit、disposition/proof；与原屏障尝试及cut item复合FK，与ce_barrier_ack延迟配对 |
| cf_target_coverage | fence/exit/permit、disposition/proof及原件；与原cut和目标结果复合FK，采用时必须精确匹配当前已选ACK |

普通和取消继续共用ci_issue序列。RUN按**取消Requester自身**的origin_authority、origin_database、run_id及generation下界选择，不能借父命令来源；manual不属于RUN。新`cf_expected_item`只选择未核销传输；完整出口集是原准备相关的全部活出口、普通未决出口、取消未决出口的并集。已退役但未决的取消出口仍捕获，活空出口仍有目标。

`cf_disposition`保存全部已提交来源的保守事实：任一可信报告、原ACK或目标结果的in_flight优先；否则有not_sent证明才为not_sent，其余unknown。失败旧attempt的原ACK也贡献强事实，不等采用后才保留。never_sent核销被后来in_flight重开；effect_resolved须独立完成证据，普通传输报告不能自动撤回该结论。原件撤回/复核失效与完整资源风险传播仍待下一布局，不以删除记录实现。

## 2. 原子写集与故障时序

RUN或准备关闭事务写来源deny、原普通集合、完整cf_run_item、ce_cut_commit及来源提交；seal对两类集合分别双向EXCEPT，捕获entered_known快照，取消每出口上限256。超限整个事务失败，不截断集合；产品实现须按既定P0保护处理落盘/容量失败，不得继续旧自动化发送。

seal到来源提交之间禁止新issue、报告、核销、覆盖与原ACK。只禁止覆盖插入还不够：旧覆盖可以先写，再通过插入ACK使它在当前事实视图中生效，因此ACK封存本身也受该窗口保护。上述事实在事务外到达时由writer串行排在cut前或后；不依赖墙钟“差不多同时”。

ACK事务保存普通和取消完整覆盖、原ACK正文、有效tick及审计；两类任一漏项均回滚。ACK已封存后不能补项、改项或替换原文。切点已知in_flight不能降为not_sent/unknown；切点之后的新强事实独立保留，不能通过采用较弱原ACK抹掉。

采用事务保存原ce_result_binding、普通及取消目标覆盖、ce_target_result。只能采用未失败的最新attempt，或精确出口的监督退役证据；两类集合都与所选ACK完全一致。退役只能保持unknown/in_flight，不制造not_sent。全部固定目标采用后，原ce_application才可汇总；空出口也不能省略。

| 故障/竞争 | 规定结果 |
| --- | --- |
| cut缺取消成员、错出口或遗漏退役未决出口 | 事务拒绝，deny与cut不半提交 |
| ordinary覆盖完整但cancel覆盖缺失 | ACK/采用拒绝，不能伪造applied |
| ACK提交后响应丢失 | 按原barrier查询，不换设备许可重发 |
| 旧attempt可靠失败后迟到in_flight ACK | 保存强事实，旧attempt不能替代最新attempt |
| 最新ACK为unknown，旧ACK后来证实in_flight | 原ACK各自不改写，当前风险保持in_flight |
| never_sent核销后迟到in_flight | 重新列入未决；下一cut必须包含，不自动清资源 |
| 全目标关闭、取消效果仍未知 | 可汇总RUN保护，取消效果和资源保持未决 |

## 3. 验证与剩余冻结项

`check_cancel_fence.py --report`执行99表内存组合：cut/ACK/采用逐条缺写及主动异常回滚、Requester精确隔离、普通/准备关闭双入口、退役目标、迟到强事实、原报告/ACK核销、256/257真实成员与不可变约束。预期集合手写，不从待测视图生成；BODY、提供者权威和原始IPC身份为合成前提。`--check-report [--staged]`只比报告声明输入字节，不重跑行为检查。

这五表不是生产迁移：仍需将完整IPC原件严格解码、JCS摘要、端点/序号/tick验证与持久列端到端联接；取消执行Plan、权限/预算、ordinary/all关闭证据仍缺物理FK；资源释放目前仍阻断取消分支。FENCE/AUTH/TIME各自选择器、全部业务锚及时间子域也须同版归并。真实IPC、writer并发、磁盘崩溃、监督器和设备执行均未验证，不能将本轮RUN子域完成扩大为全系统设计完成。
