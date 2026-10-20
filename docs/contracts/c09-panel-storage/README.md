# 安装撤销与面板出口持久化候选

本稿补齐[HTTP PS6](../c09-panel-service/HTTP_STORAGE.md)和[面板 IPC](../c09-panel-ipc/IPC_GUARD.md)之间的安装 fanout、订阅出口及恢复关联，版本为 `panel-storage/0.1.0-draft.1`。这是待审阅设计和局部 SQLite 探针，不是生产迁移，不改已确认 draft.4／IPC 0.3，不启动业务实现。

## 1. 已知约束与本轮推荐

既有设计已要求：同 writer 串行处理注册、签发与撤销；安装撤销覆盖全部挂载和后台实例；设备 ACK 不能证明本地订阅已停止；关闭不取消已受理命令、不释放 holder、不恢复组织 run。依据见上述两份契约及[channel0.2](../c09-panel/CHANNEL_V02.md)。

推荐新增持久出口登记：任何能向面板释放数据或向设备发送的路径，必须先关联安装、owner、完整运行世代和出口种类，提交成功后才能启用。安装撤销先永久禁止当前安装实例新增 owner／出口／许可，再冻结所有 owner 与出口。不能先列在线进程，再关闭入口，否则并发注册可能落在清单之外。

SQLite 同时只允许一个写事务；`BEGIN IMMEDIATE` 可能返回 BUSY。外键需要逐连接开启，复合外键中的 NULL 可绕过父记录存在性检查，因此关联列须非空。触发器可用 RAISE 拒绝非法转换，但不证明权限或证据真实性。（依据：[SQLite事务](https://www.sqlite.org/lang_transaction.html)、[外键](https://www.sqlite.org/foreignkeys.html)、[触发器](https://www.sqlite.org/lang_createtrigger.html)。）

## 2. 记录、身份及索引

下表是生产归并要求；[storage-probes.sql](storage-probes.sql)只验证本轮结构约束。SQL 的短字符串 ID 是本地连接键，不替代右列完整契约身份。

| 记录 | 必需字段与关联 |
| --- | --- |
| installation | 不可复用 installation_id；authority_service_id、database_instance_id、installation_ref、approval_ref、artifact_digest；状态及拒绝下界。批准撤销按精确批准引用定位受影响安装，不能按包名含糊匹配 |
| owner | owner_id、installation_id、kind=panel/background、identity_jcs、selector_digest、state。panel identity 为 IPC panel_session 七元身份；background 为权威登记的 extension_instance_id 与批准／安装关联。复合 UNIQUE 与 FK 固定归属，两个页面不共用 owner |
| exit_registration | exit_id、owner_id、installation_id、kind、generation_jcs。local_projection/local_preview/local_queue/device_worker/background_worker 分开；所有出口，包括已离线旧世代，保留注册墓碑，不按当前在线状态过滤 |
| subscription | owner_id、subscription_id、exit_id、activation_ref、method、target_ref、state、sent、acked；身份在 owner 生命周期内不复用；exit 必须为同 owner 的 local_projection。生产计数用已校验十进制字符串，探针仅用小整数 |
| projection_frame | owner_id、subscription_id、sequence、frame_digest、状态。完整帧 JCS 摘要遵循 channel0.2；sent 是进入本地传输出口的高水位，不证明浏览器已收到；acked 只由精确投影 ACK 推进 |
| close_batch | operation_id、installation_id、phase、manifest_digest；关联原管理幂等记录、撤销原因和审计身份。一个安装实例只有一个安装拒绝批次，重复请求查原批次；不同内容仍 conflict |
| close_member | operation_id、owner_id、installation_id、selector_digest；捕获全部 owner，即使没有设备许可、已关闭或仍未激活。每个 panel 使用永久 selector，后台使用现有 extension selector |
| close_target | operation_id、exit_id、owner_id、installation_id、generation_jcs、kind、status；同批次同出口唯一，复合 FK 保证不能借另一安装／owner 的出口补数量 |
| close_evidence | operation_id、exit_id、owner_id、generation_jcs、kind、evidence_ref、evidence_digest；只追加。证明必须绑定原目标、原 selector、切点及受监督域；证据验证与目标状态提交同事务 |
| audit/outbox | 同事务写入批次事件与可靠保护任务；outbox 重送只安装拒绝／查询证据，不重发 DISPATCH 或原面板业务请求 |

索引至少覆盖 owner(installation_id)、exit_registration(owner_id,installation_id)、subscription(owner_id,state)、close_target(operation_id,status)。本地数据库固定 authority/database 身份；所有外部引用进入事务前及提交时复核完整身份。`identity_jcs`／`generation_jcs` 在本批 SQL 仅作不可变文本，生产必须按具名 Schema 校验并规范化；任意字符串相同不是身份认证。

generation_jcs 的生产对象包含 authority_boot_id、egress_instance_id、channel_id、clock_domain_id、descriptor_digest；设备出口另关联 controller_boot_id、worker_boot_id、ipc_session_id、device_id、device_session_id 和固定 IPC 账本摘要。重连必须新出口身份，旧出口不被覆盖。后台和面板共用物理 worker 时，按 owner／selector 建不同登记，执行仍共享设备唯一写出口，不能创建第二写进程绕接管。

## 3. 安装撤销事务及完整集合

1. 可信撤销请求抵达后，本地立即禁新受理／签发；若持久提交失败，内存保护保持且对外不报 durable 完成。没有持久拒绝记录的进程重启也必须先关闸恢复，不能从旧 active 自动开闸。
2. `BEGIN IMMEDIATE`，核对安装、批准及操作身份；active→revoking，并将该安装全部 owner 置 denied。已 denied 的 owner 同样列入，不能漏掉旧未决设备出口。
3. 建 building 批次；从权威表 `INSERT ... SELECT` 捕获所有 owner 和全部 exit_registration，包含无设备命令的页面与离线世代。三类本地出口在 owner 启用前登记；其空业务队列仍需证明该出口已关闭。确实没有 owner 的安装可捕获空集合，但必须有安装拒绝记录、审计和保护 outbox。
4. 同事务撤销 offered preview、拒绝尚未受理请求；保留 accepted、unknown 及领域命令／资源记录。订阅进入 closing，不生成新投影；取消已排队但未进入传输的数据。探针只执行订阅转换，preview/request 原子行为继续由 PS6 独立探针覆盖，不能声称已合成完整领域事务。
5. manifest 为 `{operation_id,installation_id,members,targets}` 的 JCS SHA256，带 `sha256:`；members 按 owner_id、targets 按 exit_id 排序，包含完整 selector 摘要和不可变世代。不是 IPC permit ledger_digest。冻结前分别对 owner、exit 两集合做双向差集和归属核验，再计算摘要；只核数量或重算遗漏后的摘要均不够。
6. 写 audit/outbox 后 building→frozen，提交。building 是事务内临时阶段，不对外发布；恢复见到持久 building 视为存储协议故障，保护关闭并核查。冻结后禁止追加、删除或改写 member/target 身份，目标状态与证据另表更新。

同 writer 下注册先提交则进入捕获集；撤销先提交则注册拒绝。普通页面关闭仍只按一个 owner 捕获；安装撤销不复活先前页面，也不能把页面关闭扩大到其他页面。重复安装批次复用原完整清单；迟到发现未登记出口说明不变量已破坏，保护整个受影响运行域并追加独立事故记录，不能偷偷改旧 manifest。

fanout 不对目标数做截断。完整集合在数据库中冻结，网络可分页交付，但分页 manifest／总数／摘要全部核齐前不能 acknowledged。注册时预留关闭记录与保护队列容量，普通配额耗尽不阻断关闭；超保留量是保护故障，不能丢目标。生产安装总量和保护预留预算仍待 C12 profile 冻结。

## 4. 订阅出口、屏障与证据提交

本地出口必须把“读取当前拒绝下界＋决定释放一个 frame”与“安装本地关闭屏障”串行化。若数据先进入传输，随后关闭不能撤回浏览器、WebSocket 或代理中的字节；关闭证据只证明该边界之后不再释放新的业务数据。可信宿主按已关闭挂载丢弃迟到帧。关闭不是已展示信息的远程擦除。

local_projection 关闭：停止新释放、取消未发送队列、退役对应订阅和 frame 窗口，保存原 sent/acked；释放窗口不推进 acked。closed/gap 墓碑不复活，旧投影 ACK 不增加新窗口。local_preview 与 local_queue 分别证明不会再释放确认展示或代理请求；不能用 projection ACK 代替另两类出口。面板收到 closed 不是本地关闭提交的前提，页面失联不阻止服务保护。

device_worker/background_worker 使用 IPC AUTH_FENCE 及其完整 permit coverage。已 transport_entered 不降级 not_sent，旧世代不能自证未发。将未知覆盖持久化可证明屏障已应用，但设备效果与资源未决继续独立存在；不能因 batch acknowledged 推出 ready。

目标状态 pending→indeterminate→acknowledged，pending也可直接acknowledged；超时只到indeterminate且不删除目标。证据类型为 local_closed、ipc_fence、process_terminated。最后一种只在可信监督器证明**原完整运行域／进程出口**已终止且无法恢复发送时使用；它不证明设备无副作用，也不抹掉传输缓冲中的已发数据。网络断开、PID不存在或新worker的空账本都不够。

接收证据时，在同一提交中完成：验证原operation／目标／世代／selector及证据资格→插入不可变证据→目标acknowledged→必要的本地订阅退役→audit/outbox。全部目标acknowledged且捕获集完整才可将batch标acknowledged；不能只查询 `NOT EXISTS pending`，因为indeterminate同样未完成。安装保持revoking／拒绝状态，后续disabled/removed按安装生命周期处理，不反向激活。

## 5. 崩溃恢复与故障验收

| 用例 | 注入／顺序 | 必须成立的结果 |
| --- | --- | --- |
| PSF01 | 注册提交后撤销／撤销提交后注册 | 前者被完整捕获；后者无新注册及任何外部启用 |
| PSF02 | 截去一个离线出口并重算摘要 | 集合差集拒绝冻结，不因摘要自洽通过 |
| PSF03 | 第二安装同名对象或另一页面出口混入 | 复合归属／完整身份拒绝，不能以相同计数替代 |
| PSF04 | 撤销事务在捕获后、outbox前失败 | SQL回滚无半批次；进程内保护不撤销；重启先关闸 |
| PSF05 | 提交后响应丢失 | 查询原批次及manifest，不再次扩集合或重发业务 |
| PSF06 | 出口已关闭、ACK收到但落库失败 | 仍pending／indeterminate；相同证据重送可落库，不提前成功 |
| PSF07 | 新进程提交旧出口local_closed／ipc_fence | 无原世代关联拒绝；独立监督器终止证明另核，不假称未发 |
| PSF08 | 已发送3帧仅确认1帧后关闭 | sent=3、acked=1保持，窗口退役；旧ACK不能伪造消费或复活 |
| PSF09 | 全部在线出口ACK，但离线出口未知 | batch未完成，目标保留并持续核对 |
| PSF10 | 零owner安装、或只有未激活页面 | 前者经安装拒绝与完整空集可完成；后者不可因无permit漏页 |
| PSF11 | 两authority安装关联／撤销传播中断 | 各自持久operation，父聚合保留未完成服务，不承诺跨库原子 |
| PSF12 | FULL／IOERR／BUSY、机器断电或监督器崩溃 | 保护保持，COMMIT未知按原身份查；真实WAL、磁盘及传播上界须运行取证 |

恢复读取所有 frozen／indeterminate目标及持久拒绝集合，先同步到新出口再允许其他安装的工作。旧出口只能靠原证据或可信终止证据核销，不能把boot_id改成新值“接续”。备份恢复产生新database_instance_id，旧批次作为历史、不迁移旧许可；需要维护恢复流程核对旧外部影响。

## 6. 本轮离线验证与剩余归并

[check_storage.py](check_storage.py)只创建 `:memory:` SQLite，在两个串行顺序、非法SQL变更、捕获遗漏、证据错绑、订阅窗口及事务主动异常下核对独立人工断言。没有服务器、网络、浏览器、设备、监督器或磁盘故障试验。局部SQL未实现真实证据验证、外部身份Schema、完整U20计数、锁竞争或全部领域同库事务。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-storage/check_storage.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel-storage/check_storage.py --check-report --staged
```

[参考报告](reference-report.json)记录51项内存检查，包含同页面两个投影出口的独立退役反例；只确认一个出口不能清空另一出口的窗口。夹具的owner／出口是局部构造，不验证完整挂载启用、三类本地出口齐备或真实设备许可。合成process_terminated正例只验证字段关联，不证明监督器证据可信。

报告绑定本文、SQL、检查脚本与三份衔接契约原字节；`--check-report`只比字节，不重跑。独立报告不属于顶层旧十份报告清单。完整生产DDL仍需合并 PS1—PS6、领域受理／恢复、授权与审计表；安装HTTP、订阅HTTP、字段权威、公共SDK与最终版本归并仍未完成。PSF01—PSF12的真实运行验收均未执行，本候选不关闭 C09 或阶段0。
