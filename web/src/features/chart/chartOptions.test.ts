import type { Bar, PriceZone } from "../../types";
import { buildChartOption, zonePresentation } from "./chartOptions";

const bars: Bar[] = [
  { symbol: "600001.SH", timestamp: "2026-08-19T15:00:00+08:00", open: 10, high: 11, low: 9.8, close: 10.8, volume_shares: 1000, amount_cny: 10800 },
  { symbol: "600001.SH", timestamp: "2026-08-20T15:00:00+08:00", open: 10.8, high: 11.2, low: 10.5, close: 10.6, volume_shares: 1800, amount_cny: 19080 },
];
const zone = (kind: "support" | "resistance", source: "auto" | "manual"): PriceZone => ({
  zone_id: `${kind}-${source}`, timeframe: "1d", as_of_date: "2026-08-20", zone_kind: kind,
  geometry: "horizontal", lower_price: kind === "support" ? 9.7 : 11.7,
  center_price: kind === "support" ? 9.8 : 11.8, upper_price: kind === "support" ? 9.9 : 11.9,
  slope: null, intercept: null, anchors: [], strength: .8, touches: 3, source,
});

it("支撑为绿色、压力为红色，自动虚线与手动实线有明确区别", () => {
  expect(zonePresentation(zone("support", "auto"))).toMatchObject({ color: "#2ecf79", lineType: "dashed", label: "自动支撑" });
  expect(zonePresentation(zone("resistance", "manual"))).toMatchObject({ color: "#ff5a67", lineType: "solid", label: "手动压力" });
});

it("K 线、成交量和支撑压力共享时间轴", () => {
  const option = buildChartOption(bars, [zone("support", "auto"), zone("resistance", "manual")]);
  const series = option.series as Array<Record<string, unknown>>;
  expect(series[0]).toMatchObject({ type: "candlestick", name: "K 线" });
  expect(series[1]).toMatchObject({ type: "bar", name: "成交量", xAxisIndex: 1 });
  expect(series.some((item) => item.name === "自动支撑")).toBe(true);
  expect(series.some((item) => item.name === "手动压力")).toBe(true);
  expect(option.dataZoom).toHaveLength(2);
  const xAxis = (option.xAxis as Array<{ axisLabel: { formatter: (value: string) => string } }>)[0];
  expect(xAxis.axisLabel.formatter("2026-08-19T15:00:00+08:00")).toBe("08-19");
  expect(xAxis.axisLabel.formatter("2026-08-19T10:15:00+08:00")).toBe("08-19 10:15");
});
