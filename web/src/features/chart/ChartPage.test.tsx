import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Bar, BenchmarkComparison, PriceZone } from "../../types";
import { ChartPage, type ChartClient } from "./ChartPage";
import type { StockChartProps } from "./StockChart";

const bars: Bar[] = [
  { symbol: "600001.SH", timestamp: "2026-08-19T15:00:00+08:00", open: 10, high: 11, low: 9.8, close: 10.8, volume_shares: 1000, amount_cny: 10800 },
  { symbol: "600001.SH", timestamp: "2026-08-20T15:00:00+08:00", open: 10.8, high: 11.2, low: 10.5, close: 10.6, volume_shares: 1800, amount_cny: 19080 },
];
const manual: PriceZone = {
  zone_id: "manual-1", timeframe: "1d", as_of_date: "2026-08-20", zone_kind: "support",
  geometry: "trend", lower_price: 10.9, center_price: 11, upper_price: 11.1,
  slope: .05, intercept: 10, anchors: [["2026-08-01", 10], ["2026-08-20", 11]],
  strength: 1, touches: 2, source: "manual", reappeared: false,
};
const automatic: PriceZone = {
  ...manual,
  zone_id: "auto-1",
  zone_kind: "resistance",
  geometry: "horizontal",
  lower_price: 11.7,
  center_price: 11.8,
  upper_price: 11.9,
  slope: null,
  intercept: null,
  anchors: [["2026-08-01", 11.8]],
  source: "auto",
};
const automaticUptrend: PriceZone = {
  ...manual,
  zone_id: "auto-uptrend-1",
  zone_kind: "uptrend",
  source: "auto",
};
const automaticDowntrend: PriceZone = {
  ...manual,
  zone_id: "auto-downtrend-1",
  zone_kind: "downtrend",
  source: "auto",
};

function FakeChart({ bars: chartBars, zones, selectedIndicators, onAnchor, onBarSelect }: StockChartProps) {
  return <div><span>{chartBars.length} 根 K 线 / {zones.length} 条线</span><span>指标：{selectedIndicators?.join(",")}</span><button onClick={() => onAnchor?.({ date: "2026-08-01", price: 10 })}>锚点1</button><button onClick={() => onAnchor?.({ date: "2026-08-20", price: 11 })}>锚点2</button>{chartBars.map((bar) => <button key={bar.timestamp} onClick={() => onBarSelect?.(bar)}>选择 {bar.timestamp.slice(0, 10)} K线</button>)}</div>;
}

function FakeBenchmarkChart({ comparison }: { comparison: BenchmarkComparison }) {
  return <div role="img" aria-label="大盘走势对比图">{comparison.stock_name} 对比 {comparison.benchmark_name}</div>;
}

const comparison: BenchmarkComparison = {
  stock_symbol: "600001.SH",
  stock_name: "股票一",
  benchmark_symbol: "000001.SH",
  benchmark_name: "上证指数",
  points: [
    { timestamp: "2026-08-20T15:00:00+08:00", stock_return_pct: 0, benchmark_return_pct: 0, relative_pct: 0 },
  ],
};

it("后台补齐涨跌停数据后重新读取并更新 K 线颜色", async () => {
  let requests = 0;
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => {
      requests++;
      return [{ ...bars[0], limit_state: requests > 1 ? "up" : null, limit_data_pending: requests === 1 }];
    },
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  const LimitChart = ({ bars: chartBars }: StockChartProps) => <div>{chartBars[0]?.limit_state === "up" ? "涨停已着色" : "涨停未着色"}</div>;
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={LimitChart} showOverview={false} />);
  expect(await screen.findByText("涨停未着色")).toBeVisible();
  expect(await screen.findByText("涨停已着色", {}, { timeout: 5000 })).toBeVisible();
  expect(requests).toBe(2);
});

it("点击日 K 后选择15分钟并可返回日线", async () => {
  const requests: Array<[string, string, string, string]> = [];
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async (...args) => { requests.push(args); return bars; },
    indicators: async () => [],
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  await userEvent.click(await screen.findByRole("button", { name: "选择 2026-08-20 K线" }));
  await userEvent.click(screen.getByRole("button", { name: "查看15分钟" }));

  await waitFor(() => expect(requests.at(-1)).toEqual([
    "600001.SH", "15m", "2026-08-20", "2026-08-20",
  ]));
  expect(screen.getByText("日线")).toBeVisible();
  expect(screen.getByText("2026-08-20")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "返回日线" }));
  await waitFor(() => expect(requests.at(-1)?.[1]).toBe("1d"));
});

it("大盘对比使用同区间折线并在关闭后恢复指标和画线工具", async () => {
  const comparisonRequests: unknown[][] = [];
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    indicators: async () => [],
    zones: async () => [],
    benchmarkComparison: async (...args) => { comparisonRequests.push(args); return comparison; },
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  render(
    <ChartPage
      initialSymbol="600001.SH"
      client={client}
      Chart={FakeChart}
      ComparisonChart={FakeBenchmarkChart}
    />,
  );

  expect(await screen.findByText("指标：ma")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "开启大盘对比" }));

  expect(await screen.findByRole("img", { name: "大盘走势对比图" })).toBeVisible();
  expect(comparisonRequests[0]).toEqual([
    "600001.SH", "1d", expect.any(String), expect.any(String), undefined, undefined,
  ]);
  expect(screen.queryByRole("button", { name: "画支撑" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "删除指标 MA 5/10/20/30/120/250" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "关闭大盘对比" }));
  expect(await screen.findByText("指标：ma")).toBeVisible();
  expect(screen.getByRole("button", { name: "画支撑" })).toBeVisible();
});

it("缺少行情时可同步当前窗口并自动重新加载", async () => {
  let synced = false;
  const syncRequests: object[] = [];
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => synced ? bars : [],
    indicators: async () => [],
    zones: async () => [],
    syncChartData: async (_symbol, payload) => {
      syncRequests.push(payload);
      synced = true;
      return { stock_bars: bars.length, benchmark_bars: 0 };
    },
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  await userEvent.click(await screen.findByRole("button", { name: "同步当前时段数据" }));

  expect(syncRequests[0]).toMatchObject({ timeframe: "1d", include_benchmark: false });
  expect(await screen.findByText("2 根 K 线 / 0 条线")).toBeVisible();
});

it("默认显示 MA，可从菜单添加和移除副图指标", async () => {
  const requested: string[][] = [];
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    indicators: async (...args) => { requested.push(args); return []; },
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  expect(await screen.findByText("指标：ma")).toBeInTheDocument();
  expect(requested[0]).toEqual(["600001.SH", "1d", expect.any(String), expect.any(String)]);
  await userEvent.click(screen.getByRole("button", { name: "+ 指标" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "MACD" }));
  expect(screen.getByText("指标：ma,macd")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "删除指标 MACD" }));
  expect(screen.getByText("指标：ma")).toBeInTheDocument();
});

it("全屏看盘进入退出时保留当前指标", async () => {
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    indicators: async () => [],
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  expect(await screen.findByText("指标：ma")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "+ 指标" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "MACD" }));
  await userEvent.click(screen.getByRole("button", { name: "全屏看盘" }));

  expect(screen.getByTestId("chart-desk")).toHaveClass("is-fullscreen");
  expect(screen.getByText("指标：ma,macd")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "退出全屏" }));
  expect(screen.getByTestId("chart-desk")).not.toHaveClass("is-fullscreen");
  expect(screen.getByText("指标：ma,macd")).toBeInTheDocument();
});

it("切换周期、用两个锚点保存手动趋势支撑并可删除自动和手动线", async () => {
  const created: object[] = [];
  const deleted: string[] = [];
  let stored: PriceZone[] = [automatic];
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    zones: async () => stored,
    createManualZone: async (_symbol, payload) => { created.push(payload); stored = [...stored, manual]; return manual; },
    deleteZone: async (_symbol, id) => { deleted.push(id); stored = stored.filter((zone) => zone.zone_id !== id); },
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  expect(await screen.findByText("2 根 K 线 / 1 条线")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "画支撑" }));
  await userEvent.click(screen.getByRole("button", { name: "趋势线" }));
  await userEvent.click(screen.getByRole("button", { name: "锚点1" }));
  await userEvent.click(screen.getByRole("button", { name: "锚点2" }));

  await waitFor(() => expect(created).toHaveLength(1));
  expect(created[0]).toMatchObject({ zone_kind: "support", geometry: "trend" });
  expect(screen.getByText("支撑压力线")).toBeInTheDocument();
  expect(await screen.findByText("手动支撑")).toBeInTheDocument();
  expect(screen.getByText("11.00")).toBeInTheDocument();
  expect(screen.queryByText("10.90 — 11.10")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "删除自动水平压力 auto-1" }));
  await userEvent.click(screen.getByRole("button", { name: "删除手动支撑 manual-1" }));
  expect(deleted).toEqual(["auto-1", "manual-1"]);
});

it("删除失败时保留线并显示错误", async () => {
  let calls = 0;
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    zones: async () => [automatic],
    createManualZone: async () => manual,
    deleteZone: async () => { calls += 1; throw new Error("删除失败"); },
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  expect(await screen.findByText("2 根 K 线 / 1 条线")).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "删除自动水平压力 auto-1" });
  await userEvent.click(button);

  expect(await screen.findByRole("alert")).toHaveTextContent("删除失败");
  expect(screen.getByText("2 根 K 线 / 1 条线")).toBeInTheDocument();
  expect(button).toBeEnabled();
  await userEvent.click(button);
  await waitFor(() => expect(calls).toBe(2));
});

it("自动趋势线按方向展示名称并用于删除按钮", async () => {
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    zones: async () => [automaticUptrend, automaticDowntrend],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  expect(await screen.findByText("自动上升趋势线")).toBeInTheDocument();
  expect(screen.getByText("自动下降趋势线")).toBeInTheDocument();
  expect(screen.queryByText("自动趋势支撑")).not.toBeInTheDocument();
  expect(screen.queryByText("自动趋势压力")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "删除自动上升趋势线 auto-uptrend-1" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "删除自动下降趋势线 auto-downtrend-1" })).toBeInTheDocument();
});

it("删除请求完成前禁止重复提交", async () => {
  let calls = 0;
  let finish!: () => void;
  const client: ChartClient = {
    searchSymbols: async () => [],
    bars: async () => bars,
    zones: async () => [automatic],
    createManualZone: async () => manual,
    deleteZone: async () => {
      calls += 1;
      await new Promise<void>((resolve) => { finish = resolve; });
    },
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  const button = await screen.findByRole("button", { name: "删除自动水平压力 auto-1" });
  await userEvent.dblClick(button);

  expect(calls).toBe(1);
  expect(button).toBeDisabled();
  finish();
  await waitFor(() => expect(button).not.toBeInTheDocument());
});

it("支持中文模糊搜索 ETF 并打开完整代码", async () => {
  const requestedSymbols: string[] = [];
  const client: ChartClient & {
    searchSymbols(query: string): Promise<Array<{ symbol: string; name: string; exchange: string; instrument_type: "etf" }>>;
  } = {
    bars: async (symbol) => { requestedSymbols.push(symbol); return bars; },
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
    searchSymbols: async (query) => query.includes("创业板") ? [{
      symbol: "159558.SZ", name: "创业板中盘ETF", exchange: "SZ", instrument_type: "etf",
    }] : [],
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  const input = screen.getByRole("textbox");
  await userEvent.clear(input);
  await userEvent.type(input, "创业板");
  await userEvent.click(await screen.findByRole("option", { name: /创业板中盘ETF.*159558\.SZ.*ETF/ }));

  await waitFor(() => expect(requestedSymbols).toContain("159558.SZ"));
  expect(input).toHaveValue("创业板中盘ETF 159558.SZ");
});

it("直接提交六位代码时自动解析交易所后缀", async () => {
  const requestedSymbols: string[] = [];
  const client: ChartClient & {
    searchSymbols(query: string): Promise<Array<{ symbol: string; name: string; exchange: string; instrument_type: "etf" }>>;
  } = {
    bars: async (symbol) => { requestedSymbols.push(symbol); return bars; },
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
    searchSymbols: async () => [{
      symbol: "159558.SZ", name: "创业板中盘ETF", exchange: "SZ", instrument_type: "etf",
    }],
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  const input = screen.getByRole("textbox");
  await userEvent.clear(input);
  await userEvent.type(input, "159558");
  await userEvent.click(screen.getByRole("button", { name: "打开" }));

  await waitFor(() => expect(requestedSymbols).toContain("159558.SZ"));
});

it("无搜索结果时保留当前图表", async () => {
  const client: ChartClient & {
    searchSymbols(query: string): Promise<[]>;
  } = {
    bars: async () => bars,
    zones: async () => [],
    createManualZone: async () => manual,
    deleteZone: async () => undefined,
    searchSymbols: async () => [],
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  const input = screen.getByRole("textbox");
  await userEvent.clear(input);
  await userEvent.type(input, "不存在的ETF");
  await userEvent.click(screen.getByRole("button", { name: "打开" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("未找到匹配的证券");
  expect(screen.getByText("600001.SH")).toBeInTheDocument();
});

it("辅助数据未返回时先显示K线", async () => {
  const client: ChartClient = {
    searchSymbols: async () => [], bars: async () => bars,
    zones: () => new Promise(() => {}), indicators: () => new Promise(() => {}),
    createManualZone: async () => manual, deleteZone: async () => undefined,
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);
  expect(await screen.findByText("2 根 K 线 / 0 条线")).toBeInTheDocument();
  expect(screen.queryByText("正在读取行情…")).not.toBeInTheDocument();
});

it('历史入选依据不截断最新行情，并可指定日期后切回最新', async () => {
  const requests: Array<[string,string,string,string]> = [];
  const client: ChartClient = {
    searchSymbols: async()=>[], bars:async(...args)=>{requests.push(args);return bars;},
    indicators:async()=>[], zones:async()=>[],createManualZone:async()=>manual,deleteZone:async()=>undefined,
  };
  const source = {as_of:'2026-06-30',marks:[],tree:{kind:'group',logic:'and',children:[]}} as unknown as import('../watchlist/model').WatchSource;
  render(<ChartPage initialSymbol="600001.SH" watchSource={source} client={client} Chart={FakeChart}/>);
  await waitFor(()=>expect(requests.length).toBeGreaterThan(0));
  const latestEnd=requests.at(-1)![3];
  expect(latestEnd).not.toBe(source.as_of);
  expect(screen.getByLabelText('K线数据日期模式')).toHaveValue('latest');
  await userEvent.selectOptions(screen.getByLabelText('K线数据日期模式'),'history');
  const {fireEvent}=await import('@testing-library/react');
  fireEvent.change(screen.getByLabelText('K线数据日期'),{target:{value:'2026-06-30'}});
  await waitFor(()=>expect(requests.at(-1)?.[3]).toBe('2026-06-30'));
  await userEvent.selectOptions(screen.getByLabelText('K线数据日期模式'),'latest');
  await waitFor(()=>expect(requests.at(-1)?.[3]).toBe(latestEnd));
});

it("三个形态按需识别当前股票，切换开关复用结果并传入图表", async () => {
  const shape = {kind: "ascending" as const, upper_start: 20, upper_end: 20, lower_start: 10, lower_end: 15, high_points: [], low_points: []};
  const marks = ["ascending", "descending", "range"].map(kind => ({metric: "close", timeframe: "1d" as const, date: "2026-08-20", startDate: "2026-06-01", periods: 50, label: kind, shape: {...shape, kind: kind as "ascending" | "descending" | "range"}}));
  let calls = 0;
  const client: ChartClient = {
    searchSymbols: async () => [], bars: async () => bars, indicators: async () => [], zones: async () => [],
    createManualZone: async () => manual, deleteZone: async () => undefined,
    chartShapes: async (symbol) => { expect(symbol).toBe("600001.SH"); calls++; return {marks, data_date: "2026-08-20"}; },
  };
  function ShapeChart({marks: shown}: StockChartProps) { return <div data-testid="shape-marks">{shown?.map(m => m.label).join(",")}</div>; }
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={ShapeChart} />);
  await screen.findByTestId("shape-marks");
  expect(calls).toBe(0);
  await userEvent.click(screen.getByRole("button", {name: "上升三角形"}));
  await waitFor(() => expect(screen.getByTestId("shape-marks")).toHaveTextContent("ascending"));
  await userEvent.click(screen.getByRole("button", {name: "下降三角形"}));
  await userEvent.click(screen.getByRole("button", {name: "震荡区间"}));
  expect(screen.getByTestId("shape-marks")).toHaveTextContent("ascending,descending,range");
  await userEvent.click(screen.getByRole("button", {name: "✓ 上升三角形"}));
  expect(screen.getByTestId("shape-marks")).toHaveTextContent("descending,range");
  expect(screen.getByTestId("shape-marks")).not.toHaveTextContent("ascending");
  expect(calls).toBe(1);
});

it('海龟图表请求包含筛选区间之前的真实参考窗口', async () => {
  const client: ChartClient = {searchSymbols:async()=>[],bars:vi.fn(async()=>bars),zones:async()=>[],createManualZone:async()=>manual,deleteZone:async()=>{}};
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} showOverview={false} watchSource={{run_id:'sq',as_of:'2026-09-22',mode:'sequoia',tree:{kind:'group'},explanation:{path:'root',result:'true',children:[]},marks:[{metric:'close',timeframe:'1d',date:'2024-09-27',startDate:'2024-09-27',periods:1,label:'海龟突破 · 首次满足 2024-09-27'}],groups:[{id:'turtle',occurrences:[{date:'2024-09-27',checks:[{mark:{date:'2024-09-27',startDate:'2024-08-28'}}]}]}]}} />);
  await waitFor(()=>expect(client.bars).toHaveBeenCalledWith('600001.SH','1d','2024-08-28',expect.any(String)));
});
