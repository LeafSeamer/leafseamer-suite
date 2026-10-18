# C12：部署入口、输出隔离、备份恢复与维护切换候选

- 日期：2026-10-18（Asia/Tokyo）；责任仓库：Suite，Controller／Seamer提供服务和存储接口，GUI提供受权操作，SDK承载契约。
- 已确认范围：Q68的Windows 11 x64／Ubuntu 24.04 amd64及Linux容器；Q70的Linux Compose＋Nginx完整套件、Windows原生Controller＋GUI独立现场；Q71完整旧NodeCG图文。用户要求先完成全系统方案，再进行业务实现。
- 当前事实：[DF02](rebirth-df02-runtime-design.md)、[DF04](rebirth-df04-storage-design.md)、[DF05](rebirth-df05-release-design.md)分别已有监督域、数据库、发行候选；[C10](rebirth-c10-gui-design.md)已有GUI交互候选，[C11](rebirth-c11-nodecg-design.md)仍要求具体输出访问profile。本稿不把这些候选视为已批准。
- 本文推荐：DEP01—DEP08待审阅；DEP是本专题建议编号，DPT01—DPT48是未执行验收。未提供可运行安装器、Nginx配置或Compose文件，未安装服务／证书、接触设备或发布制品；公共draft.4／IPC 0.3保持原样。

## 1. DEP01：部署拓扑及责任边界

| profile候选 | 组成及边界 | 必须单独取得的证据 |
| --- | --- | --- |
| linux-compose-suite | Ubuntu24.04 amd64宿主；Nginx、指定身份Controller、Seamer及可选NodeCG容器；GUI静态制品；Suite宿主生命周期辅助程序 | cgroup／旧容器退役、每实例本地卷、宿主时钟读取、设备网络及精确镜像组合 |
| windows-native-controller | 固定Win11 x64版本；SCM启动原生监督器及Controller，内置HTTPS入口服务已打包GUI；无需Seamer／NodeCG／Docker／Nginx | Job、跨会话单实例锁、证书信任、设备与时钟profile；本机与远程访问分别验收 |
| linux-native | systemd启动原生Controller／Seamer，可接Nginx；仍用相同SDK／监督／存储规则 | 原生包、UID／cgroup、数据目录及设备网络，不借容器结果 |
| split-control | 云端或另一主机部署GUI／Seamer／入口，设备所在现场部署原生或已验容器Controller | 服务间可达性、mTLS／配对、来源年龄与延迟；设备归属唯一；不能因公网HTTP可达就认定设备可控 |

以上不增加第六个业务服务产品；宿主辅助程序、安装管理和模板属于Suite发行物，监督器属于各服务发行物。各服务可单独运行；Suite组合不替它们集中持有业务SQLite连接。macOS、Windows Server、ARM64、其他发行版及Windows上的Linux容器继续按Q68列为另行验收，不能从“可启动”推广为首期支持。

“可部署到用户服务器”指可配置主机、域名、网络与实例组合，不承诺任意主机具有直播硬件、驱动、广播发现和低时延能力。外部PostgreSQL只读排期源和Google Sheets仍保留；本地SQLite不替代这些数据源。首期每个服务实例／数据目录单活，每台设备明确一个Controller权威；Nginx轮询、容器副本数或两份数据库均不能提供设备fencing。高可用接替保留显式维护／隔离流程，不自动双活。

Nginx官方说明Windows版本仍有运行与性能限制，因此本项目继续不将其列为Windows主生产入口。Docker host networking的Linux与Desktop支持条件不同，不能用host模式解决所有发现或多播问题。SQLite WAL需要同机共享内存条件，活动库不放网络共享卷。（官方依据：[Nginx Windows](https://nginx.org/en/docs/windows.html)、[Docker host network](https://docs.docker.com/engine/network/drivers/host/)、[SQLite WAL](https://www.sqlite.org/wal.html)；具体拓扑为本项目推荐。）

## 2. DEP02：部署计划、端点与Nginx契约

推荐`DeploymentPlan`作为安装前可审阅的配置输入，与DF05不可变发布manifest分开。全部标识／整数／摘要沿SDK；计划含实际内部地址和路径，按受保护配置处理，公开诊断只给脱敏投影。

| 字段组 | 候选字段及语义 |
| --- | --- |
| 计划身份 | plan_id、revision、mode、release_manifest_ref、selected_components、plan_digest；digest只排除自身，不含秘密值 |
| 服务归属 | services[]的service_id、role、host_ref、instance_id、data_root_ref、runtime_profile_ref、issuer_ref／paired_peers；指定签发方唯一，不按URL显示名推断身份 |
| 网络入口 | management_origin、静态public_route_map、private_peer_endpoints、trusted_proxy_refs、panel_origins、editor_entry_refs、output_profiles；所有上游来自已批准配置，不能由请求URL拼接 |
| 设备与扩展 | device_assignments、module_approval_refs、egress_profiles、来源绑定；同设备跨实例重复分配拒绝，清单本身不证明旧writer退出 |
| 存储与秘密 | data／backup／log目录引用、每库归属、secret_store_ref、TLS secret_ref、backup_encryption_profile_ref；秘密不直接写JSON |
| 运行预算 | release_capacity_profile_ref、启动／关闭／采集／代理／备份预算、保留policy_ref；每个数值有单位和证据，不用无限等待掩盖未决 |
| 审阅 | 操作者、授权范围、预检报告、拟开放监听及防火墙变更、用户选择的信任安装；安装计划和执行结果分开 |

Linux管理origin推荐固定HTTPS 443；Windows本机候选`https://localhost:7443`，只监听回环，端口冲突明确改配置而非静默换端口。所有端口可显式配置，更新base URL、Cookie、Origin、证书及WS绑定后重新校验。远程Windows入口需显式绑定、可信TLS证书及访问控制，不自动开放所有网卡。实际端口和域名由部署计划固定，不写死进SDK。

| 入口 | 路由和权限规则 |
| --- | --- |
| 管理origin `/`及GUI页面 | 只发布GUI静态制品；SPA回退限定GUI页面，API／认证／内部／文件路径不能回退成200 HTML |
| `/auth/` | 只代理指定签发Controller的同名认证路径，非任意Controller轮询；会话Cookie不共享给面板／NodeCG |
| `/services/<已配置service_id>/api/v1/` | 为每个服务生成静态路由，去掉service前缀后转发已有`/api/v1/`；实际操作仍校验audience、scope、资源和当前权限 |
| 相同service路径下`/api/v1/events` | 对应已有WS端点；升级头明确转发，原Origin保留并检查，单次票据按SDK帧流程提交，不进入URL |
| `/internal/`及私有peer入口 | 公网／GUI入口拒绝；内部独立监听仅配对mTLS服务可达，不将代理证书自动等同业务peer权限 |
| 面板／兼容编辑器 | 独立origin、固定制品及C09 CSP／sandbox／握手；不把任意外部HTML放管理origin的子路径 |
| 原NodeCG dashboard | 独立管理origin和自身认证；外部控制标记，不共享LeafSeamer登录或自动代理管理员凭据 |
| 图文输出 | 仅DEP05独立只读listener及已批准资产／流，绝不通配代理NodeCG原端口 |

管理Cookie必须host-only；管理host不用于面板、输出或原NodeCG页面，不能仅靠不同端口隔离Cookie。Linux模板为各访问面配置独立host，面板按安装／制品代分配独立origin，避免版本复用可写同源storage；Windows本机GUI用localhost，面板候选用127.0.0.1加每批准安装代独立端口，TLS需覆盖对应SAN，输出另用固定只读listener。面板origin回收须先验证旧存储／通道已失效，不能只关闭窗口就重分配。额外NodeCG管理host、远程DNS和证书须显式配置验证；解析或信任不成立时相关入口不可用，不降级同源代理。跨访问面仍执行精确Origin／Host、CSRF及C09隔离，独立域名不自动授信。

管理API代理统一`proxy_next_upstream off`，不在超时／502后自动将写请求交给另一实例；不启用`non_idempotent`重试，不用登录页／缓存成功响应遮蔽服务错误。API／认证／诊断／实时输出不缓存；带hash静态资产可immutable缓存，入口HTML和配置清单重新验证，GUI发行更新不强制刷新直播中的页面或混合不同制品。不能通过service worker离线写队列绕过C10。

WS明确设置HTTP版本与Upgrade／Connection转发，配置有界空闲期限和应用心跳；代理断线只代表连接失效，不表示命令取消。请求体、header、连接及队列上限与SDK／服务profile一致，过量受理前拒绝；大备份不经过普通JSON命令大小上限。原始请求体、Authorization、Cookie、票据和完整查询串不写代理日志。服务信任的转发头只由受控代理覆盖生成；直连客户端伪造Host、Forwarded、X-Forwarded-*或身份头不得改变认证、安全origin或审计主体。内部跨主机TLS必须验证对端，不以“私网”关闭验证。

以上代理行为依据[Nginx WS](https://nginx.org/en/docs/http/websocket.html)及[proxy模块](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_next_upstream)。Nginx负责传输入口，不代替应用权限、幂等、屏障或设备仲裁；固定版本的完整配置须做实际`nginx -t`、路径及故障验收，本轮尚未生成或运行。

## 3. DEP03：宿主启动、容器与就绪

Windows由SCM启动DF02原生监督器；Linux原生由systemd管理。普通用户无需源码编译或npm安装。程序、原生库和GUI按DF05清单完整打包，固定绝对加载位置且应用账户不可改；设备模块不获得安装管理、TLS私钥或时钟管理权限。初始化由本机一次性凭据建立管理员，远程初始化只在预先保护的TLS访问下显式开启，无常驻匿名抢注入口。

本机HTTPS可使用部署者提供的可信证书；便捷安装候选提供独立本机CA和仅localhost／回环SAN的叶证书，在安装计划明确列出并由部署者选择后安装到目标用户的信任存储。默认不修改整机／其他用户信任、不将CA私钥交Controller，后续叶证书轮换沿受控安装通道；多用户和远程入口优先使用组织证书。证书到期阻止新会话，不能静默回落HTTP；证书／系统认证时间与业务NTP质量独立。

Linux Compose首期选择**整个服务容器退役后新建域**，不依赖未证明的容器内worker子树局部接替。Suite宿主辅助程序对固定plan管理容器身份、启动入口和退役证据；主业务容器不挂Docker socket、不授privileged／宿主PID／CAP_SYS_TIME。辅助程序是受限本机运维入口，只处理已批准实例和release，不接受任意镜像／命令／路径；宿主管理员仍是信任前提。

容器启动前核对固定digest、非特权隔离、旧容器及cgroup归属；关闭旧代启动入口，停止旧容器并由宿主取得完整旧组已空证据，再分配新runtime_generation／bootstrap。容器状态exited、一次kill返回或新容器看不到旧PID均不足以单独准入。旧daemon／组身份无法核对时保持protected，不删除锁后重建。容器内监督器仍执行F02账本、FENCE／OPEN／T5，宿主证明不授设备permit；远端NodeCG／设备在途不随容器退出消失。

Controller／Seamer容器不使用绕过上述检查的无限自动重启策略。故障由宿主辅助程序有界处理并留下原因；新进程进入恢复／保护，开机启动不布防、不续跑。一个Controller容器故障会影响其全部设备，部署计划须显示此故障半径；需要隔离时使用独立Controller实例和唯一设备分配，不用多个副本争同一设备。Nginx故障只影响访问，不触发设备清屏／静音或强制重启Controller。

设备协议采用模块明确的TCP／UDP通道和出站目的范围；桥接网络为默认候选，固定端口映射／发现profile按模块验收。仅经批准的Linux profile可用host networking，不能把所有设备端口映射到公网；USB／串口／MIDI／厂商驱动逐平台映射，不能凭容器可联网宣称可用。业务容器不修改宿主授时：本地provider经受限只读broker取得状态，按DF03／DF06绑定来源和采样年龄；不同运行域tick不直接相减，未经批准的容器时间profile只展示诊断，不开放绝对排期。

| 状态层 | 候选查询／字段 | 不能代表的事实 |
| --- | --- | --- |
| 进程存活 | 本机`GET /health/live`仅返回最小进程状态 | 不代表DB、身份或设备可用；不公开内部路径和版本细节 |
| API可服务 | 本机`GET /health/ready`，ready或受保护原因；管理用户查询详细system status | 不因设备离线／NTP降级／人工接管直接反复重启服务 |
| 设备可达／观察 | 现有设备观察投影，标出质量及最后合格来源 | 不等于具备写权限或资源已释放 |
| 允许控制／自动化 | 当前授权、控制、资源、存储、容量、时间及布防的各自状态 | 不压成一个“全绿”布尔；API ready可与某设备protected并存 |

健康路由和详细system status为下一版新增候选，不是当前OpenAPI已有功能。Compose启动依赖／healthcheck只安排启动顺序，不能证明上述业务条件；官方说明见[Compose启动顺序](https://docs.docker.com/compose/how-tos/startup-order/)。无法服务关键请求时ready为false，但诊断接口和关闭闸路径仍应有独立预算，不能把DB堵塞变成持续新实例竞争。

## 4. DEP04：数据、秘密、日志与诊断

每个Controller／Seamer独立本机数据目录和SQLite库，写入只属于该服务；不共享同一业务库、不以NFS／SMB承载活动WAL、不复制活动`.db/-wal`拼快照。安装程序目录、可变数据、秘密、备份和普通日志分离；容器显式命名卷／目录映射及所有者，启动看到预期库缺失时进入恢复，不能静默初始化空库。

操作系统秘密存储负责私钥、设备凭据、数据源令牌；公开配置只存secret_ref。Windows服务身份、DPAPI或其他选定封装的可迁移性必须纳入恢复profile，不能将加密blob可复制等同可解密；Linux文件秘密限服务账户读取，备份包加密不替代运行目录权限。精确密钥存储库及主机恢复封装沿身份／发行锁定，不在配置模板放示例真密钥。

日志保留旧用途：按来源、级别、文本、时间筛选及统计，明确保留策略；“关闭定期清理”不代表无限磁盘。普通日志限额轮转，关键命令／屏障／撤销／未决证据按DF04引用约束保留，不因用户清日志删除unknown。日志读取失败显示不可用，不能返回空列表冒充无事件。UTC质量、service／run／command／operation关联保留，来源／客户端序号不能伪装全局时间顺序。

`DiagnosticExport`候选字段：export_id、scope、时间范围、组件／制品引用、公开状态与reason_code、脱敏规则revision、文件清单／长度／hash、漏收项、生成结果。默认排除秘密值、会话／票据、内部地址、原始时钟证据、设备配置和数据库文件；仅授权管理人员可额外选择受保护信息，预览内容和范围后导出。诊断包不是备份，不承诺匿名，导出前须查残留可识别信息；不把任意日志正文当HTML执行。导出缺项如实标示，不写“完整成功”。

卸载默认只移除程序／启动注册，保留数据、备份和现场设备状态。清除数据、秘密或专用证书均为明确列路径和影响的独立维护操作；不递归清理用户指定的上级目录。正常直播不做VACUUM、Schema迁移或无预算大归档，磁盘压力沿F05停止新增低优先级工作并保护已受理事实。

## 5. DEP05：NodeCG只读输出profile

**固定源码事实。** 在旧提交`5d60491d7158f87fc27b564f510d321074aedac9`，三路页面均只调用`nodecg.Replicant(name).on("change", handler)`，没有Replicant赋值、sendMessage、其他NodeCG API或直接网络请求。字幕／比分读取graphicsData，排期读取scheduleData。两bundle构建同时包含dashboard，不能把整个构建目录当只读输出目录。原HTML均有`#2f2f2f`背景，字体名称存在回退，不是已证明透明或跨平台像素相同。（来源：[字幕](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/graphics/lower-third.tsx#L25)、[比分](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/graphics-package/src/graphics/scoreboard.tsx#L13)、[排期](https://github.com/ikenainanodesu/leafseamer-legacy/blob/5d60491d7158f87fc27b564f510d321074aedac9/bundles/schedule-manager/src/graphics/schedule-display.tsx#L9)、两bundle的vite.config.mjs及graphics HTML；本轮只读核查。）

**推荐实现边界。** 在Controller交付的NodeCG桥接bundle内提供独立只读HTTP／WS listener，仅导出经批准的三路投影和对应静态依赖闭包。保留旧React组件、CSS、动画、布局及显示语义；入口加载一个有限读取兼容层，再运行旧渲染组件。此层属于NodeCG兼容传输适配，不在LeafSeamer GUI自研字幕／比分／排期渲染，也不宣称支持任意NodeCG页面。

| 输出profile | 固定输入及客户端允许表 |
| --- | --- |
| legacy-lower-third | graphics-package/graphicsData的lowerThird.visible／line1／line2；只允许Replicant("graphicsData").on("change", callback) |
| legacy-scoreboard | graphics-package/graphicsData的scoreboard.visible／homeScore／awayScore；相同有限API，无其他字段 |
| legacy-schedule | schedule-manager/scheduleData的id／active／time／title／description数组；只允许Replicant("scheduleData").on("change", callback) |

每个profile以release中的固定路径与render_asset_digest绑定自己的namespace和投影，浏览器不能用查询参数选任意Replicant／bundle。仅提供读取对象和change回调，不暴露完整NodeCG SDK、Socket.IO、配置、管理cookie、key、sendMessage或写入；未知方法和字段拒绝。首快照若早于handler注册须缓存并交付注册者；提供独立数据副本，不让renderer修改共享源；重挂载须清理监听。只输出经Schema校验的纯数据，字符串按旧文本渲染，不接受HTML／脚本作为图文参数。

静态listener只服务清单中三路HTML及其hash资产闭包，禁止dashboard、源码map、目录索引、配置、扩展脚本与通配路径；默认拒绝其他路径／方法和请求体。不复用NodeCG原HTTP middleware或原socket路由。Nginx输出origin只连这个listener；去掉URL key却仍反代原端口不构成隔离。输出CSP限定本地固定脚本／样式和该profile的读取流，禁form／object／任意外连，`Referrer-Policy:no-referrer`，不设置管理cookie；实际旧样式所需许可单列核验，不靠允许任意脚本解决构建兼容。NodeCG管理端保持单独网络／认证，原生key从不传给输出页。[NodeCG官方权限说明](https://www.nodecg.dev/docs/security/)仍适用原实例，有限listener须额外负向验证，不能靠名称“只读”自证。

`OutputSnapshot`候选包含profile_id／revision、bridge_boot_id、projection_epoch、sequence、projection_digest、完整payload、source_quality；不含权限、原始内部配置或控制令牌。WS仅接受固定握手／心跳，不接受客户端业务写消息；每帧是有界完整投影，客户端可直接采用较新完整帧，序号缺口不补播历史变化。换epoch重新取baseline，重复同序不同内容拒绝。输出流只服务呈现，不作为Seamer离散trigger来源，不能把合并展示序列用于业务事件。

输出断流／数据陈旧默认保留最后完整画面，不自动清屏、归零、动画重播或写回设备；管理GUI单列renderer／来源状态与最后观察。重新取同内容baseline不人为触发动画，原组件是否因真实visible变化播放仍沿旧行为。首次无有效快照时显示旧默认／空内容并在管理面报告未就绪，不能伪造当前分数。默认保留旧背景及字体回退，透明变更另列显式profile并验收，不能暗改兼容基线。

两种访问profile：`private_render_network`仅回环或明确渲染网段可达，防火墙及TLS／代理绑定限制访问；`public_projection`显式允许公开已选图文数据，仍只有有限listener，不能转成公开NodeCG实例。私有profile无网络隔离证据时拒绝开放；原生OBS浏览器源不被要求持有LeafSeamer管理身份。输出URL只含非秘密profile路径，无bearer或NodeCG key；数据保密性由访问profile保证，公开模式不会被称为“私密链接”。后续若需互联网私有逐用户观看，另设计观看专用授权，不借用管理token。

managed_bridge的独占写证明仍须验证原生客户端／其他bundle不能绕桥；只读输出适配只解决输出浏览器的权限，不能顺带证明全实例独占。原dashboard外部入口及C10受批准兼容编辑器都保留，三者是不同访问面。桥effect_verified、NodeCG持久化、renderer已加载及观众像素分别取证。

## 6. DEP06：备份格式、分级与恢复流程

保留旧备份分级选择／历史／进度用途，重新定义范围：L0为公开模板与版本资料；L1为配置、定义、目录引用及模块批准资料（仍可能敏感）；L2为服务一致数据库、必要审计／未决证据及NodeCG数据；L3为明确选择的可恢复秘密。默认不包含L3；缺失秘密在恢复清单中列为必须重配，不把无秘密包标为可立即运行。普通日志默认不打包，可明确选范围。

所有含L1—L3的可携带备份推荐加密。候选封装为受限tar归档经age v1加密；内部manifest固定文件role／path／size／sha256、服务／database_instance、Schema／engine、备份一致点、组件／配置／secret_ref覆盖、未决清单和验证报告。外层仅保留backup_id、格式、密文字节数／hash及不含内部地址的结果索引。归档拒绝链接／绝对路径／穿越／重复项／大小写碰撞和超预算膨胀，不把解密成功直接解包到活动目录。

推荐复用官方age实现，Suite预打包小型受限加解密辅助程序调用其库，支持X25519接收者及独立口令模式，保留旧口令加密用途；不自研密码算法。秘密经专属继承通道传入，不放argv／环境／日志；禁止插件、外部命令、网络取key和任意身份类型。KDF工作量、输入／解密后字节、时间／内存有界，密码错误或认证失败不发布半个恢复集。具体库／Go工具链／制品及上限须锁定和验收；本轮只冻结候选格式与调用边界。（官方来源：[age项目](https://github.com/FiloSottile/age)、[age v1格式](https://age-encryption.org/v1)。）

加密不证明备份来自可信源；导入时核对预先可信备份目录记录／离线收据的hash和身份，来源无法证明时显示未验证并按不可信输入完整校验，禁止执行包内代码。秘密包必须显式导出且由授权人员持有解密材料，恢复机无材料则拒绝恢复该秘密，不自动复制旧session或赋权。

普通在线备份按DF04分别完成SQLite Backup至DONE、finish、关闭／同步目标、结构／外键／领域校验后发布；多个库分别一致，不冒充同一时间快照。Suite维护恢复集需固定目标、停止新增工作、退役相关writer，再取得每库一致点及未决事实；NodeCG自身持久化另备份，Replicant值或bridge ACK不能代替其数据快照。缺任一目标或秘密覆盖不完整时准确标记缺项，不覆盖上一有效备份。

恢复按`received → authenticated_or_marked_unverified → isolated_validated → plan_reviewed → old_writers_retired → prepared_protected → activated_protected → reconciled`记录；任一步未知停在保护态。授权人员审阅目标主机／服务／数据目录、版本兼容、旧实例隔离、秘密重配、未决命令和现场差异后才切换。恢复不自动连接设备作测试；隔离验证不得使用恢复出的设备地址／凭据产生业务连接。

恢复使用新database_instance／control_epoch／request_epoch及运行域；旧会话、票据、guard、已布防状态和待发排期不复活。原grant／批准记录保留历史并按当前信任重新审核；跨主机身份／证书重新绑定，不能复制旧凭据同时运行第二实例。旧库缺命令记录不证明现场未执行，恢复后先核对当前状态再明确恢复；成功步骤和unknown不重放，释放接管不等于继续自动化。

## 7. DEP07：避免多文件指针切换的安装事务

推荐细化DF05：**不以symlink、junction或通用rename作为唯一active权威**。Suite本机安装管理使用独立`installation.db`保存安装日志、信任下界和活动组合引用；它不属于可恢复业务备份，模块和普通GUI不能写。采用与该发行物共同验收的SQLite引擎及耐久配置，单写者、受保护本机目录；缺库或损坏进入修复，不新建空库绕过信任下界。

`ActiveDeployment`候选：deployment_id、generation、release_manifest_ref、组件版本／程序根、各service的data_generation_ref、配置／秘密版本引用、maintenance_operation_ref、activation_operation_id、phase。其路径都由已验证计划解析到受保护根内；安装事务只更新引用及日志，不在事务中启动进程。程序根按release_id不可变，数据按独立generation目录选择；运行时只写被选中的那一代。

1. 验证DF05发行授权、metadata、所有包字节和依赖闭包；在独立目录准备程序，不覆盖活动release。
2. 完成全目标维护并证明旧writer已退役；制作可验证维护恢复集。旧设备在途／unknown保留，不自动消除现场效果。
3. 在新的数据generation中从一致副本执行受批准迁移／恢复，校验Schema、领域约束、秘密覆盖及新的保护身份；原generation不原地改。每个候选库单独完成事务／关闭／持久结果，发布prepared记录；任何缺项不得选择部分新库。
4. 在installation.db一次事务中CAS原generation，并选择**完整release＋数据／配置generation组合**，记录activation_operation；COMMIT结果不明按原operation查询，禁止重新创建另一次激活。该事务原子的是引用选择，不是所有文件或外部设备状态。
5. 启动器取得安装选择与单实例锁，重验文件存在、digest、库归属和计划完整性后，从固定路径启动全新保护域；任一引用缺失／损坏均保持保护，不启动旧／新混合组合，也不自动回退一个“看起来完整”的目录。
6. 只读启动、能力和恢复检查通过后记录validated／completed；业务是否ready、恢复或布防独立处理。容器运行计划从同一活动记录解析固定镜像digest与卷generation，禁止手工换镜像继续旧卷写入。

Windows无需替换被占用的active程序路径，Linux无需依赖原子切换软链；新目录持久化、目标文件flush、installation.db提交及宿主存储兑现flush能力仍须平台断电试验。崩溃后未被活动记录引用的staging目录不执行，只有引用与实物全部核对才可启动。数据库事务不能证明先前文件flush或硬件持久化真实成功，证据不足保持indeterminate。

激活前可放弃候选并保留原组合，但旧域已退休时重新启动也换域且保持保护；激活后若新代已产生任何业务写，不能只回到旧数据目录。回退程序必须与当前数据Schema兼容，或执行单独获准的恢复计划并保留新代证据／未决账本；不自动丢掉新命令来恢复旧快照。TUF／release下界及撤销记录不回退，旧payload须由当前有效发行授权批准。清理release／data generation前证明无活动或恢复引用，卸载不触现场设备。

## 8. DEP08：交付包、教程与故障验收

每个正式组合须交付：精确五仓版本与协议／DB兼容矩阵；完整运行时／原生组件／GUI／模块制品；Linux Compose和原生、Windows原生模板；身份／TLS／origin及只读初始化向导；设备／时钟／容量支持profile；NodeCG桥、三路兼容资产与输出profile；备份恢复工具；日志诊断工具；来源／版权／许可证与SBOM；升级回退及故障处置说明。旧数据不迁移，只给人工重建配置建议，不迁移旧账号／令牌／执行队列。

两条主教程均按“预检→验证制品→审阅计划→配置目录／身份／TLS→保护态启动→只读连通→配置能力和授权→用户明确启用”组织。教程明确每条命令的本机修改范围，不用curl|shell或让用户自行编译补依赖；不将`compose up`、绿色health或安装完成作为可以直播的结论。其他原生路径仍提供说明，不把主教程变成唯一支持方式。

GUI实现栈、精确依赖／工具链、NodeCG修复组合、age辅助制品、平台profile数值及完整机器契约尚需最后锁定；本稿给出它们必须满足的接口与发行绑定，未假称已锁文件。部署主机、域名、签名／根密钥持有人等实际值在相应安装／发行阶段登记，不用虚构真实环境堵住设计。设计取舍审阅、实现任务和运行取证分别保留。

以下全部DPT用例均未运行；每例记录精确制品、配置摘要、平台／浏览器／容器运行时、输入与故障切点、预期／实际、日志及文件／服务／设备证据，静态检查不替代运行。

| ID | 场景／负例 | 必须观察的结果 |
| --- | --- | --- |
| DPT01 | 两主profile及Linux原生安装 | 无源码编译、固定依赖闭包，独立Controller不要求Seamer |
| DPT02 | 不支持平台／错ABI／被替换制品 | 明确拒绝，不联网补库或降级 |
| DPT03 | 同数据目录双实例／跨主机副本同设备 | 本机互斥；分机未完成隔离不准接替，不能宣称全局锁 |
| DPT04 | 公网服务可达但设备网络不可达 | 分开显示，不宣布整套可用 |
| DPT05 | 未配置service路径／请求拼接上游 | 拒绝，不形成任意代理 |
| DPT06 | API错误、404、认证失败与SPA回退 | 保持准确API错误，不返回GUI HTML伪成功 |
| DPT07 | POST已转发后超时／502 | 代理不重试，客户端查既有身份 |
| DPT08 | WS升级、心跳、代理空闲关闭 | 正确建立／失步，无票据URL，无动作重放 |
| DPT09 | GUI请求internal路径／伪造身份转发头 | 拒绝，无私有证据或授权提升 |
| DPT10 | 跨源Cookie／未知Origin／错audience | 身份隔离，面板与原NodeCG不继承管理session |
| DPT11 | 新GUI制品与旧活动页 | 固定版本资源不混用，不强制刷新直播控制页 |
| DPT12 | 大请求、慢连接、导出及日志 | 有界保护，无秘密写代理日志，无关键记录丢弃 |
| DPT13 | localhost端口占用或远程未配置TLS | 明确停止／配置，不静默换端口或开放全网卡 |
| DPT14 | 本机CA选项、证书过期和轮换 | 仅批准信任范围，失效不回HTTP、不借NTP豁免 |
| DPT15 | Compose依赖healthy但某设备protected | API与设备状态分开，不开闸或反复重启 |
| DPT16 | 容器崩溃、daemon重启、旧组证明缺失 | 旧入口关闭且退役可证才新建域，否则保护 |
| DPT17 | 直接compose重启／手动镜像换代 | 启动检查不能被跳过，不复活旧worker或permit |
| DPT18 | privileged／Docker socket／宿主时钟写权限 | 未批准组合拒绝，业务容器无运维超权 |
| DPT19 | 单Controller容器故障与多个实例 | 故障半径准确，唯一设备归属，不双活 |
| DPT20 | 设备UDP／广播／USB和Windows Docker差异 | 逐模块profile验收，能联网不当通用支持 |
| DPT21 | NTP broker失败／错域／陈旧来源 | 绝对排期保护，正常即时控制按独立条件判断 |
| DPT22 | 活动SQLite缺失、网络卷或权限错误 | 不新建空库／绕过锁，不开放写 |
| DPT23 | 日志关闭清理、磁盘满、unknown引用 | 容量有界，关键证据不被普通清理删除 |
| DPT24 | 日志读取失败和诊断导出缺项／秘密 | 显示不可用／缺项，脱敏及权限限制可证 |
| DPT25 | 三路旧页面初始快照早于listener注册 | 完整初值交付，有限API满足实际页面 |
| DPT26 | 只读listener的write／sendMessage／任意Replicant | 拒绝，原NodeCG状态不变 |
| DPT27 | 输出路径穿越／dashboard／配置／map请求 | 拒绝，不通配泄露旧构建目录 |
| DPT28 | 输出浏览器尝试获取管理cookie／key／原socket | 无管理秘密及原端口入口 |
| DPT29 | 输出帧重复冲突、乱序、换epoch／断流 | 保留最后完整画面，重建baseline，不补播旧帧或写回 |
| DPT30 | private profile未隔离／public profile展示 | 前者拒开放，后者明确公开范围且无管理写入口 |
| DPT31 | 三路背景、字体、布局、GSAP及重挂载 | 与固定兼容基线比较，透明变化不暗作默认 |
| DPT32 | 桥ACK但renderer未加载／NodeCG重启 | 不标观众像素成功，不自动清屏或补写 |
| DPT33 | L0—L3选择、秘密未选择或丢解密材料 | 覆盖和缺项准确，拒绝秘密恢复而非假成功 |
| DPT34 | age口令／接收者往返、错误密钥／篡改 | 正确恢复或明确拒绝，无半成品发布／明文秘密日志 |
| DPT35 | 超量KDF、解密膨胀、路径穿越和链接 | 在预算内拒绝，不触活动目录 |
| DPT36 | 包可解密但来源hash无可信记录 | 不把加密当来源认证，不执行包中代码 |
| DPT37 | SQLite backup未DONE／多库缺目标 | 不发布完整恢复点，不覆盖上个有效包 |
| DPT38 | 隔离恢复包含真实设备地址／凭据 | 验证期间不连接设备；旧session／arm／guard不复活 |
| DPT39 | 旧实例仍活／恢复后当前现场已有副作用 | 不准接替或补执行，不因备份缺记录推断未发生 |
| DPT40 | staged库迁移中断／部分prepared | 原组合引用不变，不选择部分新库 |
| DPT41 | 激活COMMIT前后断电／响应丢失 | 按installation operation核对一次选择，不混代启动 |
| DPT42 | 活动引用存在但文件／库损坏或缺失 | protected／indeterminate，不猜选旧目录或空库 |
| DPT43 | Windows文件占用／Linux文件未持久 | 不以rename成功冒充耐久，保留旧证据并拒开放 |
| DPT44 | 新代已有业务写后回退 | 保留新事实，不仅换旧库；信任下界不下降 |
| DPT45 | installation.db丢失／被业务备份覆盖 | 明确修复，不回到首次安装或降低撤销下界 |
| DPT46 | 安装completed／API ready但恢复未确认 | 不自动布防、续跑或操作设备 |
| DPT47 | 卸载／清理release或data generation | 默认留数据，仍被引用者不删，不清上级目录 |
| DPT48 | 两教程、全模块矩阵、来源／许可及迁移说明 | 文档、制品和实际覆盖一致；缺项不发布为全部完成 |

## 9. 下一版契约与完成条件

须归并DeploymentPlan／ActiveDeployment、宿主生命周期身份与退役查询、健康投影、DiagnosticExport、BackupManifest／RecoveryPlan及OutputSnapshot；每项需要关闭未知字段、精确scope／摘要投影／容量及正反例。DEP07是DF05平台切换的具体候选，不改变业务命令生命周期或旧draft.4文件。

C12方案成文不等于全系统设计已冻结。仍需审阅DEP01—DEP08及此前候选，锁定尚缺的工具链／协议政策，并完成全量需求—契约—用例一致性归并。DPT01—DPT48、RA／ST／RT／TP及全部模块真实验收保留在实现后执行；缺少运行证据不能假勾完成，也不以尚无业务实现为由无限阻止设计定稿。
