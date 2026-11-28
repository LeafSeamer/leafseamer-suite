# LeafSeamer

> **施工中 / Work in progress。** 新版已按依赖进入业务实现，SDK 已有可本地安装的开发包，Controller 已有持久身份、保护态启动、本机健康接口和首次管理员事务；本地HTTPS身份与GUI设备读取闭环已验证，生产认证资格与完整业务服务、完整GUI、部署组合及设备验收尚未完成，当前不提供生产可用的直播系统。

LeafSeamer 是直播软硬件控制与自动化项目。各组件独立仓库、独立版本，Suite 负责总体设计、部署组合和整套验收；首期不使用强制 Submodule。

| 仓库 | 职责 |
| --- | --- |
| [leafseamer](https://github.com/LeafSeamer/leafseamer) | Seamer 规则、状态机和排期 |
| [leafseamer-controller](https://github.com/LeafSeamer/leafseamer-controller) | 独立设备控制、模块、接管和执行 |
| [leafseamer-gui](https://github.com/LeafSeamer/leafseamer-gui) | 统一网页操作台 |
| [leafseamer-sdk](https://github.com/LeafSeamer/leafseamer-sdk) | 公共契约、客户端与模块开发接口 |
| [leafseamer-suite](https://github.com/LeafSeamer/leafseamer-suite) | 总入口、设计、兼容组合、部署与验收 |

- [当前SDK开发包：产品契约、业务客户端与独立监督通道](https://github.com/LeafSeamer/leafseamer-sdk/tree/ca0a119188b1bbf09559f12008b2d0d84b1d9a4c)
- [当前Controller开发入口：持久身份、核心监督与同源GUI服务](https://github.com/LeafSeamer/leafseamer-controller/tree/7983c38d0439a64f54b285e565ef545f692911b7)
- [GUI开发工作台：人员会话与设备读取](https://github.com/LeafSeamer/leafseamer-gui/tree/1e14019ac7f89ad56c854649161b889a3b3daa29)
- [SDK既有契约：发布原件与当前面板提供者](docs/contracts/sdk-publication-handoff/README.md)
- [完整设计稿与 Q1—Q72 决策](docs/rebirth-design.md)
- [全系统设计定稿收敛清单：具体缺口、审阅包与实施交接](docs/rebirth-design-closure.md)
- [当前归并审阅：受监督运行域、NTP 证据、公共 draft.4 与 IPC 0.3](docs/rebirth-draft4-review.md)
- [DF01：SDK 唯一契约源、固定生成链、JCS 与大整数](docs/rebirth-df01-sdk-freeze.md)
- [工具链收敛：精确候选、官方元数据与冻结验证步骤](docs/rebirth-toolchain-lock-design.md)
- [DF02：可信启动、进程纳管与运行域恢复](docs/rebirth-df02-runtime-design.md)
- [DF03：授时采集、源年龄、profile 批准与失效](docs/rebirth-df03-time-profile-design.md)
- [DF04：SQLite 表契约、事务、保留与恢复](docs/rebirth-df04-storage-design.md)
- [DF05：发布清单、信任根、升级与回退](docs/rebirth-df05-release-design.md)
- [DF06：内部身份、对象授权、来源证明与查询保护](docs/rebirth-df06-internal-trust-design.md)
- [C04：自动化表达式、发布绑定、触发仲裁与失败恢复](docs/rebirth-c04-automation-design.md)
- [C05：事件身份、快照交接、订阅 ACK 与容量保护](docs/rebirth-c05-event-sync-design.md)
- [C06：排期导入、日历、场次身份与逐步派发窗口](docs/rebirth-c06-schedule-design.md)
- [旧排期五模块能力映射与源码边界](docs/rebirth-legacy-schedule-map.md)
- [C09：模块生命周期、扩展授权与面板委托](docs/rebirth-c09-extension-design.md)
- [C10：GUI状态、接管转交、实时控制与完整编辑入口](docs/rebirth-c10-gui-design.md)
- [C11：NodeCG桥接、旧图文、编辑器与远端在途](docs/rebirth-c11-nodecg-design.md)
- [C11：OBS／ATEM全能力、传输与完成证据](docs/rebirth-c11-obs-atem-design.md)
- [C11：Mixer／DM3／WING／VB音频契约与184项来源清单](docs/rebirth-c11-audio-design.md)
- [C12：部署入口、只读输出、备份恢复与维护切换](docs/rebirth-c12-deployment-design.md)
- [旧设备八模块能力、型号与完成证据映射](docs/rebirth-legacy-device-map.md)
- [旧自动化、图文、日志、备份与持久化映射](docs/rebirth-legacy-system-map.md)
- [实施前技术选型：SDK、代码生成、认证、SQLite 与时钟](docs/rebirth-technology-selection.md)
- [平台冻结：Windows 运行域、NTP 误差界与原生制品](docs/rebirth-platform-freeze.md)
- [整体审阅及待落实事项](docs/rebirth-review.md)
- [实施前契约与验收交付清单](docs/rebirth-readiness.md)
- [首闭环 SDK/API 与执行契约草案](docs/rebirth-first-loop-contract.md)
- [可校验 Schema／OpenAPI 与正反例](docs/contracts/README.md)
- [F01—F07 进度及命令／接管边界审阅](docs/rebirth-contract-review.md)
- [F02／F03：IPC、唯一写出口、SQLite 与故障验收](docs/rebirth-f02-f03-design.md)
- [F04／F05：身份撤销、NTP 时间边界与容量保护](docs/rebirth-f04-f05-design.md)
- [F06／F07：OBS 完成证据、失败依赖证明与恢复并发](docs/rebirth-f06-f07-design.md)
- [路线图](docs/ROADMAP.md)
- [旧版交接记录](docs/LEGACY_HANDOVER.md)
- [开发记录](DEVELOPMENT_MEMO.md)

新版运行库采用 SQLite，支持指定 NTP 时间源，GUI 脱离 NodeCG；播出图文通过可选 NodeCG 桥接提供。完整功能仍在实施，实际完成范围以上述统一收敛清单为准。五仓的 `rebirth` 已通过 merge commit 合入 `main`，后续在 `main` 推进设计与实施。

## Linux 管理入口

`dist/linux-ingress.mjs` 为 C12 的 Linux 部署生成 Nginx 配置。生成器读取受保护的 `leafseamer.linux-ingress/1` 计划，核对 GUI 清单及其资产摘要，再将明确配置的服务写成静态路由。计划、证书、私钥和生成结果放在本机部署目录。GUI 目录应由部署层固定在已核验的制品代，并允许 Nginx Worker 读取。

| 计划字段 | 内容 |
| --- | --- |
| `format` | `leafseamer.linux-ingress/1` |
| `management` | `address`、`port`、`host`、`certificate_file`、`private_key_file`。监听地址为 IP，管理源使用证书覆盖的 DNS 主机名 |
| `issuer_service_id` | 唯一负责管理登录的 Controller 服务 ID |
| `services` | 每项提供 `role`、`service_id`、`database_instance_id`、`address`、`port`、`server_name`、`ca_file`。地址为固定 IP，`server_name` 绑定上游 TLS 身份 |
| `gui` | `directory` 和 `manifest_sha256`。站点须绑定签发 Controller 的身份，Seamer 配置须采用管理源下对应的 `/services/<service_id>` |

```sh
node dist/linux-ingress.mjs --config /srv/leafseamer/ingress-plan.json > /srv/leafseamer/runtime/nginx.conf
nginx -t -p /srv/leafseamer/runtime/ -c /srv/leafseamer/runtime/nginx.conf
```

已配置服务使用 `/services/<service_id>/api/v1/` 和逐服务发现路径。现有 GUI 使用的同源 `/api/v1/` 固定到签发 Controller，认证路径仅转发列出的会话与令牌接口。当前部署入口对代理到应用的 TLS 强制检查证书及名称，内部配对与本机管理接口留在独立信任边界。应用继续负责权限、幂等和设备屏障。

代理保留请求的 Origin。Controller 上游收到管理源的 Host，Seamer 上游收到计划里它自己的监听地址及端口。Seamer 的公开 API 配置须把管理源列入 `allowed_origins`。

Linux Controller 与 Seamer 的安装包都提供 `start-protected-ingress` 命令。将各服务配置中的上游地址、端口及数据库身份与 `services` 条目对应，并把 `origin` 固定为计划的管理 HTTPS 源。只从代理网络访问后端监听。保护态路径用于验证部署，登录、配对和业务操作需要可信运行装配。

[Linux 代理联调用例](test/linux-ingress.integration.mjs) 使用真实 Nginx、临时证书及独立 HTTPS 测试上游，验证静态交付、路由、握手、请求头、上游故障和写请求转发。[Linux 实际服务联调用例](test/linux-service-ingress.integration.mjs) 通过安装包 CLI 启动双服务，验证代理后的服务身份、保护响应、正常停止及临时库状态。完整 Compose 装配、真实服务信任与设备启动继续按 C12 验收。

### Docker Compose 保护态部署

`dist/linux-compose.mjs` 从 `leafseamer.linux-compose-protected/1` 计划生成双服务启动配置、Nginx 配置和 `compose.json`。先分开初始化并显式迁移两个服务库，再准备按实际服务身份构建的 GUI、三套 TLS 材料和已加载至本机的 Linux amd64 镜像。业务镜像须提供 `/usr/local/bin/node` 和 `/opt/leafseamer/dist/cli.mjs`，以及锁定的运行依赖。代理镜像须提供 `/usr/sbin/nginx`。

| 计划字段 | 内容 |
| --- | --- |
| `format` | `leafseamer.linux-compose-protected/1` |
| `subnet` | 独立且无冲突的 RFC 1918 IPv4 CIDR，前缀 16 至 29 |
| `management` | `bind_address`、`host`、`port`、`certificate_file`、`private_key_file`。`host` 为管理证书覆盖的 DNS 名，`bind_address` 是宿主发布地址 |
| `controller`、`seamer` | `image`、`uid`、`gid`、`address`、`data_dir`、`service_id`、`database_instance_id`、`server_name`、`certificate_file`、`private_key_file`、`ca_file` |
| `nginx` | `image`、`uid`、`gid`、`address` |
| `gui` | `directory` 与 `manifest_sha256`，沿用上面的 GUI 清单 |
| `cgroup` | 可选。提供本机 Docker 的 `driver`（`cgroupfs` 或 `systemd`）和新启动代的 UUID v4 `generation_id`。需要固定容器私有 cgroup 证据时设置 `namespace` 为 `private` |

镜像填写 `仓库@sha256:摘要` 或预装镜像的 `sha256:镜像ID`。子网内为三个容器分配不同地址，避开网络、广播和默认网关地址。数据目录、GUI 和 TLS 路径使用独立的绝对路径。数据目录由对应服务的 UID/GID 写入，三个私钥分别授予对应容器进程读取权限。输出目录的父目录应已存在，输出目录由生成器创建。

```sh
node dist/linux-compose.mjs --config /srv/leafseamer/plan.json --output /srv/leafseamer/generation
docker compose -p leafseamer -f /srv/leafseamer/generation/compose.json config
docker compose -p leafseamer -f /srv/leafseamer/generation/compose.json up -d --no-build --pull never
docker compose -p leafseamer -f /srv/leafseamer/generation/compose.json stop
```

只有 Nginx 发布管理端口。业务容器加入内部桥接网络，分别挂载自己的可写数据库目录和只读 TLS 文件。Compose 使用固定镜像、非 root 用户、只读根文件系统和禁止提权设置，关闭自动重启。该路径运行保护态 HTTPS，可信运行域、宿主认证时钟和首次配对由后续受信装配提供。[Docker Compose 服务配置](https://docs.docker.com/reference/compose-file/services/)、[Docker Compose 网络配置](https://docs.docker.com/reference/compose-file/networks/)

[Compose 联调用例](test/linux-compose.integration.mjs) 使用 `LEAFSEAMER_COMPOSE_CONTROLLER_IMAGE`、`LEAFSEAMER_COMPOSE_SEAMER_IMAGE`、`LEAFSEAMER_COMPOSE_NGINX_IMAGE` 指定本机镜像，以 `LEAFSEAMER_COMPOSE_GUI_ROOT` 指向构建好的 GUI。用例运行在独立 Compose 项目，使用临时数据库与证书。

已启用定时模拟器派发的联调可追加 `LEAFSEAMER_TEST_COMPOSE_SIMULATOR_RECOVERY_RECONCILIATION=1`。用例在临时 Seamer 库注入原结算失败，随后经人员批准核对已完成的写入。停机后对照两端的命令终态、恢复结算和活动槽释放，并验证模拟器只收到一次写入。

### Linux 父组退役观察

设置 `cgroup` 后，生成器按启动代和服务配置不同的 Docker `cgroup_parent`。宿主需采用与计划相同的 cgroup 驱动，并保留观察所用父组。systemd 驱动采用独立的顶层 slice。[Docker cgroup 父组](https://docs.docker.com/reference/cli/dockerd/#default-cgroup-parent) · [systemd slice](https://www.freedesktop.org/software/systemd/man/latest/systemd.slice.html)

`dist/linux-cgroup-retirement.mjs` 提供只读宿主接口。部署装配从本机取得 `readLinuxCgroupHost()`，对已核对的容器主进程取得 `readLinuxCgroupLeader(pid)`，在进程存活时用这些事实和固定角色、驱动、启动代调用 `openLinuxCgroupRetirement()`。观察绑定原父组描述符，并复核启动身份、命名空间、组 inode、主进程启动时刻和归属。`observe()` 返回 `populated`、`empty` 或 `indeterminate`。只要子组仍有活进程，父组仍为 `populated`。组丢失、换代或已绑定主进程移出原组时，当前观察锁存为 `indeterminate`。[Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html#un-populated-notification)

受信退役还需由宿主生命周期装配证明旧启动入口已关闭，并把观察写入该运行域的退役记录。本接口提供实时内核事实，消费方使用后调用 `close()`。在专用 Linux 测试宿主上可用 `LEAFSEAMER_TEST_CGROUP_HOST=1` 运行 [cgroup 联调用例](test/linux-cgroup-retirement.integration.mjs)，附加 `LEAFSEAMER_TEST_SYSTEMD_CGROUP=1` 验证临时 systemd 单元。

### Linux 宿主启停账本

可信首次安装流程在确认无旧运行代后，调用 `openInstallationStore(...).initializeLinuxDeploymentJournal()`，创建与安装身份绑定的 `linux-deployment.db` 和标记。此账本有独立的 SQLite 事务和追加记录，既有安装库沿用原 Schema。日常打开使用 `openLinuxDeploymentJournal({launch, endpointClosure})`。两个同步回调由可信宿主装配提供，且应使用有界的本机运行时操作。[SQLite 事务](https://www.sqlite.org/lang_transaction.html) · [SQLite 同步设置](https://www.sqlite.org/pragma.html#pragma_synchronous)

- `start(intent)` 接收 `generation_id`、`driver`、`compose_digest` 和两端服务及数据库身份。先持久预留，再调用 `launch`。回调返回两端已核对的本机 PID，账本绑定其实际父组。
- `closeIntake(generationId)` 持久关闭旧代启动入口。宿主停止旧运行后调用 `observeRetirement(generationId)`。两个原组均为空时才查询端点，`endpointClosure` 返回已核对的端点证据摘要，待核对时返回 `null`。
- `current()` 和 `lookup(generationId)` 查询原记录。旧代有活进程、端点未关闭或结果未证实时，新的 `start` 被拒绝。重开后仅可重新绑定仍存活且身份和组完全一致的原成员。丢失原观察时保持未证实。关闭顺序为启停账本、安装账本。

宿主账本联调使用实际 cgroup 和本机 Unix socket 验证停机屏障与重开恢复。[宿主账本联调用例](test/linux-deployment-journal.integration.mjs)

### Docker 宿主启停

可信宿主装配可从 `@leafseamer/suite/linux-compose-host` 调用 `openLinuxComposeHost({installationDirectory, planFile, generationDirectory})`，再调用 `start()`、`current()`、`retire()` 和 `close()`。宿主需预建并保留计划中的两个 cgroup 父组，安装目录需已显式初始化启停账本。默认使用 `/usr/bin/docker`、`/run/docker.sock` 和 `/run/docker.pid`。明确配置本机 Unix socket 和 PID 文件时，使用 `socketPath` 与 `pidFile`。装配用户须能核对 daemon 的进程和 socket 归属。

已安装的 Suite 提供 `leafseamer-compose` 命令。以 Linux 宿主 `root` 运行，使用仅 `root` 可访问且已初始化的安装目录、批准的部署计划和已生成的运行代目录。`--controller-dist` 指向批准的 Controller 制品目录。命令用部署计划中的制品引用校验本机 Node、构建清单和原生时钟文件，然后启动受监督组合。

```sh
leafseamer-compose run --installation /var/lib/leafseamer --plan /etc/leafseamer/plan.json \
  --generation /var/lib/leafseamer-compose/generation --controller-dist /opt/leafseamer/controller/dist
leafseamer-compose status --installation /var/lib/leafseamer
```

`run` 在前台持有监督通道和安装账本。`SIGINT` 或 `SIGTERM` 关闭本代入口并请求退役，终端输出最终账本阶段。通道意外结束时，命令尝试按原证据退役并以非零状态退出。前台进程结束后，可用同一计划和运行代目录执行 `leafseamer-compose retire` 核对或续接原代退役。只有得到 `retired` 后才能启动新的运行代。`status` 在运行中经安装目录下仅管理员可访问的套接字读取账本，在停止后直接读取账本。`running` 表示已登记的运行代，应用可用性以各自就绪状态为准。

启动时重新生成并核对固定 Compose 文件，检查本机 daemon、预载镜像、空父组及项目清单，再用独立项目名启动保护态服务。停机先在账本关闭旧入口，只处理原记录内的容器和网络。项目端点已退出且两个原父组均为空后，才写入退役结果。临时检查失败可重试原代，未知容器或网络进入原项目时拒绝停机命令。若重开后无法重获原活进程观察，继续保留未证实状态。[Docker Compose 启动](https://docs.docker.com/reference/cli/docker/compose/up/) · [Docker Compose 停机](https://docs.docker.com/reference/cli/docker/compose/down/)

在与测试进程同宿主的隔离 daemon 上，向 [Compose 用例](test/linux-compose.integration.mjs) 同时提供 `LEAFSEAMER_TEST_DOCKER_SOCKET` 和 `LEAFSEAMER_TEST_DOCKER_PID_FILE`，可运行经过启停账本的双代联调。普通计划使用保护态入口，带 `bootstrap` 的计划使用下述 DF02 受监督入口。

启用 `cgroup.namespace=private` 时，宿主从实际核心进程核对非 root UID／GID、`no_new_privs` 及空权限集。该进程的只读 cgroup 挂载必须指向宿主上与 Docker 容器 ID 匹配的成员组。设备号、inode、挂载 ID 和命名空间身份随 `runtime_binding.core_containment` 持久保存。退役操作在停止仍运行的核心容器前复核这些证据。这个入口使用 Compose 的容器私有 cgroup 选项。[Docker Compose 容器规范](https://docs.docker.com/reference/compose-file/container-spec/)

#### Compose 专用引导通道

`npm run build -- --linux-member` 同时构建 `dist/native/leafseamer_linux_compose_channel`。可信装配可从 `@leafseamer/suite/linux-compose-channel` 打开 `openLinuxComposeChannel({directory, uid, gid, timeoutMs})`，等待 `ready` 后将该次启动专用目录只读挂入目标容器。容器入口工具以 `connect <容器内套接字绝对路径> <宿主所有者 UID> -- <固定核心入口和参数>` 调用。它须为容器 PID 1，以计划中的非 root 账户运行，核对 Unix 服务器凭据后将连接作为 FD 3 交给核心。

宿主用 `accept({driver, generationId, role, host, expected})` 提供已从固定 Compose 运行代取得的 `core_containment`。发布通道前核对内核对端 PID、UID、GID，并重新核验当前容器 cgroup 及挂载身份。每个通道只使用一次。关闭宿主数据流或调用 `close()` 会终止中继，`ended` 在中继退出并清理仍与原 inode 一致的套接字后完成。实际 Compose 用例验证了同 UID／GID 的错容器拒绝、FD 3 数据往返和宿主断连退出。[Linux Unix socket 手册](https://man7.org/linux/man-pages/man7/unix.7.html) · [通道联调](test/linux-compose-channel.integration.mjs)

#### Compose DF02 准入

在私有 cgroup 计划中增加 `bootstrap` 对象，分别填写 `controller` 和 `seamer` 的 `leafseamer-core-bootstrap-policy/1`。策略固定服务和数据库身份及制品摘要。生成配置会为每个核心建立独立的只读通道挂载，固定 `contained-compose-linux` 入口。root 管理的宿主向 `openLinuxComposeHost` 提供同宿主原生时钟 `source`，并调用 `startSupervised()`。宿主只向已核对的原容器交付通道，先在启停账本持久写入 `closed` 准入回执，再将其发给核心。核心在自身库保存同一回执后开启保护态 HTTPS。通道丢失会关闭两端通道。

私有 cgroup 计划可配置 `reference_providers`。在 `image.file` 和 `image.sha256` 固定本机 Linux 授时提供者制品，分别给 `controller` 和 `seamer` 配置独立宿主 `uid`、`gid`。管理员在两个父组下各预建一个空的 `reference` 子组，将其保留至该代退役完成。启用需要宿主账本修订 `3`、Controller Schema `110` 和 Seamer Schema `34`。已有库按各组件的显式迁移入口升级。

`startSupervised()` 返回两端的 `referenceAdmissions`。宿主在专用套接字核验对应核心的 PID 和账号，交付原准入并转接受监督的提供者。各核心先写入原运行绑定，再完成连接握手，随后开启保护态 HTTPS。采集连接失联会关闭该代的两个核心。退役后可通过 `referenceAdmission(role)` 读回原件。[Compose 宿主入口](src/linux-compose-host.mjs)

切换运行代时，先在原宿主账本中完成旧代退役。宿主核对原提供者进程已退出、原 cgroup 为空及旧容器端点已关闭，再保存退役证据。新核心通过专用通道读取同一服务和数据库的原证据，在新认证时钟域内，从确认收到退役证据的时刻起等待完整的轮询间隔或退避期限。等待完成后使用新的请求和采集原件生成锚点。旧证据缺失、身份不符或存在未知的发送结果时，来源保持保护态。[Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)

使用新批准替换授时来源时，先将 Controller 和 Seamer 数据库分别显式迁移到 Schema `111` 和 `35`，再使用绑定新批准的新运行代。恢复记录会保存上一来源摘要、原退役凭证、来源槽和新批准。首次预约还需核对该记录及其等待截止。原来源和新来源的适用退避继续生效，旧采集和锚点保留原件。

启用受保护的业务授时采集时，另配置 `clock_evidence` 与 `reference_providers.capture`。后者的 `controller` 和 `seamer` 分别提供 `directory` 和 `approval_sha256`，每个目录专用并只读挂载。目录归 root 所有，属组为对应核心 GID，权限 `0750`。目录内的 `approval.json` 和 `capture.key` 归同一所有者及属组，权限 `0440`，密钥使用独立的 32 字节随机值。

`approval.json` 采用规范 JSON `leafseamer-linux-reference-capture-approval/1`，使用 `scope.service_id`、`scope.database_instance_id` 和 `provider_digest` 绑定服务与制品。`approval_id`、`approval_revision` 和 `capture_key_id` 标识批准及归档密钥，`not_before_ns` 与 `expires_ns` 采用 UTC 纳秒十进制字符串。`archive_budget_bytes` 为累计归档预留上限，最多 1 GiB，至少容纳一次采样。

| `network.authentication` | 端点配置 | 单次归档预留 |
| --- | --- | --- |
| `trusted_network` | 已批准的数字端点 `endpoint`。 | 16 KiB |
| `nts` | `key_endpoint` 为数字 TCP 端点，`server_name` 为证书校验名，`root_der` 为批准 CA 的无填充 base64url DER 数组。`default_target` 填写 `name`、`port`，须在 `targets` 中有对应项。每项另带固定数字 UDP 端点 `endpoint`，其端口与 `port` 相同。`name` 可用 DNS 名或该端点的数字 IP。 | 112 KiB |

有效的独立认证时钟限定采集授权期限。移走或改写批准文件会使当前运行停止后续采集。采集结果写入加密归档，同运行域内按至少 16 秒的间隔发起下一次采集。格式 `/1` 用于诊断归档。

NTS 采集先以当前独立认证区间校验证书，再对获准的 UDP 端点进行有认证的采样。密钥协商材料和请求、响应原件存入加密归档，核心还会核对两份 UDP 原件的唯一标识和 NTP 请求关联。NTS 认证失败时停止该次采集。证书私钥由授时服务器持有，安装批准只包含 CA 证书。 [IETF RFC 8915](https://www.rfc-editor.org/rfc/rfc8915.html)

需要业务 UTC 锚点时，采用 `leafseamer-linux-reference-capture-approval/2` 并增加 `reference`。当前两种采集模式均支持本配置。NTS 需要采用支持 `nts-bootstrap/1` 的提供者制品。每个服务保留自己的批准、采集和认证时钟原件。验收该授时环境后，再填写以下字段。

| 字段 | 配置 |
| --- | --- |
| `utc_mode` | `normal_utc_no_smear`。来源资格应覆盖 UTC 实现、无平滑和失效监测。 |
| `independent_source_ref` | 与本服务认证时钟策略的 `system_time_source_ref` 一致。审核时确认其独立于业务采集报文和采集器。 |
| `source_provenance_ref`、`monitoring_ref`、`platform_qualification_ref` | 分别引用上游来源、环境监测要求和平台时钟包络的批准原件。引用包含 `id`、`revision` 和 `digest`。 |
| `elapsed_error_ppm`、`span_quantization_ns` | 经批准的单调计数误差包络。速率使用 1 至 1000 的整数，量化使用 1 至 1000000 的纳秒字符串。 |
| `t2_error_ns`、`t3_error_ns`、`tref_error_ns` | 接收、发送和参考时间戳的误差上界，各采用大于 0 且不超过 1 秒的纳秒字符串。 |
| `max_upstream_age_ns`、`max_half_width_ns` | 上游年龄与 UTC 区间半宽上限，分别大于 0 且不超过 24 小时与 1 秒，采用纳秒字符串。 |
| `leap_schedule` | `bulletin_ref` 引用已批准的公告原件，`valid_from_ns` 和 `valid_until_ns` 界定其覆盖期。`events` 为按时序排列的公告事件，每项包含 UTC 整秒的 `utc_ns` 和整数 `direction`（1 或 -1）。 |

两端用当前独立认证区间裁定 NTP 时代，再由报文时间戳与批准误差计算条件 UTC 区间。公告覆盖期、事件前后各 24 小时、认证资格和批准期限一并限制锚点的发布与使用。通过全部检查才在原报文归档的事务中保存锚点与证据包。NTS 证据关联此尝试实际签发的四次认证读取、已验证的证书链摘要和密钥协商原件摘要。业务证据包通过 `authentication.bootstrap_ref` 引用完整的本地证据。采样过期、认证时钟失效或批准撤下后，当前服务停止提供相应资格。监测发现上游或部署前提失效时，由宿主管理员撤下批准。更新批准使用新的受监督运行代。实地授时环境及适用设备出口保护仍待验收。[授时模型与资格要求](docs/rebirth-df03-time-profile-design.md)

核心准入需要启停账本 Schema 2 或更高版本。首次初始化采用 Schema 3。已有 Schema 1 可继续运行普通保护态计划，也可在停机时显式升级，保留身份标记与原启停记录。`admission(role)` 查询已持久保存的核心准入原件。[Compose 联调](test/linux-compose.integration.mjs)

私有 cgroup 与 `bootstrap` 同时启用时，可增加 `clock_evidence`，分别为 `controller` 和 `seamer` 填写 `exchange_directory`、`policy_digest`、`public_key_file` 与 `public_key_sha256`。两个摘要均使用 `sha256:<64 位小写十六进制>`。公钥为 root 管理的 Ed25519 PEM，须允许核心账户读取。两个交换目录互不重叠，各由相应核心的 UID/GID 拥有，权限为 `0700`，祖先目录由 root 管理。生成器分别生成服务的 `/2` 配置，配置与公钥只读挂载，交换目录仅挂入相应核心。激活前宿主复核原公钥与目录身份。

闭锁准入后，核心在交换目录发布绑定当前启动和时钟域的 `challenge-<service_boot_id>.json`。宿主的受信签发器用该挑战和批准的 Chrony 配置生成签名原件，由宿主将服务可读的 `evidence-<service_boot_id>.json` 原子放入相应目录。签发私钥留在宿主的受保护目录。核心核对内核已禁用系统睡眠及当前原件的签名与时钟域，持续保存采集。证据到期会在该域锁存认证时钟故障。[Chrony 签发与 Compose 联调](test/linux-compose.integration.mjs)

#### Compose 首次配对

为启用 Compose 配对，在上述监督和认证时钟计划中加入 `pairing`。其 `controller` 和 `seamer` 项各有宿主绝对 `directory` 与 `files`，后者将文件名映射到 `sha256:` 摘要。主配置名为 `profile.json`，采用对应服务已有的 `/2` 配对格式。配置引用 `/etc/leafseamer/pairing/` 下的已列出 PEM 文件。文件由 root 管理，TLS 私钥权限为 `0640`，组为该核心的 GID。每个文件独立只读挂入该核心。文件摘要进入运行代的 Compose 配置，宿主在交付准入前核对。

每个核心在自身后端地址的 `9443` 监听服务间 mTLS，证书需覆盖配置中的服务端身份。Controller 配置中的 `https.origin` 为 `https://127.0.0.1:8444`，Seamer 的 `public_api.host` 和 `port` 为 `127.0.0.1` 与 `8444`。本机管理 TLS 证书须覆盖回环地址。Controller 的配对管理与 Seamer 的本机权限管理从各自容器内调用。Nginx 的管理源处理人员登录，后续请求使用面向指定服务的访问令牌。

首次部署时设置 `pairing.seamer.await_first_pairing: true`，在 Seamer 配置中预先固定 `public_api.binding_id`，将 `first_pairing_authorization_id` 设为 `null`。管理员从运行中 Controller 的回环使用 `pairing-admin` 登记配对，导出与固定绑定一致的一次性授权。宿主管理员用原子重命名将授权放入该运行代输出目录下的 `first-pairing/authorization.json`。文件归 root 与 Seamer 的 GID 所有，权限为 `0640`。目录只读挂入当前 Seamer，核心采用后在原 Controller 启动域及原期限内完成双向证明和激活。后续运行代省略 `await_first_pairing`，沿用持久化配对。[实际 Compose 首次配对联调](test/fixtures/linux-compose-first-pairing.mjs)

在受监督的双服务首次配对用例上设置 `LEAFSEAMER_TEST_COMPOSE_PAIRING_RESTART=1` 可验证正常停机后重启。联调沿用原业务库和配对配置，在新的运行代签发定向令牌并读回原草稿。处于原有效期内的旧启动写上下文应被拒绝，新上下文可保存另一份草稿。两代退役后，临时库中应只有一份配对完成记录和两代各自成功保存的草稿。

首次配对联调可附带浏览器验收。为现有联调环境设置 `LEAFSEAMER_TEST_COMPOSE_BROWSER`、`LEAFSEAMER_TEST_COMPOSE_PLAYWRIGHT` 和 `LEAFSEAMER_TEST_COMPOSE_SCREENSHOTS`，分别提供 Chromium 可执行文件、Playwright 模块和截图输出目录的绝对路径。浏览器从同一 Nginx 管理源登录、续期并创建草稿。测试在浏览器端丢弃已提交的成功响应，重载后查回原草稿并核对 SQLite 中仅有一条定义。[Compose 浏览器验收](test/fixtures/linux-compose-browser.mjs)

需要发布策略时，在 Seamer 的 `profile.json` 中设置 `publication_policy.approval_file` 和 `approval_sha256`。审批文件为 `/etc/leafseamer/pairing/` 下独立的 JSON 文件，其相同摘要必须列在 `pairing.seamer.files` 中。Compose 单独只读挂载审批文件。Seamer 核对当前库身份、策略引用、认证时钟期限和审批原件，并在编译前核对绑定批准。运行中撤下或改写审批会锁存撤下状态。联调可设置 `LEAFSEAMER_TEST_COMPOSE_PUBLICATION=1` 验证拒绝路径。

Linux 布防预检使用可选的 `arm_admission_policy`。其 `approval_file` 和 `approval_sha256` 指向同目录下另一份独立、只读挂载的 JSON 文件，原字节摘要也列入 `pairing.seamer.files`。文件采用规范 JSON，`format` 为 `leafseamer.arm-admission-approval/1`，包含 Seamer 的 `scope`、`profile_id`、`revision`、资格证据的 `qualification_ref`、允许的 `controller_scopes`、认证时间半开区间 `not_before_ns` 和 `expires_ns`。资格应覆盖整个允许规模。 `limits` 固定编译程序字节数、预检证据字节数、目标 Controller 数、设备动作数和来源数，键为 `artifact_bytes`、`preflight_bytes`、`controller_targets`、`device_actions` 和 `sources`。 `capacity` 与单次 `required` 均以十进制字符串给出 `logical_bytes`、`queue_slots`、`rows` 和 `work_units`。额度按逻辑资源计量，物理磁盘、排队和故障保障须取得相应环境证据。

启用 `public_api.local_run_approvals` 后，人员可在 Seamer 回环 TLS 的 `/auth/local-run-approvals/v1` 使用 `create-arm-context` 和 `record-arm-preflight`。令牌须定向 Seamer，持有当前 `request.create`、`run.arm` 和 `run.read`，且人员认证仍在近期窗口内。先用 `ttl_ms` 和 `max_unique_requests` 建立上下文，再用 `run_id`、`expected_revision` 和 `context_id` 记录一次预检。每份原件占用一次上下文额度。 `can_arm` 只描述该期预检，额度持有与运行状态转换由后续布防事务完成。[Compose 预检联调](test/fixtures/linux-compose-first-pairing.mjs)

使用 `observe-and-arm` 在一次请求内记录当前预检并受理布防。请求包含 `run_id` 和 `reservation`，后者包含 `expected_run_revision` 及 `context`。 `context` 包含 `context_id` 和 `idempotency_key`。原子请求占用一次上下文额度。持有当前合格预检时，也可以在原期限内用 `arm` 提交同样的上下文和 `preflight_ref`。成功受理占用激活槽和额度，运行保持 `disarmed`。

使用原 `operation_ref` 调用 `complete-arm`。目标回执尚未采用时，可在原授权期限内重查 `PREPARATION_PENDING`。完成事务核验当前目标资格并封存接收基线，然后把运行置为 `armed`。同键重投受理请求及重复完成操作可查回原结果。[Compose 布防联调](test/fixtures/linux-compose-first-pairing.mjs)

### Linux 原生成员创建

在 Linux 构建机运行 `npm run build -- --linux-member`，将原生创建工具及其源码和制品摘要纳入 `dist/native/`。由可信宿主装配预先登记启动意图并固定受保护的 ELF 制品、空 cgroup v2 子组及两者的设备号和 inode。装配需拥有目录访问、创建子进程和切换到指定非 root UID／GID 所需的权限。工具使用调用者原有权限，发布文件采用普通可执行模式。

```text
leafseamer_linux_member GROUP GROUP_DEVICE GROUP_INODE IMAGE IMAGE_DEVICE IMAGE_INODE UID GID -- [ARG ...]
```

装配为子进程提供已连接的 AF_UNIX 流 socket 作为 FD 3，并保留另一端作为引导通道。工具以 `clone3` 在目标 cgroup 中创建成员并保留 pidfd。它先核对成员归属并输出 JSON `created_closed`，调用者登记该观察后可在 stdin 发送单字节 `R`。组路径、成员归属及控制权限复核后，工具通过已打开的 ELF 描述符执行制品，再输出 `executed`。stdin 应保持连接至正常退出，关闭会使工具退出并触发直属成员的父进程死亡保护。创建受阻、组被占用或释放前发现漂移时拒绝执行。

后续装配还需完成 DF02 身份证明、准入回执和旧子树退役。执行成功只建立成员观察。可在专用 Linux 测试宿主编译 [成员夹具](test/fixtures/linux-member.c)，将其绝对路径放入 `LEAFSEAMER_TEST_NATIVE_MEMBER_FIXTURE`，再用 `LEAFSEAMER_TEST_NATIVE_CGROUP=1` 运行 [原生创建联调](test/linux-member.integration.mjs)。[Linux clone3 手册](https://man7.org/linux/man-pages/man2/clone.2.html)

可信装配可通过安装账本先显式调用 `initializeLinuxMemberJournal()`，再用 `openLinuxMemberJournal(assertCurrent)` 打开独立原生成员启动账本。其 `launch(intent)` 使用固定的服务、数据库、运行代、启动标识、角色、UID／GID、绝对制品路径与 SHA-256，以及非敏感 argv。父组沿现有命名规则，核心成员放入预建的 `core` 子组。装配提供同步的 `assertCurrent(record)` 核对有效批准，返回 `true` 才继续。

启动账本在创建前保存 `reserved`，观察到原生成员后保存 `created_closed`，复核后先保存 `release_requested` 再发送释放字节。`launch(intent)` 返回 `executed_closed` 及一次性的原始引导流。相同意图的重试只返回原记录，其他同角色启动需先取得原成员退役证据。账本关闭时关闭控制和引导流，原记录可通过 `lookup(launchId)` 继续查询。[启动账本联调](test/linux-member-journal.integration.mjs)

启动实际 Linux Controller 或 Seamer 时，可信装配调用 `admit(intent,{policy,source})`，其中 `source` 为同宿主、同时间命名空间的已核验 Linux 原生时钟。宿主在专用流完成既有 SDK 的 Assignment、Proof 和 Admission。它复核实际进程、cgroup 和期限，先在原账本保存闭锁回执才发送 Admission。成功结果携带 `detail.admission`，Suite 保持引导流并监听失效。两服务分别在本地业务库核对并保存回执，再开启保护态回环监听。业务授权和宿主授时资格需要独立验收。[双服务准入联调](test/linux-core-bootstrap.integration.mjs)

退役前调用 `closeIntake(launchId)` 写入关闭记录并关闭受控通道。随后可用 `observeRetirement(launchId)` 查询，或显式调用 `terminateRetirement(launchId)` 对已核验的原父组执行 `cgroup.kill`。保留原父组及 `core` 子组直至退役完成。只有原子树整体无活进程并持久记录 `retired`，新运行代才可进入同角色闭锁启动。组被替换、宿主或原成员身份不可证时保持保护。只留下启动预留的未知尝试仍需取得独立恢复证据。新账本使用 Schema 2，已有 Schema 1 可继续查询，采用退役前须显式调用 `upgradeLinuxMemberJournal()`。升级保留原身份标记和原启动记录，普通打开时仍按原版本读取。退役证据只用于进程接替，设备在途事实及资源释放继续使用各自验收条件。[退役联调](test/linux-member-retirement.integration.mjs) · [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)

可信 Linux 原生装配可从 `@leafseamer/suite/linux-native-host` 调用 `openLinuxNativeHost({installationDirectory, source})`。安装目录由宿主装配账户持有，启动计划和程序制品由 root 管理。安装账本须已显式初始化原生成员 Schema 2，宿主须预建本次运行代的父组和 `core` 子组。核心使用独立的非 root 账户，`source` 沿用已核验的同宿主原生时钟。

已显式迁移至 Controller Schema 109 的原生部署可在固定 Controller 计划设置 `worker_control: true`。核心使用同一条受监督继承流确认当前回执，并提交完整 Worker 启动快照。宿主为每次核心准入创建独立 SQLite 账本。登记绑定当前允许项、短授权摘要、原截止以及宿主预建的空 Worker cgroup。撤销在宿主账本持久生效，监督通道丢失时核心退出。[Linux 监督联调](test/linux-worker-control.integration.mjs)

需要创建 Worker 时，在同一计划配置 `worker_runtime` 的 `directory`、`uid`、`gid`。目录须为受保护的暂存目录，Worker 使用与 Controller 独立的非 root UID 和 GID。宿主从安装库取得本次封存件，确认专属 cgroup 为空，并在启动固定 Worker 入口前持久登记创建尝试。Controller 只采用绑定当前核心代、专属 cgroup 和本次封存件的闭锁回执。撤销后宿主确认子组清空、保存退役证据并移除暂存副本。[Linux 宿主入口](src/linux-native-host.mjs)

原生部署要打开模块与执行通道，在 `worker_runtime` 增加 `channel_directory`。使用 root 所有、Controller 可遍历、组和其他用户不可写的目录，绝对路径最多 60 字节。宿主为每份闭锁回执建立一次性 Unix 通道，核对 Controller 的 PID、UID、GID 和当前进程身份，再转接 Worker 的继承描述符。Controller 以当前运行绑定打开通道。断连或撤销后关闭通道并移除套接字。[Linux 监督联调](test/linux-worker-control.integration.mjs)

使用私有 cgroup 和双核心闭锁准入的 Compose 计划，可以设置 `worker_control: true`。需要 Controller Schema 109 或更新版本，以及 root 所有、模式为 `0700` 的安装目录。Controller 通过原引导通道提交启动栅栏，宿主持久保存同代栅栏后才确认。宿主复核当前容器和 cgroup 证据，关闭监督通道会停止核心。[Compose 联调](test/linux-compose.integration.mjs)

Compose 的 `worker_runtime` 固定宿主 `distribution.directory`、`distribution.manifest_sha256`、`image.file`、`image.sha256`、暂存 `directory`、独立 `uid`／`gid` 及 `channel_directory`。宿主 Node 和 Controller 制品摘要须匹配引导策略。套接字目录应专用、启动前为空、由 root 管理，绝对路径最多 60 字节。Compose 只把它以只读方式挂到 Controller 的 `/run/leafseamer-worker`。在已持有当前发行验证会话的宿主进程中，把同一安装库通过 `installationStore` 交给 `openLinuxComposeHost()`，由宿主按当前封存件和启动授权创建 Worker。Worker 使用同代 Controller 父组下预建的专属空 cgroup。[Compose 宿主入口](src/linux-compose-host.mjs)

配置 `worker_runtime` 后，宿主还会在该只读挂载提供 `installation.sock`。套接字只接纳当前准入的 Controller 进程。Controller 在启动时确认宿主安装库身份，按当前服务读取封存收据、清单、文件库存、配置 Schema 和能力模板。安装查询使用独立连接，宿主在处理查询和回复时检查当前进程身份。关闭该连接会触发当前运行代的监督关闭。由调用方提供安装库时，等待宿主的 `close()` 完成再关闭该安装库。[Compose 联调](test/linux-compose.integration.mjs)

已配置上述安装来源及 Controller 配对管理回环的部署支持 `extension-admin --origin https://127.0.0.1:8444 --ca-file /etc/leafseamer/pairing/ca.pem`。命令从私有标准输入管道读取含 `login`、`password`、`operation` 和 `request` 的 JSON。人员需要当前的 `extension.manage` 权限和近期认证。可对已审阅的候选安装执行 `approve`，用 `plan` 固定影响，再提交匹配计划的 `activate` 或 `enable`。收到受理后，用 `start` 提交原 `activation_ref`、宿主分配的 `launch_id` 和专属空组 `containment_ref`，启动保持闭锁。回环 API 的 `lookup-plan` 和 `lookup-activation` 要求在原人员会话使用同一请求标识及当前 `extension.read` 权限。[Compose 联调](test/linux-compose.integration.mjs)

将 `leafseamer.linux-native-core/1` 计划保存于安装目录下的 `linux-native/`。填入 `host_installation_id`、`role`、`driver`、`generation_id`、`launch_id`、运行账户的 `uid` 与 `gid`、`data_directory`、回环 `port` 及现有 `bootstrap` 策略。`image`、`clock_profile` 与 `pairing_profile` 各提供绝对 `file` 和 `sha256`，`distribution` 提供绝对 `directory` 和 `manifest_sha256`。摘要使用 `sha256:` 前缀，配对和时钟配置均使用各服务的 `/2` 格式。安装制品及依赖树由 root 管理，业务库目录由所选运行账户管理。

`start({planFile, planDigest})` 接受已批准计划的绝对路径与摘要。宿主核对安装身份、制品清单和各资产、权限、服务身份以及配置摘要，再组装固定的 `contained-core-linux` 启动参数。核心准入回执持久写入后返回，同一启动标识的重投返回原记录。业务 TLS 随两端认证采集另行启用。`retire(launchId)` 先持久关闭原入口并关闭监督通道，再观察原父组。仍有进程时保留 `closing`，父组清空后持久返回 `retired`。`lookup(launchId)` 查回原启动与退役记录，`close()` 释放宿主句柄。Compose 容器的认证准入继续使用单独部署验收。[原生配对联调](test/linux-core-bootstrap.integration.mjs)

## 本机安装账本与静态归档验证

Suite 已提供 `@leafseamer/suite/installation` 内部运行模块，使用与当前产品相同的 Node 24.22.0、better-sqlite3 13.0.3／SQLite 3.53.4 和 canonicalize 5.1.0。依赖固定于本仓 `package-lock.json`；构建后的包不需要相邻仓库。Windows开发环境先安装依赖并构建固定原生输入，再运行检查：

```powershell
npm ci --ignore-scripts
npm run build:native -- --headers C:\toolchain\node\include\node --node-library C:\toolchain\node.lib
npm test
```

上述工具链路径为示例，须使用`native-inputs.json`固定的Node头文件及Windows x64导入库，配合CMake、Visual Studio 2022 C++工具链和Windows SDK。构建产物核原生源码、输入、编译配置及二进制摘要，并随包交付。测试发行引用由真实验签和安装库生成，密钥、初始渠道、固定时间及安装策略仍为合成输入，不代表真实生产发行已获批准。

`createInstallationStore(directory)`只供可信首次安装入口使用，要求安装器预先建立并保护的空目录。它创建独立安装／权威／数据库／epoch身份和持久标记；普通`openInstallationStore`只开既有库，不因缺库新建。目录或数据库文件身份不符、额外DDL、错误Schema／引擎、完整性／外键失败均拒绝。连接按DF04使用单writer、WAL／FULL、零等待、外键／递归触发器和禁止可信Schema；它不与业务数据库共用事务，也没有业务备份恢复入口。标记和文件身份核验不代替OS访问控制或首次安装信任证明。

`recordAcceptedImport(request)`是本机agent核对端、目标管理权及安装策略之后的持久事务入口，不能直接暴露给网络或GUI。新请求在同一事务中查验同库真实发行记录、当前活跃会话、最新发行序号／撤销和包长度／摘要／扩展清单摘要，并核同库校验策略原件及其撤销状态；手工构造同形Ref不能受理。模块核闭合字段、完整ImportIdentity及不可变意图，仅排除顶层source_attachment_id计算摘要；同身份同摘要查原，异内容冲突。历史查原不重新授予新请求资格。`queryImport`读取原状态，`cancelImport`与复制结果由同writer排序，重复取消保留原结果。库保留全部操作、事件和复制尝试，SQL禁止删除／替换历史并以外键和字段绑定约束发行及校验策略引用；最多4096个保留请求、同时2项非终态、每peer至多1项。每操作复制尝试另有1024修订开发预算，保留终止修订空间，满额拒绝且不删旧记录。

`store.validationPolicies.configure({policy_id,approval_reference})`仅供已核人员批准的可信配置入口使用，返回同库`ValidationPolicyRef`及不可变正文。正文由宿主生成，绑定当前完整Suite构建清单、Node／平台身份，以及yauzl、pend、canonicalize静态校验执行文件的实际摘要。配置者不能上传校验器路径、脚本或自报实现摘要；同ID异内容拒绝，更新制品须重新批准新的策略ID。`historical(ref)`只查原，`revoke(policyId,operationId)`永久撤销，不删除旧导入或验证记录。配置传入的批准引用仍须由生产管理入口证明其来源，本方法不凭字符串证明人员已审批。

新受理及静态验证前后在writer之外核实际部署字节，在事务内核策略、撤销及本进程绑定的实现身份；策略撤销先提交时，迟到校验不能保存成功结果。已保存报告保留历史，后续封存仍须查当前资格。部署字节变化不能在已加载旧实现的进程内重新批准；重新启动后旧策略也不能自动绑定新制品。此检查不是不可变内容根或加载器TOCTOU证明，运行包及安装配置仍要求受保护部署。当前开发库Schema增加策略记录，旧开发布局拒绝自动打开或重建，不提供隐式迁移。

`copyImport(identity, sourceFd)`只读调用者持有的regular-file描述符，不接收源路径、URL或命令。先提交copying及唯一spool引用，再异步分块写入安装根内独立文件，核实际512MiB包上限、长度、SHA256和10分钟复制窗口，文件sync／close后提交字节回执并进入validating。它不解包、不执行包内代码。调用者仍拥有源描述符；复制期间源改变以实际复制字节核验，单次stat不作为快照。取消先提交时，迟到复制结果不能覆盖；复制中agent退出后，显式重试沿原operation分配新spool并保留旧尝试，未完成文件不被当作有效包。存储结果不明进入indeterminate或关闭当前writer，不能以新请求清除旧状态。

`validateImport(identity)`读取已复制包，在持久记录验证尝试后执行两遍静态ZIP检查。控制文档由固定SDK的artifact-import入口严格解码，核清单摘要、平台、角色及文件引用；随后逐文件检查local／central一致性、路径、CRC、SHA256和实际大小，并解压到新的隔离目录。支持stored／deflate、数据描述符和ZIP64；拒绝加密、多盘、链接、路径别名、未列条目和重叠。包上限512MiB，单文件256MiB、完整库存1GiB、压缩比100及10分钟验证预算。包内代码不执行。

`prepareMaterialization(identity,{reader_sids,release_authorization_ref})`供可信安装协调者准备Windows内容根。先核原静态报告、当前同库发行与校验策略，持久记录独立准备尝试，再由专用worker复制实际库存。首次安装为新建的空`content`父目录设置显式DACL并将目录身份写入安装标记；不会自动修改既有非空内容目录。准备时检查父目录owner与有效写权限，普通主体可写则拒绝；新根、子目录和文件使用受保护DACL，SYSTEM和安装进程用户可写，显式选定的读取SID只有读／执行权限。读取主体必须来自可信安装配置，不能由扩展包决定。

原生核验保留目录与文件句柄，核FILE_ID、实际长度／SHA256、单链接、完整树及ADS，拒绝reparse、别名和额外内容；源和目标分别复核。文件逐一sync／close，结果绑定原验证记录、内容摘要、当次发行引用、实际根身份及权限策略。目录使用可继承ACE，普通文件使用无继承标志的ACE，设置后逐项回读比较；参见[Microsoft继承规则](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)与[基于句柄设置权限](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)。安装用户及宿主管理员仍属于可信管理边界，不能用此DACL隔离共享同一写入身份的worker；生产运行身份、ACL部署和加载时检查仍须验收。

准备报告的内部`storage_identity`从实际持有的内容根句柄取得卷GUID路径、文件系统、卷序列号、文件系统标志及扇区／分配单元几何，复制前后必须一致，并与根FILE_ID的卷身份绑定。字段不接受客户端自报，也不通过导入IPC暴露。卷序列号由格式化分配，不是硬盘厂商序列号；这些信息只用于后续资格匹配，不证明存储控制器、刷新支持或断电耐久，不使结果成为sealed。接口依据：[Microsoft卷信息](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew)、[句柄最终路径](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)及[分配单元几何](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdiskfreespacew)。

文件ACL设置后再次以原生写句柄执行`FlushFileBuffers`，随后在内容锁持有期间从最深子目录向上刷新内容根，最后按已持有父目录句柄的实际身份刷新父目录，再复核内容与存储身份。`metadata_flush`保存方法、顺序、文件／目录数量和父目录身份；任何打开、类型、身份或刷新错误使本次准备失败并关闭准备句柄。此路径不打开卷设备、不执行卷级刷新。`FlushFileBuffers`要求`GENERIC_WRITE`，只读目录句柄失败不能推导写句柄不可用；接口依据：[Microsoft刷新接口](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)与[目录句柄打开方式](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)。该记录证明调用完成，不证明硬件缓存、断电恢复或平台配置已验收。

准备在独立worker中运行，writer仅记录尝试和结果，查询／取消不排在文件复制之后。取消或资格失效时终止worker并等待资源回收；迟到结果不能登记为prepared。同operation最多16次准备尝试，失败或崩溃遗留目录保持独立且不自动采用，当前不提供孤儿清理入口。正常完成后`preparedArtifact(identity)`只返回持久历史与内部目录定位；相同策略重复准备查原，不重新证明此刻字节或ACL，也不为旧报告补写刷新事实。结果明确为`directory_durability=unqualified`、`sealed=false`，导入仍为validating且无intake收据。文件与目录刷新不替代掉电实验或不可变加载资格，后续封存和启动须重新核验当前实物及信任。

可信安装入口可通过`store.platformQualifications.observe(identity)`取得实际物化根的资格适用范围及摘要，再用`configure(identity,{profile_id,approval_reference,evidence_digest,scope_digest})`登记已审阅的外部平台验收批准。范围绑定本安装实例、目录及内容父目录身份、实际卷、写入SID、OS版本、Node与构建摘要、SQLite引擎及持久策略、ACL和刷新顺序；调用者不能自报这些观察字段。批准引用与证据摘要由可信配置提供，此接口不鉴定外部报告真实性，也不自动批准本机。实际验收应覆盖存储设备、驱动及缓存配置与断电恢复；这些配置变化时须撤销原资格并重新验收，卷序列号不能替代物理磁盘身份或证明硬件配置未变。

资格的`assertCurrent(identity,ref)`重新打开原内容根并固定祖先、目录及文件句柄，核原FILE_ID、卷、库存字节和逐项ACL；缺失、同名替换、额外文件或权限漂移均拒绝，不重建目录或修复ACL。`historical(ref)`仅按完整Ref查原；`revoke(profile_id,operation_id)`永久撤销，同ID不得重用为新批准，历史仍可查询。改变构建或适用范围需要新的资格。上述入口仅供可信安装装配调用，不经管理工具IPC开放；平台资格也不替代当前发行信任、校验策略或加载许可。开发版安装库继续严格绑定DDL摘要，旧布局拒绝打开，不隐式改库。

静态结果与原复制修订持久绑定，重复调用查原；取消先提交时不采用迟到结果。静态准备成功后仍为validating、receipt=null。`copiedArtifact`及`validatedArtifact`只给可信内部后续步骤提供定位和原件，不能把隔离目录或静态报告当作当前内容证明、发行授权或启动许可。

`sealImport(identity,{platform_profile_ref,release_authorization_ref})`接续已登记的内容准备。安装库先持久记录sealing尝试，独立worker重新打开原内容根、核库存和ACL，按文件／最深目录至根／父目录顺序刷新，并持有内容句柄等待writer裁决。writer再次核当前宿主信任代、校验策略、发行授权及平台资格后，在同一事务中保存核验原件、完整ArtifactIntakeReceipt和sealed状态；SQL约束绑定原操作、内容摘要及完整引用。查询和取消不排在文件工作之后，取消先提交则迟到结果不能封存，sealed先提交则取消仅返回原收据。每operation最多16次封存尝试，不执行扩展入口。

`trustEpoch()`读取安装库持久信任代，新库从1开始；可信管理入口可用`advanceTrustEpoch({expected_epoch,operation_id})`比较并推进，重复操作查原，不能下降或复用操作ID。该代独立于TUF metadata epoch，不由客户端指定或随业务恢复重置。`sealedArtifact(identity)`返回历史收据、IntakeRef及核验原件；后续实物丢失、资格撤销或信任代变化均不改写历史。存储提交结果未知时当前writer关闭使用并要求沿原identity重开查原；若账本仍为sealing且不存在sealed提交，可重新核验并提供当前发行授权续接，不复用失败尝试的intake ID。测试覆盖写入故障造成的事务回滚和续接，真实COMMIT响应丢失、断电恢复仍待验收。

sealed表示该次内容封存提交，不能代替当前可用性查询、安装批准或加载许可。安装CLI和可信时间提供者仍未实现；生产平台验收原件及实际部署资格仍须落实，合成测试批准不能用于实际安装。

`queryIntake({intake_id,target_authority_service_id})`按安装库原件定位已封存内容，重新核当前宿主信任代、校验策略、平台资格、完整库存及ACL。发行授权从原信任域／渠道／目标及部署profile内选择同包、长度和扩展清单的最新记录，再核实际当前验证会话、metadata、撤销和发行序号；缺少当前记录返回unavailable，不用其它信任域批准或历史收据替代。重开后须先恢复真实发行验证会话及当前授权。available返回原sealed收据，unavailable不带收据，均不改写历史。

`verifyMaterialization(request)`使用相同的当前实物检查，并核请求的manifest、artifact及信任代；字段不同返回mismatch，当前实物或资格不可用返回unavailable。响应回显完整请求，包括challenge和launch_intent_digest；verified带本次随机evidence_id。这个接口证明内容观察，不证明该启动意图已获安装、权限或运行批准。观察在独立worker内进行，最多四个并行观察，开发截止为4秒；查询不执行文件刷新、修复或扩展代码，期间仍可处理其它连接的取消与撤销。

观察时钟由宿主产生：`materializationClock()`给出当前安装库打开实例的描述，响应ClockRef绑定该描述摘要，重开更换domain ID。计数取[Microsoft QueryInterruptTimePrecise](https://learn.microsoft.com/en-us/windows/win32/api/realtimeapiset/nf-realtimeapiset-queryinterrupttimeprecise)并将100ns单位转为纳秒，检测回退与溢出，不使用客户端自报时间。响应的observed_tick属于该观察域；协调者必须按自己发challenge的单调时间限制窗口并核完整响应，不能直接把宿主tick当成本地年龄。句柄在本次观察完成后释放，verified不承诺后续加载时内容仍未变；监督器／加载器接线及加载前重验仍须完成。

16项测试使用真实文件库、描述符、ZIP字节和进程强停，覆盖持久幂等、取消竞态、复制恢复、验证查原及结构反例；验证前包不可读保持indeterminate，恢复文件不能清除旧状态。磁盘写入失败为注入验证。目录身份变化后当前writer锁存关闭。真实发行信任、Windows ACL部署、Linux、真实磁盘满／COMMIT未知和掉电耐久仍未验收；安装模块的局部实现不关闭阶段1或全系统交付。

### 信任元数据内部模块

`store.trust`接入独立安装库的根、元数据原字节、根转换、缓存代际和验证会话。`initialize`只供已经核验独立渠道与批准的安装入口使用；`openVerification`要求调用者提供已验证的固定时间及证据引用和受控传输。它们当前核结构并记录输入，不负责核验真实操作者、外部渠道或时间来源，不能直接暴露为网络API。每个域同时只允许一个会话，刷新只运行一次，600秒后拒绝继续；调用者必须关闭会话后才能关闭安装库。

发行资产包含明确标为`6.0.0-leafseamer.1`的tuf-js窄补丁。`tuf-inputs.json`固定官方6.0.0全部输入摘要，`scripts/build-tuf.mjs`仅补固定时间、同步持久化、根阶段缓存轮换及公开传输错误类型；验签、引用校验和委托遍历仍由上游核心执行。构建产物保存原输入、补丁和最终字节摘要及MIT许可。每个已验证根逐代提交，在线密钥发生变化时pending永久保留到最终有效根阶段；A→B→A或中途退出不能抹掉轮换。完成轮换后递增metadata_epoch，旧缓存退出当前集合，原字节仍保留。读取或提交失败使当前客户端不可再用；已提交前序角色不因后续失败回滚。

验签前检查原JSON字节容量、重复键、有限安全版本、真实UTC整秒日期及metadata引用的长度／SHA256，不重新序列化后验签。输入最大4MiB、48层、262144节点；本机profile拒绝`__proto__`、`constructor`、`prototype`键。其它未知字段保留交给上游；目标绑定只返回当前成功会话中按路径查得的数据，不接收外来TargetFile。root与稳定targets各要求独立密钥的2-of-3，snapshot／timestamp各独立单钥；合成测试密钥不代表真实独立持有人。

`createReleaseTransport`按安装配置固定metadata和target的HTTPS地址范围，执行系统CA或显式配置CA与主机名验证，不跟随重定向，不接受压缩或部分响应。元数据最多4MiB，目标最多512MiB；30秒无活动或会话600秒总期限会中止连接。`session.download(path)`仅采用本次成功会话查得的TargetFile，以SHA256前缀构造consistent-snapshot地址，先持久记录尝试和完整元数据依据，再分块写入新的staging文件。实际长度、上游TargetFile全部哈希、文件身份及sync／close完成后才提交下载回执。

`trust.downloadedArtifact(id)`是可信安装内部查原接口，返回历史绑定及隔离文件定位，不证明文件此刻未变、目录耐久或已经获得安装权限。下载失败或关闭会话时不产生成功回执，保留尝试与已接受的元数据；不能以文件存在补写成功。真实HTTPS目标字节已经通过发行验证记录、受理事务及文件描述符交接到复制和ZIP验证，相关用例的对端、管理权、安装策略和时间环境仍为合成输入。

`trust.inspectDownloadedDocument(downloadId, kind)`将已完成可信下载的`release`或`revocations`原字节交给固定SDK发行入口检查。完整发行清单采用`native-release/0.2.0-draft.1`，涵盖五仓、入口、多通道、存储及多镜像引用闭包；文档最多4MiB。首次读取核实际文件类型、长度、SHA256和安装库身份，成功后将原字节、下载依据及解码选择不可变地保存。重复调用读取原文档，隔离文件之后变动不覆盖历史，也不证明当前实物合格。本接口只保存文档检查结果，不推进发行序号、不应用撤销、不签发ReleaseAuthorization。

可信安装配置通过`trust.configureRevocations(domain, {target_path, approval_reference})`固定每个域的全局撤销路径；配置首次写入后不可覆盖，不能从待安装包取值。`session.adoptRevocations(documentId)`只采用当前成功会话下载并检查的撤销原件，重核目标长度／摘要及根授权顶层targets；局部委托不能签全域撤销。修订按精确十进制整数比较，更低拒绝，同修订要求同原字节。新快照、采用回执与新增撤销项同事务提交，跨重启或metadata_epoch轮换不清除下界；新快照省略旧项也不撤回已经记录的撤销。`lookupRevocation(domain, kind, value)`仅查询历史撤销，null不证明当前许可存在，也不授安装或启动权。

`session.authorizeExtension({release_document_id, package_download_id})`检查当前会话的完整发行原件、扩展包下载和已采用撤销快照。扩展target的受签`custom.leafseamer`使用SDK的`leafseamer.release-extension/1`绑定两层清单；完整发行原字节与C09扩展清单JCS摘要分开，归档须与所选profile中的`extension_archive`长度／摘要一致。当前入口仅接受根授权顶层targets；第三方受限委托的发行审批入口及包含完整清单自身的组合归档仍须另外实现。

成功时同事务保存发行批准与逐包验证记录，返回同库`ReleaseAuthorizationRef`。发行序号在`(trust_domain, channel, target_profile)`内精确比较，更低拒绝，同序号要求同完整manifest原字节；一个组合可以分别绑定多个包。release_id不可换内容复用，在线key轮换不重置这些记录。`trust.releaseAuthorization(ref)`只读取历史原件；新受理另核当前会话，关闭、超时或重启后旧Ref不能创建新导入。复制／静态检查完成仍不授运行权，激活前必须重新核验当前发行及安装资格。

固定上游客户端34项测试在补丁产物上通过；本项目包含13项信任传输测试和5项发行授权／受理测试，覆盖真实签名、文件库、子进程、本机HTTPS、序号／ID冲突、多包同发行、撤销及旧Ref拒绝。真实初始信任渠道、可信时间原件与下界、安装管理权配置来源、平台资格和激活前复核仍未接通或验收；当前内部发行结果不关闭正式发行或完整安装验收。

### Windows本机安装通道

`@leafseamer/suite/local-peer`在Windows x64／Node 24.22.0提供实际命名管道。可信启动器先用`captureInstallationPeer(pid)`保留预期进程句柄，再用`createInstallationChannel({name,peer,server})`建立连接；名称限定在`\\.\pipe\LeafSeamer.Install.`前缀。双方核实际管道PID、进程创建时间、主令牌SID、登录及会话身份，拒绝AppContainer、远端和错误进程。服务端使用显式受保护DACL、首实例及单实例；同SID进程的区别依赖实际进程核对，不能仅靠DACL。原生实现不使用Node私有管道字段。

可信配置入口`store.registerClient(policy)`持久保存SID、角色、目标authority范围、权限及批准引用。management_tool仅允许import.begin／query／cancel，authority仅允许intake.query，launch_coordinator允许intake.query及materialization.verify；同一SID不自动取得其它角色权限。同ID异策略拒绝，`revokeClient`永久记录撤销并关闭现有连接。角色和`approval_reference`均来自可信启动配置，客户端自报不能证明管理权或服务身份；真实peer仍按固定进程实例核验。生产启动器、人员／服务身份与批准来源及目录ACL部署仍须落实。

`@leafseamer/suite/local-import`提供`serveInstallationClient({store,registration_id,channel_id,channel,validation_policy_ref,reader_sids=[],platform_profile_ref=null})`与`createInstallationClient({channel,channel_id})`。注册ID、channel ID、固定校验策略Ref、平台资格Ref及内容读取SID由可信配置选择；平台Ref和读取身份在首次等待前复制，管理工具不能通过IMPORT_BEGIN增添SID或平台批准，默认不额外授予读取主体。服务端在同一writer事务中先核当前对端、未撤销注册、操作权限和目标范围，再查原或受理；新请求另核当前真实发行记录及宿主信任代。客户端`attach(fd)`登记已经打开的只读普通文件，得到仅限本连接的`source_attachment_id`；`begin(input)`、`query(identity)`和`cancel(identity)`走固定SDK九帧中的对应请求。省略服务端校验策略Ref时不能开始导入。Ref匹配不替代策略配置本身的批准。

需要等待人员恢复操作的安装协调端可在可信服务端配置 `request_idle_ms`。取值为 5000 至 90000 之间的整数毫秒，默认 5000。该值只用于服务端等待下一个请求，连接、写入和客户端等待回复仍用原时限。进程身份和每条请求的注册权限持续核验。

附件传输使用长度前缀内的专用二进制记录：请求为标记字节0及8字节小端无符号客户端HANDLE，成功响应为字节`0,1`及36字节ASCII UUID，拒绝为`0,0`；它不增加SDK业务消息。服务端只向该连接已经固定的真实peer进程调用`DuplicateHandle`，核对象为普通磁盘文件、最大512MiB且访问权不含写入／删除／修改权限，再由Node自身libuv转为描述符。每连接最多8个未消费附件及4096次登记；句柄和附件ID不写入持久操作。客户端须保留原fd直至`attach`完成，之后可以关闭。源字节仍可能被其它持有人修改，最终以完整复制长度及摘要判定。API依据为[Microsoft句柄复制](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)、[对象访问权查询](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryobject)和[libuv描述符转换](https://docs.libuv.org/en/v1.x/fs.html#helper-functions)；对象查询不可用时拒绝附件。

开始请求先返回持久受理状态，后台依次完成复制、ZIP检查和受保护内容准备，查询／取消不等待整个任务。相同operation的重投共享同一后台任务，不再次复制或创建内容根；已有静态校验结果的原operation可继续准备，无需重传源附件。读取策略与平台Ref均绑定进行中的任务，不接受另一配置借原任务改变ACL或资格。关闭连接清理未用附件并等待已受理任务释放资源，不自动取消已受理操作；store关闭也须等待整条任务完成。准备失败保留原尝试及失败结果，可沿原operation重核，不自动删除目录。未配置平台Ref时止于validating；配置后以该资格和请求中原发行授权继续封存。发行会话更换后须由可信安装入口提供新的当前发行授权续接，不能改写原请求intent。sealed之后的query、cancel及同identity重投均返回原收据，不重新物化。

可信库装配另可调用`store.describeIntake(IntakeQuery)`：在与当前intake查询相同的实物、ACL、信任与平台检查通过后，返回完整收据引用、原manifest和FileInventory；不可用时content=null。它用于Controller持久候选内容，尚未增加网络IPC消息，不授予运行批准。

`store.describeConfigurationSchema(IntakeQuery)`在同样的当前资格检查下，只读取清单指定的configuration_schema_file_id，且该库存项必须为schema。读取沿用本次固定内容观察持有的原文件句柄，至多1MiB，不重开调用者路径；返回完整intake引用、清单／制品摘要、库存文件条目和原始bytes，返回前核长度及摘要。观察结束后句柄读取能力失效。不可用时content=null；该方法仍是可信库装配接口，不执行包内模块，不授予配置或运行批准。

`store.describeCapabilityTemplates(IntakeQuery)`沿相同的当前实物／ACL／信任／平台检查读取清单capability_template_file_ids指定的schema文件，合计至多1MiB、至多64个文件。读取使用本次观察持有的原文件句柄，返回前逐项核库存条目、长度和SHA-256，返回完整intake／清单／制品身份及文件原bytes。它仅供可信库装配，未新增网络IPC帧。Controller据此验证静态动作声明和Schema；包内模块不执行，运行目录批准仍须另行取得。

可信启动器可调用`store.acquireMaterialization(IntakeQuery)`取得有界加载交接。可用结果含冻结的完整内容原件、原生观察的root路径／FILE_ID／存储身份，以及同安装观察域的固定四秒截止；`assertCurrent()`核当前资格，`close()`与`closed`可等待实际句柄释放。独立worker持有祖先／目录／文件句柄，平台／策略／信任资格失效或截止即关闭；持有期间最多四个并发观察或交接，store关闭须先等交接结束。路径副本不是句柄或授权，接收方须在释放前核完整原件并建立自己的加载保护。该入口仅为可信同进程装配，未增加公开IPC，不签发启动许可，不执行扩展模块。

客户端另提供`queryIntake(input)`和`verifyMaterialization(input)`，分别收取INTAKE_RESULT和MATERIALIZATION_RESULT。服务端在查询前及观察期间核当前注册、peer和目标范围；客户端除核reply_to及预期消息类型，还核intake／目标及完整challenge请求回显，错绑关闭连接。管理工具不能借导入权限调用这两个服务查询。

每帧最多64KiB、双向序号连续、message ID不复用；响应必须匹配reply_to。开发预算为握手／单次读写5秒、接收队列16帧、每连接4096个业务请求。断连或丢失响应后沿原identity查原，不生成新请求猜测结果。实际Windows子进程、管道和安装库检查覆盖进程绑定、句柄交接、受理幂等、自动准备及封存、当前物化、恢复、取消与撤销。Controller原生监督器已接通这两个查询；Linux描述符传递及实际平台耐久与部署验收仍未完成。

跨仓本机联调使用`test/controller-materialization.integration.mjs`：先构建两仓，将`LEAFSEAMER_CONTROLLER_TEST_ROOT`设为Controller绝对路径，再运行`node --disallow-code-generation-from-strings --test test/controller-materialization.integration.mjs`。它使用临时安装库、真实进程与管道；合成发行／平台批准只供测试，不授予生产资格。

Windows 定时派发验收还需构建采用同一 Controller 的 Seamer。将 `LEAFSEAMER_SEAMER_TEST_ROOT` 设为 Seamer 绝对路径，`LEAFSEAMER_SUPERVISOR_DIST` 设为含参考时间提供者的 Controller 制品目录。临时库使用 Schema 113，测试经回环双向 TLS 自动受理场次并核对实际模拟器效果、两端终态和活动槽释放。

```powershell
$env:LEAFSEAMER_SIMULATOR_SCHEDULED_DISPATCH_TEST = '1'
node --disallow-code-generation-from-strings --test --test-name-pattern 'closure_cleanup_successor_capture_events$' test/controller-materialization.integration.mjs
```

同一 Windows 原生用例也可设置 `LEAFSEAMER_SIMULATOR_SCHEDULE_REFERENCE_WITHDRAWAL_TEST=1`。测试在 Guard 已安装且派发请求已落库后、原截止前撤下测试批准，核对零写入尝试、持久 `never_sent` 证明和 Seamer 的阻止终态。[原生联调](test/controller-materialization.integration.mjs)

Linux 定时派发验收使用同一隔离客体中的受监督 Compose、Chrony、NTS 提供者和配对模拟器镜像。启用首次配对、定义发布、运行审批及布防用例后，设置 `LEAFSEAMER_TEST_COMPOSE_SIMULATOR_SCHEDULED_DISPATCH=1`。测试通过 Seamer 发布和激活一次性场次，退役后核对 Controller 与 Seamer 的 SQLite 原件、一次写入的效果和活动槽释放。[Compose 定时联调](test/linux-compose.integration.mjs) · [持久结果断言](test/fixtures/linux-compose-simulator-schedule.mjs)

另一次隔离运行可设置 `LEAFSEAMER_TEST_COMPOSE_SIMULATOR_SCHEDULE_CLOCK_LOSS=1`，验证已跟踪场次在临时授时批准撤下后持久停发。测试在原窗口截止前放回审批文件，核对原场次仍为 `blocked`，两端均没有为它登记新的执行或命令。[停发断言](test/fixtures/linux-compose-simulator-schedule.mjs)

设置 `LEAFSEAMER_TEST_COMPOSE_SIMULATOR_SCHEDULE_REFERENCE_WITHDRAWAL=1` 可验收 Controller 的写前撤回。测试在定时 Guard 安装且派发请求提交后、原截止前撤回测试授时资格。退役后对照两端账本，核对零写入尝试、Controller 的 `never_sent` 和 Seamer 的 `blocked` 终态。两种撤回场景各自运行。[写前撤回断言](test/fixtures/linux-compose-simulator-schedule.mjs)

Linux 安装协调者可通过 `@leafseamer/suite/installation` 对已校验的包调用 `prepareMaterialization(identity, {reader_sids: [], release_authorization_ref})`。安装账户独占准备目录，实物目录和文件分别使用 `0500` 和 `0400`。准备成功后，`platformQualifications.observe(identity)` 返回绑定当前文件系统和安装实现的资格范围。部署者持有相应验收批准和证据后，使用 `configure` 登记资格，再通过 `sealImport` 在安装库中生成收据。

Linux 的本机 `queryIntake`、`verifyMaterialization` 及三个 `describe` 接口会复核当前发行信任、平台资格、内容身份与库存摘要。读取静态文档受原库存和字节预算约束。观察时间使用 Linux `/proc/uptime` 的启动时钟，按百分之一秒精度保守核验四秒窗口。[Linux 内核 uptime 实现](https://raw.githubusercontent.com/torvalds/linux/v6.12/fs/proc/uptime.c) · [安装库联调](test/content-preparation.test.mjs)

可信 Linux 宿主可调用 `store.acquireLinuxWorkerMaterialization(VerifyMaterialization, {directory, uid, gid})`。宿主提供自己持有的 `0711` 目录及批准的非 root Worker UID／GID。Suite 按原库存复制内容，复核封存、发行授权和平台资格后，才发布该次交接的 `0550` 根和 `0440` 文件。固定 Worker 在首次 `LOAD` 前核对原 intake、启动意图、时钟域、原四秒截止、目录身份及全部库存字节。交接引用在原截止后失效。

宿主在启动和交付准入前调用 `assertCurrent()`。`close()` 释放安装库的观察，`discard()` 用于成员组已经确认退出后的交付副本清理。正式 Controller 启动编排和目标文件系统的掉电耐久验收仍待完成。

Windows OBS 只读集成用例需要将 `LEAFSEAMER_OBS_PORTABLE_TEST_ROOT` 指向刚解压的 [OBS Studio 32.0.4 Windows x64 便携包](https://github.com/obsproject/obs-studio/releases/tag/32.0.4)。目录须无 `config`，并由本次测试独占。运行 `node --disallow-code-generation-from-strings --test --test-name-pattern 'supervisor_create_module_obs$' test/controller-materialization.integration.mjs`。用例在临时库登记两个空场景和随机凭据，在本机启动一次性 OBS，验证原生 Worker 采集、SQLite 保存，以及 HTTPS 场景目录的权限与失联撤回。测试使用软件实例、临时配置及合成发行批准。

同一联调文件的 `obs_cut_wire_transport$` 用例使用独占的 OBS 便携实例，在两个空场景之间验证固定 Cut 传输。用例检查同步拒发、按 UUID 设置场景、匹配应答后发起的新读回以及相同目标重复提交仍产生新的四帧。该用例使用测试提供的许可复核回调。

将运行命令的筛选模式改为 `obs_cut_dispatch_guard$`，可在同样的便携实例上独立验证固定 Cut 编码和 Controller 写门。原生用例 `supervisor_create_module_obs$` 还会读取已确认目录生成的 Cut 编码，并把它交给同一个写门验证。写入用例使用合成派发授权，确认关闭写门时场景保持不变，放行时一次许可只进入一次实际 OBS 写出口，并核对设置与读回的完整四帧。

上游兼容检查入口为`node scripts/check-tuf-upstream.mjs <固定源码检出目录>`；先按该提交的package-lock安装测试依赖并构建。入口核对固定提交及源码未变，把该提交的客户端测试映射到本仓实际补丁产物；上游测试依赖只供本地验证，不进入Suite运行包。

### 备份加解密辅助程序

使用 Go 1.27.2 执行 `npm run build -- --backup-crypto`。Go 可从 `PATH` 解析，或由 `LEAFSEAMER_BACKUP_GO` 指定。Linux 可同时选择 `--linux-member`。制品位于 `dist/native`，包含 `leafseamer_backup_crypto`（Windows 后缀为 `.exe`）、内部清单及依赖许可证，均有 Suite 清单中的 SHA-256 记录。

受信任父进程为每项操作分配独占、仅维护账户可访问的暂存目录，并以绝对路径传入 `--directory`。输入与结果采用固定文件名。

| 命令 | 输入 | 暂存结果 |
| --- | --- | --- |
| `pack` | `manifest.json` 及其列出的 `files/` 下的普通文件 | `plaintext.tar` |
| `seal --mode x25519`，重复 `--recipient` 指定 1–16 个不同公钥 | `plaintext.tar` | `ciphertext.age.partial` |
| `seal --mode passphrase` | `plaintext.tar` 和标准输入管道中的口令 | `ciphertext.age.partial` |
| `open --mode x25519\|passphrase --expected-bytes N --expected-sha256 SHA256` | `ciphertext.age` 和标准输入管道中的单一对应私钥或口令 | `plaintext.tar.partial` |
| `verify` | `plaintext.tar.partial` | 仅返回校验回执 |
| `unpack` | `plaintext.tar.partial` | `restored.partial/manifest.json` 和 `restored.partial/files/` |

父进程按原始字节写入秘密并关闭管道，最大 16 KiB。口令加密固定 scrypt logN 为 18，解密上限为 18。两端数据分别以 64 GiB 为上限。解密核对密文长度、SHA-256 和 age 认证。加解密成功返回 `state: "staged"`、`ciphertext_bytes` 和 `ciphertext_sha256`。

`pack`、`verify` 和 `unpack` 的回执包含 `state`、`archive_bytes`、`manifest_sha256` 和数据文件数 `files`。成功的 `verify` 返回 `verified`，其余两项返回 `staged`。归档布局、文件角色、元数据及限额见 [备份内部格式](docs/rebirth-c12-deployment-design.md#1041-备份内部格式)。维护流程负责确认来源、检查数据库内容、发布归档、激活恢复结果，以及清理超时、中断或丢失回执的暂存目录。

### SQLite 一致性快照

使用 `npm run build -- --sqlite-snapshot --backup-crypto` 构建快照与归档制品。Linux x64 使用 `cc`，Windows x64 使用 Zig 0.15.2，可通过 `LEAFSEAMER_SNAPSHOT_ZIG` 指定其绝对路径。构建从已锁定的 `better-sqlite3` 包取得 SQLite 3.53.4 源码，并核对源码摘要。

本机维护调用方可从 `@leafseamer/suite/sqlite-snapshot` 导入 `stageSQLiteSnapshot({sourceDirectory, stagingDirectory, operationId, scope})`。调用方配置受保护的源目录和本次独占暂存目录。`scope` 绑定 `authority`、`service_id`、`database_instance_id`、`request_epoch`、`schema_revision` 和 `control_epoch`，Seamer 的最后一项为 `null`。仅打开该权威对应的 WAL 业务库。允许共享读取的 Controller 可在线复制，独占连接需先关闭写入者。

成功返回 `staged`、操作标识、库身份、引擎、字节数和 SHA-256。单文件副本位于 `snapshot.partial/data.sqlite`，可作为受限 TAR 的数据库成员。快照执行 SQLite Online Backup，核验身份、结构完整性和外键。维护调用方负责业务不变量核验、账本与归档发布。整组恢复仍以经核准的激活计划为准。 [SQLite Online Backup](https://www.sqlite.org/c3ref/backup_finish.html)

### 备份任务账本

可信本机安装代码在持有 `openInstallationStore` 的独占写入连接时，可显式调用 `enableBackupMaintenance()` 安装账本 Schema 2。既有安装身份、标记及数据行保持原值。普通打开旧库时仍使用 Schema 1。后续打开 Schema 2 通过 `backupMaintenance()` 取得备份操作入口。

调用方先登记固定计划，再按完整请求 Key 提交。`lookup` 查回原任务及修订。维护态与 L3 请求需先由本机审批绑定原计划摘要和部署代，再以当前修订调用 `collectSnapshots`。该入口核对当前授权和部署代，逐库写入真实快照回执。已知中断可在当前复制退出后取消。重开时，未确认已退出的复制会进入 `indeterminate`，并占用复制槽直到有独立的退役证明。暂存快照与 `snapshots_staged` 回执供后续归档发布流程采用。

这些接口面向可信本机维护代码。调用方从当前安装权威取得部署代、权限、源目录和受保护的服务安装制品，并负责核对归档覆盖范围。

启用 `enableBackupPublication()` 后，安装账本显式升级到 Schema 3。L2 和 L3 需要至少一个已入账的业务库快照。以当前任务修订调用 `verifySnapshots(operationId, revision, distributions, authorize)` 可取得每个库的业务校验报告。按计划中的服务类型提供 `distributions.controller` 和／或 `distributions.seamer`，每项包含受保护的绝对 `dist` 目录 `directory`，以及从可信安装配置取得的带 `sha256:` 前缀的 `manifest_sha256`。制品及其依赖由本机维护方保管。

调用方在本次操作的 `staging/backup-<operation_id>/archive` 目录生成 `manifest.json` 与 `plaintext.tar`。将 `verifySnapshots` 返回的每份报告按 `path` 放入归档，使用 `text` 的 UTF-8 原字节及对应的 `size` 和 `sha256`，并在 `validation_reports` 中列出。将同一组 `distributions` 传给 `publishArchive`。Suite 在发布阶段按已入账的快照重新生成报告，计算验证引用，并核对清单和 TAR 中对应成员。仅含配置或发行文件的 L0 和 L1 沿用由调用方获准的验证引用。

授权函数在 `verify_snapshots` 核验当前权限和部署代，在 `seal_archive` 和 `publish_archive` 同时核验清单、覆盖、验证引用、服务制品摘要和加密配置。口令经继承的匿名管道或无名 Unix 流套接字对交付辅助程序。

辅助程序校验 TAR 后加密，独占创建 `content/<operation_id>/archive.age` 并同步文件和目录。账本核对密文字节和 SHA-256 后提交发布回执，`getArchive` 据此读取原记录。密钥槽接入、旧进程退役证明和恢复激活由维护流程分别处理。

### 隔离验证本机备份

本机维护程序可显式调用 `enableBackupRestore()`，在已有 Schema 3 的安装账本上增设恢复意图和结果表。安装身份、已发布归档和业务库保持原值，普通打开沿用库的原版本。

调用 `stageRestore({restore_id, archive_id, expected_generation, distributions, secret}, authorize)` 时，使用新 UUID 作为 `restore_id`，并选定本安装账本中已发布、带业务库校验报告的归档。按原发布证明使用相同的服务制品摘要。 `secret` 是口令或 X25519 私钥的字节，只经本机继承通道提供给辅助程序。授权函数在 `stage_restore` 和 `adopt_isolated_restore` 两步核对当前权限和部署代。

恢复候选展开到受保护的 `staging/restore-<restore_id>/restored.partial`。Suite 核对密文、归档清单、原快照回执和报告，再对展开的业务库重跑原验证。 `getRestore(restore_id)` 返回持久结果及校验引用。重放原请求可查原结果，无需再次提交秘密。未确认结束的作业在重开后记录为 `indeterminate`，新任务须等待其退役得到核对。

新生成的隔离结果含 `command_review`。Suite 按来源库、目标库、执行、步骤和原请求核对 Seamer 普通执行及恢复派发记录，以及 Controller 裁决和原终态修订。两端已有的不可变证据相冲突时，拒绝候选。若缺少对应快照或原件、终态未见或资源未决，保留 `requires_review`、原因计数和绑定快照与证据的摘要。多个库可能在不同时点复制，缺记录须交由后续现场核对。

`isolated_validated` 表示原归档已通过隔离验证。切换仍需处理未决命令、准备新的保护域并确认旧写入者退役。外部归档导入和新代激活沿各自的维护流程实施。

### 审核恢复计划

在 Schema 4 安装账本上显式调用 `enableRecoveryPlans()` 后，可用 `prepareRecoveryPlan(restoreId, target, authorize)` 为已隔离验证的归档固定一个恢复计划。目标包含 `deployment_plan_ref`、`deployment_plan_digest`、`release_manifest_digest`、新运行代 `generation_id`，以及逐库 `services`。每库目标包含 `source_database_instance_id`、`data_generation_id`、`schema_revision`、`configuration_ref` 和 `secret_policy_ref`。授权方从本机安装权威核对对应部署、制品和目标引用。计划为每个新库固定新的库实例和请求 epoch，并为 Controller 固定新的控制 epoch。

本机管理员核对隔离清单、跨库命令报告和缺项后，调用 `approveRecoveryPlan`，提交新的 `approval_id`、完整 `plan_ref`、`command_review_digest`、`coverage_digest` 和 `unresolved_digest`。Suite 重新核对隔离目录的成员、字节和摘要，在提交前再次核对部署代及管理员身份。可信宿主在 `check_recovery_approval` 和 `approve_recovery_plan` 返回从本机身份验证取得的 `origin: 'local_os'` 和 `os_subject`。

`getRecoveryPlan(restoreId)` 可查回固定计划，以及已入账的 `plan_reviewed` 回执。后续准备流程须沿用该计划的来源、目标和身份。已批准计划仍要求现场核对与保护态启动。

旧版 [leafseamer-legacy](https://github.com/ikenainanodesu/leafseamer-legacy) 已停止维护，保留旧代码及 Git 历史。旧数据库不自动迁移，新版仅提供人工迁移建议。

新项目主许可为 [Apache-2.0](LICENSE)。从旧仓延续的设计文档保留其 MIT 声明，详见 [来源与许可说明](THIRD_PARTY_NOTICES.md)。
