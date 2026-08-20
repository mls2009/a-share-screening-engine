# Deletable Zones and Daily Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow deleting every support/resistance line, render only regenerated deleted levels as dashed, and always produce one daily trend support and resistance when enough pivots exist.

**Architecture:** Persist deletion markers independently from generated zones and annotate zone query results with `reappeared`. Keep current zone records replaceable, while deletion history survives recomputation. Extend only the daily detector with a bounded candidate-window search; keep other timeframes unchanged.

**Tech Stack:** Python 3.12, DuckDB, FastAPI, pandas/numpy, pytest, React 19, TypeScript, ECharts, Vitest, Testing Library.

---

### Task 1: Persist deletion markers and delete any zone

**Files:**
- Modify: `src/astock/storage/schema.sql`
- Modify: `src/astock/features/zones.py`
- Modify: `tests/storage/test_screening_schema.py`
- Modify: `tests/features/test_zones.py`

- [ ] **Step 1: Write failing schema and deletion tests**

Add `zone_deletion_markers` to the required-table assertion. Add feature tests that insert one automatic zone, call `delete_zone(connection, symbol, zone_id)`, assert the zone is gone, and assert the marker copied `symbol`, `timeframe`, `geometry`, `lower_price`, `center_price`, and `upper_price`. Add a mismatched-symbol test that returns `False` without inserting a marker.

```python
assert delete_zone(db.connection, "600001.SH", zone_id) is True
assert db.connection.execute(
    "select symbol, timeframe, geometry, center_price from zone_deletion_markers"
).fetchone() == ("600001.SH", "1d", "horizontal", 10.0)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/storage/test_screening_schema.py tests/features/test_zones.py -q`

Expected: FAIL because the table and `delete_zone` do not exist.

- [ ] **Step 3: Add the marker table and generic transactional delete**

Add an idempotent DuckDB table:

```sql
create table if not exists zone_deletion_markers (
  marker_id uuid primary key,
  symbol varchar not null,
  timeframe varchar not null,
  geometry varchar not null,
  lower_price double not null,
  center_price double not null,
  upper_price double not null,
  deleted_at timestamp not null default current_timestamp
);
```

Replace `delete_manual_zone` with `delete_zone(connection, symbol, zone_id)`. Read the owned row, begin a transaction, insert its marker, delete the exact owned row, and commit; roll back on exceptions.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest tests/storage/test_screening_schema.py tests/features/test_zones.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/storage/schema.sql src/astock/features/zones.py tests/storage/test_screening_schema.py tests/features/test_zones.py
git commit -m "feat: persist deleted price levels"
```

### Task 2: Mark regenerated deleted levels and expose generic deletion API

**Files:**
- Modify: `src/astock/features/zones.py`
- Modify: `src/astock/api/app.py`
- Modify: `tests/features/test_zones.py`
- Modify: `tests/api/test_screening_api.py`

- [ ] **Step 1: Write failing reappearance and API tests**

Add a marker whose range contains a current zone center, query `nearest_zones`, and assert `reappeared is True`; also assert a different geometry remains `False` and a role-converted line still matches. In the API test, delete both auto and manual zone ids through `/api/symbols/{symbol}/zones/{zone_id}` and assert 204; mismatched symbol returns 404.

```python
rows = nearest_zones(db.connection, "600001.SH", Timeframe.DAY, date(2026, 8, 20), 20)
assert rows[0]["reappeared"] is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/features/test_zones.py tests/api/test_screening_api.py -q`

Expected: FAIL because `reappeared` and the generic endpoint do not exist.

- [ ] **Step 3: Annotate current rows and replace the API endpoint**

Load markers for the requested symbol/timeframe once. For each selected current row, set `reappeared` when geometry matches and `lower_price <= center_price <= upper_price`; do this after dynamic support/resistance conversion. Replace the manual-only DELETE route with the generic route and call `delete_zone`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest tests/features/test_zones.py tests/api/test_screening_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/features/zones.py src/astock/api/app.py tests/features/test_zones.py tests/api/test_screening_api.py
git commit -m "feat: expose deleted level reappearance"
```

### Task 3: Always select daily trend support and resistance

**Files:**
- Modify: `src/astock/features/zones.py`
- Modify: `src/astock/features/builder.py`
- Modify: `tests/features/test_zones.py`
- Modify: `tests/features/test_builder.py`

- [ ] **Step 1: Write a failing daily candidate test**

Build deterministic bars where the last-five regression is rejected, call `detect_zones(..., timeframe=Timeframe.DAY)`, and assert exactly one trend support below the latest close and one trend resistance above it. Add a non-daily assertion showing strict behavior remains unchanged.

```python
trends = [zone for zone in zones if zone.geometry == "trend"]
assert {zone.zone_kind for zone in trends} == {"support", "resistance"}
assert next(z.center_price for z in trends if z.zone_kind == "support") < latest_close
assert next(z.center_price for z in trends if z.zone_kind == "resistance") > latest_close
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/features/test_zones.py tests/features/test_builder.py -q`

Expected: FAIL because the daily fixture has no trend pair and `detect_zones` has no timeframe parameter.

- [ ] **Step 3: Add bounded daily candidate selection**

Pass the timeframe from the feature builder into `detect_zones`. For `1d`, take the last 12 pivots and enumerate contiguous windows of length 2–5. Fit each window once and rank confirmed role-valid candidates by `(-touches, normalized_residual, -last_position, distance)`; if none are confirmed, rank all role-valid candidates by `(normalized_residual, -touches, -last_position, distance)`. If none are role-valid, shift the minimum-residual candidate to `latest_close ± tolerance` and return two synthetic line endpoints consistent with the shifted line. For non-daily timeframes, retain the current last-five strict branch.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest tests/features/test_zones.py tests/features/test_builder.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/features/zones.py src/astock/features/builder.py tests/features/test_zones.py tests/features/test_builder.py
git commit -m "feat: select daily trend boundaries"
```

### Task 4: Update chart line styles and deletion controls

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`
- Modify: `web/src/features/chart/chartOptions.ts`
- Modify: `web/src/features/chart/chartOptions.test.ts`
- Modify: `web/src/features/chart/ChartPage.tsx`
- Modify: `web/src/features/chart/ChartPage.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing chart and interaction tests**

Add required `reappeared: boolean` to fixture zones. Assert normal auto and manual lines are solid and `reappeared` lines are dashed. Render one auto and one manual line, assert both delete buttons exist, delete the auto line, and assert failure keeps a line visible while showing an alert.

```typescript
expect(zonePresentation({ ...autoZone, reappeared: false }).lineType).toBe("solid");
expect(zonePresentation({ ...autoZone, reappeared: true }).lineType).toBe("dashed");
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- --run src/features/chart/chartOptions.test.ts src/features/chart/ChartPage.test.tsx`

Expected: FAIL because line style still depends on source and automatic lines have no delete button.

- [ ] **Step 3: Implement generic client deletion and reappearance styling**

Rename the client method to `deleteZone`, call `/api/symbols/{symbol}/zones/{zoneId}`, and show a delete button for every card with accessible label `删除{自动|手动}{水平|趋势}{支撑|压力} {zone_id}`. Wrap deletion in `try/catch`; only remove local state after success. Make `zonePresentation` choose dashed only when `zone.reappeared`, and update the legend to “正常实线 / 删除后重现虚线”.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm test -- --run src/features/chart/chartOptions.test.ts src/features/chart/ChartPage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/api.ts web/src/features/chart web/src/styles.css
git commit -m "feat: delete and distinguish chart levels"
```

### Task 5: Documentation and complete verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update user-facing behavior notes**

Document that all ordinary lines are solid, deleted-and-regenerated levels are dashed, all cards can be deleted, and daily charts select one trend support and resistance when enough pivots exist.

- [ ] **Step 2: Run complete verification**

Run:

```bash
uv run pytest
uv run ruff check .
cd web && npm test -- --run && npm run build && npm run test:e2e
```

Expected: all commands exit 0.

- [ ] **Step 3: Verify the live application**

Restart or reload the integrated server on port 8888. Verify 600519.SH daily displays horizontal and trend support/resistance, ordinary lines are solid, every card has a delete button, and browser console logs contain no errors.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: explain deletable price levels"
```
