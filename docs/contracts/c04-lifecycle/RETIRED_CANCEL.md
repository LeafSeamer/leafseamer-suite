# 跨域取消准备的监督退役来源

状态：内部设计候选，approved=false。保留已批准 draft.4／IPC 0.3 与旧同域候选；没有业务服务、真实设备或生产准入变更。

已知事实：准备切点 SQL 原来将所有成员的请求、撤销 tick 与切点提交 tick 直接比较；时钟重建后这些数值不再属于同一域。现有 RetiredCloseSet 已重建同 worker 全出口、准备授权、编码帧和撤销原件，并绑定完整监督退役采用。（来源：[原准备守卫](../c08-controller/prepare-deny-storage.sql)、[退役集合模型](retired_close_set_model.py)。）

本候选的处理方案是显式记录每个跨域成员的退役来源。新选择正文格式为 retired-cancel-source/0.1.0-draft.1，含原 CancelPrepareSource 作为 selection，以及按 prepare_id 排序且精确覆盖跨域成员的 retirements。旧同域正文不变，不做旧库自动迁移。

| 字段 | 语义 |
| --- | --- |
| selection | 固定 scope、设备、Cut Ref、注册水位、控制记录、新域与选择 tick |
| prepare_id、exit_id | 本库已登记准备及其旧出口，不接受外部声明替代原件 |
| authorization_id、authorization_digest | 原编码授权的精确身份；沿用编码域 Id 词法，不能套用对外设备 Id |
| completion_ref | 完整 RetiredCloseSet 的内部存储 Ref |
| adoption_ref | 该出口的完整监督退役采用 Ref |
| revocation_ref | 原准备撤销 Ref；不生成新域下伪造的旧域撤销时间 |

上述对象禁止额外字段，全部字段必填；1—4096条退役成员且不截断，正文不超过16 MiB。存储 Ref 的 ID 是本库查询键，可以带点，不能直接当作新的对外 API 身份。

签发时必须在同一 BEGIN IMMEDIATE 中核对完整来源：退役集合覆盖该出口和准备、授权与撤销相符、当前采用未撤回；其 evaluator_descriptor 必须等于本次新域，退役观察 tick 不晚于本次选择 tick。只在评估域内比较这两个 tick，不将旧域请求或撤销 tick 改写为新域值。更晚的第三个时钟域不能借用第二域的证明，仍须独立的可信采用方案。

新 crp_member 表保存精确证明、审计与关系键，与 pd_member、pd_cut_commit 配对。安装器核对原 pd_cut_seal 的完整 SQL，再原子安装限定例外：只有当前有效 crp_member 允许取消切点免除该旧域成员的数值比较；其他切点与同域成员仍使用原门槛。独立 seal 守卫检查证明数量、完整跨域集合、退役有效性及域绑定，不能省略证明后依靠一个更大的新域 tick 通过。Schema、SQL关系和应用层完整摘要重建共同约束，SQL关系不等于可信来源认证。

新事务仍封存全部目标和传输，写准备集合、跨域证明、必要的同域撤销、两处 seal 和拒绝事件。跨域成员必须已有完整退役关闭集合与原撤销，不新发 DENY、不释放缓存、不退款、不改变普通传输事实或业务状态。任一写入失败或缺失，全事务回滚。

历史查原重建原选择与不可变原件；证明后来撤回不删除已提交取消或拒绝墓碑，同 ID 重入只能返回原件。新签发及 OPEN 前态重新核对来源当前有效性；撤回阻止恢复，不能把历史可读解释为重新获得资格。最终 writer 仍须重新读取全部准入条件，当前来源不替代 OPEN 发送、Ready 或最终许可。

故障验收覆盖跨域小 tick、完整非空恢复来源、缺证明／多余成员、错评估域／描述／授权、观察时间越界、逐写／漏写回滚、提交观察丢失、seal 前撤回、提交后撤回、不可变原件与损坏正文。现有同域验收继续回归。实际运行结果与输入摘要见[报告](retired-cancel-report.json)，复现命令为 `docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_retired_cancel.py --report`。

交付：[生成器](build_retired_cancel.py)、[Schema](retired-cancel.schema.json)、[关系与守卫](retired-cancel.sql)、[生成的seal](retired-cancel-seal.sql)、[模型](retired_cancel_model.py)、[验收器](check_retired_cancel.py)。真实监督进程、OS观察、跨连接并发、强杀／掉电及设备效果未在本轮验证；完整链仍未签发普通传输或最终 OPEN。
