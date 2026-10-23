# 来源保护HTTP与完整执行IPC归并候选

状态：待审阅；不修改已确认draft.4／IPC0.3、面板IPC0.4或本目录原局部0.1。本批将[来源保护方案](README.md)连接到[面板执行协议](../c09-panel-ipc/IPC_GUARD.md)，生成独立`protection-service/0.2.0-draft.1`与`ipc/0.5.0-automation-draft.1`。完整是指21种消息格式，不表示全部业务模型、SDK或运行已完成。

## 已知格式冲突与推荐修订

旧公共RunBinding和RunGrant的definition_version是Version，新的自动化程序/生命周期及AutomationOriginBinding使用正十进制计数。推荐在本候选RunBinding/RunGrant统一为PositiveCounter，arm_generation和grant修订使用严格Counter，拒绝前导零及尾换行；capability_version等软件/能力版本仍为Version，不能全局字符串替换。新RunGrant增加origin_scope，避免不同Seamer数据库的同run_id借用资格。原公共文件保留原值，所有新写端点必须精确协商版本；其他沿用旧Schema的词法缺口仍由DF01统一修订，本批不能证明严格原始JSON解码已完成。

旧面板IntentRef没有完整运行来源。新CommandRequest、ExecutionGuard及DispatchPermit均带同一完整AutomationOriginBinding；IntentRef另带origin、完整binding及其摘要，GUARD_ACK回显该摘要。manual必须null，automation必须非空；面板仍只允许human/manual，不能由面板字段转成组织自动化。新增内容参与原命令身份投影和完整Guard摘要：身份仍仅剔除顶层context_id、idempotency_key、correlation_id，不能忽略automation_binding或递归删除同名业务键。

Controller从持久受理记录取得绑定，核对配对Seamer、准备记录、RunGrant、原execution_ref及完整请求；worker只消费可信Controller已绑定的记录。比较链包括origin_scope、run_id、定义计数、arm_generation、execution_id/ref、step_id与logical_action_id。Guard授权中的grant_id/revision及arm_generation、Permit、CommandRequest.run_binding与RunGrant必须一致；device/action范围及当前权限/时间/资源仍须独立通过。摘要相等不是权威来源证明。

## HTTP操作与恢复身份

| POST接口 | 输入与结果 | 语义 |
| --- | --- | --- |
| /internal/automation/protections | ProtectionRequest → ControllerProtectionRecord；首次202，重复200 | 仅可靠受理拒绝操作；accepted/fencing/applied/indeterminate保留；applied必须有Controller回执，不表示资源清理 |
| /internal/automation/protections/lookup | ProtectionLookup → found/record、not_found/null或indeterminate/null；200 | 完整controller_scope、origin_scope、operation_id、selector_digest及target_set_digest查询原件，不创建动作 |

两个接口均要求精确版本头、配对mTLS、当前automation.protect权限及origin_scope所有权，所有响应no-store。source provider不能调用；原RunGrant过期/撤销不能阻止具有当前保护权限的Seamer收紧拒绝。身份失效则走既有监督保护，不伪造授权。400/422格式错误、401认证失败、403权限/归属拒绝、409同键异内容、413请求过大、429保护容量不足、503结果暂不可确认；协议版本错误由400/version表达。错误正文不含隐藏运行或原请求内容。

幂等键仍为(controller_scope,origin_scope,operation_id)，完整请求摘要固定；查旧前仍先鉴权。同键改selector/目标/basis/detector域/plan_ref均409，不能借“更保守”改写旧操作。需要增强或从紧急记录补建持久plan时用新operation，并引用/保留旧记录。lookup未发现不授权重发设备动作；原身份单调拒绝可重投，但HTTP客户端不能泛化为所有POST自动重试。

## 21种IPC、完整来源与启动拒绝快照

生成物保留原19帧及面板selector，增加RUN_FENCE、RUN_FENCE_ACK；它们使用完整运行域、Controller/worker/IPC/device身份、seq及reply_to信封。RUN_FENCE为Controller→worker、reply_to=null；ACK反向且reply_to精确关联。QUERY_BARRIER按原operation/barrier查询冻结结果，以同种ACK回显，不重新计算空清单。运行selector独立于AUTH_FENCE的身份撤销selector，防止借通用撤权权限操作其他Seamer。

HELLO与HELLO_ACK增加必选特性automation_origin_binding、run_generation_fence、run_deny_snapshot；必须保留面板及历史必选特性。缺特性不开放自动化。新旧版本不混投，不能剥掉新增绑定降级。

OPEN_GATE增加完整RunDenySnapshot：controller_scope、snapshot_revision、entries、snapshot_digest。每项为selector/deny_revision，按(origin authority,database,run_id)排序且唯一；覆盖本Controller当前持久拒绝表，包括现无命令的墓碑。snapshot_revision为拒绝表整体修订，每次实际抬高/新增下界精确递增；每run的deny_revision是该行独立修订，不能与snapshot_revision互换。空全集也有固定摘要，不能省略。OPEN_GATE_ACK回显revision/digest。

Controller在开闸串行边界取完整快照并绑定gate_token；与保护事务同时发生时按原writer/仲裁顺序处理。worker先核对可信来源、完整集合、当前域和版本，再原子安装本地拒绝表后开闸；不能先open再异步拉下界。已经收到更新RUN_FENCE时，旧快照不得降低任何行的deny_revision/floor或漏掉已知行；拒绝旧OPEN_GATE，Controller重新构建新的开闸操作。ACK后又发生新保护也不能凭旧ACK通过最终发送。重连初始closed，历史快照/ACK不恢复旧许可。

本候选统一所有FENCE/AUTH_FENCE/TIME_FENCE/RUN_FENCE账本为**permit_id升序且唯一**，保持既有面板约定。它替代原局部run-fence-body/0.1的多字段排序；旧包络不是本版可接受消息。每目标账本最多256项；RUN_FENCE只包含automation且selector命中项，其他三类仍允许人工/面板/自动化混合。全保护可含多个目标，每目标单独冻结，不能截断后声称全局applied。

IntentRef带完整发送世代与自动化绑定；coverage必须与冻结账本逐项一致。not_sent仅能由同Controller/worker/IPC/device_session/clock域证明未收到或未消费；已知transport_entered不得降为未发或未知，新进程不能为旧出口自证未发。运行拒绝不改变control_version/holder，不撤销人工接管；与在途资源冲突的人工命令仍受原资源门控。

快照最多4096行、单目标256许可是候选硬边界，完整wire字节仍由严格解码及P0 profile限制。布防/新准备/许可签发前预留全集容量；超限保持关闭进入维护，不能分页开闸或丢墓碑。实际吞吐/时限与GC批准另验。

## 固定故障与验收时序

| 编号 | 输入或故障 | 必须结果 |
| --- | --- | --- |
| PIP01 | 原命令/guard/permit/intent同一来源 | 自动化绑定逐字段一致；手动绑定为空 |
| PIP02 | 改run或execution并重算所有公开摘要 | 与原持久受理/准备不一致，拒绝 |
| PIP03 | 另一Seamer库同run_id/代次 | 不借用原grant；原库deny不扩大命中 |
| PIP04 | 面板请求改为automation | 拒绝，不能清空panel绑定绕权威记录 |
| PIP05 | 新worker握手后缺快照开闸 | 拒绝；原旧代次不可发 |
| PIP06 | 快照漏墓碑、同数量换run、重复或乱序 | 重算摘要后仍拒绝 |
| PIP07 | 新RUN_FENCE先于旧OPEN_GATE | 旧快照不可降低本地floor/revision，保持关闭 |
| PIP08 | 当前ACK回显旧域/旧token/错快照 | 不把该ACK作为当前开闸结果 |
| PIP09 | RUN_FENCE切点前已进入transport | in_flight保留，保护applied不清资源 |
| PIP10 | 旧worker/连接/时钟域的intent报告not_sent | 拒绝；保留未知与独立退役核对 |
| PIP11 | ACK丢失后QUERY_BARRIER | 返回同一冻结覆盖；不生成新派发或空账本 |
| PIP12 | 同operation改basis/selector/目标摘要 | 409保留原件；增强保护须新操作 |
| PIP13 | 原grant已过期、Seamer仍有当前保护权 | 允许单调拒绝；不授设备动作 |
| PIP14 | RUN_FENCE与手动接管分别到达 | 各自selector/账本生效，互不清除对方门控 |
| PIP15 | 保护落盘失败或查询未知 | RAM拒绝保持；不报告可靠applied、不重发设备 |
| PIP16 | 旧协议或旧definition_version写入 | 拒绝，不降级转换或拼接新旧结构 |

上述运行验收尚未执行。[check_protocol.py](check_protocol.py)的141项检查只验证固定本地Schema闭包、HTTP投影、手写合成关联和有限状态；完整身份、NTP/面板策略、SDK解码、SQL、真实IPC及设备证明分别保留。原19帧升级正例只证明新结构可承载旧路径，不冒充原全部语义回归。[独立报告](protocol-report.json)绑定本批6文件、四份源Schema、面板夹具及channel Schema共12份原始输入；--check-report只核字节，不重跑。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/build_protocol.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_protocol.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_protocol.py --check-report --staged
```

下一统一公共版仍须归并新的CommandRequest/RunGrant到所有HTTP/Prepare记录及实际签发者、完整摘要注册和版本矩阵；P1—P4物理DDL、source重基线/跨epoch链、P0计费及GC仍待设计交付。此处OpenAPI只覆盖两个保护接口，不能据此宣称全部SDK迁移完成。
