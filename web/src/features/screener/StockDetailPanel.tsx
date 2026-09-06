import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "../../api";
import type { MetricSpec, ScreenMatch } from "../../types";
import type { ConditionMark, SourceNode } from "../watchlist/model";
import type { StockDetail } from "./workbenchTypes";
import { boundaryText, conditionEntries, describe, evaluationAt, formatValue, metricLabel } from "./presentation";
const ChartPage = lazy(() => import("../chart/ChartPage").then((module) => ({ default: module.ChartPage })));

export function StockDetailPanel({ runId, match, catalog, onClose, onStep, onOpenChart, onAddWatchlist, onBacktest, onMonitor }: {
  runId: string; match: ScreenMatch; catalog: MetricSpec[]; onClose: () => void; onStep: (delta: number) => void;
  onOpenChart: (symbol: string) => void; onAddWatchlist: (symbol: string) => void;
  onBacktest?: (symbol: string, tree: SourceNode) => void; onMonitor?: (symbol: string, price: number) => void;
}) {
  const [detail, setDetail] = useState<StockDetail>();
  const [latest, setLatest] = useState<StockDetail>();
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [focus, setFocus] = useState<ConditionMark>();
  const [path, setPath] = useState<string>();
  useEffect(() => {
    let active = true;
    setDetail(undefined); setLatest(undefined); setFocus(undefined); setPath(undefined); setError("");
    api.screenDetail(runId, match.symbol).then((value) => { if (active) setDetail(value); }).catch((cause: Error) => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, [runId, match.symbol]);
  const checkLatest = async () => {
    setChecking(true);
    try { setLatest(await api.screenDetail(runId, match.symbol, true)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "检查失败"); }
    finally { setChecking(false); }
  };
  const entries = detail ? conditionEntries(detail.source.tree) : [];
  return <aside className="stock-detail-panel" aria-label="选股详情面板" tabIndex={0} onKeyDown={(event) => {
    if (["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes((event.target as HTMLElement).tagName)) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); onStep(event.key === "ArrowDown" ? 1 : -1); }
  }}>
    <header className="detail-heading"><div><h2>{String(match.features.name ?? match.symbol)}</h2><small>{match.symbol} · 入选依据</small></div><button onClick={onClose} aria-label="关闭详情">×</button></header>
    <div className="detail-actions"><button onClick={() => onStep(-1)}>↑ 上一只</button><button onClick={() => onStep(1)}>↓ 下一只</button><button onClick={() => onAddWatchlist(match.symbol)}>加入自选</button><button onClick={() => onOpenChart(match.symbol)}>完整K线</button></div>
    <dl className="detail-quotes">{["board", "close", "return_1", "volume", "turnover_rate", "volume_ratio_20", "amount"].map((key) => <div key={key}><dt>{metricLabel(key, catalog)}</dt><dd>{formatValue(match.features[key], catalog.find((metric) => metric.key === key))}</dd></div>)}</dl>
    <p>行情时间：{String(match.features.timestamp ?? match.features.feature_date ?? detail?.source.as_of ?? "未知")} · {detail?.source.mode === "live" ? "入选时盘中快照" : "入选时收盘数据"}</p>
    <section className="sector-tags"><h3>所属行业与概念 · 东方财富</h3>{["em_industry","em_concept"].map(key=><p key={key}><strong>{key==="em_industry"?"行业":"概念"}：</strong>{Array.isArray(match.features[key])?(match.features[key] as string[]).map(name=><span key={name}>{name}</span>):"尚未获取，请更新板块后重新筛选"}</p>)}<small>成分名单快照：{String(match.features.sector_updated_at??"未获取")}；不是历史归属。最近20日的行业/概念条件不作历史重建。</small></section>
    {error && <p role="alert">{error}</p>}
    {!detail && !error && <p>正在读取入选原因与历史表现…</p>}
    {detail && <>
      <h3>为什么入选</h3>
      <p className="condition-preview">{describe(detail.source.tree, catalog)}</p>
      {entries.map(({ node, path: itemPath }) => {
        const result = evaluationAt(detail.source.explanation, itemPath);
        if (!result) return null;
        const marks = detail.source.marks?.filter((mark) => mark.path === itemPath || (!mark.path && mark.metric === node.metric)) ?? [];
        return <div className={`detail-condition ${path === itemPath ? "active" : ""}`} key={itemPath}>
          <button onClick={() => { setPath(itemPath); setFocus(marks[0] ?? { metric: node.metric!, timeframe: node.timeframe!, date: result.data_time?.slice(0, 10) ?? detail.source.as_of, periods: 1, label: describe(node, catalog) }); }}>
            {result.result === "true" ? "✓" : result.result === "false" ? "✕" : "?"} {describe(node, catalog)}
          </button>
          <p>实际 {formatValue(result.actual, catalog.find((item) => item.key === node.metric))} / 要求 {formatValue(result.expected, catalog.find((item) => item.key === node.metric))} · {result.data_time ?? detail.source.as_of}</p>
          <small>{boundaryText(node, result)} {result.reason ?? ""}</small>
          {marks.length > 1 && <details><summary>查看 {marks.length} 个依据位置</summary>{marks.map((mark, index) => <button key={index} onClick={() => { setPath(itemPath); setFocus(mark); }}>{metricLabel(mark.metric, catalog)} {mark.startDate ?? mark.date}～{mark.date}</button>)}</details>}
        </div>;
      })}
      <h3>最近20个交易日{path ? " · 所选条件" : " · 全部条件"}</h3>
      <div className="condition-calendar">{detail.recent.map((day) => {
        const result = path ? evaluationAt(day.evaluation, path) : day.evaluation;
        return <button key={day.date} className={`truth-${result?.result ?? "unknown"}`} title={`${day.date}：${result?.result === "true" ? "符合" : result?.result === "false" ? "不符合" : "数据不足"}`} onClick={() => setFocus({ metric: "close", timeframe: "1d", date: day.date, periods: 1, label: "历史观察日" })}>{day.date.slice(5)}</button>;
      })}</div><small>绿：符合 · 红：不符合 · 灰：数据不足；历史表现按当日收盘重新判断。</small>
      <div className="detail-actions"><button disabled={checking} onClick={() => void checkLatest()}>{checking ? "检查中…" : "检查最新收盘状态"}</button><button onClick={() => onBacktest?.(match.symbol, detail.source.tree)}>带入回测</button><button onClick={() => onMonitor?.(match.symbol, Number(match.features.close ?? 0))}>设置点位提醒</button></div>
      {latest && <section aria-label="最新状态"><p>截至 {String(latest.features.feature_date ?? latest.checked_at)} 最新可用收盘：{latest.source.explanation.result === "true" ? "仍符合全部条件" : latest.source.explanation.result === "false" ? "部分条件不再符合" : "数据不足"}；未覆盖入选时的信息。</p>{entries.map(({node, path:itemPath}) => { const check = evaluationAt(latest.source.explanation,itemPath); return check ? <p key={itemPath}>{describe(node,catalog)}：{check.result === "true" ? "符合" : check.result === "false" ? "不符合" : "数据不足"}，实际 {formatValue(check.actual,catalog.find(item=>item.key===node.metric))}</p> : null; })}</section>}
      <Suspense fallback={<p>正在加载标注K线…</p>}><ChartPage key={`${match.symbol}:${focus?.timeframe}:${focus?.date}:${path}`} initialSymbol={match.symbol} focusMark={focus} watchSource={{ ...detail.source, marks: (detail.source.marks ?? []).filter((mark) => !path || mark.path === path).map((mark) => ({...mark, metricLabel:metricLabel(mark.metric,catalog)})) }} /></Suspense>
    </>}
  </aside>;
}
