# ordinary/all关闭与取消编码来源候选

状态：待审阅，`build_cancel_closure.py`将[103表资源候选](CANCEL_RESOURCE.md)与`cancel-closure.sql`组合为119表离线布局。旧候选原样保留；本轮不生成可部署迁移、不修改业务服务。该组合落实[取消IPC设计](../c02-cancellation/README.md)的关闭来源关系，不宣布完整ExecutionPlan、所有屏障或最终SDK已归并。

已知事实：103表的取消关闭仅关联公开修订与资源提供者回执；普通/取消发送已共用签发水位，但发送提交仍用BODY承载ordinary关闭与编码原件。（来源：`controller-cancel-resource.sql`、`issue-ledger.sql`、`cancel-resource.sql`。）基于这些约束，本轮增加类型化外键与封存规则，使公开closed及取消发送不能仅凭非空BODY越过关闭原件。

## 1. 固定对象与字段

| 对象 | 字段与关系 |
| --- | --- |
| cc_cut / cc_cut_commit | cut_id、cancellation_id、ordinary/all、previous_cut_id、共享issued_revision、cut_digest/body；与完整集合封存双向延迟FK，commit含validation/audit/outbox |
| cc_target / cc_member | cut/exit固定目标及摘要；cut/permit/exit完整传输成员、entered_known；permit指同一ci_issue，类型从该索引读取 |
| cc_attempt / cc_failure | barrier_id、cut/exit、ordinal、previous_barrier_id、固定请求及审计/outbox；失败记录只增，cache_miss/deadline_elapsed可重装同cut，channel_lost不可复用 |
| cc_coverage / cc_ack_prepare / cc_ack | 每个原ACK完整两类传输分类及准备ID；ACK关联原attempt，保存gate_io_seq、effective_tick、原摘要/正文与验证；成员与ACK双向封存 |
| cc_selection / cc_closure | 按closure_id/cut/exit选择当前原ACK或精确退休出口；汇总以完整目标封存，关闭原件含独立摘要、验证、审计与通知 |
| cc_revocation | 精确closure_id撤回，原因、审计及保护outbox必须同一行持久化，不删除原件或撤回永久deny |
| cc_prepare / cc_packet / cc_dispatch | 准备先于编码outbox，绑定取消/执行/primitive/出口及ordinary关闭；原packet固定prepare、摘要和bytes；每条取消许可必须经dispatch外键指向同一原packet |
| cv_cancel_revision.closure_id | closed必须非空且属于同取消的当前有效all关闭；pending/indeterminate不得伪带关闭引用 |

这些是数据库内部字段，不给旧IPC添加未协商字段。现有U20用于water/tick/seq；本候选attempt ordinal使用SQLite有界整数，边界耗尽保持关闭。摘要/正文、Requester、政策、资源足迹与时间预算的真实取证仍由可信提供者验证；SQL非空检查不是权威证明。

## 2. 写集与线性化点

1. ordinary cut引用已受理cv_cancel的原水位与摘要，逐项核对原cv_cancel_target/cv_cancel_permit快照。普通attempt集合仍由cv_cancel_attempt保存；worker对原正文中普通准备集合的核验属于提供者输入映射，尚未形成逐出口普通准备外键，不能把本轮称为完整准备布局。
2. all cut引用同取消的初始ordinary cut，水位取当前ci_issue；包含该设备全部已登记出口（含退休历史）、全部普通历史、全部取消传输及全部已登记取消准备。三个成员集合均作双向EXCEPT，已核销传输不省略。all切点一旦插入，本事务内及之后禁止新增取消准备、packet和传输提交；回滚则全部撤销，切点与封存不能半边提交。
3. 只有完整cut封存后才登记尝试。ACK两类许可合用规范permit身份，按类型分别检查每出口256上限；准备ID单独完整核对。cut已知in_flight不能降为not_sent/unknown。后到的强事实仍可提升原许可，ACK不等业务效果或资源释放。
4. 原ACK保存与最终采用分开：失败旧尝试的迟到ACK仍保留原件并更新强事实；采用要求最新、未失败、cut/exit一致。退休直接引用ce_retirement，不产生not_sent事实。全部目标选择与Closure同事务；遗漏任一目标或只保存选择行不能提交。
5. 取消准备必须引用同取消有效ordinary关闭，政策为cooperative且当前仍requested；同取消执行身份/摘要不可改变。DISPATCH提交与cc_dispatch双向绑定，匹配准备的执行/primitive/出口与原packet摘要、字节。已有Requester和共享签发约束继续执行。普通关闭不允许公开closed，all关闭不代表取消成功；本轮未将任何未知结果改为confirmed。
6. 公开closed引用all原件，cx_closure再绑定该修订的同一关闭摘要。撤回all原件时，相关资源validation撤回与风险重开/保护锁存同事务，当前公开投影隐藏，历史保留。重新取证须新closure_id及完整选择集；一份cut同时只允许一份未撤回汇总。旧请求、cut和永久禁止新发送不复活，新汇总也不授设备重试。

新出口晚于all切点登记时，仍须按完整command deny快照先安装all拒绝再开闸；不能将其视作切点前目标遗漏，也不能借新出口继续旧执行。这一启动门控的实际提供者及IPC运行验证仍未实现。

## 3. 强事实与恢复

原cc_ack的in_flight同时进入普通ce_current_disposition及取消cf_disposition；强事实不等待closure或采用。若推翻旧never_sent，来源以独立`cancel_closure_ack`及原barrier_id登记资源失效，避免与RUN屏障同名ID混淆。来源必须实际覆盖释放成员。已独立核销效果的记录不因重复传输观察直接失效。

新ACK封存在既有RUN的seal至来源commit窗口内被禁止，包括先写coverage再封存ACK的顺序；否则会改变RUN捕获时的未决集合。普通和取消仍共用旧资源恢复机制，不产生第二套恢复资格。

关闭汇总撤回是本轮显式支持的撤回粒度。单个ACK/退休原件的权威撤回向所有依赖汇总展开、完整通用保护outbox内容及资源核对结果到公共证据的映射，仍须统一提供者落实；不能把任意BODY当成合格证明。本布局会保留历史强事实，无法用撤回删除实际发送记录。

## 4. 验收与剩余项

`check_cancel_closure.py --report`实际加载119表，覆盖ordinary/all切点、逐传输关联、完整ACK、关闭汇总和公开修订的逐写缺失/主动异常；另验ordinary冒充all、准备和历史遗漏、固定字节、旧ACK迟到及采用、退休不造未发、关闭撤回、重新取证和资源级联。报告绑定生成输入与检查器原字节，`--check-report --staged`核对提交版本，不重跑用例。

剩余实施前设计：唯一ExecutionPlan/Primitive/依赖边及完成证据的物理图，完整保护资源足迹和独立准备/guard/预算提供者；普通逐出口编码准备及ACK普通attempt集合的外键；取消效果DecisionEvidence与公开结果原件关联；单原件撤回传播与保护outbox最终映射；FENCE/AUTH/TIME及27表时间子域归并；统一SDK字段映射与严格解码。

上述缺口保留功能目标，不以关闭所有协作取消作为最终替代方案。内存回滚、合成BODY和参考SQLite不证明真实writer并发、磁盘耐久、IPC身份或设备效果；全系统设计与运行验收均未关闭。
