# 健康恢复后的完整换闸屏障

状态：内部候选，approved=false；不修改已确认公共基线，不进入业务实现。

已知事实：既有gf_request、gf_ack和gf_commit保存独立换闸身份，并与共享go_gate及全消息日志关联；旧首次开放夹具使用占位正文，不能证明完整请求、ACK和闸原件的绑定。（来源：[独立屏障设计](../c08-controller/GATE_RENEWAL.md)、[首次开放参考写集](typed_gate_path_model.py)。）

本候选以[统一关闭证据](CLOSE_EVIDENCE.md)为来源，构造完整GATE_FENCE请求、帧、长度前缀及摘要。新tf_origin绑定原关闭、完整ACK、PreparationClosure、控制状态及安全代次；与gf_request构成双向延迟外键，安装后新增请求不能缺少原件。已有历史请求保留，不把其占位正文升级为完整证明。请求固定首次session、出口、控制原件、close ACK和目标修订/token，重复请求只查原，不刷新时刻或租约。

ACK必须具有同请求摘要、完整binding、reply、修订、token和同域安装时刻；必须存在原请求写尝试，effective不得早于该尝试或晚于接收。非规范字节、长度、序号、绑定错误均拒绝。失效或到期后正确ACK只存历史，不能采用。接收和采用分开，采用将完整FencedGateRecord与gf_commit原子保存；没有独立完整ACK不能制造新闸。调用完整原件读取器时必须在一致的数据库事务内读取控制来源。

关闭ACK撤回、准备核销失效或会话结束，都会取消新屏障的当前资格。采用前还复核当前控制、最新关闭、安全代次和期限。当前资格表示原屏障仍可作为后续OPEN来源，不单独表达现在能发送，也不替代租约校验。历史查原不重新安装屏障、不复活已失效资格。

验收从健康新域完整关闭、准备核销及混合恢复进入换闸。写完成观察、监督启动、身份与快照提供者仍为合成；没有真实IPC、物理屏障或设备验证。保留protected控制状态及四个最终发送阻断。OPEN_GATE、ReadyCommit、新grant、新命令/attempt、新域非空prepare与最终AdmissionSeal仍须继续贯通；旧闸多轮更新须有可验证的完整前序原件，不能回退占位BODY。

交付：[Schema](typed-gate-fence.schema.json)、[SQL](typed-gate-fence.sql)、[模型](typed_gate_fence_model.py)、[验收](check_typed_gate_fence.py)、[报告](typed-gate-fence-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_typed_gate_fence.py --check`；`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_typed_gate_fence.py --report`。
