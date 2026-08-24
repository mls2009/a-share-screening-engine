import { act, render } from "@testing-library/react";

import type { Bar } from "../../types";
import { StockChart } from "./StockChart";

const echartsMock = vi.hoisted(() => {
  const chartHandlers = new Map<string, (params: unknown) => void>();
  const zrHandlers = new Map<string, (params: unknown) => void>();
  const zr = {
    on: vi.fn((name: string, handler: (params: unknown) => void) => zrHandlers.set(name, handler)),
    off: vi.fn((name: string, handler: (params: unknown) => void) => {
      if (zrHandlers.get(name) === handler) zrHandlers.delete(name);
    }),
  };
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    convertFromPixel: vi.fn(),
    dispatchAction: vi.fn(),
    getZr: vi.fn(() => zr),
    on: vi.fn((name: string, handler: (params: unknown) => void) => chartHandlers.set(name, handler)),
    off: vi.fn((name: string, handler: (params: unknown) => void) => {
      if (chartHandlers.get(name) === handler) chartHandlers.delete(name);
    }),
  };
  return { chart, chartHandlers, init: vi.fn(() => chart), use: vi.fn(), zr, zrHandlers };
});

vi.mock("echarts/core", () => ({
  init: echartsMock.init,
  use: echartsMock.use,
}));

const bars: Bar[] = [
  { symbol: "600001.SH", timestamp: "2026-08-18T15:00:00+08:00", open: 9.8, high: 10.2, low: 9.7, close: 10, volume_shares: 900, amount_cny: 9000 },
  { symbol: "600001.SH", timestamp: "2026-08-19T15:00:00+08:00", open: 10, high: 11, low: 9.8, close: 10.8, volume_shares: 1000, amount_cny: 10800 },
  { symbol: "600001.SH", timestamp: "2026-08-20T15:00:00+08:00", open: 10.8, high: 11.2, low: 10.5, close: 10.6, volume_shares: 1800, amount_cny: 19080 },
];

beforeEach(() => {
  vi.clearAllMocks();
  echartsMock.chartHandlers.clear();
  echartsMock.zrHandlers.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("图表容器尺寸变化时重新计算画布", () => {
  let notify: (() => void) | undefined;
  const observe = vi.fn();
  const disconnect = vi.fn();
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { notify = callback; }
    observe = observe;
    disconnect = disconnect;
  });

  const { unmount } = render(<StockChart bars={bars} zones={[]} />);
  expect(observe).toHaveBeenCalled();
  echartsMock.chart.resize.mockClear();
  act(() => notify?.());
  expect(echartsMock.chart.resize).toHaveBeenCalledTimes(1);

  unmount();
  expect(disconnect).toHaveBeenCalledTimes(1);
});

it("将自动趋势线的鼠标位置换算为边界内数据索引并显示 item tooltip", () => {
  echartsMock.chart.convertFromPixel.mockReturnValue([99.6, 10.4]);
  render(<StockChart bars={bars} zones={[]} />);

  const mousemove = echartsMock.chartHandlers.get("mousemove");
  expect(mousemove).toBeTypeOf("function");
  if (!mousemove) return;
  act(() => mousemove({
    seriesType: "line",
    selfType: "line",
    seriesIndex: 3,
    event: { offsetX: 120, offsetY: 80 },
  }));

  expect(echartsMock.chart.convertFromPixel).toHaveBeenCalledWith({ gridIndex: 0 }, [120, 80]);
  expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith({
    type: "showTip",
    seriesIndex: 3,
    dataIndex: 2,
  });
});

it("离开自动趋势线时隐藏 item tooltip，其他图形的 mouseout 不干扰 axis tooltip", () => {
  const { unmount } = render(<StockChart bars={bars} zones={[]} />);
  const mouseout = echartsMock.chartHandlers.get("mouseout");
  expect(mouseout).toBeTypeOf("function");
  if (!mouseout) return;

  act(() => mouseout({ seriesType: "line", selfType: "line", seriesIndex: 3 }));
  expect(echartsMock.chart.dispatchAction).toHaveBeenCalledWith({ type: "hideTip" });

  echartsMock.chart.dispatchAction.mockClear();
  act(() => mouseout({ seriesType: "candlestick", selfType: "series", seriesIndex: 0 }));
  expect(echartsMock.chart.dispatchAction).not.toHaveBeenCalled();

  const mousemove = echartsMock.chartHandlers.get("mousemove");
  expect(mousemove).toBeTypeOf("function");
  if (!mousemove) return;
  unmount();
  expect(echartsMock.chart.off).toHaveBeenCalledWith("mousemove", mousemove);
  expect(echartsMock.chart.off).toHaveBeenCalledWith("mouseout", mouseout);
});

it("忽略手动标签形状和无效的系列或坐标事件", () => {
  render(<StockChart bars={bars} zones={[]} />);
  const mousemove = echartsMock.chartHandlers.get("mousemove");
  expect(mousemove).toBeTypeOf("function");
  if (!mousemove) return;

  act(() => mousemove({ seriesType: "line", selfType: "label", seriesIndex: 3, event: { offsetX: 120, offsetY: 80 } }));
  act(() => mousemove({ seriesType: "line", selfType: "line", seriesIndex: -1, event: { offsetX: 120, offsetY: 80 } }));
  act(() => mousemove({ seriesType: "candlestick", selfType: "line", seriesIndex: 0, event: { offsetX: 120, offsetY: 80 } }));
  expect(echartsMock.chart.convertFromPixel).not.toHaveBeenCalled();

  echartsMock.chart.convertFromPixel.mockReturnValue([Number.NaN, 10]);
  act(() => mousemove({ seriesType: "line", selfType: "line", seriesIndex: 3, event: { offsetX: 120, offsetY: 80 } }));
  expect(echartsMock.chart.dispatchAction).not.toHaveBeenCalled();
});
