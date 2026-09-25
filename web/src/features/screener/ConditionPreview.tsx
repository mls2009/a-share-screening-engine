import type { MetricSpec, UiNode } from "../../types";
import type { SourceNode } from "../watchlist/model";
import { describe, metricHelp } from "./presentation";

type PreviewNode = UiNode | SourceNode;

function ConditionDetails({ node, catalog }: { node: PreviewNode; catalog: MetricSpec[] }) {
  if ("disabled" in node && node.disabled) return <li className="condition-detail-disabled">已停用，不参与筛选：{describe({ ...node, disabled: false }, catalog)}</li>;
  if (node.kind === "group" && "children" in node) {
    const relation = node.logic === "or" ? "以下条件任一满足即可" : node.logic === "not" ? "以下条件取反（不满足才通过；数据不足不视为通过）" : node.logic === "at_least" ? `同日最少满足以下 ${"minimumMatches" in node ? node.minimumMatches ?? 1 : 1} 个策略` : "以下条件必须全部满足";
    return <li><strong>{"label" in node && node.label ? `${node.label}：` : ""}{relation}</strong>
      <ol>{node.children?.map((child, index) => <ConditionDetails key={index} node={child} catalog={catalog} />)}</ol>
    </li>;
  }
  const item = node as SourceNode;
  const spec = catalog.find(entry => entry.key === item.metric);
  const rightSpec = item.right?.kind === "metric" ? catalog.find(entry => entry.key === item.right?.metric) : undefined;
  return <li><p>{describe({ ...node, label: undefined }, catalog)}</p>
    {spec && <p className="condition-detail-help">{metricHelp(spec)}</p>}
    {rightSpec && <p className="condition-detail-help">对比指标：{metricHelp(rightSpec)}</p>}
  </li>;
}

export function ConditionPreview({ tree, catalog, title = "你正在表达" }: { tree: PreviewNode; catalog: MetricSpec[]; title?: string }) {
  return <section className="condition-preview" aria-label={`${title}：中文条件预览`}>
    <strong>{title}：</strong><p>{describe(tree, catalog) || "尚无启用的条件"}</p>
    <details className="condition-preview-details"><summary><span className="condition-preview-expand">展开详细条件</span><span className="condition-preview-collapse">收起详细条件</span></summary>
      <ol className="condition-detail-tree"><ConditionDetails node={tree} catalog={catalog} /></ol>
      <p className="condition-detail-help">“计算周期”是指标使用的K线根数；“周期”决定每根K线代表日、周或分钟；“回看周期”决定检查多少次。条件中的历史范围以所选数据日期为截止，历史命中不代表今天仍满足。</p>
    </details>
  </section>;
}
