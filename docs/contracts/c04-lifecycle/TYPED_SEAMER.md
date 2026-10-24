# Seamer完整执行与请求写集候选

状态：`approved=false`。本轮将上一轮[39字段映射](COMMAND_CONTRACT.md)中的继续运行PLAN和SUBMISSION接入实际内存SQLite组合库，保留业务服务实现边界。交付[布局生成器](build_typed_seamer.py)、[组合DDL](seamer-typed.sql)、[新增约束](typed-seamer.sql)、[参考writer](typed_seamer_model.py)、[故障检查](check_typed_seamer.py)及[报告](typed-seamer-report.json)。旧候选不修改，不执行旧库迁移。

## 已知事实与设计处理

原计划步骤只引用固定动作输入和转交选择，完整CommandRequest在SUBMISSION时才能生成。若把含execution_binding_ref的完整请求提前放入ExecutionBinding所摘要的计划，会形成计划与执行绑定的摘要环。因此执行计划仍保存内部动作模板，完整请求在执行绑定已封存后生成；模板中的内部continuation只参与本地计划和cn_step关联，不出现在公开请求顶层。（来源：[旧计划writer](continuation_trigger_model.py)、[类型化writer](typed_seamer_model.py)。）

固定模板显式含完整parameters、capability_version、expected_control、required_completion、preconditions、dispatch和evidence_timeout_ms，不再由写入时把未知value包装成参数或补默认策略。测试编译器直接产生合成完整模板并参与原转交审批摘要，不能把测试模板视作真实编译器实现。

## PLAN原子写集

完整组合库新增typed_execution_source表，共120表。execution新增可空typed_source_id并具有延迟外键；存在当前代转交的普通trigger必须指向自身原件行，另有计划封存检查明确拒绝缺失原件。原件行保存输入快照Ref、编译产物Ref、定义版本、完整参数快照及Ref和计划时的监督时钟域。它与execution、原ingress决定/快照、步骤计划、审计通知、来源水位及既有预算写入在原事务中提交，不能事后补录。新增行和更大正文的完整CostManifest仍须核定，不把原预算约束通过当成新增成本已经覆盖。

ExecutionBinding使用真实ingress_decision身份与摘要、真实ingress_snapshot身份与摘要、固定原件及完整新grant/目标清单。plan_digest对实际执行计划计算；批准计划Ref独立保留在选择中。完整正文JCS写execution.binding_body，binding_digest只排自身。原状态机source/target列继续与正文对账。

原件在提交后不可更新/删除，typed_source_id不可改。当前SQL补充关系及必填约束；完整Schema、JCS和提供者检查仍由可信writer负责，数据库JSON函数不承担全Schema校验。参考ctx中的program_current/clock_current及artifact_ref仍是明确合成提供者，未验证真实编译器或原生时钟。

## SUBMISSION及查原

command_submission增加issuer_epoch和完整request_key_body，唯一键采用target两列加issuer、issuer_epoch、principal、request_epoch、operation、idempotency。原七列唯一约束移除，相关正文与新列不可变。全新键按cmd_加JCS({execution_id,step_id})的SHA-256十六进制生成，并在首次事务中固定。

writer从持久执行、固定模板、cn_step与转交原件重建完整CommandRequest，核对所有字段与原件。定义版本取PLAN持久原件，不读提交时可变ctx中的版本；参数核对固定参数快照，时钟域变化时拒绝新提交。request_body保存完整请求；request_digest只摘要CommandContent，运输字段排除规则沿用上一轮。SQL约束核对身份列、执行Ref、选择和grant，拒绝旧简化正文或旧顶层continuation。

同一execution/step的提交重进只查已持久结果，不重新写请求、分配键或发送。当前读取授权与精确历史命名空间归属仍须成立；命名空间已不能创建新请求时，有权同主体仍可查原。首次新提交必须namespace_current，通过后仍沿原ready、submission_pending、attempt_recorded状态机。首次提交失败整笔回滚，响应不确定不得换键重建。

## 验证与未完成范围

本机Python SQLite 3.50.4的隔离诊断观察到：仅在内存测试中移除新增计划封存触发器后，省略typed_execution_source仍可COMMIT，随后foreign_key_check报告execution对该表的外键违例，且foreign_keys=1。**根因尚未确定**，不能直接归因于引擎缺陷或推断正式Node制品也存在同样行为。[检查器](check_typed_seamer.py)保留可复现诊断，报告环境与实际结果；该探针仅改变独立内存库，不修改交付DDL。

参考writer在事务前要求foreign_keys=1，在提交前独立执行foreign_key_check，失败则整笔回滚；计划封存还要求原件实际存在。两条防线分别有漏写反例。全库检查在这里是离线参考措施，生产成本、精确根因、所选原生SQLite制品和替代约束方案仍须单独验证，production_clearance=false，不因76项检查通过解除这一部署门槛。

检查执行实际120表布局、完整输入原件与请求的SQLite持久化、两Controller目标各自提交、全部PLAN/SUBMISSION写后故障回滚、缺原件/缺提交写集、错epoch/旧正文、原件不可变、历史查询归属及外键。旧六类字段差异对新继续运行提交均应为空；这只证明本侧该路径已经落库。

Controller完整CommandContent受理、拒收/查原、记录投影及新版路径守卫尚未接入；不调用旧Controller夹具冒充新请求受理。普通arm和恢复动作的类型化写入仍须扩展，当前新增提交约束会拒绝未升级的旧写入器，不能宣布全系统布局可部署。最终AdmissionSeal、身份/时钟真实提供者、全系统SDK、物理磁盘崩溃与并发、真实HTTP/IPC及设备均未验证，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_typed_seamer.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_seamer.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_seamer.py --check-report
```
