import { DataDateInput } from "../../components/DataDateInput";
import { ArrowLeft, GitCompareArrows, Maximize2, Minimize2, RefreshCw, Search, Trash2 } from "lucide-react";
import { type ComponentType, useEffect, useRef, useState } from "react";

import { ChartNotes } from "../notes/ChartNotes";
import { api } from "../../api";
import { StockOverview } from "../stock/StockOverview";
import type { Bar, BenchmarkComparison, ChartDataSyncRequest, ChartDataSyncResult, ChartIndicator, ChartIndicatorPoint, PriceZone, SymbolSearchResult, Timeframe } from "../../types";
import { BenchmarkChart } from "./BenchmarkChart";
import { DrawingToolbar } from "./DrawingToolbar";
import { zonePresentation } from "./chartOptions";
import { type ChartWindow, drillWindow, drilldownTimeframes, filterWindowBars } from "./drilldown";
import { type DrawingAnchor, type DrawingGeometry, type DrawingKind, buildManualZonePayload } from "./drawing";
import { StockChart, type StockChartProps } from "./StockChart";
import { type ConditionMark, sourceMarks } from "../watchlist/model";
import { TimeframeToolbar } from "./TimeframeToolbar";

export interface ChartClient {
  chartShapes?(symbol:string, asOf:string, signal?:AbortSignal):Promise<{marks:ConditionMark[];data_date:string|null}>;
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
  { value: "ma", label: "MA 5/10/20/30/120/250" },
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
  else start.setFullYear(start.getFullYear() - (timeframe === "1w" ? 5 : 3));
  return [date(start), date(end)] as const;
};

export function ChartPage({
  initialSymbol = "600519.SH",
  client = api,
  Chart = StockChart,
  ComparisonChart = BenchmarkChart,
  watchSource,
  focusMark,
  historyWave,
  showOverview = true,
}: {
  showOverview?: boolean;
  initialSymbol?: string;
  historyWave?: { start: string; end: string; days: number };
  watchSource?: import("../watchlist/model").WatchSource;
  focusMark?: import("../watchlist/model").ConditionMark;
  client?: ChartClient;
  Chart?: ComponentType<StockChartProps>;
  ComparisonChart?: ComponentType<{ comparison: BenchmarkComparison }>;
}) {
  const [symbolInput, setSymbolInput] = useState(initialSymbol);
  const [symbol, setSymbol] = useState(initialSymbol);
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([]);
  const [searchActive, setSearchActive] = useState(false);
  const [timeframe, setTimeframe] = useState<Timeframe>(focusMark?.timeframe ?? (watchSource ? sourceMarks(watchSource)[0]?.timeframe ?? "1d" : "1d"));
  const [bars, setBars] = useState<Bar[]>([]);
  const [indicators, setIndicators] = useState<ChartIndicatorPoint[]>([]);
  const [selectedIndicators, setSelectedIndicators] = useState<ChartIndicator[]>(["ma"]);
  const [shapeKinds,setShapeKinds] = useState<string[]>([]);
  const [shapeResult,setShapeResult] = useState<{key:string;marks:ConditionMark[]}>();
  const [shapeBusy,setShapeBusy] = useState(false);
  const [shapeError,setShapeError] = useState("");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [zones, setZones] = useState<PriceZone[]>([]);
  const noteCapture = useRef<(() => string) | null>(null);
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
  const [dataDate, setDataDate] = useState("");
  const activeWindow = drillStack.at(-1)?.window;
  const [defaultStart, defaultEnd] = range(timeframe);
  const baseRequestStart = activeWindow?.start ?? (historyWave ? new Date(new Date(historyWave.start).getTime() - 90 * 86400000).toISOString().slice(0, 10) : watchSource ? new Date(new Date(watchSource.as_of).getTime() - (timeframe === "1w" ? 1827 : 730) * 86400000).toISOString().slice(0, 10) : defaultStart);
  const turtleReferences = watchSource && symbol === initialSymbol && timeframe === "1d"
    ? sourceMarks(watchSource).flatMap(mark => mark.referenceStartDate ? [mark.referenceStartDate] : []) : [];
  const requestStart = activeWindow ? baseRequestStart : [baseRequestStart, ...turtleReferences].sort()[0];
  const requestEnd = activeWindow?.end ?? (dataDate || defaultEnd);
  const requestStartAt = activeWindow?.startAt;
  const requestEndAt = activeWindow?.endAt;

  const shapesEnabled = shapeKinds.length > 0 && timeframe === "1d";
  const shapeKey = `${symbol}:${requestEnd}:${reloadVersion}`;
  useEffect(()=>{
    if (!shapesEnabled || !client.chartShapes) {setShapeBusy(false);return;}
    if (shapeResult?.key === shapeKey) return;
    const controller = new AbortController();
    let active=true;setShapeBusy(true);setShapeError("");
    client.chartShapes(symbol,requestEnd,controller.signal)
      .then(value=>{if(active)setShapeResult({key:shapeKey,marks:value.marks});})
      .catch((cause:Error)=>{if(active)setShapeError(cause.message);})
      .finally(()=>{if(active)setShapeBusy(false);});
    return ()=>{active=false;controller.abort();};
  },[client,shapesEnabled,shapeKey]);
  const shapeMarks = shapesEnabled && shapeResult?.key===shapeKey ? shapeResult.marks.filter(mark=>shapeKinds.includes(mark.shape?.kind ?? "")) : [];

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
    setBars([]);
    setZones([]);
    setIndicators([]);
    client.bars(symbol, timeframe, requestStart, requestEnd)
      .then((nextBars) => {
        if (current) setBars(activeWindow ? filterWindowBars(nextBars, activeWindow) : nextBars);
      })
      .catch((cause: Error) => { if (current) setError(cause.message); })
      .finally(() => { if (current) setLoading(false); });
    client.zones(symbol, timeframe, requestEnd)
      .then((nextZones) => { if (current) setZones(nextZones); })
      .catch((cause: Error) => { if (current) setError(`支撑阻力加载失败：${cause.message}`); });
    (client.indicators?.(symbol, timeframe, requestStart, requestEnd) ?? Promise.resolve([]))
      .then((nextIndicators) => { if (current) setIndicators(nextIndicators); })
      .catch((cause: Error) => { if (current) setError(`技术指标加载失败：${cause.message}`); });
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
          <DataDateInput label="K线数据日期" value={dataDate} onChange={value=>{setDataDate(value);setDrillStack([]);}} />
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
          <ChartNotes key={symbol} symbol={symbol} timeframe={timeframe} start={requestStart} end={requestEnd} capture={() => noteCapture.current?.()} disabled={loading || !bars.length} />
        </div>}
        {!benchmarkEnabled && <div className="indicator-toolbar" aria-label="形态识别">
          <span>两年日线形态</span>
          {[["ascending","上升三角形"],["descending","下降三角形"],["range","震荡区间"]].map(([kind,label])=><button key={kind} type="button" className="indicator-chip" style={{color: kind === "ascending" ? "#f3c969" : kind === "descending" ? "#b49aff" : "#6bc5ff", borderColor: shapeKinds.includes(kind) ? (kind === "ascending" ? "#f3c969" : kind === "descending" ? "#b49aff" : "#6bc5ff") : undefined}} aria-pressed={shapeKinds.includes(kind)} onClick={()=>{setTimeframe("1d");setDrillStack([]);setShapeKinds(current=>current.includes(kind)?current.filter(k=>k!==kind):[...current,kind]);}}>{shapeKinds.includes(kind)?"✓ ":""}{label}</button>)}
          {shapeBusy ? <span role="status">正在识别当前股票…</span> : shapesEnabled && shapeResult?.key===shapeKey ? <span>识别到 {shapeMarks.length} 段 · 不要求突破</span> : <span>按需开启，仅计算当前股票</span>}
          {shapeError&&<span role="alert">形态识别失败：{shapeError}</span>}
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
            <Chart captureRef={noteCapture} viewKey={`${symbol}:${timeframe}:${requestStart}:${requestEnd}`} bars={bars} zones={zones} indicators={indicators} selectedIndicators={selectedIndicators} marks={[...(historyWave && symbol === initialSymbol && timeframe === "1d" ? [{ metric: "close", timeframe: "1d" as const, date: historyWave.end, startDate: historyWave.start, periods: historyWave.days + 1, label: "命中历史波段" }] : watchSource && symbol === initialSymbol ? sourceMarks(watchSource).filter((mark) => mark.timeframe === timeframe && !shapeMarks.some(shape=>JSON.stringify(shape.shape)===JSON.stringify(mark.shape))) : []), ...shapeMarks]} drawing={kind !== null} onAnchor={addAnchor} onBarSelect={selectBar} />
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
      {client === api && (showOverview || symbol !== initialSymbol) && <StockOverview key={symbol} symbol={symbol} />}
    </main>
  );
}
