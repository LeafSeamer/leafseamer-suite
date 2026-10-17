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

- [完整设计稿与 Q1—Q44 决策](docs/rebirth-design.md)
- [整体审阅及待落实事项](docs/rebirth-review.md)
- [路线图](docs/ROADMAP.md)
- [旧版交接记录](docs/LEGACY_HANDOVER.md)
- [开发记录](DEVELOPMENT_MEMO.md)

新版运行库采用 SQLite，支持指定 NTP 时间源，GUI 脱离 NodeCG；播出图文通过可选 NodeCG 桥接提供。以上为设计约束，尚未实现。五仓均使用 `rebirth` 作为实施准备分支。

旧版 [leafseamer-legacy](https://github.com/ikenainanodesu/leafseamer-legacy) 已停止维护，保留旧代码及 Git 历史。旧数据库不自动迁移，新版仅提供人工迁移建议。

新项目主许可为 [Apache-2.0](LICENSE)。从旧仓延续的设计文档保留其 MIT 声明，详见 [来源与许可说明](THIRD_PARTY_NOTICES.md)。
