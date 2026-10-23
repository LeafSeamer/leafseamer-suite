# 普通与取消共享签发账本候选

状态：设计候选，未批准部署。`build_issue_ledger.py`从既有91表与`issue-ledger.sql`生成94表组合`controller-issue.sql`；旧文件和旧报告保持原范围。没有修改业务代码。

已知事实：旧`fence.sql`独立分配普通许可序号；RUN切点、`resource.sql`资源释放、`c02-command-view/storage.sql`取消受理及封存，共四处读取`max(ce_permit.issued_revision)`。IPC0.8已包含独立取消传输，因此这些水位不能表示完整发送历史。（来源：上述SQL及[时间切点候选](../df03-time-fence/README.md)。）

基于这些事实，本候选将分配与类型事实分开，先冻结共享序列及配对存储。它尚未完成取消执行Plan/ordinary关闭证据的物理FK、取消报告及核销、全部屏障覆盖、TIME与27表采集布局归并。**不得启用协作取消或把本组合当完整Controller迁移。** 下述阻断触发器是待归并缺口的可执行标记，不能替代最终完整功能，也不能作为产品降级设计。

## 字段与唯一权威

| 表 | 关系与原子约束 |
| --- | --- |
| ci_issue | permit_id全局主键，issued_revision全局唯一补零U20，kind为ordinary/cancel；只允许对应类型指针等于自身ID，反向延迟FK指向真实类型行 |
| ce_permit | 新增固定ordinary的issue_kind；复合FK回绑ci_issue的ID、revision、kind，保留原普通发送状态及资源守卫 |
| ci_cancel_transmission | 回绑ci_issue；cancellation_id指真实已提交cooperative受理，exit_id指相同设备的真实出口；execution_id/digest固定于该取消，primitive/ordinal唯一，原packet及初始permit精确关联 |
| ci_cancel_commit | 与取消传输双向FK；ordinary_closure、execution_validation、guard、budget_charge、原packet_bytes、完整dispatch_intent、审计和唯一outbox同事务保存 |

普通和取消共同从1精确递增；分配时先插ci_issue，随后类型行和提交写集。每条已提交issue必须恰好对应一种真实类型，不允许悬空预留或跨类型复用。普通类型必须有原ce_transmission_commit；取消类型必须有ci_cancel_commit。整个写集在同一writer事务提交，回滚不消费序号，提交未知只查原permit，不能换ID补发。

U20使用两段十进制算术，不能转SQLite有符号64位整数。最大值已存在时明确issue_exhausted，禁止回绕。高位边界的算术探针不等于写入了10^20条历史；生产连续性只能来自该初始库及每次守卫，不能导入任意跳号种子。新库仍无旧数据迁移。

取消的Requester来源固定在自己的origin/authority/database/run/generation，不借父命令automation来源。人工字段必须全null；自动化必须完整且不能越过当前run_deny。time_required=false禁止夹带时间绑定，true必须有绑定；具体Domain/State及时间资格由后续原件提供者核验。primitive的首次ordinal为0，后继精确加一并指同初始许可、同出口、同packet与时间要求；同取消不能换execution重做。SQL并不证明允许重传、当前权限、普通关闭、预算真实性或同字节摘要，非空BODY的通过保留为限制反证。

## 现有切点的同版迁移

生成器精确移除旧普通后继分配器，改由ci_issue负责；四个旧水位读点全部改为ci_issue。生成器按固定源码计数验证替换，任何原输入变化导致计数不符即停止，不静默遗漏。ci_issue存在未封存类型行时仍属于当前事务，最终配对不齐不能COMMIT。

RUN封存至来源提交之间，ci_issue与旧执行登记一起禁止插入，防止封存后暗增取消。取消受理与封存的水位重新比较会捕获事务内插入；资源释放封存同样读取共享水位。

仅换水位不能补齐集合，因此暂保留两个显式归并阻断：

- RUN selector匹配任何已登记自动化取消传输时，封存报cancel_run_coverage_not_merged；不能沿用仅普通的ACK覆盖并宣称applied。人工取消不按父命令run误匹配。
- 父命令已有取消传输时，资源释放报cancel_resource_coverage_not_merged；反过来，已登记释放的父命令也不能再登记取消传输，两种事务内顺序均阻断。ordinary/all关闭及取消效果不能凭BODY直接清资源。

后续必须以取消完整cut/item/ACK/采用及资源核销外键替代阻断，并在同版本组合中验证，再允许部署。FENCE/AUTH/TIME仍未具备完整物理映射；新增字段没有豁免这些保护。最终每种屏障按自己的Requester与时间选择语义取完整集合，不能全局截断或默认空。

## 故障与验收

1. 普通→取消→普通和取消→普通交错都连续；不同类型同ID、同revision、跳号、缺类型或缺提交行均回滚。
2. 逐条写入前后主动异常，对比全部94表；故障后可用同下一号重新完成尚未提交事务。提交后重复同ID失败并查到原行，不创建第二许可。
3. 不合格取消模式、错设备出口、已退役出口、已关闭取消、换执行或packet、漏origin和时间绑定都拒绝。
4. 取消占据最新水位后，RUN/取消/资源释放拒绝旧普通水位；完整取消覆盖缺口不能被新水位掩盖。
5. 全部新表UPDATE/DELETE/REPLACE拒绝；SQLite FK与完整性检查通过。

`check_issue_ledger.py --report`只使用内存SQLite和人工BODY。`--check-report [--staged]`仅核输入原字节。报告分别注明内存SQL、算术探针及未执行事项；不运行网络、磁盘崩溃、真实writer并发、权限提供者或设备。应用内严格解码/JCS到这些列的唯一映射、普通许可的完整时间外键及取消保护写集仍需下一轮冻结。
