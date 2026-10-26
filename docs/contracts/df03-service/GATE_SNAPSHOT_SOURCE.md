# OPEN参考时间下界的持久来源候选

本候选属于DF03/C04的时间来源接线，`approved=false`，不更改draft.4或现行IPC字段。它只证明拒绝下界的来源，不证明UTC可用、设备可发或OPEN已完成。权威裁决见[DF03第18节](../../rebirth-df03-time-profile-design.md#18-open时间下界的持久来源与运行身份)。

## 1. 字段与确定性身份

复用现行IPC的`S12__GateSnapshot`。不再为同一State引入独立可变floor、额外snapshot序列或额外持久快照表。

| 字段 | 唯一来源与约束 |
|---|---|
| `domain` | 完整`AuthorityState.binding.domain`，保留时间提供者身份及其`runtime_binding_ref` |
| `state_ref` | 原State的`state_id/revision/state_digest`，不使用同ID的最新值替换旧引用 |
| `snapshot_revision` | State的原始十进制revision，禁止浮点或有符号64位转换 |
| `minimum_time_generation` | 原Binding的time_generation；失效提交精确加一；不能按worker声称的floor倒写源State |
| `snapshot_id` | `time-snapshot.`加`SHA256(JCS({format_version:"time-floor-source/1",domain,state_ref}))`的小写十六进制部分 |
| `snapshot_digest` | 对除自身字段外完整快照作JCS/SHA256 |

同一State重复查原产生完全相同的ID、修订、摘要及正文。保留该算法版本，不能在原State上换算法继续使用旧身份。相邻State即使没有推进time_generation，也产生不同快照，旧OPEN候选须重新选择，沿用既有保守的State精确绑定。

## 2. 物理来源和信任边界

读取必须位于调用者持有的事务。通过`ts_head → ts_state → ts_commit/ts_seal/ts_audit/ts_outbox`找到唯一已封存来源，核完整State和Binding的规范字节、Schema、摘要、修订/状态/代次列及`ts_scope`。qualified还核完整Anchor与精确引用、Binding和采样tick；unavailable还核完整Invalidation、旧Binding、新Binding及下一代次。拒绝占位正文、重复键、超过65536字节、额外空白和重算摘要后的物理列错配。这里检查的是已持久的小型元数据正文，不把NTP原始报文送入OPEN。

这些检查以可信writer安装了原SQL约束并独立验证过来源为前提。seal存在、摘要一致及外键完整均不能代替密码学验证、采集器启动身份或当前监督资格。原始报文、Verification、加密与批准的完整提供者接线仍须完成，不能用本读取器把旧合成BODY升级成可信事实。

`source(revision)`只查历史；`current(expected_provider_domain)`必须从当前head重读并比对可信监督解析器交付的完整提供者Domain。`for_open`进一步核快照完全相等和设备出口共享的authority/database/clock_domain_id/descriptor_digest。参数中的“expected”必须来自可信内部解析器，禁止公开请求或插件自填。

时间提供者和设备worker属于不同受监督成员，因此不要求两者`runtime_binding_ref`相等，也不能把快照中的提供者Ref替换成worker的Ref。共同的时钟ID和描述摘要必须由两份完整当前运行原件分别证明。相同主机名、PID、启动时间、UTC值或仅一项相等都不能建立共享时基。本模型只验证关联值，不伪装成已完成这两份监督原件的真实解析。

## 3. 状态、失效与提交顺序

| 来源状态或事件 | 下界读取 | 对OPEN和发送的影响 |
|---|---|---|
| collecting | 当前State可生成floor | 不是UTC许可；其他OPEN资格仍独立要求 |
| qualified | 核Anchor后生成floor | 仍须在每个依赖UTC的动作上检查完整Bundle、Assessment、年龄和窗口 |
| unavailable | 核Invalidation后生成提高的floor | 必须传递拒绝下界；不得因无Anchor退回旧qualified快照 |
| 原件缺失/错配、当前提供者域不符 | 拒绝读取 | 不生成OPEN候选，不用默认值或旧缓存继续 |
| 新State先于OPEN提交 | 旧快照精确比较失败 | 放弃旧候选，重新解析全部资格，不重发旧attempt |
| worker已保存更高floor/修订 | 拒绝降低 | 不能从迟到快照恢复已撤销资格 |
| 旧记录查原/提交响应丢失 | 返回相同确定性正文 | 查询无副作用，不刷新资格，不改head，不建立新快照身份 |

正常轨迹：时间发布State 2并封存 → Controller writer同事务读取当前原件 → 构造确定性快照 → 完整OPEN候选绑定快照Ref → worker核当前域和不回退floor → ACK精确回显 → Controller采用时重读全部资格后提交Ready/Scoped。最后四步仍由完整OPEN实现负责，本模型未执行它们。

故障轨迹：选择State 2/floor 1 → 失效先提交State 3/floor 2及TIME保护 → 原State 2仍可审计查原 → OPEN当前性核对拒绝State 2 → 新选择只能携带floor 2。TIME通知存在不等于设备ACK已到；来源floor、实际屏障和完整恢复是三个独立条件。不能以读取成功提前清除保护。

最终OPEN选择/发送记账/采用所需来源必须与Controller当前资格在**同一writer裁决域**内核对；独立连接的旧WAL读快照或先读远程时间库再写Controller都不满足该要求。首期推荐时间State放在Controller自己的SQLite库，时间采集器只报告候选，继续禁止跨主机直接共享monotonic tick。后续[290表读取组合](../c04-lifecycle/OPEN_TIME_SOURCE.md)已将本14表与276表Controller恢复布局组合，并在恢复首次写入时登记真实的确定性时间ID；仍是离线候选，生产链及四个最终发送阻断保持。

## 4. 正反例与验收

[检查器](check_gate_snapshot_source.py)在原14表SQL中，**首次写入前**填入完整State/Binding/Anchor/Invalidation合成原件，未修改任何历史记录或模型返回值；验证产生的快照符合现行IPC Schema。

- 正例：collecting/qualified/unavailable三个状态；不同provider/worker运行身份共享同一时钟；同State稳定ID；精确失效后floor推进；历史原件保留；大整数纯字符串；重复读取全表无变化。
- 反例：无事务、八项提供者Domain逐项错绑、四项出口公共域逐项错绑、已接收水位更高、重新计算摘要的伪快照、正文与物理列不一致、占位/重复键/非规范/过大正文，以及失效后用旧快照OPEN。
- 结果保存于[独立报告](gate-snapshot-source-report.json)，报告绑定实际输入字节；`--check-report`仅核输入绑定，不能冒充重跑。

后续整合验收必须覆盖可信监督原件、全部时间发布来源、与TIME/恢复同库的原子关联、实际OPEN/ACK/Ready和真实提供者。WAL双连接变化后最终writer重读的离线反例已在290表组合运行，不替代实际服务writer验收。离线来源检查不是完整运行证据，也不放宽指定NTP、两平台与误差区间要求。
