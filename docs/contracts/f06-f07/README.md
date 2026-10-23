# F06／F07 候选契约与离线向量

版本 `f06-f07/0.1.0-draft.1`，对应 [OBS／依赖／恢复设计](../../rebirth-f06-f07-design.md)。公共 `1.0.0-draft.2`、F02 IPC 与 F04/F05 候选文件保持各自版本，不能把本目录新字段直接发送到旧接口。

- `build_contracts.py` 生成 `contracts.schema.json`：7 个封闭对象模型，引用公共 Id／Revision／Digest。Revision 和单调tick均使用十进制字符串，避免 JavaScript 精度丢失。
- `build_cases.py` 生成 `cases.json`：人工设定预期，含每模型正例、结构／跨字段反例、证据顺序／会话／截止、有限依赖足迹、失败继续条件及恢复预览消费向量。
- `validate_contracts.py` 检查 Schema 元结构、引用、格式、生成漂移、所列语义及固定预期；`validation-report.json` 保存输入摘要、工具版本和实际数量。

沿用上层[离线依赖说明](../README.md)，不安装业务依赖。运行：

```powershell
python docs/contracts/f06-f07/build_contracts.py
python docs/contracts/f06-f07/build_cases.py
python docs/contracts/f06-f07/validate_contracts.py --report
```

生成之后可直接运行最后一条，工具会先检查源与生成物一致。更改设计稿也需刷新报告，报告摘要包含它。

证明向量中的输入足迹／闭包／权威布尔字段是人工夹具；没有实现 DSL 分析器、来源验证、权限服务或运行中的资源别名解析。依赖判定忽略自报 verdict 并重算已给定集合；它只证明有限输入规则，不证明模块声明真实完整。恢复模型把事务视为一个原子步，枚举两位消费者的两种先后及幂等／失效情况，不是多线程、SQLite锁或跨服务屏障实验。四帧证据判定不包含实际OBS传输、图像或资源释放实现。

运行验收 OB01—OB16、AU01—AU20 均未执行。F06/F07 未因离线通过而关闭；真实版本组合、模块错误白名单、释放证据、并发／故障及全部旧功能交付仍待落实。
