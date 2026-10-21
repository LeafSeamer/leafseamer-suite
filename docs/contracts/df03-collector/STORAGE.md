# 参考时间持久化与原件生命周期候选

日期：2026-10-21。本文延续已选reference-bound/1路线，细化[14帧采集协议](README.md)和[DF04](../../rebirth-df04-storage-design.md)。`reference-time-storage/0.1.0-draft.1`是待审阅的设计资料，不是业务迁移。Controller和Seamer各自在自己的关键SQLite库使用同一布局；没有跨库原子承诺。

## 1. 事实与推荐分界

SQLite延迟外键在COMMIT时检查，任一复合外键列为NULL会跳过对应检查，因此必需关联显式NOT NULL，并将合法可空分支另加CHECK。数据库原子提交依赖VFS和存储行为，内存回滚检查不证明掉电耐久。（来源：[SQLite外键](https://www.sqlite.org/foreignkeys.html)、[原子提交](https://www.sqlite.org/atomiccommit.html)。）

本项目推荐：原始请求/响应先由核心通过受保护句柄取到并独立解析，再由秘密存储提供者加密成有界密文，**密文BLOB与发布写集同库提交**。暂存文件或对象存储不作为发布原件的唯一副本。此选择消除发布时的文件/数据库双提交问题，代价是关键库的容量、备份和密钥保留要求；具体AEAD算法/库、密钥封装和两平台profile仍由C07冻结，不能以随意加密实现替代。

## 2. 逐对象映射与唯一所有者

`storage.sql`定义十四表。所有ID只在固定scope内解释；原始DTO、Ref、单调tick及全部资格证据保存在不可变BODY。SQL列是核对后的投影，不能替代Schema、JCS、权限、计时或平台证明。库内revision/generation固定20位补零TEXT，仅用于排序与精确继任；线上仍为无前导零U20，转换必须先核词法/范围。

| 表 | 映射及约束 |
| --- | --- |
| ts_scope | 固定authority/database及布局版本；不把数据库缺失视为新建授权 |
| ts_binding | 不可变完整Binding及generation；同ID不改内容，持久ref由核心签发 |
| ts_poll | 原PollIntent、channel/config/provider完整绑定及关联摘要；核心登记先于POLL投递，重复查原；binding FK，poll_id唯一 |
| ts_capture | 每poll仅一个固定Capture裁决，capture_id唯一；candidate/failed/indeterminate与published/rejected/failure_recorded分开；明确原件数量 |
| ts_blob | capture下request/response/diagnostic槽位；明文摘要/长度、实际密文及cipher/key/provider/associated-data凭据保存在BODY；密文长度有界且原件不可换 |
| ts_verification | 核心独立验证回执；固定capture/Binding和原件集合摘要，可信parser/认证/时代/误差/批准/提交时评估均在BODY；SQL不生成权威 |
| ts_anchor | 固定Anchor、capture、Binding与m4，published才建立；同poll不生成第二锚点 |
| ts_state | 只增AuthorityState修订；含前修订、Binding、状态、可空Anchor及所属commit；旧快照不可修改 |
| ts_head | 唯一当前修订指针，CAS只能推进至精确下一修订；读取只使用已封存commit的State |
| ts_invalidation | 原Invalidation、old/new Binding、保护操作引用；新代次精确加一；新State unavailable且Anchor为空 |
| ts_commit / ts_seal | 不可变事务与单一封存回执，双向延迟FK禁止只提交一半；kind区分bootstrap/publish/reject/failure/invalidate |
| ts_audit / ts_outbox | 每commit各一条、不可替换；普通记录是通知，invalidate固定TIME保护通知；不放POLL或设备DISPATCH重发任务 |

ts_commit的receipt_body保存完整固定CommitReceipt或内部初始化/失效回执，不是新公开DTO。published只有一个Anchor引用，rejected/failure_recorded不产生State。拒绝不是重新采样授权；查询必须先通过当前对象权限。所有BODY以原字节保存，审计/通知只用脱敏投影；诊断不得复制NTS cookie、bootstrap secret、原地址或完整报文。

## 3. 五类原子写集与故障顺序

1. **初始化/重新获得资格**：原监督回执和当前批准已验证后保存新Binding，并创建bootstrap commit、collecting State、head、audit/outbox/seal。初次revision=1；已有State时必须先完成失效，重新启动不得直接复用qualified State。新Binding不得等于失效前旧Binding。SQL只核状态/代次关系，真实批准和启动身份由提供者保证。
2. **登记采样**：短事务保存完整PollIntent，提交成功后才可向当前采集器投递。采集器reserved/consumed仍按专属协议处理，数据库行存在不证明网络已发送；核心重启只查询旧poll/退役旧实例，不能重新发送旧POLL。连接内同完整帧重复仍由原幂等协议处理，不扩大成跨启动重放。
3. **发布**：事务外完成有界原件复制/解析/加密；进入单writer后重新核当前Binding、原poll、当前权限、时间年龄及预算，保存Capture、全部Blob、Verification、Anchor、精确下一State、head、commit/receipt、audit/outbox，最后seal后COMMIT。seal验证完整关联、两个必需报文槽位及字段；任一缺写或失效先到则整体回滚。收到响应时合格不代表提交时仍合格。
4. **拒绝/普通失败**：Capture和可用诊断/报文Blob、固定拒绝/失败回执、audit/outbox/seal同事务；不移动head，不刷新年龄，也不因一次正常采样失败无条件废除有证据旧Anchor。信任/运行域/存储故障需另走失效保护，不伪装普通Failure。
5. **失效**：先在本机运行态禁止新UTC许可；单writer核旧State，保存下一代Binding、Invalidation、unavailable State、head、TIME outbox、audit/seal并提交。通知携带精确Invalidation和旧Binding及保护操作Ref，交既有IPC0.8完整屏障流程。收到设备ACK、选用完整屏障、持久applied及资源核销是后续不同事务；本布局不把outbox存在当作设备已关闭。

ts_seal之前的中间查询只能用于writer内部校验；对外必须从另一只读快照/提交后读取，不向GUI或worker发布事务内head。SQL的封存约束阻止半边提交，但不执行源身份、JCS、动态Schema、误差推导或真实加密。上述验证必须与写入的字节和固定输入绑定，不能先验A再写B。

**提交未知**：首先关闭当前进程的授时资格，查询精确poll/capture/commit。已提交只返回固定历史回执；未找到不能重新发送旧网络请求。若持久状态仍不确定，维持保护并恢复数据库；不得凭RETURNING或已写日志宣称成功。提交后到发REPORT_STORED前崩溃不会重复发布。数据库恢复后必须先完成旧运行域失效和保护，再建立新的采集资格。

## 4. Blob取证、保留和故障处理

取证输入是当前采集器Domain、sealed_ref、用途、期望明文摘要/长度及批准最大字节数。提供者输出受保护只读句柄；核心读取**完整且有界**字节、验证长度/摘要、解析并生成独立验证回执。随后加密提供者以authority/database/capture/slot/明文摘要/密钥版本为关联数据，返回密文和不可变加密回执。缺密钥、读取变化、短读、超额、认证失败或非当前Domain均不发布。

事务提交前失败时只销毁本次内存副本，暂存提供者按原租期关闭句柄；不存在对外发布的原件。提交成功后可释放采集器暂存，不需要等待REPORT_STORED到达；核心密文是持久原件。启动/备份恢复必须验证密钥可用性与固定原件清单，不能仅核数据库页完整。明文仅在受限内存按需解密，不能写普通日志或独立临时文件。

本候选禁止在线删除原件、poll、capture、commit和墓碑；容量上限前预留失败/失效记录空间，普通采样拒收且不进入无界队列。该策略是首期保守保留规则，**不等于无限存储**：实际字节额度、低水位、按源配额由批准容量profile给出。未决guard、审计、远端读取、旧屏障和恢复引用全部作为pin；GC只能在维护模式通过完整引用闭包、归档和密钥保留证明另版引入，不能为恢复采样删除未知记录。数据库容量不足无法记录失效时走已有内存关闸/监督退役通道，持久化恢复前不再授时。

## 5. 验收与覆盖边界

`check_storage.py --report`只连接`:memory:`，检查完整十四表、publish/reject/failure/invalidate正常写集、逐写缺失、每步主动异常全表回滚、同poll双裁决、错Binding/锚点/前修订、失效与发布两种串行顺序、重复查原不动head、不可变证据及已封存后增补拒绝。人工预期独立于待测约束；BODY、加密回执和权威为合成占位，刻意保留“合法占位不证明密码学”的限制反例。

运行验收仍沿用TP/FT：真实writer竞争、COMMIT未知、WAL/FULL和文件系统故障、密钥丢失/轮换、采集器崩溃、设备TIME屏障及两平台监督退出均未执行。十四表覆盖本机时间发布/失效子域，不宣称整个Controller或Seamer数据库完成；与现有91表共用scope/事务/保护操作的最终组合、保护目标/ACK物理布局、STOP账本、跨实例容量及引用感知GC仍须归并。先前“原件/锚点/State没有物理写集”的缺口已落实为本候选，不能据此关闭全部C06/C08。
