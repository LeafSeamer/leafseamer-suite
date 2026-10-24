# 类型化命令到首次出口开放

状态：候选，`approved=false`。本项将类型化命令受理与[242表最终准入布局](FINAL_ADMISSION_STORAGE.md)中的出口关闭、会话日志、换闸及正常OPEN路径接通。仅增加设计参考模型和离线检查，不修改业务服务，不改变SQL守卫。

## 已知事实与本次验证范围

已有独立开放夹具使用早期简化命令；类型化命令夹具最初没有出口、会话和开放记录。本次分别在两个Controller数据库执行开放路径，并验证开放、当前grant、类型化命令及持久attempt能够同时成立。（来源：[类型化夹具](check_typed_command_view.py)、[完整路径检查](check_typed_gate_path.py)。）

验证结论限于真实SQLite持久关系：`go_ready_candidate`确实出现，领域行、日志、关闭证明和资源快照同时存在；不是仅把内存中的资格标志设为true。参考模型使用合成来源正文及提供者，未证明IPC端点身份、NTP资格、字节编码或设备已开放。`written`在本实验中是保存到SQLite的合成写结果，没有执行socket、管道或设备调用。

## 首次开放顺序

| 阶段 | 持久原件及提交要求 | 结果 |
| --- | --- | --- |
| 出口登记 | ce_exit + ct_change/state + go_close + 空准备pd_cut及其commit + 控制audit/outbox/commit同事务 | 自动控制权不变，出口protected |
| 会话 | ij_session/exit；HELLO、HELLO_ACK各有frame/handshake/commit；ACK出站写尝试与结果 | 建立当前会话及两个方向seq=1 |
| 关闭证明 | go_close_ack；pd_closure/commit；pd_close_completion精确绑定同一close/ACK/cut | 空准备集合也不能省略关闭完成证明 |
| 换闸请求 | GATE_FENCE日志、gf_request、日志commit同事务；随后持久写尝试及结果 | c2w seq=2，不授开放 |
| 换闸回执 | GATE_FENCE_ACK日志、gf_ack、日志commit同事务 | w2c seq=2；只采applied |
| 安装fence | go_gate(fenced)与gf_commit同事务 | 保持protected；期限为半开区间 |
| 恢复快照 | go_recovery、完整当前hold集合快照及commit、全部关闭target、recovery commit同事务 | 核所有关闭及准备关闭原件，记录新安全代次 |
| OPEN计划 | go_plan/commit固定快照、当前控制状态及fenced gate | 仍不能提前Ready |
| OPEN发送 | OPEN_GATE日志、go_dispatch及日志commit；随后写尝试及结果 | c2w seq=3；发送前重核plan期限及会话 |
| OPEN回执 | OPEN_GATE_ACK日志、go_evidence及日志commit同事务 | w2c seq=3；精确绑定请求、token、revision和三份快照引用 |
| Ready | ct_change/state、go_gate(ready)、go_ready、控制audit/outbox/commit同事务 | 原权威epoch/version/holder不变，产生开放候选 |

时序向量使用本域tick 11–22，换闸截止30、OPEN截止80、快照截止90、租约截止100；这些是合成纳秒计数，不是建议的产品超时。所有期限比较保留严格小于，恰等于截止点拒绝。counter继续使用20位十进制列，不转浮点。

## 一致性与失效

换闸、OPEN出站帧都必须在同会话按序写尝试；响应必须指向已提交且已尝试的原请求。不能先造领域ACK，再补对应日志。历史ACK可保存但不能作为安装fence或Ready的证据。

Ready最终提交重核当前快照、控制状态、会话与回执；采用前撤回关闭/OPEN证据会整笔回滚。采用后终止会话或撤回关闭/OPEN/换闸证据会移除候选，历史go_ready仍保留。不能修改历史ACK来“恢复”资格。

开放记录只改变闸状态和记录修订，不创造控制权转交、命令执行或完成事实。四个临时最终签发守卫及其余DDL均按前后完整sqlite_schema对比保持不变。

## 发现的顺序冲突及推荐启动顺序

**已知事实：**当前`cr_current`绑定每个设备的精确控制记录ID，而不仅是epoch/effective_version。先签grant和受理命令，再登记出口或Ready，会使当前控制记录不再等于原控制引用；历史grant及CommandRecord仍存在，但`cr_current`和`cn_live_command`失效。不能把这种情况下出现的`go_ready_candidate`称为自动化链可用。（来源：[转交SQL](continuation-controller.sql)、[已记录的控制修订约束](CONTINUATION_STORAGE.md)、本项反例。）

**推荐并已作SQL验证的顺序：**先完成所有目标设备的出口登记、关闭证明、会话、换闸和Ready，再以实际Ready控制记录作为精确control_ref签发continuation；随后由Seamer完整采用、R5和新触发生成请求，Controller受理并发布prepared修订。两Controller实验中，每库两个设备均有开放候选；受理及prepared之后，当前grant、cn_live_command和开放候选同时存在。请求的expected_control保持原epoch和effective_version，没有降低精确记录约束或重写历史grant。

检查仅在既有测试夹具的controller_seed依赖边界插入真实启动写集，并将实际控制原件返回给其后续正常签发流程；没有替换业务判定、SQL视图或触发器。失败顺序另作明确反例：grant-first后的历史命令仍为queued/pending/not_sent，但不得新建attempt。成功顺序的prepared只建立命令attempt及固定库存，尚未产生编码packet或最终permit。

本次不把“仅闸状态变化不应撤权”作为新规则放宽原设计。运行中重新开闸仍会影响已签grant，必须经过已有恢复与新代授权流程；该非首次启动闭环仍待组合验证。启动顺序的验证不代表重连或接管恢复已完成。

## 边界及剩余实施事项

[参考模型](typed_gate_path_model.py)明确限于首次出口、空准备和空hold。若已有出口、准备或hold，拒绝此辅助入口；后续完整writer必须捕获全部成员，不能按本例略去。其他设备的控制状态和原自动化来源不借用也不改写。

当前CLOSE确认沿用已有go_close_ack提供者原件；本项未新增CLOSE_GATE/CLOSE_GATE_ACK的统一日志映射。该映射、真实端点验证、非空准备/hold、多出口恢复、人工接管导致命令终态及恢复并发，需要继续组合验证。会话profile仍使用当前SQL固定的`ipc/0.13.0-journal-draft.1`，不代表对外协议版本再次冻结。

普通/取消编码、最终hold/Ownership/Guard/预算、AdmissionSeal同库签发和SEND_REPORT尚未接入本路径。测试显式断言ci_issue、ce_permit、fa_seal及ce_transmission_commit均为0。因此`sql_positive_ready_path_executed=true`与`sql_positive_issue_path_executed=false`同时成立，阶段0继续未关闭。

## 验收

检查覆盖双Controller先开放再授权的正常路径、先授权后变更控制记录的失败顺序、各写入后注入异常整库回滚、必需同事务行漏写、缺关闭完成证明、日志与领域身份错配、未尝试发送却收到ACK、历史ACK、等号到期、Ready时换时钟域、最终提交前撤回、提交后撤回及会话结束。报告记录绑定输入SHA-256，全部实验结束检查外键及悬挂事务。

未运行跨进程竞争、磁盘崩溃恢复、业务服务、真实IPC或设备。上述检查看的是数据库协议可组合性，不替代这些验收。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_gate_path.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_gate_path.py --check-report
```
