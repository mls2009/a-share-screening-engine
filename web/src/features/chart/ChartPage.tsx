import { Search, Trash2 } from "lucide-react";
import { type ComponentType, useEffect, useRef, useState } from "react";

import { api } from "../../api";
import type { Bar, ChartIndicator, ChartIndicatorPoint, PriceZone, SymbolSearchResult, Timeframe } from "../../types";
import { DrawingToolbar } from "./DrawingToolbar";
import { zonePresentation } from "./chartOptions";
import { type DrawingAnchor, type DrawingGeometry, type DrawingKind, buildManualZonePayload } from "./drawing";
import { StockChart, type StockChartProps } from "./StockChart";
import { TimeframeToolbar } from "./TimeframeToolbar";

export interface ChartClient {
  searchSymbols(query: string): Promise<SymbolSearchResult[]>;
  bars(symbol: string, timeframe: Timeframe, start: string, end: string): Promise<Bar[]>;
  indicators?(symbol: string, timeframe: Timeframe, start: string, end: string): Promise<ChartIndicatorPoint[]>;
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
}: {
  initialSymbol?: string;
  client?: ChartClient;
  Chart?: ComponentType<StockChartProps>;
}) {
  const [symbolInput, setSymbolInput] = useState(initialSymbol);
  const [symbol, setSymbol] = useState(initialSymbol);
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([]);
  const [searchActive, setSearchActive] = useState(false);
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [bars, setBars] = useState<Bar[]>([]);
  const [indicators, setIndicators] = useState<ChartIndicatorPoint[]>([]);
  const [selectedIndicators, setSelectedIndicators] = useState<ChartIndicator[]>(["ma"]);
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [zones, setZones] = useState<PriceZone[]>([]);
  const [kind, setKind] = useState<DrawingKind | null>(null);
  const [geometry, setGeometry] = useState<DrawingGeometry>("horizontal");
  const [anchors, setAnchors] = useState<DrawingAnchor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const deletingZoneIdsRef = useRef(new Set<string>());
  const [deletingZoneIds, setDeletingZoneIds] = useState(new Set<string>());

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
    const [start, end] = range(timeframe);
    setLoading(true); setError("");
    Promise.all([
      client.bars(symbol, timeframe, start, end),
      client.zones(symbol, timeframe, end),
      client.indicators?.(symbol, timeframe, start, end) ?? Promise.resolve([]),
    ])
      .then(([nextBars, nextZones, nextIndicators]) => {
        if (current) {
          setBars(nextBars); setZones(nextZones); setIndicators(nextIndicators);
        }
      })
      .catch((cause: Error) => { if (current) setError(cause.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [client, symbol, timeframe]);

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

  return (
    <main className="chart-page">
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
      <section className="chart-desk">
        <div className="chart-topline"><div><strong>{symbol}</strong><span>{bars.length ? `${bars.at(-1)?.close.toFixed(2)} 元` : "—"}</span></div><TimeframeToolbar value={timeframe} onChange={(next) => { setTimeframe(next); setAnchors([]); }} /></div>
        <div className="indicator-toolbar">
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
        </div>
        <DrawingToolbar kind={kind} geometry={geometry} anchors={anchors.length} onKindChange={(next) => { setKind(next); setAnchors([]); }} onGeometryChange={(next) => { setGeometry(next); setAnchors([]); }} onCancel={() => { setKind(null); setAnchors([]); }} />
        {error && <div className="error-banner" role="alert">{error}</div>}
        <div className="chart-canvas-wrap">
          {loading ? (
            <div className="chart-loading">正在读取行情…</div>
          ) : !bars.length ? (
            <div className="chart-loading">该周期暂无本地 K 线数据</div>
          ) : (
            <Chart bars={bars} zones={zones} indicators={indicators} selectedIndicators={selectedIndicators} drawing={kind !== null} onAnchor={addAnchor} />
          )}
        </div>
      </section>
      <section className="zone-ledger">
        <div className="section-title"><div><span>支撑压力线</span><em>{zones.length}</em></div><p><i className="support-dot" />支撑<i className="resistance-dot" />压力<span className="normal-line" />正常实线<span className="reappeared-line" />删除后重现虚线</p></div>
        <div className="zone-list">
          {zones.map((zone) => {
            const { label } = zonePresentation(zone);
            const className = zone.zone_kind === "uptrend" ? "support" : zone.zone_kind === "downtrend" ? "resistance" : zone.zone_kind;
            return <div key={zone.zone_id} className={className}><span>{label}</span><b>{zone.center_price.toFixed(2)}</b><small>{zone.touches} 次触及</small><button type="button" aria-label={`删除${label} ${zone.zone_id}`} disabled={deletingZoneIds.has(zone.zone_id)} onClick={() => remove(zone)}><Trash2 size={14} /></button></div>;
          })}
          {!zones.length && <div className="result-empty">当前窗口内尚未识别到有效支撑压力线。</div>}
        </div>
      </section>
    </main>
  );
}
