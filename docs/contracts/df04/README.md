# DF04 局部存储约束参考

设计入口：[SQLite表契约、事务与恢复](../../rebirth-df04-storage-design.md)。

- `storage-probes.sql`只定义局部探针表，不是生产Schema或迁移脚本。
- `check_storage_probes.py`固定使用`:memory:`，检查十进制文本、复合FK、唯一约束、终态／资源分离、集合缺项、事务回滚和RETURNING边界。
- `reference-report.json`记录实际版本、输入hash及结果。所有检查成功后才覆盖报告；旧报告不证明改动后的输入。

在本目录运行：

```powershell
python check_storage_probes.py
```

参考SQLite由当前Python提供，不是冻结的产品引擎；当前3.50.4未满足产品WAL修复要求。本探针不启用WAL、不打开任何业务数据库，不能用于产品引擎批准。预期来自人工设计，未运行SDK严格输入层、真实驱动、并发、掉电、checkpoint、备份恢复或设备。

SP01—SP13中SP02展开10种非法词法，共22个独立参考检查。SP04明确证明STRICT可能做类型转换；SP09明确证明外键不能保证覆盖完整；SP11明确检查语句失败后仍需整事务回滚。这些通过结果不代表ST01—ST32运行验收通过。

探针对新活跃存储建议严格词法；draft.4已登记的尾部LF／-0接受差异仍未修订，旧机器文件保持不变。示意release_ref／resolution_ref仅验证非空配对，不验证证据真实性；生产必须按设计建立引用、来源及政策核验。
