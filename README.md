# LeafSeamer

> **施工中 / Work in progress。** 新版正在设计和准备阶段，尚无生产可用实现。当前仓库不提供可运行的直播系统或部署包。

LeafSeamer 是直播软硬件控制与自动化项目。各组件独立仓库、独立版本，Suite 负责总体设计、部署组合和整套验收；首期不使用强制 Submodule。

| 仓库 | 职责 |
| --- | --- |
| [leafseamer](https://github.com/LeafSeamer/leafseamer) | Seamer 规则、状态机和排期 |
| [leafseamer-controller](https://github.com/LeafSeamer/leafseamer-controller) | 独立设备控制、模块、接管和执行 |
| [leafseamer-gui](https://github.com/LeafSeamer/leafseamer-gui) | 统一网页操作台 |
| [leafseamer-sdk](https://github.com/LeafSeamer/leafseamer-sdk) | 公共契约、客户端与模块开发接口 |
| [leafseamer-suite](https://github.com/LeafSeamer/leafseamer-suite) | 总入口、设计、兼容组合、部署与验收 |

- [最新SDK成果交接：HTTP信封、类型客户端与投影验证](docs/contracts/sdk-wire-handoff/README.md)
- [完整设计稿与 Q1—Q72 决策](docs/rebirth-design.md)
- [全系统设计定稿收敛清单：具体缺口、审阅包与实施交接](docs/rebirth-design-closure.md)
- [当前归并审阅：受监督运行域、NTP 证据、公共 draft.4 与 IPC 0.3](docs/rebirth-draft4-review.md)
- [DF01：SDK 唯一契约源、固定生成链、JCS 与大整数](docs/rebirth-df01-sdk-freeze.md)
- [工具链收敛：精确候选、官方元数据与冻结验证步骤](docs/rebirth-toolchain-lock-design.md)
- [DF02：可信启动、进程纳管与运行域恢复](docs/rebirth-df02-runtime-design.md)
- [DF03：授时采集、源年龄、profile 批准与失效](docs/rebirth-df03-time-profile-design.md)
- [DF04：SQLite 表契约、事务、保留与恢复](docs/rebirth-df04-storage-design.md)
- [DF05：发布清单、信任根、升级与回退](docs/rebirth-df05-release-design.md)
- [DF06：内部身份、对象授权、来源证明与查询保护](docs/rebirth-df06-internal-trust-design.md)
- [C04：自动化表达式、发布绑定、触发仲裁与失败恢复](docs/rebirth-c04-automation-design.md)
- [C05：事件身份、快照交接、订阅 ACK 与容量保护](docs/rebirth-c05-event-sync-design.md)
- [C06：排期导入、日历、场次身份与逐步派发窗口](docs/rebirth-c06-schedule-design.md)
- [旧排期五模块能力映射与源码边界](docs/rebirth-legacy-schedule-map.md)
- [C09：模块生命周期、扩展授权与面板委托](docs/rebirth-c09-extension-design.md)
- [C10：GUI状态、接管转交、实时控制与完整编辑入口](docs/rebirth-c10-gui-design.md)
- [C11：NodeCG桥接、旧图文、编辑器与远端在途](docs/rebirth-c11-nodecg-design.md)
- [C11：OBS／ATEM全能力、传输与完成证据](docs/rebirth-c11-obs-atem-design.md)
- [C11：Mixer／DM3／WING／VB音频契约与184项来源清单](docs/rebirth-c11-audio-design.md)
- [C12：部署入口、只读输出、备份恢复与维护切换](docs/rebirth-c12-deployment-design.md)
- [旧设备八模块能力、型号与完成证据映射](docs/rebirth-legacy-device-map.md)
- [旧自动化、图文、日志、备份与持久化映射](docs/rebirth-legacy-system-map.md)
- [实施前技术选型：SDK、代码生成、认证、SQLite 与时钟](docs/rebirth-technology-selection.md)
- [平台冻结：Windows 运行域、NTP 误差界与原生制品](docs/rebirth-platform-freeze.md)
- [整体审阅及待落实事项](docs/rebirth-review.md)
- [实施前契约与验收交付清单](docs/rebirth-readiness.md)
- [首闭环 SDK/API 与执行契约草案](docs/rebirth-first-loop-contract.md)
- [可校验 Schema／OpenAPI 与正反例](docs/contracts/README.md)
- [F01—F07 进度及命令／接管边界审阅](docs/rebirth-contract-review.md)
- [F02／F03：IPC、唯一写出口、SQLite 与故障验收](docs/rebirth-f02-f03-design.md)
- [F04／F05：身份撤销、NTP 时间边界与容量保护](docs/rebirth-f04-f05-design.md)
- [F06／F07：OBS 完成证据、失败依赖证明与恢复并发](docs/rebirth-f06-f07-design.md)
- [路线图](docs/ROADMAP.md)
- [旧版交接记录](docs/LEGACY_HANDOVER.md)
- [开发记录](DEVELOPMENT_MEMO.md)

新版运行库采用 SQLite，支持指定 NTP 时间源，GUI 脱离 NodeCG；播出图文通过可选 NodeCG 桥接提供。以上为设计约束，尚未实现。五仓的 `rebirth` 已通过 merge commit 合入 `main`，后续在 `main` 推进设计与实施。

旧版 [leafseamer-legacy](https://github.com/ikenainanodesu/leafseamer-legacy) 已停止维护，保留旧代码及 Git 历史。旧数据库不自动迁移，新版仅提供人工迁移建议。

新项目主许可为 [Apache-2.0](LICENSE)。从旧仓延续的设计文档保留其 MIT 声明，详见 [来源与许可说明](THIRD_PARTY_NOTICES.md)。
