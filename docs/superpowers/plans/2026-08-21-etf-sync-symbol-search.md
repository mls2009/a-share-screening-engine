# ETF Sync and Symbol Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync listed Shanghai/Shenzhen ETFs through the existing market-data pipeline and let the K-line page find stocks and ETFs by six-digit code or fuzzy Chinese name.

**Architecture:** Extend the existing `Security`/`symbols` reference model with an instrument type and recognize ETFs at the BaoStock provider boundary. Add one local read-only symbol search endpoint, then consume it from a small autocomplete on the chart page; all selected symbols continue through the existing bars, zones, backtest, and monitoring APIs.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, DuckDB, React 19, TypeScript, Vitest, Testing Library.

---

### Task 1: Persist and sync ETF instruments

**Files:**
- Modify: `src/astock/domain/security.py`
- Modify: `src/astock/storage/schema.sql`
- Modify: `src/astock/data/providers/baostock.py`
- Modify: `src/astock/data/service.py`
- Test: `tests/data/providers/test_baostock.py`
- Test: `tests/data/test_service.py`
- Test: `tests/storage/test_screening_schema.py`

- [ ] **Step 1: Write failing provider, persistence, and migration tests**

Add a BaoStock fixture containing a normal stock, `sz.159558`, an exchange-traded LOF, and a bond. Assert that the stock and ETF remain, their `instrument_type` values are `stock` and `etf`, and unsupported instruments remain filtered. Assert `sync_universe()` stores the type, and an existing symbols table is migrated with existing rows defaulted to `stock`.

```python
assert [(item.symbol, item.instrument_type) for item in securities] == [
    ("600519.SH", "stock"),
    ("159558.SZ", "etf"),
]
assert database.connection.execute(
    "select instrument_type from symbols where symbol = '159558.SZ'"
).fetchone() == ("etf",)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest tests/data/providers/test_baostock.py tests/data/test_service.py tests/storage/test_screening_schema.py -q`

Expected: failures because `Security` and `symbols` do not have `instrument_type`, and BaoStock filters the ETF.

- [ ] **Step 3: Implement the minimal ETF model and provider recognition**

Add `instrument_type: Literal["stock", "etf"] = "stock"` to `Security`; add a non-null `instrument_type` column defaulting to `stock`; persist it in both symbol upserts. Add one `_instrument_type(provider_symbol, basic_type)` helper that returns `etf` only for recognized Shanghai/Shenzhen ETF code families, returns `stock` for BaoStock stock type, and returns `None` otherwise. Use it in `securities_on()`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `uv run pytest tests/data/providers/test_baostock.py tests/data/test_service.py tests/storage/test_screening_schema.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the data-layer change**

```bash
git add src/astock/domain/security.py src/astock/storage/schema.sql src/astock/data/providers/baostock.py src/astock/data/service.py tests/data/providers/test_baostock.py tests/data/test_service.py tests/storage/test_screening_schema.py
git commit -m "feat: sync listed ETFs"
```

### Task 2: Add local fuzzy symbol search API

**Files:**
- Modify: `src/astock/api/app.py`
- Test: `tests/api/test_screening_api.py`

- [ ] **Step 1: Write failing API tests**

Insert `159558.SZ` with a Chinese name and `instrument_type='etf'`. Test exact six-digit search, suffixed search, Chinese substring search, exclusion of delisted rows, and `limit`.

```python
response = client.get("/api/symbols/search", params={"q": "159558"})
assert response.json()[0] == {
    "symbol": "159558.SZ",
    "name": "创业板中盘ETF",
    "exchange": "SZ",
    "instrument_type": "etf",
}
```

- [ ] **Step 2: Run the API tests and verify RED**

Run: `uv run pytest tests/api/test_screening_api.py -q`

Expected: `/api/symbols/search` is captured by the dynamic bars route or returns 404 because no search route exists.

- [ ] **Step 3: Implement the search endpoint before dynamic symbol routes**

Normalize whitespace and uppercase Latin input. Return an empty list for a blank query. Query only `is_listed` rows and rank exact full symbol/code matches before symbol prefixes and name substring matches. Escape SQL wildcard characters so user input is treated literally, cap `limit` between 1 and 20, and return only the four documented fields.

- [ ] **Step 4: Run API tests and verify GREEN**

Run: `uv run pytest tests/api/test_screening_api.py -q`

Expected: all API tests pass.

- [ ] **Step 5: Commit the API change**

```bash
git add src/astock/api/app.py tests/api/test_screening_api.py
git commit -m "feat: search securities by code or name"
```

### Task 3: Add chart-page search suggestions

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`
- Modify: `web/src/api.test.ts`
- Modify: `web/src/features/chart/ChartPage.tsx`
- Modify: `web/src/features/chart/ChartPage.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing API and component tests**

Define a `SymbolSearchResult` fixture and extend the fake chart client with `searchSymbols`. Assert Chinese input displays the ETF candidate, selecting it loads bars with `159558.SZ`, direct six-digit submission resolves the exact candidate, and no match leaves the current chart unchanged with an alert.

```tsx
await userEvent.type(screen.getByLabelText("证券搜索"), "创业板")
await userEvent.click(await screen.findByRole("option", { name: /159558\.SZ/ }))
await waitFor(() => expect(requestedSymbols).toContain("159558.SZ"))
```

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `cd web && npm test -- src/api.test.ts src/features/chart/ChartPage.test.tsx`

Expected: type or assertion failures because search support is absent.

- [ ] **Step 3: Implement the API client and accessible autocomplete**

Add the result type and `api.searchSymbols(query)`. In `ChartPage`, debounce non-empty input, render an accessible listbox below the form, select complete symbols from candidates, and resolve form submission through the same API. Keep the currently open chart unchanged on search failure or no match. Style only the new search wrapper and dropdown, following existing colors and responsive rules.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run: `cd web && npm test -- src/api.test.ts src/features/chart/ChartPage.test.tsx`

Expected: all selected tests pass without warnings.

- [ ] **Step 5: Commit the frontend change**

```bash
git add web/src/types.ts web/src/api.ts web/src/api.test.ts web/src/features/chart/ChartPage.tsx web/src/features/chart/ChartPage.test.tsx web/src/styles.css
git commit -m "feat: search stocks and ETFs on charts"
```

### Task 4: End-to-end verification

**Files:**
- Modify only if an assertion exposes a requirement defect in files already listed above.

- [ ] **Step 1: Run all backend tests and lint**

Run: `uv run pytest -q && uv run ruff check .`

Expected: all tests and Ruff pass.

- [ ] **Step 2: Run all frontend tests and production build**

Run: `cd web && npm test && npm run build`

Expected: all tests pass and Vite completes the production build.

- [ ] **Step 3: Verify the running application contract**

After restarting the existing port-8888 service when needed, migrate the real local database, sync or seed an ETF reference entry without deleting existing data, verify `/api/symbols/search?q=159558`, and open the result on the K-line page. Do not claim real K-line availability unless the ETF history sync returns stored bars.

- [ ] **Step 4: Check the final diff**

Run: `git status --short --branch && git diff --check`

Expected: no uncommitted implementation changes and no whitespace errors.
