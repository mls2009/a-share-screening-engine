import { expect, test } from "@playwright/test";

test("watchlist uses readable dark buttons and imports a condition JSON file", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/market-updates") {
      await route.fulfill({ contentType: "text/event-stream", body: "event: ready\ndata: 0\n\n" });
      return;
    }
    const json = path === "/api/watchlist" ? [{ symbol: "600001.SH", name: "测试股票", sources: [], groups: [], quote: { date: "2026-09-04", close: 12.3, change_percent: 2.5 } }]
      : path === "/api/catalog" ? [{ key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte"], group: "price", supported_modes: ["backtest"], period: 20 }]
      : path === "/api/screens/validate" ? { valid: true, errors: [] } : [];
    await route.fulfill({ json });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "自选股", exact: false }).click();
  await expect(page.getByRole("button", { name: "移除自选" })).toHaveCSS("color", "rgb(231, 233, 229)");
  await expect(page.locator(".watch-stock-name strong")).toHaveCSS("font-size", "18px");
  await expect(page.getByRole("cell", { name: /^\+2\.50% 历史涨跌幅/ })).toBeVisible();
  await page.screenshot({ path: "/tmp/astock-watchlist.png", fullPage: true });
  await page.getByRole("button", { name: "查看详情" }).click();
  const section = page.locator(".history-waves");
  await expect(section.getByRole("button", { name: "保存本股规则" })).toHaveCSS("background-color", "rgb(27, 37, 40)");
  await section.getByRole("button", { name: "导入 JSON" }).click();
  const tree = { kind: "condition", metric: "return_20", timeframe: "1d", operator: "gte", right: { kind: "constant", value: 45, unit: "percent" } };
  await page.getByLabel("选择 JSON 文件").setInputFiles({ name: "conditions.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(tree)) });
  await expect(page.getByLabel("条件 JSON", { exact: true })).toHaveValue(JSON.stringify(tree));
  await page.getByRole("button", { name: "应用 JSON" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const download = page.waitForEvent("download");
  await section.getByRole("button", { name: "导出 JSON" }).click();
  expect((await download).suggestedFilename()).toBe("600001.SH-conditions.json");
});
