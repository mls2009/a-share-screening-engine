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

export function toApiNode(node: UiNode, metrics: MetricSpec[]): object {
  if (node.kind === "group") {
    return { kind: "group", logic: node.logic, children: node.children.map((child) => toApiNode(child, metrics)) };
  }
  const metric = metrics.find((item) => item.key === node.metric);
  if (!metric) throw new Error(`未知指标：${node.metric}`);
  const right = node.right.kind === "constant"
    ? { kind: "constant", value: constantValue(node.right.value, metric.unit), unit: metric.unit }
    : node.right;
  return {
    kind: "condition",
    metric: node.metric,
    timeframe: node.timeframe,
    operator: node.operator,
    right,
    ...(node.lookback ? { lookback: node.lookback } : {}),
    ...(node.occurrences ? { occurrences: node.occurrences } : {}),
  };
}
