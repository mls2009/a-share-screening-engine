import type { Bar, PriceZone } from "../../types";
import { buildChartOption, candleTooltip, zonePresentation } from "./chartOptions";

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

it("boxes matched candles without moving the evidence to a later date", () => {
  const marks = [{ metric: "close", timeframe: "1d" as const, date: "2026-08-20", periods: 2, label: "入选依据" }];
  const option = buildChartOption(bars, [], [], [], marks);
  const series = option.series as TestSeries[];
  expect(series.some((item) => item.markArea)).toBe(true);
  const outside = buildChartOption(bars, [], [], [], [{ ...marks[0], date: "2026-08-21" }]);
  expect((outside.series as TestSeries[]).some((item) => item.markArea)).toBe(false);
});

it("marks the moving average curve at the matched candle timestamp", () => {
  const indicators = bars.map((bar) => ({ timestamp: bar.timestamp, ma_10: 10 })) as import("../../types").ChartIndicatorPoint[];
  const option = buildChartOption(bars, [], indicators, ["ma"], [{ metric: "ma_10", timeframe: "1d", date: "2026-08-20", periods: 1, label: "均线条件" }]);
  const series = option.series as Array<{ name: string; markPoint?: { data: Array<{ coord: unknown[] }> } }>;
  expect(series.find((item) => item.markPoint)?.markPoint?.data[0].coord).toEqual([bars[1].timestamp, 10]);
});
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

it("默认叠加 MA，并为 BOLL 和 MACD 生成对应图形", () => {
  const indicators = [{
    timestamp: "2026-08-19T15:00:00+08:00", ma_5: 10.1, ma_10: 10.2, ma_20: 10.3, ma_30: 10.4,
    boll_upper: 11.5, boll_middle: 10.3, boll_lower: 9.1,
    macd: 0.2, macd_signal: 0.1, macd_hist: 0.2,
  }, {
    timestamp: "2026-08-20T15:00:00+08:00", ma_5: 10.3, ma_10: 10.4, ma_20: 10.5, ma_30: 10.6,
    boll_upper: 11.7, boll_middle: 10.5, boll_lower: 9.3,
    macd: 0.3, macd_signal: 0.15, macd_hist: 0.3,
  }];

  const option = buildChartOption(bars, [], indicators as never, ["ma", "boll", "macd"] as never);
  const series = option.series as Array<Record<string, unknown>>;
  const xAxis = option.xAxis as Array<Record<string, unknown>>;

  expect(series.find((item) => item.name === "MA5")).toMatchObject({ type: "line", yAxisIndex: 0, data: [10.1, 10.3] });
  expect(series.find((item) => item.name === "MA30")).toMatchObject({ type: "line", yAxisIndex: 0, data: [10.4, 10.6] });
  expect(series.find((item) => item.name === "BOLL上轨")).toMatchObject({ type: "line", yAxisIndex: 0 });
  expect(series.find((item) => item.name === "MACD柱")).toMatchObject({ type: "bar", yAxisIndex: 2, data: [0.2, 0.3] });
  expect(series.find((item) => item.name === "DIF")).toMatchObject({ type: "line", yAxisIndex: 2 });
  expect(xAxis).toHaveLength(3);
  expect((option.dataZoom as unknown[])[0]).toMatchObject({ xAxisIndex: [0, 1, 2] });
});

it("uses dedicated limit colors for candles and matching volume bars", () => {
  const option = buildChartOption([{...bars[0],limit_state:"up"},{...bars[1],limit_state:"down"}],[],[],[]);
  const series = option.series as Array<{ data: Array<{itemStyle: {color: string; borderColor?: string}}> }>;
  expect(series[0].data[0].itemStyle.color).toBe("#ffca45");
  expect(series[0].data[1].itemStyle.borderColor).toBe("#a78bfa");
  expect(series[1].data[0].itemStyle.color).toBe("#ffca45");
  expect(series[1].data[1].itemStyle.color).toBe("#a78bfa");
});


it("指标提示文字使用对应线条和柱状图颜色", () => {
  const option = buildChartOption(bars, [], [], ["ma", "boll", "macd", "kdj", "rsi", "obv", "atr", "volume_ma"]);
  const series = option.series as Array<{name:string; type:string; lineStyle?:{color:string}; itemStyle?:{color:string}}>;
  const lines = series.filter(item => item.type === "line");
  expect(lines.length).toBeGreaterThan(10);
  for (const item of lines) {
    expect(item.itemStyle?.color).toBe(item.lineStyle?.color);
    expect(candleTooltip(bars, [{ dataIndex: 1, seriesType: "line", seriesName: item.name, value: 12.34, color: item.itemStyle?.color }]))
      .toContain(`<span style="color:${item.lineStyle?.color}">${item.name}：12.34</span>`);
  }
  expect(candleTooltip(bars, [{dataIndex: 1, seriesType: "bar", seriesName: "MACD柱", value: 0.2, color: "#aab5b8"}]))
    .toContain('<span style="color:#aab5b8">MACD柱：0.20</span>');
});

it("真空区标记使用冻结的上下沿", () => {
  const option = buildChartOption(bars, [], [], [], [{
    metric: "close", timeframe: "1d", date: "2026-08-20", startDate: "2026-08-19",
    periods: 2, label: "真空区", priceLow: 9.8, priceHigh: 11.2,
  }]);
  const series = option.series as Array<{ markArea?: { data: Array<Array<{ yAxis: number }>> } }>;
  const box = series.find(item => item.markArea)?.markArea?.data[0];
  expect(box?.map(point => point.yAxis)).toEqual([9.8, 11.2]);
});

it("默认均线包含MA120和MA250且提示配色跟随线条", () => {
  const indicators = bars.map(bar => ({timestamp: bar.timestamp, ma_120: 10, ma_250: 9.9})) as import("../../types").ChartIndicatorPoint[];
  const option = buildChartOption(bars, [], indicators);
  const series = option.series as Array<{name: string; data: number[]; lineStyle?: {color: string}; itemStyle?: {color: string}}>;
  for (const [name, value] of [["MA120", 10], ["MA250", 9.9]] as const) {
    const line = series.find(item => item.name === name);
    expect(line?.data).toEqual([value, value]);
    expect(line?.itemStyle?.color).toBe(line?.lineStyle?.color);
  }
});

it("shows a visible Pinbar label on the exact signal candle", () => {
  const option = buildChartOption(bars, [], [], [], [{metric:"close", timeframe:"1d", date:"2026-08-20", periods:1,
    label:"裸K：看涨Pinbar（下影占比>2/3）：True"}]);
  const series = option.series as Array<{markPoint?: {label?: {show?:boolean}; data:Array<{name:string;coord:unknown[]}>}}>;
  const signal = series.find(item => item.markPoint?.data.some(point => point.name === "看涨Pinbar"));
  expect(signal?.markPoint?.label?.show).toBe(true);
  expect(signal?.markPoint?.data[0].coord).toEqual([bars[1].timestamp, bars[1].low]);
});

it("initial viewport includes older Pinbar hits as well as recent hits", () => {
  const history = Array.from({length:300}, (_,i)=>({...bars[0],timestamp:new Date(Date.UTC(2025,0,i+1)).toISOString()}));
  const marks = [40,270].map(i=>({metric:'close',timeframe:'1d' as const,date:history[i].timestamp.slice(0,10),periods:1,label:'裸K：看涨Pinbar'}));
  const option=buildChartOption(history,[],[],[],marks);
  const zoom=option.dataZoom as Array<{start:number}>;
  expect(zoom[0].start).toBeLessThan(40/300*100);
  const series=option.series as Array<{markPoint?:unknown}>;
  expect(series.filter(s=>s.markPoint)).toHaveLength(2);
});

it('labels a two-bar Pinbar distinctly and covers both candles',()=>{
  const option=buildChartOption(bars,[],[],[],[{metric:'close',timeframe:'1d',date:'2026-08-20',startDate:'2026-08-19',periods:2,label:'裸K：双K合成·看涨Pinbar'}]);
  const series=option.series as Array<{markPoint?:{data:Array<{name:string}>};markArea?:{data:Array<Array<{xAxis:number}>>}}>;
  expect(series.find(s=>s.markPoint)?.markPoint?.data[0].name).toBe('双K·看涨Pinbar');
  expect(series.find(s=>s.markArea)?.markArea?.data[0].map(p=>p.xAxis)).toEqual([-.45,1.45]);
});

it('历史形态绘制两条斜边和转折点，而非突破标记',()=>{
  const option=buildChartOption(bars,[],[],[],[{metric:'close',timeframe:'1d',date:'2026-08-20',startDate:'2026-08-19',periods:2,label:'上升三角形 · 测试',
    shape:{kind:'ascending',upper_start:12,upper_end:12,lower_start:9,lower_end:10,
      high_points:[{date:'2026-08-19',price:12}],low_points:[{date:'2026-08-20',price:10}]}}]);
  const series=(option.series as TestSeries[]).find(s=>s.name==='上升三角形 · 测试');
  expect(series?.markLine?.data).toEqual([
    [{coord:[expect.any(String),12]},{coord:[expect.any(String),12]}],
    [{coord:[expect.any(String),9]},{coord:[expect.any(String),10]}],
  ]);
  expect(series?.markArea).toBeUndefined();
});

it('三种形态的边界线使用各自固定颜色',()=>{
  for (const [kind,color] of [['ascending','#f3c969'],['descending','#b49aff'],['range','#6bc5ff']] as const) {
    const option=buildChartOption(bars,[],[],[],[{metric:'close',timeframe:'1d',date:'2026-08-20',startDate:'2026-08-19',periods:2,label:kind,
      shape:{kind,upper_start:12,upper_end:12,lower_start:9,lower_end:10,high_points:[],low_points:[]}}]);
    const lines=option.series as Array<{name:string;markLine?:{lineStyle:{color:string};data:unknown[]}}>;
    expect(lines.find(s=>s.name===kind)?.markLine?.lineStyle.color).toBe(color);
    expect(lines.find(s=>s.name===kind)?.markLine?.data).toHaveLength(2);
  }
});

it("marks repeated MA support with distinct colors and arrows only on the return", () => {
  const marks = [
    { metric: "close", timeframe: "1d" as const, date: "2026-08-19", periods: 1, label: "均线重复支撑·MA120·首次触及" },
    { metric: "close", timeframe: "1d" as const, date: "2026-08-20", startDate: "2026-08-19", periods: 1, label: "均线重复支撑·MA120·本次命中·双K" },
    { metric: "close", timeframe: "1d" as const, date: "2026-08-20", periods: 1, label: "均线重复支撑·MA250·本次命中·单K" },
  ];
  const series = buildChartOption(bars, [], [], [], marks).series as Array<{
    markPoint?: { itemStyle: { color: string }; data: Array<{ name: string }> };
    markArea?: unknown;
  }>;
  const arrows = series.filter(s => s.markPoint);
  expect(arrows).toHaveLength(2);
  expect(arrows.map(s => s.markPoint!.itemStyle.color)).toEqual(["#64d8cb", "#d897ff"]);
  expect(arrows.map(s => s.markPoint!.data[0].name)).toEqual(["半年线支撑", "年线支撑"]);
  expect(series.filter(s => s.markArea)).toHaveLength(3);
});

it('新策略无需名称白名单，初始视图包含全部历史命中区间', () => {
  const history = Array.from({length:300}, (_,i)=>({...bars[0],timestamp:new Date(Date.UTC(2025,0,i+1)).toISOString()}));
  const option = buildChartOption(history, [], [], [], [{metric:'close',timeframe:'1d',date:history[42].timestamp.slice(0,10),startDate:history[40].timestamp.slice(0,10),periods:3,label:'任意新增策略'}]);
  expect((option.dataZoom as Array<{start:number}>)[0].start).toBeLessThan(40/300*100);
});

it('年线收复同时标出跌破和收复点以及整个区间', () => {
  const option = buildChartOption(bars, [], [], [], [{metric:'close',timeframe:'1d',date:'2026-08-20',startDate:'2026-08-19',periods:2,label:'年线跌破后收复·1日收复'}]);
  const series = option.series as Array<{markPoint?:{data:Array<{name:string;coord:unknown[]}>};markArea?:unknown}>;
  const points = series.flatMap(s=>s.markPoint?.data ?? []);
  expect(points.map(p=>p.name)).toEqual(expect.arrayContaining(['跌破年线','收复年线']));
  expect(points.find(p=>p.name==='收复年线')?.coord).toEqual([bars[1].timestamp,bars[1].low]);
  expect(series.filter(s=>s.markArea)).toHaveLength(1);
});
