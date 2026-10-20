# 全系统设计定稿收敛清单

建立日期：2026-10-18；本次收敛审阅：2026-10-20。本文落实用户“先完成所有系统方案设计后进行业务实现”的阶段决定，是[readiness 6.1](rebirth-readiness.md#61-全系统设计完成门槛)的统一关闭视图，沿用C／DF／T／A编号，不另建待办体系。本文不是全系统已定稿声明，也不改变draft.4／IPC 0.3。

## 1. 当前事实与推荐分界

已知事实：Q1—Q72、F02—F07、TS01—TS05、NF01—NF03及draft.4／IPC 0.3已确认。后续DF及C专题的新推荐仍待审阅；自动续跑、文档成文、参考检查通过均不产生产品批准。每轮本地commit已获授权，推送、发布、部署与真实设备操作按各自授权处理。（依据：[决策原文](rebirth-design.md)、[实施清单](rebirth-readiness.md)、[开发记录](../DEVELOPMENT_MEMO.md)。）

来源盘点已覆盖18个旧bundle：设备8个、排期5个、其他系统5个。DM3的184行已形成来源清单，但参数资格、完成证据及运行支持尚未逐项批准。“已盘点”与“逐项设计冻结”分开记账，不再次安排已经完成的目录盘点。（依据：[设备表](rebirth-legacy-device-map.md)、[排期表](rebirth-legacy-schedule-map.md)、[其他系统表](rebirth-legacy-system-map.md)、[DM3清单](contracts/c11-audio/README.md)。）

基于当前资料的分析：剩余工作应围绕下表的具体缺口收敛，避免继续增加同义专题。不能把“所有文档都有了”当作设计完成，也不能要求尚未实现的系统先通过运行验收才允许开始实现。后续证明推翻方案时，回到对应契约作版本化修订，不降低安全承诺或删除功能来关闭缺口。

### 1.1 当前关闭状态，优先于历轮进展中的旧待办

本节依据初次审阅的`0358165`及后续已落实设计持续更新。后文保留的“后续／进展”段落是历轮增量记录；其中“尚无格式／尚无接口”不能重新当作当前缺口。下表中的“已具备”仅表示设计材料存在；候选审阅、最终同版归并和实际运行分别记账。

| 范围 | 已具备的设计材料，不再重复建立 | 仍须在实施前完成 | 留给实现与验收的证据 |
| --- | --- | --- | --- |
| C01 单源与解码 | 六文件等价提取、完整历史HTTP骨架、导出／主体矩阵、严格解码具体方案及投影定位 | 将全部新增接口和类型纳入唯一SDK源；完成严格数字接受集、逐规则调用点和具名摘要投影；处理1.2的显式替换 | 真实解析器、TS生成／消费、浏览器包隔离及跨语言执行；元数据检查不替代 |
| C02/C03 命令与接管 | 三命令裁决接口及11表受理子域、三准备接口及14表准备/关闭子域；[51表组合与30帧IPC候选](contracts/c08-controller/BARRIER_ATTEMPTS.md)登记逐primitive/逐传输许可及同cut尝试/ACK/采用关系；监督控制／bootstrap及15表journal | 其余命令查询／取消／证据与转交关联；RequestKey全链映射；完整资源/终态及其他三类屏障表、真实guard/预算和packet准备持久提供者；统一SDK归并 | writer并发、最终发送竞态、进程纳管和重启、磁盘耐久、设备效果 |
| C04/C05 执行与摄取 | 程序／证明、24操作生命周期、执行记录、40表恢复／提交／摄取组合；保护HTTP、RUN_FENCE和拒绝快照；Controller双入口共享拒绝、P2完整登记集合/queued切点、P3逐出口及汇总应用候选 | 准备回执替换预填grant；P1/P4布局、P3到准备closed的真实引用与资源证据；完整来源依赖、跨source_epoch替换／GC／P0；边沿、预算和依赖边消费写集 | 真实编译器、提供者、事务执行器、跨服务故障、负载与恢复竞争 |
| C06 时间与排期 | 固定日历、场次身份、激活／受理边界；DF03两条时间模型及区间公式 | 明确DF03模型选择，再统一时间证据、ScheduleGuard、场次／日历字段和存储约束；协议库与引导信任边界 | 两平台采样、休眠／换源、NTP误差前提和日历并发运行 |
| C07 身份 | 主体用途矩阵、配对／注销／服务凭据生命周期、来源与对象授权设计 | 新生命周期接口、订阅owner及槽管理完整HTTP/WS；证书与秘密存储profile、历史身份归属及撤销映射 | TLS、当前权限提供者、秘密落盘、撤销传播及日志隔离 |
| C08 存储 | 监督journal、Seamer恢复／逐步执行／摄取布局、Controller51表登记与运行保护尝试组合、面板局部探针 | 全业务库、installation.db及监督journal的完整表／索引／事务／字段映射；完整门控、资源、其他屏障与预算/准备提供者归并，缺表不能用已有局部SQL代替 | 产品驱动、生产迁移执行、WAL、真实崩溃、备份恢复；不要求先实现才能设计 |
| C09 扩展 | 19帧面板通道、35方法和21结果、SchemaBundle、14服务及5订阅接口、15安装接口、9帧导入IPC和监督启动关联 | 数据源SourceRuntimeBinding与启动对象范围；审批／运行／目录／撤销的完整字段提供者和DDL；35方法及动态模型更新到统一协议 | ZIP与原生加载、真实审批、浏览器窗口／port、投影过滤和全部写出口 |
| C10/C11 全功能 | 18旧bundle细项来源、GUI交互、各设备和NodeCG专题；DM3参数profile与184项分组 | 逐参数codec／单位和证据政策、设备复合中间态／释放政策、NodeCG固定兼容组合及许可；统一Schema/IPC与GUI字段 | 实际型号／固件、音频标定、图文像素及浏览器交互；无硬件实证不得标支持通过 |
| C12 发行部署 | 两主部署、静态service路由、安装引用／恢复与TUF时间及信任恢复候选 | 实质取舍审阅、完整锁生成和制品验证规则、安装内层模型与统一协议映射；精确版本变化重新核对 | 下载字节、构建／签名／重建、安装／更新／恢复、Nginx及两平台部署 |

“真实提供者未实现”单独属于实现任务；但其权威来源、输入输出、期限、失败结果或持久所有者尚未定义时，仍是设计缺口。不得仅因没有产品服务而无限延长设计，也不得把未定义的关键行为改名为实现细节。各专题已有运行用例继续沿用，不为这张状态表复制新编号。

DF03应用参考时钟会改变已批准NF02，仍待明确选择；没有答复不能当作批准。该选择只阻止依赖时间模型的归并，不阻止命令／存储／权限等独立设计。其他取舍按第4节形成具体审阅包；不要求用户重新批准Q1—Q72及已确认基线。

DM3候选参数profile含177项：16条r、161条rw；保留旧174个参数地址，154项序号改变，MuteGrpCtrl/On标记为只读。静态定义不等于会话可写资格。（依据：[音频9.1](rebirth-c11-audio-design.md#91-参数成果与支持边界)、[参数profile](contracts/c11-audio/dm3-parameter-profile.json)。）

### 1.2 已有HTTP与IPC的归并裁决

已知事实：以下10份OpenAPI当前共140条操作声明；计数含两个HTTP GET形式的WS升级，不等于140项独立运行功能，也不证明全系统接口已齐备。`draft4`两服务本来有18处同方法／路径；它们属于不同authority，不是可合并身份空间。另有14处**同服务**旧／新方法路径重合，必须作明确替换。以下处置是下一统一候选的设计规则，尚未生成或部署该候选。

| 当前文件（相对docs/contracts） | 声明数 | 所有者与下一版处置 |
| --- | ---: | --- |
| [draft4/controller.openapi.json](contracts/draft4/controller.openapi.json) | 39 | Controller旧基线；命令提交被新版裁决替换，其余操作逐项迁移而非删除 |
| [draft4/seamer.openapi.json](contracts/draft4/seamer.openapi.json) | 32 | Seamer旧基线；12项生命周期及1项摄取被替换，其余继续逐项迁移 |
| [c04-lifecycle/lifecycle.openapi.json](contracts/c04-lifecycle/lifecycle.openapi.json) | 24 | Seamer；12项替换旧操作，12项新增 |
| [c04-preparation/preparation.openapi.json](contracts/c04-preparation/preparation.openapi.json) | 3 | Controller内部mTLS；准备／查原／关闭，不暴露管理origin |
| [c02-admission/admission.openapi.json](contracts/c02-admission/admission.openapi.json) | 3 | Controller；替换submitCommand，新增查原与永久拒收 |
| [c05-ingress/ingress.openapi.json](contracts/c05-ingress/ingress.openapi.json) | 3 | Seamer；替换摄取，新增查原及内部账本读取 |
| [c05-protection/protection.openapi.json](contracts/c05-protection/protection.openapi.json) | 2 | Controller内部mTLS；代次保护与查原，不是设备动作重试入口 |
| [c09-panel-service/service.openapi.json](contracts/c09-panel-service/service.openapi.json) | 14 | 两服务分别拥有会话及writer；同一界面跨服务须两份独立会话 |
| [c09-panel-subscriptions/subscriptions.openapi.json](contracts/c09-panel-subscriptions/subscriptions.openapi.json) | 5 | 两服务分别拥有订阅／投影／ACK；不合并authority或消费水位 |
| [c09-installation/installation-v02.openapi.json](contracts/c09-installation/installation-v02.openapi.json) | 15 | 目标扩展宿主拥有实例；安装0.2替代旧安装0.1，不因包相同共享批准；设备与数据源角色按C09区分 |

同服务替换全集如下，不能按文件加载顺序“后者覆盖前者”：

- Controller：`submitCommand`占用`POST /api/v1/commands`；成功响应改为不可变RequestAdjudication。当前Command仍由原command_ref查询，永久拒收不等于取消。
- Seamer生命周期：`createDefinition`、`updateDraft`、`publishDefinition`、`getIndependenceProof`、`createRun`、`getRun`、`preflightRun`、`armRun`、`pauseRun`、`previewRecovery`、`resumeRun`、`getRecoveryOperation`共12项，同方法路径切到生命周期候选；旧请求/响应不得与新模型拼接。
- Seamer摄取：`POST /api/v1/providers/{provider_id}/events`的operationId从`ingestEvent`变为`submitProviderEvent`。现有[主体矩阵](contracts/df01-source/authorization-candidate.json)和[面板策略](contracts/c09-panel/operation-policy.json)仍引用`ingestEvent`，未完成迁移；生成器、SDK导出、权限用途、调用点及用例必须显式同步，不能只重命名HTTP符号。事件自身去重身份继续按摄取契约，不借HTTP名更改原事件身份。

归并执行规则：

1. 操作主键采用`(authority角色, method, path)`，同一主键只能有一个所选版本；不同服务可以保留同名operationId，生成SDK按服务分入口。外部路由沿[C12](rebirth-c12-deployment-design.md)的静态`/services/<service_id>/api/v1/`映射，不依据用户可控body选择authority。
2. 先登记替换清单，再投影所选模型和完整operation元数据；参数、响应状态／header、认证、对象守卫和版本要求一并迁移。未登记重合、失去绑定的operationId、重复模型身份均使生成失败，不能静默丢弃。
3. 局部候选各自的`X-LeafSeamer-Contract`值保留在历史资料；统一候选必须显式重绑所选接受集及协商元数据。同一路由不得“新版解析失败再试旧版”，也不得以`/api/v1`相同认定模型兼容。最终候选号由实际完整归并产生，本表不代为批准。
4. 模型先按`($id, JSON Pointer)`定位，不能按`Command`、`Ref`、`RequestIdentity`等短名去重。同形但不同authority或语义的Ref也不能自动别名化；数字词法、摘要前缀、issuer_epoch及初始CommandRef须逐项版本映射。
5. 执行worker采用[IPC0.6完整30帧候选](contracts/c08-controller/BARRIER_ATTEMPTS.md)作为下一SDK归并输入，包含编码准备、逐传输及屏障尝试；旧0.3/0.4/0.5保留作历史，不重复拼接旧帧。监督控制9帧、bootstrap4帧、导入9帧及面板19帧仍是不同通道，保持各自端点、身份、方向和握手，不能拼成任意角色可发的通用oneOf；候选采用不等于产品批准。

归并验收沿用C01/C02/C04/C05/C09及X05/X08，具体断言为：①两authority同路径分别生成，单authority未登记重复必须失败；②新submit返回accepted裁决后查到状态修订2，裁决仍绑定初始修订1且摘要不变，reject不能改写为停止；③摄取替换后任何旧操作引用必须在迁移清单中解决，不能出现有路由无授权或有授权无路由；④旧头、缺头、错服务audience及跨通道帧拒绝，不能回退；⑤重算摘要但换issuer_epoch／scope／grant的请求仍拒绝。这里只完成文件和引用审阅，这些断言尚未在统一生成器及运行服务中执行。

### 1.3 历轮进展

以下记录保留当时边界；当前下一步以1.1和1.2为准，不再按每段旧“尚缺”重复开题。

面板HTTP／事务后续进展见[服务端候选](contracts/c09-panel-service/HTTP_STORAGE.md)：14个接口、管理与业务幂等身份、单次激活、可信确认同库受理及精确关闭时序已形成Schema／OpenAPI和局部SQL探针。191项离线检查不证明真实鉴权、并发或WAL；完整撤销IPC、领域DDL、字段提供者及SDK权威归并仍未完成。本条细化已有C08／C09缺口，不自动批准方案或关闭阶段0。

后续[面板执行绑定及IPC候选](contracts/c09-panel-ipc/IPC_GUARD.md)进一步给出完整19帧格式、两种精确selector、受理来源防剥离、完整发送世代与屏障覆盖。102项参考检查仅覆盖新增绑定及合成账本；旧IPC0.3不改，尚未完成公共SDK整体合并、安装fanout与订阅出口的完整DDL，也未运行真实worker／监督器。上一条“撤销IPC未完成”由本批局部候选推进，不表示全链路设计或运行已经完成。

后续[安装撤销与出口持久化候选](contracts/c09-panel-storage/README.md)补齐全部owner／旧世代出口捕获、双向差集冻结、证据与目标绑定、订阅退役及崩溃恢复方案，51项SQLite内存探针通过。安装fanout和订阅出口已有具体记录／事务候选，完整领域DDL、安装及订阅HTTP、公共SDK归并仍待完成；内存串行探针不证明并发、磁盘耐久、监督器或设备运行，不能关闭C08／C09或阶段0。

后续[面板订阅HTTP候选](contracts/c09-panel-subscriptions/HTTP_SUBSCRIPTIONS.md)给出五接口及19种读取的类型绑定，区分权威投影包与宿主完整帧摘要，补齐只读分页、累计消费和单订阅关闭。213项离线检查通过；订阅HTTP已形成局部机器契约，安装HTTP、完整字段提供者和生产DDL及公共SDK仍待归并，真实宿主／服务与设备未验，本候选不自动关闭任何契约。

## 2. C01—C12逐项关闭条件

后续[C04执行候选](contracts/c04-execution/README.md)补齐R4开始、不可变暂停原因、逐步计划／单次提交、提交后执行锚／步骤就绪、延迟窗口及条件跨域换算、边沿采样和分层预算记录。明确两种延迟锚及直接后继窗口为新版本推荐，lookup未发现不授权重发；XRT01—XRT12仍待运行。完整Seamer DDL、依赖边消费、内部窗口／预算／原身份拒收协议及C05/C06／SDK归并与数值codec覆盖仍缺，局部合成检查不关闭C04或阶段0。

后续[C04恢复存储候选](contracts/c04-storage/README.md)补16表及R2—R5写集、双向配对提交、独立恢复锁和旧unknown保留，修正DF04旧R3即可running的表述。内存SQLite检查覆盖逐写回滚、半边关系拒绝及错误投影反证；普通触发受理、逐步提交／延迟／边沿／预算等完整业务表和SDK/IPC归并仍缺，生产并发、磁盘及设备未验，不关闭阶段0。

后续[C04生命周期候选](contracts/c04-lifecycle/README.md)补齐活动槽、预检／准备、触发快照与一次执行、恢复记录和24操作OpenAPI；同键查询先于旧预览期限，准备回执绑定新代次及精确grant，失败后迟到回执不自动重启。本批推进运行记录及管理HTTP格式，尚缺完整Seamer DDL、延迟／边沿／预算记录、R4命令和C05/C06／SDK／IPC统一归并；有限原子步不证明数据库并发、真实身份或设备，候选未批准，C04及阶段0仍未关闭。

后续[C04程序与证明候选](contracts/c04-program/README.md)已将有限AST、规则／平坦状态机、固定输入和动作绑定、完整派生图、独立性证明及发布产物落实为Schema；完整program投影保留业务同名字段，证明从图计算全部后继。离线检查包含4096步和第301步依赖，不执行产品引擎。该批推进DSL／proof容量和投影的机器缺口；活动槽／触发快照／预检／延迟及发布HTTP、完整Seamer DDL与SDK同版归并仍缺，真实权威和参数二次验证未实现，候选未批准，C04及阶段0不关闭。

后续[监督日志完整布局](contracts/df02-supervisor/JOURNAL.md)已补15表SQL与恢复计数视图、J1—J6事务、完整快照封存／永久deny同提交、attempt和准入回执的双向提交约束、全域退役覆盖。88项内存参考通过；“监督journal尚无完整物理布局”的缺口已推进，仍需生产迁移／完整业务DDL与SDK字段映射、真实提供者／平台故障及原生制品验收。该候选不替代既有179项协议检查，也不关闭C03／C08／C09或阶段0。

后续[监督器机器候选](contracts/df02-supervisor/README.md)补齐bootstrap四帧及控制九帧、完整fence准入集合、一次创建及回执丢失核对、journal字段／事务和局部SQL约束。明确监督器AdmissionReceipt先于核心RuntimeBindingRef，关闭准入不等于组退役；新增SRT01—SRT12待运行。bootstrap／fence无格式和journal无布局的缺口由本批推进；完整生产DDL、真实提供者、原生SQLite制品／保护预算及SDK统一归并仍未完成，候选未批准，C03／C08／C09及阶段0保持未关闭。

后续[安装0.2候选](contracts/c09-installation/LIFECYCLE_V02.md)已给出15个管理接口与角色解析／review／Approval及扩展启动绑定，修正旧enable复用旧实例review的冲突；191项离线参考通过。新实例先stage再解析批准，启动短授权、fence与一次创建账本分开；完整bootstrap／fence IPC、生产DDL／监督journal和真实提供者仍缺。LACT01—LACT12未执行，不能用局部归并关闭C09/DF02或阶段0。

后续[扩展包与本机导入候选](contracts/c09-artifact-import/README.md)补齐manifest／逐文件清单、八类角色权限模板、九种IPC消息和导入恢复边界。181项离线检查不执行ZIP或实际IPC；分发包不硬编码本机设备／秘密引用，新增RoleResolution及ResolvedReview关联，旧安装HTTP不暗改。包／导入无格式的缺口已有具体方案，完整依赖锁／能力模板、可信提供者、审批／LaunchIntent同版绑定及生产DDL仍缺；IAT01—IAT12未运行，不关闭C09或阶段0。

2026-10-18安装机器契约进展：[C09第16节](rebirth-c09-extension-design.md#16-安装管理schema与openapi候选)将安装管理落实为14接口Schema／OpenAPI，增加权限收窄审阅及原管理identity查询，八种权限和四用途计划具名，阻塞页绑定固定快照。219项离线参考检查通过；原“安装HTTP尚无机器格式”的缺口已推进。完整manifest／导入IPC、所有字段提供者、运行绑定和领域DDL、最终容量与证据分页仍缺，候选未批准，ILCT运行未执行，不关闭C09或阶段0。

2026-10-18安装生命周期进展：[C09第15节](rebirth-c09-extension-design.md#15-安装身份管理操作与升级恢复)细化稳定槽位和不可复用实例、独立宿主离线导入、审批范围、9个POST及3个GET接口、管理幂等与CAS、关闭／退役／资源核对三条件及崩溃恢复。ILCT01—ILCT24是未运行验收；本轮消除disabled实例复活拒绝墓碑的冲突，不改变手动控制或全模块范围。安装HTTP已有具体字段和状态方案，但完整Schema／OpenAPI、类型化权限／依赖计划和内部导入协议、生产DDL仍待归并；文稿成文不关闭C09／C12或阶段0。

下表均未关闭。“实现后证据”不是本轮已执行测试；完整用例仍以各专题为准，表中列出主要定位。

| 契约及主责 | 实施前必须落定的设计交付 | 实现后取得的证据 |
| --- | --- | --- |
| C01／SDK | [DF01](rebirth-df01-sdk-freeze.md)单一数据源、完整HTTP/WS元数据及源等价迁移；严格原始JSON解码器的明确方案和预算；具名JCS投影及整数词法新版修订；生成器输入/输出清单 | SV01—SV20：真实双生成、Ajv等价、TS消费、浏览器CSP、原始报文拒绝与跨语言字节一致 |
| C02／Controller、SDK | [F02/F03](rebirth-f02-f03-design.md)与设备profile统一：attempt、传输ACK、效果、终态和资源释放分离；ATEM逐次重传许可；每项完成／unknown／超时及重试政策 | FT、OB、VAT、AUDT：真实发送边界、断线及设备完成证据；不以缓存或Promise完成代替 |
| C03／Controller、SDK | [DF02](rebirth-df02-runtime-design.md)bootstrap机器模型及创建时纳管；[C10](rebirth-c10-gui-design.md)转交主体、权威到期、operation关联；覆盖全部写出口的账本及屏障 | RT01—RT35、FT、UIT：进程崩溃/重启、接管effective与ready、在途保留和保护传播 |
| C04／Seamer、SDK | [AR01—AR06](rebirth-c04-automation-design.md)有限DSL与足迹规则；program/proof分离，具名路径投影，proof容量与步骤上限一致；跨版本活动槽、延迟与恢复绑定 | EX01—EX32、AU01—AU20：真实编译/执行、失败依赖、状态提交和并发恢复 |
| C05／SDK、各服务 | [ES01—ES06](rebirth-c05-event-sync-design.md)来源namespace、日志世代、完整snapshot含runs、双向帧及ACK/票据订阅绑定；摄取到执行资格的事务/失步边界 | EV01—EV36、IN：丢帧/重连/慢消费者/撤权、完整交接与不补执行 |
| C06／Seamer、SDK | [DF03](rebirth-df03-time-profile-design.md)各平台可证明年龄和一致性的具体采集方法；[SCH01—SCH07](rebirth-c06-schedule-design.md)CalendarProfile、观察来源、场次身份、激活/受理串行及ScheduleGuard与RunBinding版本联校 | TP01—TP36、CT01—CT42：真实授时/时基/休眠/换源、日历边界、并发激活及过窗不补发 |
| C07／Controller、SDK | [DF06](rebirth-df06-internal-trust-design.md)完整配对/来源注册/一次消费；内部错误映射、撤权对象与关联；独立/套件身份和面板授权交集在新版保持一致 | FA、IN01—IN32、UIT：真实TLS、身份到期/撤销、跨服务采样与日志隔离 |
| C08／各服务、Suite | [DF04](rebirth-df04-storage-design.md)完整表/约束/索引/事务规范及SDK字段映射，补场次/授权/安装模型；业务库与installation.db分别拥有者、恢复边界明确 | ST01—ST32、DPT：真实驱动WAL、并发、掉电、备份与整组引用恢复；内存SQL不替代 |
| C09／Controller、SDK | [ME01—ME07](rebirth-c09-extension-design.md)安装批准、运行身份、目录/足迹、PanelSession及撤销完整关联；逐次协议写许可与外部入口边界进入IPC | MX01—MX40：加载隔离、撤权/卸载、模块全部异步写出口、面板代理及跨实例竞争 |
| C10／GUI | [UI01—UI07](rebirth-c10-gui-design.md)完整投影、转交/未知/恢复、实时输入及复合中间态；Seamer编辑scope与受控兼容编辑入口；工具链已有精确候选，仍需审阅和闭包锁定方案 | UIT01—UIT40、TL：双语/键盘/浏览器、刷新不重发、推子有界、退出清理和权限撤销 |
| C11／Controller | [OBS/ATEM](rebirth-c11-obs-atem-design.md)、[音频](rebirth-c11-audio-design.md)、[NodeCG](rebirth-c11-nodecg-design.md)全部能力、型号、参数、资源及证据逐项冻结；下节列出不能挪到“实现时再定”的缺口 | VAT01—VAT48、AUDT01—AUDT72、NGT01—NGT32、A19/A21：各组合实际设备及图文兼容，不借用OBS证明 |
| C12／Suite | [DEP01—DEP08](rebirth-c12-deployment-design.md)及[DF05](rebirth-df05-release-design.md)统一安装/恢复模型、信任根保管/恢复及更新时间政策；完整依赖与原生制品锁定规则、两主部署与NodeCG输出profile | RA01—RA28、DPT01—DPT48、PF、A20—A22：签名/重建/安装/恢复/两平台部署及发布支持矩阵 |

## 3. 必须先解决的具体缺口

以下是对既有待办的优先排序建议，不新增或批准技术方案。

1. **DF01严格解码及完整生成链**：[DF01第8/9节](rebirth-df01-sdk-freeze.md#8-d3d5补充严格入口的具体候选)已给出原bytes扫描/原生构值/Ajv分支内token守卫、有限预算、完整HTTP骨架及源映射方案，附局部描述Schema和独立原始预期。实现路径已有具体候选，仍待审阅、全量机器归并及适配取证；不再笼统列为无方案。源等价提取与后续语义修订分开，不能用描述检查冒充SDK解析器验收。
2. **DF03两平台授时证据**：[DF03第9节](rebirth-df03-time-profile-design.md#9-p04p05复审具体后端路径与应用参考时钟候选)已核对chrony内部标记及W32公开接口的证明边界，给出后端扩展最低接口与推荐的应用参考时钟路径、区间公式、状态／故障表和TP37—TP48。推荐会改变NF02时间模型，须审阅后才能决定后续Schema分支、原生协议库／NTS引导及平台profile，不自动替换system-bound/1。不把“有推荐方案”当成架构已冻结，也不缩减指定NTP和两平台目标。
3. **C11设备协议政策**：[OBS/ATEM第8—10节](rebirth-c11-obs-atem-design.md#8-av04av06补充可审阅的传输与证据冻结方案)已有VLC源内窄补丁/桥、条目及播放代、ATEM逐传输许可/事务/接收窗口、Studio与转场独立profile和VAT33—VAT48候选；新增维护、延迟及保护成本仍待审阅，不再笼统列作无方案。专属Schema/IPC/DDL及逐型号证据仍须收敛；DM3全184项codec/单位、scene/meter、WING patch中间态与UDP关联、VB路由存在性/TEXT年龄因果继续推进。不能把selected、旧缓存或同值观察当完成。
4. **DF05/C12发行信任**：[DF05第8节](rebirth-df05-release-design.md#8-af02af03af05具体冻结候选)已有引导收据、角色保管、独立时间锚点、逐metadata事务和阈值失陷新域恢复具体方案；修正“所有metadata版本永不下降”与合法在线key轮换恢复的冲突。固定tuf-js6.0.0不具备所需时间/持久化接口及缓存恢复路径，窄适配补丁是待审阅新增选择，不宣称已可直接采用。安装记录/工具链manifest内层模型仍需归并，实际渠道/密钥及运行证据后置；业务备份不能降低信任。
5. **C04—C09跨项机器契约**：收敛DSL/证明容量、source命名空间、日志世代、完整快照、场次/版本、授权与扩展目录绑定；DDL约束、HTTP/WS和IPC同版联校。仅各自Schema合法不能证明关联成立。
6. **C10/C11/C12完整兼容组合**：明确NodeCG adapter、bridge、旧资产/编辑器的固定组合和许可；受控编辑、外部dashboard、三路只读输出分别有身份、写入口及完成证据。输出只读隔离不能代替桥在途排空或像素验证。
7. **全量工具链与预算**：在已有[精确候选](rebirth-toolchain-lock-design.md)上补严格解码、HTTP/WS、数据源驱动、设备库、测试和原生构建依赖，明确完整锁的生成/审阅规则。大小、队列、proof、请求与保护预算必须有限且有选择规则；测量结果后置，但不能留下“无限/自动”。测试工具的常规实现选择由开发处理，涉及协议语义、权限或平台支持的选择须先写设计。

每个缺口的下一次交付直接修改所属权威稿，包含字段/状态/失败表、至少一条正常和一条关键故障轨迹、正反例及对应既有用例；不再仅新建“后续仍需研究”文档转移问题。

2026-10-18 DM3进展：[音频第9节](rebirth-c11-audio-design.md#9-ad03细化参数目录编码与会话资格)明确稳定参数身份与访问资格、184项8组编码审阅计划及22个局部正反例。RCP、OSC、原生协议分域并共享物理设备仲裁。编码、会话与meter/scene已有候选；名称/枚举、原生寻址、机器归并及审阅尚未全部完成，C11保持未关闭。

2026-10-18 WING/VB进展：[音频第11—13节](rebirth-c11-audio-design.md#11-ad05细化vb请求回复存在性与释放证明)从厂商示例补出VB TEXT请求的SERVICE ID2回复关联，给出counter持久不复用、pending状态、采样年龄与presence分离；WING补主/备用和选择状态、两种中间态的计划算法及native查询解析候选。存在性、写后采样、迟到UDP副本释放和引擎完成仍缺批准依据，不能以单包OK或查询结束关闭；新增AUDT57—AUDT72待运行。限定的是证据和当前资格，不删除WING/VB功能目标。

2026-10-18机器资料进展：[音频第14节](rebirth-c11-audio-design.md#14-局部机器契约及跨项衔接修正)给出局部Schema及AC01—AC75合成检查，修正静态定义/会话权限、VB纳秒时钟/摘要和观察通道、WING计划槽/运行许可的分界。不是完整SDK或184项正式目录；源映射、codec/资格来源、观察IPC、primitive执行绑定及DDL仍待归并，AUDT运行验收未执行，C11未关闭。

2026-10-18 SDK源进展：[DF01第10节](rebirth-df01-sdk-freeze.md#10-完整机器数据的等价提取实验)已有独立纯数据重组候选，六份历史机器文件逐节点/原字节等价、两次临时副本重组一致，原232例由历史验证器复验通过。实验未触碰SDK既有未提交治理改动；语义规则、完整投影/预算/导出策略仍待提取，未切换权威或批准SDK发行，C01未关闭。

## 4. 审阅包与关闭记录

2026-10-18语义追踪进展：[DF01第11节](rebirth-df01-sdk-freeze.md#11-语义迁移与导出边界的证据)把232例分层及13入口/13投影定位落实为可复验报告，明确8个历史判定未进入该批，并复现开放数据误分派与目录唯一性漏接。公开/内部/IPC具名根闭包已逐项列出；规则按模型路径分派、目录唯一性补接和投影修订仍需新版归并审阅。函数进入不证明分支覆盖，不能用232全通过关闭SV03或删除历史独立安全集。

待审阅推荐按关联打包，编号保留：

2026-10-18导出进展：[DF01第13节](rebirth-df01-sdk-freeze.md#13-完整导出清单与客户端用途)已逐项登记71操作与227模型及8个候选子路径，46个资料用例和独立来源对账通过。浏览器入口与主体授权分开，WS仍限人员票据、面板仍走委托桥；实际包构建/导入、完整主体约束和策略批准仍待完成，不能作为SDK交付。

2026-10-18主体矩阵进展：[DF01第14节](rebirth-df01-sdk-freeze.md#14-逐操作主体凭据与目标守卫)给出71操作、105分支及43具名守卫，36个元数据正反例通过；service手动收紧、服务草稿/未布防run及有限暂停、human发布/布防/恢复均标为新推荐。当前主体用途不再无清单；真实权威取证、六类身份生命周期/订阅/委托接口、语义调用点及HTTP/IPC/DDL联合归并仍是明确剩余项，18条运行轨迹未执行，不关闭C01/C07。

2026-10-18身份生命周期进展：[DF06第9节IL01—IL06](rebirth-df06-internal-trust-design.md#9-身份生命周期细化注销组织服务与配对)已明确自身注销、PrincipalView、组织批准、staged凭据证明／激活／一次秘密交付、定向token、有限轮换及双向配对的候选接口和状态。[DF04第10节](rebirth-df04-storage-design.md#10-身份生命周期事务补充)补六类身份事务、唯一性和提交未知处理；ILT01—ILT18为待运行验收。普通退出不混撤组织run，健康轮换可建立新请求但不迁移旧许可或自动恢复；pending配对只开放精确引导用途，双方各自提交。四类身份接口已有具体方案，尚未生成下一版Schema／OpenAPI或批准运行；证书／秘密存储profile、C05服务订阅和C09面板委托仍待收敛，不把本轮成文当C07关闭。

2026-10-18服务订阅进展：[C05第9节SS01—SS06](rebirth-c05-event-sync-design.md#9-服务订阅细化与局部机器候选)补齐mTLS服务owner、consumer槽批准、独立内部入口、attach尝试／连接代际、确认链及恢复资格。七种局部模型已有Schema，27结构例和45有限关联例通过；附着幂等／并发及真实TLS、持久消费仍仅设计。重连reconcile不补直播动作、sync.ready不解除暂停，证书轮换与人员注销分别按真实资格链处理。完整manifest/data、HTTP／槽管理投影、摘要注册及与来源摄取／DDL同版归并尚缺，SST01—SST12未执行，不关闭C05/C07。

2026-10-18面板委托进展：[C09第9节PD01—PD06](rebirth-c09-extension-design.md#9-面板委托与可信宿主确认细化)明确单authority会话、窗口握手与port绑定分离、具名代理、固定预览及目标服务内确认／业务受理同事务、完整请求身份和精确撤销。71项现有操作已形成六类策略元数据及28个正反例，防止高风险动作降成直接调用或以全部禁用削功能。候选路由包括握手、激活、续租、请求查询、确认创建／消费／取消及关闭，GUI同步导航检测窗口。完整PanelSession／消息／投影、OpenAPI、撤销selector及guard／IPC／DDL仍须同版归并；PDT01—PDT16未执行，局部资料不是浏览器隔离或真实授权证据，C09未关闭。

2026-10-18快照进展：[C05第10节SP01—SP06](rebirth-c05-event-sync-design.md#10-完整快照交接的字段与事务细化)明确十二类授权投影及引用闭包、固定内容／连接绑定分离、页与manifest非循环摘要、baseline ACK摘要映射、SQLite同一致点构建及客户端原子替换、source水位和left_scope删除区别。补SNP01—SNP16运行规格，原72项服务订阅参考检查只作回归，不证明新快照模型。十二类逐字段Schema、manifest／page／delta及HTTP／WS／DDL仍待归并；来源快照不证明新鲜采样，快照和reconcile不创建直播执行，C05未关闭。

2026-10-18快照机器资料进展：[C05第11节](rebirth-c05-event-sync-design.md#11-十二类投影及分页增量的机器候选)已有十二SnapshotView及manifest／page／data局部Schema，107项结构／摘要／关联参考例通过。请求关联保留原完整身份，完成等级、取消、转交与场次资格分别表达；动态值二次校验和非循环摘要有实际合成检查。完整领域字段投影／脱敏、每字段关系闭包、真实权威／来源年龄提供者及同版HTTP／WS／DDL仍未完成，不能将局部机器候选当SDK交付。

2026-10-18面板消息进展：[C09第10节PC01—PC05](rebirth-c09-extension-design.md#10-面板会话与调用信封的机器候选)消除ready与nonce先后歧义，形成会话／委托、四窗口消息、七端口消息、Intent／Preview和Guard的局部Schema及合成关联检查。预览完整摘要绑定显示、目标修订与固定截止；关闭、取消和已消费结果分别处理，提交未知不证明未受理。完整35方法的参数／结果／显示投影、订阅消息、HTTP／IPC／DDL及真实浏览器／并发证明仍缺，C09未关闭。

2026-10-18方法字段进展：[C09第11节](rebirth-c09-extension-design.md#11-逐方法输入与结果投影)完成35方法输入候选Schema、96个HTTP字段归属和21个结果白名单，74项离线检查对账来源和手写结构预期。布防／恢复采用服务绑定展示句柄，保留可信确认和原恢复唯一消费；分页句柄不暴露上游cursor。结果Schema／投影及动态表单SchemaBundle、权威句柄事务、订阅及HTTP／IPC／DDL仍待完成，PMT01—PMT12未运行。该进展替代“35方法尚无输入字段”的旧缺口描述，不关闭C09，也不批准新候选。

2026-10-18结果机器进展：[C09第12节](rebirth-c09-extension-design.md#12-21类结果schema与关联边界)已有21类View的完整形状及35方法映射，117项合成检查通过。修正Definition承载为明确SchemaRef/value，保留unknown清理、正常在途与ready、隐藏全局目标和旧epoch接管的区分；合法字符串并不证明脱敏。结果Schema不再是空缺，真实投影器／字段授权和受控词表、SchemaBundle／订阅及HTTP／IPC／DDL仍未完成，运行验收和候选批准保持未完成。

2026-10-18SchemaBundle进展：[C09第13节](rebirth-c09-extension-design.md#13-schemabundle交付与本地闭包)补齐四种局部消息、批准绑定、本地Schema引用闭包与容量候选，109项离线检查通过。修正旧Active没有附件字段的冲突：采用channel0.2候选号，完整激活／方法／结果及订阅仍待同版归并，不改旧0.1。缓存不授权限、Schema ready不等于执行资格，实际加载器／权限／worker／浏览器与HTTP／IPC／DDL仍缺；不再把Bundle笼统列为无方案，也不关闭C09或全系统设计。

2026-10-18通道归并进展：[C09第14节](rebirth-c09-extension-design.md#14-channel02完整消息与方法归并)已有19种窗口／端口消息、35方法Registry及ActivationRef与动态Bundle联接，168项离线检查通过。新增投影订阅不循环调用预检／恢复预览，退役释放窗口不推进ACK；旧0.1不改。完整消息格式不再是空缺，但实际字段提供者、完整动态能力和DSL投影、HTTP／IPC／DDL及运行验证仍缺，C09和阶段0不关闭。

2026-10-18注册元数据进展：[DF01第12节](rebirth-df01-sdk-freeze.md#12-语义注册选择器与评估结果候选)新增局部Schema及78项离线检查，明确条件覆盖不绕开放参数、可信上下文与四类结果边界。八个业务向量及实现绑定仍为计划；完整规则/调用点/导出根边界与生产执行尚缺，不能作为C01关闭或SP缺口修复证明。

| 审阅范围 | 既有推荐编号 | 需要审阅的实质取舍 |
| --- | --- | --- |
| SDK与系统基础 | D1—D6、R01—R06、P01—P07、DB01—DB06、AF01—AF06、IA01—IA06 | 源迁移/数字新接受集、运行域/采样边界、数据库与信任恢复、内部身份；已确认方向不无故重问，DF03第9节有新增后端证据支撑的NF02模型变更须明确复审 |
| 自动化与排期 | AR01—AR06、ES01—ES06、SCH01—SCH07 | 有限DSL及失败依赖、活动槽与延迟、来源/快照/失步、固定日历与跨版场次 |
| 扩展和全部设备 | ME01—ME07、NG01—NG07、AV01—AV06、AD01—AD07 | 模块写权限/批准、桥与旧编辑器、设备复合中间态及证据不足时的可用边界；保留完整旧功能 |
| 操作台与发行 | UI01—UI07、DEP01—DEP08及工具链新增候选 | GUI交互/技术组合、只读输出与入口、加密备份、整组安装引用与信任策略 |

上述包当前均为待审阅，不能靠本文变成已确认。未解决的关键问题先补具体方案再审阅，不要求用户笼统批准未知内容。用户仅需决定影响功能、保护语义、支持范围、授权或运维负担的取舍；命名、目录和不改变契约的常规实现无需逐项请示。

关闭记录应附在各权威稿现有“剩余/放行”节中：原编号、已定行为、依据/确认记录、适用契约版本、正反例、验收编号、尚未执行的证据和失败时关闭行为。实现后证据有负责人及用例即可移入实施清单，但没有设计方案不能移走；“待实测”也不能被改写为通过。

2026-10-18逐步持久化进展：[C04第13节](rebirth-c04-automation-design.md#13-执行锚与单次命令提交的持久化)和[DF04第13节](rebirth-df04-storage-design.md#13-c04逐步提交与裁决持久化)新增执行层9表，与恢复核心组成25表draft.2候选，补执行锚、步骤、单次提交、最终裁决与终态映射。212项内存/合成检查通过；补强无持久裁决不可自造accepted、迟到accepted不重开unknown、合格取消非业务成功。普通触发/发布事务、delay依赖消费、edge/budget、Controller永久拒收以及SDK/IPC同版归并仍待完成；真实运行及候选批准状态不变，不关闭阶段0。

## 5. 合并与实施交接顺序

2026-10-20普通摄取进展：[C05第12节](rebirth-c05-event-sync-design.md#12-规范摄取的完整扇出与原子受理)、[C04第14节](rebirth-c04-automation-design.md#14-普通触发批次世代水位与执行发布)和[DF04第14节](rebirth-df04-storage-design.md#14-来源摄取批次与多运行实例的存储边界)补出零／多run完整批次、ReceiveCursor及独立ingest_revision、全决定／计划同事务、数据库级摄取审计、provider脱敏回执、回滚后不升级live资格和EN01—EN24验收设计。现有数字水位和单run审计不能承载这些含义，须在新版本共同归并；不暗改原机器资料。普通摄取不再只有原则描述，但新Schema／OpenAPI／DDL和原子批次检查器尚未交付，EN未执行；旧局部回归不证明本轮新设计已运行。边沿／预算、场次和最终SDK/IPC关联继续推进，候选及阶段0未关闭。

2026-10-20摄取机器资料进展：[C05第13节](rebirth-c05-event-sync-design.md#13-普通摄取机器候选与原子写集检查)和[局部候选](contracts/c05-ingress/README.md)补出Schema、三接口OpenAPI及15表附属布局，与原执行/恢复组成40表；190项离线检查通过，包含完整集合关联、逐写回滚、半边拒绝和provider投影隔离。上一条“尚无机器资料”由本批推进，但仍无完整来源保护/GC/floor、实际预算、固定回执持久映射和端到端writer；未运行真实认证、并发、磁盘或设备。EN全套验收、SDK/WS/IPC最终归并和阶段0继续未关闭。

2026-10-20来源保护进展：[C05第14节](rebirth-c05-event-sync-design.md#14-来源失效完整依赖保护与恢复门槛)、[C04第16节](rebirth-c04-automation-design.md#16-来源暂停的代次绑定与恢复消费)及[DF04第16节](rebirth-df04-storage-design.md#16-来源保护的持久所有者与四个事务)补齐完整来源依赖/旧执行pin、prepare发送前目标登记、运行代次拒绝、P1—P4持久所有者及显式恢复门槛。[保护局部候选](contracts/c05-protection/README.md)已有模型Schema及RUN_FENCE两种正文包络；131项结构/合成关联和有限原子模型检查通过。保护applied不清理在途/unknown，不直接恢复run；source_changed关闭旧key，故障只增强，重新同步不重放旧事件。完整HTTP/IPC/握手、实际字段提供者、P1—P4物理DDL、跨source_epoch替换链、P0与GC仍待交付；PFT01—PFT18未运行，未关闭阶段0。

2026-10-20保护协议归并进展：[C05第15节](rebirth-c05-event-sync-design.md#15-来源保护http及完整执行ipc候选)及[协议候选](contracts/c05-protection/PROTOCOL.md)提供两个内部保护HTTP操作和21帧IPC0.5，连接自动化来源与面板绑定，补开闸完整拒绝快照。统一定义计数与运行域、保留人工路径，141项离线检查通过；原局部资料不暗改，账本排序/容量修订显式版本化。保护HTTP/IPC不再是无机器格式，公共命令与Prepare入口、全部字段签发者、P1—P4物理DDL、跨epoch基线与GC/P0仍缺；运行验收及阶段0未关闭。

2026-10-20准备签发进展：[准备候选](contracts/c04-preparation/README.md)补三项内部HTTP及Schema，分离准备意图、Controller实际grant回执和最终ExecutionBinding，消除预先要求尚未签发grant引用的环。arm绑定代次、恢复绑定单execution；实际grant由null一次绑定，迟到回执不恢复失败操作，close先到也建立精确拒绝墓碑。102项结构/合成关联与串行快照检查通过；旧夹具不改。准备接口不再缺机器格式，但实际提供者、完整SQL事务、公共命令全路由及SDK统一迁移仍缺；PRE01—PRE12未运行，候选待审阅，不关闭阶段0。

2026-10-20命令裁决进展：[受理/查原/永久拒收候选](contracts/c02-admission/README.md)提供三项公共HTTP与Schema，明确issuer_epoch进入持久身份、submitCommand到createCommand的操作映射、完整参数摘要及同writer排他裁决。accepted固定原CommandRef，rejected永久阻止迟到请求；92项离线结构/关联和串行顺序检查通过。旧4xx或not_found仍不构成永久拒收；Controller物理DDL、历史命名空间归属provider、公共其余查询/取消/证据路由与SDK/C04身份列统一迁移仍缺，运行验收和阶段0不关闭。

2026-10-20命令存储进展：[受理子域布局](contracts/c02-admission/STORAGE.md)提供11表、完整受理/拒收写集、历史namespace及当前权限提供者边界，159项内存SQL检查通过。裁决/初始命令/容量/审计/通知及拒收操作双向配对，关闭namespace不阻当前有权保护，旧命令RequestIdentity字典已明确标为历史。完整Controller执行/屏障和准备表、实际鉴权、Seamer身份列与SDK归并仍待完成；内存串行检查不关闭运行验收或阶段0。

1. 补齐第3节实质缺口并完成第4节相关取舍审阅；按readiness的X01—X16检查跨项安全约束，保留已有确认及全部功能范围。
2. 在SDK独立完成旧基线单一源的等价提取，Suite保留历史资料及对账入口；产出逐节点对账和原例接受集对账，不能只比类型数量。此处仍是契约资料/生成验证，不启动服务业务实现。
3. 在明确的新候选版本归并已审阅修订，形成同版Schema、OpenAPI、IPC、路由/WS元数据、具名摘要投影和DDL映射；旧draft.4／IPC0.3原样保留。版本号由实际变更包决定，本文不提前宣布新基线已批准。
4. 每个修订必须有正常、边界、错身份/错域/错版本、重算摘要后错配、旧写降级拒绝用例；按故障需要补接管/撤权/崩溃时序。校验报告绑定实际输入及提交字节，静态结果和运行证据分列。
5. 全量追踪从18个bundle细项和Q决策到C契约、五仓交付及A01—A22，无遗漏且第2/3节设计未决为零后，才登记阶段0完成并进入业务实现。保留实现、平台和设备未验收清单，不能顺带声明项目完成。

本清单不自行批准任何候选或宣告阶段0关闭。2026-10-18后续进展：DF01严格解码和生成元数据已有具体候选及局部描述；DF03已形成具体路线复审包，模型选择仍未确认。SDK源未迁移，draft.4／IPC0.3及业务代码未改。后续推进设备证据和发行信任等独立缺口，时间模型相关归并等待选择明确。
