# 面板回执账本的只读快照

[receipt_journal.py](receipt_journal.py)为[无投影回执入口](RECEIPTS.md)提供文件SQLite读取器，数据库候选布局见[receipt-journal.sql](receipt-journal.sql)。固定panel4选择与完整模型保持不变。approved=false、runtime_ready=false；这是隔离设计参考，未接入业务数据库。

## 原件与一致读取

可信宿主提供绝对数据库路径、当前认证产生的完整RequestIdentity、原意图的独立已采用摘要及必需的authorize接口。身份和摘要不能取自面板自报值。每次调用先核查询权，再以mode=ro、query_only打开既有数据库；缺库不会创建新库，不使用忽略WAL的immutable模式。只接受固定application_id、user_version与精确表／触发器布局，以及匹配的选择和authority/database作用域。

显式BEGIN在同一快照内读取作用域、原panel.request、完整Invocation和全部有界回执历史，读取完成即关闭事务和连接。WAL并发提交只能出现在下一次快照，不把新回执拼到旧原件。原请求全文必须相同，完整原意图摘要、八字段身份、方法、TypedValue参数、activation和对象引用作用域必须匹配；JSON须为规范原字节。重复键、非规范空白或无效模型不能靠解析后重排获得通过。

request_origin和journal_scope禁止更新／删除；request_receipt仅追加连续ordinal，禁止更新／删除。完整历史重新核验当前模型和关联，pending_confirmation可进入权威终态，accepted／rejected／cancelled不允许回退或换终态，受理引用及拒绝／取消原因固定。重新启动读取器也执行这些规则，不依赖旧通道内存登记。SQL只限制布局、原件不可变与序号；领域状态正确性由读取器再验，并仍须未来真实writer在提交时保证。

实验上限为单原请求／Invocation／回执各64KiB、单请求最多64条历史、回执累计1MiB。读取对超大正文使用SQL条件限长后才返回Python；超过限额拒绝，不截断历史后声称状态有效。schema预算不等于查询执行时间硬限额：SQLite锁等待设为零，外层enqueue_status继续执行原1—2000毫秒截止，但并未实现进程级CPU／I/O抢占。正式留存／压缩协议未定义，达到64条时不能删除原件或重建空账本绕过限制。

## 当前读权和输出

authorize先接收当前上下文、原请求和None，必须在查询存在性之前核验当前主体和查询权；取得原件后，在事务外再次接收完整record，核验target_handle、资源、委托、策略和能力引用到原件的权威映射及当前可见性。没有默认批准入口，返回值必须严格为True。回调收到副本，不能篡改待返回原件。真实认证源仍待接线；测试的权限映射为显式合成配置。

读取器返回原回执，不把错误转换为unknown_outcome，也不把available投影静默裁剪为unavailable。交给enqueue_status时，available仍被拒绝并要求完整读集。当前没有回执、损坏、锁竞争、版本错配或授权失败均停止当前交付，由宿主按正式查询协议处理，不能据此推断领域操作没有发生。

调用方必须将会话和账本读权依赖登记到同一个Coordinator，且在授权、目标映射、数据库代或源替换失效时先撤销依赖。此适配不提供事件监听。数据库由可信宿主独占管理，路径隔离、文件权限、writer配置和数据库更换通知都是接入条件；SQL触发器不抵抗持有任意DDL／文件写权限的对手，也不能证明外来数据库内容是权威事实。原意图摘要需要独立权威采用，不能读到什么就信什么。

入队后仍使用Delivery重新取权、原截止和撤权关闭规则。普通追加受理回执与权限撤销不是同一事件；只读快照证明该时点的历史一致性，不声称在无限延迟后仍代表最新状态。领域写入、确认消费、业务幂等事务、数据库迁移、日志保留及完整19类面板帧归并均未由本适配实现。

## 实际验证

```text
python -B docs/contracts/c09-providers/check_journal.py --sdk <SDK仓库> --report
```

[journal-report.json](journal-report.json)记录实际文件数据库、35方法回执输出、新进程重新打开、WAL并发提交的一致快照、不可变约束、原意图错绑、历史状态回退、字节与历史数量限制，以及读取后和排队后的撤权。数据库位于隔离临时目录，结束后清理；不使用既有业务库。固定SDK用例构造数据库原件，领域writer与认证显式合成，业务操作提交、生产授权、浏览器和设备运行均为零。此报告不证明断电耐久、产品部署或最终生产Gate，阶段0继续开放。
