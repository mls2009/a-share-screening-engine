import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Bar, PriceZone } from "../../types";
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

function FakeChart({ bars: chartBars, zones, onAnchor }: StockChartProps) {
  return <div><span>{chartBars.length} 根 K 线 / {zones.length} 条线</span><button onClick={() => onAnchor?.({ date: "2026-08-01", price: 10 })}>锚点1</button><button onClick={() => onAnchor?.({ date: "2026-08-20", price: 11 })}>锚点2</button></div>;
}

it("切换周期、用两个锚点保存手动趋势支撑并可删除自动和手动线", async () => {
  const created: object[] = [];
  const deleted: string[] = [];
  let stored: PriceZone[] = [automatic];
  const client: ChartClient = {
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
  expect(await screen.findByText("手动趋势支撑")).toBeInTheDocument();
  expect(screen.getByText("11.00")).toBeInTheDocument();
  expect(screen.queryByText("10.90 — 11.10")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "删除自动水平压力 auto-1" }));
  await userEvent.click(screen.getByRole("button", { name: "删除手动趋势支撑 manual-1" }));
  expect(deleted).toEqual(["auto-1", "manual-1"]);
});

it("删除失败时保留线并显示错误", async () => {
  const client: ChartClient = {
    bars: async () => bars,
    zones: async () => [automatic],
    createManualZone: async () => manual,
    deleteZone: async () => { throw new Error("删除失败"); },
  };
  render(<ChartPage initialSymbol="600001.SH" client={client} Chart={FakeChart} />);

  expect(await screen.findByText("2 根 K 线 / 1 条线")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "删除自动水平压力 auto-1" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("删除失败");
  expect(screen.getByText("2 根 K 线 / 1 条线")).toBeInTheDocument();
});

it("删除请求完成前禁止重复提交", async () => {
  let calls = 0;
  let finish!: () => void;
  const client: ChartClient = {
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
