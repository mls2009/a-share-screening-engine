import type { MetricSpec } from "../../types";
import { createCondition, fromApiNode, toApiNode } from "./treeModel";

const metrics: MetricSpec[] = [
  { key: "return_20", label: "价格涨跌", unit: "percent", timeframes: ["1d"], operators: ["gte", "between"], group: "price", family: "price_change", period: 20, directions: [{ value: "rise", label: "上涨幅度" }, { value: "fall", label: "下跌幅度" }] },
  { key: "volume_change_20", label: "成交量增减", unit: "percent", timeframes: ["1d"], operators: ["gte", "between"], group: "activity", family: "volume_change", period: 20, directions: [{ value: "increase", label: "成交量增加" }, { value: "decrease", label: "成交量减少" }] },
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

it("把成交量减少的正数输入转换为负数底层条件", () => {
  const decrease = {
    ...createCondition("volume_change_20"),
    direction: "decrease" as const,
    operator: "gte",
    right: { kind: "constant" as const, value: "30" },
  };

  expect(toApiNode(decrease, metrics)).toMatchObject({
    metric: "volume_change_20",
    operator: "lte",
    right: { value: -30, unit: "percent" },
  });
});

it.each(["-30", "0", "abc"])("拒绝无效的方向幅度输入 %s", (value) => {
  const condition = {
    ...createCondition(),
    direction: "fall" as const,
    right: { kind: "constant" as const, value },
  };

  expect(() => toApiNode(condition, metrics)).toThrow("幅度必须是大于 0 的数字");
});

it("拒绝倒序的方向幅度区间", () => {
  const condition = {
    ...createCondition(),
    direction: "rise" as const,
    operator: "between",
    right: { kind: "constant" as const, value: "30, 10" },
  };

  expect(() => toApiNode(condition, metrics)).toThrow("幅度区间必须从小到大填写");
});

it("拒绝会混入反方向结果的操作符", () => {
  const condition = {
    ...createCondition(),
    direction: "fall" as const,
    operator: "lte",
  };

  expect(() => toApiNode(condition, metrics)).toThrow("方向条件只支持大于、至少或介于");
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

it("把导入的负涨跌幅 JSON 还原为界面中的下跌幅度正数", () => {
  const imported = fromApiNode({
    kind: "group",
    logic: "and",
    children: [{
      kind: "condition",
      metric: "return_20",
      timeframe: "1d",
      operator: "lte",
      right: { kind: "constant", value: -30, unit: "percent" },
    }],
  }, metrics);

  expect(imported).toMatchObject({
    kind: "group",
    logic: "and",
    children: [{
      metric: "return_20",
      operator: "gte",
      direction: "fall",
      right: { kind: "constant", value: "30" },
    }],
  });
  expect(toApiNode(imported, metrics)).toMatchObject({
    children: [{ operator: "lte", right: { value: -30 } }],
  });
});
