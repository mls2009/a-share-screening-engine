import { expect, test } from "@playwright/test";

test("backtest controls stay dark and readable at desktop and mobile widths", async ({ page }) => {
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({ json: path === "/api/catalog" ? [{ key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte"], group: "price", supported_modes: ["backtest", "close"], period: 20 }] : [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "策略回测", exact: true }).click();
  await expect(page.getByRole("button", { name: "暂停条件", exact: true }).first()).toHaveCSS("background-color", "rgb(27, 37, 40)");
  await expect(page.getByRole("button", { name: "复制条件", exact: true }).first()).toHaveCSS("color", "rgb(231, 233, 229)");
  await page.getByRole("button", { name: "导入入场 JSON" }).click();
  await expect(page.getByLabel("入场条件 JSON")).toHaveCSS("background-color", "rgb(13, 16, 18)");
  await page.screenshot({ path: "/tmp/backtest-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "取消", exact: true })).toHaveCSS("background-color", "rgb(27, 37, 40)");
  const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.width);
  await page.screenshot({ path: "/tmp/backtest-mobile.png", fullPage: true });
});
