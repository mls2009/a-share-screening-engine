import type { EChartsOption, LineSeriesOption } from "echarts";

import type { Bar, PriceZone } from "../../types";

const compactTime = (value: string) => {
  const day = value.slice(5, 10);
  const time = value.includes("T") ? value.slice(11, 16) : "";
  return time && time !== "15:00" ? `${day} ${time}` : day;
};

export function zonePresentation(zone: PriceZone) {
  const support = zone.zone_kind === "support";
  return {
    color: support ? "#2ecf79" : "#ff5a67",
    lineType: zone.source === "auto" ? "dashed" as const : "solid" as const,
    label: `${zone.source === "auto" ? "自动" : "手动"}${support ? "支撑" : "压力"}`,
  };
}

function anchors(zone: PriceZone): Array<[string, number]> {
  if (Array.isArray(zone.anchors)) return zone.anchors;
  try { return JSON.parse(zone.anchors) as Array<[string, number]>; } catch { return []; }
}

function trendValues(zone: PriceZone, bars: Bar[]): Array<number | null> {
  const indexed = anchors(zone)
    .map(([day, price]) => [
      bars.findIndex((bar) => bar.timestamp.slice(0, 10) === day),
      price,
    ] as const)
    .filter(([index]) => index >= 0)
    .sort(([left], [right]) => left - right);
  if (indexed.length < 2) return bars.map(() => null);
  const [firstIndex, firstPrice] = indexed[0];
  const [lastIndex, lastPrice] = indexed.at(-1)!;
  if (firstIndex === lastIndex) return bars.map(() => null);
  const slope = (lastPrice - firstPrice) / (lastIndex - firstIndex);
  return bars.map((_, index) => (
    index < firstIndex ? null : Number((firstPrice + slope * (index - firstIndex)).toFixed(12))
  ));
}

function zoneSeries(zone: PriceZone, bars: Bar[]): LineSeriesOption {
  const style = zonePresentation(zone);
  const width = zone.source === "manual" ? 3 : 2;
  const base: LineSeriesOption = {
    name: style.label,
    type: "line",
    yAxisIndex: 0,
    symbol: "none",
    silent: true,
    lineStyle: { color: style.color, type: style.lineType, width, opacity: 1 },
    emphasis: { disabled: true },
    z: zone.source === "manual" ? 8 : 5,
  };
  if (zone.geometry === "trend") {
    const data = trendValues(zone, bars);
    const currentPrice = [...data].reverse().find((value) => value !== null);
    return {
      ...base,
      data,
      endLabel: {
        show: currentPrice !== undefined,
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
      silent: true,
      symbol: ["none", "none"],
      label: {
        show: true,
        position: "insideEndTop",
        formatter: `${style.label} ${zone.center_price.toFixed(2)}`,
        color: style.color,
        backgroundColor: "#0d1113e6",
        padding: [3, 5],
        borderRadius: 2,
        fontSize: 10,
      },
      lineStyle: { color: style.color, type: style.lineType, width, opacity: 1 },
      data: [{ yAxis: zone.center_price }],
    },
  };
}

export function buildChartOption(bars: Bar[], zones: PriceZone[]): EChartsOption {
  const dates = bars.map((bar) => bar.timestamp);
  const candleData = bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]);
  const volumeData = bars.map((bar) => ({
    value: bar.volume_shares,
    itemStyle: { color: bar.close >= bar.open ? "#2ecf79a8" : "#ff5a67a8" },
  }));
  return {
    animation: false,
    backgroundColor: "transparent",
    axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#30383c" } },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" }, backgroundColor: "#111517", borderColor: "#394247", textStyle: { color: "#dfe3e1", fontSize: 11 } },
    grid: [
      { left: 58, right: 22, top: 28, height: "64%" },
      { left: 58, right: 22, top: "76%", height: "15%" },
    ],
    xAxis: [
      { type: "category", data: dates, boundaryGap: true, axisLine: { lineStyle: { color: "#30383c" } }, axisLabel: { color: "#758086", hideOverlap: true, formatter: compactTime }, splitLine: { show: false }, min: "dataMin", max: "dataMax" },
      { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: "#30383c" } }, axisLabel: { show: false }, min: "dataMin", max: "dataMax" },
    ],
    yAxis: [
      { scale: true, splitLine: { lineStyle: { color: "#20272a", type: "dashed" } }, axisLabel: { color: "#758086" }, position: "right" },
      { scale: true, gridIndex: 1, splitNumber: 2, splitLine: { lineStyle: { color: "#20272a", type: "dashed" } }, axisLabel: { color: "#758086" }, position: "right" },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: Math.max(0, 100 - 12000 / Math.max(bars.length, 1)), end: 100 },
      { type: "slider", xAxisIndex: [0, 1], bottom: 4, height: 16, borderColor: "#30383c", backgroundColor: "#111517", fillerColor: "#313a3e80", handleStyle: { color: "#c8ff42" }, textStyle: { color: "#677277" } },
    ],
    series: [
      { name: "K 线", type: "candlestick", data: candleData, itemStyle: { color: "#2ecf79", color0: "#ff5a67", borderColor: "#2ecf79", borderColor0: "#ff5a67" } },
      { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: volumeData, barMaxWidth: 12 },
      ...zones.map((zone) => zoneSeries(zone, bars)),
    ],
  };
}
