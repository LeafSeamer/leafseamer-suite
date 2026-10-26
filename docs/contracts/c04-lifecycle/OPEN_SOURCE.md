# 恢复快照与开放前态的完整来源

状态：内部候选，approved=false；仅设计与离线验证，旧批准基线不变。

已知事实：完整换闸路径仍使用占位恢复资源正文；旧开放计划必须引用恢复自身的snapshot，不能另采一个快照便声称原恢复已绑定完整来源。（来源：[完整换闸](TYPED_GATE_FENCE.md)、[恢复采用模型](recovery_close_choice_model.py)、[既有开放布局](../c08-controller/open-storage.sql)。）

本候选从健康关闭与准备核销之后继续：在同一个BEGIN IMMEDIATE事务内读取当前控制、权威、安全代次、全部风险占用及完整归属原件，构造完整ResourceSnapshotRecord，再与RecoveryCloseChoice及全部关闭选择一起封存。未知、未解决、缺归属或旧权威占用拒绝普通恢复，不会清空风险集合；限定取消仍使用独立范围评估。

恢复本身推进安全代次。新快照预计算严格后继cut，其head只引用恢复ID，不引用恢复摘要，避免摘要循环；写入go_recovery后，必须从实际go_hazard及其他物理来源重建快照并逐字段相等，才能写入快照及seal。原件读取继续验证规范字节、自摘要、物理列和完整hold成员。已有双向延迟外键及恢复seal保障缺写不能提交；完整正文验证由参考适配器执行，不宣称任意绕过适配器的SQL写入也获得同等验证。

开放前态读取要求同一数据库事务：按恢复ID读取原完整资源快照，核当前恢复及屏障资格、时钟域、租约与快照时窗、当前控制原件和安全cut，输出与[当前OPEN契约](../c08-controller/OPEN_CONTRACT.md)一致的ControlProjection和GateProjection。控制holder投影只移除存储Principal的kind字段，身份、epoch、版本和protected状态保持；闸仍为fenced。物理Ref使用真实change_id／gate_id、修订和原件摘要。

授权及run／command／time快照ID是显式关联输入，本轮不把ID当作已验证授权或时间证明；没有生成GateAccess、OpenProposal、OPEN_GATE、ReadyCommit或最终发送许可。资源provider身份与外部观察仍为合成，完整身份认证另验。当前域非空恢复全链、实际并发／磁盘崩溃、线路及设备尚未验证。

66项离线验收覆盖空风险的完整健康恢复到换闸和开放前态，另以既有非空归属库核风险集合及候选正文不省略成员，并检查归属撤回和接管后的拒绝；二者不合称非空恢复已贯通。逐写故障、漏写、提交前后观察故障、重入冲突、期限等号、关闭与换闸证明撤回、会话结束、历史查原及旧占位正文拒绝分别检查。原换闸112项及OPEN契约110项回归通过；保留四个最终发送阻断。

交付：[模型](open_source_model.py)、[验收](check_open_source.py)、[报告](open-source-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_open_source.py --report`。本轮沿用既有完整来源及投影Schema和269表布局，不新建平行存储表；授权、三快照持久来源和完整OPEN发送／采用写集仍须继续接通。
