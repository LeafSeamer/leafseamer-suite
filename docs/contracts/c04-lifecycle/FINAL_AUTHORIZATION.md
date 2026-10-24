# 最终授权使用与本地撤销切点

状态：内部候选，未批准生产使用。入口为[Schema生成器](build_final_authorization.py)、[具名Schema](final-authorization.schema.json)、[局部存储](final-authorization.sql)、[判定器](final_authorization_model.py)和[检查器](check_final_authorization.py)。

## 已知事实

当前最终授权投影只含有效时间窗，其本身不能证明来源当前有效。F04已规定修订下界采用严格小于比较；credential按精确ID永久禁用，trust覆盖issuer/epoch信任域；历史active不能覆盖本地拒绝记录。DF04要求T2在同一writer事务核对当前授权，持久化BODY与查询列保持一致。（来源：[最终准入](FINAL_ADMISSION_SEAL.md)、[F04授权与撤销](../../rebirth-f04-f05-design.md)、[DF04表契约](../../rebirth-df04-storage-design.md)。）

## 本轮方案

`AuthorizationUse`完整保存既有AuthorizationSnapshot与AuthorizationBinding，并绑定完整ExecutionIdentity、出口/运行域、challenge发送tick、响应接收tick、本地新鲜度上限、授权生效/截止tick，以及权威、对象范围和有效期取证Ref。使用`use_digest`覆盖全部正文，存为严格JCS字节。引用全部采用精确ID、revision和digest。授权有效期的UTC判定仍由认证时钟取证负责，此记录不能自证那些Ref的真实性。

`authorization_use`是Controller内部的不可变使用证据；`authorization_floor_event`是同一库内已接收撤销的不可变事件。两者附加在242表候选后用于实验，不新增签发方或独立授权数据库，不作为生产迁移发布。新鲜度截止取`challenge_sent + min(snapshot.fresh_for_ms, local_limit_ms)`，再与上游授权截止取最小值，禁止从响应接收时刻刷新TTL。所有tick保持十进制字符串。

判定器先取得同库writer锁，再查实际授权使用正文、主体/用途/audience、快照共同字段和device.command权限；要求响应接收及最终封存均处在授权有效窗内，且接收不晚于选取。普通人工必须human/manual并有session，自动化必须service/automation并有grant和arm。取消和面板委托尚未接通，明确拒绝此入口，不能去掉委托字段复用旧证据。

撤销依赖从已核对的绑定字段推导，不接受调用者提供可任意删减的依赖列表。principal/session/grant/extension比较实际绑定revision与所有已见下界；相等只表示未被该下界拒绝，仍需其余资格。credential无条件拒绝匹配ID；trust按issuer/epoch查询，不能换target_id规避。乱序较低事件可以保存审计，但不能降低实际拒绝下界。同event_id同正文幂等，不同正文拒绝。事件不可修改或删除。

最终授权source_ref是明确命名的`authorization-cut/1`内部派生描述的摘要，覆盖use_ref、scope、事务、选取/封存tick及实际匹配的撤销事件Ref；不是原AuthorizationSnapshot的摘要。`planned`在同一事务重新读取该切点并核对授权投影，再调用[编码原件封存检查](FINAL_ENCODING_SOURCE.md)。较高下界直接拒绝；相等下界仍改变切点，旧投影必须重选。不得把这个附属写集独立提交视为完整T2成功。

查询每种依赖最多读取4097条，超过4096则保护拒绝，不截断成成功；后续生产须实现单调压缩与保留证明，不能无界扫描或删除仍被引用的拒绝依据。UPDATE零行用于在实际读取前取得writer锁；陈旧DEFERRED快照升级失败属于事务失败，调用者必须整事务回滚。

## 故障时序与验收

1. 撤销先提交：后续最终规划读取已见下界，拒绝旧授权；原packet、历史授权和在途事实保留。
2. 封存事务先取writer锁：另一个撤销writer不能插入该事务中途；释放锁后撤销可提交，下一次规划必须重读。该顺序不代替提交后的AUTH_FENCE、入流前复核和worker守卫。
3. 响应迟到、到期等号、主体/epoch/audience错配、权限撤回、正文重复键或摘要不符：拒绝，不延长缓存、不重签或重发设备动作。
4. 同操作重复/乱序：同事件不重复插入；较低下界不恢复权限；其他主体或issuer/epoch的撤销不误伤当前绑定。

检查覆盖真实244表普通自动化编码来源和19条最终附属写集规划，并使用临时文件SQLite双连接验证writer顺序；manual会话场景只验证局部授权存储，尚未声明完整manual编码闭环。四个最终签发阻断保留，ci_issue和fa_seal均为零。原有引用模型不因新增候选自动获得发送资格。

## 剩余冻结与接通事项

authority/scope/validity取证Ref仍未解析，真实凭据、配对、scope匹配、认证时钟和grant/arm批准尚未由此候选证明；授权来源保留为合成测试输入。事件入口的管理权限、固定撤销目标集与逐出口ACK也未实现，本地下界存在不代表全服务撤销applied。下一步须把这些来源绑定到现有身份与时间权威，并与完整控制、资源、Guard、预算及deny来源一起组成完整T2，随后验证入流前复核和AUTH_FENCE。阶段0仍未关闭，业务实现仍未开始。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_final_authorization.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_authorization.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_authorization.py --check-report
```
