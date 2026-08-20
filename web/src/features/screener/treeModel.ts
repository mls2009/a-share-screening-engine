import type { MetricSpec, Timeframe, UiConditionNode, UiGroupNode, UiNode, Unit } from "../../types";

let sequence = 0;
const id = (prefix: string) => `${prefix}-${++sequence}`;

export function createCondition(metric = "return_20"): UiConditionNode {
  return {
    id: id("condition"),
    kind: "condition",
    metric,
    timeframe: "1d",
    operator: "gte",
    right: { kind: "constant", value: "30" },
    ...(metric.startsWith("return_") ? { direction: "rise" as const } : {}),
  };
}

export function createGroup(logic: UiGroupNode["logic"] = "and"): UiGroupNode {
  return { id: id("group"), kind: "group", logic, children: [createCondition()] };
}

export function updateNode(root: UiNode, targetId: string, updater: (node: UiNode) => UiNode): UiNode {
  if (root.id === targetId) return updater(root);
  if (root.kind === "condition") return root;
  return { ...root, children: root.children.map((child) => updateNode(child, targetId, updater)) };
}

export function removeNode(root: UiNode, targetId: string): UiNode {
  if (root.kind === "condition") return root;
  return {
    ...root,
    children: root.children
      .filter((child) => child.id !== targetId)
      .map((child) => removeNode(child, targetId)),
  };
}

export function setTreeTimeframe(root: UiNode, timeframe: Timeframe): UiNode {
  if (root.kind === "condition") {
    const right = root.right.kind === "metric" ? { ...root.right, timeframe } : root.right;
    return { ...root, timeframe, right };
  }
  return { ...root, children: root.children.map((child) => setTreeTimeframe(child, timeframe)) };
}

function constantValue(raw: string, unit: Unit): boolean | number | string | number[] {
  if (unit === "boolean") return raw === "true";
  if (unit === "category") return raw;
  if (raw.includes(",")) return raw.split(",").map((value) => Number(value.trim()));
  return Number(raw);
}

const inverseOperator: Record<string, string> = {
  gt: "lt",
  gte: "lte",
  lt: "gt",
  lte: "gte",
};

type ConstantValue = boolean | number | string | number[] | string[];

function directionalMagnitude(raw: string, operator: string): number | number[] {
  const values = raw.split(",").map((value) => Number(value.trim()));
  if (values.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("幅度必须是大于 0 的数字");
  }
  if (operator === "between") {
    if (values.length !== 2) throw new Error("幅度区间需要填写两个数字");
    if (values[0] > values[1]) throw new Error("幅度区间必须从小到大填写");
    return values;
  }
  if (values.length !== 1) throw new Error("幅度必须是大于 0 的数字");
  return values[0];
}

function negativeMagnitude(value: ConstantValue): ConstantValue {
  if (Array.isArray(value)) {
    return value.every((item) => typeof item === "number")
      ? value.map((item) => -Number(item)).reverse()
      : value;
  }
  return typeof value === "number" ? -value : value;
}

export function toApiNode(node: UiNode, metrics: MetricSpec[]): object {
  if (node.kind === "group") {
    return { kind: "group", logic: node.logic, children: node.children.map((child) => toApiNode(child, metrics)) };
  }
  const metric = metrics.find((item) => item.key === node.metric);
  if (!metric) throw new Error(`未知指标：${node.metric}`);
  const negativeDirection = node.direction === "fall" || node.direction === "decrease";
  if (node.direction && !["gt", "gte", "between"].includes(node.operator)) {
    throw new Error("方向条件只支持大于、至少或介于");
  }
  const constant = node.selectedValues?.length
    ? node.selectedValues
    : node.direction && node.right.kind === "constant"
      ? directionalMagnitude(node.right.value, node.operator)
      : constantValue(node.right.kind === "constant" ? node.right.value : "", metric.unit);
  const right = node.right.kind === "constant"
    ? {
        kind: "constant",
        value: negativeDirection ? negativeMagnitude(constant) : constant,
        unit: metric.unit,
      }
    : node.right;
  return {
    kind: "condition",
    metric: node.metric,
    timeframe: node.timeframe,
    operator: negativeDirection ? inverseOperator[node.operator] ?? node.operator : node.operator,
    right,
    ...(node.lookback ? { lookback: node.lookback } : {}),
    ...(node.occurrences ? { occurrences: node.occurrences } : {}),
  };
}
