# AStock Mobile Responsive Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all four AStock modules fully operable on common phone viewports, with K-line research supporting a focused full-screen watch mode.

**Architecture:** Keep one React component tree for desktop and mobile. Add semantic state only where mobile behavior requires it (active navigation and K-line full-screen); use responsive CSS for layout changes and component-local scrolling for dense data. Preserve all backend contracts and desktop layouts.

**Tech Stack:** React 19, TypeScript, ECharts 6, CSS media queries, Vitest/Testing Library, Playwright.

---

### Task 1: Mobile application shell

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write the failing navigation semantics test**

Add an assertion that the selected navigation button exposes its current state:

```tsx
expect(screen.getByRole("button", { name: "条件选股" })).toHaveAttribute("aria-current", "page");
await userEvent.click(screen.getByRole("button", { name: "K 线研究" }));
expect(screen.getByRole("button", { name: "K 线研究" })).toHaveAttribute("aria-current", "page");
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd web && npm test -- --run src/App.test.tsx`

Expected: FAIL because navigation buttons do not expose `aria-current`.

- [ ] **Step 3: Implement navigation semantics and mobile shell CSS**

Set `aria-current={page === id ? "page" : undefined}`. At `max-width: 760px`, turn `.app-frame` into one column and `.rail` into a fixed bottom bar using `env(safe-area-inset-bottom)`. Hide `.brand`, `.rail-foot`, `.nav-index`; make four navigation buttons equal width, vertically stack icon and label, and reserve bottom padding on all module pages.

- [ ] **Step 4: Run focused tests and commit**

Run: `cd web && npm test -- --run src/App.test.tsx`

Expected: PASS.

Commit: `git commit -am "feat: add mobile application navigation"`

### Task 2: Mobile condition composer and screening results

**Files:**
- Modify: `web/src/features/screener/ConditionTree.tsx`
- Modify: `web/src/features/screener/ConditionTree.test.tsx`
- Modify: `web/src/features/screener/ResultsTable.tsx`
- Modify: `web/src/features/screener/ScreenerPage.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing structural tests**

Verify condition controls have stable wrappers for responsive placement and the results table exposes a scroll region:

```tsx
expect(screen.getByLabelText("周期").closest(".condition-field")).not.toBeNull();
expect(screen.getByRole("region", { name: "筛选结果表格" })).toHaveClass("results-table-wrap");
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd web && npm test -- --run src/features/screener/ConditionTree.test.tsx src/features/screener/ScreenerPage.test.tsx`

Expected: FAIL because the wrappers/region are absent.

- [ ] **Step 3: Add minimal semantic wrappers**

Wrap period/operator/value controls in `.condition-field` containers without changing values or callbacks. Set `role="region" aria-label="筛选结果表格" tabIndex={0}` on the table scroll container.

- [ ] **Step 4: Add responsive layouts**

At phone width, make headings and screening controls full width; use condition cards with the metric path spanning the card, two-column controls above 390px and one-column at 380px or below. Expand buttons to 44px, constrain choice popovers to the viewport, stack result explanation below the table, and let pagination wrap without page-level overflow.

- [ ] **Step 5: Run focused tests and commit**

Run: `cd web && npm test -- --run src/features/screener/ConditionTree.test.tsx src/features/screener/ScreenerPage.test.tsx`

Expected: PASS.

Commit: `git commit -am "feat: adapt stock screening for phones"`

### Task 3: K-line focused full-screen mode

**Files:**
- Modify: `web/src/features/chart/ChartPage.tsx`
- Modify: `web/src/features/chart/ChartPage.test.tsx`
- Modify: `web/src/features/chart/StockChart.tsx`
- Modify: `web/src/features/chart/StockChart.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing full-screen interaction test**

Test that the chart desk can enter and exit focused mode while preserving selected indicators:

```tsx
await userEvent.click(screen.getByRole("button", { name: "全屏看盘" }));
expect(screen.getByTestId("chart-desk")).toHaveClass("is-fullscreen");
expect(screen.getByText("指标：ma,macd")).toBeInTheDocument();
await userEvent.click(screen.getByRole("button", { name: "退出全屏" }));
expect(screen.getByTestId("chart-desk")).not.toHaveClass("is-fullscreen");
```

- [ ] **Step 2: Write failing chart resize observer test**

Provide a controllable `ResizeObserver` mock, render `StockChart`, trigger the observer, and assert `chart.resize()` is called.

- [ ] **Step 3: Run chart tests and verify RED**

Run: `cd web && npm test -- --run src/features/chart/ChartPage.test.tsx src/features/chart/StockChart.test.tsx`

Expected: FAIL because full-screen controls and element resize observation are missing.

- [ ] **Step 4: Implement focused mode**

Add `fullscreen` state to `ChartPage`, a `data-testid="chart-desk"` class toggle, and buttons labeled `全屏看盘` / `退出全屏`. While active, add a body class to prevent background scrolling and attempt `screen.orientation.lock("landscape")` inside a caught promise; unlock on exit where supported. Do not clear symbol, timeframe, indicators, zones, or drawing state.

- [ ] **Step 5: Make StockChart responsive**

Replace the fixed inline height with CSS custom properties for desktop/mobile heights. Observe the chart element with `ResizeObserver` and call `chart.resize()` whenever its box changes; keep the existing window resize fallback and clean up both listeners.

- [ ] **Step 6: Add mobile chart styling**

Make search full width; convert timeframe, indicator, drawing-kind and geometry controls to horizontal scroll strips; reduce chart grid padding; make support/resistance cards one column. In `.chart-desk.is-fullscreen`, use `position: fixed; inset: 0; z-index`, `100dvh`, safe-area padding, internal scrolling, and hide the page header and zone ledger through the page full-screen class.

- [ ] **Step 7: Run focused tests and commit**

Run: `cd web && npm test -- --run src/features/chart/ChartPage.test.tsx src/features/chart/StockChart.test.tsx src/features/chart/chartOptions.test.ts`

Expected: PASS.

Commit: `git commit -am "feat: add mobile full-screen chart desk"`

### Task 4: Backtest and monitoring phone layouts

**Files:**
- Modify: `web/src/features/backtest/BacktestPage.tsx`
- Modify: `web/src/features/backtest/BacktestPage.test.tsx`
- Modify: `web/src/features/monitor/MonitorPage.tsx`
- Modify: `web/src/features/monitor/MonitorPage.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing accessible scroll-region tests**

For backtest trades and monitor ledgers, assert stable regions:

```tsx
expect(screen.getByRole("region", { name: "交易明细表格" })).toHaveClass("table-scroll");
expect(screen.getByRole("region", { name: "监控任务" })).toBeInTheDocument();
expect(screen.getByRole("region", { name: "最近触发" })).toBeInTheDocument();
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd web && npm test -- --run src/features/backtest/BacktestPage.test.tsx src/features/monitor/MonitorPage.test.tsx`

Expected: FAIL because the regions are not labelled.

- [ ] **Step 3: Add region semantics and responsive CSS**

Label the existing scroll/ledger elements without altering data behavior. At phone width use one-column backtest configuration, stacked strategy trees, two-column metrics, full-width run button, and internal trade scrolling. Use two-column monitor summaries, one-column creation form, full-width create button, stacked task/signal ledgers, wrapped symbols, and 44px task actions.

- [ ] **Step 4: Run focused tests and commit**

Run: `cd web && npm test -- --run src/features/backtest/BacktestPage.test.tsx src/features/monitor/MonitorPage.test.tsx`

Expected: PASS.

Commit: `git commit -am "feat: adapt backtest and monitoring for phones"`

### Task 5: Real viewport regression coverage

**Files:**
- Modify: `web/e2e/workbench.spec.ts`
- Modify: `web/playwright.config.ts` only if the existing server configuration cannot run the mobile cases

- [ ] **Step 1: Add mobile viewport tests**

Reuse API routes from the existing workbench test and iterate through phone sizes. For each viewport, navigate all four pages and assert:

```ts
expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
```

At 390×844 enter K-line full-screen, verify the chart desk fills the viewport, switch to 844×390, then exit and confirm the selected indicator remains visible.

- [ ] **Step 2: Run E2E and fix only demonstrated layout defects**

Run: `cd web && npm run test:e2e`

Expected: all desktop and mobile cases PASS with no console/page errors.

- [ ] **Step 3: Run full verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
cd web
npm test
npm run build
npm run test:e2e
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit verification coverage**

Commit: `git commit -am "test: cover mobile workbench layouts"`

### Task 6: Deploy local service and inspect the real Tailscale page

**Files:**
- No tracked source files expected

- [ ] **Step 1: Fast-forward the main branch after verification**

From the primary worktree, merge `codex/mobile-responsive-workbench` with `--ff-only`.

- [ ] **Step 2: Rebuild and restart the existing Tailscale service**

Build `web/dist` in the service worktree, restart only `com.astock.local8888`, and verify `http://100.90.109.126:8888/` returns the app.

- [ ] **Step 3: Verify mobile rendering against the running service**

Use a 390×844 browser viewport to open the real service, visit each module, enter/exit K-line full-screen, and confirm no page-level horizontal overflow or browser errors.

- [ ] **Step 4: Push the completed main branch**

Run: `git push origin main`

Expected: remote `main` points to the verified mobile implementation commit.
