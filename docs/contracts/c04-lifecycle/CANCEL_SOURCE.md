# 完整取消受理与两阶段切点来源

状态：内部候选，approved=false；设计、Schema与离线参考模型，未修改业务服务。

已知事实：当前IPC的取消Exit要求socket_instance_id，但ce_exit列及完整监督启动绑定不包含它。仅从目标BODY读取该值不能证明它属于登记出口；旧取消存储的占位BODY也不能作为完整Cut使用。（来源：[当前IPC](continuation-binding-ipc.schema.json)、[出口布局](../c08-controller/fence.sql)、[监督启动绑定](supervisor-retirement-adoption.schema.json)。）

本候选补cs_socket不可变登记，绑定当前scope、完整出口代次、socket实例和观察者Ref。登记必须早于该出口的普通packet、取消prepare或取消受理目标冻结；组合布局有ep_request时也禁止在该准备登记之后补录。首次登记与重复查原均核列投影和JCS摘要，重复ID不能换socket或观察者。观察者Ref只是待认证的来源引用，离线模型没有证明真实OS、socket或worker认证。

取消受理来源逐字段核对命名空间、请求摘要、原expected State、初始CancelOperation、CancelReceipt及取消Policy，派生CancellationBinding。历史查原不要求原授权仍有效，但不返回新的执行权限。原请求人可以不同于父命令原请求人；本模块核对的是已记录身份，不替代当前取消授权。初始operation对应受理后的State，receipt的accepted_state_ref对应CAS使用的受理前State，两者不能混用。

Cut及Policy从既有取消定义和当前公共命令/IPC类型图派生，CutTarget采用当前的完整传输类型。ordinary严格复用受理时冻结的完整原件与签发水位；all引用原ordinary Cut，纳入取消准备、全部取消传输及新增出口。目标、准备和许可均排序，旧普通集合不得变化。每个目标回显完整受理attempt ID集合，包含尚无packet的尝试；这是保守的候选选择，避免仅按已签发许可筛选而丢失准备，后续worker屏障必须按此集合验证。

原件读取核对普通许可与原intent、packet、自摘要、出口和重传根；取消传输核对执行、packet、准备关联与实际持久字节。读取结果证明候选数据库中的原件对应关系，不证明此前传输获得生产准入，也不证明设备已执行。切点封存通过既有cc_cut/target/member/commit写集，拒绝水位由上一轮钩子自动推进。重入只查原；关闭证据撤回不删除历史cut或拒绝墓碑，是否还能用于开放须另行检查。

snapshot_body按指定拒绝水位读取完整Cut并派生符合当前IPC的DenySnapshot正文；pending受理不能被过滤，历史ordinary不会被后来的all替换。正文尚未持久封存，不能把一次读取结果缓存成后续开放资格。当前有122项检查通过，覆盖逐写与漏写回滚、提交观察丢失、身份/原intent/时钟错配、重算摘要、实际取消字节错配、新出口、历史快照和必填字段；既有拒绝水位98项及关闭布局251项回归通过。测试只在首次登记前选择合法身份并生成一致摘要，不修改既存身份；旧占位正文明确拒绝。

本轮正例在119表取消布局叠加拒绝水位及socket绑定形成121表，覆盖非空普通许可、取消准备和取消许可。该来源验证不等同当前包含准备cut、IPC日志和监督认证的完整运行布局写入；capture在后者仍须接入对应准备核销写集，不能跳过原守卫。完整DenySnapshot封存、OPEN前态引用、当前授权/时间及最终AdmissionSeal继续待完成。

后续进展：[命令拒绝快照封存](COMMAND_SNAPSHOT.md)已增加持久身份、历史重建及局部OPEN绑定检查，补齐上述“尚无封存”的部分；完整运行布局的非空接线仍未完成。完整布局安装检查发现附加ep_request守卫缺SQL终止符，已修正；旧标识格式和准备cut写集仍须逐项接通，不能据安装成功宣布运行来源已验证。

交付：[Schema生成器](build_cancel_source.py)、[Schema](cancel-source.schema.json)、[SQL](cancel_source.sql)、[原件模型](cancel_source_model.py)、[验收](check_cancel_source.py)、[报告](cancel-source-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_cancel_source.py --report`。
