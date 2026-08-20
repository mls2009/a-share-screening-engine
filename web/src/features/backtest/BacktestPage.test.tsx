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
    expect(screen.getByText("600001.SH")).toBeInTheDocument();
    expect(screen.getByText("买入")).toBeInTheDocument();
  });

  it("切换回测周期时同步入场和离场条件周期", async () => {
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
    expect(payload.entry_tree.children[0].timeframe).toBe("5m");
    expect(payload.exit_tree.children[0].timeframe).toBe("5m");
  });
});
