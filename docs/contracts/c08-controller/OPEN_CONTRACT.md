# 当前IPC的完整OPEN契约

状态：0.3内部候选，approved=false；不改变draft.4／IPC 0.3批准基线，不开始业务实现。

已知事实：旧OpenPlan与OpenLifecycle引用IPC 0.8正文；当前全消息候选IPC 0.14已包含GateAccess、ProtectionAssessment及ACK的gate_access_ref。SQLite同时具有普通Ready与限定ScopeCommit两条采用路径。旧ControlProjection又以稳定逻辑ID描述修订，而完整存储原件使用新change_id／gate_id表达后继，不能直接套用旧同ID判定。（来源：[旧格式源](build_open_plan.py)、[当前IPC](../c04-lifecycle/continuation-binding-ipc.schema.json)、[限定存储](build_scope_storage.py)、[完整控制原件](../c04-lifecycle/final_source_bodies_model.py)、[换闸原件](../c04-lifecycle/typed_gate_fence_model.py)。）

本候选保留旧版，使用[新Schema](open-contract.schema.json)精确引用当前IPC的OPEN_GATE及ACK。OpenProposal封装完整计划、控制和闸前态，以及control_authority、authorization、resource_safety、gate_safety四种资格Ref。计划正文必须含完整GateAccess；cancel_only还必须含完整初始ProtectionAssessment，普通用途必须为null。scope依据精确引用评估原件；普通用途沿用activation／resource_recovery／gate_recovery。

| 对象 | 必须保留的关联 |
| --- | --- |
| OpenPlan | 全binding、四个state_refs、恢复或scope依据、当前完整OPEN正文、选择及到期时刻、plan_digest |
| OpenProposal | plan、eligibility_refs、control_before、gate_before、proposal_digest；Proposal Ref使用包络摘要，不能使用plan_digest |
| OpenDispatch | 原Plan Ref、当前IPC完整帧及方向序号、reserved_tick_ns、dispatch_digest |
| OpenAckEvidence | 原Plan与Dispatch Ref、完整ACK、可信接收观察Ref和tick；回显闸身份、三种快照和GateAccess Ref |
| OpenAdoption | purpose、Proposal／Dispatch／Evidence／Access Ref、可空评估Ref、四资格Ref、控制及闸后态、commit_id和提交时刻、adoption_digest |

ordinary只可采用为control.ready与gate.ready；cancel_only只可采用为control.protected与gate.scoped，不能借用限定取消资格宣称普通ready。两条路径都保留holder、mode、control_epoch和effective_version。后态存储原件使用新ID、精确后继修订及新摘要；公开稳定逻辑ID投影是另一层，不能混入这组物理原件Ref。phase与purpose由Schema交叉约束；Ref相等性、摘要和事务事实由关联判定器验证。

计划选择不得早于Access选择；计划到期不晚于Access、评估和闸租约期限。ordinary要求当前完整资源证据；cancel_only使用既有范围评估核对全部风险、保护占用、父命令风险政策、ordinary已关闭且all未关闭。硬保护、撤回、控制变化、快照变化和期限等号均拒绝。提交后按新控制与闸原件判断，不能重跑要求前态相等的提交前判定。当前资格仍不等于最终发送许可。

本轮验收使用相互独立的合成上下文和[正例](open-contract-examples.json)，覆盖ordinary与非空风险的cancel_only，不把允许的父命令风险清成空集合。发送与ACK均要求当前IPC的journal_mode=durable。提交后另核Plan／Dispatch／Evidence摘要、引用链、ACK回显、初始评估、采用时序与物理后继，不凭已提交标志略过这些关系；不重放要求旧前态仍为当前的提交前判定。110项局部检查通过，旧开放计划68项、生命周期103项及范围模型308项实际回归通过。可信状态、身份、库存、时间和观察仍由夹具提供，不能据此声称实际来源已持久绑定。读取current必须由将来的同库提供者保证事务一致；本纯关联模型不取得锁、不执行网络或设备。

后续沿C04收敛项完成：把完整换闸原件与这组前态Ref接入SQLite；为授权、三种快照及资源证据逐一建立完整持久来源；封存Plan／Dispatch／Evidence并绑定全消息日志；分别实现ReadyCommit与ScopeCommit的原子写集及提交后资格。缺少来源时必须拒绝，不用占位正文补齐。新grant、新命令/attempt、当前域非空prepare及最终AdmissionSeal仍待完成。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/build_open_contract.py --check`；`docs/contracts/.venv/Scripts/python.exe docs/contracts/c08-controller/check_open_contract.py --report`。结果及输入绑定见[报告](open-contract-report.json)。
