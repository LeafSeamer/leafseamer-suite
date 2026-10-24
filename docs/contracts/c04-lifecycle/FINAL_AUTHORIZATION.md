# 最终授权使用与本地撤销切点

状态：内部候选，未批准生产使用。入口为[Schema生成器](build_final_authorization.py)、[具名Schema](final-authorization.schema.json)、[局部存储](final-authorization.sql)、[判定器](final_authorization_model.py)和[检查器](check_final_authorization.py)。

## 已知事实

当前最终授权投影只含有效时间窗，其本身不能证明来源当前有效。F04已规定修订下界采用严格小于比较；credential按精确ID永久禁用，trust覆盖issuer/epoch信任域；历史active不能覆盖本地拒绝记录。DF04要求T2在同一writer事务核对当前授权，持久化BODY与查询列保持一致。（来源：[最终准入](FINAL_ADMISSION_SEAL.md)、[F04授权与撤销](../../rebirth-f04-f05-design.md)、[DF04表契约](../../rebirth-df04-storage-design.md)。）

## 本轮方案

`AuthorizationUse`完整保存既有AuthorizationSnapshot与AuthorizationBinding，并绑定完整ExecutionIdentity、出口/运行域、challenge发送tick、响应接收tick、本地新鲜度上限、授权生效/截止tick，以及权威、对象范围和有效期取证Ref。使用`use_digest`覆盖全部正文，存为严格JCS字节。引用全部采用精确ID、revision和digest。授权有效期的UTC判定仍由认证时钟取证负责，此记录不能自证那些Ref的真实性。

`authorization_use`是Controller内部的不可变使用证据；`authorization_floor_event`是同一库内已接收撤销的不可变事件；`authorization_challenge`与`authorization_response`保存首次查询和唯一响应；`authorization_context`与`authorization_command_scope`保存初次受理所依赖的凭据归属及动作范围；`authorization_clock_record`与`authorization_validity`保存认证时钟日志和有效期原件。八表附加在242表候选后用于实验，不新增签发方或独立授权数据库，不作为生产迁移发布。新鲜度截止取`challenge_sent + min(snapshot.fresh_for_ms, local_limit_ms)`，再与上游授权截止取最小值，禁止从响应接收时刻刷新TTL。所有tick保持十进制字符串。

`AuthorizationChallenge`固定完整出口/运行域、requester、credential、audience、scope_digest、device.command用途和首次发送tick；challenge_id为64位小写hex，未来发送端必须用256位CSPRNG，不能从用户输入或业务ID派生。本地先持久登记再发送。同ID同正文重试只读原记录，同ID重填时间拒绝。测试使用确定的合成nonce，不证明随机数生成器运行。

`AuthorityResponse`固定完整challenge_ref、原AuthorizationSnapshot、接收tick和channel_evidence_ref；每challenge至多一条响应。接收端逐项核对issuer/epoch/principal、credential、audience、scope_digest、challenge与时间顺序，首次响应可靠保存后不得覆盖；响应重传也不能刷新年龄。最终使用再按authority_evidence_ref解析实际响应，核对完整snapshot和原发送/接收时间。因此凭据轮换或复制快照不能直接重用旧响应。channel_evidence_ref仍待接入真实认证通道，数据库中存在这些记录不证明TLS或签发者真实。

判定器先取得同库writer锁，再查实际授权使用正文、主体/用途/audience、快照共同字段和device.command权限；要求响应接收及最终封存均处在授权有效窗内，且接收不晚于选取。普通人工必须human/manual并有session，自动化必须service/automation并有grant和arm。取消和面板委托尚未接通，明确拒绝此入口，不能去掉委托字段复用旧证据。

自动化还须从实际ca_request_key/ca_command_initial、cn_live_command、cr_current、cr_device及typed_command_source读取原件。重新验证转交请求与回执摘要、完整grant正文与Ref、Seamer执行/采用、目标Controller及设备全集，并逐项对齐AuthorizationBinding中的grant_id、grant_revision、arm_generation与原命令run_binding。不能用另一个格式合法的grant或代次替换；原grant撤销、准备关闭或控制变化后，当前视图失效即拒绝。`ContinuationAuthorization`是这些本地原件的具名投影，其action_id和capability_version来自原命令，不表示action_set_ref的授权内容已经验证。该关联复用[继续运行绑定](continuation_binding_model.py)，不另造grant。

`RequestContextBinding`是内部持久归属，不改变公开RequestContext：绑定实际namespace、context_id/request_epoch、完整requester、credential/session、允许操作、original_scope_ref及issuance_evidence_ref。创建时核对ca_namespace的主体和请求世代，原scope须属于同主体/凭据/服务。上下文必须在首个对应ca_request_key前登记；SQL在新提交受理时再次检查context、namespace、操作及原动作范围。已有命令不能事后补造缺失归属，已有context不能换凭据或覆盖原scope；旧实验库须重建合成fixture，不能修改历史行修复。发行时间、期限和容量仍依赖完整context签发/消费契约，本记录不假装已完成这些服务。

`CommandScope`采用内部精确动作profile：完整服务scope、requester、credential_id、已排序permissions及已排序的`(device_id,action_id,capability_version)`目标组合。`scope_digest=SHA-256(JCS(完整CommandScope))`，存储ID为该摘要派生值；响应snapshot必须绑定已存的同一规范正文。目标集合允许为空以表达无可用动作，重复组合拒绝。不提供通配符、组合展开或从不认识的scope_digest推断权限；含参数级限制的上游策略不能丢弃限制后降级成此profile，须另行交付可验证的约束模型。它不改变内部时钟、事件或面板的其他scope模型。

最终自动化使用由实际请求transport取得context_id，再同时核对原context和当前snapshot。credential/session必须与原context相同，即使轮换后拿到新challenge和新响应也不能继承旧context。原scope与当前scope均须允许同一完整目标组合和device.command，当前permissions须与snapshot完全一致；“设备A的动作X”和“设备B的动作Y”不能组合成“设备A的动作Y”。新的更宽scope不改写旧context，变窄scope立即阻止不再允许的目标。`CommandScopeProof`绑定context_ref、原/当前scope_ref、响应Ref、实际命令/请求Ref和目标；scope_evidence_ref必须等于按这些原件重建的引用。真实签发权限、参数资格与action_set_ref交集仍需后续来源核验。

撤销依赖从已核对的绑定字段推导，不接受调用者提供可任意删减的依赖列表。principal/session/grant/extension比较实际绑定revision与所有已见下界；相等只表示未被该下界拒绝，仍需其余资格。credential无条件拒绝匹配ID；trust按issuer/epoch查询，不能换target_id规避。乱序较低事件可以保存审计，但不能降低实际拒绝下界。同event_id同正文幂等，不同正文拒绝。事件不可修改或删除。

最终授权source_ref是明确命名的`authorization-cut/1`内部派生描述的摘要，覆盖use_ref、scope、事务、选取/封存tick、实际authority_response_ref、continuation_ref与scope_proof_ref（manual局部检查均为null）及实际匹配的撤销事件Ref；不是原AuthorizationSnapshot的摘要。`planned`在同一事务重新读取该切点并核对授权投影，再调用[编码原件封存检查](FINAL_ENCODING_SOURCE.md)。较高下界直接拒绝；相等下界仍改变切点，旧投影必须重选。不得把这个附属写集独立提交视为完整T2成功。

查询每种依赖最多读取4097条，超过4096则保护拒绝，不截断成成功；后续生产须实现单调压缩与保留证明，不能无界扫描或删除仍被引用的拒绝依据。UPDATE零行用于在实际读取前取得writer锁；陈旧DEFERRED快照升级失败属于事务失败，调用者必须整事务回滚。

## 故障时序与验收

认证时窗的局部推导由[整数时窗模型](authorization_validity_model.py)承担，新增故障用例见[时窗检查](check_authorization_validity.py)。以下为候选方案及已完成的离线验证，不表示真实认证时钟已交付：

- `AuthenticationClockSample`固定`trusted-system-interval/1`、完整运行/出口绑定、单调锚点、UTC纳秒上下界、漂移预算、采样截止、质量、策略Ref和采集Ref。严格拒绝业务`reference-bound/1`及业务offset字段。UTC使用规范毫秒字符串转整数纳秒，tick及UTC范围限制为无符号64位，计算不经过浮点。漂移预算的Schema上限为1000000 ppb，属于候选可表达范围，不能当作生产可信预算。
- `store_clock`在同库writer事务按完整Binding追加日志，序号及parent_ref由原件推导。同ID只能重读相同采样，不能刷新锚点或截止。迟于旧采样截止、tick回退/重复、失信、倒置区间、策略/漂移预算改变或新旧预测区间不相交，均写入保护锁存；相同运行绑定后续恢复正常采样仍受保护。没有自动恢复或同域清锁入口。生产显式恢复必须另行验证受监督新运行绑定与重新认证，不能仅改ID绕过。
- 对有效采样，令锚点为`m`、有效UTC界为`L/U`、漂移预算为`r`、`N=10^9`，则`t>=m`时区间为`[L+floor((t-m)(N-r)/N), U+ceil((t-m)(N+r)/N)]`。后续重叠采样的有效下界取新下界与旧预测下界的较大值，上界也取较大值，保留先前保守预测，禁止借误差收窄使已过期资格复活。该候选刻意不优化长期误差累计；最终仍受最早采样截止限制。
- `AuthorizationValidity`精确绑定原响应Ref、ExecutionIdentity、AuthorizationBinding、运行域及原clock_ref。components必须按credential、session、grant顺序完整列出当前绑定实际需要的对象，缺失、重复、错对象均拒绝；每项带具名来源Ref及UTC有效期。与snapshot取`nbf=max(all not_before)`、`exp=min(all expires_at)`。component来源的签名、凭据真实性及grant批准仍未解析，不以登记行替代真实验证。
- 最终读取同时验证原采样在响应接收和封存时的UTC区间，以及当前最新采样在封存时的区间：下界须不小于nbf，上界须严格小于exp。原采样映射下界为`m+max(0,ceil((nbf-L)N/(N-r)))`；严格上界为`m+floor((exp-1-U)N/(N+r))+1`。最后与原/当前采样截止、首次challenge的新鲜度截止及原使用记录的更短截止取交集。自报截止只能收窄，不能替代这些来源；任何负值、空区间、溢出或到期等号均拒绝。
- `AuthorizationTimeCut`保存validity_ref、原/当前clock_ref和最终窗口，进入授权切点摘要。新合法采样也会使旧最终投影失配，需要在当前事务重新选取；不能事后覆写已封存证据。当前采样不得晚于选取tick；选取之后出现新采样须以新切点重新选取，不能把未来原件填入旧选择。写闸、Guard和其他最终门控仍须共同取交集，不允许只提交授权附属写集。

1. 撤销先提交：后续最终规划读取已见下界，拒绝旧授权；原packet、历史授权和在途事实保留。
2. 封存事务先取writer锁：另一个撤销writer不能插入该事务中途；释放锁后撤销可提交，下一次规划必须重读。该顺序不代替提交后的AUTH_FENCE、入流前复核和worker守卫。
3. 响应迟到、到期等号、主体/epoch/audience错配、权限撤回、正文重复键或摘要不符：拒绝，不延长缓存、不重签或重发设备动作。
4. 同操作重复/乱序：同事件不重复插入；较低下界不恢复权限；其他主体或issuer/epoch的撤销不误伤当前绑定。
5. 相同主体换凭据、快照换challenge、授权使用重新填写发送/接收tick：必须与已存原响应一致，否则拒绝。换凭据后即使有新响应，自动化路径仍拒绝继承原context；新凭据用于新请求需另建context。
6. grant格式正确但ID、修订或arm_generation与已受理命令不符：拒绝，不能只根据本地不存在匹配撤销就认定有效。
7. context未登记、操作不在交集、目标超出原scope：在新命令受理前由同库约束拒绝；最终规划还须检查当前scope收窄、组合拆分及能力版本变化，保留原请求与在途事实。

检查覆盖实际250表候选普通自动化编码来源和19条最终附属写集规划，并使用临时文件SQLite双连接验证writer顺序；fixture在首次decide前登记合成scope/context，验证新受理约束实际运行。时窗检查逐tick枚举核对整数舍入，覆盖大于2^53的相邻UTC纳秒、缺失/错误期限依赖、前跳/回拨锁存及正常采样不能解锁、NTP profile混用拒绝、当前切点重选和追加事务回滚。manual会话场景只验证局部授权存储，context/动作scope和完整manual编码闭环尚未接通。Schema、来源正文与转交原件均严格检查规范JSON和摘要；SQL不代替这些检查。四个最终签发阻断保留，ci_issue和fa_seal均为零。原有引用模型不因新增候选自动获得发送资格。

## 剩余冻结与接通事项

authority_evidence_ref已解析到持久响应与challenge，自动化scope_evidence_ref已解析到实际原/当前scope及context；validity_evidence_ref已解析到本地期限和认证时钟日志。上游channel_evidence_ref、context的issuance_evidence_ref、期限component的source_ref以及时钟policy_ref/acquisition_ref仍未解析。真实凭据/配对、context签发认证与容量/期限、上游scope与action_set/参数规则的真实性、系统时间采集/回拨检测及grant/arm批准真实性仍未由此候选证明；认证传输和采集来源保留为合成测试输入。格式非法或采集异常尚不能由运行时自动转化成保护事件；未来采集器必须保证该失败路径，不能仅丢弃坏样本后沿用旧可信状态。当前保守日志不提供长期误差收敛、清锁或压缩删除策略。

报告分别列出本地stored绑定、整数推导、保护锁存验证为true和完整真实性验证为false，不能互相替代。事件入口的管理权限、固定撤销目标集与逐出口ACK也未实现，本地下界存在不代表全服务撤销applied。下一步须把这些来源绑定到现有身份与认证时间权威，并与完整控制、资源、Guard、预算及deny来源一起组成完整T2，随后验证入流前复核和AUTH_FENCE。阶段0仍未关闭，业务实现仍未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_final_authorization.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_authorization.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_authorization.py --check-report
```
