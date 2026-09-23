import {
  NotebookPen,
  BellRing,
  CandlestickChart,
  Database,
  FlaskConical,
  ScanSearch,
  Star,
  Trees,
} from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { ScreenerPage } from "./features/screener/ScreenerPage";
import type { SourceNode, WatchSource } from "./features/watchlist/model";

const ChartPage = lazy(() => import("./features/chart/ChartPage").then((module) => ({ default: module.ChartPage })));
const BacktestPage = lazy(() => import("./features/backtest/BacktestPage").then((module) => ({ default: module.BacktestPage })));
const MonitorPage = lazy(() => import("./features/monitor/MonitorPage").then((module) => ({ default: module.MonitorPage })));
const WatchlistPage = lazy(() => import("./features/watchlist/WatchlistPage").then((module) => ({ default: module.WatchlistPage })));

const SequoiaPage = lazy(() => import("./features/sequoia/SequoiaPage").then(module => ({ default: module.SequoiaPage })));

const NotesPage = lazy(() => import("./features/notes/NotesPage").then(module => ({default:module.NotesPage})));

type Page = "screener" | "chart" | "backtest" | "monitor" | "watchlist" | "sequoia" | "notes";

const pages = [
  { id: "screener" as const, label: "条件选股", icon: ScanSearch },
  { id: "watchlist" as const, label: "自选股", icon: Star },
  { id: "notes" as const, label: "笔记", icon: NotebookPen },
  { id: "chart" as const, label: "K 线研究", icon: CandlestickChart },
  { id: "backtest" as const, label: "策略回测", icon: FlaskConical },
  { id: "sequoia" as const, label: "Sequoia 选股", icon: Trees },
  { id: "monitor" as const, label: "实时监控", icon: BellRing },
];

export function App() {
  const [page, setPage] = useState<Page>("screener");
  const [chartSource, setChartSource] = useState<WatchSource>();
  const [chartSymbol, setChartSymbol] = useState("600519.SH");
  const [backtestDraft, setBacktestDraft] = useState<{symbol:string;tree:SourceNode}>();
  const [monitorDraft, setMonitorDraft] = useState<{symbol:string;price:number}>();
  return (
    <div className="app-frame">
      <aside className="rail">
        <div className="brand" aria-label="AStock">
          <span className="brand-mark">A</span>
          <div><strong>ASTOCK</strong><small>LOCAL TERMINAL</small></div>
        </div>
        <nav aria-label="主导航">
          {pages.map(({ id, label, icon: Icon }, index) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              onClick={() => setPage(id)}
              type="button"
              aria-label={label}
              aria-current={page === id ? "page" : undefined}
            >
              <span className="nav-index">0{index + 1}</span>
              <Icon size={18} strokeWidth={1.7} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="rail-foot">
          <Database size={16} />
          <span>DuckDB</span>
          <i />
        </div>
      </aside>
      {page === "screener" ? (
        <ScreenerPage onOpenChart={(symbol, source) => { setChartSymbol(symbol); setChartSource(source); setPage("chart"); }} onBacktest={(symbol,tree)=>{setBacktestDraft({symbol,tree});setPage("backtest");}} onMonitor={(symbol,price)=>{setMonitorDraft({symbol,price});setPage("monitor");}} />
      ) : page === "watchlist" ? (
        <Suspense fallback={<main className="empty-page">正在加载自选股…</main>}><WatchlistPage /></Suspense>
      ) : page === "notes" ? (
        <Suspense fallback={<main>正在加载笔记…</main>}><NotesPage onLatest={symbol => {setChartSymbol(symbol);setChartSource(undefined);setPage("chart");}} /></Suspense>
      ) : page === "sequoia" ? (
        <Suspense fallback={<main className="empty-page">正在加载 Sequoia 选股…</main>}><SequoiaPage /></Suspense>
      ) : page === "chart" ? (
        <Suspense fallback={<main className="empty-page"><p className="eyebrow">LOADING CHART DESK</p></main>}>
          <ChartPage key={`${chartSymbol}:${chartSource?.run_id ?? ""}`} initialSymbol={chartSymbol} watchSource={chartSource} />
        </Suspense>
      ) : page === "backtest" ? (
        <Suspense fallback={<main className="empty-page"><p className="eyebrow">LOADING BACKTEST ENGINE</p></main>}>
          <BacktestPage initialDraft={backtestDraft}/>
        </Suspense>
      ) : (
        <Suspense fallback={<main className="empty-page"><p className="eyebrow">LOADING LIVE MONITOR</p></main>}>
          <MonitorPage initialDraft={monitorDraft}/>
        </Suspense>
      )}
    </div>
  );
}
