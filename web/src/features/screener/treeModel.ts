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

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("条件 JSON 结构无效");
  }
  return value as Record<string, unknown>;
}

function constantText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function isNegativeMagnitude(value: unknown): boolean {
  if (typeof value === "number") return value < 0;
  return Array.isArray(value)
    && value.length > 0
    && value.every((item) => typeof item === "number" && item < 0);
}

export function fromApiNode(value: unknown, metrics: MetricSpec[]): UiNode {
  const node = record(value);
  if (node.kind === "group") {
    if (!Array.isArray(node.children) || !["and", "or", "not"].includes(String(node.logic))) {
      throw new Error("条件组合结构无效");
    }
    return {
      id: id("group"),
      kind: "group",
      logic: node.logic as UiGroupNode["logic"],
      children: node.children.map((child) => fromApiNode(child, metrics)),
    };
  }
  if (node.kind !== "condition") throw new Error("条件 JSON 缺少 kind");

  const metric = metrics.find((item) => item.key === node.metric);
  if (!metric) throw new Error(`未知指标：${String(node.metric)}`);
  const right = record(node.right);
  let operator = String(node.operator);
  let direction: UiConditionNode["direction"];
  let constant = right.value;
  if (metric.directions?.length) {
    const negative = isNegativeMagnitude(constant);
    const wanted = negative ? ["fall", "decrease"] : ["rise", "increase"];
    direction = metric.directions.find((item) => wanted.includes(item.value))
      ?.value as UiConditionNode["direction"];
    if (!direction) throw new Error(`无法识别 ${metric.label} 的方向`);
    if (negative) {
      operator = inverseOperator[operator] ?? operator;
      constant = negativeMagnitude(constant as ConstantValue);
    }
    if (!["gt", "gte", "between"].includes(operator)) {
      throw new Error(`${metric.label} 的导入条件无法在当前界面中无损表示`);
    }
  }

  const selectedValues = metric.multiple && Array.isArray(constant)
    ? constant.map(String)
    : undefined;
  const operand = right.kind === "metric"
    ? {
        kind: "metric" as const,
        metric: String(right.metric),
        timeframe: String(right.timeframe) as Timeframe,
        multiplier: Number(right.multiplier ?? 1),
      }
    : { kind: "constant" as const, value: constantText(constant) };
  return {
    id: id("condition"),
    kind: "condition",
    metric: metric.key,
    timeframe: String(node.timeframe) as Timeframe,
    operator,
    right: operand,
    direction,
    selectedValues,
    ...(typeof node.comparison_operator === "string" ? { comparison_operator: node.comparison_operator as UiConditionNode["comparison_operator"] } : {}),
    ...(typeof node.lookback === "number" ? { lookback: node.lookback } : {}),
    ...(typeof node.occurrences === "number" ? { occurrences: node.occurrences } : {}),
  };
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
    ...(node.comparison_operator ? { comparison_operator: node.comparison_operator } : {}),
    ...(node.lookback ? { lookback: node.lookback } : {}),
    ...(node.occurrences ? { occurrences: node.occurrences } : {}),
  };
}
