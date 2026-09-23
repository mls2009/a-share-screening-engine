import { expect, test } from "@playwright/test";

test("screen results target a group and that group supplies independent backtests", async ({ page }) => {
  const members: Array<{ symbol: string; name: string; sources: unknown[]; groups: Array<{ id: string; name: string }> }> = [];
  const requests: string[][] = [];
  const matches = ["600001.SH", "600002.SH"].map((symbol, index) => ({ symbol, rank: index + 1, features: { name: `股票${index + 1}`, close: 12, return_20: 35 }, explanation: { result: "true", children: [] } }));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path === "/api/catalog") json = [{ key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte"], group: "price", supported_modes: ["backtest", "close"], period: 20 }];
    if (path === "/api/screens/validate") json = { valid: true, errors: [] };
    if (path === "/api/watchlist/groups") json = [{ id: "g1", name: "芯片观察" }];
    if (path === "/api/watchlist") json = members;
    if (path === "/api/screens/run") json = { run_id: "r1", status: "completed", universe_size: 2, realtime_covered: 0, failed_batches: 0, match_count: 2, matches, diagnostics: { conditions: {}, warnings: [], data_dates: {} } };
    if (path === "/api/workbench/runs/r1/watchlist") {
      const payload = route.request().postDataJSON();
      expect(payload.group_id).toBe("g1"); expect(payload.all_matches).toBe(true);
      members.push(...matches.map(match => ({ symbol: match.symbol, name: match.features.name, sources: [], groups: [{ id: "g1", name: "芯片观察" }] })));
      json = { added: 2 };
    }
    if (path === "/api/backtests/run") {
      const payload = route.request().postDataJSON(); requests.push(payload.symbols);
      expect(payload.entry_tree.children[0].right.value).toBe(45);
      json = { run_id: `b${requests.length}`, result: { request: payload, metrics: { total_return: 1, annualized_return: 1, max_drawdown: 1, sharpe_ratio: 1, win_rate: 50, trade_count: 1 }, equity_curve: [], trades: [], rejected_orders: [] } };
    }
    await route.fulfill({ json });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "运行全市场筛选", exact: true }).click();
  await page.getByRole("button", { name: "选择全部 2 只" }).click();
  await page.getByLabel("目标自选分组").selectOption("g1");
  await page.getByRole("button", { name: "批量加入自选", exact: true }).click();
  await expect(page.getByText("已将 2 只股票加入芯片观察并保存来源")).toBeVisible();
  await page.getByRole("button", { name: "策略回测", exact: true }).click();
  await page.getByLabel("回测股票来源").selectOption("group");
  await page.getByLabel("回测自选分组").selectOption("g1");
  await page.getByLabel("回测方式").selectOption("individual");
  await page.getByRole("button", { name: "导入入场 JSON" }).click();
  const entry = { kind: "condition", metric: "return_20", timeframe: "1d", operator: "gte", right: { kind: "constant", value: 45, unit: "percent" } };
  await page.getByLabel("入场 JSON 文件").setInputFiles({ name: "entry.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(entry)) });
  await page.getByRole("button", { name: "应用入场 JSON" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "运行策略回测" }).click();
  await expect(page.getByText("批量回测结束，共处理 2 只股票")).toBeVisible();
  expect(requests).toEqual([["600001.SH"], ["600002.SH"]]);
});
