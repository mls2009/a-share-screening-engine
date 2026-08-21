# Remove Automatic Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop generating and returning automatic trend lines, delete stored automatic trend lines, and preserve manual trends plus automatic horizontal support/resistance.

**Architecture:** Remove automatic trend production at the detector boundary, filter legacy automatic trends at the chart-query boundary, and add an idempotent storage cleanup during migration. Existing manual trend creation and rendering remain unchanged.

**Tech Stack:** Python 3.12, pandas, DuckDB, pytest, FastAPI, React/TypeScript.

---

### Task 1: Stop automatic trend detection

**Files:**
- Modify: `tests/features/test_zones.py`
- Modify: `src/astock/features/zones.py`

- [ ] **Step 1: Replace automatic trend expectations with a failing detector test**

```python
def test_detect_zones_only_returns_automatic_horizontal_zones() -> None:
    zones = detect_zones(frame, as_of=date(2026, 1, 20), pivot_order=1)
    assert zones
    assert {zone.geometry for zone in zones} == {"horizontal"}
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest tests/features/test_zones.py -q`
Expected: FAIL because `detect_zones()` still returns `geometry == "trend"`.

- [ ] **Step 3: Remove the directional trend call and its private helpers**

Delete `_fit_trend()`, `_directional_trend_zones()`, and the `zones.extend(_directional_trend_zones(...))` block. Keep horizontal clustering and `PriceZone` manual-trend support unchanged.

- [ ] **Step 4: Run the focused feature tests**

Run: `uv run pytest tests/features/test_zones.py -q`
Expected: PASS after updating obsolete automatic-trend assertions to the new contract.

### Task 2: Hide legacy automatic trends and preserve manual trends

**Files:**
- Modify: `tests/features/test_zones.py`
- Modify: `tests/api/test_screening_api.py`
- Modify: `src/astock/features/zones.py`

- [ ] **Step 1: Add a failing chart-query test**

```python
def test_chart_zones_excludes_auto_trends_but_keeps_manual_trends(tmp_path: Path) -> None:
    rows = chart_zones(db.connection, "600001.SH", Timeframe.DAY, as_of)
    assert not [row for row in rows if row["source"] == "auto" and row["geometry"] == "trend"]
    assert [row for row in rows if row["source"] == "manual" and row["geometry"] == "trend"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/features/test_zones.py -q`
Expected: FAIL because `chart_zones()` still selects one automatic uptrend and downtrend.

- [ ] **Step 3: Remove automatic trend selection from `chart_zones()`**

Keep this selection only:

```python
selected = [row for row in rows if row["source"] == "manual"]
if close is not None:
    selected.extend(_nearest_horizontal_zones(rows, close, limit_each, source="auto"))
return selected
```

- [ ] **Step 4: Update API expectations and run focused tests**

Run: `uv run pytest tests/features/test_zones.py tests/api/test_screening_api.py -q`
Expected: PASS; API responses contain automatic horizontal lines and manual lines only.

### Task 3: Delete stored automatic trend lines during migration

**Files:**
- Modify: `tests/storage/test_screening_schema.py`
- Modify: `src/astock/storage/schema.sql`

- [ ] **Step 1: Add a failing migration cleanup test**

Insert one automatic trend, one manual trend, and one automatic horizontal line, run `db.migrate()`, then assert:

```python
assert db.connection.execute(
    "select source, geometry from support_resistance_zones order by source, geometry"
).fetchall() == [("auto", "horizontal"), ("manual", "trend")]
```

- [ ] **Step 2: Run the migration test and verify it fails**

Run: `uv run pytest tests/storage/test_screening_schema.py -q`
Expected: FAIL because the automatic trend row remains.

- [ ] **Step 3: Add the idempotent cleanup after the zone table exists**

```sql
delete from support_resistance_zones
where source = 'auto' and geometry = 'trend';
```

- [ ] **Step 4: Run migration and feature tests**

Run: `uv run pytest tests/storage/test_screening_schema.py tests/features/test_zones.py -q`
Expected: PASS and manual trends remain.

### Task 4: Documentation, full verification, and live cleanup

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Remove README claims about automatic directional trends**

Document that automatic lines are horizontal support/resistance only and manual horizontal/trend drawing remains available.

- [ ] **Step 2: Run full verification**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all Python tests pass and Ruff reports no errors.

Run: `cd web && npm test && npm run build && npm run test:e2e`
Expected: all frontend tests, production build, and browser test pass.

- [ ] **Step 3: Restart port 8888 and execute the real migration**

Restart `uvicorn astock.api.app:create_default_app --factory --host 127.0.0.1 --port 8888`. Startup migration must remove existing automatic trends from the real DuckDB database.

- [ ] **Step 4: Verify the live page**

Open K 线研究 for `600519.SH` on daily, weekly, and 15-minute periods. Confirm there are no automatic uptrend/downtrend rows or chart lines, while horizontal lines and the manual trend drawing control remain.
