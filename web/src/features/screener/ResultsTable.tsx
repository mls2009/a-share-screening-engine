import { FailureButton } from "../reviews/FailureButton";
import { ArrowUpRight, ChevronRight } from "lucide-react";

import type { Evaluation, ScreenMatch } from "../../types";
import type { MetricSpec } from "../../types";
import { formatValue, metricLabel } from "./presentation";

export type ScreenSortField = string;
export type SortDirection = "asc" | "desc";

function number(value: unknown, digits = 2): string {
  return typeof value === "number" ? value.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "—";
}

function leaves(evaluation: Evaluation): Evaluation[] {
  return evaluation.children.length ? evaluation.children.flatMap(leaves) : [evaluation];
}

export function ResultsTable({ matches, selected, onSelect, onOpenChart, onAddWatchlist, sortBy, sortDirection, onSort, columns, catalog = [], checked, onCheck, hideExplanation, newSymbols = [], failedSymbols = [], reviewBusy = false, onToggleFailure }: {
  failedSymbols?: string[];
  reviewBusy?: boolean;
  onToggleFailure?: (symbol:string)=>void;
  newSymbols?: string[];
  columns?: string[];
  catalog?: MetricSpec[];
  checked?: string[];
  onCheck?: (symbol: string) => void;
  hideExplanation?: boolean;
  matches: ScreenMatch[];
  selected?: string;
  onSelect: (match: ScreenMatch) => void;
  onOpenChart: (symbol: string) => void;
  onAddWatchlist?: (symbol: string) => void;
  sortBy?: ScreenSortField;
  sortDirection?: SortDirection;
  onSort: (field: ScreenSortField) => void;
}) {
  if (!matches.length) return <div className="result-empty">当前条件没有命中证券。</div>;
  return (
    <div className="results-layout">
      <div className="results-table-wrap" role="region" aria-label="筛选结果表格" tabIndex={0}>
        <table className="results-table">
          <thead><tr>{onCheck && <th>选择</th>}{(columns ? [["rank", "#"], ["symbol", "证券"], ...columns.map((key) => [key, metricLabel(key, catalog)])] : [
            ["rank", "#"], ["symbol", "证券"], ["close", "现价"], ["return_20", "20 周期"], ["volume_ratio_20", "量比"],
          ]).map(([field, label]) => <th key={field}><button type="button" aria-label={`按 ${label} 排序`} onClick={() => onSort(field)}>{label}{sortBy === field && <span aria-hidden="true"> {sortDirection === "desc" ? "↓" : "↑"}</span>}</button></th>)}{onToggleFailure && <th>复盘标记</th>}<th /></tr></thead>
          <tbody>
            {matches.map((match) => (
              <tr key={match.symbol} className={selected === match.symbol ? "selected" : ""} onClick={() => onSelect(match)}>
                {onCheck && <td><input type="checkbox" aria-label={`勾选 ${match.symbol}`} checked={checked?.includes(match.symbol) ?? false} onClick={(event) => event.stopPropagation()} onChange={() => onCheck(match.symbol)} /></td>}
                <td>{String(match.rank).padStart(2, "0")}</td>
                <td><strong>{String(match.features.name ?? match.symbol)}</strong><small>{match.symbol}</small>{newSymbols.includes(match.symbol) && <span className="new-match-badge">新增</span>}</td>
                {columns ? columns.map((key) => {const value=formatValue(key.includes(":") ? (match.features.metric_values as Record<string, unknown> | undefined)?.[key] : match.features[key], catalog.find((item) => item.key === key.split(":").at(-1)));return <td key={key} className={key.includes("em_")?"sector-cell":undefined} title={value}>{value}</td>;}) : <><td>{number(match.features.close)}</td>
                <td className={Number(match.features.return_20) >= 0 ? "positive" : "negative"}>{number(match.features.return_20)}%</td>
                <td>{number(match.features.volume_ratio_20)}x</td></>}
                {onToggleFailure && <td><FailureButton symbol={match.symbol} failed={failedSymbols.includes(match.symbol)} disabled={reviewBusy} onClick={()=>onToggleFailure(match.symbol)} /></td>}
                <td>{onAddWatchlist && <button type="button" aria-label={`加入自选 ${match.symbol}`} onClick={(event) => { event.stopPropagation(); onAddWatchlist(match.symbol); }}>+ 自选</button>}<button type="button" aria-label={`查看 ${match.symbol} K 线`} onClick={(event) => { event.stopPropagation(); onOpenChart(match.symbol); }}><ArrowUpRight size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && !hideExplanation && (() => {
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
