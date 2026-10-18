# F04／F05 候选契约与离线边界向量

依据 [设计稿](../../rebirth-f04-f05-design.md)。本目录版本 `f04-f05/0.1.0-draft.1`；不修改已同意的公共 draft.2 或 F02 IPC .1，不提供认证服务、NTP 客户端或限流器实现。

| 文件 | 用途 |
| --- | --- |
| [build_contracts.py](build_contracts.py)、[contracts.schema.json](contracts.schema.json) | 13 个候选模型及人工定义源；按 `$defs/<名称>` 校验，根是模型库，不代表任意 JSON 已合法 |
| [simulation-profile.json](simulation-profile.json) | 实验预算权威值，未验证生产环境；purpose=simulation、验证证据为 null |
| [build_cases.py](build_cases.py)、[cases.json](cases.json) | 人工正反例、精确撤销作用域、快照时限、UTC 区间／事件年龄及容量决策向量 |
| [validate_contracts.py](validate_contracts.py) | 元校验、本地引用、生成漂移、跨字段检查与有限计算；不会联网、启动服务或创建数据库 |
| [validation-report.json](validation-report.json) | 实际离线结果、工具版本与输入摘要；运行验收执行数为 0 |

根模型引用父目录 draft.2 的 Id／Revision／Timestamp 等，校验器只注册本地文件，不抓取远程 Schema。秘密没有进入模型样例；WsTicketBinding 是服务端绑定记录，不是可用票据。来源、权限和 durable 字段必须由真实实现证明，Schema 通过不能给客户端自授 active／applied 的权力。

`AuthorizationBinding.origin` 将 human 限定为 manual；service/manual 表示受限外部程序，service/automation 必须有组织 grant 和 arm_generation。撤销作用域向量分别核对人员退出与独立组织自动化。credential/trust 失效不能靠数值修订复活；其他 selector 下界只拒绝旧修订，不自动授予新权限。

时间计算用整数与 Fraction 向外舍入，验证边界等号／未知误差／旧时钟域／恢复锁存。快照 TTL 从 challenge 发出时计算，不从收到响应时延长。容量向量假定已经鉴权，只验证有限决策表；没有执行 token bucket、线程调度、预留槽并发分配或实际吞吐。FA01—FA24、TB01—TB24 是设计稿中的未运行验收规范，不能与静态向量数量混算。

```powershell
python docs/contracts/f04-f05/build_contracts.py
python docs/contracts/f04-f05/build_cases.py
python docs/contracts/f04-f05/validate_contracts.py --report
```

在 Suite 根目录、上级已固定的独立验证依赖环境运行。未引入新业务依赖。父契约与 F02/F03 有各自验证命令；生成物不可独立手改，检查失败不能用旧报告证明新内容。报告包含设计文档和实验配置摘要，参数或正文变化后需要重验对应资料。

本轮仅提供候选字段 Schema；API 路径、鉴权方式和新增守卫／AUTH_FENCE／TIME_FENCE 的说明在设计稿，尚未合并为下一版完整 OpenAPI／IPC 消息包。该归并与客户端代码生成、登录／WS 浏览器、NTP 和容量故障验证仍是明确余项。
