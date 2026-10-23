# 21类面板结果的机器候选

[METHODS字段规范](METHODS.md)的下一步资料，仍未批准。`result.schema.json`是本批结果形状唯一源，根为离线`{method,value}`分派，绑定35个方法及21个View；port继续使用既有host.result及TypedValue，不增加另一层线上包络。生产Registry须分别绑定输入／结果Schema，不能让面板用自报schema_ref选择结果模型。

所有静态对象关闭额外字段并显式要求全部字段；缺失值使用有定义的null，不能省略后让GUI猜默认状态。数组有有限上限，超出时按方法分页或返回unavailable，不默默截断后标完整。Id允许旧领域使用的点号，但采用严格尾锚；Counter为最多20位规范十进制字符串，不转换为Number。Timestamp要求毫秒UTC及真实日历日期；Schema版本字符串目前按有限Id承载，完整SemVer及平台组合仍由SDK统一规则负责。

## 1. 两类动态值的边界

ObservationView.values使用`QualifiedValue={schema_ref,value}`。来源`integrity=complete|gap|unavailable`和授权投影`projection_status=complete|filtered`独立；允许完整来源被裁剪，也允许面板保留失步来源的最后观察，但它不产生自动化资格。values的每个字段仍须当前可读，Schema不是权限替代品。

DefinitionView.definition在本轮明确为`QualifiedDefinition={schema_ref,value}`：value保留原Definition的全部结构，再按批准的编辑投影Schema检查所有嵌套参数。它修正上一轮白名单未固定definition承载格式的缺口；保存时输入definition取其value，并保持原revision。完整读权不足时整个可编辑结果unavailable，不返回删字段或脱敏占位后仍可保存的定义。测试只提供一条合成rule的批准Schema，不宣称覆盖完整DSL的安全投影。

SchemaRef为`schema_id,definition,schema_digest`，格式与既有面板／快照引用一致。本批合成上下文将schema_id映射到完整Schema，实际计算`SHA-256(JCS(schema))`并核对definition；生产仍须通过当前批准的SchemaBundle，不能从结果中接收“approved=true”。本检查不联网解析ref。CapabilityView只返回批准表单Schema引用，不输出document或内部footprint。后续[BUNDLE](BUNDLE.md)固定definition为文档根$defs的具名入口，并提供四种交付消息及闭包检查；本结果夹具的根Schema映射仍是旧合成前提，未改为完整Bundle加载或实际渲染，不混称已联合验证。

字符串、reason_code和label_key合法不证明无秘密。设备名称、原因、业务文本仍须由受权白名单和受控显示词表产生；禁止将设备ERROR、异常堆栈或未知协议帧装进这些合法字符串。检查器保留一个`SYNTHETIC_UNREDACTED_TEXT`可通过合法display_label结构的反证探针，明确显示该限制；它不是允许生产泄露。检查器没有真实脱敏器或字段授权提供者，不能据结果Schema关闭这项运行验收。

## 2. 从旧对象到结果的具体映射

其余字段沿METHODS第4节，本轮补齐此前未落到具体类型的嵌套：

| 源／概念 | 候选映射与拒绝规则 |
| --- | --- |
| CommandRecord.completion | required→required_completion、achieved→achieved_completion；不传evidence_ids，完整证据由受限EvidencePage投影提供。succeeded必须达到要求，effect_status与实际达到等级相符 |
| CommandRecord.cancellation／resolution | status→cancellation_state；resolution只revision/resolved_outcome/resolved_at。unknown主终态不因后续resolved_outcome改变，资源clear另须权威释放证明，不由摘要自行推出 |
| ControlRecord.in_flight_command_ids／unresolved_command_ids | 各映射为可见ID集合＋has_hidden；只隐去身份，不隐去阻塞事实。gate ready要求没有pending或未决；正常控制过程中允许有在途命令，因此ready不等于idle |
| ControlOperation | effective_version来自该操作应用的版本，非当前最新版本；ready使用同一读取一致点的当前控制记录，并核对操作原epoch、目标version/mode/holder。旧epoch或旧holder的已生效操作不能借新控制记录显示ready。缺当前权威数据则unavailable，不用缓存猜true |
| TransferOffer | accepted必须有明确accept_operation_id，其他状态为null。旧对象缺该字段，下一版须新增持久关联；不能用时间最近的接管操作猜测，也不把accepted解释为effective |
| TargetApplication | service_id换为当前范围可见service_alias；status/applied_revision保持配对，未applied时revision为null。隐藏目标通过has_hidden表达，全局applied仍由完整权威目标集决定 |
| TransitionRecord | stage映射transition_summary.phase，保留validating/exit/transition/enter/committing/completed/failed/unknown；不凭展示phase提交business_state |
| GrantBinding | controller_id映射controller_alias、application_state映射status，保留pending/applied/revoking/revoked/indeterminate；不输出grant_revision／授权摘要或秘密。armed/running的完整目标集必须已applied，不能只检查可见子集 |
| RecoveryOperation | 保留7种state、原修订／提交修订／generation、新execution和有限command列表；committed_run_revision严格大于previous_run_revision。ready/running/completed只在完整目标集已applied时成立，仍不表示设备效果成功 |
| ResourceReleaseSummary | status直接取命令当前resource_status，policy_label为受控标签或null；某条evidence显示sent／ack不自动构成clear证据 |
| CheckResult／IndependenceProof | checks不含原details；passed为true时至少一项且每项passed。proof verdict只能取权威证明，unknown不能投影为independent；面板摘要不参与执行决策 |
| 面板容量 | 预算与计数仅当前PanelSession；预算缩小时可能已有使用量高于新预算，不能据此把历史计数清零或拒绝展示。限流及pressure仍由真实服务判定 |

ControlOperationView的ready是该操作目标是否仍是当前可用控制权的即时展示，ControlView.gate_state是当前控制闸门。两者和传输host.result.status=accepted完全不同。单次结果不承诺永久有效；下一条操作仍必须带expected_control／revision并在服务重新检查。

## 3. 离线参考检查

`check_results.py`载入固定本地公共Schema和21个手写结果夹具，对35方法逐一验证模型映射，再执行结构反例及有限上下文关联。所有权限、当前控制、完整目标集、证据归属、批准动态Schema和定义可见性均来自人工夹具。上下文不在面板结果中，也不是生产证明。

主要覆盖：全部View的额外字段拒绝；嵌套原始证据／actor／time_evidence泄漏；开放值秘密字段与Schema错摘要；unknown清理与结果不改写；完成等级；隐藏未决与在途正常状态；旧epoch／旧版本接管；转交关联；隐藏目标／grant；预检空集；恢复修订及proof verdict篡改。真实源到白名单的过滤过程、来源采样年龄、身份提供者、数据库并发和浏览器仍未执行。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_results.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_results.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-panel/check_results.py --check-report --staged
```

报告绑定本稿、结果Schema、人工用例、检查器、method-bindings及公共领域Schema共六输入。--check-report只核对原字节，不重跑用例；报告不在顶层旧十份清单内。结果Schema实际验证不等于过滤器已实现，也不证明合法字符串不含秘密。本批引用局部Schema不改变draft.4／IPC0.3或35方法用途。

## 4. 剩余同版交付

21类View形状已有机器候选，不能再将它们笼统列为“没有结果Schema”。SchemaBundle已有独立局部候选，后续[CHANNEL_V02](CHANNEL_V02.md)将完整消息、投影订阅和35方法的静态／动态Schema引用联接，并固定Result有限reason词表；本117例仍保留原根Schema合成上下文。每个字段的实际来源／授权提供者与完整语义注册、其余显示词表、HTTP状态错误与IPC／DDL联合归并，以及PMT01—PMT12实际运行仍须完成。恢复结果隐藏命令身份不删除未决影响，Schema合法不能让Seamer恢复自动化。全系统设计和C09仍未关闭。
