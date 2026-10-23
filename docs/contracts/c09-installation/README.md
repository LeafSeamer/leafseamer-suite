# 扩展安装管理机器候选

版本`extension-installation/0.1.0-draft.1`，未批准、未切换SDK权威。依据[C09第15节](../../rebirth-c09-extension-design.md#15-安装身份管理操作与升级恢复)，本目录将安装管理字段投影为封闭Schema和14个HTTP操作；本轮只处理设计及离线参考，不是安装器或服务实现。已确认draft.4／IPC0.3及原面板契约保持原字节。

## 1. 唯一源、版本和边界

[build_contracts.py](build_contracts.py)是本候选格式唯一源，生成[installation.schema.json](installation.schema.json)和[installation.openapi.json](installation.openapi.json)。Schema根故意拒绝直接校验，消费者必须选具名`$defs`；OpenAPI只转换本地具名ref，枚举和实例常量不递归改写。生成物不手改，不把重复投影当第二权威。

本候选Ref统一含kind、authority_service_id、database_instance_id、object_id、revision和digest。revision采用无前导零、严格末尾、最多20位十进制串，最大99999999999999999999，不是uint64。digest在本候选一律`sha256:`前缀；不能直接替换面板旧裸hex。Ref的revision是不可变内容快照，当前CAS revision另传。内容快照与引用存在性、跨authority合法关联及真实批准仍由服务权威核验。

局部结构包含八种具名Permission、PermissionReview、Approval、ArtifactIntakeReceipt、四用途PlanSelection、DependencyPlan、SlotView、InstanceView、OperationView、BlockerPage，以及全部管理请求和错误。尚未实现完整ExtensionManifest、逐文件清单、内部import IPC、运行LaunchIntent扩展和生产DDL；IntakeReceipt结构合法不代表文件校验、签名或导入完成。

## 2. 两个补充入口

原12接口保留用途，新增两项解决具体缺口；当前共11个POST和3个GET。

- `POST /api/v1/extensions/{installation_id}/review`：当前管理员提交proposed_permissions和配置引用；服务取得该安装固定manifest的requested_permissions，验证只能删除权限项、缩小具名数组集合或降低cache quota，生成不可变PermissionReview。此步只审阅，不签运行审批，不产生外部调用。默认相同权限的review可在stage完成时生成。review更改必须新revision，旧引用不覆写。
- `POST /api/v1/extension-operations/lookup`：按原七元管理identity读取该次可靠受理的固定结果快照。认证来自当前凭据，body的旧auth_session不是当前认证。必须验证当前主体有原对象读权且可读取原请求归属，不能仅知道ID就读取。失去旧会话不等于失去查询自己历史的能力；被撤销的当前凭据不能查询。查询本身不建立新管理操作、不改变原CAS、不重发原请求。

LookupResult按result_kind包含原SlotView／OperationView／DependencyPlan／PermissionReview快照；不是在同ref下重新生成内容。原OperationView可能停留accepted，客户端再GET该operation读取当前状态。隐藏或不可见返回404而不是“确认未受理”，COMMIT未知返回503/unknown_outcome。first-response丢失时无需猜测服务生成的slot_id／operation_id，也不能换host_operation_id重试。Lookup无新的context，所有其他POST仍绑定完整Context。

Review的requested_permissions只由宿主静态manifest提供，客户端不能自报；purpose及kind不可改，缩小范围不能更换端点、协议profile、helper、秘密角色或文件根角色。权限扩大走新manifest／安装批准。protocol_io必须引用同审阅包中的network_endpoint且profile相同，实际approve选择也须保留该依赖。secret_role须有至少一个精确设备或来源；没有对象不是全局秘密访问。网络host按规范小写DNS或规范IP校验，不是任意URL／通配符；DNS解析地址、连接地址及网络策略仍在最终出口核对，本参考不实现DNS或防重绑定。

approve只从当前review.proposed_permissions的request_id集合选择，实际授予范围取该review里的内容；不只拿ID回查原manifest而丢掉收窄约束。Approval固定review_ref、实例内容快照、配置、平台和授予ID；批准不转移当前用户动作权限。一个PermissionReview是未授予的固定提案，最终批准者和选择记录归Approval及其operation；修正早期把“审阅”和“已批准”混为同一记录的简写。

## 3. 摘要、计划和分页

- 管理intent_digest为`{operation,path,body}`完整JCS的SHA256；body仅删除顶层context。path由路由器规范化并绑定实际目标，不能由客户端选择摘要用路径。七元identity单独作唯一键；同identity同内容先查原结果，再决定是否需要新CAS。当前认证检查始终在前。
- Review content_digest覆盖除顶层review_ref／content_digest之外的全部字段；Plan对应排除顶层plan_ref／content_digest。其自身Ref.digest回显该摘要，避免循环。Ref身份仍由authority登记，公开可重算摘要不证明批准。其他嵌套同名字段不剔除。
- DependencyPlan包含固定slot和dependency revisions、四用途选择、配置digest、完整影响数组、平台／策略及同域单调截止。配置digest须等configuration_ref.digest；其内容和身份必须与计划消费操作相同。完整影响集合取writer权威依赖闭包，不能从客户端给出的数组计算后自证完整；受理前重新核对dependency_revision。达到deadline等号即过期，换域也失效。
- 本批候选影响数组上限4096，权限128项、每权限设备64个、单页blockers64项，旧实例关闭引用最多256项。它们是资料实验预算，非生产批准。超过预算拒绝创建普通计划，不能截断影响集合或允许升级。保护关闭不受此公开数组截断：服务内部完整捕获，公开证据／阻塞投影超限时保留未完成／不可用状态；不得因输出放不下而漏撤目标。完整分页化证据模型及全局保护容量仍须C12合并。
- BlockerPage有snapshot_ref、total、offset、items、has_more、next_cursor。首次GET固定一份OperationView及其阻塞集；后续`GET /extension-operations/{id}?blockers_cursor=...`读取同一快照的其余页，不能把新phase与旧页拼成完成证明。游标由服务绑定当前读者、operation、snapshot及下一offset，过期或错绑409并从最新第一页重取。累计只有完整连续同snapshot页才可显示完整清单，未取完不能显示“无阻塞”。snapshot的生存期和数量沿有限profile，不能长期无限保留。

## 4. 状态和权威

Slot、安装实例及operation状态分离。安装状态没有泛化failed可绕过revoking；operation.failed_closed或indeterminate不删除旧实例和未决设备命令。completed结果按操作用途固定：stage→verified、approve→approved、activate／enable／upgrade→active_closed、disable→disabled或no_change、uninstall→removed或no_change。completed仍不等于设备效果、资源释放或自动化恢复。

active_closed是启动管理结果；后续独立手动接管可使runtime_readiness改变，不能反写原完成结果或迁移旧许可。disabled实例与removed实例不得直接重新激活。新实例启动须核对前任关闭、退役及相关资源、owner／出口预登记和当前批准；新装无前任时“前任条件不适用”由权威证据表明，不能由客户端填true。卸载可保留设备unknown历史，相关资源继续约束后续新writer。

本参考的transition_decision仅核局部快照，不验证完整状态机每条边的所有权威。ArtifactIntakeReceipt仍为内部对象，不直接出现在公共响应；其host、trust epoch、实物及发行授权验证须由实际宿主提供者实现。后台module、第三方面板和service凭据不能因Schema正确而调用管理HTTP；OpenAPI声明human＋POST CSRF仅表达契约，不实现认证。

## 5. 正反例、复验和未完成项

[check_contracts.py](check_contracts.py)手写正常样本与变异预期，逐例比较本地Schema和OpenAPI模型接受集，校验八种权限／四种计划、严格整数、额外字段、收窄与重算摘要篡改、幂等先查、永久拒绝和关闭／退役／资源分离、阻塞分页。JSON往返隔离样本引用；可信身份和证据均为人工前提。生成漂移或任一预期失败即不写报告。

```powershell
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-installation/build_contracts.py --check
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-installation/check_contracts.py --report
& docs/contracts/.venv/Scripts/python.exe docs/contracts/c09-installation/check_contracts.py --check-report --staged
```

[报告](reference-report.json)绑定7份实际输入字节；check-report只验绑定不重跑，不纳入顶层旧十份报告清单。本批不执行真实HTTP鉴权、SQLite事务、文件解包／加载、IPC、监督器、设备、故障重启或磁盘耐久。C09的ILCT01—ILCT24仍全部待运行。

剩余设计必须补齐：完整manifest／文件清单与导入IPC、申请及批准完整权限提供者、配置投影的受控词表、生命周期完整事务和新RuntimeBinding、公共SDK同版归并、C12最终容量及全部证据分页。Schema及参考检查不能独自关闭这些条目；用户审阅前本候选不视为冻结。
