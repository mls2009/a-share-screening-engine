import { Play, Radio, Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../api";
import type { MetricSpec, ScreenMatch, ScreenRunResult, UiGroupNode, UiNode } from "../../types";
import { ConditionTree } from "./ConditionTree";
import { ResultsTable } from "./ResultsTable";
import { createGroup, toApiNode } from "./treeModel";

export interface ScreenerClient {
  catalog(): Promise<MetricSpec[]>;
  runScreen(payload: object): Promise<ScreenRunResult>;
  screenResults(runId: string, limit: number, offset: number): Promise<ScreenRunResult>;
}

const today = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

export function ScreenerPage({
  client = api,
  onOpenChart,
}: {
  client?: ScreenerClient;
  onOpenChart: (symbol: string) => void;
}) {
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [tree, setTree] = useState<UiGroupNode>(() => createGroup());
  const [mode, setMode] = useState<"close" | "live">("close");
  const [asOf, setAsOf] = useState(today);
  const [result, setResult] = useState<ScreenRunResult>();
  const [selected, setSelected] = useState<ScreenMatch>();
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(200);
  const [error, setError] = useState("");

  useEffect(() => {
    client.catalog().then((metrics) => {
      setCatalog(metrics);
    }).catch((cause: Error) => setError(cause.message));
  }, [client]);

  const run = async () => {
    if (!tree.children.length) { setError("至少需要一个筛选条件"); return; }
    setLoading(true); setError("");
    try {
      const next = await client.runScreen({ tree: toApiNode(tree, catalog), mode, as_of: asOf, limit: pageSize, offset: 0 });
      setResult(next);
      setSelected(next.matches[0]);
      setPage(1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "筛选失败");
    } finally {
      setLoading(false);
    }
  };

  const loadPage = async (nextPage: number, nextPageSize = pageSize) => {
    if (!result) return;
    setPaging(true); setError("");
    try {
      const next = await client.screenResults(
        result.run_id,
        nextPageSize,
        (nextPage - 1) * nextPageSize,
      );
      setResult(next);
      setSelected(next.matches[0]);
      setPage(nextPage);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取筛选结果失败");
    } finally {
      setPaging(false);
    }
  };

  const totalPages = result ? Math.max(1, Math.ceil(result.match_count / pageSize)) : 1;

  return (
    <main className="screener-page">
      <header className="compact-heading">
        <div><p className="eyebrow">FULL MARKET / RULE COMPOSER</p><h1>选股工作台</h1></div>
        <div className="screen-controls">
          <label><span>数据日期</span><input aria-label="数据日期" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
          <label><span>运行方式</span><select aria-label="筛选模式" value={mode} onChange={(event) => setMode(event.target.value as "close" | "live")}><option value="close">收盘数据</option><option value="live">实时行情</option></select></label>
          <button type="button" className="run-button" aria-label="运行全市场筛选" disabled={loading || !catalog.length} onClick={run}>{mode === "live" ? <Radio size={16} /> : <Play size={16} />}{loading ? "计算中…" : "运行筛选"}</button>
        </div>
      </header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <section className="composer-section">
        <div className="section-title"><div><SlidersHorizontal size={17} /><span>条件编排</span></div><button type="button" className="ghost-button" disabled><Save size={14} />保存方案</button></div>
        {catalog.length ? <ConditionTree tree={tree} catalog={catalog} onChange={(next: UiNode) => setTree(next as UiGroupNode)} /> : <div className="loading-strip">正在读取指标目录…</div>}
      </section>
      <section className="screen-results">
        <div className="section-title">
          <div><span>命中结果</span>{result && <em>共命中 {result.match_count.toLocaleString("zh-CN")} 只</em>}</div>
          {result && <div className="run-stats"><span>全市场 <b>{result.universe_size.toLocaleString("zh-CN")}</b></span><span>实时覆盖 <b>{result.realtime_covered.toLocaleString("zh-CN")}</b></span></div>}
        </div>
        {!result ? <div className="result-empty">组合条件后运行，命中股票将在这里显示。</div> : <>
          <ResultsTable matches={result.matches} selected={selected?.symbol} onSelect={setSelected} onOpenChart={onOpenChart} />
          <div className="results-pagination">
            <label>每页<select aria-label="每页数量" value={pageSize} disabled={paging} onChange={(event) => {
              const nextSize = Number(event.target.value);
              setPageSize(nextSize);
              void loadPage(1, nextSize);
            }}>{[50, 100, 200].map((size) => <option key={size} value={size}>{size} 只</option>)}</select></label>
            <button type="button" aria-label="上一页" disabled={page <= 1 || paging} onClick={() => void loadPage(page - 1)}>上一页</button>
            <span>第 {page} / {totalPages} 页</span>
            <button type="button" aria-label="下一页" disabled={page >= totalPages || paging} onClick={() => void loadPage(page + 1)}>下一页</button>
          </div>
        </>}
      </section>
    </main>
  );
}
