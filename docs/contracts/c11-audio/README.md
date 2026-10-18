# C11音频静态来源资料

[音频候选设计AD01—AD07](../../rebirth-c11-audio-design.md)的附属资料。当前只提供[DM3旧目录184行](dm3-legacy-catalog.json)，不是生产能力目录、运行配置或完成证据。

来源固定于LeafSeamer Legacy提交`5d60491d7158f87fc27b564f510d321074aedac9`，文件`bundles/mixer-control/extension/drivers/dm3-rcp-catalog.ts`。JSON中的source_blob_sha256绑定该提交的原始Git blob，source_line与raw_line保留位置及原文。只解析字段，不执行TypeScript；default_lexeme保留带引号形式，不将其转换成生产默认值。

本轮逐行比较184条：prminfo索引0—173、scninfo索引1000／1001／1010／1011、mtrinfo索引2000／2001／2002／2100／2101／2102，无缺项或重复index。原始122—144行没有OK前缀，仍保留原行。此比较只证明来源覆盖与转录一致，未验证任何设备值域、codec、参数单位、应答、权限、效果或恢复。

原文件注释引用Bitfocus Yamaha RCP资料；该来源链和旧MIT声明见[来源说明](../../../THIRD_PARTY_NOTICES.md)。既有注释中的实机核验不算本轮证据。后续QualifiedParameterDefinition必须逐条建立编码／语义、物理足迹、授权／秘密分类及型号验证，不能直接把本JSON加载到Controller发布写能力。

本轮没有运行AUDT01—AUDT40设备验收；draft.4／IPC 0.3未改。
