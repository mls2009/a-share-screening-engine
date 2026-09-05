# AStock 项目记忆

## 项目概况
- A 股选股/K线/回测/实时监控工作台，Python 3.12 + FastAPI 后端（src/astock，约 6300 行），React+Vite+TS 前端（web/src，约 3200 行），Playwright e2e。
- 数据源：BaoStock（沪深日线主源）、AKShare（北交所）、腾讯行情（盘中快照）、mootdx。日线存 Parquet，其余存 DuckDB（data/ 目录，ASTOCK_DATA_DIR 可改）。
- 核心模块：data（同步+providers 路由+快照+质量）、features（技术指标/形态/支撑压力 zones）、screening（受控 JSON 条件树，三值逻辑，close/live 两模式）、backtest（A股规则近似：T+1、整手、费税）、live（监控调度+飞书通知 outbox 重试）、api（FastAPI 一体化服务，前端静态托管，端口 8888）。
- CLI 入口：astock（data sync-market / screen / backtest 等）。
- 前端四工作区：screener / chart / backtest / monitor。
- 测试：pytest（tests/ 按模块分目录）+ vitest + playwright e2e。
