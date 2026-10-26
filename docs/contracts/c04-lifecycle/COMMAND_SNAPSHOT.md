# 命令拒绝快照的持久封存与开放前态绑定

状态：内部候选，approved=false。仅设计与离线参考模型；业务服务及已批准的 draft.4／IPC 0.3 不变。

已知事实：取消受理、ordinary 切点及 all 切点分别推进设备拒绝水位。完整 Cut 原件已有结构和数据库关联验证，但一次投影没有持久身份；单靠成员数量也不能识别 ordinary 到 all 的变化。（来源：[拒绝账本](COMMAND_DENY.md)、[完整取消来源](CANCEL_SOURCE.md)。）

本候选在既有账本之上增加 ds_snapshot、ds_commit 两表。snapshot_id 是不可复用的存储查询键，IPC 正文继续使用现有 DenySnapshot，不增加第二套拒绝权威。设备、水位、成员数、JCS 正文和自摘要固定保存；正文最多 16 MiB，成员最多 4096，不截断。SQL 的 ds_frontier 按每命令最后一个已提交来源事件计算，accepted 仍未生成 Cut 时记为 pending；pending 必须阻止新快照封存，不能将它过滤成空集合。

新捕获在 BEGIN IMMEDIATE 内执行：读取当前账本并核对全部 Cut 原件，写 snapshot，再写 commit，读取原件与当前水位作回验，最后提交。双向延迟外键阻止半边提交，插入和 seal 两处检查设备水位、完整成员数和 pending。所有表不可变，开启 foreign_keys 和 recursive_triggers。SQL 计数不证明正文真实；read 必须严格解码、验证当前 IPC 类型、自摘要、canonical bytes、列和 audit，再按保存的历史水位从完整来源重建并比较正文。

同 ID 重试只查原，不能换设备、重采样或刷新水位。若 ordinary 快照之后推进到 all，历史 read 保留 ordinary 引用，current 返回 false；即使成员数量相同也不能继续用于开放。提交结果不确定时先按原 ID 查原：已提交返回原件，未提交可重新执行；不能为规避不确定性临时换 ID。临时数据库关闭重开和提交观察异常只覆盖这些离线行为，不等于真实进程强杀或掉电验证。

for_open 先调用已有运行拒绝快照与恢复前态组合，再使用恢复资源原件内的 command_snapshot_id 读取本库快照，核对当前水位、scope 和 device_id，返回 command_deny_snapshot。局部绑定检查不生成 OPEN、Ready 或最终许可。调用方必须在最终唯一 writer 的新写事务内重新读取所有准入来源；WAL 中已建立的读事务可能继续看到旧水位，此时 current=true 只描述旧快照时点。跨连接测试明确覆盖这一边界。

## 集成进展与剩余边界

已知事实：完整恢复夹具的设备和部分启动标识仍含点号，例如 dev.1；当前取消 IPC 的相应 Id 限制为字母、数字、下划线和连字符。旧恢复链能接受这些测试标识，取消来源校验会拒绝。另一个安装故障是存在 ep_request 时追加守卫的 SQL 缺少语句终止符；本轮已修正，并实际验证完整组合中该守卫存在。（来源：[恢复夹具](check_run_snapshot.py)、[监督来源夹具](check_supervisor_retirement_adoption.py)、[当前取消 Schema](cancel-source.schema.json)、[安装入口](cancel_source_model.py)。）

基于上述事实的处理方案已在[当前准备切点接线](PREPARED_CANCEL.md)落实：保持严格 Id 边界，在首次登记前统一合法标识，覆盖监督启动、出口、IPC 会话、命令受理和恢复原件；接通 cc_cut 与 pd_cut／pd_member／准备撤销／pd_cut_commit 的原子写集及历史重建。没有只补prepare_cut_id、删除守卫或放宽Schema，既存原件不替换点号或重算身份。

本文件对应的59项验收中，275表只验证安装与拒绝，非空普通／取消传输位于123表，局部OPEN绑定使用受控前态输入，其报告仍保持原验证范围。新增[准备切点报告](prepared-cancel-report.json)另行证明275表真实恢复数据库来源接入双非空拒绝快照，包含编码准备但未签发普通传输。两个报告不能互相扩大结论：完整OPEN发送及Ready、准备跨域退役核销、时间／授权完整来源、最终AdmissionSeal与真实提供者认证继续未完成。

## 验收与交付

- 零水位、pending 拒绝、非空 ordinary/all 历史查原、同数量推进、错设备重入。
- 两次逐写故障、漏写、原始 SQL 半边、不可变与 REPLACE、中途水位推进、提交观察丢失。
- 重算摘要后的错成员、错 Cut 摘要、错 scope 不能伪造来源；局部开放绑定拒绝错设备、错 scope 和旧快照。
- DELETE/WAL 临时磁盘库双连接 writer 排他、提交可见、关闭重开；WAL 旧视图与新写事务区分。
- 完整布局的安装守卫及旧标识拒绝；不将该负例计为完整接线成功。

交付：[SQL](command_snapshot.sql)、[模型](command_snapshot_model.py)、[验收](check_command_snapshot.py)、[报告](command-snapshot-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_command_snapshot.py --report`。报告绑定实际输入字节；没有运行真实网络、设备、服务、OS 观察或崩溃测试。
