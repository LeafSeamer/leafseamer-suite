# 摄取事务独立封存候选

状态：`approved=false`。本候选替代[类型化Seamer](TYPED_SEAMER.md)的摄取封存关系，交付[组合生成器](build_atomic_ingress.py)、[121表DDL](seamer-atomic-ingress.sql)、[独立封存约束](atomic-ingress.sql)、[参考writer](atomic_ingress_model.py)、[检查器](check_atomic_ingress.py)及[实测报告](atomic-ingress-report.json)。这是设计验证成果，未开始业务服务实现。

## 已知事实

存在未解决的延迟外键违例时，COMMIT应失败。（来源：[SQLite官方外键说明](https://www.sqlite.org/foreignkeys.html#fk_deferred)。）本机Python和Node内置SQLite 3.50.4使用同一[合成向量](fk-seal-vectors.json)，均观察到：缺失父记录的child与自引用seal同时写入，再把seal.sealed从0更新到1，COMMIT成功，而foreign_key_check仍报告child孤儿。这些向量不含应用触发器，也未关闭外键或切换defer_foreign_keys。

旧结构的孤儿用例在报告中明确保存`conforms=false`，不以总检查通过掩盖其违例。新的独立封存结构在两个本机运行时均要求：完整写集可提交；漏父记录、漏封存行、漏sealed=1更新均拒绝提交。报告记录各自运行时版本与SQLite source id；两个运行时使用同源SQLite，不代表两个引擎版本或正式原生依赖均已覆盖。

## 基于事实的设计处理

已定位可复现触发结构，尚未审查SQLite内部实现，不能把内部计数器机理当成已证实根因。新候选将可变自引用关系替换为两个表的相互延迟外键：ingress_commit要求同ID的ingress_commit_seal；后者固定sealed=1且要求同ID、sealed=1的ingress_commit。封存原件不可更新或删除，原有提交封存触发器和完整写集检查保留。

参考writer在原最终sealed更新前加入唯一封存行。accepted、no_match及suppressed_busy都使用同一事务；同键同内容查原不增加行，同键异内容拒绝。漏封存、错ID、漏最终更新会整笔回滚，不能用事后补录完成摄取。现有旧写入器未加入封存行，不能直接用于新布局；本轮不迁移旧数据库。

检查在实际121表组合库中逐写注入异常，验证回滚；独立内存库额外移除typed_plan_source_seal并漏写typed_execution_source，直接使用无预提交foreign_key_check的事务执行器，仍须由SQLite外键拒绝提交。这一用例验证替代关系本身，未改变交付DDL。完整执行绑定及两个目标的命令请求继续通过既有字段一致性检查。

## 剩余冻结事项

- 保留可信writer的外键启用检查、提交前foreign_key_check和原件封存检查。全库检查的生产成本未核定，不能凭本轮离线测试删除防线。
- 正式选定的原生SQLite制品须运行同向量、完整组合库故障集和磁盘崩溃恢复；本机Node内置SQLite不能替代该制品验证。其他自引用历史关系未被本轮证明全部安全。
- 新封存行及此前新增完整正文必须计入CostManifest，完成准入预留和实际扣费对应。Controller完整请求受理、拒收和查原尚待接入；普通arm和恢复动作的类型化路径仍待扩展。
- 本轮只验证内存SQLite和合成提供者，没有实际HTTP/IPC、监督时钟、设备或直播运行验证，阶段0保持未关闭。

```powershell
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/build_atomic_ingress.py --check
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_atomic_ingress.py --report
docs/contracts/.venv/Scripts/python.exe docs/contracts/c04-lifecycle/check_atomic_ingress.py --check-report
```
