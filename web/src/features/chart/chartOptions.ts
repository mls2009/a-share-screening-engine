import type { EChartsOption, LineSeriesOption } from "echarts";

import type { Bar, ChartIndicator, ChartIndicatorPoint, PriceZone } from "../../types";
import type { ConditionMark } from "../watchlist/model";
import { STRATEGY_COLORS } from "../sequoia/chartMarks";

export const DEFAULT_CHART_INDICATORS: ChartIndicator[] = ["ma"];

const compactTime = (value: string) => {
  const day = value.slice(5, 10);
  const time = value.includes("T") ? value.slice(11, 16) : "";
  return time && time !== "15:00" ? `${day} ${time}` : day;
};

export function zonePresentation(zone: PriceZone) {
  const kind = zone.zone_kind as string;
  const validGeometry = zone.geometry === "horizontal"
    ? zone.slope === null && zone.intercept === null
    : zone.geometry === "trend" && typeof zone.slope === "number" && typeof zone.intercept === "number";
  if (!validGeometry) throw new Error("无效的支撑压力线类型");

  let support: boolean;
  let label: string;
  if (zone.source === "manual" && (kind === "support" || kind === "resistance")) {
    support = kind === "support";
    label = `手动${support ? "支撑" : "压力"}`;
  } else if (zone.source === "auto" && zone.geometry === "horizontal" && (kind === "support" || kind === "resistance")) {
    support = kind === "support";
    label = `自动水平${support ? "支撑" : "压力"}`;
  } else if (zone.source === "auto" && zone.geometry === "trend" && (kind === "uptrend" || kind === "downtrend")) {
    support = kind === "uptrend";
    label = support ? "自动上升趋势线" : "自动下降趋势线";
  } else {
    throw new Error("无效的支撑压力线类型");
  }
  return {
    color: support ? "#2ecf79" : "#ff5a67",
    lineType: zone.reappeared ? "dashed" as const : "solid" as const,
    label,
  };
}

function anchors(zone: PriceZone): Array<[string, number]> {
  if (Array.isArray(zone.anchors)) return zone.anchors;
  try { return JSON.parse(zone.anchors) as Array<[string, number]>; } catch { return []; }
}

function trendValues(zone: PriceZone, bars: Bar[]): Array<number | null> {
  const indexed = anchors(zone)
    .map(([anchorAt, price]) => [
      bars.findIndex((bar) => anchorAt.includes("T")
        ? bar.timestamp === anchorAt
        : bar.timestamp.slice(0, 10) === anchorAt),
      price,
    ] as const)
    .filter(([index]) => index >= 0)
    .sort(([left], [right]) => left - right);
  if (indexed.length < 2) return bars.map(() => null);
  const firstIndex = indexed[0][0];
  const meanIndex = indexed.reduce((sum, [index]) => sum + index, 0) / indexed.length;
  const meanPrice = indexed.reduce((sum, [, price]) => sum + price, 0) / indexed.length;
  const denominator = indexed.reduce((sum, [index]) => sum + (index - meanIndex) ** 2, 0);
  if (denominator === 0) return bars.map(() => null);
  const slope = indexed.reduce(
    (sum, [index, price]) => sum + (index - meanIndex) * (price - meanPrice),
    0,
  ) / denominator;
  const intercept = meanPrice - slope * meanIndex;
  return bars.map((_, index) => (
    index < firstIndex ? null : Number((intercept + slope * index).toFixed(12))
  ));
}

function tooltipDataIndex(params: unknown): number | undefined {
  if (typeof params !== "object" || params === null || !("dataIndex" in params)) return undefined;
  const dataIndex = (params as { dataIndex?: unknown }).dataIndex;
  return typeof dataIndex === "number" && Number.isInteger(dataIndex) && dataIndex >= 0
    ? dataIndex
    : undefined;
}

export function candleTooltip(bars: Bar[], params: unknown): string {
  const entries = Array.isArray(params) ? params : [params];
  const index = entries.map(tooltipDataIndex).find(value => value !== undefined);
  if (index === undefined || !bars[index]) return "";
  const bar = bars[index];
  const previous = bars[index - 1]?.close;
  const percent = (base: number | undefined, price = bar.close) => base && base > 0 ? (price / base - 1) * 100 : null;
  const change = percent(previous);
  const signed = (value: number | null) => value === null ? "暂无（缺少上一根）" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  const color = change === null || change === 0 ? "#dfe3e1" : change > 0 ? "#ff7a85" : "#50d5a0";
  const escape = (text: string) => text.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]!));
  const indicators = entries.flatMap(entry => {
    if (!entry || typeof entry !== "object" || !["line", "bar"].includes(entry.seriesType) || typeof entry.value !== "number" || !Number.isFinite(entry.value)) return [];
    const indicatorColor = typeof entry.color === "string" && /^#[0-9a-f]{3,8}$/i.test(entry.color) ? entry.color : "#dfe3e1";
    return [`<span style="color:${indicatorColor}">${escape(String(entry.seriesName ?? "指标"))}：${entry.value.toFixed(2)}</span>`];
  });
  return `${bar.timestamp.slice(0, 19).replace("T", " ")}${bar.limit_state === "up" ? " · 收盘涨停" : bar.limit_state === "down" ? " · 收盘跌停" : ""}<br/>`
    + `开 ${bar.open.toFixed(2)}（${signed(percent(previous, bar.open))}）　收 ${bar.close.toFixed(2)}（${signed(change)}）<br/>高 ${bar.high.toFixed(2)}（${signed(percent(previous, bar.high))}）　低 ${bar.low.toFixed(2)}（${signed(percent(previous, bar.low))}）<br/>`
    + `<span style="color:${color}">涨跌幅（相对上一根收盘）：${signed(change)}</span><br/>`
    + `振幅（高低价差÷上一根收盘）：${previous && previous > 0 ? ((bar.high - bar.low) / previous * 100).toFixed(2) + "%" : "暂无（缺少上一根）"}<br/>`
    + `实体涨跌幅（开收变化）：${signed(percent(bar.open))}<br/>成交量：${bar.volume_shares.toLocaleString("zh-CN")} 股<br/>成交额：${bar.amount_cny.toLocaleString("zh-CN")} 元` + (indicators.length ? `<br/>${indicators.join("<br/>")}` : "");
}

function trendTooltip(
  label: string,
  bars: Bar[],
  values: Array<number | null>,
  params: unknown,
): string {
  const dataIndex = tooltipDataIndex(params);
  if (dataIndex === undefined) return label;
  const timestamp = bars[dataIndex]?.timestamp;
  const value = values[dataIndex];
  const price = typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "";
  return [label, timestamp ? compactTime(timestamp) : "", price].filter(Boolean).join(" · ");
}

function zoneSeries(zone: PriceZone, bars: Bar[]): LineSeriesOption {
  const style = zonePresentation(zone);
  const width = zone.source === "manual" ? 3 : 2;
  const base: LineSeriesOption = {
    name: style.label,
    type: "line",
    yAxisIndex: 0,
    symbol: "none",
    silent: zone.source === "manual",
    lineStyle: { color: style.color, type: style.lineType, width, opacity: 1 },
    itemStyle: { color: style.color },
    emphasis: { disabled: true },
    z: zone.source === "manual" ? 8 : 5,
  };
  if (zone.geometry === "trend") {
    const data = trendValues(zone, bars);
    const currentPrice = [...data].reverse().find((value) => value !== null);
    return {
      ...base,
      ...(zone.source === "auto" ? {
        silent: false,
        symbol: "circle",
        symbolSize: 1,
        itemStyle: { opacity: 0 },
        triggerEvent: "line" as const,
        tooltip: {
          show: true,
          trigger: "item" as const,
          formatter: (params: unknown) => trendTooltip(style.label, bars, data, params),
        },
      } : {}),
      data,
      endLabel: {
        show: zone.source === "manual" && currentPrice !== undefined,
        formatter: `${style.label} ${currentPrice?.toFixed(2) ?? ""}`,
        color: style.color,
        backgroundColor: "#0d1113e6",
        padding: [3, 5],
        borderRadius: 2,
        fontSize: 10,
      },
    };
  }
  return {
    ...base,
    data: [],
    markLine: {
      silent: zone.source === "manual",
      symbol: ["none", "none"],
      ...(zone.source === "auto" ? {
        tooltip: {
          show: true,
          trigger: "item" as const,
          formatter: () => `${style.label} · ${zone.center_price.toFixed(2)}`,
        },
      } : {}),
      label: {
        show: zone.source === "manual",
        position: "insideEndTop",
        formatter: `${style.label} ${zone.center_price.toFixed(2)}`,
        color: style.color,
        backgroundColor: "#0d1113e6",
        padding: [3, 5],
        borderRadius: 2,
        fontSize: 10,
      },
      lineStyle: { color: style.color, type: style.lineType, width, opacity: 1 },
    itemStyle: { color: style.color },
      data: [{ yAxis: zone.center_price }],
    },
  };
}

function values(indicators: ChartIndicatorPoint[], field: keyof ChartIndicatorPoint): Array<number | null> {
  return indicators.map((item) => typeof item[field] === "number" ? item[field] : null);
}

function line(name: string, data: Array<number | null>, axis: number, color: string) {
  return {
    name,
    type: "line" as const,
    xAxisIndex: axis,
    yAxisIndex: axis,
    data,
    symbol: "none" as const,
    connectNulls: true,
    lineStyle: { color, width: 1.4 },
    itemStyle: { color },
    emphasis: { disabled: true },
  };
}

export function buildChartOption(
  bars: Bar[],
  zones: PriceZone[],
  indicators: ChartIndicatorPoint[] = [],
  selected: ChartIndicator[] = DEFAULT_CHART_INDICATORS,
  marks: ConditionMark[] = [],
): EChartsOption {
  const dates = bars.map((bar) => bar.timestamp);
  const signalDates = new Set(marks.flatMap(mark => [mark.referenceStartDate, mark.startDate, mark.date].filter((day): day is string => Boolean(day))));
  const firstSignal = bars.findIndex(bar => signalDates.has(bar.timestamp.slice(0, 10)));
  const initialStart = firstSignal >= 0 ? Math.min(Math.max(0, bars.length - 120), Math.max(0, firstSignal - 10)) : Math.max(0, bars.length - 120);
  const candleData = bars.map((bar) => {
    const color = bar.limit_state === "up" ? "#ffca45" : bar.limit_state === "down" ? "#a78bfa" : undefined;
    const value = [bar.open, bar.close, bar.low, bar.high];
    return color ? { value, itemStyle: { color, color0: color, borderColor: color, borderColor0: color } } : value;
  });
  const volumeData = bars.map((bar) => ({
    value: bar.volume_shares,
    itemStyle: { color: bar.limit_state === "up" ? "#ffca45" : bar.limit_state === "down" ? "#a78bfa" : bar.close >= bar.open ? "#2ecf79a8" : "#ff5a67a8" },
  }));
  const subIndicators = selected.filter((item) => ["macd", "kdj", "rsi", "obv", "atr"].includes(item));
  const paneCount = 2 + subIndicators.length;
  const usable = 86;
  const unit = usable / (3.4 + subIndicators.length);
  const mainHeight = unit * 2.4;
  const paneHeight = unit;
  const paneTop = (index: number) => 5 + mainHeight + 2 + (index - 1) * (paneHeight + 2);
  const grids = [
    { left: 58, right: 88, outerBoundsMode: "none" as const, top: "5%", height: `${mainHeight}%` },
    { left: 58, right: 88, outerBoundsMode: "none" as const, top: `${paneTop(1)}%`, height: `${paneHeight}%` },
    ...subIndicators.map((_, index) => ({
      left: 58, right: 88, outerBoundsMode: "none" as const, top: `${paneTop(index + 2)}%`, height: `${paneHeight}%`,
    })),
  ];
  const axes = grids.map((_, index) => ({
    type: "category" as const,
    gridIndex: index,
    data: dates,
    boundaryGap: true,
    axisLine: { lineStyle: { color: "#30383c" } },
    axisLabel: index === 0
      ? { color: "#758086", hideOverlap: true, formatter: compactTime }
      : { show: false },
    splitLine: { show: false },
    min: "dataMin" as const,
    max: "dataMax" as const,
  }));
  const yAxes = grids.map((_, index) => ({
    scale: true,
    gridIndex: index,
    splitNumber: 2,
    splitLine: { lineStyle: { color: "#20272a", type: "dashed" as const } },
    axisLabel: { color: "#758086" },
    position: "right" as const,
  }));
  const chartSeries: Array<Record<string, unknown>> = [
    { name: "K 线", type: "candlestick", data: candleData, itemStyle: { color: "#2ecf79", color0: "#ff5a67", borderColor: "#2ecf79", borderColor0: "#ff5a67" } },
    { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: volumeData, barMaxWidth: 12 },
  ];
  if (selected.includes("ma")) {
    chartSeries.push(
      line("MA5", values(indicators, "ma_5"), 0, "#f3c969"),
      line("MA10", values(indicators, "ma_10"), 0, "#6bc5ff"),
      line("MA20", values(indicators, "ma_20"), 0, "#d897ff"),
      line("MA30", values(indicators, "ma_30"), 0, "#ffab70"),
      line("MA120", values(indicators, "ma_120"), 0, "#64d8cb"),
      line("MA250", values(indicators, "ma_250"), 0, "#e6e9ef"),
    );
  }
  if (selected.includes("boll")) {
    chartSeries.push(
      line("BOLL上轨", values(indicators, "boll_upper"), 0, "#ffab70"),
      line("BOLL中轨", values(indicators, "boll_middle"), 0, "#b7c1c5"),
      line("BOLL下轨", values(indicators, "boll_lower"), 0, "#75baff"),
    );
  }
  if (selected.includes("volume_ma")) {
    chartSeries.push(
      line("VOL MA5", values(indicators, "volume_ma_5"), 1, "#f3c969"),
      line("VOL MA20", values(indicators, "volume_ma_20"), 1, "#6bc5ff"),
    );
  }
  subIndicators.forEach((indicator, offset) => {
    const axis = offset + 2;
    if (indicator === "macd") {
      chartSeries.push(
        { name: "MACD柱", type: "bar", xAxisIndex: axis, yAxisIndex: axis, data: values(indicators, "macd_hist"), barMaxWidth: 10, itemStyle: { color: "#aab5b8" } },
        line("DIF", values(indicators, "macd"), axis, "#f3c969"),
        line("DEA", values(indicators, "macd_signal"), axis, "#6bc5ff"),
      );
    }
    if (indicator === "kdj") chartSeries.push(
      line("K", values(indicators, "kdj_k"), axis, "#f3c969"),
      line("D", values(indicators, "kdj_d"), axis, "#6bc5ff"),
      line("J", values(indicators, "kdj_j"), axis, "#d897ff"),
    );
    if (indicator === "rsi") chartSeries.push(line("RSI14", values(indicators, "rsi_14"), axis, "#d897ff"));
    if (indicator === "obv") chartSeries.push(line("OBV", values(indicators, "obv"), axis, "#75baff"));
    if (indicator === "atr") chartSeries.push(line("ATR14", values(indicators, "atr_14"), axis, "#ffab70"));
  });
  const indicatorRows = new Map(indicators.map((row) => [row.timestamp, row as unknown as Record<string, unknown>]));
  const strategySignals = new Map<string, { name: string; color: string; offset: number; points: Array<{ name: string; coord: [string, number] }> }>();
  for (const mark of marks) {
    let endIndex = bars.length - 1;
    while (endIndex >= 0 && bars[endIndex].timestamp.slice(0, 10) > mark.date) endIndex--;
    if (endIndex < 0) continue;
    const firstIndex = mark.startDate ? bars.findIndex((bar) => bar.timestamp.slice(0, 10) >= mark.startDate!) : Math.max(0, endIndex - mark.periods + 1);
    if (firstIndex < 0 || firstIndex > endIndex || bars[endIndex].timestamp.slice(0, 10) !== mark.date) continue;
    if (mark.shape) {
      const shape = mark.shape;
      const color = shape.kind === "ascending" ? "#f3c969" : shape.kind === "descending" ? "#b49aff" : "#6bc5ff";
      chartSeries.push({name: mark.label, type:"line", data:[], z:15,
        markLine: {symbol:["none","none"], lineStyle:{color,width:2,type:"solid"},
          label:{show:true,formatter:mark.label.split(" · ")[0],color,backgroundColor:"#111517",padding:3},
          tooltip:{formatter:mark.label},
          data:[[{coord:[dates[firstIndex],shape.upper_start]},{coord:[dates[endIndex],shape.upper_end]}],
                [{coord:[dates[firstIndex],shape.lower_start]},{coord:[dates[endIndex],shape.lower_end]}]]},
        markPoint:{symbol:"circle",symbolSize:6,itemStyle:{color},label:{show:false},tooltip:{formatter:mark.label},
          data:[...shape.high_points,...shape.low_points].filter(p=>bars.some(b=>b.timestamp.slice(0,10)===p.date))
            .map(p=>({coord:[dates[bars.findIndex(b=>b.timestamp.slice(0,10)===p.date)],p.price]}))}
      });
      continue;
    }
    const markColor = mark.label.startsWith("均线重复支撑·") ? (mark.label.includes("MA250") ? "#d897ff" : "#64d8cb") : mark.strategyId ? STRATEGY_COLORS[mark.strategyId] ?? "#f3c969" : "#f3c969";
    if (mark.strategyId && (mark.label.includes(" · 命中 ") || mark.label.startsWith("海龟突破 · 首次满足"))) {
      const bearish = mark.strategyId === "shakeout" || mark.strategyId === "trend_drop";
      const offset = Object.keys(STRATEGY_COLORS).indexOf(mark.strategyId);
      const signal = strategySignals.get(mark.strategyId) ?? { name: `${mark.strategyName ?? mark.label.split(" · ")[0]}信号`, color: markColor,
        offset: (bearish ? -1 : 1) * (12 + Math.max(0, offset) * 8), points: [] };
      signal.points.push({ name: mark.label, coord: [dates[endIndex], bearish ? bars[endIndex].high : bars[endIndex].low] });
      strategySignals.set(mark.strategyId, signal);
      continue;
    }
    const metric = mark.metric;
    const isCandle = ["open", "high", "low", "close", "pattern_type", "pattern_strength", "is_limit_up"].includes(metric);
    if (isCandle) {
      const section = bars.slice(firstIndex, endIndex + 1);
      if (mark.label.startsWith("年线放量／涨停突破·")) {
        const name = mark.label.includes("·涨停突破") ? "年线涨停突破" : "年线放量突破";
        chartSeries.push({ name, type: "line", data: [], z: 20,
          markPoint: { symbol: "triangle", symbolSize: 15, symbolOffset: [0, 14],
            itemStyle: { color: markColor },
            label: { show: true, formatter: "{b}", position: "bottom", color: markColor,
              backgroundColor: "#111517", padding: [4, 6], borderRadius: 3 },
            tooltip: { formatter: mark.label },
            data: [{ name, coord: [dates[endIndex], bars[endIndex].low] }],
          },
        });
      }
      if (mark.label.startsWith("年线跌破后收复·")) {
        for (const [index, name, bullish, color] of [
          [firstIndex, "跌破年线", false, "#ff9c6e"],
          [endIndex, "收复年线", true, "#64d8cb"],
        ] as const) {
          chartSeries.push({ name, type: "line", data: [], z: 20,
            markPoint: { symbol: "triangle", symbolRotate: bullish ? 0 : 180, symbolSize: 15,
              symbolOffset: [0, bullish ? 14 : -14], itemStyle: { color },
              label: { show: true, formatter: "{b}", position: bullish ? "bottom" : "top",
                color, backgroundColor: "#111517", padding: [4, 6], borderRadius: 3 },
              tooltip: { formatter: mark.label },
              data: [{ name, coord: [dates[index], bullish ? bars[index].low : bars[index].high] }],
            },
          });
        }
      }
      const pinbar = mark.label.includes("Pinbar") && mark.label.startsWith("裸K");
      const turtle = mark.label.startsWith("海龟突破 · 首次满足");
      const confluence = mark.label.startsWith("海龟突破＋均线金叉放量；") || mark.label.startsWith("海龟突破＋均线金叉放量＋RPS强势近高点；");
      const maSupport = (mark.label.startsWith("均线重复支撑·") && mark.label.includes("本次命中")) || mark.label.startsWith("年线下影支撑·");
      const maPierce = (mark.label.startsWith("均线粘连走平·") && !mark.label.includes("突破前10日整理")) || mark.label.startsWith("阳线实体上穿除年线外全部均线");
      if (pinbar || turtle || confluence || maPierce || maSupport || mark.label.startsWith("实体低点回访：")) {
        const bullish = !pinbar || mark.label.includes("看涨");
        chartSeries.push({ name: maSupport ? "均线支撑信号" : maPierce ? "均线穿线信号" : confluence ? "组合命中信号" : turtle ? "海龟突破信号" : "裸K信号", type: "line", data: [], z: 20,
          markPoint: { symbol: "triangle", symbolRotate: bullish ? 0 : 180, symbolSize: 14,
            symbolOffset: [0, bullish ? 12 : -12],
            itemStyle: { color: markColor },
            label: { show: true, formatter: "{b}", position: bullish ? "bottom" : "top",
              color: markColor, backgroundColor: "#111517", padding: [4, 6], borderRadius: 3 },
            tooltip: { formatter: mark.label },
            data: [{ name: maSupport ? ((mark.label.includes("MA250") || mark.label.startsWith("年线下影支撑·")) ? "年线支撑" : "半年线支撑") : maPierce ? "均线穿线" : confluence ? "组合命中" : turtle ? "海龟突破" : !pinbar ? "实体低点回访" : `${mark.label.includes("双K合成") ? "双K·" : ""}${bullish ? "看涨Pinbar" : "看跌Pinbar"}`, coord: [dates[endIndex], bullish ? bars[endIndex].low : bars[endIndex].high] }],
          },
        });
      }
      chartSeries.push({ name: mark.label, type: "line", data: [], markArea: {
        silent: false, itemStyle: { color: `${markColor}18`, borderColor: markColor, borderWidth: 2 },
        label: { show: false },
        tooltip: { formatter: mark.label },
        data: [[{ name: mark.label, xAxis: firstIndex - 0.45, yAxis: mark.priceLow ?? Math.min(...section.map((bar) => bar.low)) * 0.995 },
          { xAxis: endIndex + 0.45, yAxis: mark.priceHigh ?? Math.max(...section.map((bar) => bar.high)) * 1.005 }]],
      } });
      continue;
    }
    const values = bars.map((bar) => {
      const value = indicatorRows.get(bar.timestamp)?.[metric];
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    });
    if (!values.some((value) => value !== null)) continue;
    const priceMetric = /^ma_\d+$/.test(metric) || /^(boll_|high_|low_)/.test(metric);
    const volumeMetric = metric === "volume" || /^volume_ma_/.test(metric);
    let axis = priceMetric ? 0 : volumeMetric ? 1 : grids.length;
    const knownNames: Record<string, string> = { ma_5: "MA5", ma_10: "MA10", ma_20: "MA20", ma_30: "MA30", ma_120: "MA120", ma_250: "MA250", macd: "DIF", macd_signal: "DEA", macd_hist: "MACD柱", kdj_k: "K", kdj_d: "D", kdj_j: "J", rsi_14: "RSI14", obv: "OBV", atr_14: "ATR14", volume: "成交量" };
    const existing = chartSeries.find((series) => series.name === (knownNames[metric] ?? metric));
    if (existing) axis = Number(existing.xAxisIndex ?? 0);
    if (axis === grids.length) {
      grids.push({ left: 58, right: 88, outerBoundsMode: "none" as const, top: "0%", height: "10%" });
      axes.push({ ...axes[1], gridIndex: axis });
      yAxes.push({ ...yAxes[1], gridIndex: axis });
    }
    const points = values.flatMap((value, index) => index >= firstIndex && index <= endIndex && value !== null
      ? [{ name: mark.label, coord: [dates[index], value] }] : []);
    chartSeries.push({ name: knownNames[metric] ?? mark.metricLabel ?? metric, type: "line", xAxisIndex: axis, yAxisIndex: axis,
      data: values, showSymbol: false, itemStyle: { color: markColor }, lineStyle: { color: markColor, width: 1, opacity: existing ? 0 : 1 },
      markPoint: { symbol: "circle", symbolSize: 10, itemStyle: { color: markColor, borderColor: "#fff", borderWidth: 1 },
        label: { show: false }, tooltip: { formatter: mark.label }, data: points } });
  }
  for (const signal of strategySignals.values()) chartSeries.push({ name: signal.name, type: "line", data: [], z: 20,
    markPoint: { symbol: "diamond", symbolSize: 13, symbolOffset: [0, signal.offset],
      itemStyle: { color: signal.color, borderColor: "#111517", borderWidth: 1 },
      label: { show: false }, tooltip: { formatter: (params: { data?: { name?: string } }) => params.data?.name ?? signal.name },
      data: signal.points },
  });
  if (grids.length > paneCount) {
    const available = 86 / (grids.length + 1.4);
    grids.forEach((grid, index) => {
      grid.top = `${index === 0 ? 5 : 5 + available * (index + 1.4)}%`;
      grid.height = `${available * (index === 0 ? 2.4 : 1) - 2}%`;
    });
  }
  return {
    animation: false,
    backgroundColor: "transparent",
    axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#30383c" } },
    tooltip: { trigger: "axis", formatter: (params: unknown) => candleTooltip(bars, params), axisPointer: { type: "cross" }, backgroundColor: "#111517", borderColor: "#394247", textStyle: { color: "#dfe3e1", fontSize: 11 } },
    grid: grids,
    xAxis: axes,
    yAxis: yAxes,
    dataZoom: [
      { type: "inside", xAxisIndex: Array.from({ length: grids.length }, (_, index) => index), start: initialStart / Math.max(bars.length, 1) * 100, end: 100 },
      { type: "slider", xAxisIndex: Array.from({ length: grids.length }, (_, index) => index), bottom: 4, height: 16, borderColor: "#30383c", backgroundColor: "#111517", fillerColor: "#313a3e80", handleStyle: { color: "#c8ff42" }, textStyle: { color: "#677277" } },
    ],
    series: [
      ...chartSeries,
      ...zones.map((zone) => zoneSeries(zone, bars)),
    ],
  };
}
