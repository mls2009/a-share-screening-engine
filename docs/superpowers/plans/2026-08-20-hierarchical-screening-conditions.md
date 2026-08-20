# Hierarchical Screening Conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立分类驱动的条件选择，严格区分涨跌/量增减，并支持板块、上市阶段和 K 线形态多选。

**Architecture:** 后端指标目录提供分类、指标族、周期、方向及枚举值元数据；评估器增加 `in/not_in`。前端条件树使用级联选择和多选面板，并在序列化时把下跌/缩量的正数幅度转为带符号底层条件。

**Tech Stack:** Python 3.12, FastAPI, Pydantic, DuckDB, React 19, TypeScript, Vitest, Testing Library.

---

### Task 1: 扩展指标目录契约

**Files:**
- Modify: `src/astock/screening/catalog.py`
- Modify: `src/astock/api/app.py`
- Test: `tests/api/test_screening_api.py`

- [ ] **Step 1: Write the failing catalog contract test**

断言 `return_20` 包含 `group="price"`、`family="price_change"`、`period=20` 及 `directions=["rise", "fall"]`，`board` 包含四个中文选项并开启多选，`pattern_type` 返回全部形态选项。

- [ ] **Step 2: Run the focused API test and verify RED**

Run: `uv run pytest tests/api/test_screening_api.py::test_catalog_exposes_hierarchical_filter_metadata -q`

Expected: FAIL because catalog items have no presentation metadata.

- [ ] **Step 3: Add immutable catalog metadata**

Add `group`, `family`, `period`, `directions`, `choices`, and `multiple` fields to `MetricSpec`; populate every metric family and serialize them from `_catalog()` without changing the underlying metric key.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `uv run pytest tests/api/test_screening_api.py::test_catalog_exposes_hierarchical_filter_metadata -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/screening/catalog.py src/astock/api/app.py tests/api/test_screening_api.py
git commit -m "feat: describe hierarchical screening metrics"
```

### Task 2: 实现枚举多选语义

**Files:**
- Modify: `src/astock/screening/models.py`
- Modify: `src/astock/screening/evaluator.py`
- Modify: `src/astock/screening/validation.py`
- Modify: `src/astock/features/store.py`
- Test: `tests/screening/test_evaluator.py`
- Test: `tests/screening/test_validation.py`
- Test: `tests/features/test_store.py`

- [ ] **Step 1: Write failing membership and listing-stage tests**

Test `board in [main, chinext]`, `pattern_type not_in [...]`, invalid empty/string membership operands, and dynamic mapping of listing days 30/31/250/251 to `new/secondary_new/established`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/screening/test_evaluator.py tests/screening/test_validation.py tests/features/test_store.py -q`

Expected: FAIL because `in/not_in`, string arrays, and `listing_stage` do not exist.

- [ ] **Step 3: Implement minimal backend support**

Add `IN` and `NOT_IN` operators, allow `ConstantOperand.value` to hold `list[str]`, implement membership comparison and validation, derive `listing_stage` in `MarketFeatureStore._decode`, and register it as a category metric limited to screening timeframes.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/screening/test_evaluator.py tests/screening/test_validation.py tests/features/test_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/screening tests/screening src/astock/features/store.py tests/features/test_store.py
git commit -m "feat: evaluate multi-select screening values"
```

### Task 3: 转换方向幅度和多选条件

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/features/screener/treeModel.ts`
- Test: `web/src/features/screener/treeModel.test.ts`

- [ ] **Step 1: Write failing serialization tests**

断言“20 周期下跌幅度 ≥ 30”转换为 `return_20 lte -30`，“下跌幅度介于 10,30”转换为 `between [-30,-10]`，多选板块转换为 `in` 和字符串数组。

- [ ] **Step 2: Run test and verify RED**

Run: `cd web && npm test -- src/features/screener/treeModel.test.ts`

Expected: FAIL because UI nodes have no direction or selected values.

- [ ] **Step 3: Implement minimal transformations**

Extend `UiConditionNode` with `direction?: "rise" | "fall"` and `selectedValues?: string[]`; add operator/value inversion for `fall` and serialize category selections using `in/not_in`.

- [ ] **Step 4: Run test and verify GREEN**

Run: `cd web && npm test -- src/features/screener/treeModel.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/features/screener/treeModel.ts web/src/features/screener/treeModel.test.ts
git commit -m "feat: serialize directional and multi-select filters"
```

### Task 4: 建立级联条件选择器

**Files:**
- Modify: `web/src/features/screener/ConditionTree.tsx`
- Modify: `web/src/features/screener/ConditionTree.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing interaction tests**

覆盖分类切换、上涨/下跌不出现原始“涨跌幅”、周期切换、板块多选、K 线形态多选、ST/停牌业务文案，以及切换指标保留可兼容周期。

- [ ] **Step 2: Run component tests and verify RED**

Run: `cd web && npm test -- src/features/screener/ConditionTree.test.tsx`

Expected: FAIL because only a flat metric select exists.

- [ ] **Step 3: Implement the cascading selector**

Render category, business condition, optional calculation period, operators, and a checkbox multi-select panel. Preserve the existing industrial research-desk visual language, use compact path labels and clear selected-count summaries, and keep keyboard-accessible labels.

- [ ] **Step 4: Run component tests and verify GREEN**

Run: `cd web && npm test -- src/features/screener/ConditionTree.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/screener/ConditionTree.tsx web/src/features/screener/ConditionTree.test.tsx web/src/styles.css
git commit -m "feat: add hierarchical screening condition picker"
```

### Task 5: 集成验收

**Files:**
- Modify: `web/src/features/screener/ScreenerPage.test.tsx`
- Modify: `web/e2e/workbench.spec.ts`
- Modify: `README.md`

- [ ] **Step 1: Add an end-to-end payload assertion**

在页面测试中选择“价格行情 → 下跌幅度 → 20 周期 → 至少 30%”，断言提交的底层条件为 `return_20 <= -30`。

- [ ] **Step 2: Verify RED, then update integration fixtures and documentation**

Run: `cd web && npm test -- src/features/screener/ScreenerPage.test.tsx`

Expected: FAIL until fixtures contain the new catalog metadata and interaction.

- [ ] **Step 3: Run full verification**

```bash
uv run pytest -q
uv run ruff check .
cd web && npm test && npm run build && npm run test:e2e
```

Expected: all commands exit 0 with no test failures.

- [ ] **Step 4: Verify the running page on port 8888**

Open the screener, exercise directional and multi-select conditions, confirm the browser console has no errors, and avoid running a destructive or unexpectedly broad live screen.

- [ ] **Step 5: Commit**

```bash
git add README.md web/src/features/screener/ScreenerPage.test.tsx web/e2e/workbench.spec.ts
git commit -m "docs: explain hierarchical screening filters"
```
