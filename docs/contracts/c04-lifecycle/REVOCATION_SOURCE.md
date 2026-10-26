# 授权撤销切点的持久来源

本候选是基于现有账本的设计与离线验证，approved=false。它落实[OPEN授权取证设计](OPEN_AUTHORIZATION.md)中的拒绝来源，尚不提供当前设备授权状态或开闸许可。

## 事实与适配范围

[既有授权模型](final_authorization_model.py)从 AuthorizationBinding 推导 principal、credential、trust 及非空 session／grant／extension，查询全部匹配 FloorEvent。低于 revision_floor 才拒绝；credential 与整个 issuer_id／issuer_epoch 的 trust 永久拒绝。事件不能更新或删除，但原表没有可重建历史全集的入账顺序。（来源：[现有DDL](final-authorization.sql)。）

本轮首个来源适配器只读取既有 AuthorizationUse 完整原件和挑战／响应，不接受调用方删减的依赖数组。它核物理摘要、引用、scope、身份、audience、快照共有字段及成对依赖；grant／arm、扩展来源真实性和有效期仍由原最终授权链核验。存储使用原件不等于认证成功，不将 command 的 AuthorizationUse 改称为 OPEN 凭证。未来评估器、持有人和独立取消来源须各自注册类型明确的适配器，不能直接复用本入口作为整台设备的授权。

## 顺序与确定性快照

[局部DDL](revocation-source.sql)新增两表。authorization_revocation_order 由现有 FloorEvent 的 AFTER INSERT 触发器同事务写入，event_id 唯一且不可变。sequence 是SQLite本地有符号整数入账位置，最大为 2^63-1；耗尽时写入失败、事务回滚，不能回绕。它不是权威发行者修订，也不表示网络接收或真实发生时间，迟到的低下界仍保留。

安装在 BEGIN IMMEDIATE 内检查原账本为空，逐条执行完整DDL，不使用会切换事务边界的脚本执行接口。现有非空账本拒绝安装，不能靠排序旧事件伪造历史；生产升级方案另行冻结。即便尚未捕获任何快照，新撤销也必须先完成事件和顺序的同库写集。匹配事件缺顺序时读取拒绝，不以JOIN过滤丢弃。

[Schema](revocation-source.schema.json)由[唯一局部定义](build_revocation_source.py)生成。Snapshot包含完整 source_use_ref、Binding、AuthorizationBinding、派生依赖、observed_through、逐成员sequence／event_ref／denial、observed_floor_result和自身摘要。依赖按kind排序，成员按入账整数排序。observed_through是最后一个相关成员的位置，空集合为0；无关主体或发行代次的新事件不改变该来源。trust忽略target_id，匹配整个发行代次。

snapshot_id由不含自身ID与摘要的规范正文确定，snapshot_digest覆盖加入ID后的正文，仅排除自身顶层摘要。每依赖最多4096条，查询4097探测溢出；最多六依赖，不截断历史而声称全集。credential／trust即便revision_floor为0仍拒绝。相等或较低下界不产生拒绝，但新增相关事件仍改变切点身份。

authorization_revocation_snapshot仅封存完整快照及use_id、最后相关顺序、摘要的物理关联。单条INSERT和读回处于同一writer事务；它不提交控制状态或签发权限，故不另造Ready、审计成功或OPEN outbox。后续设备授权采用必须另行与自身审计／保护写集绑定。旧快照不覆盖，内容相同仅查原。

## 历史、当前与资格

[读取器](revocation_source_model.py)按固定切点重读实际事件全集并重建完整快照，核每条事件规范正文、摘要、scope与物理列；不同顺序、少成员、错原件或重算摘要均不能替换存储历史。历史读取不验证当前未撤销，也不把后来到达的事件追加进旧对象。

current先取同库writer资格，再核历史原件与当前全部相关事件重建结果完全相等。WAL旧读可能看见先前快照，不能直接作为最终资格；旧读升级writer失败必须结束事务，重新取writer后旧切点应被拒绝。所有当前判定仅对所持事务成立，离开事务后须重新取证。

observed_floor_result只有denied或no_matching_denial。前者证明本库已记录拒绝；后者只表示这些已存事件没有命中拒绝，既不证明响应仍active／未过期，也不证明发行者可信、设备范围、grant／arm、扩展批准、取消代行、控制持有或OPEN资格。current可以返回已拒绝快照，供保护与审计查原，调用者不得把“查到current”当作允许执行。

## 故障与验收

| 故障／交错 | 预期 |
| --- | --- |
| 撤销事件写后异常 | 事件及入账顺序一并回滚，不能只留一侧 |
| 相同事件重投 | 查同一原件，不增加入账位置；异内容同ID仍由原账本拒绝 |
| 快照写后异常、漏写或COMMIT前异常 | 全库回滚，原历史仍可读 |
| COMMIT后观察丢失 | 新快照可查原，重复捕获不新建身份 |
| 迟到低下界／新相等下界 | 完整保留；已有较高拒绝不降低，旧切点须重选 |
| 无关主体、发行者或代次事件 | 不改变相关切点，不凭全局数量误判当前来源变化 |
| 4097条匹配事件 | 当前读取拒绝容量溢出，既有4096条历史切点仍可查 |
| 撤销先提交、旧读升级或新writer重读 | 旧读升级拒绝，新writer拒绝旧切点；不允许沿用内存结果 |

[检查器](check_revocation_source.py)在既有253表授权夹具上组合为255张业务表，全库比较另含SQLite自动创建的sqlite_sequence。覆盖真实4096／4097边界、手动人员与扩展依赖、已有自动化grant、永久拒绝、全表回滚、相同事件重投及本机WAL双连接。另在首次INSERT时注入六类错误快照正文并重算ID／摘要，历史读取仍拒绝；顺序插入故障不会留下孤立撤销事件。人员／扩展测试的使用原件在首次写入前构造，仍为合成证据；不冒充真实身份签发。[报告](revocation-source-report.json)绑定完整输入。

本轮没有把两表并入306表OPEN恢复链，也没有完成原撤销接收器的真实性、全部受影响设备保护传播、真实进程终止、磁盘断电或最终发送。下一步须以完整设备授权来源组合这些拒绝切点，首次绑定恢复快照，再完成OPEN／ACK／Ready与撤销的原子采用。业务及批准协议保持原样。
