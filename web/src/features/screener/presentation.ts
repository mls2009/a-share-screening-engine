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
  if ("label" in node && node.label) return node.label;
  if ("disabled" in node && node.disabled) return "";
  if (node.kind === "group" && "children" in node) {
    const children = node.children?.map((child) => describe(child, catalog)).filter(Boolean) ?? [];
    return node.logic === "not" ? `不满足（${children.join("")}）` : node.logic === "at_least" ? `同日最少满足 ${"minimumMatches" in node ? node.minimumMatches ?? 1 : 1} 个策略（${children.join("；")}）` : `（${children.join(node.logic === "or" ? "；或者 " : "；并且 ")}）`;
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
  if (metric.key === "ma250_reclaim_2d_2y") return "以下任一满足即可，完成日必须在市场最近5个已入库交易日内：①前一根收盘>当天MA250，当根收盘<当天MA250，随后第1～3根收盘重新>各自当天MA250，仅记录首次收复。②单K或双K合并后形成下影支撑：最低价距其当天MA250在±2%以内，下影>0且≥实体，最终收盘>当天MA250。双K使用首根开盘、末根收盘和两根最低价合成。不要求此前两次有效支撑；不限制成交量。扫描近两年背景，图上标记最近5日命中的实际区间和形态类别。";
  if (metric.key === "ma120_250_repeat_support_2y") return "先在近两年日线内寻找同一均线的两次有效支撑，窗口开头20根不计入；每次触及后20个交易日收盘均高于对应均线，期间收盘跌破则清零。只有第三次及后续单K/双K下影支撑发生在市场最近5个交易日内才入选。MA120按股价分位判断K线实际接触，MA250仍允许最低价距离均线±2%；下影>0且≥实体，最终收盘在均线上方。";
  if (metric.key === "ma_cluster_pierce_10d_no120_2y") return "突破前连续10个交易日：MA10/20/30每天最大间距≤0.8%，10日整体拟合斜率绝对值均≤0.10%/日，每天的滚动5日拟合斜率绝对值均≤0.20%/日。不含突破当天，需14个前置交易日的均线值。突破阳线实体穿过MA5/10/20/30/60，不要求MA120；成交量≥含当日20日均量的2倍。查近两年所有命中，标出整理区间与突破K线。";
  if (metric.key === "ma_cluster_pierce_up_2y") return "近两年内，MA10/20/30在突破前5个交易日的整体拟合斜率绝对值均≤0.10%/交易日，且这5天每一天各自的滚动5日拟合斜率绝对值均≤0.20%/交易日。所有斜率不包含突破当天，需至少9个前置交易日的有效均线值。当天MA10/20/30间距≤2%，成交量≥含当日20日均量的2倍，阳线实体上穿MA5/10/20/30/60/120。MA60/120不参与走平判定。";
  if (metric.key === "sequoia_triple_ma120_within_2y") return "最近两个自然年内，至少一根已完成日K同时满足Sequoia海龟突破、均线金叉放量、RPS强势近高点（普通海龟突破与金叉均要求至少2倍放量；真实涨停豁免海龟的放量要求，金叉仍要求2倍），并满足：开盘≤当日MA120且收盘>MA120；或者MA120<开盘≤MA120×1.10。三策略直接复用Sequoia口径，RPS使用当日全市场排名。记录全部命中日期，不要求今天满足。此历史组合用于收盘选股。";
  if (metric.key === "sequoia_double_ma120_within_2y") return "最近两个自然年内，至少一根已完成日K同时满足Sequoia海龟突破、均线金叉放量（普通海龟突破与金叉均要求至少2倍放量；真实涨停豁免海龟的放量要求，金叉仍要求2倍），并满足：开盘≤当日MA120且收盘>MA120；或者MA120<开盘≤MA120×1.10。不要求RPS排名或接近120日高点。记录全部命中日期，不要求今天满足。此历史组合用于收盘选股。";
  if (metric.key === "vacuum_reentry_ma120_within_250") return "按日线成交量定义缩量急跌区间，无需分钟数据。急跌段日均成交量须≤前20日日均量的0.8倍。最近250个交易日（含观察日）至少一天同时满足：跌幅>25%的缩量急跌区间跌出后重新进入，且该日收盘价>该日MA120。不要求今天仍满足；历史不足但已找到命中时可入选，否则显示数据不足。";
  if (metric.key.startsWith("vacuum_")) return "日线缩量急跌区间；急跌段日均成交量/此前20日日均量≤0.8，缺失不判定。日线：20日高点起跌，3～5根跌幅>25%、下跌效率≥80%、相邻收盘每日跌幅≥2%，无连续3根振幅≤3%的平台；急跌首次放缓后的收盘确认终点（缓跌不计入），满5根则固定区间。之后收盘远离下沿至少5%，连续5日收盘低于下沿，且远离后间隔3～20日才允许从下方收盘重新进入、且低于上沿时触发一次。MA120需另加条件。多个区间优先展示最新命中区间；仅支持收盘和历史回测。";
  if (metric.key.startsWith("pa_")) {
    if (metric.key.endsWith("within_250")) return "扫描截至观察日最近250个交易日：同一天同时满足Pinbar、区间边界、局部极值与四项至少两项。命中过一次即可入选，同一股票所有命中日期及当时关键位都会标记。每次只使用当时已知历史，不要求今天仍符合。";
    if (metric.key.endsWith("pinbar")) return "主影线长度严格超过整根振幅的2/3；不限制副影线比例，不限制阴阳线。仅识别已收盘日线。";
    if (metric.key.endsWith("local_extreme")) return "看涨：前3根收盘依次降低，当根最低价低于这3根最低价；看跌按相反方向判断。";
    if (metric.key === "pa_prominent") return "当前最高价−最低价，至少为前20根同类振幅中位数的1.5倍；20根和1.5倍是对书中‘明显’的量化参数。";
    if (metric.key === "pa_left_eye") return "本根实体全部位于前一根高低价范围内，且本根振幅更大；两个要求一起满足。";
    if (metric.key.endsWith("trend")) return "只使用此前已结束周线；拐点左右各2周确认，最近两个波峰与两个波谷均抬高（看涨）或降低（看跌）。";
    return "试验版：此前250根日线低价2%与高价98%分位估计大区间，只选靠近底部/顶部20%的已确认周线转折，每侧一个区域；中部位置及中部支撑压力转换不参与。转折仍须左右2周确认、反向离开≥周ATR14两倍。图上普通参考线不变。";
  }
  if (metric.key === "pe_ratio") return "腾讯公布的市盈率原值，未明确区分静态/动态/TTM。单位为倍，负值保留，缺失不按零计算；请选择实时行情模式。";
  if (metric.key === "pb_ratio") return "最新市净率，单位为倍；请选择实时行情模式。";
  if (["total_market_cap", "float_market_cap"].includes(metric.key)) return "当前行情快照中的市值，筛选输入单位为元（1 亿元 = 100000000 元）；请选择实时行情模式。";
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
