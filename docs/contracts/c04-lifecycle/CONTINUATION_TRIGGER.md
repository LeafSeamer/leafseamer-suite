# 继续运行授权到普通触发的联接候选

状态：`approved=false`。承接[转交持久化](CONTINUATION_STORAGE.md)，[组合器](build_continuation_trigger.py)在完整117/235表候选上追加2/1表，形成119表Seamer与236表Controller。交付[Seamer关联SQL](continuation-trigger.sql)、[Controller关联SQL](continuation-command.sql)、[参考writer](continuation_trigger_model.py)、[检查器](check_continuation_trigger.py)和[报告](continuation-trigger-report.json)。公共draft.4／IPC0.3与旧生成产物不变。

## 已知事实与本轮结论

前两轮分别给出独立继续运行grant/采用原件及两侧持久化，但普通trigger仍被原recovery execution准备作用域拒绝。本轮只在明确存在新grant关联时扩展两处准入条件，保留原准备行及原execution限制。（来源：[转交契约](CONTINUATION.md)、[原持久化边界](CONTINUATION_STORAGE.md)、[本轮组合器](build_continuation_trigger.py)）

离线实验已经串联来源故障保护、baseline/delta/ready、新代R2/R4、恢复步骤完成、两个Controller签发、完整采用、恢复R5，以及之后连续两次普通trigger的双动作受理/完成/普通R5。Controller保存新命令的实际受理和公开初始状态，Seamer保存受理回执和终结原件；新grant只签发一次。**设备效果完成证据仍由合成提供者给出**，没有发送协议包或运行OBS；“普通触发完成链”在此仅指参考模型及SQLite契约链，不是设备验收。（证据：[完整检查](check_continuation_trigger.py)、[输入绑定报告](continuation-trigger-report.json)）

## 新执行与命令的明确归属

新增Seamer `cn_step(execution_id,step_id,transfer_id,registration_id,device_id,adoption_digest,grant_ref_body)`，每个普通动作唯一。它引用已持久化的转交回执和采用、原准备及完整步骤计划；只有本代恢复R5已封存、资格仍有效、device属于已批准目标时才可建立。execution必须是新trigger，不能是原recovery execution。

本轮参考动作请求增加`device_id`及`continuation={transfer_id,registration_id,adoption_digest,grant_ref}`。继续运行计划的Ref指向不含continuation封装的已批准完整步骤正文，writer验证正文摘要及实际动作/参数与批准步骤完全一致，再附加固定资格引用。这样避免计划与Adoption之间循环摘要；新执行的原有binding/plan摘要仍覆盖最终包含资格引用的完整步骤。

`cn_current`沿Request→Target→Receipt→Adoption→恢复R5→原准备与当前PQ资格查询，同时核当前run/generation和本地DENY。原`rs_plan_preparation`与`flow_submission_target`仍保留arm及精确recovery execution分支，只追加“此步骤有有效cn_step”的分支。未写cn_step、错grant、错Adoption、错设备或普通入口省略资格封装，整笔完整计划或提交被拒绝。

Controller新增`cn_command(command_id,transfer_id,execution_id,step_id,submission_id,request_digest,adoption_digest,grant_ref_body,binding_body)`，与原`ce_command`及受理事务同提交。其原prep_key/receipt_id保持不变，因此`ce_run_command`仍投影原origin/run/generation，整运行保护能够找到这些新命令。独立grant与Adoption另有明确引用，不把原recovery grant改成通用授权。

受理writer通过可信Seamer连接读取实际submission、cn_step、execution、Adoption和R5原件，并重核Controller当前准备、控制/授权、时间、设备和计划。SQL最后ca_commit要求完整cn_command关联，另核请求设备与ce_command设备一致。新attempt及最终transmission seal增加cr_current检查；任何原唯一出口、编码、IPC、资源、预算或完成证据守卫继续存在，本轮不开放尚未完成的发送路径。

## 撤回与保护预算

Controller的cr_revocation先让cr_current/cn_live_command失效：即使Seamer尚未收到消息，新受理和新attempt已被拒绝。历史受理及回执保持可查，已经在途的命令继续由原屏障和证据规则结算。

Seamer新增`cn_withdrawal(transfer_id,registration_id,proof_body)`，保存来自对应Controller已持久化撤回原件的证据；同一事务调用已有PQ完整失效计划，再通过`instance_budget_model.apply`完成实际差集计量、受损代预算扣账和最后seal。省略撤回原件、保护成员、预算或seal均不能产生半份保护。没有调用会漏预算的旧独立withdraw入口。

测试中的第2代PQ计划捕获该run不晚于第2代的准备、执行和新普通提交，并建立两个Controller目标。其保护成本由第2代恢复账户承担；原第1代arm账户保持原账，不重复扣款、不退款。计量正文包含新增cn_withdrawal实际行；该过程不是来源故障，不消耗新的来源实例份额。重复同一撤回查原且不重复扣账。

暂停但仍占有活动execution槽时，新事件按既有仲裁记录为suppressed_busy，不新增执行；未占槽的暂停运行沿用suppressed_inactive。撤回不清活动槽、不把未决动作改成成功、不自动重放历史事件。

## 已运行的验证

- 完整新trigger事务及Controller受理事务：每个写项省略、每个写后异常均比较全库回滚快照。
- 两次连续普通触发完成，Controller每次都有独立命令原件，继续运行grant不重复签发；旧恢复准备和新命令的run保护归属保持。
- 已批准参数变动、缺新grant关联、旧grant复用、错Adoption/设备/执行等拒绝。
- 撤回发生在新命令受理前及既有受理之后：受理/attempt拒绝；Seamer完整PQ保护、所有写后异常、所有业务写项省略以及漏预算seal验证。
- 撤回计划包含新提交和两Controller；实际计量包含新原件，受损代账户精确扣一份，旧账不变；重复撤回和事件查原零写。

上一轮检查夹具仅增加可选的布局工厂参数，默认布局与行为保持，原140项检查实际回归并更新输入摘要；本轮不改上一轮参考writer或关系模型。

## 剩余冻结与运行验收

本候选成功用例是固定顺序规则、两个Controller、每次两动作；通用分支/并行计划、state_machine、全部模块能力及NodeCG兼容交付不能由此推导。受理基础字段和完成证据仍由现有合成夹具提供，授权/时间/审批/资源提供者、网络接口与身份隔离未实现。

新增引用随已有计划/命令槽增长约束准入，撤回写入纳入现有保护差集计量；完整普通存储CostManifest、Controller历史容量、引用感知GC、物理持久化及真实容量实测仍未齐。cr_revocation的可信事件输送、接管全过程和最终唯一出口必须在服务实现时联合验收；串行内存连接不能证明跨进程竞态、WAL恢复或实际硬件效果。

下一步应把这条已串联的参考链归并到统一Schema/API及最终SDK来源，审阅上述剩余提供者和运行验收门槛，避免把内部候选当作公开版本。阶段0及整个项目继续保持未完成；业务实现仍遵守先完成系统方案设计的要求。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_continuation_trigger.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_trigger.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_continuation_trigger.py --check-report
```
