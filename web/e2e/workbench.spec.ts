import { expect, test } from "@playwright/test";

test("workbench and chart desk render without browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

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
    ] });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "选股工作台" })).toBeVisible();
  await expect(page.getByLabel("指标")).toBeVisible();
  await page.screenshot({ path: "test-results/screener-workbench.png", fullPage: true });

  await page.getByRole("button", { name: "K 线研究" }).click();
  await expect(page.getByRole("heading", { name: "K 线研究" })).toBeVisible();
  await expect(page.getByRole("img", { name: "K 线与成交量图" })).toBeVisible();
  await expect(page.getByText("自动水平支撑")).toBeVisible();
  await expect(page.getByText("手动水平压力")).toBeVisible();
  await page.screenshot({ path: "test-results/chart-desk.png", fullPage: true });

  expect(errors).toEqual([]);
});
