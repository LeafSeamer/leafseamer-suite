# 固定证据快照与分页读取候选

状态：`approved=false`。本轮在[完整公开记录](TYPED_COMMAND_VIEW.md)上增加[证据装配与读取参考模型](command_evidence_model.py)、[检查](check_command_evidence.py)及[报告](command-evidence-report.json)。复用[既有七接口及类型图](COMMAND_CONTRACT.md)，不增加HTTP路由或改旧Schema，不运行服务和设备。

2026-10-24后续：[attempt原件映射](ATTEMPT_PROJECTION.md)已接入分页内部完整记录核验；非空attempt必须具有同修订本地来源，不能通过证据页绕开原件校验。没有attempt的旧空快照维持原行为；单条证据查询仍按自身来源验证。

## 已知事实与本轮边界

公共证据页已有固定state_revision、limit 1–64、独立command.evidence.read、不可变snapshot和五类EvidenceRecord契约。单独command.read不能授权读取证据正文，current不可发布不妨碍明确的历史证据查询。（来源：[公开读取契约](../c02-command-view/README.md)、[OpenAPI](command-contract.openapi.json)。）

本轮将证据行、成员和完整公开修订装配到实际237表SQLite布局，并实际执行HMAC签名与验证。它验证持久关联、分页及权限边界；输入的生命周期裁决、原件真实性、脱敏和当前时间仍由显式合成提供者表达。示例decision仅用于检验存储和排序，不表示现场动作已经失败或完成，不据此自动生成命令终态。

## 发布与原件映射

调用evidence_steps的唯一writer必须已经在同一事务持久权威证据原件、验证记录和完整新State，并在公开投影装配后写cm_commit。局部装配器不负责决定动作成败、调用设备或新建普通attempt。

1. 核当前本地发布权限、原件验证、投影验证和脱敏证明，精确绑定StateRef、新证据view_digest集合以及完整attempt/completion/cancellation投影摘要。
2. 在读取原集合前核对完整证据成员容量；超额整笔拒绝，不截断集合或省略证据。
3. 对每个EvidenceRecord核完整Schema、命令/scope/kind/ID/revision、source_body和view.body一致，以及原件摘要和view_digest。decision/release/resolution的自身摘要字段按各自契约计算，observation/invalidation直接摘要正文。
4. 合并已持久全部证据版本，按ID、数值revision、kind排序，保存新cv_evidence、cv_snapshot、完整成员及CommandRecord。同修订State、快照和公开记录由已有SQL封存核对，发布者再调用内部完整记录验证，最后cm_commit。

既有decision/release/resolution原件FK和guard继续有效；观察证据的实际worker/attempt/出口提供者映射仍是未关闭项。只有非空validation_body不能证明原件真实或已经脱敏。公开body由封闭Schema白名单约束，但合法字符串仍可能包含秘密，真实投影提供者必须落实脱敏，不能靠本轮布尔标记放行。

## 两个只读操作

getCommandEvidence以command_id、明确state_revision和limit读取固定已提交快照。每页重新核当前认证、授权有效性、command.evidence.read、本库scope、设备范围或受信Seamer来源。单页最多64项；读取时另有显式max_snapshot_members合成包络，超总量拒绝，避免将页大小误当作整集验证成本上限。

getCommandEvidenceRevision按command/evidence/revision读取与初次公开State提交配对的不可变原件。错命令、错版本和未提交对象不返回正文。两种读取都拒绝正在进行的writer事务；响应阶段失权也不输出正文。读取不分配证据序号、不刷新State、不补写成员，不取得任何设备写权。

查询固定历史修订时，迟到新证据进入新的State和snapshot；旧页total、成员顺序及摘要不变。历史证据可在原grant撤回后由当前有权主体审计读取，不能据此断言当前效果仍有效。

## 游标具体冻结候选

外部仍是既有16–4096字符的不透明base64url串。本地参考编码为规范化JSON正文、分隔字节和32字节HMAC-SHA256认证码整体编码；固定域前缀隔离其他令牌用途，比较使用标准库constant-time接口。签名密钥只由本地keyring输入，不进入游标或报告；仓库测试值是显式合成字节。此编码是参考实现候选，不构成生产SDK密码库或部署密钥方案已获批准的声明。

| 游标字段 | 约束 |
|---|---|
| version、contract_version、key_id | 固定游标版本、命令契约版本和部署验证键身份；没有可选算法字段 |
| scope、command_id | 精确绑定Controller实例及命令 |
| snapshot_ref、state_ref | 固定快照及State的ID、revision和digest，不能换最新修订续页 |
| subject | 当前读取主体的issuer_id、issuer_epoch、principal_id、session_id和authorization_revision，来自可信认证上下文 |
| limit、offset | limit绑定原页大小，offset为U20十进制字符串；不允许越界或把数字改成浮点 |
| clock_domain_id、descriptor_digest | 本地受监督单调时钟域；换域拒绝旧游标 |
| issued_tick、expires_tick | U20精确整数；issued≤now<expires，等于expires即过期；续页保持原有效期 |

服务每页验证签名和完整字段绑定。授权修订、主体、session、scope、command、StateRef、snapshot或limit变化均拒绝续页。密钥轮换可以保留旧验证键使原游标在原期限内完成；撤去旧键不能降级为不认证游标，也不能自动当作首屏重新查询。无效游标由HTTP适配层映射既有错误，不能泄漏内部异常或密钥状态详情。

过期或时钟域改变后，用户可用当前权限重新请求指定历史修订首屏；这不会切换到最新快照。参考模型使用单调时钟输入，NTP参考UTC修订不能直接改变已签发游标的单调有效期。真实监督域和时钟提供者尚未接入。

## 验收与剩余事项

86项检查通过：证据发布逐写异常和漏写、缺提供者资格/脱敏证据拒绝、超容量全事务回滚、空快照、排序与整集、两页间新提交、旧空快照保持、单条原件、只读零写、读取权限/配对/主体变化、错误limit/State/时钟域、过期边界、损坏认证码、有效签名但越界offset、保留/撤销旧密钥、续页不延长TTL、原件损坏及超过2^53的精确时间。

新生产者夹具使用实际cm_decision与cv_evidence关系，维持非终态State，仅用于公开投影事务验收。它不是已实现的设备决策器，不替代后续完整attempt、完成/释放/Resolution和取消生命周期writer。五类证据的Schema被复用，但本轮数据库正例主要覆盖decision，其他四类完整上游生产链尚须逐一归并。

当前已提供两类证据读取的本地参考行为；真实HTTP错误封装、认证/授权与监督时钟、部署密钥保护和轮换、完整CostManifest/GC、全部生命周期及SDK生成、原生制品、磁盘/并发/网络/设备验收仍未完成。业务未改，阶段0不关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_command_evidence.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_command_evidence.py --check-report
```
