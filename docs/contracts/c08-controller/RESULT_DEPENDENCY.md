# 取消结果到资源证明的因果依赖候选

状态：待审阅。新增3张来源关系表，与[独立占用129表](PROTECTED_HOLD.md)组合为132表；旧候选与报告保留。不是生产迁移或真实提供者实现。

已知事实：`cg_result_member`固定结果采用的全部传输；`cg_dispatch_dependency`固定每次传输采用的前驱结果。原资源释放依赖视图已经覆盖普通及取消关闭、核销和双政策释放验证，但尚未与取消结果关联。（来源：[动作图](cancel-plan.sql)、[共享资源](protected-hold.sql)。）

基于这些事实，本轮推荐把每份`cr_validation`的直接来源显式化，再沿实际传输采用关系追溯祖先。计划中未执行的边不自动成为证据依赖；同设备无关结果也不自动撤回全部证明。

## 字段与完整性

| 对象 | 字段与约束 |
| --- | --- |
| cd_manifest | validation_id与cr_validation双向关联；basis为independent或cancel_result；source_count为0至256；manifest_digest及完整manifest_body；必须同事务封存 |
| cd_result_source | validation_id、result_id、result_digest；一个原件一行，指向已封存结果；封存后不得增补、更改或删除 |
| cd_manifest_commit | validation_id、provider_ref、manifest_digest、receipt_body、audit_body；提供者及回执与资源验证一致 |
| cd_result_ancestor | 每份结果含自身及其全部传输采用的前驱结果的递归闭包，UNION去重；跨多级、多传输、汇合边均保留 |
| cd_affected_validation | 直接来源及祖先到验证的反向关系，用于撤回扇出和事后审计 |

每份资源验证都必须有来源清单，包括hold、close、settlement、release与recovery，不能因缺行默认独立。independent必须明确零个取消结果来源；cancel_result必须至少一个，且数量与成员相等。当前批准的提供者必须核验原回执声明的完整清单、JCS摘要、政策允许的证据类别、父命令和设备；不得把依赖取消结果的证明标成独立。SQL检查数量、摘要投影、同父命令/设备、已封存成功及未撤回祖先，不能证明非空BODY真实或清单未被提供者漏报。

清单正文的规范字段为`version=resource-result-dependency/1`、`validation_id`、`basis`、`sources`；sources按result_id的UTF-8字节序排序，每项包含result_id和result_digest，禁止重复。manifest_digest为上述完整正文的JCS SHA-256（带sha256前缀），不包含自身摘要。资源验证receipt必须绑定manifest_digest以及既有subject/policy/provider原件，可信writer核对正文与关系表的双向集合后写入。数据库的receipt字节相等只是投影约束，不等同于已执行JCS或来源认证。

独立取证不是绕过未知动作的后门：必须由既有释放/核销政策允许的独立安全证据支持。结果succeeded也不单独证明资源已安全；完整关闭、全部历史传输核销和父/取消两份释放政策继续合取。failed/unknown不能作为成功结果来源；现场重新取证可建立新的独立验证，不能改写原结果或复活旧动作。

## 事务、撤回和恢复

验证事务为：cr_validation→manifest→全部直接来源→manifest_commit→使用该验证的领域写集。双向延迟外键阻止缺清单或未封存验证落库；cr_valid_validation只暴露已封存且当前有效的验证。封存再次检查全部直接来源及祖先，预写成员后发生撤回也不能借旧检查通过。

收到结果撤回时，在同一writer事务插入cg_revocation；触发器按完整因果闭包撤回全部已封存验证，沿原cr_release_validation传播到全部已使用释放、风险hold及设备保护。直接验证已撤回时不重复创建失效，但每份cg_revocation及来源关系永久保留，不丢第二个原因。历史结果及命令终态保持不变。任一步异常都回滚整个撤回事务，不允许只提交结果撤回而漏记资源保护。

若撤回先于验证封存，拒绝封存；若先于释放提交，拒绝释放；若释放先提交，追加失效并重开风险。祖先撤回同样生效，不能仅检查直接结果的succeeded标志。晚撤回发生于另一命令已占用后，保留两份风险及原许可。新的完整独立取证可清风险，但仍需覆盖全部历史失效的显式恢复；旧恢复不覆盖后来失效，不恢复取消发送或自动化布防。

本机保护持久化与worker实际停止仍有传播窗口。完整保护outbox、最终Guard/预算提供者、普通准备、DecisionEvidence、其他屏障/TIME和SDK归并继续列为设计缺口；本轮不把本地触发器当作设备已关闸。

## 验收

运行`build_result_dependency.py --check`和`check_result_dependency.py --report`。报告[result-dependency-report.json](result-dependency-report.json)记录实际检查数、参考SQLite版本及输入摘要；`--check-report --staged`只核字节绑定。

正例覆盖独立来源、直接成功来源、祖先闭包、一个结果影响多个释放以及独立取证后的显式恢复。反例覆盖缺写/逐写主动回滚、错父/错设备/错摘要/错提供者、失败未知来源、错误数量、封存后增补、成员预写后撤回及释放提交竞态。晚撤回须证明保留无关holder和许可，撤回事务注入失败须证明全库回滚。旧129表检查单独回归，不把其通过算作132表全部行为已验。

检查使用合成BODY及提供者与单进程内存SQLite；真实JCS提供者、网络/IPC、writer并发、磁盘/进程崩溃、NTP和设备测试均未执行。容量上限为候选结构界，不构成直播负载批准。
