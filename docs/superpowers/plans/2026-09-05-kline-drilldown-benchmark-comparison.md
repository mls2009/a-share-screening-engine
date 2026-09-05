# K 线周期下钻与大盘走势对比 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 K 线研究页实现逐级小周期下钻、精确时段真实行情同步，以及自动匹配大盘的累计涨跌幅双折线对比。

**Architecture:** 前端由纯函数管理下钻窗口，`StockChart` 只上报被点击的蜡烛，`ChartPage` 管理路径与模式；对比图使用独立 ECharts 配置。后端新增集中式 benchmark 服务，负责板块映射、指数同步、时间对齐和收益归一化，AKShare 只承担指数基础日线和 5 分钟数据适配。

**Tech Stack:** Python 3.12、FastAPI、DuckDB、Parquet、Pydantic、AKShare、React 19、TypeScript、ECharts 6、Vitest、Testing Library、Playwright

---

## 文件结构

- Create `src/astock/features/benchmark.py`：指数映射、对比计算、图表定向同步和业务错误。
- Modify `src/astock/data/providers/akshare.py`：规范化指数日线和 5 分钟行情。
- Modify `src/astock/api/dependencies.py`：把 benchmark 服务注入 API 上下文。
- Modify `src/astock/api/app.py`：暴露对比与定向同步接口，并在默认应用中组装服务。
- Create `tests/features/test_benchmark.py`：映射、对齐、归一化和同步测试。
- Modify `tests/data/providers/test_akshare.py`：指数适配器契约测试。
- Modify `tests/api/test_screening_api.py`：新增 HTTP 接口契约测试。
- Create `web/src/features/chart/drilldown.ts`：可下钻周期和父 K 时间窗口纯函数。
- Create `web/src/features/chart/drilldown.test.ts`：下钻规则测试。
- Modify `web/src/features/chart/StockChart.tsx`：上报蜡烛点击并与画线互斥。
- Modify `web/src/features/chart/StockChart.test.tsx`：图表事件测试。
- Create `web/src/features/chart/benchmarkOptions.ts`：双折线比较配置。
- Create `web/src/features/chart/benchmarkOptions.test.ts`：坐标轴、系列和 tooltip 测试。
- Create `web/src/features/chart/BenchmarkChart.tsx`：比较图生命周期和响应式尺寸。
- Modify `web/src/types.ts`、`web/src/api.ts`、`web/src/api.test.ts`：对比与同步 API 类型。
- Modify `web/src/features/chart/ChartPage.tsx`、`ChartPage.test.tsx`：下钻路径、周期菜单、对比模式和同步交互。
- Modify `web/src/styles.css`：桌面浮层、手机底部面板、路径、对比图和缺失提示。
- Modify `web/e2e/workbench.spec.ts`：桌面和手机端完整流程。

### Task 1: 下钻周期与时间窗口纯函数

**Files:**
- Create: `web/src/features/chart/drilldown.ts`
- Create: `web/src/features/chart/drilldown.test.ts`

- [ ] **Step 1: 写失败测试**

测试全部周期的候选列表，并断言日、周、月和分钟父 K 生成正确窗口：

```ts
expect(drilldownTimeframes("1d")).toEqual(["60m", "30m", "15m", "5m"]);
expect(drillWindow(dailyBar, "1d", "15m")).toMatchObject({
  timeframe: "15m", start: "2026-08-20", end: "2026-08-20",
});
expect(drillWindow(minuteBar, "60m", "15m")).toMatchObject({
  startAt: "2026-08-20T09:30:00+08:00",
  endAt: "2026-08-20T10:30:00+08:00",
});
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `cd web && npm test -- --run src/features/chart/drilldown.test.ts`

Expected: FAIL，因为 `drilldown.ts` 尚不存在。

- [ ] **Step 3: 最小实现**

定义：

```ts
export interface ChartWindow {
  timeframe: Timeframe;
  start: string;
  end: string;
  startAt?: string;
  endAt?: string;
  label: string;
}

export function drilldownTimeframes(timeframe: Timeframe): Timeframe[];
export function drillWindow(bar: Bar, parent: Timeframe, target: Timeframe): ChartWindow;
export function filterWindowBars(bars: Bar[], window: ChartWindow): Bar[];
```

月线按自然月、周线按周一至周五、日线按当天；分钟父 K 以时间戳为右边界并减去父周期分钟数，过滤采用 `timestamp > startAt && timestamp <= endAt`。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `cd web && npm test -- --run src/features/chart/drilldown.test.ts`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add web/src/features/chart/drilldown.ts web/src/features/chart/drilldown.test.ts
git commit -m "feat: define chart drilldown windows"
```

### Task 2: 蜡烛点击事件与画线互斥

**Files:**
- Modify: `web/src/features/chart/StockChart.tsx`
- Modify: `web/src/features/chart/StockChart.test.tsx`

- [ ] **Step 1: 写失败测试**

给 `StockChartProps` 增加 `onBarSelect?: (bar: Bar) => void`，模拟 ECharts 点击：

```ts
act(() => chartHandlers.get("click")?.({ seriesType: "candlestick", dataIndex: 1 }));
expect(onBarSelect).toHaveBeenCalledWith(bars[1]);
```

另测 `drawing=true` 时不调用 `onBarSelect`，ZRender 点击仍调用 `onAnchor`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `cd web && npm test -- --run src/features/chart/StockChart.test.tsx`

Expected: FAIL，因为属性和 click handler 尚未实现。

- [ ] **Step 3: 最小实现**

保存最新 callback ref，注册 ECharts `click` 事件，只接受：

```ts
if (!drawing && params.seriesType === "candlestick" && Number.isInteger(params.dataIndex)) {
  const bar = bars[params.dataIndex];
  if (bar) barSelectCallback.current?.(bar);
}
```

卸载时移除同一 handler。保留现有 ZRender 锚点逻辑。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `cd web && npm test -- --run src/features/chart/StockChart.test.tsx`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add web/src/features/chart/StockChart.tsx web/src/features/chart/StockChart.test.tsx
git commit -m "feat: emit candlestick selections"
```

### Task 3: 指数行情适配器

**Files:**
- Modify: `src/astock/data/providers/akshare.py`
- Modify: `tests/data/providers/test_akshare.py`

- [ ] **Step 1: 写失败测试**

用 `SimpleNamespace` 模拟 AKShare：

```python
daily = provider.index_history(
    "000001.SH", Timeframe.DAY, date(2026, 8, 1), date(2026, 8, 20)
)
minute = provider.index_history(
    "399006.SZ", Timeframe.MIN_5, date(2026, 8, 20), date(2026, 8, 20)
)
assert daily[0].adjustment == Adjustment.NONE
assert minute[0].volume_shares == 12_300 * 100
```

断言日线调用 `stock_zh_index_daily_em(symbol="sh000001", start_date="20260801", end_date="20260820")`，分钟调用 `index_zh_a_hist_min_em(symbol="399006", period="5", start_date="2026-08-20 00:00:00", end_date="2026-08-20 23:59:59")`，其他基础周期抛出 `ValueError`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/data/providers/test_akshare.py -q`

Expected: FAIL，`index_history` 不存在。

- [ ] **Step 3: 最小实现**

新增：

```python
def index_history(
    self, symbol: str, timeframe: Timeframe, start: date, end: date
) -> list[Bar]:
```

日线字段映射 `date/open/high/low/close/volume/amount`；分钟字段映射 `时间/开盘/最高/最低/收盘/成交量/成交额`。分钟成交量从“手”乘以 100 转为股，指数 `adjustment=Adjustment.NONE`，只接受 `DAY` 和 `MIN_5`。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `uv run pytest tests/data/providers/test_akshare.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/astock/data/providers/akshare.py tests/data/providers/test_akshare.py
git commit -m "feat: load benchmark index bars"
```

### Task 4: Benchmark 业务服务

**Files:**
- Create: `src/astock/features/benchmark.py`
- Create: `tests/features/test_benchmark.py`

- [ ] **Step 1: 写失败测试**

覆盖映射：

```python
assert service.benchmark_for("600001.SH").symbol == "000001.SH"
assert service.benchmark_for("300001.SZ").symbol == "399006.SZ"
assert service.benchmark_for("688001.SH").symbol == "000688.SH"
assert service.benchmark_for("920001.BJ").symbol == "899050.BJ"
assert service.benchmark_for("159558.SZ").symbol == "399001.SZ"
```

向 BarStore 写入股票前复权和指数不复权数据，断言共有点归一化：

```python
result = service.compare("600001.SH", Timeframe.DAY, start, end)
assert result.points[0].stock_return_pct == 0
assert result.points[1].stock_return_pct == 10
assert result.points[1].benchmark_return_pct == 5
assert result.points[1].relative_pct == 5
```

覆盖股票缺失、指数缺失和没有共有时间点的不同错误代码。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/features/test_benchmark.py -q`

Expected: FAIL，因为 benchmark 模块尚不存在。

- [ ] **Step 3: 实现映射、对齐和同步**

定义冻结模型 `BenchmarkDefinition`、`ComparisonPoint`、`BenchmarkComparison`。`BenchmarkDataError` 接收 `code` 和 `message` 并保存错误码。`BenchmarkService` 对外暴露三个明确方法：`benchmark_for(symbol)` 返回 `BenchmarkDefinition`；`compare(symbol, timeframe, start, end, start_at=None, end_at=None)` 返回 `BenchmarkComparison`；`sync(symbol, timeframe, start, end, include_benchmark)` 返回分别写入的股票和指数 bar 数量。

`compare()` 读取股票 `QFQ` 与指数 `NONE` 的基础周期，派生目标周期，过滤精确时间并按时间戳交集计算百分比。`sync()` 用股票 MarketDataService 同步股票基础周期，用 AKShare `index_history()` 同步指数基础周期并 upsert。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `uv run pytest tests/features/test_benchmark.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/astock/features/benchmark.py tests/features/test_benchmark.py
git commit -m "feat: compare stocks with market benchmarks"
```

### Task 5: HTTP 对比与定向同步接口

**Files:**
- Modify: `src/astock/api/dependencies.py`
- Modify: `src/astock/api/app.py`
- Modify: `tests/api/test_screening_api.py`

- [ ] **Step 1: 写失败接口测试**

在 `_client` 注入 benchmark 服务并写入指数 bars，然后断言：

```python
response = client.get(
    "/api/symbols/600001.SH/benchmark-comparison",
    params={"timeframe": "1d", "start": "2026-08-19", "end": "2026-08-20"},
)
assert response.status_code == 200
assert response.json()["benchmark_symbol"] == "000001.SH"
assert response.json()["points"][0]["stock_return_pct"] == 0
```

再用 fake service 断言 POST `/api/symbols/600001.SH/chart-data/sync` 正确传递周期、日期和 `include_benchmark`，业务错误返回结构化 `code/message`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/api/test_screening_api.py -q`

Expected: FAIL，两个路由均为 404。

- [ ] **Step 3: 实现上下文与路由**

给 `ApiContext` 增加可选 `benchmark: BenchmarkService | None = None`。定义：

```python
class ChartDataSyncRequest(BaseModel):
    timeframe: Timeframe
    start: date
    end: date
    include_benchmark: bool = False
```

GET 调用 `compare()`；POST 调用 `sync()`。捕获 `BenchmarkDataError`，使用 404 表示证券不存在、409 表示数据缺失或无法对齐、422 表示分钟历史不可用。默认应用复用现有 `market_data`，并注入独立 `AkShareProvider` 作为指数源。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `uv run pytest tests/api/test_screening_api.py tests/features/test_benchmark.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/astock/api/dependencies.py src/astock/api/app.py tests/api/test_screening_api.py
git commit -m "feat: expose benchmark chart APIs"
```

### Task 6: 前端 API、类型与比较图

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`
- Modify: `web/src/api.test.ts`
- Create: `web/src/features/chart/benchmarkOptions.ts`
- Create: `web/src/features/chart/benchmarkOptions.test.ts`
- Create: `web/src/features/chart/BenchmarkChart.tsx`

- [ ] **Step 1: 写失败测试**

断言 API URL 含周期、日期和精确时间，POST body 含同步范围。比较图断言两个 line series、百分比轴和 relative tooltip：

```ts
const option = buildBenchmarkOption(comparison);
expect(option.series).toMatchObject([
  { name: "股票一", type: "line" },
  { name: "上证指数", type: "line" },
]);
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `cd web && npm test -- --run src/api.test.ts src/features/chart/benchmarkOptions.test.ts`

Expected: FAIL，因为 API 和 option builder 尚不存在。

- [ ] **Step 3: 最小实现**

新增 `BenchmarkComparisonPoint`、`BenchmarkComparison` 类型；API 增加：

```ts
benchmarkComparison(symbol, timeframe, start, end, startAt?, endAt?)
syncChartData(symbol, payload)
```

`BenchmarkChart` 初始化 ECharts，使用 ResizeObserver 和 window resize，容器 role 为 `img`、名称为“大盘走势对比图”。option 使用统一百分比轴，股票绿色、大盘蓝色，tooltip 展示三项百分比。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `cd web && npm test -- --run src/api.test.ts src/features/chart/benchmarkOptions.test.ts`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add web/src/types.ts web/src/api.ts web/src/api.test.ts web/src/features/chart/benchmarkOptions.ts web/src/features/chart/benchmarkOptions.test.ts web/src/features/chart/BenchmarkChart.tsx
git commit -m "feat: add benchmark comparison chart"
```

### Task 7: K 线页整合下钻、对比和同步

**Files:**
- Modify: `web/src/features/chart/ChartPage.tsx`
- Modify: `web/src/features/chart/ChartPage.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: 写失败组件测试**

扩展 FakeChart 以触发 `onBarSelect`，覆盖：

```ts
await userEvent.click(screen.getByRole("button", { name: "选择 2026-08-20 K线" }));
await userEvent.click(screen.getByRole("button", { name: "查看15分钟" }));
expect(client.bars).toHaveBeenLastCalledWith("600001.SH", "15m", "2026-08-20", "2026-08-20");
expect(screen.getByRole("button", { name: "返回日线" })).toBeVisible();
```

再测开启“大盘对比”时调用 comparison API、显示比较图并隐藏画线工具；关闭后原指标仍存在。空 bars 显示同步按钮，点击后调用 `syncChartData` 并重载。

- [ ] **Step 2: 运行测试确认 RED**

Run: `cd web && npm test -- --run src/features/chart/ChartPage.test.tsx`

Expected: FAIL，因为页面尚无对应控件。

- [ ] **Step 3: 最小页面实现**

`ChartClient` 增加对比和同步方法。状态包括：

```ts
const [drillStack, setDrillStack] = useState<ChartWindow[]>([]);
const [selectedBar, setSelectedBar] = useState<Bar | null>(null);
const [benchmarkEnabled, setBenchmarkEnabled] = useState(false);
const [comparison, setComparison] = useState<BenchmarkComparison | null>(null);
const [syncing, setSyncing] = useState(false);
```

普通周期切换和证券切换清空 stack；返回按钮 pop 一层。当前 window 驱动 bars、indicators、zones 和 comparison 请求。对比模式渲染 `BenchmarkChart`，普通模式渲染 `StockChart`。没有 bars 或 comparison 时显示精确同步按钮。

CSS 增加 `.drilldown-menu`、`.drill-breadcrumb`、`.benchmark-toggle`、`.chart-data-empty`；760px 以下菜单使用 fixed bottom sheet 并预留 safe area，按钮最小 44px；全屏状态确保浮层 z-index 位于 chart desk 内。

- [ ] **Step 4: 运行组件测试确认 GREEN**

Run: `cd web && npm test -- --run src/features/chart/ChartPage.test.tsx src/features/chart/StockChart.test.tsx src/features/chart/drilldown.test.ts`

Expected: PASS。

- [ ] **Step 5: 运行前端构建**

Run: `cd web && npm run build`

Expected: TypeScript 和 Vite build 均成功。

- [ ] **Step 6: 提交**

```bash
git add web/src/features/chart/ChartPage.tsx web/src/features/chart/ChartPage.test.tsx web/src/styles.css
git commit -m "feat: add interactive chart drilldown"
```

### Task 8: 浏览器验收、全量验证与部署

**Files:**
- Modify: `web/e2e/workbench.spec.ts`

- [ ] **Step 1: 写浏览器流程**

mock 日线、15分钟和 benchmark API。点击日 K，选择 15分钟，断言路径、请求范围和返回按钮；开启比较后断言两条曲线图出现；分别在 390×844 和 844×390 全屏尺寸断言无页面溢出。

- [ ] **Step 2: 运行 E2E**

Run: `cd web && npm run test:e2e`

Expected: 所有 Playwright 用例通过。

- [ ] **Step 3: 全量验证**

Run: `uv run pytest -q && uv run ruff check .`

Expected: 后端全部通过且 Ruff 无问题。

Run: `cd web && npm test && npm run build && npm run test:e2e`

Expected: 前端单元测试、生产构建和 E2E 全部通过。

- [ ] **Step 4: 提交 E2E**

```bash
git add web/e2e/workbench.spec.ts
git commit -m "test: cover chart drilldown and benchmark comparison"
```

- [ ] **Step 5: 合并、更新服务和推送**

将 `codex/kline-drilldown-benchmark` 快进合并到 `main`，在 main 上复验。再把常驻服务工作树快进到 main、构建 `web/dist`，执行 `launchctl kickstart -k gui/501/com.astock.local8888`，用 390px 与横屏浏览器访问 Tailscale 地址核验后推送 GitHub。
