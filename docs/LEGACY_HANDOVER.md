# 旧版交接记录

日期：2026-10-17。

- 旧仓已改名为 [ikenainanodesu/leafseamer-legacy](https://github.com/ikenainanodesu/leafseamer-legacy)，停止维护并在 README 指向新组织及 Suite；最终推送核验后已设为 GitHub 只读归档，未删除代码或历史。
- 最终旧版 main 提交：[`5d60491`](https://github.com/ikenainanodesu/leafseamer-legacy/commit/5d60491d7158f87fc27b564f510d321074aedac9)。已通过 Git 远端引用核对与本地提交一致。
- 最终旧版提交仅包含七份设计、README 和开发记录文档，旧业务代码及 MIT 许可保持原状；未推送 stash、全部 refs 或本地运行资料。
- 原工作区完整搬离新父目录保留，包含 Git 历史、原有未提交改动、被忽略配置、数据库、依赖、工具索引及嵌套工作树；嵌套 Git 路径已修复。搬移不代表已完成旧环境可运行性验证。
- 新父目录采用五个独立 Git 仓库，每仓有独立 origin 和 rebirth 分支，不建立父仓库或 Submodule。
- 新仓只初始化说明、设计和许可证；旧源码的分仓历史提取尚未执行，后续以路线图记录来源映射。
- 旧数据不自动迁移；未来仅提供人工迁移建议。未做数据库恢复演练、生产部署或真实设备控制。

## 许可来源

旧仓保持 MIT，新项目主许可 Apache-2.0。本仓两份 Rebirth 设计／审阅文档延续旧版最终提交并已调整链接与交接状态；原 MIT 声明保存在 [legacy-MIT.txt](../LICENSES/legacy-MIT.txt)。旧历史未被重新许可。
