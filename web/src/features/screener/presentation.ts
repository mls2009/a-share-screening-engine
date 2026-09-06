import type { Evaluation, MetricSpec, UiNode } from "../../types";
import type { SourceNode } from "../watchlist/model";

export const timeLabels: Record<string, string> = { "1d": "日线", "1w": "周线", "1mo": "月线", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟", "60m": "60分钟" };
export const opLabels: Record<string, string> = { gt: "大于", gte: "大于等于", lt: "小于", lte: "小于等于", eq: "等于", ne: "不等于", between: "介于", not_between: "不在区间", in: "属于", not_in: "不属于", crosses_above: "上穿", crosses_below: "下穿" };
export const units: Record<string, string> = { price: "元", percent: "%", ratio: "倍", shares: "股", amount: "元", count: "次", days: "周期", score: "分" };
export function metricLabel(key: string, catalog: MetricSpec[]) {
  const [timeframe, metric] = key.includes(":") ? key.split(":") : ["", key];
  const spec = catalog.find((item) => item.key === metric);
  return `${spec?.label ?? metric}${spec?.period ? ` ${spec.period === "history" ? "历史" : spec.period + "周期"}` : ""}${timeframe ? ` · ${timeLabels[timeframe]}` : ""}`;
}
export function formatValue(value: unknown, spec?: MetricSpec): string {
  if (value == null) return "数据不足";
  if (Array.isArray(value)) return value.length ? value.map((item) => formatValue(item, spec)).join("、") : "未收录";
  if (typeof value === "string" && value.trim() && spec && units[spec.unit] && Number.isFinite(Number(value))) return formatValue(Number(value), spec);
  if (typeof value === "number") return value.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) + (units[spec?.unit ?? ""] ?? "");
  return spec?.choices?.find((choice) => choice.value === String(value))?.label ?? String(value);
}
export function describe(node: UiNode | SourceNode, catalog: MetricSpec[]): string {
  if ("disabled" in node && node.disabled) return "";
  if (node.kind === "group" && "children" in node) {
    const children = node.children?.map((child) => describe(child, catalog)).filter(Boolean) ?? [];
    return node.logic === "not" ? `不满足（${children.join("")}）` : `（${children.join(node.logic === "or" ? "；或者 " : "；并且 ")}）`;
  }
  const item = node as SourceNode & { direction?: string; selectedValues?: string[]; comparison_operator?: string; occurrences?: number };
  const spec = catalog.find((entry) => entry.key === item.metric);
  const lhs = `${timeLabels[item.timeframe ?? ""] ?? ""} ${metricLabel(item.metric ?? "", catalog)}`;
  const right = item.right?.kind === "metric" ? metricLabel(`${item.right.timeframe}:${item.right.metric}`, catalog) + (item.right.multiplier != null && Number(item.right.multiplier) !== 1 ? ` × ${item.right.multiplier}` : "")
    : formatValue(item.selectedValues ?? item.right?.value, spec);
  const direction = ({ rise: "上涨幅度", fall: "下跌幅度", increase: "成交量增加", decrease: "成交量减少" } as Record<string, string>)[item.direction ?? ""];
  const expression = `${direction ? lhs.replace(spec?.label ?? "", direction) : lhs} ${opLabels[item.operator ?? ""] ?? ""} ${right}`;
  if (item.operator === "continuous" || item.operator === "at_least") return `最近 ${item.lookback ?? 5} 个${item.timeframe === "1d" ? "交易日" : "周期"}，${item.operator === "continuous" ? "每天/每根K线都" : `至少 ${item.occurrences ?? 1} 次` }满足：${lhs} ${opLabels[item.comparison_operator ?? "gt"]} ${right}`;
  return expression;
}
export function conditionEntries(node: SourceNode, path = "root"): Array<{ node: SourceNode; path: string }> {
  return node.children ? node.children.flatMap((child, index) => conditionEntries(child, `${path}.children[${index}]`)) : [{ node, path }];
}
export function evaluationAt(evaluation: Evaluation, path: string): Evaluation | undefined {
  return evaluation.path === path ? evaluation : evaluation.children.map((child) => evaluationAt(child, path)).find(Boolean);
}
export function boundaryText(node: SourceNode, evaluation: Evaluation): string {
  const actual = evaluation.actual, expected = evaluation.expected;
  if (typeof actual !== "number" || typeof expected !== "number" || !["gt", "gte", "lt", "lte"].includes(node.operator ?? "")) return "";
  const delta = ["lt", "lte"].includes(node.operator!) ? expected - actual : actual - expected;
  return `${delta >= 0 ? "距不符合边界" : "尚差"} ${Math.abs(delta).toFixed(4)}${evaluation.unit === "percent" ? "个百分点" : units[evaluation.unit ?? ""] ?? ""}`;
}
export function metricHelp(metric: MetricSpec): string {
  const key = metric.key;
  if (key === "em_industry" || key === "em_concept") return "名称及成分股完全沿用东方财富，按当前同步快照判断。多选“属于”表示任一命中；要求同时属于多个板块时，在AND组添加多条条件。历史日期不代表历史归属。";
  if (key.includes("slope_abs")) return "近5根均线值的回归斜率绝对值 ÷ 同期均值 ×100，每周期百分比；例如0.03代表0.03%/周期。";
  if (key.includes("range_5")) return "近5根均线的（最大值÷最小值−1）×100；例如0.8代表范围0.8%。";
  if (key === "ma_10_20_distance") return "|MA10−MA20| ÷ 两者均值 ×100；10元和10.1元的距离约0.995%。";
  if (/^ma_\d+$/.test(key)) return `最近${metric.period}根K线收盘价的算术平均。选择日线时为${metric.period}个交易日。`;
  if (/^return_\d+$/.test(key)) return `（当前收盘价÷${metric.period}周期前收盘价−1）×100；10元涨到11元为10%。`;
  if (key === "volume_ratio_20") return "当前周期成交量÷包含当前周期的20周期平均成交量；2倍表示当前量为均量的2倍。";
  if (key === "turnover_rate") return "成交股数÷流通股数×100；成交100万股、流通1亿股为1%。需数据源提供该日期换手率。";
  return `${metric.label}，单位：${units[metric.unit] ?? "选项"}。${metric.period ? `计算范围：${metric.period === "history" ? "截至数据日期的可用历史" : metric.period + "根K线"}。` : ""}数据日期是观察截止时间；比较另一指标时使用其所选周期。`;
}
