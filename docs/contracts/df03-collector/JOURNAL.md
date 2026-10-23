# 采集发送日志、停止与容量持久化候选

日期：2026-10-21。本文是基于[0.2通道](CHANNEL_V02.md)与[十四表时间存储](STORAGE.md)的分析和推荐，尚未批准为产品迁移。`collector-journal/0.1.0-draft.1`增加十一表并生成25表组合；旧SQL及旧检查仍独立保存。Controller与Seamer各有独立authority/database，不共享一个跨服务事务。

## 1. 固定身份与账本映射

| 表 | 固定字段及唯一所有者 |
| --- | --- |
| tc_policy | 本库批准的来源数、全局活动采样数、累计证据预约字节、历史channel数和每channel查询帧预算；一次安装固定，变更走维护，不借重启清零 |
| tc_source | 稳定来源槽及canonical_digest；同摘要不能另建别名。规范来源映射由可信配置提供者给出，不能用地址拼写或Source修订绕过 |
| tc_channel | channel、source、Binding、config、完整RuntimeBinding和间隔资格回执；每channel只绑定一个不可变配置，换配置必须停旧实例、退役后建立新channel |
| tc_reservation | 原poll、channel/Binding、配置内ordinal、最坏证据预约字节及原BODY；与ts_poll双向外键，同一事务提交 |
| tc_frame | 核心到采集器的固定序号、消息身份、完整帧字节和poll/Commit/STOP投影；一poll最多一个POLL和一个REPORT_STORED，一STOP一个固定帧 |
| tc_attempt / tc_written | 唯一发送出口的尝试标记与完整帧提交本机流的回执；下一帧尝试前，所有更小序号须有written。written不等于对端处理或网络采样完成 |
| tc_stop | 固定停止意图、channel和本库Invalidation提交；每channel一次，失效seal前捕获旧Binding全部未退役channel |
| tc_ack | 原STOP的固定ACK、完整帧关联、received_through、last_poll_ordinal及closed_tick；不写额度释放 |
| tc_retired | 监督器原退役回执、精确channel/RuntimeBinding及接收者新Domain/tick；证明真实退出的提供者不能由GUI或采集器自报替代 |
| tc_release | 活动额度核销；stored精确关联Capture提交和原REPORT_STORED序号；retired精确关联本channel监督回执，未知墓碑和累计预约字节不删除 |

SQL从唯一原件抽取列做关系核验，BODY仍须通过具体Schema、JCS、来源、方向和当前身份验证。`tc_frame.body`保存完整规范帧，不重新序列化为不同内容；消息内Poll/Stop/Receipt摘要分别核验。库内U20补零只用于比较，线上无前导零，严禁将整个U20转为REAL或SQLite整数。旧十四表版本字段保留原子域身份，组合版本由交付清单固定，不假称旧布局已独自具备本能力。

## 2. 核心writer与唯一发送出口

1. **登记与预约**：同一短事务写ts_poll和tc_reservation。核当前Binding、稳定来源未决操作、全库活动数及累计存储预约。poll ordinal精确+1。未提交不排POLL；提交未知查原，不新建另一个poll掩盖未知。
2. **帧封存**：同一writer分配channel内sequence，保存固定字节。STOP意图存在后禁止新POLL入队，但已排入前缀的POLL保留。STOP帧的cut为本序号减一，last_poll_ordinal取前缀中POLL最大ordinal，不能取所有已登记但尚未投递的poll。正文摘要与列投影由可信编码提供者验证后一起写入。
3. **实际发送**：出口先提交tc_attempt，再从同一进程的串行队列写完整帧。只有本机可靠流已接收全部字节才持久tc_written；随后才可尝试下一帧。局部write只允许当前存活调用继续写同一缓冲剩余字节，不准从头再写、换socket或重建相同attempt。错误、断连、提交未知或崩溃均停止此channel并退役，旧未尝试帧也不在新进程重放。
4. **采样提交与回执**：Capture/原件/发布或失败原写集增加固定REPORT_STORED帧及stored释放记录，在同一ts_commit封存提交。可在本库释放活动槽；下一POLL必须排在该回执之后，其实际写还受written前缀约束。采集器仍须接收并核验精确回执后才能释放自己的缓存；核心只在提交后释放本次取证内存副本。回执丢失不造成自动重新采样或第二次发布。
5. **失效与STOP**：先在运行态关闭授时资格，再同库写Invalidation/unavailable State、TIME outbox及全部旧channel的tc_stop，最后seal。STOP帧封存另用短事务，保持唯一有序出口；不存在“为了尽快STOP越过半帧”的特殊路径。无法完整写前缀时放弃该channel，走监督退役。设备TIME屏障的ACK/应用/资源释放仍属于不同账本。
6. **ACK与退役**：ACK固定绑定原STOP帧及已排入的poll水位，只证明未来关闸；未知采样继续占槽。可信监督退出回执保存后，允许为旧channel各未决poll追加retired释放；缺写部分释放只会保守占槽，恢复继续查原核销。退役不等待设备效果，也不授重新发送旧poll的权利。

`tc_attempt`存在而无`tc_written`的恢复状态是write_unknown；有written也只说明本机流提交。两者都不能证明采集器是否已消费。原进程仍活着时相同STOP的处理幂等由0.2控制，但本候选不主动重投完整流帧；查回执使用新的有界QUERY，查询失败最终退役。采集器到核心的sequence由采集器单出口管理，核心入站验证器核连续序号/原帧身份并与ACK/Capture等原件绑定；本轮没有把该完整入站去重提供者写成另一套SQL水位，仍须在最终IPC接收账本中统一，不能称双向运行已完成。

**迟到报告**：已退役释放的poll可以在独立验证后保存rejected或failure_recorded历史；旧Binding不能发布新Anchor，不再向旧channel排REPORT_STORED。retired释放记录保持原样，不能改成stored来伪造当时已知。报告未通过原件或身份验证时只记有界审计，不制造可信Capture。

## 3. 容量与跨域恢复边界

单源单飞依据稳定source槽，跨实例共用tc_active；存活旧channel不能通过另建同源channel绕过。活动释放与存储计费分离：累计reserved_bytes永不在线退款，退役也不删除未知墓碑。查询数、历史channel数有明确硬上限；满额进入维护，不能静默GC或无限增加新身份。ACK、写回执、退役与固定STOP各有唯一行，不因重试增长；POLL/REPORT_STORED帧随有界poll数量增长。两方向线长度、Blob、原件提供者和进程资源仍受原协议预算约束。

SQL核逻辑原件实际长度不超过预约，并限制单帧65536字节；本候选**不将逻辑字节和等同磁盘页/索引/WAL大小**。批准容量profile必须另给每channel/poll/保护记录的固定元数据、最大BODY和页/WAL放大预算，并给普通采样停止水位与紧急保护保留空间。真实文件占用与可用空间取证由存储提供者提供；没有该profile不得授予生产容量资格。这里的固定SQL上限是设计接受集，未批准为生产默认。

退役后的新channel须具有新Domain下的间隔资格回执：从当前核心收到可信退役回执后的tick起计算经过量下界，等待旧/新配置最小间隔及有效KoD等待的保守上界；未知上界或时基失效则unavailable。SQL保存回执身份，不凭非空BODY证明等待真实完成。数据库丢失、恢复旧备份或核心重启，均不得把同源水位和退避重置为零；先完成旧域保护和持久身份恢复。

## 4. 故障与验收

| 故障或反例 | 必须结果 |
| --- | --- |
| 仅写poll、漏写预约，或反向缺poll | COMMIT失败且25表快照不变 |
| Capture已写但漏回执帧/额度释放/seal | 事务整体失败，不能对外宣称持久成功 |
| COMMIT成功而REPORT_STORED未投递 | 查到原提交；新POLL可排在回执之后，但不能越过未written回执实际发送 |
| tc_attempt已提交后崩溃 | write_unknown，关闭/退役，不重复消费该发送许可 |
| STOP前存在半帧 | 不越过前缀，不制造成功ACK；监督退役 |
| STOP已ACK但采样结果未知 | 活动额度和未知墓碑仍在；退役后仅释放执行额度 |
| 退役后旧Capture迟到 | 保存不合格历史，不发布新Anchor，不修改原释放原因 |
| 新provider/Source修订引用同稳定来源 | 仍受同一源槽和退避约束；canonical映射需提供者验证 |
| 原件超预约、活动满额、查询或channel上限 | 明确拒绝；STOP/退役保留空间按批准profile独立预留 |

`check_journal.py`加载真实候选25表，在`:memory:`运行正常事务、每步缺写与主动异常回滚、两种可观察先后、序号/来源/回执错配、固定ACK、未知恢复和退役后迟到历史。输入和预期是人工合成；不将同一待测查询结果用作期望全集。合法占位BODY仍可通过，专门保留该限制反证。

未执行真实IPC/网络、加密、提供者、并发writer、WAL/掉电、监督退出或设备操作。`collector-storage.sql`由`build_journal.py`固定源组合，旧十四表独立检查不因此扩大覆盖。下一统一布局仍需接入完整Controller/Seamer身份及事务、入站持久去重、TIME保护目标/ACK、密码学与容量profile；这些是尚未闭合的具体契约，不以离线通过代替产品运行批准。
