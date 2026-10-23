# 限定取消评估与开放采用的持久候选

状态：设计与离线参考资料，未批准部署。以[独立换闸](GATE_RENEWAL.md)的186表为底层，在同一物理`go_gate`增加`scoped`状态与八表，组成[194表候选](controller-scope.sql)。不改变历史SQL、已确认draft.4或IPC0.10的字段；普通ReadyCommit与取消ScopeCommit分型，四个最终签发阻断继续保留。

## 已知事实与修订

既有[范围模型](SCOPED_GATE.md)允许父命令unknown时只开放指定取消，但共享库只有普通T5。普通`go_valid_snapshot`拒绝父unknown，不能直接套用到保护取消。`go_snapshot`已逐项绑定原Owner并核对`cr_risk_hold`全集，适合作为两种资格共用的事实来源。（来源：[归属SQL](ownership-storage.sql)、[开放SQL](open-storage.sql)。）

本轮修订：初始资源评估先采样，随后选择并封存引用它的GateAccess/OPEN计划；必须`sampled_tick <= selected_tick <= now < assessment.expires_tick`。旧局部判定器把初始采样下界写成Access选择时刻，允许引用未来才取得的初始评估，却误拒先采样后选择；本轮修正判定器及独立正反例。后续Guard的新评估可晚于选择时刻，采样不早于初始评估，不能延长原Access。Access截止可晚于单次评估截止，但OPEN派发、采用和每次发送均需当前未过期评估。

## 物理字段与不变量

| 对象 | 持久字段与关联 |
| --- | --- |
| gs_policy / gs_parent_class / gs_policy_commit | `policy_id`绑定真实`cg_plan.execution_id`及完全相同的`policy_ref_body`，保存政策截止、提供者回执和允许父风险分类；成员封存不可增补。允许集合为空表示不允许任何父ordinary风险，不伪称无需证明批准政策完整性 |
| gs_assessment / gs_assessment_commit | 三元`assessment_id/revision/digest`绑定已提交`go_snapshot`、政策和真实取消Ownership；分别保存资源安全与闸安全的`id/revision/digest`六字段，连同提供者回执、完整正文封存 |
| gs_access | 三元`access_id/revision/digest`、唯一`plan_id`与初始评估；与`go_plan_commit`同事务，不能事后增加或替换。出口、控制、授权、两安全Ref及取消Scope通过初始评估和实际计划联接，不建立另一个物理发送闸 |
| gs_scope_commit | 唯一Access、原OPEN ACK、控制change及输出gate，采用tick与正文；控制提交反向配对，输出闸也反向绑定本记录。当前GUI保持protected，控制holder/epoch/effective_version不变 |
| gs_revocation | policy/assessment/access三种精确原件撤回，原件必须实际存在；同事务进入共享`go_hazard`并保存通知正文，不删除历史、不释放hold |

两安全Ref保留独立身份，不能用一个`go_hazard.revision`冒充两份权威。当前实现仅将该本机水位作为共同失效栅栏，并比较两组三元字段；两Ref的真实提供者、原件内容及水位映射仍由最终提供者外验，非空BODY和摘要形状不证明真实性。授权快照、完整硬保护与政策批准回执亦同。此边界不减少最终产品要求。

`gs_current_assessment`复用完整风险全集：自身取消hold必须active并属于当前Requester；其余只容许同父命令的ordinary hold，保留原Owner且来源未撤回。分类从当前命令事实重核，unknown优先于unresolved，不能自行重标active；政策必须允许该分类。相同父下另一取消、无关风险、stale、缺项/多项和超过256项均不能通过。没有父attempt时只保留取消独立hold，不能伪造普通历史。256只是候选上限，不是生产容量批准。

当前无pending接管、ordinary关闭原件有效、all未开始、取消仍requested、动作图未停止、出口存活及同运行域、资源硬保护不存在，都是必要条件。普通`go_valid_snapshot`与ReadyCommit条件保持；取消资格不反向放宽普通资格。

## 同一写闸的时序和事务

1. 封存政策和完整评估；初始评估来自当前`go_snapshot_commit`，旧快照不采用。
2. 同事务写`go_plan(basis_kind=scope)`、`gs_access`及`go_plan_commit`；activation/resource_recovery/gate_recovery必须全空。当前物理闸须fenced，来源是有效独立换闸或首次控制屏障；旧关闭ACK不能制造新屏障。
3. 继续使用唯一`go_dispatch`保存OPEN原字节及出站预约。入流前核原初始评估仍当前且期限有效；不是第二条取消发送路径。
4. `go_evidence`增加可空的Access三元回显：scope必须完整匹配实际Access，ordinary必须全空。迟到ACK可存为历史，不能跳过采用时的重新核验。
5. ScopeCommit事务写ct_change、保持protected的ct_state、`go_gate(scoped)`、`gs_scope_commit`及原控制审计/outbox/commit；最后seal重新核初始评估当前性、前态CAS、原ACK、期限、当前屏障、撤回和输出闸。采用后go_authority不把显示投影当新授权。
6. `gs_scope_candidate`允许后续完整评估刷新，但政策、Owner、取消执行、初始撤回状态、控制/授权/安全代次和三个安装快照必须与原Access一致。候选视图没有实时now；最终AdmissionSeal仍须在同事务核当前tick及完整Guard、预算、时间、packet和共享issue。

新异常、接管、all关闭、Owner/政策/评估/开放ACK/屏障证明撤回均撤销资格。新评估不能复活已撤初始依据；普通ready与限定范围互换须重新关闭、换屏障和开放。通知BODY不代表worker已经关闭，入流前缀仍有传播窗口。提交不确定时只查原，重启不重放Access或设备许可。

## 验收与证据边界

[检查器](check_scope_storage.py)执行内存SQL的完整配对、缺写及主动异常全库回滚，覆盖父未发与父unknown、真实T3/T4后旧Owner保留、范围采用不升普通ready、原ACK错引用、初始采样先后、期限等号、两安全Ref分别改变、最后seal前撤回、接管/all关闭与各原件撤回、八表UPDATE/DELETE/REPLACE不可变。

父unknown夹具先提交合成历史普通发送与bootstrap/Owner同事务，再走命令unknown、控制接管与取消关闭。所有触发器和外键保持开启；它证明后续范围联接，不证明产品普通最终准入已实现。没有在真实设备发送、网络IPC、并发writer、磁盘掉电或OS监督环境运行。旧48帧的结构回归另记，不当JSON至SQL端到端证明。

剩余冻结项：完整AdmissionSeal和逐许可Guard/预算/packet联接、两安全Ref可信提供者映射、统一全部关闭来源及全消息序号账本、SDK/API同版归并。正常父hold释放后的新完整评估已有局部模型证明，本SQL轮只验证完整新快照更新，尚未覆盖从真实父资源释放写集到下一Guard的全链。阶段0未关闭，不能将临时阻断作为最终产品删减。

复验：`python docs/contracts/c08-controller/build_scope_storage.py --check`与`python docs/contracts/c08-controller/check_scope_storage.py --report`；`--check-report --staged`只验证报告声明输入的原字节。
