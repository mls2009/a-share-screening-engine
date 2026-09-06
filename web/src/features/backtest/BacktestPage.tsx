import { Activity, Play, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import type { BacktestRun, MetricSpec, Timeframe, UiGroupNode, UiNode } from "../../types";
import { ConditionTree } from "../screener/ConditionTree";
import { createGroup, fromApiNode, setTreeTimeframe, toApiNode } from "../screener/treeModel";
import { conditionEntries } from "../screener/presentation";

export interface BacktestClient {
  catalog(): Promise<MetricSpec[]>;
  runBacktest(payload: object): Promise<BacktestRun>;
}

const today = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

function oneYearAgo() {
  const value = new Date();
  value.setFullYear(value.getFullYear() - 1);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(value);
}

function formatNumber(value: number | null | undefined, digits = 2, suffix = "") {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(digits)}${suffix}` : "—";
}

const rejectionReasons: Record<string, string> = {
  suspended: "停牌",
  zero_volume: "成交量为零",
  slippage_outside_price_limits: "滑点价格超出涨跌停边界",
  limit_up_no_liquidity: "开盘涨停限制买入",
  limit_down_no_liquidity: "开盘跌停限制卖出",
  "insufficient cash": "可用资金不足",
};

function rejectionText(order: string) {
  const separator = order.lastIndexOf(": ");
  const reason = order.slice(separator + 2);
  return separator < 0 ? rejectionReasons[order] ?? order : `${order.slice(0, separator)}：${rejectionReasons[reason] ?? reason}`;
}

function EquitySparkline({ run }: { run: BacktestRun }) {
  const values = run.result.equity_curve.map((point) => point.equity).filter(Number.isFinite);
  const points = useMemo(() => {
    if (!values.length) return "";
    const min = Math.min(...values);
    const max = Math.max(...values);
    const spread = max - min || 1;
    return values.map((value, index) => {
      const x = values.length === 1 ? 50 : index / (values.length - 1) * 100;
      return `${x},${38 - (value - min) / spread * 34}`;
    }).join(" ");
  }, [values]);
  if (!values.length) return <p>暂无有效权益数据</p>;
  return (
    <div className="equity-chart" aria-label="权益曲线">
      <svg viewBox="0 0 100 42" preserveAspectRatio="none"><polyline points={points} /></svg>
    </div>
  );
}

export function BacktestPage({ client = api, initialDraft }: { client?: BacktestClient; initialDraft?: {symbol:string;tree:import("../watchlist/model").SourceNode} }) {
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [entryTree, setEntryTree] = useState<UiGroupNode>(() => createGroup());
  const [exitTree, setExitTree] = useState<UiGroupNode>(() => createGroup());
  const [symbols, setSymbols] = useState(initialDraft?.symbol ?? "600519.SH");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [start, setStart] = useState(oneYearAgo);
  const [end, setEnd] = useState(today);
  const [cash, setCash] = useState(1_000_000);
  const [positionSize, setPositionSize] = useState(20);
  const [mode, setMode] = useState<"simple" | "realistic">("realistic");
  const [run, setRun] = useState<BacktestRun>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const backtestCatalog = useMemo(
    () => catalog.filter((metric) => metric.supported_modes ? metric.supported_modes.includes("backtest") : metric.timeframes.length === 7),
    [catalog],
  );
  const entryCatalog = initialDraft ? catalog : backtestCatalog;
  const unsupportedEntry = conditionEntries(entryTree).flatMap(({node}) => [node.metric, node.right?.kind === "metric" ? node.right.metric : undefined]).filter((key): key is string => Boolean(key) && catalog.length > 0 && !backtestCatalog.some(metric=>metric.key===key));

  useEffect(() => {
    client.catalog().then(metrics=>{
      setCatalog(metrics);
      if(initialDraft){
        const node = fromApiNode(initialDraft.tree,metrics);
        setEntryTree(node.kind==="group"?node:{...createGroup(),children:[node]});
        const first = initialDraft.tree.children?.[0] ?? initialDraft.tree;
        if(first.timeframe) setTimeframe(first.timeframe);
      }
    }).catch((cause: Error) => setError(cause.message));
  }, [client,initialDraft]);

  const execute = async () => {
    setLoading(true); setError("");
    try {
      const parsedSymbols = symbols.split(/[，,\s]+/).map((value) => value.trim().toUpperCase()).filter(Boolean);
      const result = await client.runBacktest({
        symbols: parsedSymbols,
        timeframe,
        start,
        end,
        entry_tree: toApiNode(entryTree, entryCatalog),
        exit_tree: toApiNode(exitTree, backtestCatalog),
        initial_cash: cash,
        position_size: positionSize / 100,
        mode,
        adjustment: "qfq",
      });
      setRun(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回测失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="backtest-page">
      <header className="compact-heading">
        <div><p className="eyebrow">CAUSAL ENGINE / NEXT OPEN EXECUTION</p><h1>策略回测</h1></div>
        <button className="run-button" type="button" aria-label="运行策略回测" disabled={!backtestCatalog.length || loading || unsupportedEntry.length > 0} onClick={execute}>
          <Play size={16} />{loading ? "计算中…" : "运行回测"}
        </button>
      </header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {unsupportedEntry.length > 0 && <p role="alert">以下入场指标暂不支持回测：{[...new Set(unsupportedEntry)].map(key=>catalog.find(metric=>metric.key===key)?.label??key).join("、")}。已保留原条件，请删除或替换这些条件后再运行。</p>}
      <section className="backtest-config">
        <label><span>证券代码（逗号分隔）</span><input aria-label="回测证券代码" value={symbols} onChange={(event) => setSymbols(event.target.value)} /></label>
        <label><span>周期</span><select aria-label="回测周期" value={timeframe} onChange={(event) => { const next = event.target.value as Timeframe; setTimeframe(next); setEntryTree((tree) => setTreeTimeframe(tree, next) as UiGroupNode); setExitTree((tree) => setTreeTimeframe(tree, next) as UiGroupNode); }}>{["5m", "15m", "30m", "60m", "1d", "1w", "1mo"].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>开始</span><input aria-label="回测开始日期" type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <label><span>结束</span><input aria-label="回测结束日期" type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
        <label><span>初始资金</span><input aria-label="初始资金" type="number" min="1" value={cash} onChange={(event) => setCash(Number(event.target.value))} /></label>
        <label><span>单次仓位 %</span><input aria-label="单次仓位" type="number" min="1" max="100" value={positionSize} onChange={(event) => setPositionSize(Number(event.target.value))} /></label>
        <label><span>撮合模式</span><select aria-label="撮合模式" value={mode} onChange={(event) => setMode(event.target.value as "simple" | "realistic")}><option value="realistic">A 股规则近似</option><option value="simple">简化模式</option></select></label>
      </section>
      <div className="strategy-trees">
        <section className="strategy-tree"><h2><TrendingUp size={17} />入场条件</h2>{entryCatalog.length > 0 && <ConditionTree tree={entryTree} catalog={entryCatalog} onChange={(tree: UiNode) => setEntryTree(tree as UiGroupNode)} />}</section>
        <section className="strategy-tree"><h2><TrendingDown size={17} />离场条件</h2>{backtestCatalog.length > 0 && <ConditionTree tree={exitTree} catalog={backtestCatalog} onChange={(tree: UiNode) => setExitTree(tree as UiGroupNode)} />}</section>
      </div>
      {!run ? <section className="result-empty backtest-empty">配置入场与离场条件后运行。信号按收盘计算，下一根 K 线开盘撮合，避免未来函数。</section> : (
        <section className="backtest-report">
          {!!run.result.warnings?.length && <div className="report-panel" role="status"><h2>回测警告</h2><ul>{run.result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
          {run.result.diagnostics && <div className="report-panel"><h2>数据覆盖</h2>
            <p>有效区间：{run.result.diagnostics.effective_start ?? "—"} 至 {run.result.diagnostics.effective_end ?? "—"}</p>
            <p>执行 K 线：{run.result.diagnostics.execution_bars} 根；信号 K 线：{run.result.diagnostics.signal_bars} 根</p>
            <p>历史状态覆盖：{run.result.diagnostics.status_covered_bars} 根（{formatNumber(run.result.diagnostics.status_coverage_pct, 2, "%")}）</p>
            <p>无法判定条件：{run.result.diagnostics.unknown_evaluations} 次</p>
            <p>预热 K 线：{Object.entries(run.result.diagnostics.warmup_bars).map(([symbol, count]) => `${symbol} ${count} 根`).join("；") || "无"}</p>
          </div>}
          <div className="metrics-grid">
            <div><span>总收益</span><strong>{formatNumber(run.result.metrics.total_return, 2, "%")}</strong></div>
            <div><span>年化收益</span><strong>{formatNumber(run.result.metrics.annualized_return, 2, "%")}</strong></div>
            <div><span>最大回撤</span><strong>{formatNumber(run.result.metrics.max_drawdown, 2, "%")}</strong></div>
            <div><span>夏普</span><strong>{formatNumber(run.result.metrics.sharpe_ratio)}</strong></div>
            <div><span>胜率</span><strong>{formatNumber(run.result.metrics.win_rate, 1, "%")}</strong></div>
            <div><span>完成交易</span><strong>{formatNumber(run.result.metrics.trade_count, 0)}</strong></div>
          </div>
          <div className="report-panel"><h2><Activity size={17} />权益曲线</h2><EquitySparkline run={run} /></div>
          <div className="report-panel"><h2>拒单记录（{run.result.rejected_orders.length} 次）</h2>{run.result.rejected_orders.length ? <ul>{run.result.rejected_orders.map((order, index) => <li key={index}>{rejectionText(order)}</li>)}</ul> : <p>无拒单记录</p>}</div>
          <div className="report-panel"><h2>交易明细</h2>{!run.result.trades.length && <p>暂无成交记录</p>}<div className="table-scroll" role="region" aria-label="交易明细表格" tabIndex={0}><table><thead><tr><th>证券</th><th>方向</th><th>信号时间</th><th>成交时间</th><th>数量</th><th>价格</th><th>费用</th></tr></thead><tbody>{run.result.trades.map((trade, index) => <tr key={`${trade.timestamp}-${index}`}><td>{trade.symbol}</td><td className={trade.side}>{trade.side === "buy" ? "买入" : "卖出"}</td><td>{new Date(trade.signal_at).toLocaleString("zh-CN")}</td><td>{new Date(trade.timestamp).toLocaleString("zh-CN")}</td><td>{trade.quantity.toLocaleString("zh-CN")}</td><td>{trade.price.toFixed(3)}</td><td>{(trade.commission + trade.tax + trade.transfer_fee).toFixed(2)}</td></tr>)}</tbody></table></div></div>
        </section>
      )}
    </main>
  );
}
