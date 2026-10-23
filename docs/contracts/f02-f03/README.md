# F02／F03 内部协议与离线检查

本目录配合 [实施设计](../../rebirth-f02-f03-design.md)，公共 `1.0.0-draft.2` 保持不变。内部 `ipc/0.1.0-draft.1` 是实现评审资料，尚不是已验收的运行协议。没有服务、设备驱动、SQLite 表迁移或可执行部署。

| 文件 | 权威来源／用途 |
| --- | --- |
| [build_ipc.py](build_ipc.py)／[ipc.schema.json](ipc.schema.json) | 人工维护的 13 类 IPC 消息定义及生成物；引用已有 draft.2 CommandRequest／DispatchPermit／BarrierAck，不复制修改公共模型 |
| [build_cases.py](build_cases.py)／[cases.json](cases.json) | 独立人工编排的消息正反例、屏障账本／发送门控快照和有限符号轨迹；不从 Schema 自动生成“必然通过”答案 |
| [validate_ipc.py](validate_ipc.py) | 元校验、离线引用、生成漂移、结构、指定快照关系、人工顺序检查；不启动 IPC／SQLite／设备 |
| [validation-report.json](validation-report.json) | 本次实际检查数量、工具版本与输入 SHA-256；运行验收数明确为 0 |

内部 Schema 只覆盖信封与字段；身份鉴别、帧序列及重放缓存、真实账本、全资源冲突、当前 UTC／授权、最终写出口、进程监督和持久化必须由实现验证。动态参数／候选证据 payload 仍需相应能力 Schema 二次校验；示例 `scene-demo` 是合成目录 ID，不是实际厂商配置。

账本摘要固定为按 `permit_id` 升序排序的完整 `open_intents` 数组，经 RFC 8785 JCS 后 SHA-256，使用 `sha256:` 前缀；排序不删重复，重复许可直接拒绝。屏障静态校验检查覆盖集合、条目身份、当前及旧 worker、摘要、切点、目标版本／gate 修订、ACK 投影。`barriers` 的反例均结构合法，必须由静态跨字段检查拒绝。未知／在途仍可能与接管 effective 并存。

`dispatch_checks` 是给定可信门控快照后的比较测试，包含原请求摘要、设备／控制／期限绑定；其 `storage_healthy` 表示出口**已知**的健康状态，不代表主服务故障瞬间远端自动得知。符号轨迹另显式允许故障传播窗口内旧许可已发。它们不证明 F04 授权与 F05 时钟来源，不模拟线程竞态、socket 缓冲、SQLite 提交或 fsync，不是完整状态空间穷举。

复用上级目录已固定的验证依赖，不增加业务依赖：

```powershell
python docs/contracts/f02-f03/build_ipc.py
python docs/contracts/f02-f03/build_cases.py
python docs/contracts/f02-f03/validate_ipc.py --report
python docs/contracts/validate_contracts.py --report
git diff --check
```

命令在 Suite 根目录及独立验证环境运行。`--check` 防止手改生成物；只有全部通过才写新报告，失败时旧报告不能证明当前版本。父目录验证器不递归检查本目录，两个验证命令都必须运行；本目录报告包含公共 Schema 和实施设计摘要，公共 OpenAPI 并未随内部方案升版。

FT01—FT26 是待实现后执行的真实故障验收规范，列在实施设计中。当前静态正反例只覆盖其中可离线判断的部分，不能把用例数量相加宣称完成运行验收。
