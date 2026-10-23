# 恢复准备与 R2 原子登记候选

状态：离线设计候选，`approved=false`，不改变draft.4／IPC0.3，不实现业务服务。[P1上一轮布局](STORAGE.md)保留原证据范围；本页解决其中“R2已提交但准备尚未登记”的窗口，并补原请求尝试和回执采用。源文件为[registration.sql](registration.sql)、[参考写集](registration_model.py)，由[生成器](build_registration.py)组合为[66表布局](seamer-registration.sql)。新布局从建库开始安装全部约束，不是生产迁移方案。

## 已验证事实

[检查脚本](check_registration.py)和[报告](registration-report.json)记录105项离线检查。实验在新66表内存库直接执行既有摄取写集，生成真实关联的trigger决定、执行与完整计划，再把该执行置unknown、run暂停，随后执行R2、准备尝试、回执采用、R3和R4。没有先移除守卫再导入非法历史。

正例覆盖rule正常恢复及零设备reconcile路径；旧unknown、原摄取决定和旧计划保留。反例覆盖每条R2写入缺失及写后异常的全库回滚、集合/别名/完整scope/正文错配、准备容量失败、来源未同步、预览截止等号、准备途中P1、迟到回执和已规划R4的最后拒绝。新链路不代表state_machine所有恢复分支已经在此组合验证。

## 固定契约与提交顺序

| 对象 | 主要字段与约束 |
| --- | --- |
| 原recovery_operation／preparation_target | operation反向延迟引用pr_commit；每个目标通过原operation/controller别名反向延迟引用唯一p1_preparation。登记仍正向引用原目标，缺任何一侧都不能COMMIT |
| pr_commit | operation_id、run_revision、slot_revision、dependency_head、target_count、manifest_digest/body及audit。声明别名数组、原目标、登记数量、manifest绑定必须完整相等；固定run/slot/generation、原preview消耗和preparing/pending前态；依赖来源必须synchronized |
| p1_preparation | 沿用原字段，新增(recovery_operation_id,recovery_controller_id)唯一约束。目标别名与Controller完整scope分别存储，不能把别名当authority；原target正文须与登记的scope、preparation_id、registration_id和请求正文一致 |
| pr_attempt | registration_id唯一、attempt_id唯一、原request_digest/binding、runtime/audit正文。要求R2已封存、原操作仍preparing、原目标pending、同run/execution/generation、来源同步且未被P1拒绝 |
| pr_receipt | registration_id、operation_id、controller_id、evidence_id、audit。采用的证据必须来自原尝试，且反向延迟引用目标的同一个receipt_id。证据、采用事实和目标applied同事务，不可单独提交半个采用 |

1. 在`BEGIN IMMEDIATE`内核验身份、预览、当前上下文、原run/slot；创建原R2操作、执行、锁、全部目标，并消耗预览、增加run/slot修订。
2. 同事务登记完整准备请求、outbox及审计；最后写pr_commit，重核集合和来源。只在COMMIT确认后返回accepted；任何登记/配额失败回滚整个R2，原暂停状态和锁存不丢失。
3. 准备发送前另记pr_attempt；记录不等于网络已发送，也不授予设备发送许可。参考模型不调用网络，实际提供者须在唯一发送出口再次核验当前资格，不能跨网络等待持有SQLite写锁。
4. 网络结果未知或提交结果未知时，先按原数据库与请求身份查账。pr_attempt已存在时只查原请求，不能根据“没看到响应”再发一次；未尝试者也必须重新过当前资格。`pr_recovery_inventory`只是分类，不是重启发送队列。
5. 回执采用复用[准备Observation契约](../c08-controller/PREPARATION_DELIVERY.md)：只采用`applied`，验证原binding、认证域及摘要。external_evidence的object_id、revision、digest分别绑定applied_receipt_ref.id、preparation_revision、observation_digest，body保留完整观察。
6. 已有同字节external_evidence但尚无pr_receipt时继续完成采用，不能误当完整重复；已完整采用的精确重复零写。同身份矛盾正文拒绝，旧原件保留。
7. 全目标有匹配采用事实后才允许ready。R4重新检查原锁存和来源，SQL同时检查准备完整性及P1拒绝下界；即使R4写集已经规划，后发生的P1仍能阻止其提交。

目标数量受既有p1_limit.max_targets约束，登记总量仍受max_preparations约束；不以缩短目标集合满足配额。manifest和摘要用于绑定，SQL不证明摘要来源或发布工件的语义完整性。参考模型的request_body明确是内部合成请求，尚不是冻结的HTTP序列化器。

## 故障边界与剩余工作

- R2故障：写入目标但未登记、登记但未封存、只写部分目标或写后抛异常，整个事务回滚。没有可被P1遗漏的已提交R2目标。实际磁盘IOERR、COMMIT结果未知仍需运行层查询原身份及受监督闭锁，内存回滚不能证明掉电安全。
- P1发生在准备前或准备途中：完整登记已在库内，P1固定全部目标，包括尚未尝试与响应未知者。P1后禁止新尝试，迟到回执只补历史；旧generation和新增锁存阻止R4。
- 本页的applied是历史准备回执，不能冒充永久有效grant。当前仍缺准备回执矛盾/撤回的持久隔离与失效传播、通知流健康、可信身份/时间/资源提供者及最后启动资格的完整联接；`gates`和runtime正文均为显式合成上下文。
- 正常arm登记、完整P0预留与磁盘预算、来源baseline/resolution、新代次恢复条件、Controller最终AdmissionSeal、全部API/SDK同版归并及业务服务仍须完成。没有删除原需求，也没有关闭阶段0。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/build_registration.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_registration.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c05-protection/check_registration.py --check-report
```

本轮未运行真实并发、网络、磁盘崩溃、NTP或设备测试。上轮179项报告按原字节范围保留，只复核绑定，不借本轮结果扩张其证明范围。
