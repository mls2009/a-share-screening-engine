import type { MetricSpec } from "../../types";
import { createCondition, toApiNode } from "./treeModel";

const metrics: MetricSpec[] = [
  { key: "return_20", label: "20周期涨跌幅", unit: "percent", timeframes: ["1d"], operators: ["between"] },
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
