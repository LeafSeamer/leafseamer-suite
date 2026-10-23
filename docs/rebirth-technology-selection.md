# 实施前技术选型：SDK、认证、SQLite 与时钟

- 日期：2026-10-17；范围：设计推荐与验证计划，未修改业务代码、安装业务依赖或执行服务／设备试验。
- 已确认：用户同意公共 `1.0.0-draft.3`／`ipc/0.2.0-draft.1` 归并基线；对应 [整体审阅](rebirth-draft3-review.md) 与 [机器契约](contracts/draft3/README.md)。确认基线不代表正式稳定版或运行验收通过。
- 后续确认：用户已同意 TS01—TS05 推荐方案。确认的是技术方向，精确制品和运行验收仍未冻结；不追记为 Q 系列决策。下文保留选型依据，网页、主分支和包版本声明不能代替实际发布产物检验。
- 最新细化：[NF01—NF03](rebirth-platform-freeze.md)已获同意，[draft.4／IPC 0.3](rebirth-draft4-review.md)显式修订宿主启动身份依赖并归并NTP证据。下文TS05的旧host_boot_id建域方式仅为选型历史，当前采用受监督运行域；PF01—PF18及原生发布组合仍未验收。
- 后续DF01：[具体冻结推荐](rebirth-df01-sdk-freeze.md)因openapi-typescript7.13.0的^5.x peer约束，将生成链候选修正为TypeScript5.9.3；下文6.0为早期试验建议，不是已验证组合。D1—D6仍待确认，SDK源和机器协议尚未迁移。

## 1. 推荐决策与依赖

| 编号 | 推荐方案 | 主要理由与代价 | 冻结门槛 |
| --- | --- | --- | --- |
| TS01 | 首方 SDK 使用 TypeScript，服务运行基线 Node.js 24 LTS；发布 ESM JavaScript 与声明文件 | GUI／Seamer／Controller 共用契约；不把浏览器 SDK 捆绑原生依赖。增加少量平台适配代码 | 编译器／Node 精确版本、浏览器产物、双平台安装验证 |
| TS02 | Schema-first；openapi-typescript 7.x＋openapi-fetch；Ajv 8 的 2020-12 实现＋ajv-formats，构建时生成校验函数 | 类型生成与运行时校验职责分开；HTTP、事件、IPC 共用模型源 | 既有正反例、条件约束、数值及摘要测试；生成可重复、语义不得宽松化 |
| TS03 | 保持 F04 不透明会话／定向令牌；node-argon2＋node:crypto＋node:tls，cookie 负责 Cookie 编解码 | 保留精确撤销和独立 Controller；不用长期 JWT 替代权威状态。不引入第六个必需身份服务 | 密码成本、轮换并发、CSRF、配对撤销、秘密保管与认证时钟验证 |
| TS04 | better-sqlite3＋专用存储线程；关键事务使用显式 SQL，不以 ORM 隐藏提交边界 | 可直接检查事务状态与控制备份；同步驱动必须隔离，不得阻塞最终写出口 | 驱动／实际引擎／编译选项固定；WAL/FULL、故障与恢复验证 |
| TS05 | 单调钟用薄层 Node-API 原生适配；NTP 优先宿主 chrony／W32Time 质量适配 | 不用普通计时器或单个 SNTP offset 冒充共享时钟和可信 UTC | 宿主启动身份、namespace、休眠、误差界与两平台验证；缺证明不开放相关能力 |

TS01—TS05 已整体获准；具体补丁版本／原生产物仍需验证后冻结。首期不同时维护 Python／Go／Rust 官方客户端；语言中立的 OpenAPI／JSON Schema 和协议示例仍交付，第三方可自行适配。是否增加其他首方语言取决于实际模块需求及契约测试覆盖。

## 2. SDK 语言与生成链

### 2.1 已核对事实

Node 官方发布页当前列 24 为 LTS、26 为 Current，并建议生产使用 LTS。TypeScript 6.0 已有官方版本说明。openapi-typescript 明确支持 OpenAPI 3.0／3.1，输出不含运行时校验；openapi-fetch 消费其类型。Ajv 的 2020-12 使用专门入口，支持构建时生成 standalone 校验函数。（来源：[Node 发布表](https://nodejs.org/en/about/previous-releases)、[TypeScript 6.0](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)、[类型生成器](https://openapi-ts.dev/introduction)、[HTTP 客户端](https://openapi-ts.dev/openapi-fetch/)、[Ajv Schema](https://ajv.js.org/json-schema.html)、[standalone](https://ajv.js.org/standalone.html)）

### 2.2 项目推荐

首轮工具验证从 TypeScript 6.0 稳定补丁线、Node 24 LTS 开始；这是保守兼容起点，不声称 6.0 是最新编译器。发布 JS＋`.d.ts`，服务 ESM／NodeNext，浏览器独立入口，禁止因 SDK import 拉入 SQLite、密码库或原生时钟。配置启用 strict、exactOptionalPropertyTypes、noUncheckedIndexedAccess；声明中避免 Node 私有类型泄漏到浏览器。CJS 消费暂不作为首期承诺，需要时通过独立消费测试后加入。

推荐保留五个逻辑包边界：contracts、client、controller-module、seamer-provider、testkit；正式 npm scope／包名另行核验。认证实现留在 Controller，存储实现留在各服务，平台适配作为内部运行包；SDK 仅定义必要接口与测试替身。纯浏览器 client 不依赖 Node 运行时。

生成方向固定为：

```text
SDK 仓库的版本化 JSON Schema 2020-12 + 端点描述
  ├─ 公共模型 + Controller/Seamer OpenAPI 3.1.1
  ├─ 内部 IPC/事件 Schema（独立协议版本）
  ├─ openapi-typescript → HTTP 类型、模型声明
  └─ Ajv2020 + ajv-formats → 构建时 standalone 校验器
openapi-fetch + 少量手写门面 → HTTP client
手写有界状态机 + 生成的消息类型/校验器 → WS/IPC 传输适配
```

1. SDK正式源从Suite当前生成结果和声明提取，消除对历史候选Python脚本的运行／发布依赖。先证明与当前draft.4逐模型语义相等，再设为唯一编辑源；Suite通过精确版本及摘要引用。现有文档生成脚本不等于产品实现语言。
2. OpenAPI 的服务模型均由同一模型源投影；IPC-only 模型可生成内部 components-only OpenAPI 投影供同一类型生成器使用，**不增加虚假 HTTP 路由、不替换 IPC Schema**。若条件类型无法等价表达，允许 TS 类型较宽，但必须标明并以原 Schema 运行时拒绝非法值，禁止倒推宽松 TS 类型覆盖原 Schema。
3. Ajv2020 使用严格模式；coerceTypes、useDefaults、removeAdditional 均关闭。对 2020-12 条件写法产生的 strict 警告逐项修正或登记精确例外，不能整体关严格模式。启用已声明格式；固定外部 `$ref` 为本地产物，运行时不网络取 Schema。readOnly／writeOnly 只是注解，输入与输出方向仍需单独约束和服务端权限检查。
4. 浏览器仅运行预编译函数，不要求 unsafe-eval；不接受第三方任意 Schema 当代码编译。模块注册 Schema 的体积、深度、正则和编译成本纳入容量审批。用户输入无条件转型为 T、只校验请求不校验响应，都不算契约验证。
5. tick 等十进制字符串在 wire 上保持字符串；内部计算用 bigint，禁止 Number 往返损失。JSON 数字仅接受协议允许的安全范围；JCS 使用独立 RFC 8785 实现和既有固定向量，不让生成器重排业务数组或重算不同投影的摘要。
6. 客户端默认不重试写请求、不自动生成新幂等键、不跟随重定向重放带凭据写入。Abort／超时只表示客户端停止等待，不表示设备未执行；通过原 request／operation 查询。刷新凭据不自动重发此前不确定的 mutation。202、GUARD_ACK、ready 不被包装成设备成功。
7. WS 重连只恢复允许的订阅；新连接新票据，丢首次票据响应不能用同键索要第二次 secret。IPC 只生成消息形状，不生成重试、持久化或发送权限。只读重试也受次数、退避、总期限限制。

本轮不选择以 Zod／装饰器反向生成全套 Schema，也不选择生成整套服务端业务骨架；理由是避免现有 if/then、完整 coverage、权威证据与有限许可语义在转换中丢失。不是这些工具普遍不可用，而是本项目原 Schema 已是确认基线。

## 3. 认证、密码与秘密保管

### 3.1 已核对事实

node-argon2 提供 Argon2id、PHC 格式的 hash／verify，公开列出 Windows x64 与 Linux 预构建支持；这不等于已验证本项目的 Windows 11／Ubuntu 24.04。Node crypto 提供 CSPRNG、摘要和固定时间比较；Node TLS 使用 OpenSSL。cookie 提供 Cookie 编解码，不承担会话撤销。OWASP 建议 Argon2id 并给出成本下限。（来源：[node-argon2](https://github.com/ranisalt/node-argon2)、[Node crypto](https://nodejs.org/docs/latest-v24.x/api/crypto.html)、[Node 24 TLS](https://raw.githubusercontent.com/nodejs/node/v24.22.0/doc/api/tls.md)、[cookie](https://github.com/jshttp/cookie)、[OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)）

Windows DPAPI 通常绑定同一登录凭据及机器；systemd credentials 提供服务凭据装载机制。二者不是可随数据库备份自动跨机恢复的通用保险箱。（来源：[Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)、[systemd credentials](https://systemd.io/CREDENTIALS/)）

### 3.2 项目推荐

认证采用 F04 专用状态模块，密码／随机数／TLS 交给上述库。通用身份框架只在能保持原 F04 精确撤销、目标 challenge 起算 TTL 和可靠 receipt 时才可替换；本轮不引入 OAuth/OIDC 服务器，也不宣称自己实现了这些标准。此选择仍需要针对状态模块的专项安全审阅，不能用“使用成熟库”代替审阅。

- 密码首个实验参数建议 Argon2id、m=65536 KiB、t=3、p=1、16 字节独立随机盐、32 字节输出；均显式配置并保存 PHC 参数。先测最低配置机器的登录 P95、峰值内存和并发；该值是实验起点，不是生产批准。密码工作放在独立有界执行池，不与设备出口、存储或其他保护通道争用无限任务。拒绝超大输入及不受控成本 PHC；升级只在成功认证后按策略 rehash。
- 会话、定向 token、WS 票据使用至少 32 字节 CSPRNG 随机秘密，分类型编码；服务端保存带类型域分隔的 SHA-256 验证值及身份、audience、期限和撤销引用。高熵 token 不用密码 KDF，以免每次请求产生昂贵计算；禁止保存明文长凭据用于重复返回。
- cookie 库只做序列化。沿用 Secure／HttpOnly／SameSite=Strict／Path=/auth，固定部署 Origin，CSRF 使用会话绑定随机值及恒定时间校验。拒绝含重复认证 Cookie、畸形 Authorization 的歧义请求；不凭客户端转发头重建可信 Origin。首期不使用要求 Path=/ 的 `__Host-` 前缀覆盖已定 /auth 路径。
- 刷新轮换、复用检测、撤销事务及丢响应语义沿用 F04；增加浏览器多标签页协调测试，不能把正常并发刷新变成不受控延长旧凭据的理由。退出不自动撤销独立组织 grant，也不释放持久手动接管。
- 服务间直接终止 mTLS 于服务受控入口，校验 CA／对端身份／用途与有效期，并将证书身份映射到配对记录及当前授权。公网 Nginx 入口不提供伪造内部 mTLS 身份的 header 旁路。若部署要求代理终止内部 mTLS，另审可信代理协议，不能默认为等价。
- 服务证书、设备密码与加密主密钥使用 SecretStore 接口：Windows 首选专用服务身份下 DPAPI；Linux 原生首选 systemd credentials；容器首选受权限限制的只读秘密文件挂载。运行库保存 secret_ref，受控加密设备凭据可用 node:crypto 的 AEAD，主密钥不放同库。原生封装、密钥轮换和跨机重配需单独验证；不把加密算法、CA 签发或 DPAPI 重新实现。
- TLS 证书有效期按系统认证时间验证；业务 NTP offset 无权延长它。认证时间异常暂停新凭据签发／相关授权，已有许可仍受不可延长的单调截止约束。

## 4. SQLite 驱动与存储边界

### 4.1 已核对事实

better-sqlite3 提供同步调用、inTransaction、显式 SQL 和增量 backup；文档禁止把 async 函数放入其自动 transaction 包装。`v13.0.3` 标签文档列出 SQLite 3.53.4，默认 `SQLITE_DEFAULT_WAL_SYNCHRONOUS=1`，并省略 progress callback；不能假定任意 SQL 都可及时取消。Node 24 的 node:sqlite 已有事务状态和 backup，但当前文档仍标记 release candidate，不能以“没有备份 API”为理由排除它。（来源：[驱动 API](https://github.com/WiseLibs/better-sqlite3/blob/master/docs/api.md)、[固定标签编译配置](https://github.com/WiseLibs/better-sqlite3/blob/v13.0.3/docs/compilation.md)、[Node SQLite](https://nodejs.org/download/release/latest-v24.x/docs/api/sqlite.html)）

SQLite 官方说明 WAL-reset 缺陷在 3.51.3 及后续修复，另有 3.44.6／3.50.7 回移植；这是已知缺陷底线，不是所有未来版本都自动获准。（来源：[SQLite WAL 第 11 节](https://www.sqlite.org/wal.html)）

### 4.2 项目推荐

优先验证 better-sqlite3 13.0.3／其宣称的 SQLite 3.53.4 组合。正式冻结仍须对下载的包、各平台 `.node` 实际执行 `sqlite_version()`、`sqlite_source_id()` 和 `compile_options`，记录摘要、Node ABI／Node-API、VFS／文件系统、编译器及依赖许可；网页版本号不是实测证据。node:sqlite 留作后续替换候选，不在首期维护两种可热切换驱动；不选远端 libSQL、浏览器 WASM 或 DuckDB 替换已定本地关键库。

每服务一个本地关键库，一个专用 writer 线程及有界队列，读连接独立且只读。连接只在所属线程使用；设备模块不持有连接。存储线程之外的服务／最终出口负责保护期限，SQL 卡住时无法及时确认的 intent 一律不发送；失联保护不可依赖堵塞线程自己执行回调。原生线程崩溃可能带倒进程，仍由 F02 监督器／worker 租约处理，线程隔离不是进程隔离保证。

沿用 F03 的 WAL、FULL、foreign_keys=ON、busy_timeout=0、wal_autocheckpoint=0，事务外设置并回读每个相关连接。构造器 timeout 也设零；不能保留驱动默认等待再声称应用队列负责重试。关键路径用参数化 SQL 与显式短 `BEGIN IMMEDIATE`／COMMIT，不混用自动 transaction；不在事务中 await 网络／IPC。

提交失败先检查连接及 inTransaction，结合 tx_id 查询判定，不把 `inTransaction=false` 当作“提交一定成功”或“没有副作用”。没有证明前关闭相关新写，禁止重发设备动作。checkpoint 受控 PASSIVE；Online Backup 成功返回、校验并形成清单后才可用。SQL 更新、审计、outbox 同事务不等于设备写与数据库原子。阶段 1 要做真实锁竞争／崩溃实验，掉电耐久另用受控环境验证。

关键状态表首期不采用 ORM 自动事务、自动重试或启动时静默迁移。使用显式版本化迁移、启动兼容检查、维护窗口及可恢复备份；未来非关键查询层可评估查询构造器，但不能改变 T1—T8／R1—R5 边界。不向模块开放任意 SQL／动态 SQLite 扩展。

## 5. 时钟与 NTP 后端

### 5.1 已核对事实

Node hrtime 文档描述相对任意起点的高精度间隔，没有提供本项目需要的跨进程同域及睡眠计入保证。Windows QueryInterruptTimePrecise 返回含睡眠／休眠的 interrupt time；Linux CLOCK_BOOTTIME 包含 suspend，但 time namespace 可改变其 offset。Node-API 提供 ABI 稳定的原生接口，不替代平台行为验证。（来源：[Node hrtime](https://nodejs.org/docs/latest-v24.x/api/process.html#processhrtimebigint)、[Microsoft API](https://learn.microsoft.com/en-us/windows/win32/api/realtimeapiset/nf-realtimeapiset-queryinterrupttimeprecise)及[interrupt time 语义](https://learn.microsoft.com/en-us/windows/win32/sysinfo/interrupt-time)、[Linux man-pages 项目源码](https://kernel.googlesource.com/pub/scm/docs/man-pages/man-pages/+/master/man/man7/time_namespaces.7)、[Node-API](https://nodejs.org/api/n-api.html)）

chrony tracking 提供 offset、root delay／dispersion、skew 等观测，其误差公式依赖源正确等前提；W32Time 提供配置与状态查询，但单独的选源名称不能证明 UTC 误差界。Linux 内核提供 boot_id；它与进程自身启动 ID 是不同概念。（来源：[chronyc](https://chrony-project.org/doc/4.7/chronyc.html)、[W32Time](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/windows-time-service-tools-and-settings)、[Linux 内核 random 文档](https://docs.kernel.org/admin-guide/sysctl/kernel.html#random)）

### 5.2 项目推荐

采用小型 C／C++ Node-API 适配层，仅封装平台计时和必要身份查询；不增加第六个独立服务，不重写 NTP 算法。Windows 读 QueryInterruptTimePrecise 的 100ns 值并用 bigint 转为纳秒；单位转换不代表纳秒准确度。Linux 读 CLOCK_BOOTTIME。SDK 公共入口仍只暴露 ClockSample／ClockAssessment 等协议，不把原生库传入浏览器。

每个需最终门控的进程直接读取同域时钟，不能每次派发远程请求主服务当前时间。使用 host_boot_id＋平台实现／版本＋时间 namespace 身份建立 clock_domain_id；namespace 不同拒绝共享 tick。Linux 宿主 boot_id 来源须由平台适配验证；Windows 可用且受支持的宿主启动身份来源仍为明确冻结阻断项，不能用启动时间估算、固定机器 GUID 或服务 nonce 伪装 host_boot_id。若要改成保守运行代模型，必须另版审阅字段语义，本稿不改 draft.3。

时间使用三条明确边界：单调钟负责队列／租约／保护截止；认证时间负责身份和证书生命周期；NTP 质量评估负责 UTC 区间和绝对排期。Date.now、setTimeout、日期格式库可用于展示／唤醒，醒来仍重新校验，不能作为一次设备写许可。

默认使用宿主授时：Ubuntu chrony 4.x 的受支持发行版构建；Windows W32Time 指定源与质量适配。读取质量应是本地受限只读接口、固定命令参数／超时及结构化解析；不暴露 chrony 管理 socket 给模块，不让普通服务账户修改系统时钟。配置、实际选源、源认证、样本年龄、保守误差增长和跳变检查一并纳入 F05。容器读取同宿主的受控质量快照并验证所属时钟域，不默认授 CAP_SYS_TIME。

**没有经验证的误差界时，评估保持无证明状态，沿现有 Schema 返回空区间、eligible_for_absolute=false 和原因；不新增一个未定义的 ClockSample quality 枚举。** 即时手动操作仍须通过认证、存储、单调许可等其他门控；共享单调域本身无法验证时，按 F02 禁止写入。Windows NTP 质量证明不足阻断该平台绝对排期验收，不能拿 Linux 通过代替；Windows 首期支持承诺仍需补齐，不能无声缩水。

application_offset 保留已定扩展接口，本轮不选未经审阅的 npm SNTP 库作为默认来源。若宿主后端无法满足部署要求，进入独立 NTP／NTS 实现选型与安全审阅，不回退自写 UDP 时间解析；该模式不标记为首闭环已支持。NTS、单源可信网络、未认证源各按 F05 策略处理，不能因用了 NTS 就宣称时间绝对正确。闰秒／smear／era 与虚拟机快照恢复均需专门边界测试。

## 6. 冻结记录与验证计划

先确认技术方向，再授权隔离技术试验，最后根据真实结果冻结产物。方向同意不自动授权改业务代码。所有验证记录必须包含用例、输入、平台／依赖清单、期望、实际结果、原始证据路径和失败处置。

| 用例 | 阶段与关联 | 方法及通过标准（均待执行） |
| --- | --- | --- |
| TV01 | 选型试验；F01 | 固定工具将171模型、63操作及19 IPC 消息投影／生成；既有正反例逐项等价，生成前后模型引用和摘要不漂移；条件无法表达为 TS 时运行校验仍拒绝 |
| TV02 | 选型试验；F01 | 编译两个服务 client、浏览器最小消费、IPC-only 类型；锁定重生成两次零差异；严格 CSP 下校验，无 Node/native 泄漏；新旧协议错误不自动降级 |
| TV03 | 选型试验；F01/F02 | Number 边界、纳秒字符串、null/缺失、未知字段、格式、if/then、JCS 固定向量、限体积／深度；变异值必须拒绝，拒绝不修改输入 |
| TV04 | 实现后；F01/F04 | 代理丢 201／202、401刷新、超时、重定向、WS断开；不重发不确定写、不更换幂等身份；票据同键重取无secret，不能把等待终止当未发送 |
| TV05 | 选型试验；F04/F05 | 两平台 Argon2id 已知向量／PHC互验；最低配置并发登录测延迟、内存和限流，登录耗尽不阻断出口保护期限；成本配置低于既定安全下限则不发布 |
| TV06 | 实现后；F04 | 多标签刷新竞态、复用、会话固定、CSRF、跨Origin、Cookie歧义、签发方重启和认证钟跳变；精确撤销、拒绝重开旧下界、组织grant不误撤，关联 FA 清单 |
| TV07 | 实现后；F04 | 伪客户端证书、有效证书但未配对、轮换／撤销、代理伪header、DPAPI身份变化／容器权限及备份异机恢复；拒绝越权、秘密不入日志，旧epoch不复活 |
| TV08 | 选型试验；F03 | 双平台原生包加载并回读引擎／source_id／全部PRAGMA；配置不符拒绝写；量测正常事务、读并发、checkpoint／备份对独立保护通道的影响 |
| TV09 | 实现后；F02/F03/F07 | BUSY、FULL、IOERR、提交后丢应答、writer卡住、进程kill、并发恢复CAS；每步tx_id／inTransaction／outbox核对；零未获许可发送，unknown不重投，关联 FT／AU |
| TV10 | 发布验收；F03 | 受控掉电／存储故障、在线备份中断、WAL积压、恢复和迁移；成功确认的关键记录耐久性、备份完整性及新epoch证明，不能用kill模拟替代掉电 |
| TV11 | 选型试验；F02/F05 | 两进程交错读tick验证同域排序；不同namespace／宿主／boot拒绝；休眠／恢复／快速启动／服务重启／VM快照，旧deadline与许可不复活；单位及溢出检查 |
| TV12 | 实现后；F05 | NTP指定源变更、不可达、异常stratum/LI、年龄过期、RTT异常、墙钟跳变、闰秒／smear；区间保守且最终发送重算，窗口右边界拒绝，质量恢复不补发 |
| TV13 | 实现后；F02—F05 | 登录峰值＋DB长查询＋遥测饱和＋接管／撤权并发；独立观测关闸和最后发送，保护预算必须取自获批容量profile，不能任意填“足够快” |
| TV14 | 发布验收；全项 | 干净 Windows11x64／Ubuntu24.04amd64 原生及承诺容器组合复装；lockfile、SBOM、源／产物摘要、第三方许可证、依赖安全公告与可复现构建证据齐全 |

选型试验使用合成数据和模拟出口，不连接直播设备；实施后测试再联动原 FC／FT／FA／TB／OB／AU 验收清单。本轮仅制定这些用例，没有执行 TV01—TV14。

正式版本清单至少记录：组件／用途、精确包版本、锁文件摘要、registry integrity、源tag／commit、实际原生产物hash、内嵌引擎／OpenSSL版本、编译选项、平台矩阵、许可证及公告检查日期、验证报告。生产构建不使用 latest、浮动Git分支或运行时自动更新；升级重新跑受影响用例，不把安全修复拖到大版本重构。

## 7. 剩余冻结事项与当前交付

- SDK：独立 canonical 源提取方案、严格校验例外清单、JCS 库精确版本及语言消费范围；组件独立版本＋Suite组合清单继续保留。
- 认证：HTTP框架接入点、密码实测参数、秘密保管原生封装／CA配对签发与轮换实现；本稿选定的库不能补足这些事实。
- 存储：实际包与内嵌引擎证明、队列和超时预算、文件系统支持清单、迁移／备份运行证据。
- 时钟：Windows宿主启动身份、两平台质量界及源认证证据、容器namespace／休眠／VM策略、application_offset是否进入首发支持矩阵。
- 后续独立轮次：OBS实际版本组合、有限DSL／足迹生成器、监督器与IPC传输、GUI框架／打包部署及容量／留存预算；不因本轮库推荐关闭 F01—F07。

本轮只更新设计入口和确认状态，公共 Schema、OpenAPI、IPC、正反例及生成器保持 draft.3 原内容。文档关联的离线报告可刷新输入摘要；它不验证上述新库可安装、可运行或可用于直播。

本轮实际检查：既有 draft.3 的 221 个离线用例通过，171 个模型、63 个 HTTP／WS 操作、19 类 IPC 消息计数不变；[报告](contracts/draft3/validation-report.json)记录运行验收数为 0。核对 9 份相关文档的 84 个本地链接、24 个报告输入摘要，以及公共 Schema／两份 OpenAPI／IPC／正反例的 5 个基线摘要，全部一致。Git diff 空白检查通过；TV01—TV14 的新工具／平台验证未执行。
