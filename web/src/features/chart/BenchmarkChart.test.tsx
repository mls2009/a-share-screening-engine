import { render } from "@testing-library/react";

import type { BenchmarkComparison } from "../../types";
import { BenchmarkChart } from "./BenchmarkChart";

const echartsMock = vi.hoisted(() => ({
  chart: { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() },
  init: vi.fn(),
  use: vi.fn(),
}));
echartsMock.init.mockReturnValue(echartsMock.chart);

vi.mock("echarts/core", () => ({ init: echartsMock.init, use: echartsMock.use }));

const comparison: BenchmarkComparison = {
  stock_symbol: "600001.SH",
  stock_name: "股票一",
  benchmark_symbol: "000001.SH",
  benchmark_name: "上证指数",
  points: [
    { timestamp: "2026-08-20T15:00:00+08:00", stock_return_pct: 0, benchmark_return_pct: 0, relative_pct: 0 },
  ],
};

it("创建可响应尺寸变化的大盘比较图并在卸载时释放", () => {
  const observe = vi.fn();
  const disconnect = vi.fn();
  vi.stubGlobal("ResizeObserver", class {
    observe = observe;
    disconnect = disconnect;
  });

  const { unmount } = render(<BenchmarkChart comparison={comparison} />);

  expect(echartsMock.init).toHaveBeenCalled();
  expect(echartsMock.chart.setOption).toHaveBeenCalledWith(expect.objectContaining({
    series: expect.any(Array),
  }), true);
  expect(observe).toHaveBeenCalled();
  unmount();
  expect(disconnect).toHaveBeenCalled();
  expect(echartsMock.chart.dispose).toHaveBeenCalled();
});
