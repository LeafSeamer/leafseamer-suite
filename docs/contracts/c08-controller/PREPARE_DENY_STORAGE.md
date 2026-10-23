# 准备拒绝与完整Closure的同库候选

状态：设计候选，未经产品冻结。以[共享日志219表](IPC_JOURNAL_STORAGE.md)为基础增加11表，共230表；沿用[IPC0.13](IPC_JOURNAL.md)已有DENY与PreparationClosure契约，不另造同义消息，不修改业务服务或已确认公共基线。

## 本轮已经联接的关系

`pd_registration`与每个ep_request双向配对，记录单调登记序号、自己的manual/automation来源、自动化准备回执以及控制epoch/version。普通准备与原ce_command来源一致；取消准备来自自己的取消请求，使用独立namespace/授权和显式来源，不能自动拷贝父命令的RUN。相同取消的多个primitive不得更换来源。自动化来源绑定cp_receipt及目标设备；原始请求解码、主体资格和来源提供者仍须外部核验，provenance_body不是自证授权。

登记序号采用补零U20，按两段递增；候选Controller总准备历史受ep_limit.max_metadata_prepares限制，避免单个内部Closure超过65536项。此处将原每出口元数据计数补为Controller总上限，仍不是生产容量批准。活字节退款不删除登记历史、不退款序号；历史归档与新数据库代次不能由本候选自动执行。

| 原关闭事实 | 准备选择范围 | 原有最后提交的要求 |
| --- | --- | --- |
| cu_cut | 同设备全部历史编码准备，包含不同出口、未回复、失败及已释放记录 | ct_commit必须看到配对的pd_cut_commit；cu_effective及最终ct_commit重核完整准备Closure |
| cc_cut ordinary/all | 同命令的ordinary准备／同命令全部普通与取消准备 | cc_cut_commit必须封存完整准备集合；cc_closure必须引用对应准备Closure |
| ce_fence | 自身origin authority/database/run及被拒代次的自动化准备 | ce_cut_commit必须封存准备集合；ce_application必须绑定完整准备Closure |
| go_close | 该物理出口的全部准备 | 原保护ct_commit封存准备集合；物理ACK另存，恢复前逐出口补pd_close_completion |

四种选择直接连接原有表，不接受调用方另填一套自由selector代替。AUTH/TIME仍没有完整权威同库来源，本轮不创建可自填成功的替代记录；它们的准备捕获和最终应用继续作为冻结缺口。

## 写入顺序与完整性

准备登记顺序为`ep_request → pd_registration → ep_request_commit`。登记与原prepare反向外键配对；登记晚于原seal、重复序号、来源错配或旧RUN/控制版本均拒绝。登记仍不产生发送许可。

关闭顺序为原cut/保护事实、`pd_cut`、全部`pd_member`、成员永久ep_revocation、`pd_cut_commit`，最后原领域seal。pd_cut同时绑定原操作和登记水位；成员逐项绑定prepare、授权与出口。封存对比完整SQL选择集合，不从permit或prepared结果推导成员、不忽略已退款历史。原领域seal再次核水位，防止同一事务中先封存cut再插入准备绕过集合检查。复用已有撤回原件，不为同一prepare覆盖第二份墓碑。

DENY出站为`ij_frame → pd_deny_request → ij_commit`，复用已有共享发送尝试与完整写入约束。请求精确关联原编码帧、授权Ref、原撤回Ref、出口和时间；编码已预约而worker尚未看到时仍可拒绝。尚未预约编码帧的准备走本地never_attempted证明，不伪造encode_frame_digest。

DENY入站为`ij_frame → pd_deny_ack → ij_commit`。ACK关联原请求的Ref、message_id、完整帧摘要、prepare与同一出口，先有请求入流尝试；有效时刻不得早于尝试。日志保留historical ACK，但只有applied且未撤回的原ACK可参与关闭证明。DenyAck不证明消费者退出、缓存清空、设备未发送或预留可退款。

内部Closure为`pd_closure → 每成员pd_coverage → pd_closure_commit`。四种依据分别为：

- never_attempted：已永久撤回，且数据库从未记录编码发送尝试。
- released：原ReleaseAck已通过原adoption/退款/ACK seal提交；不能只凭ep_reply成功或失败。
- retired：原出口存在监督退役证据，且证据未被撤回。
- deny_ack：同prepare与同出口的原DenyAck已作为applied入站提交且未撤回。

任何缺项、错prepare、错授权、错出口、未提交或撤回证明都会拒绝Closure。输出序列化仍须按prepare_id排序；SQL关系集合不能代替JCS规范原件。Closure先于相关公开生效，控制的最终ct_commit再次重核，防止在同一事务里先组装effective再撤回其准备证明。

## 故障和恢复边界

编码结果未知仍占原预留，不能走never_attempted。Deny之后，已经准备好的packet与设备在途事实保留；新编码预约和发送通过永久撤回守卫拒绝。正常Release继续独立处理，重复ACK只查原，不重复退款或采用。

物理CLOSE_GATE_ACK的记录与准备完成分开。恢复必须逐个原close/ACK引用pd_close_completion，不能仅凭物理闸已关推导全部编码准备不可再用。准备证明撤回使对应Closure、控制/取消有效视图、RUN有效应用投影和恢复视图失效；已恢复的ready候选也继续依赖有效恢复证明。旧历史记录不覆盖或删除。

这里验证的是数据库内关系与当前候选。向GUI/订阅者发布撤回后的新事件、真实worker拒绝、设备传播窗口及可靠通知服务仍待业务实现。pd_valid_application是新增的有效RUN应用投影；P3至P4及所有公共查原消费者必须在统一SDK归并时接入，不能继续把历史ce_application的存在当作当前有效。

所有新表不可改写/删除。数据库不可写时的volatile_close与监督退役仍按IPC0.13执行，不等待本轮表写入；本轮没有运行该路径。实际重启、重复请求查询、磁盘预算和旧会话封死仍须运行证据。

## 验证与后续冻结

```text
python docs/contracts/c08-controller/build_prepare_deny_storage.py --check
python docs/contracts/c08-controller/check_prepare_deny_storage.py --report
python docs/contracts/c08-controller/check_prepare_deny_storage.py --check-report
```

检查在完整230表内存SQLite上执行，不停用旧守卫。包含登记、接管捕获、RUN捕获、保护关闭、DENY出入站、Closure各写集缺写和逐步异常回滚；真实T4、RUN应用、取消ordinary/all、保护完成至恢复/换闸/OPEN/ready链；准备证明撤回使旧恢复与ready失效；未知、失败、已释放历史及多个出口的集合；取消自身来源、旧代次拒收及不可变原件。精确结果与输入摘要见[报告](prepare-deny-storage-report.json)。

剩余工作沿[全系统清单](../../rebirth-design-closure.md)收敛：AUTH/TIME权威及准备范围、其他消息领域共享日志迁移、完整AdmissionSeal与Guard/预算/时间、全部P3/P4和公共投影消费者、唯一SDK源。BODY和授权/监督提供者仍是合成前提，不能把内存SQLite结果当作真实IPC、并发、磁盘、设备或直播验收。四最终准入阻断保留，阶段0未关闭。
