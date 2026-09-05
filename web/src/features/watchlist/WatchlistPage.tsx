import { useEffect, useState } from "react";
import { api } from "../../api";
import { ChartPage } from "../chart/ChartPage";
import { sourceMarks, type WatchItem, type SourceNode } from "./model";
import type { Evaluation, MetricSpec } from "../../types";

function SourceExplanation({ node, result, catalog }: { node: SourceNode; result: Evaluation; catalog: MetricSpec[] }) {
  if (node.children) return <div style={{ paddingLeft: 16, borderLeft: "2px solid #394247" }}>
    <p>{node.logic === "and" ? "全部满足（AND）" : node.logic === "or" ? "任一满足（OR）" : "不满足（NOT）"}</p>
    {node.children.map((child, index) => <SourceExplanation key={index} node={child} result={result.children[index]} catalog={catalog} />)}
  </div>;
  const spec = catalog.find((item) => item.key === node.metric);
  const operators: Record<string, string> = { gt: "大于", gte: "至少", lt: "小于", lte: "至多", eq: "等于", ne: "不等于", in: "属于", not_in: "不属于", continuous: "连续成立", at_least: "最近 N 次至少成立", crosses_above: "上穿", crosses_below: "下穿", between: "介于", not_between: "不介于" };
  const display = (value: unknown): string => Array.isArray(value) ? value.map(display).join("、") : typeof value === "number" ? value.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) : spec?.choices?.find((choice) => choice.value === String(value))?.label ?? String(value ?? "数据不足");
  const rightSpec = catalog.find((item) => item.key === node.right?.metric);
  const comparison = rightSpec ? `${rightSpec.label}${rightSpec.period ? ` ${rightSpec.period}周期` : ""}（${display(result.expected)}）` : display(result.expected);
  const timeframes: Record<string, string> = { "1d": "日线", "1w": "周线", "1mo": "月线", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟", "60m": "60分钟" };
  return <p>{result.result === "true" ? "✓" : result.result === "false" ? "✕" : "?"} {spec?.label ?? node.metric}{spec?.period ? ` · ${spec.period}周期` : ""}（{timeframes[node.timeframe ?? ""] ?? node.timeframe}） {node.lookback ? `最近 ${node.lookback} 周期，` : ""}{operators[node.operator ?? ""] ?? node.operator} {comparison}{spec?.unit === "percent" ? "%" : ""}；实际 {display(result.actual)}{spec?.unit === "percent" ? "%" : ""}</p>;
}

export function WatchlistPage() {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [selected, setSelected] = useState<string>();
  const [sourceIndex, setSourceIndex] = useState(0);
  const [error, setError] = useState("");
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  useEffect(() => { api.watchlist().then(setItems).catch((cause: Error) => setError(cause.message)); }, []);
  useEffect(() => { api.catalog().then(setCatalog).catch((cause: Error) => setError(cause.message)); }, []);
  const item = items.find((entry) => entry.symbol === selected);
  const source = item?.sources[sourceIndex];
  const remove = async (symbol: string) => {
    try {
      await api.removeWatchlist(symbol);
      setItems((previous) => previous.filter((entry) => entry.symbol !== symbol));
      if (selected === symbol) setSelected(undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "移除失败"); }
  };
  return <div style={{ minWidth: 0, flex: 1 }}>
    <section style={{ padding: "24px 32px" }}>
      <h1>自选股 <small>{items.length} 只</small></h1>
      {error && <p role="alert">{error}</p>}
      {!items.length && <p>在条件选股结果中点击“+ 自选”，即可保留股票及入选条件。</p>}
      <div className="results-table-wrap"><table className="results-table">
        <thead><tr><th>证券</th><th>来源</th><th>操作</th></tr></thead>
        <tbody>{items.map((entry) => <tr key={entry.symbol} className={entry.symbol === selected ? "selected" : ""}>
          <td><button onClick={() => { setSelected(entry.symbol); setSourceIndex(0); }}>{entry.name} · {entry.symbol}</button></td>
          <td>{entry.sources.length ? `${entry.sources.length} 次条件选股 · ${entry.sources.at(-1)?.as_of}` : "手动加入"}</td>
          <td><button onClick={() => { setSelected(entry.symbol); setSourceIndex(0); }}>查看标注 K 线</button> <button onClick={() => void remove(entry.symbol)}>移除自选</button></td>
        </tr>)}</tbody>
      </table></div>
      {item && <div>
        {item.sources.length > 0 && <label>入选记录 <select aria-label="入选记录" value={sourceIndex} onChange={(event) => setSourceIndex(Number(event.target.value))}>
          {item.sources.map((entry, index) => <option key={entry.run_id} value={index}>{entry.as_of} · {entry.mode === "live" ? "盘中" : "收盘"} · 第 {index + 1} 次</option>)}
        </select></label>}
        {source && <p>金色框与圆点表示这次入选的条件依据；切换对应周期可查看标注。盘中入选记录可能与最终收盘图形不同。</p>}
        {source && <details open><summary>入选条件与成立结果</summary><SourceExplanation node={source.tree} result={source.explanation} catalog={catalog} /></details>}
      </div>}
    </section>
    {item && <ChartPage key={`${item.symbol}:${sourceIndex}`} initialSymbol={item.symbol} watchSource={source ? { ...source, marks: sourceMarks(source).map((mark) => {
      const spec = catalog.find((entry) => entry.key === mark.metric);
      const metricLabel = `${spec?.label ?? mark.metric}${spec?.period ? ` ${spec.period}周期` : ""}`;
      return { ...mark, metricLabel, label: `${metricLabel} · ${mark.label}` };
    }) } : undefined} />}
  </div>;
}
