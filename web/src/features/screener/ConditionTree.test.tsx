import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import type { MetricSpec, UiGroupNode } from "../../types";
import { ConditionTree } from "./ConditionTree";
import { createGroup } from "./treeModel";

const directions = [{ value: "rise", label: "上涨幅度" }, { value: "fall", label: "下跌幅度" }];
const catalog: MetricSpec[] = [
  { key: "return_5", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gt", "gte", "lte", "between", "not_between"], group: "price", family: "price_change", period: 5, directions },
  { key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gt", "gte", "lte", "between", "not_between"], group: "price", family: "price_change", period: 20, directions },
  { key: "low_20", label: "阶段最低价", unit: "price", timeframes: ["1d"], operators: ["lte"], group: "price", family: "period_low", period: 20 },
  { key: "low_history", label: "阶段最低价", unit: "price", timeframes: ["1d"], operators: ["lte"], group: "price", family: "period_low", period: "history" },
  { key: "volume", label: "成交量", unit: "shares", timeframes: ["15m", "1d", "1w"], operators: ["gt"], group: "activity", family: "volume" },
  { key: "board", label: "所属板块", unit: "category", timeframes: ["1d"], operators: ["in", "not_in"], group: "attributes", family: "board", multiple: true, choices: [{ value: "main", label: "主板" }, { value: "chinext", label: "创业板" }, { value: "star", label: "科创板" }] },
  { key: "is_new", label: "新股（旧条件）", unit: "boolean", timeframes: ["1d"], operators: ["eq"], group: "attributes", family: "is_new", visible: false },
  { key: "is_suspended", label: "交易状态", unit: "boolean", timeframes: ["1d"], operators: ["eq", "ne"], group: "status", family: "suspension_status", choices: [{ value: "false", label: "正常交易" }, { value: "true", label: "停牌" }] },
  { key: "pattern_type", label: "K 线形态", unit: "category", timeframes: ["1d"], operators: ["in", "not_in"], group: "candlestick", family: "pattern", multiple: true, choices: [{ value: "morning_star", label: "早晨之星" }, { value: "hammer", label: "锤头线" }] },
];

function Harness() {
  const [tree, setTree] = useState<UiGroupNode>(() => createGroup());
  return <ConditionTree tree={tree} catalog={catalog} onChange={(next) => setTree(next as UiGroupNode)} />;
}

describe("ConditionTree", () => {
  it("可在根分组增加条件和嵌套分组", async () => {
    render(<Harness />);

    await userEvent.click(screen.getByRole("button", { name: "根分组添加条件" }));
    expect(screen.getAllByLabelText("指标")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "根分组添加子分组" }));
    expect(screen.getAllByLabelText("组合逻辑")).toHaveLength(2);
  });

  it("按分类、条件和计算周期逐级选择涨跌方向", async () => {
    render(<Harness />);

    expect(screen.getByLabelText("指标分类")).toHaveValue("price");
    expect(screen.getByRole("option", { name: "上涨幅度" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "下跌幅度" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /20周期涨跌幅/ })).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("指标"), "price_change:fall");
    await userEvent.selectOptions(screen.getByLabelText("计算周期"), "5");

    expect(screen.getByLabelText("指标")).toHaveValue("price_change:fall");
    expect(screen.getByLabelText("计算周期")).toHaveValue("5");
    expect(screen.getByRole("option", { name: "大于" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "至少" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "介于" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "至多" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "不介于" })).not.toBeInTheDocument();
  });

  it("阶段最高低价的计算周期可选择历史", async () => {
    render(<Harness />);

    await userEvent.selectOptions(screen.getByLabelText("指标"), "period_low");

    expect(screen.getByRole("option", { name: "历史" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("计算周期"), "history");

    expect(screen.getByLabelText("计算周期")).toHaveValue("history");
  });

  it("切换分类后只显示该类条件并保留兼容 K 线周期", async () => {
    render(<Harness />);
    expect(screen.getByLabelText("周期").closest(".condition-field")).not.toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("指标分类"), "activity");

    expect(screen.getByLabelText("指标")).toHaveValue("volume");
    expect(screen.getByLabelText("操作符")).toHaveValue("gt");
    expect(screen.getByLabelText("周期")).toHaveValue("1d");
  });

  it("板块和 K 线形态支持多选", async () => {
    render(<Harness />);
    await userEvent.selectOptions(screen.getByLabelText("指标分类"), "attributes");
    expect(screen.queryByRole("option", { name: "新股（旧条件）" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("选择所属板块选项"));
    await userEvent.click(screen.getByRole("checkbox", { name: "创业板" }));

    expect(screen.getByRole("checkbox", { name: "主板" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "创业板" })).toBeChecked();

    await userEvent.selectOptions(screen.getByLabelText("指标分类"), "candlestick");
    await userEvent.click(screen.getByLabelText("选择K 线形态选项"));
    await userEvent.click(screen.getByRole("checkbox", { name: "锤头线" }));
    expect(screen.getByRole("checkbox", { name: "早晨之星" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "锤头线" })).toBeChecked();
  });

  it("交易状态使用业务文案而不是布尔值", async () => {
    render(<Harness />);
    await userEvent.selectOptions(screen.getByLabelText("指标分类"), "status");

    expect(screen.getByRole("option", { name: "正常交易" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "停牌" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "true" })).not.toBeInTheDocument();
  });
});
