import type { Evaluation, Timeframe } from "../../types";

export interface SourceNode {
  kind: string;
  logic?: string;
  children?: SourceNode[];
  metric?: string;
  timeframe?: Timeframe;
  operator?: string;
  lookback?: number;
  right?: { kind: string; metric?: string; timeframe?: Timeframe; value?: unknown; multiplier?: number };
}
export interface WatchSource {
  run_id: string;
  as_of: string;
  mode: string;
  tree: SourceNode;
  explanation: Evaluation;
  marks?: ConditionMark[];
}
export interface WatchItem {
  symbol: string;
  name: string;
  sources: WatchSource[];
  added_at?: string;
}
export interface ConditionMark {
  path?: string;
  metric: string;
  timeframe: Timeframe;
  date: string;
  startDate?: string;
  periods: number;
  label: string;
  metricLabel?: string;
}

export function sourceMarks(source: WatchSource): ConditionMark[] {
  if (source.marks) return source.marks;
  const marks: ConditionMark[] = [];
  function visit(node: SourceNode, evaluation: Evaluation) {
    if (evaluation.result !== "true" || node.logic === "not") return;
    if (node.children) {
      node.children.forEach((child, index) => {
        const result = evaluation.children[index];
        if (result) visit(child, result);
      });
      return;
    }
    if (!node.metric || !node.timeframe) return;
    const periods = node.operator === "continuous" || node.operator === "at_least"
      ? node.lookback ?? 1
      : /_(slope_abs|range)_5$/.test(node.metric) ? 5 : 1;
    const label = `入选 ${source.as_of}：实际 ${String(evaluation.actual)}，期望 ${String(evaluation.expected)}`;
    marks.push({ metric: node.metric, timeframe: node.timeframe, date: source.as_of, periods, label });
    if (node.right?.kind === "metric" && node.right.metric) {
      marks.push({ metric: node.right.metric, timeframe: node.right.timeframe ?? node.timeframe,
        date: source.as_of, periods, label });
    }
  }
  visit(source.tree, source.explanation);
  return marks;
}
