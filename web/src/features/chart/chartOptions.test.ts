import type { Bar, PriceZone } from "../../types";
import { buildChartOption, zonePresentation } from "./chartOptions";

type TestTooltip = {
  show?: boolean;
  trigger?: string;
  formatter?: unknown;
};

type TestSeries = {
  name?: string;
  silent?: boolean;
  triggerEvent?: string;
  data?: unknown;
  markArea?: unknown;
  tooltip?: TestTooltip;
  endLabel?: { show?: boolean; formatter?: unknown };
  markLine?: {
    silent?: boolean;
    data?: unknown;
    tooltip?: TestTooltip;
    label?: { show?: boolean; formatter?: unknown };
    lineStyle?: { width?: number };
  };
};

const bars: Bar[] = [
  { symbol: "600001.SH", timestamp: "2026-08-19T15:00:00+08:00", open: 10, high: 11, low: 9.8, close: 10.8, volume_shares: 1000, amount_cny: 10800 },
  { symbol: "600001.SH", timestamp: "2026-08-20T15:00:00+08:00", open: 10.8, high: 11.2, low: 10.5, close: 10.6, volume_shares: 1800, amount_cny: 19080 },
];
const autoHorizontalZone = {
  zone_id: "auto-horizontal", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "support",
  geometry: "horizontal", lower_price: 9.7, center_price: 9.8, upper_price: 9.9,
  slope: null, intercept: null, anchors: [], strength: .8, touches: 3, source: "auto", reappeared: false,
} satisfies PriceZone;
const autoTrendZone = {
  zone_id: "auto-trend", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "uptrend",
  geometry: "trend", lower_price: 9.7, center_price: 9.8, upper_price: 9.9,
  slope: .4, intercept: 10, anchors: [["2026-08-19", 10], ["2026-08-20", 10.4]] as Array<[string, number]>,
  strength: .8, touches: 3, source: "auto", reappeared: false,
} satisfies PriceZone;
const autoDowntrendZone = {
  ...autoTrendZone,
  zone_id: "auto-downtrend",
  zone_kind: "downtrend",
} satisfies PriceZone;
const manualHorizontalZone = {
  zone_id: "manual-horizontal", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "resistance",
  geometry: "horizontal", lower_price: 11.7, center_price: 11.8, upper_price: 11.9,
  slope: null, intercept: null, anchors: [], strength: .8, touches: 3, source: "manual", reappeared: false,
} satisfies PriceZone;
const manualTrendZone = {
  zone_id: "manual-trend", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "support",
  geometry: "trend", lower_price: 9.7, center_price: 9.8, upper_price: 9.9,
  slope: .4, intercept: 10, anchors: [["2026-08-19", 10], ["2026-08-20", 10.4]] as Array<[string, number]>,
  strength: .8, touches: 3, source: "manual", reappeared: false,
} satisfies PriceZone;

// @ts-expect-error 自动水平线不能使用趋势方向 kind
const invalidAutoHorizontalZone = { ...autoHorizontalZone, zone_kind: "uptrend" } satisfies PriceZone;
// @ts-expect-error 手动画线不能使用自动趋势方向 kind
const invalidManualTrendZone = { ...manualTrendZone, zone_kind: "uptrend" } satisfies PriceZone;

it("拒绝运行时绕过类型约束的支撑压力线组合", () => {
  expect(() => zonePresentation(invalidAutoHorizontalZone as unknown as PriceZone))
    .toThrow("无效的支撑压力线类型");
  expect(() => zonePresentation(invalidManualTrendZone as unknown as PriceZone))
    .toThrow("无效的支撑压力线类型");
});

it("支撑和上升趋势为绿色，压力和下降趋势为红色，只有删除后重现的线使用虚线", () => {
  expect(zonePresentation(autoHorizontalZone)).toMatchObject({ color: "#2ecf79", lineType: "solid", label: "自动水平支撑" });
  expect(zonePresentation(manualHorizontalZone)).toMatchObject({ color: "#ff5a67", lineType: "solid", label: "手动压力" });
  expect(zonePresentation(autoTrendZone)).toMatchObject({ color: "#2ecf79", lineType: "solid", label: "自动上升趋势线" });
  expect(zonePresentation(autoDowntrendZone)).toMatchObject({ color: "#ff5a67", lineType: "solid", label: "自动下降趋势线" });
  expect(zonePresentation({ ...autoHorizontalZone, reappeared: true })).toMatchObject({ lineType: "dashed" });
});

it("K 线、成交量和支撑压力共享时间轴", () => {
  const option = buildChartOption(bars, [autoHorizontalZone, manualHorizontalZone]);
  const series = option.series as Array<Record<string, unknown>>;
  expect(series[0]).toMatchObject({ type: "candlestick", name: "K 线" });
  expect(series[1]).toMatchObject({ type: "bar", name: "成交量", xAxisIndex: 1 });
  expect(series.some((item) => item.name === "自动水平支撑")).toBe(true);
  expect(series.some((item) => item.name === "手动压力")).toBe(true);
  expect(option.dataZoom).toHaveLength(2);
  const xAxis = (option.xAxis as Array<{ axisLabel: { formatter: (value: string) => string } }>)[0];
  expect(xAxis.axisLabel.formatter("2026-08-19T15:00:00+08:00")).toBe("08-19");
  expect(xAxis.axisLabel.formatter("2026-08-19T10:15:00+08:00")).toBe("08-19 10:15");
});

it("自动水平线只在直接悬停时显示中心价，手动水平线保持常驻标签", () => {
  const option = buildChartOption(bars, [autoHorizontalZone, manualHorizontalZone]);
  const series = option.series as TestSeries[];
  const support = series.find((item) => item.name === "自动水平支撑")!;
  const resistance = series.find((item) => item.name === "手动压力")!;
  const supportLine = support.markLine!;
  const resistanceLine = resistance.markLine!;

  expect(option.tooltip).toMatchObject({ trigger: "axis" });
  expect(support.markArea).toBeUndefined();
  expect(support.silent).toBe(false);
  expect(supportLine.data).toEqual([{ yAxis: 9.8 }]);
  expect(supportLine.silent).toBe(false);
  expect(supportLine.label).toMatchObject({ show: false });
  expect(supportLine.tooltip).toMatchObject({ show: true, trigger: "item" });
  const formatter = supportLine.tooltip!.formatter as (params: unknown) => string;
  expect(formatter({})).toContain("自动水平支撑");
  expect(formatter({})).toContain("9.80");
  expect(supportLine.lineStyle).toMatchObject({ width: 2 });
  expect(resistance.silent).toBe(true);
  expect(resistanceLine.silent).toBe(true);
  expect(resistanceLine.label).toMatchObject({ show: true });
  expect(resistanceLine.label!.formatter).toContain("11.80");
});

it("自动趋势线只在直接悬停时显示当前时间和拟合价，手动趋势线保持常驻标签", () => {
  const minuteBars = bars.map((bar, index) => ({
    ...bar,
    timestamp: index === 1 ? "2026-08-20T10:15:00+08:00" : bar.timestamp,
  }));
  const option = buildChartOption(minuteBars, [
    autoTrendZone,
    manualTrendZone,
  ]);
  const series = option.series as TestSeries[];
  const automatic = series.find((item) => item.name === "自动上升趋势线")!;
  const manual = series.find((item) => item.name === "手动支撑")!;

  expect(option.tooltip).toMatchObject({ trigger: "axis" });
  expect(automatic).toMatchObject({
    silent: false,
    triggerEvent: "line",
    endLabel: { show: false },
    tooltip: { show: true, trigger: "item" },
  });
  const formatter = automatic.tooltip!.formatter as (params: unknown) => string;
  expect(formatter({ dataIndex: 1 })).toContain("自动上升趋势线 · 08-20 10:15 · 10.40");
  expect(() => formatter({ dataIndex: -1 })).not.toThrow();
  expect(() => formatter({ dataIndex: 99 })).not.toThrow();
  expect(() => formatter({ dataIndex: "1" })).not.toThrow();
  expect(formatter({ dataIndex: 99 })).toContain("自动上升趋势线");

  const noValueOption = buildChartOption(minuteBars, [{
    ...autoTrendZone,
    anchors: [["2026-08-19", 10]],
  }]);
  const noValueSeries = (noValueOption.series as TestSeries[])
    .find((item) => item.name === "自动上升趋势线")!;
  const noValueFormatter = noValueSeries.tooltip!.formatter as (params: unknown) => string;
  expect(() => noValueFormatter({ dataIndex: 1 })).not.toThrow();
  expect(noValueFormatter({ dataIndex: 1 })).toContain("自动上升趋势线");

  expect(manual.silent).toBe(true);
  expect(manual.endLabel).toMatchObject({ show: true });
});

it("分钟趋势锚点按完整时间匹配同一天内的多根K线", () => {
  const intradayBars: Bar[] = ["09:30", "09:45", "10:00", "10:15"].map((clock, index) => ({
    ...bars[index % bars.length],
    timestamp: `2026-08-20T${clock}:00+08:00`,
  }));
  const trend: PriceZone = {
    ...autoTrendZone,
    timeframe: "15m",
    center_price: 13,
    anchors: [
      ["2026-08-20T09:30:00+08:00", 10],
      ["2026-08-20T09:45:00+08:00", 11],
      ["2026-08-20T10:15:00+08:00", 13],
    ],
  };

  const option = buildChartOption(intradayBars, [trend]);
  const automatic = (option.series as TestSeries[])
    .find((item) => item.name === "自动上升趋势线")!;

  expect(automatic.data).toEqual([10, 11, 12, 13]);
  const formatter = automatic.tooltip!.formatter as (params: unknown) => string;
  expect(formatter({ dataIndex: 2 })).toContain("08-20 10:00 · 12.00");
});

it("周线趋势锚点按日期匹配并将中心线延伸到最新K线", () => {
  const weeklyBars: Bar[] = [
    { ...bars[0], timestamp: "2026-08-07T15:00:00+08:00" },
    { ...bars[1], timestamp: "2026-08-14T15:00:00+08:00" },
    { ...bars[1], timestamp: "2026-08-21T15:00:00+08:00" },
    { ...bars[1], timestamp: "2026-08-28T15:00:00+08:00" },
  ];
  const trend: PriceZone = {
    ...autoTrendZone,
    center_price: 10.4,
    anchors: [["2026-08-07", 10], ["2026-08-14", 10.4], ["2026-08-21", 10.2]],
  };

  const option = buildChartOption(weeklyBars, [trend]);
  const series = option.series as TestSeries[];
  const support = series.find((item) => item.name === "自动上升趋势线")!;

  expect(support.data).toEqual([10.1, 10.2, 10.3, 10.4]);
  expect(support.endLabel!.formatter).toContain("10.40");
});
