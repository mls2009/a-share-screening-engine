import type { EChartsOption } from "echarts";

import type { BenchmarkComparison } from "../../types";

const percent = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
const points = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}`;

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[character] ?? character);
}

export function buildBenchmarkOption(comparison: BenchmarkComparison): EChartsOption {
  const tooltip = (params: unknown) => {
    if (!Array.isArray(params) || typeof params[0]?.dataIndex !== "number") return "";
    const point = comparison.points[params[0].dataIndex];
    if (!point) return "";
    const relative = point.relative_pct >= 0
      ? `跑赢 ${points(point.relative_pct)} 个百分点`
      : `跑输 ${points(Math.abs(point.relative_pct))} 个百分点`;
    return [
      escapeHtml(new Date(point.timestamp).toLocaleString("zh-CN")),
      `${escapeHtml(comparison.stock_name)} ${percent(point.stock_return_pct)}`,
      `${escapeHtml(comparison.benchmark_name)} ${percent(point.benchmark_return_pct)}`,
      relative,
    ].join("<br/>");
  };

  return {
    animation: false,
    backgroundColor: "transparent",
    color: ["#c8ff42", "#6bc5ff"],
    legend: {
      top: 8,
      textStyle: { color: "#aab4b7", fontSize: 11 },
      data: [comparison.stock_name, comparison.benchmark_name],
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: tooltip,
      backgroundColor: "#111517",
      borderColor: "#394247",
      textStyle: { color: "#dfe3e1", fontSize: 11 },
    },
    grid: { left: 54, right: 24, top: 50, bottom: 50 },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: comparison.points.map((point) => point.timestamp),
      axisLine: { lineStyle: { color: "#30383c" } },
      axisLabel: { color: "#758086", hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#758086", formatter: percent },
      splitLine: { lineStyle: { color: "#20272a", type: "dashed" } },
    },
    dataZoom: [
      { type: "inside", start: Math.max(0, 100 - 12_000 / Math.max(comparison.points.length, 1)), end: 100 },
      { type: "slider", bottom: 5, height: 16, borderColor: "#30383c", backgroundColor: "#111517", fillerColor: "#313a3e80", handleStyle: { color: "#c8ff42" }, textStyle: { color: "#677277" } },
    ],
    series: [
      {
        name: comparison.stock_name,
        type: "line",
        symbol: "none",
        data: comparison.points.map((point) => point.stock_return_pct),
        lineStyle: { color: "#c8ff42", width: 2 },
        markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "#4c565a", type: "dashed" }, data: [{ yAxis: 0 }] },
      },
      {
        name: comparison.benchmark_name,
        type: "line",
        symbol: "none",
        data: comparison.points.map((point) => point.benchmark_return_pct),
        lineStyle: { color: "#6bc5ff", width: 2 },
      },
    ],
  };
}
