# C11音频参数与协议候选

[音频候选设计AD01—AD07](../../rebirth-c11-audio-design.md)的附属资料。提供[DM3旧目录184行](dm3-legacy-catalog.json)、[编码审阅计划](dm3-codec-plan.json)及[177项参数profile](dm3-parameter-profile.json)，不是生产能力目录、运行配置或完成证据。

来源固定于LeafSeamer Legacy提交`5d60491d7158f87fc27b564f510d321074aedac9`，文件`bundles/mixer-control/extension/drivers/dm3-rcp-catalog.ts`。JSON中的source_blob_sha256绑定该提交的原始Git blob，source_line与raw_line保留位置及原文。只解析字段，不执行TypeScript；default_lexeme保留带引号形式，不将其转换成生产默认值。

本轮逐行比较184条：prminfo索引0—173、scninfo索引1000／1001／1010／1011、mtrinfo索引2000／2001／2002／2100／2101／2102，无缺项或重复index。原始122—144行没有OK前缀，仍保留原行。此比较只证明来源覆盖与转录一致，未验证任何设备值域、codec、参数单位、应答、权限、效果或恢复。

原文件注释引用Bitfocus Yamaha RCP资料；该来源链和旧MIT声明见[来源说明](../../../THIRD_PARTY_NOTICES.md)。既有注释中的实机核验不算本轮证据。后续QualifiedParameterDefinition必须逐条建立编码／语义、物理足迹、授权／秘密分类及型号验证，不能直接把本JSON加载到Controller发布写能力。

编码计划按来源摘要/index绑定8组，覆盖全部184项；只有旧174项为prminfo参数，不能与新profile的177参数直接按数量/序号比较。局部Schema强制候选状态；22个DMC正反例核对结构、唯一覆盖、类型分组及秘密投影，不运行RCP解析器。实际目录重新编号时按地址和协议/参数集版本关联；旧秘密index119不等于新profile的index119。

离线复验命令（在Suite根目录，使用既有契约虚拟环境）：

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c11-audio/check_codec_plan.py
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c11-audio/check_parameter_profile.py --report
```

第二条仅读取随仓交付的两个JSON文件，24项检查覆盖候选身份、禁止运行批准、字段闭合、整数与值域、唯一地址、连续序号及固定兼容差异。默认重跑检查；`--report`在全部通过后更新[参数报告](parameter-profile-report.json)，绑定两个JSON和检查器的原字节摘要。任何人可在本仓独立复验；这不是设备报文解析器或硬件验收。

新profile为177条、16条r/161条rw；174个旧参数地址均保留，154个序号改变，新增3项且MuteGrpCtrl/On标记由rw变为r。只证明两个候选文件之间的兼容关系，不证明当前设备状态或可写资格。所有AUDT01—AUDT72运行验收仍未执行；其中第11—13节的VB专用回复关联及WING源绑定/查询方案仅为设计，不在上述DM3检查器的覆盖范围。draft.4／IPC 0.3未改。

## 音频局部候选结构与关联

[audio-candidate.schema.json](audio-candidate.schema.json)是本批局部格式的唯一源，[人工正反例](audio-candidate-cases.json)覆盖75项；[检查器](check_audio_candidates.py)与[报告](audio-candidate-report.json)分别给出执行方法和输入绑定。详细边界见[音频设计第14节](../../rebirth-c11-audio-design.md#14-局部机器契约及跨项衔接修正)。这些对象不是已批准SDK：包络强制design_fixture_only/runtime_approved=false，RCP参数部分只对照prminfo，未展开全部184项资格、OSC/native、scene/meter或完整codec。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c11-audio/check_audio_candidates.py
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c11-audio/check_audio_candidates.py --check-report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c11-audio/check_audio_candidates.py --check-report --staged
```

默认命令重跑Schema、JCS摘要及关联预期；`--report`仅在全部通过后更新本目录报告。`--check-report`只比较报告声明的四个输入原字节，不重跑用例；`--staged`读取Git暂存区。此报告独立于顶层原十份报告检查清单，收尾需分别执行两者。夹具中的可信来源、采样资格、pending及中间态批准为人工前提；通过不证明真实权限、服务端取样、UDP排空、WING原子性、持久化或接管。
