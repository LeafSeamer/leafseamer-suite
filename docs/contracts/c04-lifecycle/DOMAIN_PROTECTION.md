# 跨域保护与退役关闭复用

状态：内部候选，approved=false；接续[快照换域](SNAPSHOT_DOMAIN_ORDER.md)，业务实现尚未开始。

已知事实：原授权保护writer展开同设备全部出口，按设备当前域tick写入关闭cut；这不能表示跨域旧出口的时间。（来源：[原保护模型](authorization_clock_protection_model.py)。）

本候选在换域后分开保存当前域关闭与旧出口退役依据。旧出口必须提供当前有效的完整RetiredCloseSet，核对最新关闭、全部准备与整个worker成员；只引用原件，不新建旧域关闭、cut、撤回或IPC。当前域出口继续使用原关闭协议及完整准备撤销事务。两部分由同事务DomainProtection与封存行组成，SQL强制全部设备出口精确覆盖；旧保护入口尝试跨域写go_close也被守卫拒绝。

DomainProtection包含完整active_protection、retired选择和整体摘要。active_protection只表示本次需要新关闭的当前域出口，不能独立代表整台设备；使用本候选的消费者必须同时核对xdp_commit与退役成员。后续证明撤回使当前资格失效，历史查原不刷新资格、不复活旧worker。提供者Ref和模拟ACK不能证明物理完成。

适用边界：每个受影响设备必须有当前域出口且至少复用一个退役出口。缺少旧域退役证明时整笔失败，调用者必须执行出口停止/监督终止流程；全退役设备继续保持protected，使用既有完整退役路径，不为凑关闭记录制造新会话。真实监督动作、全系统主动保护传播与最终重新开放尚未交付。

交付：[Schema](domain-protection.schema.json)、[SQL](domain-protection.sql)、[模型](domain_protection_model.py)、[验收](check_domain_protection.py)、[报告](domain-protection-report.json)。保留全部最终发送阻断，不修改公共已确认基线。

本轮实际86项检查通过，覆盖266表组合：旧writer跨域写入被拒且回滚、旧关闭和准备原件不变、逐写异常/漏写完整回滚、提交前后观察失败、重复查原、兄弟出口证明撤回及历史读取。合成新域会话实际写入CLOSE_GATE日志、入流尝试与结构化ACK，随后准备核销和新域快照进入混合恢复seal；恢复seal后旧worker任一成员证明撤回同时使保护及恢复资格失效。当前域夹具的准备集合为空，非空准备撤销路径沿用已有模型但本轮未独立覆盖；磁盘崩溃、跨进程竞争、真实IPC及物理关闭尚未验证。

复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_domain_protection.py --check`；`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_domain_protection.py --report`。本轮只证明跨域保护到恢复seal，不能视作重新开放或全系统验收通过。
