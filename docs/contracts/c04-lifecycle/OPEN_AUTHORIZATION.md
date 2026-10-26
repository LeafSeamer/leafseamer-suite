# OPEN 授权来源与撤销切点候选

状态：待审阅、approved=false。以下“推荐”是基于现有契约的设计分析，不是已运行的认证系统，也不改变已批准 draft.4／IPC 0.3。

稳定授权状态、短期响应刷新与三类来源的统一规则，现归入[DF06第10节](../../rebirth-df06-internal-trust-design.md#10-设备授权语义状态短期取证与恢复)。authorization_state_ref指稳定语义状态；正常证据刷新不推进其修订，真正失效后不得靠新响应直接续约。本文件的Requirement仍只是取证清单，不将新规则暗改进已批准API／IPC。

## 已知事实与缺口

[306表恢复来源](OPEN_PROVIDER_SOURCE.md)已经重建控制、资源、拒绝快照与时间来源，但[资源快照构造](open_source_model.py)的 authorization_ref 仍只接受关联 ID。[最终命令授权](final_authorization_model.py)的挑战固定 device.command，AuthorizationUse 绑定具体 ExecutionIdentity，并且当前入口拒绝取消和面板委托。[GateAccess](../c08-controller/build_scoped_gate.py)则按设备和 ordinary／cancel_only 限定出口；两者不是可互换的凭证。

因此，不能把任意一个有效命令的 AuthorizationUse 填入资源快照后宣称完整 OPEN 已有授权。也不能在读取旧恢复时补写或替换 authorization_ref。本轮交付取证需求的字段与边界，尚未接通该持久来源。

## 推荐：设备开闸资格与动作授权分别取证

开闸由受监督 Controller 内部评估器发起。它必须证明当前服务身份、受控设备范围、现行策略及认证有效期；这里的 policy_ref 是内部策略原件，不新增面向用户的 gate.open 权限，更不能将模块自报 capability 当作权限。主体矩阵的扩展应在统一 SDK 归并时显式审阅。

| 用途／模式 | 必须读取的当前来源 | 不能继承的权限 |
| --- | --- | --- |
| ordinary／manual | 评估器来源；精确当前控制与权威；当前持有人三元身份；当前有效人员会话与凭证；挑战响应、设备范围及认证时钟有效期 | control.acquire 只证明可申请接管；持有记录或旧 T4 不证明当前仍可控制；不得使用另一人的会话 |
| ordinary／automatic | 评估器来源；精确当前 automatic／null holder；现行设备策略及撤销切点 | 不以任意一个 run／grant 或 service 的 device.command 代表整台设备；每条动作仍核自身 grant、arm、主体及取消水位 |
| cancel_only／任意模式 | 评估器来源；当前控制投影；完整 ProtectionScope、Assessment、Ownership 和独立的取消授权链 | 不要求已被撤权的旧持有人重新授权安全取消，也不允许因此恢复 ordinary；普通 AuthorizationUse 不能代替取消授权 |

manual 的新会话必须通过当前身份、同一持有人三元组及设备范围重新取证；不续用过期会话的授权，不改变持有人。会话失效保持持有记录并保护设备，不自动释放控制权。cancel_only 的独立授权必须遵循已有取消／代行契约，缺真实提供者时拒绝，不能以空对象或布尔 verified 放行。

## 需求对象与引用映射

[唯一局部定义](build_open_authorization.py)生成[Schema](open-authorization.schema.json)。Requirement 只是需要解析的证据清单，不是 AuthorizationSnapshot、AuthorizationUse、GateAccess 或开放决定。其摘要只排除自身顶层 requirement_digest，嵌套原件引用全部保留。

| 字段 | 冻结含义 |
| --- | --- |
| requirement_id／revision／requirement_digest | 不可变需求身份，revision 固定 1；内容改变创建新身份 |
| binding | 完整 scope、两启动身份、出口、IPC／设备会话及受监督时钟域；任何一项变化重新选择 |
| purpose／control_mode／holder | ordinary 或 cancel_only；manual 必有持有人三元组，automatic 必为 null |
| control_state_ref／control_authority_ref | 分别解析当前状态与当前有效控制权原件；不得混用同名 ID |
| evaluator | runtime、policy、authority_response、scope_proof、validity 的完整 Ref；必须来自当前内部评估器，不能由 API 请求方指定权威 |
| holder_evidence | 仅 ordinary/manual 必填：精确 holder、session、credential 以及挑战／响应／范围／有效期 Ref；其他分支必须 null |
| cancel_evidence | 仅 cancel_only 必填：ProtectionScope、Assessment、取消授权与Ownership Ref；ordinary 必须 null |
| authorization_state_ref | 同库封存的当前设备授权状态原件；其 ID 对应资源快照 authorization_ref，完整三元组用于 Plan／GateAccess／EligibilityRefs |
| revocation_cut_ref | 当前授权拒绝事件切点原件，必须从已有撤销账本的完整相关事件集合派生；不能由调用者传删减的依赖列表 |
| selected_tick_ns／expires_tick_ns | 同 Binding 域的半开区间；selected <= now < expires，数值为至多20位无前导零十进制字符串 |

authorization_revision 仍是授权状态源的修订，不是 Requirement.revision，也不能拿 principal.subject_revision 或单个撤销事件号替代。新需求本身不推进该修订。未来持久来源必须明确设备授权状态及撤销切点的规范正文和可重建物理来源，本轮没有预先承诺它们的表名或伪造原件。

## 持久读取与撤销时序

最终 writer 在同一 BEGIN IMMEDIATE 中取得当前控制、评估器、认证响应、范围、有效期及拒绝来源。依赖从完整主体／凭证／会话／授权／扩展绑定推导，复用已有 principal、session、grant、extension 下界以及 credential、trust 永久拒绝语义；较低或乱序事件不能降低拒绝。设备策略或当前信任变化也必须改变授权状态来源，不新增可回退的平行授权计数器。

新授权状态应在恢复首次封存之前取得；恢复快照、需求以及之后 Plan 必须指向同一完整当前状态。恢复之后发生撤销，旧需求与旧恢复失效，重新取证并首次封存新恢复；不能用“重新算摘要”修复旧记录。旧原件仍可查，查原不返回当前可执行资格。

OPEN 计划、预留发送、ACK 采用和最终每条设备许可均重读当前来源。需求到期点不得超过所有评估器／持有人／取消授权有效期、挑战 freshness、范围与策略有效期、资源快照以及闸租期的最早终点。认证有效期使用已确定的认证时钟来源，不由业务 NTP 可用性替代；引用时必须核相同单调域，不能直接比较不同域的 tick。

| 交错／故障 | 推荐必须结果 |
| --- | --- |
| 撤销提交先于 OPEN writer | 旧选择拒绝，控制仍 protected；不预留 OPEN |
| 旧 WAL 读者看见有效授权，另一连接完成撤销 | 旧快照不作为准入；结束读事务后由 writer 重取，不能重试升级失败的旧读事务 |
| OPEN 已预留，随后撤销提交 | 同一撤销事务作废待发资格并写保护／关闭意图；唯一发送出口再次核验，已越过发送线性化点的命令进入在途核销，不能声称未发送 |
| 已发送 OPEN，撤销先于 ACK | ACK 原件可存历史，但不得 Ready；关闸／AUTH_FENCE 按既有适用范围推进，未确认关闭保持保护 |
| Ready 事务后观察丢失或进程崩溃 | 查原确认历史，重启仍撤本地 Ready；重新验证出口与当前授权，不能重放 OPEN 或隐式恢复自动化 |
| 撤销写集任一步失败或 COMMIT 不确定 | 不发布新 Ready；保护及关闭走既有存储故障路径，查原后再恢复；不能把异常当成“撤销没有发生” |
| 存量普通授权被撤回，但安全取消仍获独立授权 | 只可选择 cancel_only 的固定范围；不得恢复普通闸、释放未知占用或复用普通命令凭证 |

撤销保护与全部受影响设备／待发／在途的原子传播仍须接入既有账本验证；这一设计表不等于已经完成并发闭锁。跨库身份提供者的响应有效窗口也不是瞬时撤权保证，必须保持既有 freshness 与主动撤销的界限。

## 验收与下一处接线

[检查器](check_open_authorization.py)仅验证需求 Schema、JCS 摘要、持有人一致性与时间边界，并明确验证“全部引用均为合成占位”仍能通过结构检查；该反例证明 Schema 不能代替真实权威。正反例涵盖四分支、错误主体、空／多余证据、未知字段、旧凭证形状、数字与大整数、到期等号和重算摘要后的身份错配。[报告](open-authorization-report.json)不宣称数据库、身份、撤销传播、完整 OPEN 或真实设备通过。

后续接线必须依次完成：当前设备授权状态与撤销切点的完整同库原件；ordinary/manual 的实际挑战、范围及认证有效期链；automatic 的内部评估器来源；cancel_only 的独立取消授权来源；首次恢复登记与完整306表链绑定；OPEN／ACK／Ready 与撤销的逐写、漏写和双连接竞争验收。任一来源缺失，维持 protected，不能以本需求对象补齐占位 authorization_ref。原批准 API／IPC、旧报告和业务代码均保持原样。
