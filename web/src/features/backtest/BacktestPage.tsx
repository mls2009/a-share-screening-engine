import { Activity, Play, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import type { BacktestRun, MetricSpec, Timeframe, UiGroupNode, UiNode } from "../../types";
import { ConditionTree } from "../screener/ConditionTree";
import { createGroup, toApiNode } from "../screener/treeModel";

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

function EquitySparkline({ run }: { run: BacktestRun }) {
  const values = run.result.equity_curve.map((point) => point.equity);
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
  return (
    <div className="equity-chart" aria-label="权益曲线">
      <svg viewBox="0 0 100 42" preserveAspectRatio="none"><polyline points={points} /></svg>
    </div>
  );
}

export function BacktestPage({ client = api }: { client?: BacktestClient }) {
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [entryTree, setEntryTree] = useState<UiGroupNode>(() => createGroup());
  const [exitTree, setExitTree] = useState<UiGroupNode>(() => createGroup());
  const [symbols, setSymbols] = useState("600519.SH");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [start, setStart] = useState(oneYearAgo);
  const [end, setEnd] = useState(today);
  const [cash, setCash] = useState(1_000_000);
  const [positionSize, setPositionSize] = useState(20);
  const [mode, setMode] = useState<"simple" | "realistic">("realistic");
  const [run, setRun] = useState<BacktestRun>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    client.catalog().then(setCatalog).catch((cause: Error) => setError(cause.message));
  }, [client]);

  const execute = async () => {
    setLoading(true); setError("");
    try {
      const parsedSymbols = symbols.split(/[，,\s]+/).map((value) => value.trim().toUpperCase()).filter(Boolean);
      const result = await client.runBacktest({
        symbols: parsedSymbols,
        timeframe,
        start,
        end,
        entry_tree: toApiNode(entryTree, catalog),
        exit_tree: toApiNode(exitTree, catalog),
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
        <button className="run-button" type="button" aria-label="运行策略回测" disabled={!catalog.length || loading} onClick={execute}>
          <Play size={16} />{loading ? "计算中…" : "运行回测"}
        </button>
      </header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <section className="backtest-config">
        <label><span>证券代码（逗号分隔）</span><input aria-label="回测证券代码" value={symbols} onChange={(event) => setSymbols(event.target.value)} /></label>
        <label><span>周期</span><select aria-label="回测周期" value={timeframe} onChange={(event) => setTimeframe(event.target.value as Timeframe)}>{["5m", "15m", "30m", "60m", "1d", "1w", "1mo"].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>开始</span><input aria-label="回测开始日期" type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <label><span>结束</span><input aria-label="回测结束日期" type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
        <label><span>初始资金</span><input aria-label="初始资金" type="number" min="1" value={cash} onChange={(event) => setCash(Number(event.target.value))} /></label>
        <label><span>单次仓位 %</span><input aria-label="单次仓位" type="number" min="1" max="100" value={positionSize} onChange={(event) => setPositionSize(Number(event.target.value))} /></label>
        <label><span>撮合模式</span><select aria-label="撮合模式" value={mode} onChange={(event) => setMode(event.target.value as "simple" | "realistic")}><option value="realistic">A 股真实规则</option><option value="simple">简化模式</option></select></label>
      </section>
      <div className="strategy-trees">
        <section className="strategy-tree"><h2><TrendingUp size={17} />入场条件</h2>{catalog.length && <ConditionTree tree={entryTree} catalog={catalog} onChange={(tree: UiNode) => setEntryTree(tree as UiGroupNode)} />}</section>
        <section className="strategy-tree"><h2><TrendingDown size={17} />离场条件</h2>{catalog.length && <ConditionTree tree={exitTree} catalog={catalog} onChange={(tree: UiNode) => setExitTree(tree as UiGroupNode)} />}</section>
      </div>
      {!run ? <section className="result-empty backtest-empty">配置入场与离场条件后运行。信号按收盘计算，下一根 K 线开盘撮合，避免未来函数。</section> : (
        <section className="backtest-report">
          <div className="metrics-grid">
            <div><span>总收益</span><strong>{run.result.metrics.total_return.toFixed(2)}%</strong></div>
            <div><span>年化收益</span><strong>{run.result.metrics.annualized_return.toFixed(2)}%</strong></div>
            <div><span>最大回撤</span><strong>{run.result.metrics.max_drawdown.toFixed(2)}%</strong></div>
            <div><span>夏普</span><strong>{run.result.metrics.sharpe_ratio.toFixed(2)}</strong></div>
            <div><span>胜率</span><strong>{run.result.metrics.win_rate.toFixed(1)}%</strong></div>
            <div><span>完成交易</span><strong>{run.result.metrics.trade_count}</strong></div>
          </div>
          <div className="report-panel"><h2><Activity size={17} />权益曲线</h2><EquitySparkline run={run} /></div>
          <div className="report-panel"><h2>交易明细</h2><div className="table-scroll"><table><thead><tr><th>证券</th><th>方向</th><th>信号时间</th><th>成交时间</th><th>数量</th><th>价格</th><th>费用</th></tr></thead><tbody>{run.result.trades.map((trade, index) => <tr key={`${trade.timestamp}-${index}`}><td>{trade.symbol}</td><td className={trade.side}>{trade.side === "buy" ? "买入" : "卖出"}</td><td>{new Date(trade.signal_at).toLocaleString("zh-CN")}</td><td>{new Date(trade.timestamp).toLocaleString("zh-CN")}</td><td>{trade.quantity.toLocaleString("zh-CN")}</td><td>{trade.price.toFixed(3)}</td><td>{(trade.commission + trade.tax + trade.transfer_fee).toFixed(2)}</td></tr>)}</tbody></table></div></div>
        </section>
      )}
    </main>
  );
}
