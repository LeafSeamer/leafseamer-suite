# Seamer完整裁决接收候选

状态：`approved=false`。本候选将[Controller持久裁决](TYPED_CONTROLLER.md)接入[Seamer摄取布局](ATOMIC_INGRESS.md)，交付[本地观察Schema](adjudication-receive.schema.json)、[123表组合DDL](seamer-adjudication-receive.sql)、[新增约束](adjudication-receive.sql)、[参考writer](adjudication_receive_model.py)、[检查](check_adjudication_receive.py)和[报告](adjudication-receive-report.json)。全部运行在合成提供者及内存SQLite中，业务服务未实现。

## 已知事实

完整RequestAdjudication已由两个独立Controller参考库实际提交，并能经lookup返回；accepted仅证明持久受理，不能证明发送或动作完成。not_found不能证明请求未发送，运输失败也不能当作永久拒收。（来源：[Controller模型](typed_controller_model.py)、[命令契约](COMMAND_CONTRACT.md)。）

接收writer仅持有Seamer连接，不读取Controller数据库。测试夹具从Controller已提交记录取得原件，再以显式合成证据调用writer；可信提供者的认证、持久性验证和网络查询本身尚未实现。`trusted_provider`、`authenticated`等布尔字段是本地测试边界，禁止作为公共HTTP参数接受。

## 具体契约与状态规则

本地Observation是封闭对象，全部字段必需：

| 字段 | 约束 |
|---|---|
| observation_id | 本地观察幂等身份，1–256字符，仅字母、数字、下划线、点、冒号、短横线 |
| submission_id | 本地提交引用，不加入Controller公共请求 |
| identity | 从SDK唯一类型图复用完整RequestIdentity，逐字段匹配已持久请求 |
| source | create_response、lookup、transport_timeout、transport_error |
| result | create_response必须found；lookup允许found/not_found/indeterminate；运输异常必须null |

本地提供者另外绑定attempt_id、观察摘要、来源Controller scope、持久记录验证结果及裁决摘要。必须已有原attempt；身份、摘要、Controller scope及revision均须匹配。裁决的command_ref和commit_ref保留远端原件，不用本地submission_id代替；本地receipt主键独立生成，远端裁决唯一性按Controller scope与远端ID组合。

| 观察与旧状态 | submission | 步骤与run |
|---|---|---|
| 首次found accepted，步骤仍pending | accepted，保存完整裁决 | submission_pending推进accepted；outcome仍pending，业务状态不提交 |
| 首次found rejected，步骤仍pending | rejected，保存永久墓碑 | failed；必需步骤同事务暂停、锁存并建立完整保护 |
| 无持久裁决且not_found/indeterminate/运输异常 | indeterminate | unknown，同事务建立保护；不能换幂等键重发 |
| unknown后迟到accepted或rejected | 只补最终受理裁决 | unknown及已有终态、暂停、锁存和保护账不改 |
| 已有裁决后迟到运输异常或not_found | 保持原裁决 | 不降级已确定受理，不凭观察伪造动作终态 |
| 同observation_id、相同正文 | 零写查原 | 仍校验当前观察者权限；异正文冲突 |
| 同请求收到不同裁决正文 | 拒绝 | 全事务无写，不能覆盖原裁决 |

可选步骤的确定failed沿用原策略，可不暂停；unknown仍要求保护。已经暂停时其他并行动作的迟到accepted可以补齐受理事实，不解除暂停，也不允许R5。动作完成证据仍经独立生命周期处理，此候选不将accepted转换为succeeded。

## 原子性与容量

BEGIN IMMEDIATE内完成原请求/attempt查验、sa_observation、完整裁决与ADJUDICATION审计/outbox、提交状态、步骤修订、必要的STEP_TERMINAL、run暂停、锁存、sf/sp完整保护计划及sa_commit。发生保护时，最后计量实际新增/改写逻辑正文并写pb_use/pb_commit；整个事务通过独立外键检查后才能COMMIT。

sa_commit先于计量，确保本地审计通知也进入差集。它只是事务内的投影一致性封存，不表示事务已提交或远端已关闭。protection_plan_registry到pb_commit的延期外键以及pb_commit的完整账户守卫，保证缺预算记录不能提交；sa_observation与sa_commit互相绑定，防止孤立观察。逐写异常和漏写用例同时覆盖两种封存，不以应用预提交外键检查代替SQL约束证明。

实测旧16 KiB合成单行包络拒绝完整失败保护库存，本轮保留该反例。正例在初始化前选择`sim-typed-receive`合成profile，单行上限128 KiB，随后正常生成profile摘要及全部arm/recovery预留；没有改已持久预算或关闭守卫。旧profile及其报告保持原样。新正例验证计量中的sa_observation/sa_commit和实际差集逐项一致；这不证明正式工作负载的最大包络。

保护确认在任何保护写入前变为unconfirmed，成功提交后才为durable；异常回滚或预览不能保留本次durable。durable仅指本地保护任务及预算落库，不表示Controller关闭ACK或设备效果。失败回滚保留原attempt；调用方须按已有监督/关闭协议处理，不能将接收失败报告为成功保护。

## 故障与验收边界

- 创建响应丢失：原Controller裁决保持持久；Seamer先unknown并保护，后续有权lookup仅补历史，不自动恢复。
- 查原暂时不可读或not_found：没有rejected墓碑，不构造command_ref；禁止据此重发设备操作。
- 观察同ID冲突、attempt错绑、issuer_epoch变化、重摘要跨Controller引用或失去当前观察权限：拒绝且无写。
- 任意写后异常、漏裁决/状态/审计/保护目标/预算/封存：整笔回滚；重复观察不重复消费。
- 人员操作权限失效不阻止已授信系统观察者执行保护；缺可信关闭、时钟等待或易失关闭证据仍不允许报告保护落库成功。

本轮只验证内存SQLite、合成授权/时间/完成资格及逻辑正文计量。真实HTTP/IPC、进程崩溃和磁盘恢复、并发、正式原生制品、设备及物理WAL/空间成本未验证。普通arm/recovery/manual完整请求、公开CommandRecord、最终AdmissionSeal、全系统SDK单一来源、完整CostManifest和GC仍待完成；不得据此关闭阶段0或开放最终发送。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_adjudication_receive.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_controller.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_adjudication_receive.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_adjudication_receive.py --check-report
```
