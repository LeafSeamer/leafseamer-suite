# 监督日志完整布局与事务候选

版本`supervisor-journal/0.1.0-draft.1`。本稿把[监督启动候选](README.md)的日志字典落实为[完整15表DDL及恢复视图](journal.sql)，替代“只有三张局部探针表”的资料状态；不是已批准生产迁移，也不是整个LeafSeamer业务数据库。当前继续系统设计，不创建本机运行日志或启动服务。

## 1. 已知事实与设计边界

SQLite延迟外键允许事务内暂时不满足关联，但COMMIT必须满足；失败后事务可能仍需显式回滚。生成列可参与外键但不能作为主键。本候选使用普通列主键与生成的attempt_marker辅助双向关联；每连接在事务外开启并回读foreign_keys和recursive_triggers。（来源：[SQLite外键](https://www.sqlite.org/foreignkeys.html#fk_deferred)、[生成列](https://www.sqlite.org/gencol.html)、[触发器](https://www.sqlite.org/lang_createtrigger.html)。）

基于上述机制的推荐：监督器单writer、参数化语句、短`BEGIN IMMEDIATE`事务；DDL只在明确的维护／初始化流程加载，运行连接不获得任意SQL入口。信任边界仍是宿主、监督器和权限受限的本地文件；拥有直接改库／关闭约束能力的同权限攻击者不在这些外键的证明范围。原生运行profile继续采用上一轮候选DELETE／EXTRA，内存探针不测试它。

协议BODY与查询列必须由同一可信解码结果产生：严格JSON→具名Schema→完整JCS／摘要与引用关联→权威来源→事务内重核当前状态。SQL只约束投影列／引用，不解释BODY、不验证签名／MAC，不以digest字符串相等授予权限。历史原始wire另作受限诊断资料，不把重序列化的JCS称为原报文。

## 2. 表、字段及DTO映射

所有主键显式NOT NULL，表为STRICT，文本身份使用默认BINARY比较；协议整数采用规范十进制TEXT。Id／Digest的完整词法由上层唯一Schema验证；SQL重点保护多表身份、不可逆状态和提交关联。BODY固定BLOB，包含该版本对象的完整非秘密字段，不能只存“校验通过”布尔值。

| 物理表／视图 | 主键、必存字段与来源 | 不变量与消费方 |
| --- | --- | --- |
| journal_meta | singleton=1；format_version、host_installation_id、incarnation_id、storage_profile_digest | 宿主保护配置初始化；不可更新／删除；路径存在但身份不符时不开准入 |
| runtime | supervisor_id；service、runtime_generation、domain_id／descriptor_digest／descriptor_jcs、protected_policy_digest、root组／代／backend、phase／domain_retirement_id | descriptor映射ClockDomainDescriptor；初始active只表示域记录可登记，不代表入口已同步／设备可写。active→closing→retired不可逆 |
| control_scope | supervisor_id；service、database_instance_id、scope_jcs | 核心可信恢复后一次绑定Scope；FK匹配runtime.service，业务库换代不得改旧scope |
| fence_snapshot | (supervisor_id,revision)；完整FenceSnapshot JCS、snapshot_digest、item_count、sealed | 初始draft；只允许一次封存，JCS／摘要／计数不得原地修改 |
| fence_item | (supervisor,revision,launch_id)；ordinal、intent_digest、allow/deny | 快照投影；ordinal唯一、连续、按ASCII launch_id排序。允许预登记尚未REGISTER的意图 |
| launch_deny | (supervisor,launch_id)；intent_digest、first_revision | 只能来自已封存deny项，永久保留；后续快照可省略历史终态项，不能清旧拒绝 |
| current_fence | supervisor_id→revision | 只指已封存快照，严格整数递增；不等于本连接已经同步，连接状态只在易失内存保存 |
| launch_intent | (supervisor,launch_id)；完整Intent JCS／digest、member、role、组／代、origin／origin_binding_jcs | worker对应extension完整绑定；core/time_provider对应保护策略绑定。与launch_state双向延迟FK，同事务建立；所有身份／内容不可更新 |
| launch_state | (supervisor,launch_id)；state、creation_attempted、生成attempt_marker、admission_id、retirement_id | 投影JournalView。attempt只增、终态不复活；admission／retirement已设不可替换，retirement仅在retired状态非空 |
| creation_attempt | (supervisor,launch_id)；marker=1、fence_revision、authorization_jcs、materialization_observation_id、is_recovery／recovery_policy_jcs、origin_tick | worker须当前allow、完整短授权和当前实物证据；保护配置分支不伪造扩展授权。与state.attempt双向延迟FK，COMMIT不允许仅保存其中一方 |
| recovery_attempt（视图） | creation_attempt中is_recovery=1的行 | 不维护第二份计数表。首次普通启动不算恢复；失败尝试仍保留。所属supervisor绑定原时钟域，跨域不能把origin_tick当新域值 |
| bootstrap_challenge | (supervisor,launch_id)；全局唯一bootstrap_id、member_boot_id、channel_binding_id；原issued／expires、transcript_digest | 每意图一次挑战。只在awaiting_bootstrap登记；不含secret、完整Assignment、proof或可恢复秘密；死亡后不得由摘要重建挑战 |
| os_observation | observation_id；subject supervisor／可空launch、observer supervisor、kind、组／代、observed_tick、evidence_jcs | kind包括物化宿主观察、进程实例、子组退出和全域退出。物化沿原候选复用此受限观察表，不表示它来自OS；来源身份在BODY且由提供者核验 |
| admission_receipt | (supervisor,launch_id)及唯一receipt_id；bootstrap_id、process_observation_id、admitted_tick、receipt_jcs | 对应AdmissionReceipt；与state.admission_id双向延迟FK。行存在代表本次proof已消费，不再额外维护可能漂移的consumed字段 |
| retirement_evidence | (supervisor,evidence_id)；target_scope、可空target_launch、observer、observation_id、result、target_count、evidence_jcs、sealed | 对应RetirementEvidence；unproven也可封存作历史，但不能引用为退休依据；新证据用新ID，不能原地改confirmed_empty |
| retirement_target | (supervisor,launch_id,evidence_id) | 证据目标集合。同域FK防借别人证据；member_group精确一意图，runtime_domain覆盖整个旧域全部登记意图，含保护配置角色和已终态历史 |

运行成员、bootstrap端点、组／generation均有唯一约束。materialization、进程准入和退役各自要求正确kind与观察者；相同opaque ID不能跨用途借用。新观察域的tick可以比旧域数值小，只在该观察者域内核验年龄；没有跨域减法。退役目标表记录登记意图，不能代替真实OS组内未登记后代／无逃逸证明。除主键和唯一索引外，增加域内状态、证据目标反向索引及恢复窗口的长度／BINARY文本索引；后者仅服务同原域窗口，不授权跨域计时。

**跨项澄清：**FENCE_PUT的完整集合是该control_scope下所有扩展worker意图，而非由业务核心批准core自身。protected_config的core/time_provider不进入业务allow快照；其保护策略入口只在监督器受限配置路径，整域关闭／退役则必须覆盖它们。SQL明确拒绝把protected角色混入业务fence，不能借排除它们遗漏一个扩展writer。

## 3. 六类原子事务与唯一创建出口

| 事务 | 顺序和提交条件 | 提交失败／未知 |
| --- | --- | --- |
| J1 域／scope登记 | 宿主初始化核身份；新runtime记录；核心恢复后另事务绑定control_scope。控制连接初始unsynchronized，不能由数据库phase=active推导可写 | 不自动建立替代scope或空库；关闭准入、核对原记录 |
| J2 完整fence | 先锁存连接新创建关闭；BEGIN→insert snapshot/items→验证BODY投影→sealed 0→1。触发器检查全部非终态worker（含尚未配state的intent），同事务追加永久deny及更新current指针→COMMIT→内存同步→ACK | 不回ACK；旧allow不恢复。回执丢失同revision／同digest只读取原封存结果，不能重复INSERT；异内容冲突 |
| J3 REGISTER | 当前peer／scope／授权／完整意图核验；BEGIN→intent→state.registered→COMMIT | 双向FK拒绝孤立记录；同键重投只读并比较完整摘要，不用REPLACE |
| J4 CREATE | 单一监督串行临界区内重核当前fence／权威／短授权与实物年龄→BEGIN→观察记录与creation_attempt（含恢复预算）→state.creating／attempt=1→COMMIT→至多一次OS创建调用 | COMMIT未确认不调用OS；崩溃后不清attempt，即便可能从未调用也按未知退役。禁止一事务混入其他控制请求 |
| J5 bootstrap准入 | 创建成功awaiting_bootstrap及挑战登记；OS实例与MAC等通过后BEGIN→进程观察／admission_receipt→state.admitted_closed／admission_id→COMMIT→交付Receipt | 任一方缺失COMMIT失败并整体回滚；已提交而响应丢失查询原回执；不能再次消费proof。核心RuntimeBinding仍是后续独立业务事务 |
| J6 关闭／退役 | 先停止新准入并将目标retiring或域closing；异步取得真实退出证据；BEGIN→evidence/targets→封存→对应state.retired→完整域最后runtime.retired→COMMIT | kill或ACK不是成功证据；unproven保持保护，等待新证据。不能以退休释放设备资源或改写unknown命令 |

J2封存将快照、拒绝集合、current指针放在同一SQL语句触发器事务内，不能留下“新指针但无deny”。items必须精确计数且有序；已知意图的摘要必须相同，退休／拒绝／退役中／未知成员不能被新快照标allow。漏一个registered或旧未知目标即失败；不截断集合。同一current快照可保留已准入成员allow，但CREATE仍受state／attempt限制，不能据此重启已运行进程。

J4、J5使用双向延迟FK解决“证据先写”与“状态先写”的中间态；这不跨业务库或OS原子。CREATE的完整权限／短期时间判断仍由监督执行上下文完成，SQL只核当前快照、记录身份和事务配对。创建临界区、fence ACK不能越过未完成OS调用的规则仍沿README第3节；本DDL不自行生成派发outbox或恢复任务。

所有字段绑定使用参数占位，不拼接模块SQL；不使用INSERT OR REPLACE。recursive_triggers开启后的删除触发器进一步阻止REPLACE抹除墓碑，但它不是向不可信调用者开放SQL的理由。JCS、身份词法、权限、物化challenge、运行域、profile预算、系统时钟和进程证明逐一由可信提供者核对，不能将`journal_committed=true`当作这些事实已成立。

## 4. 重开、容量与归档

正常新监督器：取得宿主单实例权和保护配置→校验路径／host／incarnation／格式及storage profile→启用并回读PRAGMA→数据库完整性与FK检查→重新解析全部活动BODY及标量投影／digest→发现草稿或孤立证据即保护→保持控制连接未同步→关闭旧域并核对真实组→登记新域及当前核心scope→完整fence后才可新准入。已退出旧runtime不能重新active；旧admission不能给新域使用，旧bootstrap挑战永不恢复。

若存储读写不可靠、COMMIT未知、检测到回滚／损坏或宿主已存在而日志缺失：先停止新准入和设备许可续期，尝试保护关闭／整域停止；仅在有实际OS清空证据后才允许维护恢复。不能`CREATE IF NOT EXISTS`隐式修成空库，不能从业务备份覆盖监督日志，不能根据query未命中推断没有旧进程。真正首次安装由宿主可信安装记录确认，不能靠目录为空猜测。

日志保留所有deny、attempt及不可变证据；运行中没有通用DELETE／VACUUM清理接口。候选实验高水位：256个当前worker意图、每域4096个历史launch、64个保留runtime、日志数据及回滚文件合计256MiB、单BODY256KiB、观察队列128项，80%高水位停止新REGISTER和启动，预留其余20%供保护／退役记录；不能以空间不足清活跃墓碑或截断证明。实际写盘耗尽仍可使保护记录失败，此时先停进程而不虚报耐久。实验值待profile实测批准，不改变全部模块功能范围。

维护归档仅在所有旧域退役、核心确认不再引用、旧请求域永久拒绝且恢复预算可证明已结束或得到明确维护授权之后：保持服务停止→写只读归档及摘要→验证原库与归档字节、全部引用／deny／计数保留→生成新incarnation候选（含保留高水位和归档链）→耐久安装新宿主指针→再核对启动。任一步不确定继续停机，不原地删表重启；归档链、宿主安装指针及精确fsync的生产实现仍属C12／DF05交付，不能以本内存探针关闭运行验收。每次变更格式也走离线受审计迁移和备份核对，首期不在线升级Schema。

## 5. 验证及实施交接

[check_journal.py](check_journal.py)只创建`:memory:`，实际执行15表及双向FK、封存触发器、不可逆状态和不可变证据约束。覆盖J2提交前异常整体回滚、孤立intent／state／attempt／receipt在COMMIT时拒绝、deny后不可创建、不同观察域的退役、全域覆盖及REPLACE墓碑保护。错误与正常结果由人工预期对照，未从SQL自动生成预期；BODY/digest为明确合成占位，不证明其提供者真实。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/check_journal.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/df02-supervisor/check_journal.py --check-report --staged
```

[独立报告](journal-report.json)绑定本稿、SQL、检查器、监督Schema与DF04五份输入；不在旧顶层十份报告清单内。`--check-report`仅核字节；先前179项监督协议检查与局部三表探针保留为历史独立回归，不能把两批计数当同一覆盖口径。

对应SRT02／04／05／07／08／10／11及ST：后续必须在Windows／Linux／容器目标组合运行真实单writer与IPC、创建切点崩溃、disk-full／fsync错误、COMMIT未知重开、保护队列及归档恢复。完整布局已经有候选SQL，尚需统一SDK字段投影与生产迁移／原生驱动审阅；所有真实平台、磁盘和设备证据均未取得，阶段0未关闭。
