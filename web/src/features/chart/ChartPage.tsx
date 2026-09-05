import { ArrowLeft, GitCompareArrows, Maximize2, Minimize2, RefreshCw, Search, Trash2 } from "lucide-react";
import { type ComponentType, useEffect, useRef, useState } from "react";

import { api } from "../../api";
import type { Bar, BenchmarkComparison, ChartDataSyncRequest, ChartDataSyncResult, ChartIndicator, ChartIndicatorPoint, PriceZone, SymbolSearchResult, Timeframe } from "../../types";
import { BenchmarkChart } from "./BenchmarkChart";
import { DrawingToolbar } from "./DrawingToolbar";
import { zonePresentation } from "./chartOptions";
import { type ChartWindow, drillWindow, drilldownTimeframes, filterWindowBars } from "./drilldown";
import { type DrawingAnchor, type DrawingGeometry, type DrawingKind, buildManualZonePayload } from "./drawing";
import { StockChart, type StockChartProps } from "./StockChart";
import { sourceMarks } from "../watchlist/model";
import { TimeframeToolbar } from "./TimeframeToolbar";

export interface ChartClient {
  searchSymbols(query: string): Promise<SymbolSearchResult[]>;
  bars(symbol: string, timeframe: Timeframe, start: string, end: string): Promise<Bar[]>;
  indicators?(symbol: string, timeframe: Timeframe, start: string, end: string): Promise<ChartIndicatorPoint[]>;
  benchmarkComparison?(symbol: string, timeframe: Timeframe, start: string, end: string, startAt?: string, endAt?: string): Promise<BenchmarkComparison>;
  syncChartData?(symbol: string, payload: ChartDataSyncRequest): Promise<ChartDataSyncResult>;
  zones(symbol: string, timeframe: Timeframe, asOf: string): Promise<PriceZone[]>;
  createManualZone(symbol: string, payload: object): Promise<PriceZone>;
  deleteZone(symbol: string, zoneId: string): Promise<void>;
}

const indicatorOptions: Array<{ value: ChartIndicator; label: string }> = [
  { value: "ma", label: "MA 5/10/20/30" },
  { value: "boll", label: "BOLL" },
  { value: "macd", label: "MACD" },
  { value: "kdj", label: "KDJ" },
  { value: "rsi", label: "RSI" },
  { value: "volume_ma", label: "成交量均线" },
  { value: "obv", label: "OBV" },
  { value: "atr", label: "ATR" },
];

const date = (value: Date) => value.toISOString().slice(0, 10);
const timeframeLabel: Record<Timeframe, string> = {
  "5m": "5分钟",
  "15m": "15分钟",
  "30m": "30分钟",
  "60m": "60分钟",
  "1d": "日线",
  "1w": "周线",
  "1mo": "月线",
};

const range = (timeframe: Timeframe) => {
  const end = new Date();
  const start = new Date(end);
  if (timeframe.endsWith("m")) start.setDate(start.getDate() - 60);
  else start.setFullYear(start.getFullYear() - 3);
  return [date(start), date(end)] as const;
};

export function ChartPage({
  initialSymbol = "600519.SH",
  client = api,
  Chart = StockChart,
  ComparisonChart = BenchmarkChart,
  watchSource,
}: {
  initialSymbol?: string;
  watchSource?: import("../watchlist/model").WatchSource;
  client?: ChartClient;
  Chart?: ComponentType<StockChartProps>;
  ComparisonChart?: ComponentType<{ comparison: BenchmarkComparison }>;
}) {
  const [symbolInput, setSymbolInput] = useState(initialSymbol);
  const [symbol, setSymbol] = useState(initialSymbol);
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([]);
  const [searchActive, setSearchActive] = useState(false);
  const [timeframe, setTimeframe] = useState<Timeframe>(watchSource ? sourceMarks(watchSource)[0]?.timeframe ?? "1d" : "1d");
  const [bars, setBars] = useState<Bar[]>([]);
  const [indicators, setIndicators] = useState<ChartIndicatorPoint[]>([]);
  const [selectedIndicators, setSelectedIndicators] = useState<ChartIndicator[]>(["ma"]);
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [zones, setZones] = useState<PriceZone[]>([]);
  const [kind, setKind] = useState<DrawingKind | null>(null);
  const [geometry, setGeometry] = useState<DrawingGeometry>("horizontal");
  const [anchors, setAnchors] = useState<DrawingAnchor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [drillStack, setDrillStack] = useState<Array<{ parentTimeframe: Timeframe; window: ChartWindow }>>([]);
  const [selectedBar, setSelectedBar] = useState<Bar | null>(null);
  const [benchmarkEnabled, setBenchmarkEnabled] = useState(false);
  const [comparison, setComparison] = useState<BenchmarkComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);
  const deletingZoneIdsRef = useRef(new Set<string>());
  const [deletingZoneIds, setDeletingZoneIds] = useState(new Set<string>());
  const activeWindow = drillStack.at(-1)?.window;
  const [defaultStart, defaultEnd] = range(timeframe);
  const requestStart = activeWindow?.start ?? (watchSource ? new Date(new Date(watchSource.as_of).getTime() - 730 * 86400000).toISOString().slice(0, 10) : defaultStart);
  const requestEnd = activeWindow?.end ?? (watchSource?.as_of ?? defaultEnd);
  const requestStartAt = activeWindow?.startAt;
  const requestEndAt = activeWindow?.endAt;

  useEffect(() => {
    if (!searchActive) return;
    const query = symbolInput.trim();
    if (!query) {
      setSuggestions([]);
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => {
      client.searchSymbols(query)
        .then((results) => { if (current) setSuggestions(results); })
        .catch((cause: Error) => {
          if (current) {
            setSuggestions([]);
            setError(cause.message || "证券搜索失败");
          }
        });
    }, 180);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [client, searchActive, symbolInput]);

  useEffect(() => {
    let current = true;
    setLoading(true); setError("");
    Promise.all([
      client.bars(symbol, timeframe, requestStart, requestEnd),
      client.zones(symbol, timeframe, requestEnd),
      client.indicators?.(symbol, timeframe, requestStart, requestEnd) ?? Promise.resolve([]),
    ])
      .then(([nextBars, nextZones, nextIndicators]) => {
        if (current) {
          setBars(activeWindow ? filterWindowBars(nextBars, activeWindow) : nextBars);
          setZones(nextZones);
          setIndicators(nextIndicators);
        }
      })
      .catch((cause: Error) => { if (current) setError(cause.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [client, reloadVersion, requestEnd, requestEndAt, requestStart, requestStartAt, symbol, timeframe]);

  useEffect(() => {
    if (!benchmarkEnabled) {
      setComparison(null);
      setComparisonLoading(false);
      return;
    }
    if (!client.benchmarkComparison) {
      setError("当前数据服务不支持大盘对比");
      return;
    }
    let current = true;
    setComparisonLoading(true);
    setError("");
    client.benchmarkComparison(symbol, timeframe, requestStart, requestEnd, requestStartAt, requestEndAt)
      .then((result) => { if (current) setComparison(result); })
      .catch((cause: Error) => {
        if (current) {
          setComparison(null);
          setError(cause.message || "大盘对比数据读取失败");
        }
      })
      .finally(() => { if (current) setComparisonLoading(false); });
    return () => { current = false; };
  }, [benchmarkEnabled, client, reloadVersion, requestEnd, requestEndAt, requestStart, requestStartAt, symbol, timeframe]);

  useEffect(() => {
    if (!fullscreen) return;
    document.body.classList.add("chart-fullscreen-open");
    const orientation = window.screen.orientation as ScreenOrientation & {
      lock?: (mode: string) => Promise<void>;
      unlock?: () => void;
    };
    void orientation?.lock?.("landscape").catch(() => undefined);
    return () => {
      document.body.classList.remove("chart-fullscreen-open");
      orientation?.unlock?.();
    };
  }, [fullscreen]);

  const addAnchor = async (anchor: DrawingAnchor) => {
    if (!kind) return;
    const next = [...anchors, anchor];
    setAnchors(next);
    if (next.length < 2) return;
    try {
      const created = await client.createManualZone(
        symbol,
        buildManualZonePayload(timeframe, kind, geometry, next.slice(0, 2) as [DrawingAnchor, DrawingAnchor]),
      );
      setZones((previous) => [...previous, created]);
      setAnchors([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "手动画线保存失败");
    }
  };

  const openResult = (result: SymbolSearchResult) => {
    setSymbolInput(`${result.name} ${result.symbol}`);
    setSymbol(result.symbol);
    setSuggestions([]);
    setSearchActive(false);
    setDrillStack([]);
    setSelectedBar(null);
    setComparison(null);
    setError("");
  };

  const submitSearch = async () => {
    const query = symbolInput.trim();
    if (!query) return;
    setError("");
    try {
      const results = await client.searchSymbols(query);
      const normalized = query.toUpperCase();
      const exact = results.find((result) =>
        result.symbol === normalized || result.symbol.split(".")[0] === normalized
      );
      if (exact) {
        openResult(exact);
      } else if (results.length === 1) {
        openResult(results[0]);
      } else if (!results.length) {
        setSuggestions([]);
        setError("未找到匹配的证券，请先同步行情数据");
      } else {
        setSuggestions(results);
        setSearchActive(true);
        setError("找到多个结果，请从下拉列表选择");
      }
    } catch (cause) {
      setSuggestions([]);
      setError(cause instanceof Error ? cause.message : "证券搜索失败");
    }
  };

  const remove = async (zone: PriceZone) => {
    if (deletingZoneIdsRef.current.has(zone.zone_id)) return;
    deletingZoneIdsRef.current.add(zone.zone_id);
    setDeletingZoneIds(new Set(deletingZoneIdsRef.current));
    setError("");
    try {
      await client.deleteZone(symbol, zone.zone_id);
      setZones((previous) => previous.filter((item) => item.zone_id !== zone.zone_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "支撑压力线删除失败");
    } finally {
      deletingZoneIdsRef.current.delete(zone.zone_id);
      setDeletingZoneIds(new Set(deletingZoneIdsRef.current));
    }
  };

  const addIndicator = (indicator: ChartIndicator) => {
    setSelectedIndicators((previous) => previous.includes(indicator) ? previous : [...previous, indicator]);
    setIndicatorMenuOpen(false);
  };

  const removeIndicator = (indicator: ChartIndicator) => {
    setSelectedIndicators((previous) => previous.filter((item) => item !== indicator));
  };

  const changeTimeframe = (next: Timeframe) => {
    setTimeframe(next);
    setDrillStack([]);
    setSelectedBar(null);
    setComparison(null);
    setAnchors([]);
  };

  const selectBar = (bar: Bar) => {
    if (benchmarkEnabled || kind || !drilldownTimeframes(timeframe).length) return;
    setSelectedBar(bar);
  };

  const enterDrilldown = (target: Timeframe) => {
    if (!selectedBar) return;
    const window = drillWindow(selectedBar, timeframe, target);
    setDrillStack((previous) => [...previous, { parentTimeframe: timeframe, window }]);
    setTimeframe(target);
    setSelectedBar(null);
    setComparison(null);
    setAnchors([]);
  };

  const leaveDrilldown = () => {
    const previous = drillStack.at(-1);
    if (!previous) return;
    setDrillStack((stack) => stack.slice(0, -1));
    setTimeframe(previous.parentTimeframe);
    setSelectedBar(null);
    setComparison(null);
    setAnchors([]);
  };

  const toggleBenchmark = () => {
    setBenchmarkEnabled((enabled) => !enabled);
    setSelectedBar(null);
    setIndicatorMenuOpen(false);
    setKind(null);
    setAnchors([]);
    setError("");
  };

  const syncCurrentWindow = async () => {
    if (!client.syncChartData) {
      setError("当前数据服务不支持行情同步");
      return;
    }
    setSyncing(true);
    setError("");
    try {
      await client.syncChartData(symbol, {
        timeframe,
        start: requestStart,
        end: requestEnd,
        include_benchmark: benchmarkEnabled,
      });
      setReloadVersion((version) => version + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "行情同步失败");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <main className={`chart-page ${fullscreen ? "has-fullscreen-chart" : ""}`}>
      <header className="chart-heading">
        <div><p className="eyebrow">PRICE STRUCTURE / DRAWING DESK</p><h1>K 线研究</h1></div>
        <form onSubmit={(event) => { event.preventDefault(); void submitSearch(); }}>
          <Search size={15} />
          <input
            aria-autocomplete="list"
            aria-controls="symbol-search-results"
            aria-expanded={suggestions.length > 0}
            aria-label="证券代码或名称"
            placeholder="代码 / 中文名称"
            value={symbolInput}
            onChange={(event) => {
              setSymbolInput(event.target.value);
              setSearchActive(true);
              setError("");
            }}
          />
          <button className="chart-search-submit" type="submit">打开</button>
          {suggestions.length > 0 && (
            <div className="symbol-search-results" id="symbol-search-results" role="listbox">
              {suggestions.map((result) => (
                <button
                  className="symbol-search-option"
                  key={result.symbol}
                  role="option"
                  type="button"
                  onClick={() => openResult(result)}
                >
                  <span>{result.name}</span>
                  <code>{result.symbol}</code>
                  <em>{result.instrument_type === "etf" ? "ETF" : "股票"}</em>
                </button>
              ))}
            </div>
          )}
        </form>
      </header>
      <section className={`chart-desk ${fullscreen ? "is-fullscreen" : ""}`} data-testid="chart-desk">
        <div className="chart-topline">
          <div><strong>{symbol}</strong><span>{bars.length ? `${bars.at(-1)?.close.toFixed(2)} 元` : "—"}</span></div>
          <div className="chart-actions">
            <TimeframeToolbar value={timeframe} onChange={changeTimeframe} />
            <button
              type="button"
              className={`benchmark-toggle ${benchmarkEnabled ? "active" : ""}`}
              aria-label={benchmarkEnabled ? "关闭大盘对比" : "开启大盘对比"}
              aria-pressed={benchmarkEnabled}
              onClick={toggleBenchmark}
            >
              <GitCompareArrows size={15} />
              <span>{benchmarkEnabled ? "关闭对比" : "大盘对比"}</span>
            </button>
            <button type="button" className="fullscreen-toggle" aria-label={fullscreen ? "退出全屏" : "全屏看盘"} onClick={() => setFullscreen((current) => !current)}>
              {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              <span>{fullscreen ? "退出" : "全屏"}</span>
            </button>
          </div>
        </div>
        {drillStack.length > 0 && <div className="drill-breadcrumb">
          <button type="button" aria-label={`返回${timeframeLabel[drillStack.at(-1)!.parentTimeframe]}`} onClick={leaveDrilldown}>
            <ArrowLeft size={14} />返回{timeframeLabel[drillStack.at(-1)!.parentTimeframe]}
          </button>
          <span>{timeframeLabel[drillStack[0].parentTimeframe]}</span>
          {drillStack.map((entry) => <span className="drill-crumb" key={`${entry.window.timeframe}-${entry.window.label}`}>/ <b>{entry.window.label}</b> / {timeframeLabel[entry.window.timeframe]}</span>)}
        </div>}
        {!benchmarkEnabled && <div className="indicator-toolbar">
          <span>技术指标</span>
          {selectedIndicators.map((indicator) => {
            const option = indicatorOptions.find((item) => item.value === indicator);
            return <button key={indicator} type="button" className="indicator-chip" aria-label={`删除指标 ${option?.label}`} onClick={() => removeIndicator(indicator)}>{option?.label} ×</button>;
          })}
          <div className="indicator-menu-wrap">
            <button type="button" className="add-indicator" aria-expanded={indicatorMenuOpen} onClick={() => setIndicatorMenuOpen((open) => !open)}>+ 指标</button>
            {indicatorMenuOpen && <div className="indicator-menu" role="menu">
              {indicatorOptions.filter((option) => !selectedIndicators.includes(option.value)).map((option) => (
                <button key={option.value} type="button" role="menuitem" onClick={() => addIndicator(option.value)}>{option.label}</button>
              ))}
            </div>}
          </div>
        </div>}
        {!benchmarkEnabled && <DrawingToolbar kind={kind} geometry={geometry} anchors={anchors.length} onKindChange={(next) => { setKind(next); setAnchors([]); }} onGeometryChange={(next) => { setGeometry(next); setAnchors([]); }} onCancel={() => { setKind(null); setAnchors([]); }} />}
        {error && <div className="error-banner" role="alert">{error}</div>}
        <div className="chart-canvas-wrap">
          {benchmarkEnabled ? comparisonLoading ? (
            <div className="chart-loading">正在读取大盘走势…</div>
          ) : comparison ? (
            <ComparisonChart comparison={comparison} />
          ) : (
            <div className="chart-data-empty">
              <p>当前时段缺少可对齐的股票或大盘行情。</p>
              <button type="button" disabled={syncing} onClick={() => void syncCurrentWindow()}><RefreshCw size={14} />{syncing ? "正在同步…" : "同步股票及大盘数据"}</button>
            </div>
          ) : loading ? (
            <div className="chart-loading">正在读取行情…</div>
          ) : !bars.length ? (
            <div className="chart-data-empty">
              <p>该周期暂无本地 K 线数据。</p>
              <button type="button" disabled={syncing} onClick={() => void syncCurrentWindow()}><RefreshCw size={14} />{syncing ? "正在同步…" : "同步当前时段数据"}</button>
            </div>
          ) : (
            <Chart bars={bars} zones={zones} indicators={indicators} selectedIndicators={selectedIndicators} marks={watchSource && symbol === initialSymbol ? sourceMarks(watchSource).filter((mark) => mark.timeframe === timeframe) : []} drawing={kind !== null} onAnchor={addAnchor} onBarSelect={selectBar} />
          )}
        </div>
        {selectedBar && <div className="drilldown-menu" role="dialog" aria-label="选择小周期">
          <div><strong>{selectedBar.timestamp.slice(0, 10)}</strong><span>选择要查看的小周期</span></div>
          <div>
            {drilldownTimeframes(timeframe).map((target) => <button key={target} type="button" aria-label={`查看${timeframeLabel[target]}`} onClick={() => enterDrilldown(target)}>{timeframeLabel[target]}</button>)}
            <button type="button" className="drilldown-cancel" onClick={() => setSelectedBar(null)}>取消</button>
          </div>
        </div>}
      </section>
      {!benchmarkEnabled && <section className="zone-ledger">
        <div className="section-title"><div><span>支撑压力线</span><em>{zones.length}</em></div><p><i className="support-dot" />支撑<i className="resistance-dot" />压力<span className="normal-line" />正常实线<span className="reappeared-line" />删除后重现虚线</p></div>
        <div className="zone-list">
          {zones.map((zone) => {
            const { label } = zonePresentation(zone);
            const className = zone.zone_kind === "uptrend" ? "support" : zone.zone_kind === "downtrend" ? "resistance" : zone.zone_kind;
            return <div key={zone.zone_id} className={className}><span>{label}</span><b>{zone.center_price.toFixed(2)}</b><small>{zone.touches} 次触及</small><button type="button" aria-label={`删除${label} ${zone.zone_id}`} disabled={deletingZoneIds.has(zone.zone_id)} onClick={() => remove(zone)}><Trash2 size={14} /></button></div>;
          })}
          {!zones.length && <div className="result-empty">当前窗口内尚未识别到有效支撑压力线。</div>}
        </div>
      </section>}
    </main>
  );
}
