import type { MetricSpec } from "../../types";
import { createCondition, toApiNode } from "./treeModel";

const metrics: MetricSpec[] = [
  { key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte", "between"], group: "price", family: "price_change", period: 20, directions: [{ value: "rise", label: "上涨幅度" }, { value: "fall", label: "下跌幅度" }] },
  { key: "board", label: "所属板块", unit: "category", timeframes: ["1d"], operators: ["in", "not_in"], group: "attributes", family: "board", choices: [{ value: "main", label: "主板" }, { value: "chinext", label: "创业板" }], multiple: true },
  { key: "is_new", label: "新股", unit: "boolean", timeframes: ["1d"], operators: ["eq"] },
];

it("把区间常量和布尔值转换为后端条件", () => {
  const range = { ...createCondition(), operator: "between", right: { kind: "constant" as const, value: "10, 30" } };
  const boolean = { ...createCondition("is_new"), operator: "eq", right: { kind: "constant" as const, value: "true" } };

  expect(toApiNode(range, metrics)).toMatchObject({
    right: { value: [10, 30], unit: "percent" },
  });
  expect(toApiNode(boolean, metrics)).toMatchObject({
    right: { value: true, unit: "boolean" },
  });
});

it("把下跌幅度的正数输入转换为负数底层条件", () => {
  const atLeast = {
    ...createCondition(),
    direction: "fall" as const,
    operator: "gte",
    right: { kind: "constant" as const, value: "30" },
  };
  const range = {
    ...atLeast,
    operator: "between",
    right: { kind: "constant" as const, value: "10, 30" },
  };

  expect(toApiNode(atLeast, metrics)).toMatchObject({
    metric: "return_20",
    operator: "lte",
    right: { value: -30, unit: "percent" },
  });
  expect(toApiNode(range, metrics)).toMatchObject({
    operator: "between",
    right: { value: [-30, -10], unit: "percent" },
  });
});

it("把多选枚举转换为包含条件", () => {
  const board = {
    ...createCondition("board"),
    operator: "in",
    selectedValues: ["main", "chinext"],
    right: { kind: "constant" as const, value: "" },
  };

  expect(toApiNode(board, metrics)).toMatchObject({
    metric: "board",
    operator: "in",
    right: { value: ["main", "chinext"], unit: "category" },
  });
});
