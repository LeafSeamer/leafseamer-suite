# 准备当前资格与独立保护传播候选

状态：离线设计候选，`approved=false`，不改变draft.4／IPC0.3，不实现业务服务。本页接续[66表准备登记](REGISTRATION.md)，补准备观察冲突、关闭和授权撤回的持久隔离，复用已有保护状态接收器。由[生成器](build_qualification.py)将[新增约束](qualification.sql)组合为[72表布局](seamer-qualification.sql)；[参考事务](qualification_model.py)仅运行SQLite写集，不发送设备或网络命令。

## 已验证事实

[检查脚本](check_qualification.py)和[结果报告](qualification-report.json)记录112项内存SQLite检查。新库从开始即安装完整约束，通过既有摄取写集形成历史执行，再实际运行R2登记、准备尝试、观察采用和显式恢复。未卸载守卫导入历史。旧66表夹具新增可选layout参数后，其105项检查另行回归，仍由[原报告](registration-report.json)绑定原范围。

验证覆盖撤回全部写入的逐条省略和写后异常、关闭与冲突接收的逐写异常全库回滚、错绑定/提供者/摘要、四种撤回原因、同数成员替换、局部容量失败、准备中/ready/running失效，以及未知提交增加第三Controller的完整保护集合。旧代次撤回迟到不改变更高代次的run与锁存，新代次仍可在重新登记、取得观察并显式恢复后启动。新代次夹具中的锁释放证据是合成前提，不是实际资源释放验证。

R5反例只证明最后插入的旧代次拒绝守卫；并未因此增加完整R5成功提交的验收结论。保护applied到达只减少待处理目标，后续indeterminate重新列入待处理，二者均不恢复原准备资格。

## 字段与状态约束

[撤回Schema](preparation-qualification.schema.json)为具名`$defs/Withdrawal`，版本`preparation-qualification/0.1.0-draft.1`；根对象刻意不可直接实例化。对象禁止额外属性，正文上限16KiB。

| 字段或对象 | 约束与含义 |
| --- | --- |
| contract_version／event_id | 固定候选版本及事件Id；去重以原登记的首失效事实为准，不能依靠重用event_id清除失效 |
| binding | 复用原Preparation Binding，精确绑定Controller与Seamer完整scope、准备Id、run、generation、mode、execution和请求摘要 |
| reason | authorization_revoked、grant_expired、controller_instance_changed、stream_unconfirmed |
| proof_ref | scope、id、revision、digest；revision沿用正U20字符串，完整scope必须等外部已授信提供者 |
| withdrawal_digest | 对排除此字段后的JCS正文计算SHA-256；匹配摘要不证明提供者有权撤回 |
| pq_observation | 按registration_id、准备revision、保护revision保存不可变原观察、binding、摘要、审计与通知。不可用状态反向延迟引用同登记pq_fault，不能单独提交 |
| pq_fault | 每登记首失效一槽，类型conflict／unavailable／withdrawal；保存首证据、摘要和独立plan_id，后续失效不无限增长、不清除首事实 |
| pq_plan／pq_target | 原登记、受损代次、当前代次、精确run前后修订、准备登记水位、完整成员、Controller集合、原保护binding及派发正文 |
| pq_commit | 同事务封存run后态、独立锁存、完整集合及共享sp计划；缺少反向引用、目标或通知均不能提交 |
| protection_plan_registry | 来源P1与准备保护严格互斥分类，同一sp接收器从此注册表引用；po准备关闭接收仍要求原P1，不能冒充其来源 |

`pq_current`只有三种投影：无最高applied观察时为`pending`；最高观察applied且没有首失效为`observed_applied`；存在首失效永久为`invalidated`。后者优先于任何迟到成功。原pr_receipt和Controller applied原件保持历史事实，不改写为失败。`observed_applied`只表示最高已观察状态，不证明grant在当前时刻仍有效，也不证明通知流健康。

当前资格守卫用于ready、回执采用、R4、step_ready、command_submission、submission_attempt和R5；共享拒绝下界另覆盖旧代次。正常arm尚未进入本布局的完整登记链，不能把无准备记录解释成已经通过全部准入。

## 原子时序与代次隔离

1. 验证具名Schema、JCS摘要及外部认证域；进入`BEGIN IMMEDIATE`后核对原登记binding，并与历史观察检查冲突。完整认证/授权与真实时钟判定属于可信提供者，参考函数的scope相等检查不能代替它们。
2. 接收有效新观察时保存原件；最高applied可沿原R2回执采用链配对。关闭、拒绝、indeterminate或同身份矛盾时，同事务建立首失效与保护计划。关闭先到后补旧applied只保存观察，不伪造历史采用。
3. 保护成员包含同run受损代次及以下的全部准备、全部历史执行及其binding_digest、全部历史提交。响应未知、失败、尚未尝试均不从集合删除；目标为准备与提交完整Controller scope的并集。SQL以数量与集合差集共同拒绝省略、重复替换和额外目标。
4. 受损代次等于当前代次且run未completed：精确增加修订、置paused、关闭dispatch，追加原因为preparation_qualification的独立锁存。completed保持终态和修订并追加保护锁存，不能恢复执行；此分支本轮只审阅约束，未新增独立completed运行用例。
5. 受损代次小于当前代次：保持当前run的生命周期、修订与锁存，不把新代次准备或执行加入旧保护集合。拒绝下界仅推进到受损代次，不借旧故障封锁新的显式恢复。
6. 保护计划、完整目标、sp接收计划及两端seal同事务提交。提交确认后才可由未来消费者向Controller输送；参考dispatch_body是内部protect_registered_run请求，不是完成鉴权的公共HTTP请求。
7. 同源精确重复零写；新冲突仍保留首失效。共享sp接收器可以继续保存旧保护applied或新indeterminate，但保护观察不授予原准备重新执行。恢复必须另走新代次的显式操作和完整准入。

## 故障边界与待落实事项

- 事务中缺写或异常：整个持久写集回滚，不能留下半个失效或半个保护计划。容量不足、磁盘不可写、COMMIT结果未知时，回滚可能保留旧观察资格；实际运行层必须立即触发受监督的volatile_close，再按原请求身份查账。该运行联接尚未实现，不能只依赖数据库触发器宣称已立即停发。
- 正文、引用与摘要：SQL固定关联和集合，参考writer验证Schema及JCS摘要；SQL本身不完成证据签发者授权、摘要真实性或外部对象的资格核验。
- 容量：限制目标数、计划总数和本次选定正文总量；不是完整P0预留，也不覆盖全部历史、WAL、磁盘或通知排队容量。保护预算必须在正式准入前预留，不能通过截断集合继续执行。
- 时间和通知：grant_expired与stream_unconfirmed是已授信事件输入，尚未联接应用参考时钟、误差区间、流游标和实时失效提供者；在撤回抵达之前仍存在传播窗口，旧观察不能替代唯一发送出口的当前核验。
- 下一收敛工作：正常arm与完整P0预留、来源baseline/resolution及新代次恢复条件、AUTH/TIME提供者、Controller最终AdmissionSeal与四个发送阻断的完整替换、唯一SDK及全部API/IPC同版归并、实际通知/GUI消费者。保持阶段0未关闭，设计完成后再进入业务实现。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/build_qualification.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_registration.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_qualification.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_qualification.py --check-report
```

本轮未验证真实服务、并发、通知网络、磁盘崩溃、NTP或设备。内存SQLite检查不代表产品平台、掉电恢复或直播安全已获验收。
