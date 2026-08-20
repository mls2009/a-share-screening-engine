import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MetricSpec, ScreenRunResult } from "../../types";
import { ScreenerPage, type ScreenerClient } from "./ScreenerPage";

const catalog: MetricSpec[] = [
  { key: "return_20", label: "20周期涨跌幅", unit: "percent", timeframes: ["1d"], operators: ["gte"] },
];
const result: ScreenRunResult = {
  run_id: "run-1",
  status: "completed",
  universe_size: 5547,
  realtime_covered: 0,
  failed_batches: 0,
  matches: [{
    symbol: "600001.SH",
    rank: 1,
    features: { name: "测试股份", close: 12.5, return_20: 35.2, volume_ratio_20: 1.8 },
    explanation: { path: "root", result: "true", actual: 35.2, expected: 30, unit: "percent", children: [] },
  }],
};

function client(): ScreenerClient {
  return { catalog: async () => catalog, runScreen: async () => result };
}

describe("ScreenerPage", () => {
  it("运行筛选并展示证券名称、关键数值和解释", async () => {
    render(<ScreenerPage client={client()} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");

    await userEvent.click(screen.getByRole("button", { name: "运行全市场筛选" }));

    expect((await screen.findAllByText("测试股份")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("35.20%")).toBeInTheDocument();
    expect(screen.getByText("实际 35.2 / 期望 30")).toBeInTheDocument();
    expect(screen.getByText("5,547")).toBeInTheDocument();
  });

  it("可切换实时模式并打开命中股票 K 线", async () => {
    const calls: object[] = [];
    const open: string[] = [];
    const fake: ScreenerClient = {
      catalog: async () => catalog,
      runScreen: async (payload) => { calls.push(payload); return result; },
    };
    render(<ScreenerPage client={fake} onOpenChart={(symbol) => open.push(symbol)} />);
    await screen.findByLabelText("指标");
    await userEvent.selectOptions(screen.getByLabelText("筛选模式"), "live");
    await userEvent.click(screen.getByRole("button", { name: "运行全市场筛选" }));
    await userEvent.click(await screen.findByRole("button", { name: "查看 600001.SH K 线" }));

    await waitFor(() => expect(calls[0]).toMatchObject({ mode: "live" }));
    expect(open).toEqual(["600001.SH"]);
  });
});
