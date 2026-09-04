import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MetricSpec, ScreenRunResult } from "../../types";
import { ScreenerPage, type ScreenerClient } from "./ScreenerPage";

const catalog: MetricSpec[] = [
  { key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte", "lte", "between"], group: "price", family: "price_change", period: 20, directions: [{ value: "rise", label: "上涨幅度" }, { value: "fall", label: "下跌幅度" }] },
];
const result: ScreenRunResult = {
  run_id: "run-1",
  status: "completed",
  universe_size: 5547,
  match_count: 1,
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
  return {
    catalog: async () => catalog,
    validateScreen: async () => ({ valid: true, errors: [] }),
    listScreenTemplates: async () => [],
    saveScreenTemplate: async (name, tree) => ({ template_id: "saved", name, version: 1, tree, updated_at: "2026-09-05T00:00:00" }),
    deleteScreenTemplate: async () => undefined,
    runScreen: async () => result,
    screenResults: async () => result,
  };
}

describe("ScreenerPage", () => {
  it("按全部命中结果排序并第三次点击恢复默认顺序", async () => {
    const fetchPage = vi.fn().mockResolvedValue(result);
    const fake: ScreenerClient = {
      ...client(),
      runScreen: async () => ({ ...result, match_count: 450 }),
      screenResults: fetchPage,
    };
    render(<ScreenerPage client={fake} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");
    await userEvent.click(screen.getByRole("button", { name: "运行全市场筛选" }));

    await userEvent.click(screen.getByRole("button", { name: "按 20 周期 排序" }));
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith("run-1", 200, 0, "return_20", "desc"));
    expect(screen.getByRole("button", { name: "按 20 周期 排序" })).toHaveTextContent("20 周期 ↓");

    await userEvent.click(screen.getByRole("button", { name: "按 20 周期 排序" }));
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith("run-1", 200, 0, "return_20", "asc"));
    expect(screen.getByRole("button", { name: "按 20 周期 排序" })).toHaveTextContent("20 周期 ↑");

    await userEvent.click(screen.getByRole("button", { name: "按 20 周期 排序" }));
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith("run-1", 200, 0, undefined, undefined));
    expect(screen.getByRole("button", { name: "按 20 周期 排序" })).toHaveTextContent("20 周期");
  });

  it("运行筛选并展示证券名称、关键数值和解释", async () => {
    render(<ScreenerPage client={client()} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");

    await userEvent.click(screen.getByRole("button", { name: "运行全市场筛选" }));

    expect(screen.getByRole("region", { name: "筛选结果表格" })).toHaveClass("results-table-wrap");
    expect((await screen.findAllByText("测试股份")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("35.20%")).toBeInTheDocument();
    expect(screen.getByText("实际 35.2 / 期望 30")).toBeInTheDocument();
    expect(screen.getByText("5,547")).toBeInTheDocument();
  });

  it("可切换实时模式并打开命中股票 K 线", async () => {
    const calls: object[] = [];
    const open: string[] = [];
    const fake: ScreenerClient = {
      ...client(),
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

  it("下跌幅度以正数输入并提交为带符号条件", async () => {
    const calls: object[] = [];
    const fake: ScreenerClient = {
      ...client(),
      runScreen: async (payload) => { calls.push(payload); return result; },
    };
    render(<ScreenerPage client={fake} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");

    await userEvent.selectOptions(screen.getByLabelText("指标"), "price_change:fall");
    await userEvent.clear(screen.getByLabelText("比较值"));
    await userEvent.type(screen.getByLabelText("比较值"), "30");
    await userEvent.click(screen.getByRole("button", { name: "运行全市场筛选" }));

    await waitFor(() => expect(calls[0]).toMatchObject({
      tree: {
        children: [{
          metric: "return_20",
          operator: "lte",
          right: { value: -30, unit: "percent" },
        }],
      },
    }));
  });

  it("显示总命中数并通过已保存结果翻页和切换每页数量", async () => {
    const secondPage: ScreenRunResult = {
      ...result,
      match_count: 450,
      matches: [{
        ...result.matches[0],
        symbol: "830001.BJ",
        rank: 201,
        features: { ...result.matches[0].features, name: "北交样本" },
      }],
    };
    const firstPage = { ...result, match_count: 450 };
    const fetchPage = vi.fn().mockResolvedValue(secondPage);
    const fake: ScreenerClient = {
      ...client(),
      runScreen: async () => firstPage,
      screenResults: fetchPage,
    };
    render(<ScreenerPage client={fake} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");

    await userEvent.click(screen.getByRole("button", { name: "运行全市场筛选" }));
    expect(await screen.findByText("共命中 450 只")).toBeInTheDocument();
    expect(screen.getByText("第 1 / 3 页")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(fetchPage).toHaveBeenCalledWith("run-1", 200, 200, undefined, undefined));
    expect((await screen.findAllByText("北交样本")).length).toBeGreaterThanOrEqual(1);

    await userEvent.selectOptions(screen.getByLabelText("每页数量"), "50");
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith("run-1", 50, 0, undefined, undefined));
    expect(screen.getByText("第 1 / 9 页")).toBeInTheDocument();
  });

  it("校验并导入粘贴的条件 JSON", async () => {
    const validateScreen = vi.fn().mockResolvedValue({ valid: true, errors: [] });
    const fake = {
      ...client(),
      validateScreen,
      listScreenTemplates: async () => [],
      saveScreenTemplate: vi.fn(),
      deleteScreenTemplate: vi.fn(),
    };
    render(<ScreenerPage client={fake} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");

    await userEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
    const imported = {
      kind: "group",
      logic: "and",
      children: [{
        kind: "condition",
        metric: "return_20",
        timeframe: "1d",
        operator: "lte",
        right: { kind: "constant", value: -30, unit: "percent" },
      }],
    };
    fireEvent.change(screen.getByLabelText("条件 JSON"), {
      target: { value: JSON.stringify(imported) },
    });
    await userEvent.click(screen.getByRole("button", { name: "应用 JSON" }));

    await waitFor(() => expect(validateScreen).toHaveBeenCalledWith(imported));
    expect(screen.getByLabelText("指标")).toHaveValue("price_change:fall");
    expect(screen.getByLabelText("比较值")).toHaveValue(30);
  });

  it("保存、加载并删除持久化条件模板", async () => {
    const saved = {
      template_id: "template-1",
      name: "强势股",
      version: 1,
      tree: {
        kind: "condition",
        metric: "return_20",
        timeframe: "1d",
        operator: "gte",
        right: { kind: "constant", value: 45, unit: "percent" },
      },
      updated_at: "2026-09-05T00:00:00",
    };
    const saveScreenTemplate = vi.fn().mockResolvedValue(saved);
    const deleteScreenTemplate = vi.fn().mockResolvedValue(undefined);
    const fake = {
      ...client(),
      validateScreen: async () => ({ valid: true, errors: [] }),
      listScreenTemplates: vi.fn().mockResolvedValue([saved]),
      saveScreenTemplate,
      deleteScreenTemplate,
    };
    render(<ScreenerPage client={fake} onOpenChart={() => undefined} />);
    await screen.findByLabelText("指标");

    await userEvent.type(screen.getByLabelText("模板名称"), "强势股");
    await userEvent.click(screen.getByRole("button", { name: "保存模板" }));
    await waitFor(() => expect(saveScreenTemplate).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: "加载模板" }));
    expect(screen.getByLabelText("比较值")).toHaveValue(45);

    await userEvent.click(screen.getByRole("button", { name: "删除模板" }));
    await waitFor(() => expect(deleteScreenTemplate).toHaveBeenCalledWith("template-1"));
  });
});
