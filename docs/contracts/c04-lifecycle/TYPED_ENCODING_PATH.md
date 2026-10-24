# 类型化命令的编码与packet持久化

状态：候选，`approved=false`。本项接续[首次开放链](TYPED_GATE_PATH.md)，在同一个242表Controller中验证当前grant、类型化命令、prepared attempt、普通编码及packet固定库存。业务服务未改，最终签发阻断保留。

## 已知事实与本次对齐

现有SQL会话profile固定IPC 0.13，而已确认的continuation绑定消息为0.14。既有编码关系模型把完整运输请求计入content_digest；当前命令契约排除context_id、idempotency_key和correlation_id。直接拼接这两组接口会产生版本或摘要分歧。（来源：[会话SQL](../c08-controller/ipc-journal-storage.sql)、[当前消息生成器](build_continuation_binding.py)、[编码关系模型](../c08-controller/encoding_authority_model.py)、[命令受理](typed_controller_model.py)。）

本项独立生成[候选布局](controller-typed-encoding.sql)：会话profile统一为`ipc/0.14.0-continuation-draft.1`；普通编码的content_digest沿用已受理CommandContent摘要。运输请求仍按首次原件完整保存，消息摘要覆盖完整帧；packet摘要与原字节SHA-256各司其职。旧生成产物不变。

## 同库正向链

先用实际启动写集开放全部目标设备，再签grant、Seamer采用/R5/触发、Controller受理并生成固定prepared修订。随后按以下顺序写入：

1. 在BEGIN IMMEDIATE内读取原命令、请求、namespace、attempt、出口及当前会话，验证当前cn_live_command与提供者；保存完整EncodingAuthorization、ep_request、pd_registration和request commit。
2. 生成Schema可校验的ENCODE_PACKET完整帧，包含首次运输请求和独立编码授权。保存ij_frame、ij_encoding_frame和ij_commit；全会话方向序列从已有握手/换闸/OPEN的3继续为4。
3. 同事务保存ep_send_attempt和对应ij_write_attempt；随后独立保存写结果。本向量以四字节大端长度前缀封装规范JSON，保存完整wire_body并依据实际字节计算SHA-256；这是明确的离线封装选择，正式管道分帧与读取器仍待实现验收。
4. 接收PREPARE_PACKET时重新读原请求、授权、当前grant及会话；校验完整Schema、原始消息对应、当前外部来源、packet命令/attempt/出口、计划和传输profile、socket/protocol、字节长度和SHA-256。
5. 同事务保存入站日志、完整ep_reply/EncodingEvidence、接收commit、日志commit以及ce_packet映射。响应接收事实可与ce_packet映射分阶段持久，但正常参考路径一次提交；缺领域提交不允许仅凭日志采用。
6. 发布下一固定CommandRecord库存修订，从实际ce_packet与ep_request提取packet和出口；旧修订按自身固定成员读取，不借新packet。此时仍not_sent，send_started_at为null。

## 当前资格与异常

候选SQL在普通编码登记与最后request commit重核continuation资格。ep_open_request追加当前cn_live_command限制，因此撤回grant后不能入队、开始编码、采用响应或继续作为prepared候选；已保存字节和日志不删除。它仍不是最终发送Guard。

完整授权正文与SQL列绑定scope、出口各代次、命令/attempt、主体、内容摘要、primitive、reservation和时窗；响应packet正文绑定列及原命令、出口、长度与摘要。SQL不计算SHA-256、不证明提供者真实性，完整校验由唯一writer内的[参考适配器](typed_encoding_path_model.py)完成；不能把直接执行SQL当作受信业务接口。

授权和采用都需要当前授权、能力、参数、时间、容量保留和传输实例提供者。测试中的这些来源明确为合成，不将它们的true标志当成生产资格。到期等号、同长度字节替换、重算摘要后换命令/attempt/出口、错响应会话均应拒绝。撤回编码授权保留活额度，只有既有release证明流程可归还，不能把超时或响应拒绝当作退款。

## 验证与限制

[检查器](check_typed_encoding_path.py)在两个独立Controller运行正常路径，覆盖逐写故障与必需行漏写、当前grant在各阶段及最后提交点撤回、列/正文错配、完整帧Schema、原字节、截止等号、提供者失效、旧库存稳定性及恢复不重投。比较新旧sqlite_schema，仅允许列出的会话版本与编码收紧变化，四个最终签发阻断不放开。

启动握手、OPEN及外部身份/时钟仍沿用明确合成提供者。编码请求与响应是完整Schema消息，尚未用真实管道或socket发送；SQL中written仅表示实验保存的合成写结果。未验证完整握手协商、取消编码链、最终hold/Ownership/Guard/预算/AdmissionSeal、SEND_REPORT、真实进程崩溃或设备。阶段0继续未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_typed_encoding_path.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_encoding_path.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_encoding_path.py --check-report
```
