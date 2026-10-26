# 设备授权状态与当前取证的原子采用

本候选落实[DF06第10节](../../rebirth-df06-internal-trust-design.md#10-设备授权语义状态短期取证与恢复)的存储映射，approved=false。它是独立九表SQLite子域与离线参考适配器，不是生产迁移，尚未并入完整Controller库，也不证明真实身份或设备保护完成。

## 表与完整关联

[DDL](device-authorization-storage.sql)包含以下九表。所有历史对象不可更新或删除，完整正文是JCS字节；[读取器](device_authorization_storage_model.py)核规范字节、摘要、物理列、原件引用及转换结果，SQL约束不替代来源真实性检查。

| 表 | 关键约束 |
| --- | --- |
| da_state | scope/device/revision唯一，每修订独立state_id；前驱到原状态；policy_selected必须有恢复授权消费；protected不允许伪造消费 |
| da_revalidation | 不可变完整RecoveryAuthorization，指原protected状态；当前Binding、待选Context与有效窗口按契约核验 |
| da_consumption | authorization_id主键、state_id唯一，双向关联采用状态；同一恢复授权不能消费两次 |
| da_evidence | 不可变Evidence，绑定State及首次封存commit；不能改写原窗口或同ID异内容 |
| da_head | 每scope/device唯一，保存完整State、可空Evidence、独立selection generation和commit；从原件重建完整期望值 |
| da_commit | 不可变操作请求、真实before／after、采样tick及父回执Ref；关联本次State／Evidence和seal |
| da_audit／da_outbox | 与commit同键、同正文，记录采用或保护意图；outbox不是已发送的AUTH_FENCE／CLOSE_GATE |
| da_seal | 同键引用commit、audit、outbox；commit反向延迟外键要求本事务完整封存 |

State到commit、State到消费以及head到commit的必要延迟外键允许同事务写齐，但不允许缺一侧后提交。head的SQL触发器禁止删除、跨设备改键、generation回退、同一State清空旧Evidence和重复指同一Evidence；切换State必须指原State前驱且清空当前Evidence。精确加1、类型与完整Ref一致由适配器重建验证；不声称任意绕过适配器的原始SQL都有同等语义保障。

## 唯一writer入口与四种写集

apply持有自己的BEGIN IMMEDIATE，拒绝已有读事务及未启用外键的连接。请求键为内部operation_id；完整规范request不含重试时的新now。相同键先核原请求、完整回执及历史转换，返回原结果；异内容冲突，响应丢失或后来到期不会重做操作。该内部键不替代对外主体RequestKey或当前读取授权。

| 操作 | 同事务写入顺序 |
| --- | --- |
| initialize | protected State、head、commit、audit、outbox、seal |
| revalidate | 恢复授权原件、State后继、一次消费、head、commit、audit、outbox、seal |
| select | 新Evidence、head、commit、audit、outbox、seal；不增加State修订 |
| protect | protected State后继、清空Evidence的head、commit、audit、outbox、seal |

提交前重新读取本次完整回执、父回执、State／Evidence／恢复授权／消费原件及实际head，必须与预期逐项相等。COMMIT前异常回滚全部九表；COMMIT后观察丢失保留实际已提交结果，重投只查原。这里的故障是主动异常／漏写，不是电源中断或I/O故障证明。

select和revalidate要求调用者期望的完整head与writer实际读到的head相等。当前head已有Evidence时只允许renewal，从库读取旧Evidence并同时核旧、新窗口；不能传previous=null或清空旧指针绕过到期条件。旧Evidence到期即拒绝select；该拒绝本身不伪称已完成设备保护，控制器必须继续提交protect并执行既有关闭路径，最终发送守卫在此期间也必须核旧窗口并拒绝派发。

首次取证也必须读取当前State消费的完整RecoveryAuthorization及消费行，核其原protected状态为State前驱、完整Ref与物理列一致，且Evidence的完整Binding与该恢复授权精确相等。不能因为“没有旧Evidence可比较”而省略worker／Controller／IPC／设备会话／时钟域绑定；后续刷新继续检查同一来源，换域须重新保护和恢复。

protect只对期望State Ref做CAS，允许同一State下的短期选择已更新，并在writer内捕获实际最新head。这样刷新先提交后，撤权仍能清空新选择；撤权先提交则刷新因State／head变化拒绝。若State本身已变，保护来源适配器必须重新核撤销对新状态的适用性，不得将一次CAS冲突解释为撤销完成或撤销无关。

旧回执可以在当前State已保护后查原，但不移动head，也不授权发送。恢复请求、策略lineage和Window仍由显式合成受信输入提供；本轮没有将客户端任意字段变成可信来源。真正的来源读取须接入当前writer事务，不能依赖事务开始前缓存的“已验证”布尔值。

## 验收与交付限制

[检查器](check_device_authorization_storage.py)覆盖四类写集及刷新路径，每一写入的主动故障和漏写均比较全九表；另外验证前后COMMIT观察、一次消费、原键查原、禁止清空当前指针、到期拒绝，以及本机DELETE／WAL双连接刷新竞争、撤权顺序与writer排他。[报告](device-authorization-storage-report.json)绑定完整输入。操作和时间来源均为合成，不把顺序交错称为多进程崩溃测试。

剩余实施验证：将本子域的外部Ref连接真实控制、身份、恢复及全部撤销来源；将保护outbox接入完整屏障与旧待发／在途核销；接入真实OPEN续约、ACK采用与Ready；确认当前选择的恢复／备份行为及实际驱动故障。生产业务、真实设备与批准API／IPC均未修改。
