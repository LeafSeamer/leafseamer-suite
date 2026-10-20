# 应用参考时钟：HTTP、执行IPC与排期绑定候选

本资料沿用户已确认的`reference-bound/1`路线，细化[DF03字段候选](../df03-reference/README.md)。`reference-time-service/0.1.0-draft.1`与`ipc/0.8.0-reference-time-draft.1`均待审阅，未切换SDK权威，旧资料保持原版。只交付设计、生成资料和离线检查。

## 1. 公共时间与内部精确读取

两authority分别提供相同路径，各自读取本服务的参考时钟，静态代理路由决定服务身份。外部调用不能传一个service_id来选择别人的时钟。

| 接口 | 输出及边界 |
| --- | --- |
| `GET /api/v1/clock` | 当前`PublicClock`展示投影；保留原operationId `getClock` |
| `GET /api/v1/clock-assessment` | 同一种当前投影；保留`getClockAssessment`，不返回可执行许可 |
| `GET /internal/reference-time/bundles/{id}/{revision}` | 固定`EvidenceBundle`，含来源、profile、批准、政策、请求及认证/误差/时代/交换/锚点/评估的完整结构 |
| `GET /internal/reference-time/anchors/{id}/{revision}` | 原始不可变Anchor |
| `GET /internal/reference-time/assessments/{id}/{revision}` | 原始不可变Assessment；不重新采样或刷新年龄 |
| `GET /internal/reference-time/profiles/{id}/{revision}` | 指定历史Profile；能读不等于当前获准 |

全部要求精确`X-LeafSeamer-Contract`、`Cache-Control: no-store`，内部还必有`digest`查询参数。当前认证、精确对象权限先于历史查询；同ID/revision摘要不符409，其他authority/不可见对象按对象隐藏政策拒绝，不提供全局枚举。内部使用已配对mTLS及`clock.internal.read`；公共为人员bearer及`status.read`。本轮未新增第三方服务读取公共时钟的授权档案。

公共与内部OpenAPI分开生成引用闭包。公共只展示配置中批准的来源显示名、认证方式、参考UTC闭区间、精确十进制纳秒中点及覆盖两端的误差半径；不暴露设备地址、原报文、NTS秘密、批准原件、provider/数据库/运行域或内部Ref。中点为`floor((L+U)/2)`，半径为`max(mid-L,U-mid)`；不经浮点。GUI须标注“采样时参考时间／条件误差”，不能把响应到达时刻当采样时刻，也不能用浏览器时钟把区间当最新授权。状态不可用时UTC、中点、误差全部null，不能回填宿主wall时间或旧合格值。源标签的脱敏由配置提供者保证，Schema不能证明字符串安全。

读取证据是历史审计，安装及发送是当前裁决，二者不共用资格判定。Bundle按固定原件生成，只单向引用发布State；State不回指Bundle，避免摘要循环。原件中bytes_ref仅为受限内容引用，本API不交付原始数据或cookie。Bundle摘要覆盖除顶层`bundle_digest`外的完整JCS内容；本候选不递归删除同名业务字段。

旧`/internal/clock-domain`及运行域结构仍独立。旧time-evidence/time-profiles/clock-samples接口在统一版本中由上表精确端点替代，旧模型只供历史工具读取；线上不双格式降级。旧ClockSample、跨服务EventAgeProof及其他公共事件时间字段仍需下一SDK统一迁移，不能把本候选称为全公共draft.5。

## 2. 完整46帧设备IPC的同版映射

以[IPC0.7](../c02-cancellation/README.md)为唯一设备帧输入，输出自包含46帧0.8候选。生成器以`($id, defs指针)`投影引用闭包；来源字节见`source-bindings.json`。不按短名去重，不重写const/enum内的业务数据。

| 位置 | 同版变化 |
| --- | --- |
| 三处具名ExecutionGuard及取消Guard | 删除旧时间代次/政策/样本/证据引用组合，新增`reference_time: ExecutionTime|null`；time_required真假分别强制非空/空 |
| `ExecutionTime` | `context_ref`精确指Bundle；完整`utc_guard`绑定本地Domain、来源/批准/profile/policy/time_generation、Anchor、Assessment和UTC窗口；独立`schedule_ref`可空 |
| `GUARD_INSTALL` | 删除旧clock_sample/time_evidence/time_profile；增加reference_context；schedule_guard独立可空。需要UTC不自动意味着有排期 |
| `CANCEL_GUARD` | 同一reference_context与ExecutionTime；保护动作的时间要求来自已批准取消政策，不能从父命令继承或自行降级；不携带普通排期 |
| 两种Guard ACK | 回显`reference_time_digest`，普通ACK另回显schedule_guard_digest；摘要null规则及关联由语义验证，ACK不授新权 |
| `OPEN_GATE/ACK` | 安装/回显GateSnapshot，固定Domain、State引用、snapshot_revision和minimum_time_generation；不得降低已收到的floor |
| `TIME_FENCE/ACK` | 替换旧系统clock_generation字段，携带Invalidation及精确回显和minimum_time_generation；原普通与保护双清单、尝试及覆盖保持 |
| `HELLO/ACK` | 精确0.8版本及reference_bound_time/reference_time_floor/schedule_source_binding三特性；缺任意一项拒绝，不回退0.7 |

Guard摘要须按新正文重算，permit/重传/查询内的guard_ref或guard_id+digest均回绑同一原件；不能把旧摘要搭配新Guard。`reference_time_digest`为整个ExecutionTime的JCS摘要，不是仅UtcGuard摘要。发送必须复核完整普通或保护守卫，时间模块通过只完成其中一部分。每次传输及协议重传均重新按本地共享时基外推，不能复用安装时区间。

本候选采用保守的当前State精确绑定：State修订后，旧Bundle不得用于新的安装或发送，应重新评估并签发新Guard；不能借重签重发已消费或未知传输。TIME_FENCE正文/信封的clock_domain_id和descriptor_digest须与Invalidation.old_binding.domain一致，失效代次精确加一；更强历史floor只保留、不降回。这个State绑定选择仍属于候选，不把来源模型批准扩大为此细节已确认。

设备worker只消费核心验证并持久的时间证据，不直接发NTP请求；指定NTP的采集器启动/上报通道尚待单独设计，不借设备IPC注册采集器。Bundle不取得自身权威：核心来源验证、profile批准及原件真实性仍由指定提供者负责。

## 3. 排期与运行域绑定

`ScheduleGuard`固定：origin_service_id、origin_database_instance_id、occurrence_ref、definition_artifact_ref、schedule_version、activation_ref、admission_ref、execution_id、step_id、step_window_ref、window、queue_deadline_tick_ns、local_clock_domain及自身id/revision/digest。引用来自持久场次及受理，不由GUI填报为权威。

来源域属于Seamer排期库；local_clock_domain属于当前Controller执行时钟，二者不能混用。所有来源字段须和受理时固定RunBinding/CommandRequest及原件提供者一致；完整场次模型和日历DDL仍在C06关闭项。本轮仅落实逐步守卫格式及关联，不声称已生成完整排期API。

UTC窗口必须与UtcGuard逐字一致并满足`not_before <= L && U < not_after`。队列截止与原命令/发送/授权单调截止均独立满足，取交集；截止等号拒绝。每步骤自己的窗口不借另一场次或相邻步骤。即时手动/即时保护`time_required=false`且时间/排期字段全null，不因NTP不可用拒绝，但受监督域、单调期限、身份、控制、资源、预算和永久deny仍必须有效。

## 4. 故障时序与人工验收预期

1. 安装后UTC证据过期或区间越过窗口：发送时拒绝，重装旧Bundle不能刷新年龄。
2. 核心已失效但worker尚未收到TIME_FENCE：本机停止签发新UTC许可；旧在途按原屏障模型分类。不能声称网络传播窗口内瞬时全局关闭。
3. TIME_FENCE将floor推进后，迟到OPEN_GATE或Guard携带旧代：不得降低floor或重新开UTC资格；即时手动仍须独立满足其他开闸条件。
4. 样本恢复但自动化/场次已锁存失败：只恢复新时间资格，不解除业务锁存或重放旧场次；恢复需原恢复流程。
5. 重算摘要但换场次、步骤、排期版本或来源库：仍拒绝。只改本地时钟代次不能替代排期版本。
6. 同一bundle历史读取在profile撤销后仍可返回原文；失去当前对象读取权则拒绝。历史读取成功不允许安装或发送。
7. provider/boot/runtime或共享clock_domain改变：旧锚点作废，重新建域；错误配置不可fallback到系统时间。
8. API响应丢失只重新读取；独立observation_id可变化，不能由GET重新签发执行许可。内部exact GET必须返回原文。

TIME_FENCE只切断其捕获范围内依赖UTC的普通/保护传输；运行域失效必须另外走整域保护，不能因此放行即时命令。ACK中的minimum_time_generation回显本次Invalidation要求的下界，不表示接收端没有更高下界。接收端保存所有已应用保护的最大值；不得用迟到ACK或旧快照覆盖。GateSnapshot以snapshot_id、snapshot_revision、snapshot_digest组成精确Ref，按authority及Domain隔离。

## 5. 验证和剩余冻结

运行`python docs/contracts/df03-service/build_contracts.py --check`及`python docs/contracts/df03-service/check_contracts.py --report`；`--check-report [--staged]`只核输入字节。报告分别记录46帧结构、公共/内部引用闭包、合成关联和floor快照，旧帧升级正例仅证明形状，不自动证明全部旧语义。

尚需完成：时间权威和失效/屏障的物理写集及保护outbox；采集器专属协议；逐permit当前时间提供者与各源批准/撤销持久映射；跨服务年龄与完整公共时间模型迁移；精确协议库、引导信任及双平台误差profile；统一SDK和完整排期API。真实HTTP/鉴权/IPC/NTP、并发/磁盘、系统时钟及设备均未运行。
