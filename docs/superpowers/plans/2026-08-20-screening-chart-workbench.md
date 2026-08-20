# A 股选股与 K 线工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个本地可运行的选股工作台，用下拉框构建任意嵌套 AND/OR/NOT 条件，展示全市场选股结果、K 线和成交量，并支持自动/手动支撑压力位。

**Architecture:** FastAPI 提供稳定 JSON API 和 SPA 静态文件；React + TypeScript 管理条件树与结果状态；Apache ECharts 绘制 K 线、成交量、区间与趋势线。自动线与手动线共用同一领域模型，通过 `source` 字段区分。

**Tech Stack:** Python 3.12, FastAPI, DuckDB, React 19, TypeScript, Vite, Apache ECharts, Vitest, Testing Library, pytest, Ruff.

### Task 1: 补齐筛选数据与手动区间 API

**Files:** `src/astock/features/store.py`, `src/astock/features/zones.py`, `src/astock/api/app.py`, `tests/features/test_store.py`, `tests/features/test_zones.py`, `tests/api/test_screening_api.py`

- [x] 先写失败测试：特征 JSON 展开、形态/支撑压力并入筛选快照、手动区间 CRUD。
- [x] 实现并验证：手动数据不被自动重算删除，自动与手动区间可同时返回。
- [x] 扩展条件目录，覆盖新高/新低、回撤、连涨/连跌、形态与区间距离。

### Task 2: 搭建前端应用外壳和 API 客户端

**Files:** `web/package.json`, `web/vite.config.ts`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api.ts`, `web/src/types.ts`, `web/src/styles.css`, `web/src/App.test.tsx`

- [x] 先写失败测试：页签、数据状态、选股页首屏。
- [x] 实现深色交易终端外壳，支持宽屏和窄屏，数字使用等宽字体。
- [x] Vite 开发代理 `/api` 到 FastAPI，生产构建输出由 FastAPI 托管。

### Task 3: 实现任意嵌套条件树与选股结果

**Files:** `web/src/features/screener/ConditionTree.tsx`, `ConditionRow.tsx`, `ResultsTable.tsx`, `ScreenerPage.tsx`, 对应 `*.test.tsx`

- [x] 先写失败测试：新增/删除条件、嵌套 AND/OR/NOT、常量/指标对比、校验错误。
- [x] 根据后端 catalog 动态渲染指标、周期、操作符和单位，不在前端重复业务规则。
- [x] 运行收盘/实时筛选，展示排名、证券名称、关键数值和逐层命中解释。

### Task 4: 实现 K 线、成交量与支撑压力绘图

**Files:** `web/src/features/chart/StockChart.tsx`, `DrawingToolbar.tsx`, `ChartPage.tsx`, 对应 `*.test.tsx`

- [x] 先写失败测试：5/15/30/60 分钟、日/周/月切换；颜色和线型映射；手动线提交。
- [x] K 线与成交量共享时间轴、缩放和十字光标。
- [x] 支撑使用绿色，压力使用红色；自动区间半透明虚线，手动区间/趋势线实线并带“手动”标识。
- [x] 手动模式先选支撑或压力，再用两个锚点创建水平区间或趋势区间，可删除。

### Task 5: 端到端验收与本地启动

**Files:** `src/astock/api/app.py`, `tests/integration/test_web_workbench.py`, `README.md`

- [x] 构建前端，从 FastAPI 首页打开工作台。
- [ ] 以固定数据验收“过去 20 个交易周期涨幅≥30%”、查看 K 线、自动区间和保存手动趋势线。
- [x] 运行 `uv run --extra dev pytest -q`、`uv run --extra dev ruff check src tests`、`npm test -- --run`、`npm run build`。
