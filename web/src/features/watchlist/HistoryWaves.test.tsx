import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../../api";
import { HistoryWaves } from "./HistoryWaves";
import type { MetricSpec } from "../../types";

vi.mock("../chart/ChartPage", () => ({ ChartPage: ({ focusMark }: { focusMark: { periods: number } }) => <div>标注 {focusMark.periods} 天</div> }));
const catalog: MetricSpec[] = [{ key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte"], group: "price", supported_modes: ["backtest"], period: 20 }];
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
it("uses the condition editor and locates inclusive matched intervals", async () => {
  const run = vi.spyOn(api, "historyWaves").mockResolvedValue({ matches: [{ start: "2024-01-01", end: "2024-01-02", days: 2, start_price: 12, end_price: 13, gain: 8.33 }], matched_days: 2, total: 1, bars: 5, unknown: 1, start: "2024-01-01", end: "2024-01-05" });
  render(<HistoryWaves symbol="600001.SH" catalog={catalog} />);
  expect(screen.getByLabelText("指标")).toBeInTheDocument();
  expect(screen.queryByLabelText("波段涨幅")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "扫描历史条件" }));
  expect(run).toHaveBeenCalledWith("600001.SH", { tree: expect.objectContaining({ kind: "group", logic: "and" }) });
  expect(await screen.findByText(/命中 2 天/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "定位 K 线" }));
  expect(screen.getByText("标注 2 天")).toBeInTheDocument();
});

it("imports validated JSON and keeps existing conditions when import fails", async () => {
  const validate = vi.spyOn(api, "validateScreen").mockResolvedValue({ valid: true, errors: [] });
  const run = vi.spyOn(api, "historyWaves").mockResolvedValue({ matches: [], matched_days: 0, total: 0, bars: 0, unknown: 0, start: null, end: null });
  render(<HistoryWaves symbol="600001.SH" catalog={catalog} />);
  await userEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
  const input = screen.getByLabelText("条件 JSON");
  const tree = { kind: "condition", metric: "return_20", timeframe: "1d", operator: "gte", right: { kind: "constant", value: 45, unit: "percent" } };
  await userEvent.click(input);
  await userEvent.paste(JSON.stringify(tree));
  await userEvent.click(screen.getByRole("button", { name: "应用 JSON" }));
  expect(validate).toHaveBeenCalledWith(tree);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
  await userEvent.clear(screen.getByLabelText("条件 JSON"));
  await userEvent.click(screen.getByLabelText("条件 JSON"));
  await userEvent.paste(JSON.stringify({ ...tree, timeframe: "1w" }));
  await userEvent.click(screen.getByRole("button", { name: "应用 JSON" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("仅支持日线");
  await userEvent.click(screen.getByRole("button", { name: "取消" }));
  await userEvent.click(screen.getByRole("button", { name: "扫描历史条件" }));
  expect(run).toHaveBeenCalledWith("600001.SH", { tree: expect.objectContaining({ children: [tree] }) });
});
