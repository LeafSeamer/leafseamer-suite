# 工具链收敛：SDK、GUI、日历与运维依赖

日期：2026-10-18。本文承接 DF01、TS01—TS05、C06、C10、DF05 和 C12，给出待审阅的组合与冻结步骤。推荐未自动获准，不修改业务代码。用户新增“每完成一轮进行一次commit”，本轮保存本地设计检查点；不包含推送、发布或设备操作授权。

## 1. 已核实事实

读取 npm 官方注册表中18个精确版本的元数据，保存为[观察记录](contracts/toolchain/metadata-observation.json)：逐项URL、原响应SHA-256、版本、engines、peer、依赖范围及发布者声明的tarball integrity。省略维护者邮箱等无关字段。原响应hash只标识本次观察，不是签名；元数据以后可能变化。没有下载tarball，不能据此声称包字节、来源证明或供应链安全已验证。

直接约束包括：openapi-typescript 7.13.0要求TS ^5.x；react-dom 19.3.1要求react ^19.3.1；plugin-react 6.1.2要求Vite ^8.0.0；timezone 3.1.0要求core >=5.7.0。Vite/插件要求Node ^20.19.0或>=22.12.0；tuf-js要求^22.22.2、^24.15.0或>=26.0.0。既有Node24.22.0候选落在这些范围内，仅证明直接声明交集，不是完整依赖求解。（来源：观察记录中的逐项官方固定版本URL。）

TUF客户端实际包名是`tuf-js`，`@tufjs/models`是依赖，不采用未经核实的`@tufjs/client`名称。age v1.3.2的go.mod声明go1.25.0、toolchain go1.27.0；Go官方索引本轮返回稳定版go1.27.2。语言最低版本、上游构建指令、本项目工具链须分别记录。（来源：[TUF官方仓库](https://github.com/theupdateframework/tuf-js)、[age固定go.mod](https://raw.githubusercontent.com/FiloSottile/age/v1.3.2/go.mod)、[Go官方索引](https://go.dev/dl/?mode=json)。）

## 2. 推荐组合

下表是基于项目分层的推荐，不是上游对LeafSeamer的兼容保证。

| 用途 | 精确候选 | 采用边界 |
| --- | --- | --- |
| 共用构建运行时 | Node24.22.0 / npm11.19.1 | 延续DF01，分别锁平台分发物，不能用本机版本代替 |
| SDK生成 | TS5.9.3、openapi-typescript7.13.0、Ajv8.20.0、ajv-formats3.0.1 | 声明生成与运行校验分别验收 |
| 客户端/规范化 | openapi-fetch0.17.0、canonicalize5.1.0 | 严格原始解码在先，不自动重试写操作 |
| GUI | React/React DOM19.3.1、Vite8.3.4、plugin-react6.1.2、TS5.9.3 | 浏览器ESM静态应用，服务职责仍在Seamer/Controller |
| GUI类型 | @types/react、@types/react-dom均19.3.0 | 与运行包分别锁定 |
| 日历 | @js-joda/core6.3.0、timezone3.1.0 | 固定完整时区数据，按profile隔离worker |
| 认证/存储 | cookie2.0.1、argon2 0.45.1、better-sqlite3 13.0.3 | cookie编解码不代替会话/CSRF；原生模块只在服务端 |
| 更新校验 | tuf-js6.0.0 | Suite运维依赖，固定初始根和独立持久信任状态 |
| 备份辅助 | age v1.3.2、Go1.27.2 | C12受限预编译辅助，不要求用户现场安装Go |

18包不是五仓完整依赖清单；测试工具、HTTP/WS框架、数据源驱动、原生编译器及各设备模块仍须进入完整闭包。C11原有NodeCG、ATEM等候选不由本表替换。精确候选已指定不等于制品已经冻结。

## 3. GUI实现边界推荐

采用React+Vite纯客户端应用，静态资产由C12入口提供；操作记录与事件投影来自SDK，React state只保存界面状态。具名服务会话管理器拥有HTTP/WS连接，组件订阅不可变投影，不另建命令状态机。React官方支持Vite起步，也说明自行组合应用须承担路由/数据获取责任；本选择依据已有独立服务和SDK，不宣称普遍优于完整框架。（来源：[React官方说明](https://react.dev/learn/build-a-react-app-from-scratch)。）

生产不带Vite开发服务器或HMR；首期不依赖SSR/RSC、模块联邦或可选React Compiler。固定页面路由只包含非秘密标识，路由不是权限边界。退出/切服务销毁投影，刷新只查询已有操作，不重发。组件effect、重新挂载、StrictMode检查和渲染重试不得发设备命令。

按C10合并未提交推子输入、每资源单未决；持久化仅白名单主题、语言和布局，不保存票据、授权快照、待发送动作或执行队列。Vite构建图包含Rolldown、Lightning CSS，构建宿主仍需原生依赖锁；浏览器产物不得带fs、addon或运行时Schema编译。静态网页并不意味着构建无原生组件。（来源：[Vite官方指南](https://vite.dev/guide/)、固定版本观察记录。）

## 4. 日历、更新和备份边界

日历冻结项为包版本、tzdb release、实际数据文件原始hash、alias map及有效日期范围。本轮未下载数据，不猜测tzdb版本。SCH03的gap跳过、fold显式选择、月末跳过及每profile隔离worker不变，库默认值不能代替批准政策。

TUF用自身编码/签名语义，不接业务JCS；每信任库单writer，持久版本下限留在安装状态域，不随业务恢复降级。批准地址的元数据/制品读取可有界重试，不授权重复安装、激活或设备命令。更新进程失败不能自行切换业务版本。

TUF到期判断仍须检查具体库的时间API，验证回退/前跳/过期；不全局替换Date，不因直播NTP profile无效而关闭签名/到期检查。更新需要可接受的宿主时间和持久防回退证据，无法建立时拒绝更新、保留现安装服务，不自动停止直播。时间适配和初始根保管是DF05剩余冻结项，本轮未验证库能满足这些条件。

age辅助使用固定Go发行物及go.sum；`GOTOOLCHAIN=local`防隐式切换，依赖下载与离线构建分开。只暴露C12的X25519/口令模式，无插件、网络和任意命令入口。秘密不进命令行、环境变量或日志；加解密成功不证明备份来源可信或恢复安全。

## 5. 固定冻结步骤

1. 审阅职责和新增GUI/运维候选；不原地改变已确认协议。
2. 在工具链验证阶段，按SDK生成、GUI构建、服务运行、运维辅助分别生成完整传递锁，严格peer/engine检查，不靠override/legacy-peer-deps放行。
3. 隔离缓存下载并验integrity及原始字节hash，记录来源/签名和许可；可选平台包、安装脚本、二次下载单独列出。哈希一致不等于证明上游安全。
4. 初次安装禁止lifecycle；确有需要时在隔离构建环境按审阅清单执行。ignore-scripts成功不证明原生加载成功；用户生产安装不现场npm install或编译下载。
5. 执行DF01双生成、GUI禁用依赖/CSP、日历数据、TUF及age探针，记录实际工具/平台和输入输出摘要。
6. 证据齐备后写DF05正式制品清单；未测平台不批准。安全更新走精确锁修订和必要复验，不追随latest。

metadata、resolved、bytes_verified、installed、built、qualified分别表示证据层次，不是设备命令状态，也不能仅靠改布尔值晋级。本次仅metadata。定义验证步骤属于设计，取得业务运行证据属于实施/验收，不互相冒充。

## 6. 具体验证用例

下列TL01—TL14均为计划，执行数0；不替代SV/PF/UIT/DPT。

| 用例 | 输入/故障 | 必须结果 |
| --- | --- | --- |
| TL01 | TS不满足^5.x | 依赖失败，不override继续 |
| TL02 | React/DOM peer不匹配 | 拒绝构建组合 |
| TL03 | 同锁两次干净Windows/Linux构建 | 协议生成字节相同，平台产物差异可追踪 |
| TL04 | URL相同但tarball被更改 | integrity失败，不执行或发布 |
| TL05 | 缺原生包/脚本二次联网 | 明确失败，不现场回退编译下载 |
| TL06 | GUI含fs/addon/runtime Ajv/HMR | 依赖/CSP验收失败 |
| TL07 | StrictMode挂载、路由切换、刷新 | 无新增设备写，只恢复查询订阅 |
| TL08 | 手势尾值未提交或已有unknown后卸载 | 不补发，不重放，保留可见差异 |
| TL09 | 同日历版本换tzdb/超有效范围 | 拒绝生成，不能静默偏移 |
| TL10 | TUF旧版/过期/错误根/时钟回退 | 拒绝更新，信任不降级，保留现安装 |
| TL11 | 下载重试和激活超时 | 前者有界，后者查已有操作，不重复激活 |
| TL12 | age错误口令/截断/非法插件/高成本输入 | 有界失败，无部分激活或秘密日志 |
| TL13 | 缺Go/离线缺模块 | 明确失败，无隐式工具链下载 |
| TL14 | metadata合法但无制品/运行证据 | 不得标qualified或生产可用 |

继续按[readiness 6.1](rebirth-readiness.md#61-全系统设计完成门槛)收敛完整依赖、设备协议政策、机器契约归并和统一定稿清单。本文减少未指定候选，不宣称全系统设计完成；用户需审阅的实质取舍仍保持待审阅。
