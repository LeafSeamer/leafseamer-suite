# 不可变占用归属持久化候选

状态：设计候选，未批准部署。本文将[Ownership](FINAL_ADMISSION.md)接入[178表开放布局](OPEN_STORAGE.md)，形成182表组合；继续使用原资源、RequestKey和控制历史，不建立第二套资源仲裁。旧文件保持原版，生成源为[ownership-storage.sql](ownership-storage.sql)和[组合器](build_ownership_storage.py)，生成物为[controller-ownership.sql](controller-ownership.sql)。

## 已知事实及本轮边界

旧178表允许`go_hold.owner_ref`为任意非空文本，旧占用可以在新快照中被标成新authority的active。该缺口此前已由[旧检查器](check_hold_ownership.py)复现。新组合把Owner引用改为三元外键，并在快照封存时逐项核对原始hold及authority；在普通资源候选中还要求该归属的主体与当前控制事实匹配。

基于上述事实，本轮完成归属来源的物理联接，优先消除“改标签即取得当前权限”的通路。限定取消的ScopeCommit、Assessment和最终AdmissionSeal仍需接入同一个`go_gate`；本轮不创建另一物理闸，也不解除四个最终签发阻断。归属原件属于历史事实，当前主体资格只是其中一个子条件。

## 字段映射与单一来源

| 表或视图 | 字段及实际关系 | 提供者仍须证明的内容 |
| --- | --- | --- |
| ow_source | source_id/revision/digest对应source_receipt_ref；scope_id引用唯一controller_scope；hold_id/digest、command_id/device_id、kind、attempt_id或cancellation_id/execution_id；两种RequestKey互斥、namespace_id/request_digest、origin与完整Principal；authority_state_id/control_epoch/effective_version、clock_domain/descriptor、sampled/acquired/expires_tick、provider_ref/receipt_body | 回执及完整Ownership业务字段的JCS、签发者资格、实际采样和期限；取消origin从自己的授权原件提取，不根据父命令origin猜测 |
| ow_ownership | ownership_id/revision=1/digest、hold_id、source_id、完整ownership_body；hold与source均唯一 | 完整Schema与JCS；wire中的command/attempt/cancellation/execution/source Ref的修订与摘要逐项对应真实原件。现有旧表未暴露的这些摘要仍在BODY中，不伪称已有物理外键 |
| ow_commit | ownership_id、hold_id、committed_tick、审计、唯一outbox及正文；必须配对实际cr_hold_commit | 提交tick来自受监督单调时钟；outbox为归属事件通知，不能冒充设备关闭ACK |
| ow_revocation | 精确source_id、撤回提供者、原因、审计及通知；每source一次且不可变 | 撤回者资格及撤回原件；真实关闭目标仍由统一保护层完成 |
| ow_request_source | ordinary从ce_attempt→ca_command_initial→ca_request_key→ca_namespace取身份；cancel从cv_cancel→cv_cancel_key及cg_plan取身份 | namespace保存的主体归属必须由可信身份提供者建立，数据库本身不认证用户 |
| ow_current_source / ow_current_owner | 当前go_authority、ct_current_state、同epoch/version、无pending、同域/descriptor；manual精确匹配完整holder，automation要求automatic且无holder；排除已撤回来源 | 不检查实时now、完整RunGrant、预算、GateAccess或Guard，不是最终发送视图 |
| go_hold | owner_ref改为ownership_id，并增加owner_revision/owner_digest复合FK；hold_id及authority_state_id必须匹配封存原件 | 异常分类、完整提供者原件与内容一致性仍需外验，不能从合法Ref推断资源无风险 |

线上U20保持无补零十进制字符串；库内采用原布局的20位补零文本。所有新表为STRICT，原件禁止UPDATE/DELETE，归属与回执修订固定1。重新取得同名控制权也不能覆盖或复活旧Ownership；真实控制授权记录改变后，`ow_current_owner`不再返回旧行。gate的ready/protected展示修订不改变`go_authority`。

`source_receipt_ref`与`identity.source_ref`不是同一对象。前者索引ow_source，后者连同完整ExecutionIdentity保存在回执和Ownership正文，由提供者重建其真实RequestKey/执行原件投影后核验。SQL显式核验上述已有实体关系，不声称能对非空BODY完成Schema、JCS或签名校验。后续最终准入必须保留这些完整原件校验，不能以本轮视图替代。

来源回执的期限限制**本次归属封存**：sampled≤acquired≤committed<expires，且committed不得早于当前控制状态的单调时刻。封存后的归属历史不会因为这份采样回执过期而消失；之后的每次发送必须另取当前授权和Guard。本轮当前主体视图故意不表示实时发送期限合格。

## 原子写集与故障顺序

取消Plan与独立占用采用一个BEGIN IMMEDIATE写集：写来源回执，写原cg_plan及全部资源/primitive/依赖、验证清单和独立cr_hold，完成原cg_plan_commit及cr_hold_commit，写Ownership及ow_commit，最后提交。source不引用未来Ownership的摘要，避免摘要环；SQL使用反向延迟外键阻止source、hold、Ownership或commit的半边提交。

`ow_commit`最后核对真实请求来源、hold/Plan归属、当前控制和时钟域、来源撤回及期限。缺少任何必要写入或者发生主动异常时，所有182表一起回滚。SQLite提交不与设备副作用原子绑定；提交结果不确定时只查原，不新建同hold的Owner，不重发设备命令。

普通首次派发仍按[最终准入写集](FINAL_ADMISSION.md)执行：前态资源资格→新hold及Ownership→许可/预算/命令提交→完整后态快照→AdmissionSeal。本组合已强制普通hold也必须有归属封存，绝不允许缺归属回填当前holder。由于最终AdmissionSeal尚未完成，普通新签发仍被原四个触发器阻断；本轮只实际验证普通RequestKey/attempt来源投影的未提交写集并回滚，不声称已跑通完整普通派发。

接管按现有T3/T4写集推进。T3进入pending后，旧Owner的当前主体资格立即消失；T4只改变控制权，不改变旧Owner、旧命令终态或风险hold。快照可以诚实记录旧authority及异常状态，但不得把该hold重标成新authority。新的保护操作必须使用自己的合法请求、Plan及独立hold，不能借父Actor。

来源撤回与`go_hazard`精确后继同事务写入，非法来源不能凭空推进代次。原Owner和风险hold保留，当前主体资格和旧开放快照失效；撤回通知不等于worker已经关闸，也不自动释放资源。旧cu/ro/go关闭目标的统一以及AdmissionSeal最后复核仍是后续同版联接任务。

旧资源分类与新风险Schema采用显式映射：active→active、unknown→unknown、failed_unresolved→unresolved、orphaned/proof_revoked→stale。`ow_risk_projection`仅执行词表映射，不证明分类原因、来源新鲜度或批准的父风险政策。范围评估必须从完整实际风险集合和独立提供者取证；256上限不得截断集合。

## 验收用例与交付证据

| 场景 | 预期及检查边界 |
| --- | --- |
| 父命令由其他主体受理，当前人员或自动化Requester创建取消Plan | 各取取消RequestKey，封存独立Owner；父未发时不伪造普通attempt |
| 缺来源、Plan成员、hold、Owner或commit；各写入后主动异常 | 不允许半边提交，182表快照全部回滚 |
| 错issuer/epoch/principal、namespace、请求摘要、执行或父命令 | 实体FK或归属封存拒绝；重写文本标签不授当前权 |
| pending接管、T4生效、旧hold重标新authority | 当前主体资格消失，旧历史及风险保持；伪快照拒绝 |
| 来源期限前一刻与到期等号、倒退tick或换域 | 前一刻可封存；等号、倒退或错域拒绝 |
| 撤回发生、重复撤回、伪造撤回代次 | 同事务推进一次安全代次并保留占用；重复/伪造拒绝，不执行设备关闭 |
| 所有四表的更新和删除 | 对确有数据的表验证不可变，失败后全库不变 |
| 普通来源投影、取消实际签发 | 前者仅在未提交写集中核对实际来源后回滚；后者即便Owner存在仍命中最终禁发门槛 |
| 合成BODY及提供者标识通过 | 这是来源真实性限制反证，不证明鉴权、JCS或真实授权 |

[检查器](check_ownership_storage.py)只连接`:memory:`，启用外键及递归触发器。报告记录实际用例、SQLite版本及完整声明输入摘要；`--check-report --staged`只核暂存字节，不重跑。串行故障切点、主动异常与真实多连接并发、进程崩溃、磁盘耐久、IPC和设备验收分别记账，后五者本轮未执行。

复验：`python docs/contracts/c08-controller/build_ownership_storage.py --check`；`python docs/contracts/c08-controller/check_ownership_storage.py --report`。剩余冻结事项是ScopeCommit/ReadyCommit分型、完整Assessment与AdmissionSeal、统一关闭和全消息序号、上述完整原件提供者输入输出与SDK归并。阶段0仍未关闭。
