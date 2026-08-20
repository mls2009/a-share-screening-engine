# Hover Labels and Directional Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide persistent labels on automatic chart lines and independently display the best rising and falling trend line for every supported timeframe.

**Architecture:** Keep horizontal support/resistance selection isolated for screening features. Persist automatic trends as `uptrend`/`downtrend`, expose them through a chart-specific selector, and render automatic overlays as hoverable ECharts lines without persistent labels.

**Tech Stack:** Python 3.12, pandas, NumPy, DuckDB, FastAPI, React, TypeScript, ECharts 6, Pytest, Vitest, Playwright

---

### Task 1: Detect directional trends for every timeframe

**Files:**
- Modify: `src/astock/features/zones.py`
- Test: `tests/features/test_zones.py`

- [ ] **Step 1: Replace role-based daily expectations with failing direction tests**

Add tests that construct recent pivot windows and assert that `detect_zones()` returns at most one automatic `uptrend` and one automatic `downtrend`, independently of price position:

```python
def test_detects_best_uptrend_and_downtrend_without_support_roles() -> None:
    frame = _frame(
        [12, 9, 15, 10, 14, 11, 13, 12, 12.5, 13, 12.8, 14, 13.2],
        lows={1: 8, 3: 9, 5: 10, 7: 11, 10: 12},
        highs={2: 17, 4: 16, 6: 15, 9: 14.5, 11: 14},
    )
    zones = detect_zones(frame, date(2026, 1, 19), timeframe=Timeframe.DAY, pivot_order=1)
    trends = [zone for zone in zones if zone.geometry == "trend"]
    assert [zone.zone_kind for zone in trends].count("uptrend") == 1
    assert [zone.zone_kind for zone in trends].count("downtrend") == 1
    assert next(zone for zone in trends if zone.zone_kind == "uptrend").slope > 0
    assert next(zone for zone in trends if zone.zone_kind == "downtrend").slope < 0
```

Add a second test using nearly equal pivots and assert no trend is created when total fitted movement is below one tolerance. Parameterize the first test over `Timeframe.DAY`, `Timeframe.WEEK`, and `Timeframe.MONTH` to prove the rule is not daily-only.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/features/test_zones.py -k "directional or near_horizontal" -q
```

Expected: FAIL because current code returns `support`/`resistance` trends and has daily-only fallback behavior.

- [ ] **Step 3: Implement one best candidate per slope direction**

Replace `_daily_trend_zone()` and the current role-based trend loop with a direction helper used for all timeframes. Use recent pivot windows from both low and high pivots, reject residuals above tolerance and fitted movement below tolerance, then rank by recency, touches, and residual:

```python
def _directional_trend_zones(
    data: pd.DataFrame,
    as_of: date,
    positions_by_column: tuple[tuple[str, list[int]], ...],
    tolerance: float,
    rule_version: str,
) -> list[PriceZone]:
    candidates: dict[str, list[tuple]] = {"uptrend": [], "downtrend": []}
    for column, positions in positions_by_column:
        recent = positions[-12:]
        for size in range(2, min(5, len(recent)) + 1):
            for start in range(len(recent) - size + 1):
                selected = recent[start : start + size]
                slope, intercept, center, residual = _fit_trend(data, selected, column)
                movement = abs(slope) * (selected[-1] - selected[0])
                if residual > tolerance or movement < tolerance or slope == 0:
                    continue
                direction = "uptrend" if slope > 0 else "downtrend"
                candidates[direction].append(
                    (selected, column, slope, intercept, center, residual)
                )
    zones = []
    for direction, matching in candidates.items():
        if not matching:
            continue
        selected, column, slope, intercept, center, residual = min(
            matching,
            key=lambda item: (-item[0][-1], -len(item[0]), item[5] / tolerance),
        )
        anchors = tuple(
            (pd.Timestamp(data.iloc[position]["timestamp"]).date(), float(data.iloc[position][column]))
            for position in selected
        )
        zones.append(PriceZone(
            as_of_date=as_of,
            zone_kind=direction,
            geometry="trend",
            lower_price=center - tolerance,
            center_price=center,
            upper_price=center + tolerance,
            slope=slope,
            intercept=intercept,
            anchors=anchors,
            strength=max(0.1, min(1.0, len(selected) / 5 * (1 - residual / tolerance))),
            touches=len(selected),
            rule_version=rule_version,
        ))
    return zones
```

Call it once from `detect_zones()` with `(("low", low_positions), ("high", high_positions))`. Remove artificial line shifting and all current-price support/resistance checks for automatic trend geometry. Keep horizontal detection unchanged.

- [ ] **Step 4: Run all zone tests and verify GREEN**

Run:

```bash
uv run pytest tests/features/test_zones.py -q
uv run ruff check src/astock/features/zones.py tests/features/test_zones.py
```

Expected: all zone tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add src/astock/features/zones.py tests/features/test_zones.py
git commit -m "feat: detect directional trend lines"
```

### Task 2: Separate chart overlays from screening support distances

**Files:**
- Modify: `src/astock/features/zones.py`
- Modify: `src/astock/api/app.py`
- Test: `tests/features/test_zones.py`
- Test: `tests/api/test_screening_api.py`

- [ ] **Step 1: Write failing selector and API contract tests**

Insert nearer horizontal rows plus `uptrend` and `downtrend` rows for the same automatic batch. Assert `nearest_zones(..., limit_each=1)` contains only one horizontal support and one horizontal resistance, while `chart_zones(..., limit_each=1)` additionally contains one trend per direction and active manual lines:

```python
nearest = nearest_zones(connection, symbol, Timeframe.DAY, as_of, limit_each=1)
chart = chart_zones(connection, symbol, Timeframe.DAY, as_of, limit_each=1)
assert {row["geometry"] for row in nearest} == {"horizontal"}
assert {row["zone_kind"] for row in chart if row["source"] == "auto"} == {
    "support", "resistance", "uptrend", "downtrend"
}
```

Update the API contract test so `GET /api/symbols/{symbol}/zones` must return directional trends even when `limit_each=1` is already consumed by horizontal lines.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
uv run pytest tests/features/test_zones.py -k "chart_zones" -q
uv run pytest tests/api/test_screening_api.py -k "bars_zones" -q
```

Expected: FAIL because `chart_zones` does not exist and the endpoint still calls `nearest_zones`.

- [ ] **Step 3: Add shared row decoration and chart-specific selection**

Extract the active-batch query, automatic horizontal role conversion, and deletion-marker matching into a private `_active_zones()` helper. Implement selectors with these rules:

```python
def nearest_zones(connection, symbol, timeframe, as_of, limit_each=3):
    rows, close = _active_zones(connection, symbol, timeframe, as_of)
    selected = []
    for kind in ("support", "resistance"):
        matching = [row for row in rows if row["geometry"] == "horizontal" and row["zone_kind"] == kind]
        matching.sort(key=lambda row: abs(row["center_price"] - close))
        selected.extend(matching[:limit_each])
    return selected

def chart_zones(connection, symbol, timeframe, as_of, limit_each=3):
    rows, close = _active_zones(connection, symbol, timeframe, as_of)
    manual = [row for row in rows if row["source"] == "manual"]
    horizontal = [row for row in nearest_zones(connection, symbol, timeframe, as_of, limit_each) if row["source"] == "auto"]
    trends = []
    for direction in ("uptrend", "downtrend"):
        matching = [row for row in rows if row["source"] == "auto" and row["geometry"] == "trend" and row["zone_kind"] == direction]
        matching.sort(key=lambda row: (row["last_touched_on"], row["touches"], row["strength"]), reverse=True)
        trends.extend(matching[:1])
    return manual + horizontal + trends
```

Avoid duplicate queries in the final implementation by passing already decorated rows into a small horizontal selection helper. In `src/astock/api/app.py`, import and call `chart_zones()` for the chart endpoint. Leave `MarketFeatureStore` on `nearest_zones()` so screening distances remain horizontal-only.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/features/test_zones.py tests/api/test_screening_api.py -q
uv run ruff check src/astock/features/zones.py src/astock/api/app.py tests/features/test_zones.py tests/api/test_screening_api.py
```

Expected: all focused tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add src/astock/features/zones.py src/astock/api/app.py tests/features/test_zones.py tests/api/test_screening_api.py
git commit -m "feat: expose chart trend overlays"
```

### Task 3: Add directional names and remove persistent automatic labels

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/features/chart/chartOptions.ts`
- Modify: `web/src/features/chart/ChartPage.tsx`
- Test: `web/src/features/chart/chartOptions.test.ts`
- Test: `web/src/features/chart/ChartPage.test.tsx`

- [ ] **Step 1: Write failing presentation and page tests**

Expand test fixtures to accept directional kinds and add assertions:

```typescript
expect(zonePresentation({ ...trend, zone_kind: "uptrend", slope: 0.1 })).toMatchObject({
  color: "#2ecf79",
  label: "自动上升趋势线",
});
expect(zonePresentation({ ...trend, zone_kind: "downtrend", slope: -0.1 })).toMatchObject({
  color: "#ff5a67",
  label: "自动下降趋势线",
});
```

Build an option containing automatic horizontal and directional lines. Assert automatic `markLine.label.show` and automatic trend `endLabel.show` are false, while manual lines retain visible labels. In `ChartPage.test.tsx`, assert the ledger contains “自动上升趋势线” and “自动下降趋势线”, never “自动趋势支撑/压力”.

- [ ] **Step 2: Run frontend focused tests and verify RED**

Run:

```bash
cd web && npm test -- src/features/chart/chartOptions.test.ts src/features/chart/ChartPage.test.tsx
```

Expected: TypeScript/test failures because directional kinds and labels are unsupported and automatic labels remain visible.

- [ ] **Step 3: Extend the UI type and centralize labels**

Change the union and presentation function:

```typescript
export interface PriceZone {
  zone_kind: "support" | "resistance" | "uptrend" | "downtrend";
}

export function zonePresentation(zone: PriceZone) {
  const rising = zone.zone_kind === "support" || zone.zone_kind === "uptrend";
  const direction = zone.zone_kind === "uptrend"
    ? "上升趋势线"
    : zone.zone_kind === "downtrend"
      ? "下降趋势线"
      : zone.zone_kind === "support" ? "支撑" : "压力";
  return {
    color: rising ? "#2ecf79" : "#ff5a67",
    lineType: zone.reappeared ? "dashed" as const : "solid" as const,
    label: `${zone.source === "auto" ? "自动" : "手动"}${direction}`,
  };
}
```

Use `zonePresentation(zone).label` in `ChartPage` instead of rebuilding labels. Use support styling for `support/uptrend` ledger cards and resistance styling for `resistance/downtrend`. Set automatic persistent labels to hidden while leaving manual labels unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
cd web && npm test -- src/features/chart/chartOptions.test.ts src/features/chart/ChartPage.test.tsx
```

Expected: focused Vitest tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/features/chart/chartOptions.ts web/src/features/chart/ChartPage.tsx web/src/features/chart/chartOptions.test.ts web/src/features/chart/ChartPage.test.tsx
git commit -m "feat: label directional chart trends"
```

### Task 4: Show automatic line values only on direct hover

**Files:**
- Modify: `web/src/features/chart/chartOptions.ts`
- Test: `web/src/features/chart/chartOptions.test.ts`

- [ ] **Step 1: Write failing tooltip option tests**

Assert automatic horizontal mark lines are interactive and expose item-only tooltip text, while automatic trend lines trigger events on the line and format the hovered data point:

```typescript
expect(horizontal.markLine).toMatchObject({
  silent: false,
  label: { show: false },
  tooltip: { show: true, trigger: "item" },
});
expect(horizontal.markLine.tooltip.formatter({ value: 9.8 })).toContain("9.80");

expect(uptrend).toMatchObject({
  silent: false,
  triggerEvent: "line",
  endLabel: { show: false },
  tooltip: { show: true, trigger: "item" },
});
expect(uptrend.tooltip.formatter({ dataIndex: 1, value: 10.2 })).toContain("08-14");
expect(uptrend.tooltip.formatter({ dataIndex: 1, value: 10.2 })).toContain("10.20");
```

Also assert automatic series do not contribute persistent labels. Keep the existing line-regression test for non-collinear anchors.

- [ ] **Step 2: Run the chart option test and verify RED**

Run:

```bash
cd web && npm test -- src/features/chart/chartOptions.test.ts
```

Expected: FAIL because overlays are `silent`, automatic labels are permanent, and item tooltips are absent.

- [ ] **Step 3: Configure direct-hover tooltips**

For automatic horizontal `markLine`, set `silent: false`, `label.show: false`, and an item tooltip formatter returning label plus `center_price`. For automatic trend line series, set `silent: false`, `triggerEvent: "line"`, `endLabel.show: false`, and an item tooltip formatter that uses `params.dataIndex` to read the matching bar timestamp and `params.value` for the fitted price. Preserve `silent: true` and current permanent labels for manual overlays.

Set automatic overlay series tooltip trigger to `item` so their values do not appear in the global axis tooltip unless the pointer directly hits that line. Keep candlestick/volume axis tooltip behavior unchanged.

- [ ] **Step 4: Run focused tests and production build**

Run:

```bash
cd web && npm test -- src/features/chart/chartOptions.test.ts && npm run build
```

Expected: chart tests pass and Vite production build exits 0.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/chart/chartOptions.ts web/src/features/chart/chartOptions.test.ts
git commit -m "feat: reveal automatic line values on hover"
```

### Task 5: Build automatic trends for the requested chart timeframe

**Files:**
- Modify: `src/astock/features/builder.py`
- Modify: `src/astock/features/zones.py`
- Modify: `src/astock/api/app.py`
- Test: `tests/features/test_builder.py`
- Test: `tests/api/test_screening_api.py`

- [ ] **Step 1: Write failing minute-timeframe API tests**

Store final 5-minute bars containing valid rising and falling pivot windows, request `15m` zones, and assert the endpoint derives 15-minute bars, persists one automatic `uptrend` and one automatic `downtrend`, and returns them without requiring a pre-existing `market_features.close`. Request the endpoint a second time and assert the same automatic batch and zone ids are reused instead of rebuilt.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
uv run pytest tests/features/test_builder.py tests/api/test_screening_api.py -k "requested_timeframe or minute_chart" -q
```

Expected: FAIL because the chart endpoint only reads previously persisted zones and the builder has no timeframe-specific zone method.

- [ ] **Step 3: Add incremental chart-timeframe zone building**

Add a `FeatureBuilder.ensure_chart_zones(symbol, timeframe, as_of)` method that reads QFQ daily bars for daily/weekly/monthly or base 5-minute bars for minute timeframes, derives the requested aggregate with `MarketDataService.derive`, and returns the latest completed bar close. Only call `replace_auto_zones()` when the requested timeframe has no automatic batch or its latest `as_of_date` is older than the latest completed bar, so repeated GET requests are stable.

Allow `chart_zones()` to accept that latest-bar close as an optional override for horizontal distance and role conversion; keep `nearest_zones()` unchanged for screening. In the zones endpoint, call `ensure_chart_zones()` before `chart_zones()`. If no bars exist, preserve current manual-line behavior and return no new automatic lines.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/features/test_builder.py tests/api/test_screening_api.py tests/features/test_zones.py -q
uv run ruff check src/astock/features/builder.py src/astock/features/zones.py src/astock/api/app.py tests/features/test_builder.py tests/api/test_screening_api.py
```

Expected: focused tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add src/astock/features/builder.py src/astock/features/zones.py src/astock/api/app.py tests/features/test_builder.py tests/api/test_screening_api.py
git commit -m "feat: build trends for chart timeframes"
```

### Task 6: Rebuild real chart data, document behavior, and verify end to end

**Files:**
- Modify: `README.md`
- Test: existing backend/frontend/e2e suites

- [ ] **Step 1: Update user-facing documentation**

Document that `/api/symbols/{symbol}/zones` returns nearest horizontal support/resistance plus at most one automatic `uptrend` and one automatic `downtrend`, and that automatic chart labels appear only on direct hover. State that manual lines retain their chosen support/resistance role.

- [ ] **Step 2: Rebuild the current sample symbol without resyncing market data**

Run `FeatureBuilder.build_symbol()` against `data/astock.duckdb` without requesting new market data:

```bash
uv run python -c "from datetime import date; from astock.config import Settings; from astock.features.builder import FeatureBuilder; from astock.features.store import MarketFeatureStore; from astock.storage.bars import BarStore; from astock.storage.database import Database; settings=Settings(); database=Database(settings.database_path); database.migrate(); FeatureBuilder(BarStore(settings.bars_dir), MarketFeatureStore(database), database).build_symbol('600519.SH', date(2026, 8, 20)); database.connection.close()"
```

Then verify the query contains at most one active automatic trend per direction for each built timeframe:

```sql
with latest as (
  select timeframe, max(as_of_date) as as_of_date
  from support_resistance_zones
  where symbol = '600519.SH' and source = 'auto'
  group by timeframe
)
select zones.timeframe, zones.zone_kind, count(*)
from support_resistance_zones zones
join latest using (timeframe, as_of_date)
where zones.symbol = '600519.SH' and zones.source = 'auto'
  and zones.state = 'active'
  and zones.zone_kind in ('uptrend', 'downtrend')
group by zones.timeframe, zones.zone_kind
order by zones.timeframe, zones.zone_kind;
```

- [ ] **Step 3: Run full verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
cd web && npm test && npm run build && npm run test:e2e
```

Expected: all backend tests, Ruff, all Vitest tests, production build, and Playwright e2e pass.

- [ ] **Step 4: Restart port 8888 and inspect actual responses**

Restart the existing one-worker Uvicorn process from the feature worktree. Verify `/` returns 200 and the daily `/api/symbols/600519.SH/zones` response contains directional trend kinds when valid. In the K-line page verify no automatic labels are permanently painted, hovering automatic horizontal/trend lines reveals the correct value, and switching timeframe requests different lines without browser console errors.

- [ ] **Step 5: Request code review and address blockers**

Ask the existing review agent to inspect the implementation against the design, with emphasis on trend selection isolation, tooltip hit behavior, feature-store compatibility, and regressions. Fix Critical/Important findings using new failing tests before final verification.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: explain directional chart trends"
```
