# 旧排期能力到新版的映射

日期：2026-10-17。范围仅为五个排期相关bundle，不代表18个bundle已全部盘点。已知事实来自Legacy固定提交`5d60491d7158f87fc27b564f510d321074aedac9`的源码；本轮没有运行旧测试、连接数据源或控制设备。新版归属和变化是[C06 SCH01—SCH07](rebirth-c06-schedule-design.md)待审阅推荐，不是已实现功能。

## 1. 固定源码事实与保留关系

下列链接均指向同一固定提交，文件名后的行号为本轮源码定位。未复制业务源码或改写旧许可。

| ID | 旧版源码已实现的能力与边界 | 新版保留／替代及验收定位 |
| --- | --- | --- |
| LS01 | `PlaylistItem`有source/externalId/revision、展示time、可空plannedAt、title/description/state/active、metadata/triggerMappings；无结束时间、时区、DST或重复规则。[模型11—35行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/src/types/schedule.types.ts#L11) | Seamer/SDK保留来源、展示和标量字段，补独立时间／日历模型；重复规则是已确认新版需求，不伪称旧有。CT02、CT08—CT20。 |
| LS02 | GUI本地新增／删除／编辑time/title/description、启停active；外部项只读。本地replace将plannedAt写null，因此显示时间不触发到期。[面板31—100、149—208行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/src/dashboard/schedule-panel.tsx#L31)、[服务88—110行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/extension/schedule-service.ts#L88) | GUI/Seamer保留编辑、启停、来源只读和删除确认；display_only与executable显式转换、外部项用版本化覆盖，不反写数据源。CT02、CT08、CT24—CT26。 |
| LS03 | preview含added/updated/removed/unchanged/errors；commit只替换同sourceId；rollback交换上一份内存快照，并非持久版本恢复。[导入63—125行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/extension/schedule-import.ts#L63) | Seamer保留差异预览及编辑恢复；SQLite不可变输入、草稿CAS与反向差异，回退不撤销设备效果。CT01、CT03、CT04、CT07。 |
| LS04 | 每秒检查active且plannedAt<=now；内存Set按item.id+revision防重，没有迟到截止，重启清空。[服务44—45、84—85、157—172行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/extension/schedule-service.ts#L44)、[到期128—150行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/extension/schedule-import.ts#L128) | 保留到期触发用途，替换为持久逻辑场次身份、批准窗口及资格锁存；不继承无限迟到或revision变化重新触发。CT18、CT27—CT39。 |
| LS05 | 核心字段变化可匹配from/to，metadata优先于顶层，仅原有项生成变化。本地GUI及两个转换器写空metadata/mappings，不能声称现有GUI已完整配置。[变化逻辑153—197行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/extension/schedule-import.ts#L153) | SDK/Seamer保留标量from/to；新映射显式字段路径与类型，不沿用隐式同名遮蔽。独立批准观察绑定，首次／重同步不造边沿；草稿不触发。CT41及C05 EV用例。 |
| LS06 | seamer-adapter-schedule仅有item.due、field.changed，无动作；支持来源／节目／字段及from/to筛选、目录可读名称。监听只取scheduleEvents[0]，同批其余事件不逐项交付。[manifest](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer-adapter-schedule/extension/manifest.ts#L3)、[入口26—39行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer-adapter-schedule/extension/index.ts#L26)、[目录](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer-adapter-schedule/extension/presentation.ts#L13) | 原生Seamer排期＋数据观察提供等价触发及目录，沿C05持久来源序号逐条摄取，不能复制“只取第一条”。排期不是新增设备控制模块。CT38、CT41；全批交付与gap用C05验收。 |
| LS07 | data-sync-service以只读OAuth启动读取并60秒轮询Sheet1!A1:E10；发布sheetData/syncStatus；空结果保留旧数据，失败记状态。[Google客户端24—97行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/data-sync-service/extension/google-sheets-client.ts#L24) | Seamer数据源适配保留只读采集、同步状态与轮询；允许受限范围映射并持久捕获，空源差异显式确认。NodeCG兼容投影另定，不暴露凭据。CT04、CT05、CT40。 |
| LS08 | Sheet转换器认8类表头，缺表头以前4列回退；无标题跳过，缺externalid列用行号，Date.parse失败为null；收到sheet1自动commit。采集只5列，不证明8列同时端到端可用。[转换13—80行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-adapter-google-sheets/extension/transform.ts#L13)、[入口24—35行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-adapter-google-sheets/extension/index.ts#L24) | 保留可映射列与展示，稳定key／时区必须明确；无标题等非法行给逐行诊断，不能静默跳过后声称完整导入。自动采集只到草稿，观察触发单独批准。CT01—CT05、CT08、CT24、CT41。 |
| LS09 | PG读取external_id/time/title/description/state/active/planned_at/revision；sourceId/name、query、env连接、轮询及timeout可配；至少5秒轮询、每次自动commit，失败保留旧数据。[转换](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-adapter-postgresql/extension/transform.ts#L6)、[入口21—88行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-adapter-postgresql/extension/index.ts#L21) | PostgreSQL继续作为外部只读源；运行库SQLite不排斥它。查询模板、稳定主键、秘密引用、固定快照与预算；只入草稿。CT03、CT04、CT06、CT24。 |
| LS10 | PG限制SELECT开头，拒分号／注释／INTO／行锁；BEGIN TRANSACTION READ ONLY，statement_timeout夹1—60秒，失败ROLLBACK并释放连接。[只读查询14—52行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-adapter-postgresql/extension/read-only-query.ts#L14) | 保留只读与超时保护；提升为批准视图／模板和REPEATABLE READ固定事务，不能仅靠正则声称任意SQL无副作用。CT06及配置权限验收。 |
| LS11 | NodeCG图形为1920×1080，显示所有active项time/title/description；标题UPCOMING但实际不只筛未来。[展示17—75行](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/src/graphics/schedule-display.tsx#L17) | C11兼容包保留展示数据及旧版筛选行为；若增加“仅未来”作为新配置须显式选择，不悄然改变旧画面。新版GUI独立，图文渲染不自研。CT40、A21。 |

## 2. 已发现的行为缺口

以下是基于源码的分析，不是现场事故或已通过复现的结论：

- 两个转换器可用采集时间生成默认revision，而到期去重含revision；轮询可能让同一逻辑节目再次满足到期条件。新版身份不得依赖这种revision。
- 旧scheduleEvents最多100条且未持久化，适配器只消费首条；不能用旧轮询测试证明全事件交付。
- 两个外部适配器直接commit，没有发布／激活、在途保护或显式采集互斥；新版分离数据观察和计划编辑，旧响应不能覆盖较新捕获。
- 回滚内存快照、重启丢去重、Date.parse默认解释及无截止都不是新版安全保证；它们的编辑／展示用途保留，执行语义按已确认Q58—Q60替代。

## 3. 现存测试与后续证据

固定提交存在以下测试，本轮未运行，不能记为新版通过：

- [schedule-import.test.ts](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/schedule-import.test.ts)：重复ID、同源替换、进程内去重、字段变化与无效时间。
- [schedule-adapters.test.ts](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/schedule-adapters.test.ts)：转换、两类trigger、模拟只读事务／失败回滚；不是实际PG连接试验。
- [device-presentations.test.ts](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/device-presentations.test.ts)：排期目录名称及旧数据回退。
- [dashboard-ui-operations.test.ts](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/dashboard-ui-operations.test.ts)：本地来源、提交字段和删除交互的AST检查；不是浏览器操作验收。

剩余交付：C06候选归并、C05字段观察来源和事件完整性、C10编辑／失败交互、C11具体NodeCG字段投影与兼容包，以及上述LS01—LS11逐项运行证据。其余13个bundle的来源盘点现见[设备8模块](rebirth-legacy-device-map.md)与[系统5模块](rebirth-legacy-system-map.md)；全部能力仍需逐字段／型号／证据冻结，不能由来源盘点推断全部功能验收通过。
