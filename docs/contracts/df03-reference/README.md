# 应用参考时钟字段与区间候选

日期：2026-10-20。依据用户已确认的[DF03 reference-bound/1路线](../../rebirth-df03-time-profile-design.md)，本目录落实`reference-time/0.1.0-draft.1`的内部领域字段、精确算术、发布与失效边界。模型路线已确认；具体字段和profile仍是候选，不更改公共draft.4、旧TimeGuard或设备IPC，也不实现采集器。

## 1. 事实与本项目选择

**协议事实。** NTP时间戳含32位秒与32位小数，报文不携带完整时代编号；接收／发送时间分别由T2／T3表示。KoD不是可用于计算的时间响应。NTS提供认证和请求关联，存在独立的引导信任责任。（来源：[RFC5905 §6—8](https://www.rfc-editor.org/rfc/rfc5905.html)、[RFC8915 §5及§8.5](https://www.rfc-editor.org/rfc/rfc8915.html)。）

**本项目的设计选择。** 使用可信采集组件的发送前m1／完整接收后m4括号，不修改宿主wall。服务端时间精度、上游新鲜度、时代解释及本地单调速率必须由批准profile和独立证据提供；字段合法、NTS通过或root数字很小不能自行证明这些前提。当前版本只接受normal UTC、禁smear，闰秒附近和语义未知时关闭绝对时间资格。它是保守资格策略，不表示NTP协议禁止其他合法模式。

模型唯一源为[build_contracts.py](build_contracts.py)，生成[reference.schema.json](reference.schema.json)。按具名`$defs`验证，根拒绝直接实例。模型常量为`reference-bound/1`／revision `1`；拒绝将`system-bound/1`的offset、source_update_id或旧profile套入。

## 2. 字段、所有权与摘要

| 模型 | 字段与责任 |
| --- | --- |
| Domain | authority_service_id、database_instance_id、provider_id/boot_id、runtime_binding_ref、clock_domain_id、descriptor_digest、clock_generation；与DF02真实运行域关联 |
| Source | source_id/revision、configured_server_ref、endpoint_set_ref、effective_config_ref、authentication、trust_policy_ref、source_digest；指定服务器与实际端点分开，原地址仅受保护原件可读 |
| Profile | model/revision、collector/protocol制品Ref、platform_qualification/clock_method/error_method/era_method Ref、elapsed_model、elapsed_error_ppm、span_quantization_ns、包字节上限、time_scale/leap/smear政策及摘要 |
| Policy | 最大采样跨度、交换年龄、锚点年龄、上游年龄、UTC半宽，全部纳秒十进制串；独立revision/digest |
| Approval | 精确Profile/Source及qualification Ref、authority、approved/revoked与revision/digest；Profile不反向引用批准，避免摘要循环 |
| Binding | Domain、Source/Profile/Approval/Policy Ref及time_generation；全部时间记录固定绑定，改变任一资格条件不能现场套新值 |
| Request | 唯一request_id/revision、Binding、correlation/endpoint Ref、m1、响应截止tick、请求原字节Ref及长度、摘要；关联值不复用，不能依赖不可靠wall作为唯一身份 |
| AuthEvidence | 原Request/响应字节/Source、mode、verification/peer_binding Ref；NTS必须有bootstrap_ref，trusted_network必须为null，真实验证结果仍由权威提供 |
| ErrorEvidence | Binding、原Request/响应字节、error_method/qualification/provenance Ref、T2与T3误差上界、m1处上游年龄上界；未知不能填零或形成合格原件 |
| EraEvidence | 原Request/响应字节、method/independent_time Ref、允许UTC区间；时代必须与独立范围一致，不能用同一待验证响应证明自身时代 |
| Exchange | 原Request/Binding/correlation/endpoint/响应字节和长度、m4、原头字段、T2/T3的seconds/fraction/era、authentication/error/era/parser_receipt Ref及摘要 |
| Anchor | 固定id/revision、model、Binding、exchange_ref、m4、exchange_start=m1、UTC上下界、derivation_digest和anchor_digest |
| Assessment | 固定id/revision、model、Binding、anchor_ref、当前tick、UTC区间与三种年龄、conditional/unavailable及原因、摘要；unavailable的区间和年龄全为null |
| Failure | 无法建立完整Exchange时的domain、可空request_ref、tick、原因和可空诊断Ref；不伪造来源／误差证据 |
| AuthorityState | 单writer拥有state_id/revision、Binding、cold/collecting/qualified/unavailable、可空当前anchor及invalidation Ref、摘要 |
| Invalidation | old_binding、精确下一time_generation、cause/protection_operation Ref、deny_new_utc_permits=true及摘要；关闭新资格不等于全部设备屏障已完成 |
| UtcGuard | 固定model、Binding、anchor/assessment Ref、绝对窗口与单调expires_tick、摘要；是时间子守卫，不代替控制、授权、资源及来源保护 |

所有Ref都是所属authority的不可变原件引用，三字段为id/revision/digest，不能当作bearer权限。跨authority读取仍经DF06对象权限和配对mTLS。原始请求/响应可能含协议秘密，只存受保护原件Ref，不回传GUI、不进入普通日志；摘要不是脱敏或权限措施。

摘要为JCS/SHA-256，只排除该对象自身的具名digest字段，不递归删除同名业务字段。`derivation_digest`精确包含exchange_ref、request_ref、Source/Profile/Policy/Approval Ref、authentication/error/era Ref和formula常量；Anchor再固定该摘要及计算输出。不得通过改输入后只重算摘要取得批准。Approval引用Profile单向；Exchange引用Request与证据，证据仅引用Request/响应字节，不回指Exchange摘要。

整数词法严格且不接受负零、前导零、指数或尾随换行。UInt/修订是最多20位十进制串；Signed UTC纳秒最多30位；原32位word最多10位再语义检查`0..2^32−1`，时代须在有符号32位内。尺寸是候选护栏，不是无限时间或产能承诺。所有入口先严格原始JSON解码及Schema，再调用语义判定；本目录不重复实现DF01原始解码器。

## 3. 精确时间与条件区间

原始T2/T3无损换算为有理数纳秒：

```text
T = (era × 2^32 + seconds − 2208988800) × 10^9
    + fraction × 10^9 / 2^32
```

不先转JS Number或把亚纳秒截断。时代由独立证据解释，秒回绕不能清零时代；all-zero未设置时间戳不能取得资格。root_delay_word保留原32位字，不在本候选中将其误读为无符号秒，也不直接把root数字变成E2/E3。parser_receipt必须绑定实际报文、长度和所有解析字段；参考检查仅假定这些由可信提供者产生，尚未运行报文解析器。

`elapsed_model=observed-delta-relative/1`明确规定：对当前批准环境中的两个同域读数，归一化观测差为Δ，真实经过量包含在：

```text
e_minus = max(0, Δ × (1 − ρ) − q)
e_plus  =        Δ × (1 + ρ) + q
ρ = elapsed_error_ppm / 10^6
q = span_quantization_ns
```

q覆盖两次读取和计数换算的总跨度量化，只加一次。ρ定义为**相对已观测Δ的经过量误差界**，不能直接把硬件频率ppm代入；若平台报告定义相对真实经过量，须先转换为保守包络并重新批准。暂停、回退、频率假设失效及共享clock代际变化作废资格。q和ρ为零只出现在合成夹具，不代表生产平台可批准为零。

沿已选DF03条件推导，服务端真实接收／发送UTC分别被T2±E2、T3±E3覆盖，且因果延迟非负：

```text
L4 = floor(T3 − E3)
U4 = ceil(T2 + E2 + e_plus(m4 − m1))
L(m) = floor(L4 + e_minus(m − m4))
U(m) = ceil(U4 + e_plus(m − m4))
```

若L4>U4直接拒绝，不交换端点；上下行不必对称，不用半RTT缩窄区间。m4后的外推同时推进误差与年龄。服务端误差E必须覆盖实际T2/T3取样语义、UTC刻度和误差前提；它是资格提供者的条件界，认证只证明关联与对端身份。

交换年龄=`ceil(e_plus(now−m1))`，锚点年龄=`ceil(e_plus(now−m4))`，上游年龄=m1处上界+交换年龄。收到迟到包、重复报文或查询旧锚点都不刷新这三者。采样跨度允许等号；请求deadline、三种年龄上限及guard的单调期限均拒绝等号；半宽用`U−L ≤ 2×max_half_width`精确比较，不浮点除二；排期必须`not_before ≤ L`且`U < not_after`。

API展示所需毫秒下端向下、上端向上转换，负纪元使用数学floor/ceil；UI中心点或平滑值不能用于执行判定。尚未把这些字段合并成公共ClockSample/Assessment响应或修改GUI。

## 4. 发布、失效与恢复的写集

1. 唯一可信采集组件先固定Binding和请求关联，再取m1与原字节；每源单飞且全局有界。完整响应后取m4，核验原请求、端点、认证、头字段、时代、误差资格、预算及年龄。一个请求只消费一个交换；无资格时只记录Failure。
2. writer在同一事务保存不可变Request/证据/Exchange/Anchor、请求消费墓碑、审计/通知意图和当前State指针，并核对state_revision与完整Binding。提交时重新计算资格，不能因为接收时尚未过期而发布已经老化的锚点；旧m4也不能覆盖较新样本。拒绝、存储失败或未知提交均不发布未经核对的当前资格。
3. 请求消费键覆盖authority/db/provider/boot/request_id。重投同交换返回原历史结果，不移动当前指针、不创建年轻Anchor；同请求不同交换摘要拒绝。失效后查到旧提交也只有历史意义，不借查原重新合格。真实读取仍先验证当前查询权限。
4. 失效事务保存不可变Invalidation、推进time_generation、关闭新UTC许可、清当前指针，并保存TIME保护outbox。返回`closed_pending_fence`仅表示本机资格关闭；屏障覆盖普通与保护传输，最终生效仍按完整原件与持久提交定义。
5. 重启、换源或撤销后，不从旧Anchor恢复资格。新的当前Binding、批准、采集及原保护恢复流程全部满足才重新发布；新合格样本不解除自动化暂停，不补旧场次，不延长旧许可。可留存同代较旧Anchor供已有guard重评，但原件必须未撤回、当前authority仍qualified且完整Binding相同。

`UtcGuard`必须持久绑定原Assessment与Anchor；发送前用当前同域tick重新评估，不把旧Assessment区间当作当前时刻。已有批准guard不能被客户端重新摘要替换。`time_required=false`的即时手动动作不携带本UTC子守卫，仍由外层检查运行域、单调期限、接管、授权及资源；不能自行将批准动作的时间要求关掉。

本轮的发布／失效仅为内存字典副本模型，不能宣称已定义完整SQLite表或验证真实CAS。物理DDL仍需覆盖上述不可分写集、每请求排他、当前资格索引、失效outbox、原件撤回、留存与恢复查询；证据保留失败必须关闭资格，不能静默丢原件。

## 5. 故障与验证边界

| 输入或故障 | 必须结果 |
| --- | --- |
| 合法NTS但上游误差或时代未证明 | 无合格Anchor；root字段不补造证明 |
| 迟到响应、重复关联、重算摘要换原件 | 截止或身份拒绝；旧结果只读，不刷新年龄 |
| 秒／小数超32位、时代溢出、错误era窗口 | 明确拒绝；不截断或靠本机wall猜测 |
| 采样跨度等号、年龄等号、排期右端等号 | 分别允许、拒绝、拒绝；随后仍核其他守卫 |
| 提交前撤销或Binding改变 | CAS／资格失败，当前指针不发布 |
| 证据已写到事务副本但提交前故障 | 证据消费与当前指针一同回滚；真实掉电另验 |
| 成功提交后丢响应、再投同请求 | 只读原记录，不再发布或延长有效性 |
| 宿主wall跳变，共享单调域连续 | 仅诊断变化；参考区间不读取wall |
| provider重启、共享时钟失效或失效代次推进 | 旧Anchor不能继续授时；历史可审计 |
| guard创建时合格，发送时过窗或撤销 | 拒绝；必须重新外推，旧合格结果不豁免 |

[check_contracts.py](check_contracts.py)以独立手写预期验证Schema封闭性、整数及版本、NTP固定点换算、TP39—TP43区间、当前绑定、年龄/窗口边界、失效和有限事务顺序；[reference_model.py](reference_model.py)只作参考判定。原件真实性、认证、NTS引导、parser与上游E提供者由合成上下文假定；不连接网络、NTP、SQLite或设备，不执行线程、OS挂起或真正掉电。`--check-report`只比较声明输入字节，不重跑用例。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df03-reference/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df03-reference/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/df03-reference/check_contracts.py --check-report --staged
```

下一步在此字段基础上完成公共ClockSample/TimeBoundEvidence/Assessment、内部查询OpenAPI、TimeGuard/IPC特性和C06 ScheduleGuard的同版映射，再落物理写集。精确协议库／原生制品、NTS冷启动、时代／闰秒／上游E资格与双平台计时profile仍需冻结；本目录不是这些门槛已通过的证明。
