import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { BacktestRun, MetricSpec } from "../../types";
import { BacktestPage } from "./BacktestPage";

const allTimeframes = ["15m", "1d", "1mo", "1w", "30m", "5m", "60m"] as const;
const catalog: MetricSpec[] = [
  {
    key: "return_20", label: "近 20 周期涨跌幅", unit: "percent",
    timeframes: [...allTimeframes], operators: ["gte"],
  },
  {
    key: "volume", label: "成交量", unit: "shares",
    timeframes: [...allTimeframes], operators: ["gt"],
  },
];
const run: BacktestRun = {
  run_id: "run-1",
  result: {
    request: { symbols: ["600001.SH"] },
    metrics: {
      total_return: 12.5, annualized_return: 18.2, max_drawdown: 6.4,
      sharpe_ratio: 1.25, win_rate: 60, profit_loss_ratio: 1.8,
      trade_count: 1, total_fees: 16.2,
    },
    trades: [{
      symbol: "600001.SH", side: "buy", signal_at: "2026-08-18T15:00:00+08:00",
      timestamp: "2026-08-19T09:30:00+08:00", quantity: 1000, price: 10,
      gross: 10000, commission: 5, tax: 0, transfer_fee: 0.1, reason: "entry",
    }],
    equity_curve: [
      { timestamp: "2026-08-18T15:00:00+08:00", cash: 100000, market_value: 0, equity: 100000, drawdown: 0 },
      { timestamp: "2026-08-20T15:00:00+08:00", cash: 0, market_value: 112500, equity: 112500, drawdown: 0 },
    ],
    rejected_orders: [],
  },
};

describe("BacktestPage", () => {
  it("保留带入的非回测指标并提示，不静默替换入场条件", async () => {
    const client = {catalog:async()=>[...catalog,{key:"board",label:"板块",unit:"category",timeframes:["1d"],operators:["eq"],supported_modes:["close"],choices:[{value:"beijing",label:"北交所"}]}] as MetricSpec[],runBacktest:vi.fn()};
    render(<BacktestPage client={client} initialDraft={{symbol:"920001.BJ",tree:{kind:"condition",metric:"board",timeframe:"1d",operator:"eq",right:{kind:"constant",value:"beijing"}}}} />);
    expect(await screen.findByText(/以下指标缺少可用的历史回测支持：板块/)).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"运行策略回测"})).toBeDisabled();
  });
  it("展示完整条件目录，并在运行前提示历史支持限制", async () => {
    const client = {
      catalog: async () => [
        { ...catalog[0], timeframes: ["1d"], supported_modes: ["backtest"] },
        { ...catalog[1], supported_modes: ["close", "live"] },
      ] as unknown as MetricSpec[],
      runBacktest: async () => run,
    };
    render(<BacktestPage client={client} />);
    const selects = await screen.findAllByRole("combobox", { name: "指标" });
    expect(selects[0]).toHaveTextContent("近 20 周期涨跌幅");
    expect(selects[0]).toHaveTextContent("成交量");
  });

  it("显示中文拒单原因与数据覆盖诊断", async () => {
    const client = {
      catalog: async () => catalog,
      runBacktest: async () => ({ ...run, result: { ...run.result,
        rejected_orders: ["2026-08-19T09:30:00+08:00 600001.SH: limit_up_no_liquidity", "600001.SH: zero_volume", "600001.SH: slippage_outside_price_limits"],
        warnings: ["历史停牌状态覆盖不足"],
        diagnostics: {
          effective_start: "2026-08-18T09:30:00+08:00", effective_end: "2026-08-20T15:00:00+08:00",
          execution_bars: 3, signal_bars: 2, status_covered_bars: 1,
          status_coverage_pct: 33.33, unknown_evaluations: 4, warmup_bars: { "600001.SH": 20 },
        },
      } }),
    };
    render(<BacktestPage client={client} />);
    await userEvent.click(await screen.findByRole("button", { name: "运行策略回测" }));
    expect(await screen.findByText("开盘涨停限制买入", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("成交量为零", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("滑点价格超出涨跌停边界", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("历史停牌状态覆盖不足")).toBeInTheDocument();
    expect(screen.getByText("33.33%", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("无法判定条件：4 次")).toBeInTheDocument();
  });

  it("空权益曲线与非有限指标仍显示可用报告", async () => {
    const client = {
      catalog: async () => catalog,
      runBacktest: async () => ({ ...run, result: { ...run.result, equity_curve: [], trades: [],
        metrics: { ...run.result.metrics, total_return: NaN, max_drawdown: Infinity, sharpe_ratio: NaN },
      } }),
    };
    render(<BacktestPage client={client} />);
    await userEvent.click(await screen.findByRole("button", { name: "运行策略回测" }));
    expect(await screen.findByText("暂无有效权益数据")).toBeInTheDocument();
    expect(screen.getByText("暂无成交记录")).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByText(/NaN|Infinity/)).not.toBeInTheDocument();
  });

  it("年化收益不可计算时仍展示回测报告", async () => {
    const client = {
      catalog: async () => catalog,
      runBacktest: async () => ({ ...run, result: { ...run.result,
        metrics: { ...run.result.metrics, annualized_return: null },
      } }),
    };
    render(<BacktestPage client={client} />);
    await screen.findByRole("heading", { name: "入场条件" });
    await userEvent.click(screen.getByRole("button", { name: "运行策略回测" }));
    expect(await screen.findByText("12.50%")) .toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("用入场和离场条件树运行回测并展示指标与交易", async () => {
    const client = {
      catalog: async () => catalog,
      runBacktest: vi.fn().mockResolvedValue(run),
    };
    render(<BacktestPage client={client} />);

    expect(await screen.findByRole("heading", { name: "策略回测" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "入场条件" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "离场条件" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "运行策略回测" }));

    expect(client.runBacktest).toHaveBeenCalledOnce();
    expect(await screen.findByText("12.50%")) .toBeInTheDocument();
    expect(screen.getByRole("region", { name: "交易明细表格" })).toHaveClass("table-scroll");
    expect(screen.getByText("600001.SH")).toBeInTheDocument();
    expect(screen.getByText("买入")).toBeInTheDocument();
  });

  it("切换信号检查周期时保留各条件自己的周期", async () => {
    const client = {
      catalog: async () => catalog,
      runBacktest: vi.fn().mockResolvedValue(run),
    };
    render(<BacktestPage client={client} />);

    await screen.findByRole("heading", { name: "入场条件" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "回测周期" }), "5m");
    for (const metric of screen.getAllByRole("combobox", { name: "指标" })) {
      await userEvent.selectOptions(metric, "volume");
    }
    await userEvent.click(screen.getByRole("button", { name: "运行策略回测" }));

    const payload = client.runBacktest.mock.calls[0][0];
    expect(payload.timeframe).toBe("5m");
    expect(payload.entry_tree.children[0].timeframe).toBe("1d");
    expect(payload.exit_tree.children[0].timeframe).toBe("1d");
  });
});

it("runs the latest watchlist group members independently and continues after failure", async () => {
  const { api } = await import("../../api");
  const groups = vi.spyOn(api, "watchGroups").mockResolvedValue([{ id: "group-1", name: "芯片观察" }]);
  const stocks = vi.spyOn(api, "watchlist").mockResolvedValue([
    { symbol: "600001.SH", name: "股票一", sources: [], groups: [{ id: "group-1", name: "芯片观察" }] },
    { symbol: "600002.SH", name: "股票二", sources: [], groups: [{ id: "group-1", name: "芯片观察" }] },
    { symbol: "600003.SH", name: "其他组股票", sources: [], groups: [] },
  ]);
  const runBacktest = vi.fn().mockRejectedValueOnce(new Error("历史数据不足")).mockResolvedValueOnce(run);
  try {
    render(<BacktestPage client={{ catalog: async () => catalog, runBacktest }} />);
    await userEvent.selectOptions(screen.getByLabelText("回测股票来源"), "group");
    await screen.findByRole("option", { name: "芯片观察 · 2 只" });
    await userEvent.selectOptions(screen.getByLabelText("回测自选分组"), "group-1");
    await userEvent.selectOptions(screen.getByLabelText("回测方式"), "individual");
    await userEvent.click(screen.getByRole("button", { name: "运行策略回测" }));
    expect(await screen.findByText("批量回测结束，共处理 2 只股票")).toBeInTheDocument();
    expect(stocks).toHaveBeenCalledTimes(2);
    expect(runBacktest).toHaveBeenNthCalledWith(1, expect.objectContaining({ symbols: ["600001.SH"] }));
    expect(runBacktest).toHaveBeenNthCalledWith(2, expect.objectContaining({ symbols: ["600002.SH"] }));
    expect(screen.getByText("历史数据不足")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看 600002.SH 报告" })).toBeInTheDocument();
  } finally { groups.mockRestore(); stocks.mockRestore(); }
});

it("deduplicates a multi-stock portfolio into one shared-capital request", async () => {
  const runBacktest = vi.fn().mockResolvedValue(run);
  render(<BacktestPage client={{ catalog: async () => catalog, runBacktest }} />);
  const input = screen.getByLabelText("回测证券代码");
  await userEvent.clear(input);
  await userEvent.type(input, "600001.SH,600002.SH,600001.SH");
  await userEvent.click(screen.getByRole("button", { name: "运行策略回测" }));
  expect(runBacktest).toHaveBeenCalledOnce();
  expect(runBacktest).toHaveBeenCalledWith(expect.objectContaining({ symbols: ["600001.SH", "600002.SH"] }));
});

it("imports entry JSON with its timeframe and preserves it after malformed JSON", async () => {
  const { api } = await import("../../api");
  const validate = vi.spyOn(api, "validateScreen").mockResolvedValue({ valid: true, errors: [] });
  const runBacktest = vi.fn().mockResolvedValue(run);
  try {
    render(<BacktestPage client={{ catalog: async () => catalog, runBacktest }} />);
    await screen.findAllByLabelText("指标");
    await userEvent.click(screen.getByRole("button", { name: "导入入场 JSON" }));
    const tree = { kind: "condition", metric: "return_20", timeframe: "1w", operator: "gte", right: { kind: "constant", value: 45, unit: "percent" } };
    await userEvent.click(screen.getByLabelText("入场条件 JSON"));
    await userEvent.paste(JSON.stringify(tree));
    await userEvent.click(screen.getByRole("button", { name: "应用入场 JSON" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "导入入场 JSON" }));
    await userEvent.clear(screen.getByLabelText("入场条件 JSON"));
    await userEvent.click(screen.getByLabelText("入场条件 JSON"));
    await userEvent.paste("{bad");
    await userEvent.click(screen.getByRole("button", { name: "应用入场 JSON" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "取消" }));
    await userEvent.click(screen.getByRole("button", { name: "运行策略回测" }));
    expect(runBacktest).toHaveBeenCalledWith(expect.objectContaining({ timeframe: "1d", entry_tree: expect.objectContaining({ children: [tree] }) }));
  } finally { validate.mockRestore(); }
});
