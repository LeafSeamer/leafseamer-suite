# 准备状态交付与接收候选

状态：待审阅。使用上一轮[237表Controller](PREPARATION_COMPLETION.md)的真实原件，新增[可校验片段](preparation-delivery.schema.json)、[单快照导出及接收模型](preparation_delivery_model.py)和[独立六表观察库](preparation-receiver.sql)。不改已批准公共API、业务服务或原Controller布局。

## 事实与推荐

已知事实：cp_event保存准备历史修订，pc_status_event保存完成后的保护修订；closed可以在保护证据撤回后仍作为不可变历史存在。旧保护交付模型仅导出HTTP ProtectionRequest来源，不能替代准备关闭来源。准备合法迁移没有循环，close可以先于prepare到达。（来源：[准备SQL](../c04-preparation/preparation.sql)、[准备完成SQL](preparation-completion.sql)、[旧交付模型](protection_delivery_model.py)。）

本轮推荐：分别保存准备revision及保护revision，通过一条SELECT导出同一快照，P4接收按两个修订轴保存历史。只允许符合原状态图的乱序补入；同认证来源、同计划绑定的矛盾证据须持久标记未确认，不能仅报错并继续显示旧成功。整个观察层不提供设备发送、资源清空或恢复权限。

## 片段字段与验证边界

选择Schema的具名Observation，根Schema刻意不作为裸请求入口。所有对象禁止额外字段；ID为受限ASCII且最长128，摘要为sha256加64位小写十六进制。它仍须被已有认证、时钟和版本包络承载。

| 字段 | 固定规则 |
| --- | --- |
| contract_version | preparation-delivery/0.1.0-draft.1，仅候选版本 |
| binding | controller_scope、origin_scope、preparation_id、run_id、generation、mode、execution_id、request_digest；与已封存计划目标逐字段相等，mode=arm时execution_id为null，recovery时必填 |
| preparation_revision、previous_revision | 原准备事件修订，线上正十进制字符串；revision1的previous为null，其他严格减一。SQLite边界按U20补零，绝不经过浮点数 |
| state | accepted/applied/rejected/indeterminate/closing/closed，保留原历史，不与保护状态混淆 |
| applied_receipt_ref | 原准备applied回执ID及精确字节摘要；从未签发时为null，签发后所有关闭历史保留同一原件 |
| close_ref | closing/closed必须含原close ID、operation_id、operation_digest及request_body精确字节摘要；其他状态为null |
| completion | closed必填completion ID、fence_id、cut_ref、保护receipt_ref和prepare_closure_ref；其他状态为null。cut_ref.id必须等于fence_id |
| protection_revision、protection_state | 未closed为字符串0，非closing对应not_applicable，closing对应pending；closed只能1/applied或2/indeterminate |
| cause | 未closed为null；初始完成指向fence，失效指向准备Closure、采用RUN ACK或退役出口，沿原ra_status_event精确导出 |
| observation_digest | 除自身外整个片段的JCS SHA-256；原件bytes_digest只对原始字节求摘要，不能与JCS摘要混用 |

generation可达20位，例如99999999999999999999；准备revision虽然使用相同安全字符串编码，但当前状态图推导最多4步。模型显式枚举原图的合法路径，检查每条消息及全部已观察消息能否属于同一条路径，包括applied回执的有无。它不允许凭“修订更大”接受不可能的状态跳转。今后改变状态图必须同版修改Schema关联检查、SQL修订边界和用例，不能只增加enum。

原事件与当前查询分开：历史导出必须显式给出两条修订轴，当前导出走pc_current及最高保护事件；证明撤回后历史成功正文不变，当前查询返回失效。不存在或无法确认的原记录必须报查询失败，不能制造not_found授权重试，更不能补造applied回执。导出一条SQL保证读快照一致，但不保证结果离开数据库后仍为最新。

模型接收已解码对象，验证Schema、JCS摘要、关联和外部传入的认证Controller域；不能从正文自授身份。BODY真实性、原件摘要是否由可信提供者形成、重复JSON键和原始网络帧解析仍是外层职责。合法结构只是可审计引用，不证明真实设备状态。

## 持久写集、乱序与冲突

po_plan/po_target/po_plan_commit导入已经核验的完整准备目标集，目标数为1至65536且不可重复；数量上限沿用交付候选，不等于生产容量批准。计划正文与摘要固定，封存后不能追加目标。导入validation_body仍为合成信任边界，尚未联接真实P1计划、fault、latch及outbox外键。

正常P4写集为po_observation和po_observation_commit（audit、重查通知），双向外键保证不能只存半条；提交成功才可确认接收。原观察键为(plan,target,preparation_revision,protection_revision)，同键同JCS正文返回duplicate，不能因此重发设备动作；不同保护修订必须保留相同准备事件、原回执、close及completion身份。两次修订的不同cause沿各自原事件保存。

较旧合法观察可以补入历史，但po_current_observation只取最大准备修订及该修订的最大保护修订。失效先于成功、closed先于closing、旧applied迟到均不能回退当前观察。准备state=applied仅表示过去签发准备，不等于关闭applied；rejected和准备indeterminate同样不能代替完成保护。多Controller目标全部已观察closed且保护applied才汇总applied，缺任一目标保持pending，失效为indeterminate，冲突优先为unconfirmed。

同认证Controller、同封存binding且通过单条结构/关联验证后，如果出现同键不同正文、跨修订更换原件、替换已签准备回执或无法属于同一路径的历史，接收事务保存po_conflict，而不把矛盾消息放入正常观察序列。第一条冲突包含完整正文、摘要、原因、审计和重查通知；每目标只占一个不可变冲突槽，后续相同冲突去重，不同冲突返回conflict_retained并保留首证据，不声称已保存所有后续正文。正常消息可继续补历史，但不能自动清除此目标的未确认状态。治理性解决仍须完整恢复/新准备流程，不提供删冲突或强制改绿入口。

每个观察正文上限16KiB，target绑定也有16KiB后备上限；正常模型每目标至多5条观察，冲突仅1条。SQL修订槽限于1至4，正文和状态配对也有后备约束；完整路径和原件一致性由可信接收模型验证。目标总数、全局计划生命周期、磁盘余量和审计保留预算尚须接入统一容量政策，不能由这些局部上限宣称全系统容量已完成。

错误认证域、错误计划binding和结构错误在入库前拒绝，不允许外部错误消息污染目标。已经认证的解析或存储故障必须由真实输送层维持保护、标记流状态未确认；本模型未实现该外层行为。接收/冲突提交异常整体回滚，不发送成功确认，不能把回滚后尚在库中的旧applied显示为已获得新的健康证明。

## 故障与验收

1. close先到：Controller原子保存准备身份、closing墓碑、deny及完整RUN cut；晚到准备不能补发grant；完整出口证明与应用提交后，closed仍保持applied_receipt_ref=null。
2. 正常准备先到：accepted→applied→closing→closed；关闭完成后任一采用证据撤回，当前为closed/保护indeterminate，原准备回执保留。
3. 失效先到P4：先保存保护修订2，后到修订1只补历史；旧accepted/applied/closing也不能改写当前closed。
4. 接收提交成功但响应丢失：重新查询/发送同规范观察只返回原接收结果，不增修订、不重新执行动作。接收两写集缺写、逐写异常和冲突插入失败均回滚。
5. 同一目标矛盾消息：第一条冲突持久化并显示unconfirmed；后到正常成功或失效不清该诊断，冲突流量不能无限增长单目标存储。

```text
python docs/contracts/c08-controller/build_preparation_delivery.py --check
python docs/contracts/c08-controller/check_preparation_delivery.py --report
python docs/contracts/c08-controller/check_preparation_delivery.py --check-report --staged
```

[检查器](check_preparation_delivery.py)实际加载237表Controller和六表Seamer观察库，两个Controller均独立建库；覆盖关闭先到、正常路径、三类撤回、代表性乱序、历史与当前导出、回执身份、同修订矛盾、故障原子性、错误来源/结构、修订及正文容量、计划封存、不可变与外键。[报告](preparation-delivery-report.json)记录实际检查数和完整输入摘要。真实身份、通知网络、HTTP/GUI/P4服务、并发、磁盘崩溃、NTP和设备均未执行；不是已经完成端到端产品。

Controller事实提交与Seamer观察之间仍有传播窗口，旧已观察applied不代表远端持续有效，也不能解锁恢复。剩余冻结包括真实P1导入、通知游标及流健康、实际消费者与唯一SDK同版归并、AUTH/TIME、剩余消息共享日志、非空在途综合历史和完整AdmissionSeal/Guard/预算/时间。四个最终发送阻断保留，阶段0未关闭。
