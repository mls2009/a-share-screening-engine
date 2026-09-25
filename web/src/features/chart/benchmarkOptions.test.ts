import type { BenchmarkComparison } from "../../types";
import { buildBenchmarkOption } from "./benchmarkOptions";

const comparison: BenchmarkComparison = {
  stock_symbol: "600001.SH",
  stock_name: "股票一",
  benchmark_symbol: "000001.SH",
  benchmark_name: "上证指数",
  points: [
    { timestamp: "2026-08-19T15:00:00+08:00", stock_return_pct: 0, benchmark_return_pct: 0, relative_pct: 0, stock_period_pct: null, benchmark_period_pct: null, relative_period_pct: null },
    { timestamp: "2026-08-20T15:00:00+08:00", stock_return_pct: 10, benchmark_return_pct: 5, relative_pct: 5, stock_period_pct: -10, benchmark_period_pct: -8, relative_period_pct: -2 },
  ],
};

it("保持股票和大盘两条累计走势，悬停使用独立的当日数据", () => {
  const option = buildBenchmarkOption(comparison);
  const series = option.series as Array<Record<string, unknown>>;
  const yAxis = option.yAxis as { axisLabel: { formatter: (value: number) => string } };

  expect(series).toHaveLength(2);
  expect(series[0]).toMatchObject({
    name: "股票一", type: "line", data: [0, 10], lineStyle: { color: "#c8ff42" },
  });
  expect(series[1]).toMatchObject({
    name: "上证指数", type: "line", data: [0, 5], lineStyle: { color: "#6bc5ff" },
  });
  expect(yAxis.axisLabel.formatter(5)).toBe("+5.00%");
  expect(yAxis.axisLabel.formatter(-2.5)).toBe("-2.50%");
});

it("提示框展示双方涨跌幅和相对强弱", () => {
  const option = buildBenchmarkOption(comparison);
  const tooltip = option.tooltip as { formatter: (params: unknown) => string };
  const text = tooltip.formatter([{ dataIndex: 1 }]);

  expect(text).toContain("股票一 当日涨跌：-10.00%");
  expect(text).toContain("上证指数 当日涨跌：-8.00%");
  expect(text).toContain("当日跑输大盘 2.00 个百分点");
  expect(text).toContain("股票一累计 +10.00%");
});
