# Chart Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add broker-style technical indicators to the K-line page with accurate full-history calculations.

**Architecture:** Add a read-only indicator endpoint that computes technical features from complete local history and returns the visible range. The React chart page manages selected indicators while ECharts dynamically builds overlays and indicator panes.

**Tech Stack:** Python, FastAPI, Pandas, React, TypeScript, ECharts, Pytest, Vitest.

---

### Task 1: Chart indicator API

**Files:**
- Modify: `src/astock/api/app.py`
- Test: `tests/api/test_screening_api.py`

- [ ] Write a failing endpoint test with more than 20 daily bars before the requested window. Assert `GET /api/symbols/600001.SH/indicators` returns the requested timestamps and a non-null precomputed `ma_20`.
- [ ] Run `uv run pytest tests/api/test_screening_api.py -q` and verify the new route fails.
- [ ] Read all final QFQ base bars, derive the requested timeframe, calculate via `compute_technical_features`, replace NaN values with JSON null, and return only requested timestamps.
- [ ] Re-run the focused API test and commit `feat: expose chart indicators`.

### Task 2: Dynamic chart indicators

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/features/chart/chartOptions.ts`
- Modify: `web/src/features/chart/chartOptions.test.ts`
- Modify: `web/src/features/chart/StockChart.tsx`

- [ ] Write failing chart-option tests for default MA lines, BOLL overlay, MACD pane, and every x-axis included in zoom synchronization.
- [ ] Run `npm test -- src/features/chart/chartOptions.test.ts` and verify the new assertions fail.
- [ ] Add indicator types/configuration and construct overlay/subchart series plus dynamic grid, axes and zoom from the selected list.
- [ ] Re-run the focused test and commit `feat: render technical indicators on charts`.

### Task 3: Indicator menu and page data flow

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/api.test.ts`
- Modify: `web/src/features/chart/ChartPage.tsx`
- Modify: `web/src/features/chart/ChartPage.test.tsx`
- Modify: `web/src/styles.css`

- [ ] Write failing tests that default to MA, add MACD through the indicators menu, remove it, and request indicators when the timeframe changes.
- [ ] Run `npm test -- src/api.test.ts src/features/chart/ChartPage.test.tsx` and verify the assertions fail.
- [ ] Implement the API client, selected indicator state, menu interactions and restrained menu styles; pass indicator data/configuration into `StockChart`.
- [ ] Re-run focused frontend tests, full backend/frontend suites, lint and production build; commit `feat: manage technical indicators on charts`.
