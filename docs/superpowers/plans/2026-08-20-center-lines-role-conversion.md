# Center Lines and Role Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render support and resistance as clear center lines, make weekly trend lines visible, and reclassify broken automatic levels relative to the latest close.

**Architecture:** Keep stored price zones unchanged. `nearest_zones()` derives an effective role for automatic zones before ranking, while the chart converts horizontal zones to `markLine` and trend anchors to index-aligned line data. Manual roles remain user-controlled.

**Tech Stack:** Python, DuckDB, React, TypeScript, ECharts, Pytest, Vitest, Playwright

---

### Task 1: Reclassify automatic support and resistance

**Files:**
- Modify: `src/astock/features/zones.py:288-325`
- Test: `tests/features/test_zones.py`

- [ ] **Step 1: Add a failing role-conversion test**

Create a test with latest close `10`, an automatic support centered at `12`, an automatic
resistance centered at `8`, and a manual support centered at `11`. Assert that the returned
automatic roles become resistance and support respectively, while the manual support stays
support.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `.venv/bin/pytest -q tests/features/test_zones.py -k role_conversion`

Expected: FAIL because `nearest_zones()` currently returns stored `zone_kind` values.

- [ ] **Step 3: Implement effective automatic roles**

After loading rows in `nearest_zones()`, copy each automatic row and set:

```python
effective["zone_kind"] = (
    "support" if effective["center_price"] < close_row[0] else "resistance"
)
```

Leave manual rows unchanged, then rank the transformed rows separately by role and distance.

- [ ] **Step 4: Run feature-zone tests**

Run: `.venv/bin/pytest -q tests/features/test_zones.py`

Expected: all tests pass.

- [ ] **Step 5: Commit backend change**

```bash
git add src/astock/features/zones.py tests/features/test_zones.py
git commit -m "fix: reclassify broken automatic price levels"
```

### Task 2: Render center lines and repair trend timestamps

**Files:**
- Modify: `web/src/features/chart/chartOptions.ts`
- Test: `web/src/features/chart/chartOptions.test.ts`

- [ ] **Step 1: Add failing center-line and weekly-trend tests**

Assert that a horizontal zone series contains a center-price `markLine`, contains no
`markArea`, and labels the center price. Add weekly bars with full ISO timestamps and trend
anchors using `YYYY-MM-DD`; assert the generated trend data begins at the matching bar and
extends through the latest bar.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `cd web && npm test -- --run src/features/chart/chartOptions.test.ts`

Expected: FAIL because horizontal series still contains `markArea` and trend anchors are passed
through without date mapping.

- [ ] **Step 3: Implement horizontal center lines**

Remove `markArea`. Use a `markLine` at `zone.center_price`, with a visible end label containing
the presentation label and price. Set automatic width to `2` and manual width to `3`.

- [ ] **Step 4: Implement index-aligned trend lines**

Pass `bars` into `zoneSeries()`. Match `anchorDate` to `bar.timestamp.slice(0, 10)`, calculate
the per-index slope from the first and last matched anchors, return `null` before the first anchor,
and project values through the final bar. Show the final projected value in `endLabel`.

- [ ] **Step 5: Run chart-option tests**

Run: `cd web && npm test -- --run src/features/chart/chartOptions.test.ts`

Expected: all tests pass.

- [ ] **Step 6: Commit chart change**

```bash
git add web/src/features/chart/chartOptions.ts web/src/features/chart/chartOptions.test.ts
git commit -m "feat: render support resistance center lines"
```

### Task 3: Rename chart UI from zones to lines

**Files:**
- Modify: `web/src/features/chart/ChartPage.tsx`
- Modify: `web/src/features/chart/DrawingToolbar.tsx`
- Test: `web/src/features/chart/ChartPage.test.tsx`

- [ ] **Step 1: Add failing UI wording assertions**

Assert that the page shows `支撑压力线`, the toolbar exposes `水平线` and `趋势线`, and the
ledger shows the single `center_price` rather than `lower_price — upper_price`.

- [ ] **Step 2: Run the focused page test and confirm failure**

Run: `cd web && npm test -- --run src/features/chart/ChartPage.test.tsx`

Expected: FAIL because the current page uses the word `区间` and displays a range.

- [ ] **Step 3: Update UI wording and ledger price**

Rename labels and accessibility names from `区间` to `线`, change error and empty messages to
line terminology, and render `zone.center_price.toFixed(2)` in the ledger.

- [ ] **Step 4: Run page tests**

Run: `cd web && npm test -- --run src/features/chart/ChartPage.test.tsx`

Expected: all tests pass.

- [ ] **Step 5: Commit UI change**

```bash
git add web/src/features/chart/ChartPage.tsx web/src/features/chart/DrawingToolbar.tsx web/src/features/chart/ChartPage.test.tsx
git commit -m "fix: clarify support resistance line controls"
```

### Task 4: Full verification

**Files:**
- Modify if required by updated copy: `web/e2e/workbench.spec.ts`

- [ ] **Step 1: Run backend verification**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`

Expected: all Python tests and lint pass.

- [ ] **Step 2: Run frontend verification**

Run: `cd web && npm test -- --run && npm run build && npm run test:e2e`

Expected: all Vitest tests, production build, and Playwright flow pass.

- [ ] **Step 3: Verify the actual weekly API**

Run: `curl --fail 'http://127.0.0.1:8888/api/symbols/600519.SH/zones?timeframe=1w&as_of=2026-08-20&limit_each=20'`

Expected: JSON includes the trend support and reclassified automatic horizontal lines.

- [ ] **Step 4: Confirm clean worktree**

Run: `git status --short`

Expected: no output after any required final commit.
