import { expect, test, type Page } from "@playwright/test";

async function hoverChartValue(page: Page, dataIndex: number, value: number) {
  const chartElement = page.getByRole("img", { name: "K 线与成交量图" });
  const box = await chartElement.boundingBox();
  if (!box) throw new Error("无法获取图表位置");
  const point = await chartElement.evaluate(async (element, coordinate) => {
    const moduleUrl = performance.getEntriesByType("resource")
      .map((entry) => entry.name)
      .find((name) => name.includes("/echarts_core.js"));
    if (!moduleUrl) throw new Error("无法找到 ECharts 浏览器模块");
    const echarts = await import(moduleUrl) as unknown as {
      getInstanceByDom: (target: HTMLElement) => {
        convertToPixel: (finder: { gridIndex: number }, value: [number, number]) => unknown;
      } | undefined;
    };
    const instance = echarts.getInstanceByDom(element);
    const pixel = instance?.convertToPixel({ gridIndex: 0 }, coordinate);
    if (!Array.isArray(pixel) || !Number.isFinite(Number(pixel[0])) || !Number.isFinite(Number(pixel[1]))) {
      throw new Error("无法换算 ECharts 数据坐标");
    }
    return [Number(pixel[0]), Number(pixel[1])] as const;
  }, [dataIndex, value] as [number, number]);
  await page.mouse.move(box.x + point[0], box.y + point[1]);
}

test("workbench and chart desk render without browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.route("**/api/catalog", async (route) => {
    await route.fulfill({ json: [{
      key: "return_20",
      label: "价格涨跌",
      unit: "percent",
      timeframes: ["5m", "15m", "30m", "60m", "1d", "1w", "1mo"],
      operators: ["gte", "lt"],
      group: "price",
      family: "price_change",
      period: 20,
      directions: [{ value: "rise", label: "上涨幅度" }, { value: "fall", label: "下跌幅度" }],
    }] });
  });

  await page.route("**/api/symbols/*/bars?*", async (route) => {
    const start = new Date("2026-05-01T15:00:00+08:00");
    const bars = Array.from({ length: 80 }, (_, index) => {
      const timestamp = new Date(start.getTime() + index * 86_400_000);
      const center = 1500 + index * 1.2 + Math.sin(index / 4) * 22;
      const open = center - Math.sin(index) * 8;
      const close = center + Math.cos(index) * 8;
      return {
        symbol: "600519.SH", timestamp: timestamp.toISOString(), timeframe: "1d",
        open, high: Math.max(open, close) + 12, low: Math.min(open, close) - 12, close,
        volume_shares: 2_000_000 + index * 15_000, amount_cny: center * 2_000_000,
        adjustment: "qfq", source: "e2e", is_final: true,
      };
    });
    await route.fulfill({ json: bars });
  });
  await page.route("**/api/symbols/*/zones?*", async (route) => {
    await route.fulfill({ json: [
      { zone_id: "auto-support", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "support", geometry: "horizontal", lower_price: 1510, center_price: 1518, upper_price: 1526, slope: null, intercept: null, anchors: "[]", strength: .8, touches: 4, source: "auto" },
      { zone_id: "manual-resistance", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "resistance", geometry: "horizontal", lower_price: 1590, center_price: 1598, upper_price: 1606, slope: null, intercept: null, anchors: "[]", strength: 1, touches: 2, source: "manual" },
      { zone_id: "auto-uptrend", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "uptrend", geometry: "trend", lower_price: 1490, center_price: 1545, upper_price: 1600, slope: 1.39, intercept: 1490, anchors: "[[\"2026-05-01\",1490],[\"2026-07-19\",1600]]", strength: .9, touches: 3, source: "auto" },
    ] });
  });
  await page.route("**/api/backtests/run", async (route) => {
    await route.fulfill({ json: {
      run_id: "backtest-e2e",
      result: {
        request: { symbols: ["600519.SH"] },
        metrics: { total_return: 18.42, annualized_return: 24.8, max_drawdown: 7.3, sharpe_ratio: 1.42, win_rate: 62.5, profit_loss_ratio: 1.9, trade_count: 8, total_fees: 326 },
        trades: [{ symbol: "600519.SH", side: "buy", signal_at: "2026-08-18T15:00:00+08:00", timestamp: "2026-08-19T09:30:00+08:00", quantity: 600, price: 1542, gross: 925200, commission: 277.56, tax: 0, transfer_fee: 9.25, reason: "entry condition matched" }],
        equity_curve: Array.from({ length: 60 }, (_, index) => ({ timestamp: new Date(2026, 5, index + 1).toISOString(), cash: 200000, market_value: 800000 + index * 3200 + Math.sin(index / 3) * 15000, equity: 1000000 + index * 3200 + Math.sin(index / 3) * 15000, drawdown: 0 })),
        rejected_orders: [],
      },
    } });
  });
  await page.route("**/api/monitor/tasks", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: { task_id: "task-new", ...(await route.request().postDataJSON()), created_at: "2026-08-20", updated_at: "2026-08-20" } });
      return;
    }
    await route.fulfill({ json: [{ task_id: "task-1", name: "贵州茅台突破", symbols: ["600519.SH"], comparator: "cross_above", threshold: 1600, cooldown_seconds: 300, scope: "watchlist", enabled: true, created_at: "2026-08-20", updated_at: "2026-08-20" }] });
  });
  await page.route("**/api/monitor/status", async (route) => route.fulfill({ json: { running: false, tasks: 1, enabled_tasks: 1, pending_notifications: 0, feishu_configured: true, watchlist_interval_seconds: 5, market_interval_seconds: 300 } }));
  await page.route("**/api/monitor/signals", async (route) => route.fulfill({ json: [{ signal_key: "signal-1", symbol: "600519.SH", price: 1602.5, threshold: 1600, comparator: "cross_above", triggered_at: "2026-08-20T10:08:05+08:00" }] }));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "选股工作台" })).toBeVisible();
  await expect(page.getByLabel("指标分类")).toHaveValue("price");
  await expect(page.getByLabel("指标", { exact: true })).toHaveValue("price_change:rise");
  await expect(page.getByLabel("指标", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/screener-workbench.png", fullPage: true });

  await page.getByRole("button", { name: "K 线研究" }).click();
  await expect(page.getByRole("heading", { name: "K 线研究" })).toBeVisible();
  await expect(page.getByRole("img", { name: "K 线与成交量图" })).toBeVisible();
  await expect(page.getByText("自动水平支撑")).toBeVisible();
  await expect(page.getByText("手动压力")).toBeVisible();
  await expect(page.getByText("自动上升趋势线")).toBeVisible();

  await hoverChartValue(page, 40, 1518);
  await expect(page.getByText("自动水平支撑 · 1518.00", { exact: true })).toBeVisible();

  const trendHoverIndex = 40.35;
  const trendHoverValue = 1490 + (1600 - 1490) / 79 * trendHoverIndex;
  await hoverChartValue(page, trendHoverIndex, trendHoverValue);
  await expect(page.getByText("自动上升趋势线 · 06-10 07:00 · 1545.70", { exact: true })).toBeVisible();

  await hoverChartValue(page, 20, 1500 + 20 * 1.2 + Math.sin(20 / 4) * 22 + Math.cos(20) * 8);
  await expect(page.getByText("K 线", { exact: true })).toBeVisible();
  await expect(page.getByText("成交量", { exact: true })).toBeVisible();
  await expect(page.getByText("自动水平支撑 · 1518.00", { exact: true })).toBeHidden();
  await expect(page.getByText("自动上升趋势线 · 06-10 07:00 · 1545.70", { exact: true })).toBeHidden();
  await page.screenshot({ path: "test-results/chart-desk.png", fullPage: true });

  await page.getByRole("button", { name: "策略回测" }).click();
  await expect(page.getByRole("heading", { name: "策略回测" })).toBeVisible();
  await page.getByRole("button", { name: "运行策略回测" }).click();
  await expect(page.getByText("18.42%")).toBeVisible();
  await page.screenshot({ path: "test-results/backtest-desk.png", fullPage: true });

  await page.getByRole("button", { name: "实时监控" }).click();
  await expect(page.getByRole("heading", { name: "实时监控" })).toBeVisible();
  await expect(page.getByText("贵州茅台突破")).toBeVisible();
  await expect(page.getByText("1602.5")).toBeVisible();
  await page.screenshot({ path: "test-results/monitor-desk.png", fullPage: true });

  expect(errors).toEqual([]);
});
