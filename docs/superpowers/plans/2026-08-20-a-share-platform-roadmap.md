# A 股策略平台实施路线图

依据设计文档：[`2026-08-20-a-share-backtest-monitor-design.md`](../specs/2026-08-20-a-share-backtest-monitor-design.md)

按以下顺序执行。每个阶段完成后运行该计划末尾的验收命令，再进入下一阶段。

1. [`2026-08-20-a-share-foundation-data.md`](2026-08-20-a-share-foundation-data.md)：项目骨架、领域模型、DuckDB/Parquet、BaoStock、mootdx、周期聚合和数据质量。
2. [`2026-08-20-a-share-strategy-backtest.md`](2026-08-20-a-share-strategy-backtest.md)：技术指标、配置规则、Python 策略、撮合、真实 A 股规则、组合与报告。
3. [`2026-08-20-a-share-live-monitoring.md`](2026-08-20-a-share-live-monitoring.md)：交易时段调度、信号去重、模拟账户、飞书和恢复机制。
4. [`2026-08-20-a-share-web-console.md`](2026-08-20-a-share-web-console.md)：本地网页控制台、后台任务入口、端到端流程和启动文档。

每个计划依赖前一个计划的公开接口，不允许跨阶段直接访问其他模块内部实现。

## 验收追踪

| 已确认验收项 | 负责计划 / 里程碑 |
| --- | --- |
| 日、周、月、5/15/30/60 分钟数据与回测 | 底座 Task 5/10；回测 Task 7/10 |
| 配置式与 Python 策略 | 回测 Task 3/4 |
| 单股与组合、结果可重复 | 回测 Task 7/8/10 |
| 简化/真实 A 股规则 | 回测 Task 5/6 |
| 自选股 5 秒、全市场 5 分钟 | 实时 Task 7/8 |
| 飞书仅推送一次并更新模拟持仓 | 实时 Task 2/5/6/9 |
| 重启恢复任务、状态、持仓与数据 | 实时 Task 2/8/9 |
| 异常数据停止信号并显示原因 | 底座 Task 6；实时 Task 7；Web Task 3/6/7 |
| 两条完整端到端流程 | Web Task 9/10 |

第一版边界保持不变：仅 A 股、本机单用户、只做模拟交易；不实现真实券商下单、卖空、云部署、多年 1 分钟、参数寻优或任意深度表达式。
