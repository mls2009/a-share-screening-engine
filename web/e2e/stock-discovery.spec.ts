import { expect, test } from "@playwright/test";
test("market search, group addition, valuation details and group filtering", async ({ page }) => {
  const stock = { symbol: "600519.SH", name: "贵州茅台", exchange: "SH", instrument_type: "stock" };
  const group = { id: "cc3062af-7bcc-432e-abd4-5d7baed2187d", name: "长期观察" };
  let added = false;
  let payload: Record<string, unknown> | undefined;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/market-updates") { await route.fulfill({ contentType: "text/event-stream", body: "event: ready\ndata: 0\n\n" }); return; }
    let json: unknown = [];
    if (path === "/api/watchlist") {
      if (route.request().method() === "POST") { expect(route.request().postDataJSON()).toMatchObject({ symbol: stock.symbol, group_id: group.id }); added = true; json = { ...stock, sources: [] }; }
      else json = added ? [{ ...stock, sources: [], groups: [group], quote: { date: "2026-09-08", close: 12, change_percent: 2 } }] : [];
    } else if (path === "/api/watchlist/groups") json = [group];
    else if (path === "/api/symbols/search") json = [stock];
    else if (path === "/api/catalog") json = [{ key: "pe_ratio", label: "市盈率（腾讯）", unit: "ratio", group: "attributes", timeframes: ["1d"], operators: ["gt", "lt"], supported_modes: ["live"] }];
    else if (path.endsWith("/overview")) json = { ...stock, board: "main", listed_on: "2001-08-27", message: null, valuation_note: "腾讯公布的 PE 原值，缺失值不按零处理。", quote: { timestamp: "2026-09-08T15:00:00+08:00", price: 12, previous_close: 11, source: "tencent", pe_ratio: 18.2, pb_ratio: 2.4, total_market_cap: 1200000000, float_market_cap: 800000000, turnover_rate: 2.1, volume_ratio: 1.2, volume_shares: 100000, amount_cny: 1200000 } };
    else if (path === "/api/screens/run") { payload = route.request().postDataJSON(); json = { run_id: "r1", status: "completed", match_count: 1, universe_size: 1, realtime_covered: 1, failed_batches: 0, matches: [{ symbol: stock.symbol }], diagnostics: { warnings: [], conditions: {}, data_dates: {} } }; }
    await route.fulfill({ json });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "自选股", exact: false }).click();
  await page.getByLabel("全市场股票搜索").fill("600519");
  await expect(page.locator(".watch-market-results").getByText("贵州茅台")).toBeVisible();
  await page.getByLabel("搜索添加目标分组").selectOption(group.id);
  await page.getByRole("button", { name: "加入自选", exact: true }).click();
  await expect(page.locator(".watchlist-page table").getByText("贵州茅台")).toBeVisible();
  await page.getByRole("button", { name: "长期观察 1", exact: true }).click();
  await page.getByText("按条件筛选当前自选分组", { exact: true }).click();
  await page.getByRole("button", { name: "筛选当前分组", exact: true }).click();
  await expect(page.getByText(/符合条件 1 只/)).toBeVisible();
  expect(payload).toMatchObject({ scope: "watchlist", watch_group_id: group.id, mode: "live" });
  expect(JSON.stringify(payload?.tree)).toContain("pe_ratio");
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  const overview = page.getByRole("region", { name: "股票行情与估值" });
  await expect(overview.getByText("18.2 倍")).toBeVisible();
  await expect(overview.getByText("12 亿")).toBeVisible();
  await expect(overview.getByRole("button", { name: "刷新行情" })).toHaveCSS("background-color", "rgb(27, 37, 40)");
  await page.screenshot({ path: "/tmp/stock-overview-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(overview.getByText("18.2 倍")).toBeVisible();
  await page.screenshot({ path: "/tmp/stock-overview-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
