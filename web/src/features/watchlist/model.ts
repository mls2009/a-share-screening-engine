import type { Evaluation, Timeframe } from "../../types";

export interface SourceNode {
  label?: string;
  kind: string;
  logic?: string;
  minimumMatches?: number;
  children?: SourceNode[];
  metric?: string;
  timeframe?: Timeframe;
  operator?: string;
  lookback?: number;
  right?: { kind: string; metric?: string; timeframe?: Timeframe; value?: unknown; multiplier?: number };
}
interface SourceCheck { mark?: { date: string; startDate?: string } }
export interface WatchSource {
  minimum_matches?: number;
  confluence_dates?: string[];
  groups?: Array<{ id: string; checks?: SourceCheck[]; occurrences?: Array<{ date: string; checks: SourceCheck[] }> }>;
  run_id: string;
  as_of: string;
  mode: string;
  tree: SourceNode;
  explanation: Evaluation;
  marks?: ConditionMark[];
}
export interface WatchGroup { id: string; name: string }
export interface WatchItem {
  current_quote?: { date: string; timestamp: string; close: number; change_percent: number | null; source: string } | null;
  trading_status?: { date: string; is_suspended: boolean } | null;
  groups?: WatchGroup[];
  quote?: { date: string; close: number | null; change_percent: number | null } | null;
  symbol: string;
  name: string;
  sources: WatchSource[];
  added_at?: string;
}
export interface ConditionMark {
  strategyId?: string;
  strategyName?: string;
  referenceStartDate?: string;
  shape?: { kind: string; upper_start: number; upper_end: number; lower_start: number; lower_end: number; high_points: {date:string;price:number}[]; low_points: {date:string;price:number}[] };
  path?: string;
  metric: string;
  timeframe: Timeframe;
  date: string;
  startDate?: string;
  periods: number;
  label: string;
  metricLabel?: string;
  priceLow?: number;
  priceHigh?: number;
}

export function sourceMarks(source: WatchSource): ConditionMark[] {
  if (source.marks) {
    const references = new Map<string, string>();
    for (const group of source.groups ?? []) {
      if (group.id !== "turtle") continue;
      for (const hit of group.occurrences ?? [{ date: "", checks: group.checks ?? [] }]) {
        for (const check of hit.checks) {
          const mark = check.mark;
          if (!mark?.startDate) continue;
          const day = hit.date || mark.date;
          const previous = references.get(day);
          if (!previous || mark.startDate < previous) references.set(day, mark.startDate);
        }
      }
    }
    return source.marks.map(mark => mark.label.startsWith("海龟突破 · 首次满足")
      ? { ...mark, referenceStartDate: references.get(mark.date) ?? mark.referenceStartDate } : mark);
  }
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
