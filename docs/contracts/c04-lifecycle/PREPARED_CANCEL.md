# 当前运行布局的取消准备切点与恢复来源

状态：内部设计候选，approved=false；保留既有批准契约，未修改业务服务。完整 OPEN 发送、Ready 采用和最终许可仍未完成。

已知事实：当前 Controller 布局要求 cc_cut 与 pd_cut 双向配对，准备全集核销后才能提交取消切点。上一轮完整恢复夹具使用旧标识，不能直接作为当前取消 IPC 的正例。（来源：[准备拒绝布局](../c08-controller/prepare-deny-storage.sql)、[组合生成器](../c08-controller/build_prepare_deny_storage.py)、[上轮快照边界](COMMAND_SNAPSHOT.md)。）

本轮在首次登记前选择合法设备、启动代次和 socket 身份；从实际 Seamer 请求、Controller 受理、固定 attempt 库存和编码登记开始，经过保护、监督退役、新域关闭与恢复，再读入非空运行及命令拒绝快照。所有模型和 SQL 守卫正常执行，没有改写历史数据库、关闭守卫或放宽 Id 校验。身份与 OS、时钟、权限观察仍为合成提供者，属于离线集成证据。（来源：[完整夹具](current_open_fixture.py)、[验收器](check_prepared_cancel.py)。）

## 冻结候选字段

两个新增具名定义由现有生成器输出到 [取消来源 Schema](cancel-source.schema.json)，不创建新的线上 IPC 版本。

| 定义／字段 | 约束与含义 |
| --- | --- |
| CancelPrepareContext.clock_domain_id、descriptor_digest | 当前控制变化记录对应的精确时钟域与描述摘要 |
| CancelPrepareContext.selected_tick_ns | 规范十进制 Counter；同域且不早于当前控制变化 |
| CancelPrepareSource.format_version | 固定 cancel-prepare-source/0.1.0-draft.1 |
| scope、device_id | 原取消父命令所在 Controller 与设备 |
| cut_ref | 完整 CancelCut 的 ID、固定修订 1 和摘要 |
| prepare_head | 同一写事务锁定的 pd_registration 最大 sequence，字符串计数 |
| control_change_id | 本库不可变控制变化记录的查询键，1—256字符；不是对外设备 Id |
| clock_domain_id、descriptor_digest、selected_tick_ns | 原样封存的选择上下文；重复查原不能刷新 |

上述对象必填字段完整，禁止未知字段。Schema 只证明形状；实际读取还须按已封存控制变化、准备注册与撤销原件重建。

## 原子写集和历史规则

完整布局的 capture 必须带 prepare_context；基础取消布局不接受无效的附加上下文。单个 BEGIN IMMEDIATE 写入 cc_cut、目标、传输成员及取消准备，然后写 pd_cut、完整 pd_member、必要的 ep_revocation、pd_cut_commit，最后 cc_cut_commit。cc_cut 的 prepare_cut_id 由 cut ID 确定；pd_cut 的选择正文固定引用该 Cut，避免两个摘要相互引用。

准备成员来自 pd_expected 在锁定 prepare_head 下的完整集合。ordinary 选择父命令的普通准备；all 选择父命令全部准备。每个成员的出口、授权 ID 和授权摘要必须精确匹配，最多 4096，不截断。已有撤销保留原件；没有撤销时在本事务追加撤销、审计与通知。撤销不等于释放资源，不创建 ep_release，也不证明 worker 已处理 DENY。取消屏障关闭和资源释放继续使用原完成证据门槛。

read_cut 读取封存的准备选择正文、两处 seal、摘要与列，并按历史 prepare_head 重建成员。选择上下文绑定当时的不可变 control_change_id，不使用现在的域重写历史。同 ID 重试只能用原上下文查原；新域仍可读取旧域历史，不自动产生新执行权限。提交结果不确定时先查原，不换 ID 重发。

## 时钟边界和故障时序

准备请求提交 tick 与撤销 tick 只能在同域比较。本候选要求所选准备出口的域及描述摘要与选择上下文一致；不允许以新域较小或较大的 tick 核销旧域准备。跨域准备需要补充监督退役及时间证明的独立契约，本轮保持拒绝，不能把数字比较放宽成支持。

正向时序是在旧域受理取消，封存 ordinary/all 及非空准备集合，再监督退役并创建新域出口；恢复快照引用已封存的命令拒绝快照。这样历史读取不跨域比较 tick，新 worker 的开放前态仍携带旧命令拒绝墓碑。真实恢复链若引用同数量但较旧的 ordinary 快照，在 all 水位推进后必须拒绝。

故障时，任一 Cut、准备成员、撤销或 seal 漏写／异常都回滚整笔事务，取消受理保持 pending，不产出假的完整快照。原始 SQL 的延迟外键和 seal 守卫继续有效；应用层还核对完整字节和来源，因此重算选择正文摘要不能将历史控制记录换成另一个时钟域。

## 验证范围

验收覆盖实际 275 表恢复链的双非空快照、非空准备成员、既有撤销与新撤销两条写集、逐写及漏写回滚、历史重入、Schema 正反例、重算摘要错域、真实恢复旧水位拒绝和跨域失败关闭。已有 123 表非空普通／取消传输验收继续作为回归；本轮完整链的命令已有编码准备但尚未签发普通传输，不能把它称为所有在途传输及设备效果的端到端证明。

交付：[Schema 生成器](build_cancel_source.py)、[原件模型](cancel_source_model.py)、[报告](prepared-cancel-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_prepared_cancel.py --report`。准备跨域退役核销、授权与参考时间最终来源、OPEN/Ready、真实设备和系统级验证继续保留在实施前清单。
