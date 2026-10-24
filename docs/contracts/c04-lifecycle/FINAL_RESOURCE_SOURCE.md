# 最终封存的控制、占用及资源来源

状态：候选，`approved=false`。新增[关系解析器](final_resource_source_model.py)和[检查器](check_final_resource_source.py)，继续连接[编码原件](FINAL_ENCODING_SOURCE.md)与[最终封存](FINAL_ADMISSION_STORAGE.md)。不改变既有DDL，不移除最终发送阻断。

## 已知事实

普通`cr_hold_commit`要求同attempt已有permit及传输commit，Ownership再依赖hold_commit；完整T2不能把hold独立提前提交。新增hold后，旧资源快照已不再等于当前风险全集，因此只能用于前态，最终封存必须另取完整后态。`go_authority`排除ready等闸投影变更，不能以最新公开控制修订替换真正控制授权来源。（来源：[资源布局](../c08-controller/resource.sql)、[占用归属](../c08-controller/ownership-storage.sql)、[开放布局](../c08-controller/open-storage.sql)。）

归属采样回执期限限制的是当次Ownership封存，已封存历史不因回执过期而消失。之后每次发送另取当前授权与Guard，不能错误要求历史回执在每次发送时仍未过期。（来源：[归属存储说明](../c08-controller/OWNERSHIP_STORAGE.md)。）

## 本次关系边界

`control`从当前go_authority、ct_current_state及实际ce_exit读取完整控制epoch/version、holder和运行域；pending、跨库、换出口或完整主体不符均拒绝。其Ref沿用控制原件的id/revision/digest，不把ready修订当成新控制权。

`inventory`读取精确已提交go_snapshot及全部go_hold，并按cr_hold与ow_record反查不可变归属。当前后态必须属于go_current_snapshot，且与cr_risk_hold双向集合相等。历史前态不再拿当前全集替代；每个历史成员仍保留其实际hold与Ownership三元引用，分类通过既有词表映射。

`pair`分别检查历史前态和当前后态。create只允许增加指定新hold，所有旧成员的摘要、归属和分类必须完全相同；reuse要求整个集合相等且指定hold已存在。两态的控制授权、出口及资源安全代次必须一致，且等于本库当前hazard代次。选取时刻之前必须已有前态，后态不能来自未来。`pair`只是集合关系子检查，保护hold新增正例不等于普通T2首次签发正例。

`ownership`核当前来源未撤回、实际命令/attempt或取消/execution、完整Requester、原控制授权与时钟域，验证sampled≤acquired≤原committed<expires以及原committed≤本次selected≤sealed。它不把原expires当成本次发送截止。

`read`组合四种投影：control、ownership、resource_before、resource_after。普通路径另要求后态go_valid_snapshot；取消路径仍需独立保护评估，不能借本解析器直接授权。`verify`把调用方四种投影与本次实际读取逐项比较，返回`storage_relationships_valid_requires_provider_verification`。

## 来源真实性与未闭合项

本轮核的是实际表列、归属外键、完整集合及当前失效事实。旧控制、快照和Ownership字段仍允许合成正文；其已有digest列并不证明完整正文Schema/JCS或提供者真实性已核验。因此本解析器不能被当作完整原件密码学验证器，也不能单独据此签发。resource_safety_ref仍由对应可信提供者传入，本库只验证两态和当前hazard代次相等；该Ref自身的权威绑定、独立gate_safety、完整回执与其他来源仍待接通。

这与编码原件解析器已实际重建完整消息和证据的验证强度不同。报告分别标示：当前控制读取已进入242表编码链；非空归属和资源变化在既有182表子域中实际执行。没有删SQL守卫或强行插入缺传输的普通hold来制造完整正例，242表完整hold/Ownership/T2正向事务仍未完成。

## 验收及后续

正例覆盖已过采样回执期限但仍保留的有效历史归属、真实保护hold新增前后态、相同hold复用、242表普通编码与当前控制投影连接。反例覆盖跨库/出口/主体、pending接管、错父命令或取消执行、漏风险、重标归属、错误create/reuse、期限等号、来源撤回与hazard推进。失败不写库，撤回保留原占用和历史。

下一步需将控制、Ownership和资源回执升级为可核验的具名正文，与真实提供者和剩余最终准入来源合并，再完成完整T2领域写集及发送前复核。阶段0保持未完成，未运行真实设备、服务IPC或进程崩溃验证。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_resource_source.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_final_resource_source.py --check-report
```
