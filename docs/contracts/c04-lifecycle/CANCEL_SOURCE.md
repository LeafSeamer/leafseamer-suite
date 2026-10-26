# 完整取消受理与两阶段切点来源

状态：内部候选，approved=false；设计、Schema与离线参考模型，未修改业务服务。

已知事实：当前IPC的取消Exit要求socket_instance_id，但ce_exit列及完整监督启动绑定不包含它。仅从目标BODY读取该值不能证明它属于登记出口；旧取消存储的占位BODY也不能作为完整Cut使用。（来源：[当前IPC](continuation-binding-ipc.schema.json)、[出口布局](../c08-controller/fence.sql)、[监督启动绑定](supervisor-retirement-adoption.schema.json)。）

本候选补cs_socket不可变登记，绑定当前scope、完整出口代次、socket实例和观察者Ref。登记必须早于该出口的普通packet、取消prepare或取消受理目标冻结；组合布局有ep_request时也禁止在该准备登记之后补录。首次登记与重复查原均核列投影和JCS摘要，重复ID不能换socket或观察者。观察者Ref只是待认证的来源引用，离线模型没有证明真实OS、socket或worker认证。

取消受理来源逐字段核对命名空间、请求摘要、原expected State、初始CancelOperation、CancelReceipt及取消Policy，派生CancellationBinding。历史查原不要求原授权仍有效，但不返回新的执行权限。原请求人可以不同于父命令原请求人；本模块核对的是已记录身份，不替代当前取消授权。初始operation对应受理后的State，receipt的accepted_state_ref对应CAS使用的受理前State，两者不能混用。

Cut及Policy从既有取消定义和当前公共命令/IPC类型图派生，CutTarget采用当前的完整传输类型。ordinary严格复用受理时冻结的完整原件与签发水位；all引用原ordinary Cut，纳入取消准备、全部取消传输及新增出口。目标、准备和许可均排序，旧普通集合不得变化。每个目标回显完整受理attempt ID集合，包含尚无packet的尝试；这是保守的候选选择，避免仅按已签发许可筛选而丢失准备，后续worker屏障必须按此集合验证。

原件读取核对普通许可与原intent、packet、自摘要、出口和重传根；取消传输核对执行、packet、准备关联与实际持久字节。读取结果证明候选数据库中的原件对应关系，不证明此前传输获得生产准入，也不证明设备已执行。切点封存通过既有cc_cut/target/member/commit写集，拒绝水位由上一轮钩子自动推进。重入只查原；关闭证据撤回不删除历史cut或拒绝墓碑，是否还能用于开放须另行检查。

snapshot_body按指定拒绝水位读取完整Cut并派生符合当前IPC的DenySnapshot正文；pending受理不能被过滤，历史ordinary不会被后来的all替换。它本身只负责投影，持久封存由[命令快照模块](COMMAND_SNAPSHOT.md)负责，不能把一次读取结果缓存成后续开放资格。基础来源有122项检查，覆盖逐写与漏写回滚、提交观察丢失、身份/原intent/时钟错配、重算摘要、实际取消字节错配、新出口、历史快照和必填字段。测试只在首次登记前选择合法身份并生成一致摘要，不修改既存身份；旧占位正文明确拒绝。

基础正例在119表取消布局叠加拒绝水位及socket绑定形成121表，覆盖非空普通许可、取消准备和取消许可。后续[当前布局接线](PREPARED_CANCEL.md)在capture中增加prepare_context及对应准备核销原子写集，并验证275表恢复链的非空准备／命令快照来源；不跳过原守卫。准备跨域退役核销、当前授权/时间及最终AdmissionSeal仍待完成，完整链尚未覆盖所有在途传输。

准备选择上下文及来源记录由CancelPrepareContext／CancelPrepareSource约束。历史读取绑定当时的控制变化与时钟域，跨域裸tick比较明确拒绝。完整布局安装的ep_request守卫终止符问题已经修复；新夹具在首次登记时选定合法标识，旧库不会隐式改名。

交付：[Schema生成器](build_cancel_source.py)、[Schema](cancel-source.schema.json)、[SQL](cancel_source.sql)、[原件模型](cancel_source_model.py)、[验收](check_cancel_source.py)、[报告](cancel-source-report.json)。复现：`docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_cancel_source.py --report`。
