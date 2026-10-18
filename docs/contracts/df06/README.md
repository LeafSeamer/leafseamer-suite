# DF06 内部信任的有限参考资料

对应[IA01—IA06设计推荐](../../rebirth-df06-internal-trust-design.md)，候选`internal-trust/0.1.0-draft.1`。不修改已确认draft.4／IPC 0.3，不实现服务、证书、授权、数据库或设备操作。

`internal-trust.schema.json`是本目录唯一手写结构源，含7个局部附属模型：来源引用、域引用、采样请求／回执、待决消费、单对象读授权和实验预算。它们不是完整SourceRegistration／配对／HTTP响应或生产存储Schema；PendingCapture的配对快照等完整内部状态见设计稿，归并时须补齐。版本字符串仍需SDK的Version类型二次校验。

`examples.json`含人工正反预期；`check_reference_cases.py`先验证模型结构，再检查受限对象读取、来源绑定、因果年龄及串行一次消费。运行：

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/df06/check_reference_cases.py
```

使用上级锁定jsonschema校验环境；实际结果、工具版本和输入摘要在`reference-report.json`。报告只在全部预期通过后写出，旧报告不证明新输入。

合成上下文中的transport_authenticated、pairing_active、permission_present、source_approved、capture_attested、object_current等由夹具提供，**没有实现或验证这些前提真实成立**。expected digest也是合成预期，本轮只比较绑定，不计算JCS或证明来源真实性。SDK摘要投影须另有固定字节向量及完整实现。

一次消费只模拟三个串行原子步，不证明数据库CAS、网络重放或崩溃安全。公共日志策略仅有设计与IN28—IN30待运行验收，没有用allowlist参考函数冒充真实脱敏链路测试。

全部运行验收计数为零。结构／参考通过不关闭DF06、不批准CA或生产容量，也不证明公网入口隔离、TLS证书验证、实测采样新鲜度或防重放墓碑保留。
