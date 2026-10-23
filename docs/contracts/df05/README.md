# DF05 发布清单候选资料

对应[发布设计 AF01—AF06](../../rebirth-df05-release-design.md)，版本 `native-release/0.1.0-draft.1`，推荐尚待审阅，不修改公共 draft.4／IPC 0.3。

- `release-manifest.schema.json`：本候选格式的唯一手写定义源；JSON Schema 2020-12，封闭对象及 ABI／动态依赖互斥分支。
- `examples.json`：合成基例与人工编写的 36 组正反预期；所有 hash、commit、版本及报告仅供格式检查，没有真实发布文件或签名。
- `validate_manifest.py`：Python 参考校验器，先结构后路径、角色、引用与兼容关系；不作为生产安装器。
- `reference-report.json`：实际离线结果、工具版本与输入摘要，`release_authorized=false`。

从仓库根执行 `docs/contracts/.venv/Scripts/python.exe docs/contracts/df05/validate_manifest.py`。使用上级 requirements-validation.lock.txt 中 jsonschema 及 RFC3339 校验依赖的锁定子集；不安装产品依赖。依赖实际版本写入报告。

Schema 不证明报告真实、平台批准、源 commit 存在、版本组合兼容或文件 hash 匹配。合成 stable 正例只证明字段关系，绝不构成生产晋级。报告的运行验收计数全为零。

本参考限制文件输入 4 MiB、单数组 4096 项、路径 256 字符；这是有界格式候选，不是正式下载／解压或容量 profile。大小按安全 JSON 整数，release_sequence／DB revision 用规范十进制字符串，不能转 Number 比较。严格尾锚拒绝末尾换行。

路径仅允许 ASCII 相对路径，结构拒绝穿越、绝对路径、反斜杠与百分号；语义拒绝保留名、尾点、重复和大小写折叠碰撞。实际解包链接、reparse、TOCTOU、压缩炸弹与磁盘配额另列 RA04／RA05／RA20，未由这些字符串用例证明。

归档／manifest 绑定、TUF 缓存事务及客户端互操作、真实签名、原生依赖加载、安装崩溃与断电恢复仍待实现后执行。工具链清单内部 Schema、发布批准记录与平台文件切换协议仍属设计缺口。
