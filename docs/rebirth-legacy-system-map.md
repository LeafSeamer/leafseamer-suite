# 旧自动化、图文、日志、备份与持久化映射

日期：2026-10-17。固定源码提交`5d60491d7158f87fc27b564f510d321074aedac9`；范围为seamer、graphics-package、logger-system、backup-system、database-postgresql五个bundle。以下区分源码事实和新版映射；未执行测试、数据库、浏览器或设备。与[设备8模块](rebirth-legacy-device-map.md)、[排期5模块](rebirth-legacy-schedule-map.md)合计18个bundle的来源盘点，不是全量设计／实现验收完成。

## 1. 自动化工作台

| ID | 固定源码事实 | 新版保留／替代 |
| --- | --- | --- |
| SY01 | 工作区卡片新增／编辑／删除，标题及actions数组存seamerCards，runSeamerCard执行；旧执行对actions.forEach发起，无全卡串行等待／汇总结果。[入口](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/extension/index.ts#L18) | GUI保留手动卡片；明确顺序／并行执行与逐步证据，按C04重建语义，不复制无等待群发。 |
| SY02 | 单卡JSON下载；拖入单个title/actions对象分配新ID；数组导入分支为空，不能说旧有批量导入。[导入](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/src/dashboard/App.tsx#L128)、[导出](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/src/dashboard/components/Card.tsx#L14) | 保留单卡交换，转为版本化可审阅定义，不携带运行授权／秘密；批量交换若新增须独立契约。 |
| SY03 | 两代触发均单条件→单动作＋delay＋enabled；旧动作Mixer电平／发送、VB预置、OBS场景／转场、ATEM宏／源，另有动态能力引用。[类型](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/src/types/seamer.types.ts#L7) | 保留所有动作映射；复杂AST／状态机／恢复为新版设计，不能说旧状态机已实现。 |
| SY04 | Mixer阈值穿越eq/gt/lt／mute变化、ATEM节目源变化、OBS场景／直播状态变化、VB路由变化；匹配后setTimeout，到时void执行，无已安排timer取消句柄。[trigger-manager](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/extension/trigger-manager.ts#L21) | C04/C05保留边沿用途，新增持久决定、有效来源、暂停／接管取消与延迟截止；停用不再留下游离动作。 |
| SY05 | provider注册／注销，拒重复integrationId、校验manifest，深拷贝状态；seamerIntegrations不持久。executeCapability仅检查provider后调用。[registry](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/extension/integration-registry.ts#L126) | SDK/API固定来源、目录批准及版本绑定，不能将NodeCG进程内provider当外部可信身份。 |
| SY06 | 参数目录有父子依赖／条件可见／引用有效性；引用默认留空，数字中间态undefined；卡片标题与能力引用合法才保存。[字段组件](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/seamer/src/dashboard/trigger/CapabilityFields.tsx#L17) | C10保留目录联动和非法输入反馈；隐藏字段的执行值仍受服务端Schema校验，不沿用仅UI验证。 |

## 2. NodeCG图文实际范围

| ID | 固定源码事实 | 兼容交付要求 |
| --- | --- | --- |
| GR01 | graphicsData为lowerThird{visible,line1,line2}和scoreboard{visible,homeScore,awayScore}。[数据模型](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/types/graphics.types.ts#L1) | C11固定这些字段的方向、版本和权限；不只提供一个通用URL输入框。 |
| GR02 | 原Dashboard两行文字即时编辑、字幕显隐、主客分数±1且UI下限0、比分显隐；直接替换Replicant分支，无命令网关。[编辑器](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/dashboard/graphics-control.tsx#L16) | 保留外部编辑器可达使用方式；桥接不能让Replicant写绕过新版控制授权，来源／回流与并发编辑须明确。 |
| GR03 | Lower Third订阅visible变化触发GSAP进出场，文字变化不重新播动画；动画参数_config未使用，固定−300px与时长。[渲染](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/graphics/lower-third.tsx#L23)、[动画](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/utils/lower-third-animations.ts#L4) | 保留既有动画行为；不把未使用配置声称成已有模板可配置能力。 |
| GR04 | Scoreboard隐藏时null，HOME/AWAY固定标签，无队名字段；两路图形均1920×1080。[比分](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/graphics/scoreboard.tsx#L12)、[交付](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/package.json#L4) | 兼容两路图形及排期展示，原编辑器／输出页／OBS浏览器源分别验收；不自研GUI渲染。 |
| GR05 | DataFetcher只有构造器／占位注释，无外部抓取；未发现业务消息、模板编辑器或播出完成回执。[占位实现](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/extension/data-fetcher.ts#L3) | 新桥消息及证据是新增设计；状态同步不能伪称观众收到像素。外部数据通过已批准数据源／桥接供给。 |

## 3. 日志、备份及NodeCG持久化

| ID | 固定源码事实 | 新版保留／替代 |
| --- | --- | --- |
| OP01 | 包装NodeCG info/warn/error，提取正文开头category；脱敏后近期500条Replicant、来源清单；按UTC日期文件，写／清理串行队列，失败stderr。[采集](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/logger-system/extension/log-capture.ts#L21)、[存储](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/logger-system/extension/storage.ts#L19) | 各服务日志及GUI统一查询保留；关键审计与普通日志失败政策分开，沿DF04／DF06。 |
| OP02 | 查看按来源、级别、文本筛选及统计；保留关闭/1h/6h/24h/7d/30d默认关闭，5分钟清理与设置变更清理；未发现导出UI。[查看](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/logger-system/src/dashboard/log-viewer.tsx#L63)、[配置](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/logger-system/extension/index.ts#L48) | 保留筛选／留存设置，按新容量profile定义“关闭清理”；导出如新增单列，不把日志文件存在当已有导出流程。 |
| OP03 | PostgreSQL audit_events，payload脱敏、command／时间／limit1—1000查询；audit异步失败stderr，库不可用查询返回空。[审计](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/logger-system/extension/audit-store.ts#L49) | SQLite关键审计事务化，不把“读取失败”变成“无记录”，GUI明确不可用。 |
| OP04 | 备份仅cfg/db逐文件读，跳符号链接；L0示例／README，L3秘密模式，其余db L2／其他L1，默认L0/L1。[范围](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/backup-system/extension/backup-manager.ts#L53)、[政策](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/backup-system/extension/backup-policy.ts#L10) | 保留分级选择／历史／进度反馈；重新定义五服务、模块、配置与数据库备份范围，不能复制活动.db逐文件当一致备份。 |
| OP05 | L3需明确includeSecrets及≥12字符独立口令，scrypt＋AES-256-GCM；manifest含path/level/size/hash/encrypted；ZIP以wx创建、失败清不完整产物。[加密政策](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/backup-system/extension/backup-policy.ts#L99) | 保留秘密显式选择与加密用途，精确KDF／格式／恢复工具另冻结；不把旧算法存在当新版备份已安全验收。 |
| OP06 | 无恢复／解密入口、无在线PG转储、无cfg/db一致事务；createBackup在归档完成后回ack。[消息入口](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/backup-system/extension/index.ts#L12) | DF04/Suite补完整恢复和演练；归档成功、备份可用、现场恢复安全分别取证。 |
| OP07 | database-postgresql为NodeCG预加载适配器；用户／角色／权限／identity／API key／Replicant及audit表；不是排期外部PG源。[预加载](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/database-postgresql/nodecg.config.js#L1)、[表与方法](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/database-postgresql/src/database-adapter.ts#L62) | 退出新版核心，Seamer/Controller用SQLite；可选NodeCG自身持久化按固定组合单独配置，不误删外部PG排期源。 |
| OP08 | Replicant按namespace/name upsert；缺连接配置时注册拒访问适配器防回退，正常pool max10。[保存与fail-closed](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/database-postgresql/src/database-adapter.ts#L388) | 不移植NodeCG内部用户表到新身份系统；旧数据作废，仅提供人工迁移建议，凭据／权限不得批量继承。 |

## 4. 测试边界与后续工作

旧仓存在[seamer-capability](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/seamer-capability.test.ts)、[backup-policy](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/backup-policy.test.ts)、[logger-security](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/logger-security.test.ts)、[postgresql-adapter](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/postgresql-adapter.test.ts)及需要实库的[postgresql-live](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/tests/postgresql-live.test.ts)。本轮均未运行；没有据此证明浏览器动画、完整归档恢复、真实数据库或新版业务。

C10仍需保留卡片／目录／输入校验／日志／备份交互并细化双语和错误状态；[C11 NodeCG候选](rebirth-c11-nodecg-design.md)已补三路旧图文（字幕、比分、排期）及原编辑器的桥接方向、回流去重、并发与权限，尚待审阅及机器归并；C12补实际备份范围／恢复包／部署组合。来源事实已定位，逐字段机器契约、交互与运行证据仍是独立门槛。
