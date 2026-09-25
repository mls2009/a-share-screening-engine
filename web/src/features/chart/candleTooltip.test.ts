import { candleTooltip } from "./chartOptions";
import type { Bar } from "../../types";
const bar = (close: number): Bar => ({ symbol: "600001.SH", timestamp: "2026-09-08T15:00:00+08:00", open: 12, close, low: 9, high: 13, volume_shares: 100, amount_cny: 1000 });
it("uses previous close for change, separately from open-close change", () => {
  const value = candleTooltip([bar(10), bar(11)], [{ dataIndex: 1 }]);
  expect(value).toContain("涨跌幅（相对上一根收盘）：+10.00%");
  expect(value).toContain("振幅（高低价差÷上一根收盘）：40.00%");
  expect(value).toContain("实体涨跌幅（开收变化）：-8.33%");
});
it("does not invent previous close for the first candle", () => {
  expect(candleTooltip([bar(11)], [{ dataIndex: 0 }])).toContain("暂无（缺少上一根）");
  expect(candleTooltip([], [])).toBe("");
});

it("shows each OHLC percentage relative to previous close", () => {
  const value = candleTooltip([bar(10), bar(11)], [{ dataIndex: 1 }]);
  for (const text of ["开 12.00（+20.00%）", "收 11.00（+10.00%）", "高 13.00（+30.00%）", "低 9.00（-10.00%）"]) expect(value).toContain(text);
});
