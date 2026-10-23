# RUN证明撤回到资源保护的同库候选

状态：待审阅。在[保护交付232表](PROTECTION_DELIVERY.md)上增加3张来源表，生成[235表组合](controller-run-resource.sql)。旧候选保持原样，不是业务服务或生产迁移；现有四个最终发送阻断保留。

## 已知事实与修订理由

已知事实：原cr_validation已有取消结果来源清单，原cr_validation_revocation能够传播到释放失效、风险占用、设备保护和关闭通知。RUN保护交付能撤回当前应用资格，但尚未记录资源验证对RUN原件的直接依赖。（来源：[取消结果依赖](result-dependency.sql)、[资源表](resource.sql)、[保护交付](protection-delivery.sql)。）

本轮分析：按设备粗略撤回所有证明会误伤独立证据；只撤回公开状态又会漏掉实际依赖的释放。因此推荐为每份资源验证显式封存RUN来源维度，并复用原验证撤回链，不再创建另一套风险或恢复权威。资源提供者仍必须完整证明原有政策；依赖关系不是新的释放资格。

验证还发现：旧关闭通知只登记当时未退役出口，恢复可能没有显式引用被省略的退役证明。新反例在旧捕获规则下实际得到仅exit.0，期望的完整历史集合为exit.0和exit.1。本候选将完整历史出口保留在目标表；有效退役只免除网络关闭，恢复必须显式采用退役证据。

## 字段和完整来源

| 表 | 字段及约束 |
| --- | --- |
| rr_manifest | validation_id双向关联cr_validation；source_count为0至256；manifest_digest、manifest_body；反向FK要求同事务rr_manifest_commit |
| rr_source | (validation_id,kind,source_id)唯一；kind为run_ack或run_application；fence_id、source_body精确绑定原件 |
| rr_manifest_commit | validation_id、manifest_digest、provider_ref、receipt_body、audit_body；提供者和回执必须与资源验证一致，最后seal重新检查全部来源 |

所有资源验证都必须有本清单，包括hold、close、settlement、release、recovery。零行必须显式source_count=0并封存，表示不依赖RUN来源，不能把缺清单当作独立。它与原cd_manifest的取消结果维度并存；各声明的零依赖只针对相应维度，不能覆盖另一份非空清单。

规范manifest正文为`version=run-resource-dependency/1`、`validation_id`、`sources`；sources按(kind,source_id)的UTF-8字节序排序，禁止重复，每项含kind、source_id、fence_id和原source_body的bytes_digest。manifest_digest是整个规范正文的JCS SHA-256，不包含自身。可信提供者在资源validation的原回执中绑定完整manifest及既有政策、主体和对象；writer核对规范正文与关系表双向集合。SQLite只核关系、计数和原件字节，不执行JCS或认证；非空BODY不能证明提供者真实或没有漏报依赖。

run_ack必须是原ce_result_binding实际采用的ce_barrier_ack，来自固定fence/出口，原BODY相等且未被ra_barrier_revocation撤回。未采用、被替代或错误出口的ACK不能充当来源。run_application必须是当前pd_valid_application中的固定receipt，已覆盖完整原出口与准备Closure；来源不是旧ce_application存在性。完整应用失效时，其资源依赖失效；只依赖另一份仍有效出口ACK的验证不会因无关出口失效自动撤回。

非recovery验证的command必须属于该fence的完整origin authority/database/run，代次不高于被拒代次；每份来源还必须覆盖validation的device。recovery没有command绑定，仍核设备及原件，完整恢复的资源、全部关闭目标与政策另行合取。不能把RUN ACK当作manual取消已结束的证明；原取消关闭、双政策释放及所有传输核销要求继续独立成立。

## 原子撤回、恢复与旧出口

写集为cr_validation→rr_manifest→全部rr_source→rr_manifest_commit，与原cd_manifest和业务使用同事务提交。缺清单、缺成员、错原件、错run/设备/提供者或先撤回后封存均拒绝。封存后不能追加来源、更新或删除原件；即使成员预写时有效，seal仍重新检查。

原RUN ACK撤回沿直接run_ack来源插入cr_validation_revocation；完整应用的ra_status_event修订2沿run_application来源插入同一撤回表。继续通过cr_release_validation覆盖父/取消政策、关闭及普通/取消核销等既有引用，触发原释放失效、风险hold、设备保护及ro_target关闭通知。一个原件可以影响多个验证和释放；同验证只追加一次失效，所有源撤回及来源关系保留，多个原因不因去重丢失。应用撤回的reason/audit正文记录fence和状态修订的内部来源引用，不复用旧成功回执冒充撤回原因。

通知、incident、任一验证撤回或释放失效写入失败，会回滚整个源撤回事务，包含P3状态事件。真实writer必须随后保持内存关闭并进入原数据库故障保护流程，本实验未执行该运行路径。提交未知先查原，不重发设备动作，不假装内存保护已耐久。

cr_valid_validation同时合取原取消结果清单和本RUN清单。释放/恢复最后提交依赖当前有效验证，避免预写后撤回再提交。原件撤回不删除ce_application、资源释放、命令结果或已签许可。新独立现场证据可以按政策解除风险，但不能消除历史失效或自动恢复设备。

关闭目标现在包含该设备全部已登记历史出口；rr_valid_retirement仅暴露未撤回的退役证据。ro_pending免除仍有效退役的网络关闭；ro_valid_recovery_target对退役也检查当前有效性，不再仅看非空ID。退役证明撤回会使旧恢复失效并补齐此时的完整出口目标，已经消费过的关闭ACK不能被旧恢复再次利用。旧出口无真实可达worker时只能保持保护并重新取得监督证据，不能凭记录尚在把它当安全退出。

## 验证及范围

```text
python docs/contracts/c08-controller/build_run_resource.py --check
python docs/contracts/c08-controller/check_run_resource.py --report
python docs/contracts/c08-controller/check_run_resource.py --check-report --staged
```

[报告](run-resource-report.json)记录实际用例数和输入摘要。检查加载完整235表、不删除守卫：采用ACK与完整应用来源、双来源去重、多释放扇出、取消双政策、零依赖隔离、完整写集缺写/逐写异常、预写来源后撤回、最后释放提交重核、通知链逐层失败回滚、独立重新取证后恢复、恢复验证再撤回、旧ACK不可复用、显式退役恢复及撤回后的关闭重开。

资源端到端夹具是尚未发送设备动作的取消独立hold，完整普通及取消许可集合均为空；没有放行最终发送来制造已发送夹具。普通/取消传输核销引用沿用原cr_release_validation，但本轮未实际运行带设备发送历史的新增综合用例；不能将此报告扩称全部在途场景验收。提供者、政策BODY和来源清单完整声明为合成前提，真实服务、IPC、并发、磁盘、通知网络、NTP与设备未执行。

剩余事项：将本来源清单归并统一SDK及实际提供者；准备closed/恢复消费者与通知服务；真实P1计划引用；AUTH/TIME与剩余消息共享日志；完整AdmissionSeal/Guard/预算/时间及跨库恢复。当前成果不关闭这些缺口，也不关闭阶段0。
