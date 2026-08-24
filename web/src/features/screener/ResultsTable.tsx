import { ArrowUpRight, ChevronRight } from "lucide-react";

import type { Evaluation, ScreenMatch } from "../../types";

export type ScreenSortField = "rank" | "symbol" | "close" | "return_20" | "volume_ratio_20";
export type SortDirection = "asc" | "desc";

function number(value: unknown, digits = 2): string {
  return typeof value === "number" ? value.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "—";
}

function leaves(evaluation: Evaluation): Evaluation[] {
  return evaluation.children.length ? evaluation.children.flatMap(leaves) : [evaluation];
}

export function ResultsTable({ matches, selected, onSelect, onOpenChart, sortBy, sortDirection, onSort }: {
  matches: ScreenMatch[];
  selected?: string;
  onSelect: (match: ScreenMatch) => void;
  onOpenChart: (symbol: string) => void;
  sortBy?: ScreenSortField;
  sortDirection?: SortDirection;
  onSort: (field: ScreenSortField) => void;
}) {
  if (!matches.length) return <div className="result-empty">当前条件没有命中证券。</div>;
  return (
    <div className="results-layout">
      <div className="results-table-wrap" role="region" aria-label="筛选结果表格" tabIndex={0}>
        <table className="results-table">
          <thead><tr>{([
            ["rank", "#"], ["symbol", "证券"], ["close", "现价"], ["return_20", "20 周期"], ["volume_ratio_20", "量比"],
          ] as const).map(([field, label]) => <th key={field}><button type="button" aria-label={`按 ${label} 排序`} onClick={() => onSort(field)}>{label}{sortBy === field && <span aria-hidden="true"> {sortDirection === "desc" ? "↓" : "↑"}</span>}</button></th>)}<th /></tr></thead>
          <tbody>
            {matches.map((match) => (
              <tr key={match.symbol} className={selected === match.symbol ? "selected" : ""} onClick={() => onSelect(match)}>
                <td>{String(match.rank).padStart(2, "0")}</td>
                <td><strong>{String(match.features.name ?? match.symbol)}</strong><small>{match.symbol}</small></td>
                <td>{number(match.features.close)}</td>
                <td className={Number(match.features.return_20) >= 0 ? "positive" : "negative"}>{number(match.features.return_20)}%</td>
                <td>{number(match.features.volume_ratio_20)}x</td>
                <td><button type="button" aria-label={`查看 ${match.symbol} K 线`} onClick={(event) => { event.stopPropagation(); onOpenChart(match.symbol); }}><ArrowUpRight size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && (() => {
        const match = matches.find((item) => item.symbol === selected)!;
        return (
          <aside className="explanation-panel">
            <p className="panel-kicker">MATCH EXPLANATION</p>
            <h3>{String(match.features.name ?? match.symbol)}</h3>
            <span>{match.symbol}</span>
            <div className="explanation-list">
              {leaves(match.explanation).map((item) => (
                <div key={item.path}><ChevronRight size={13} /><p>{`实际 ${String(item.actual)} / 期望 ${String(item.expected)}`}</p><b>{item.result === "true" ? "成立" : item.result === "false" ? "不成立" : "数据不足"}</b></div>
              ))}
            </div>
          </aside>
        );
      })()}
    </div>
  );
}
