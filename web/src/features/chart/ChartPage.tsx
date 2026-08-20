import { Search, Trash2 } from "lucide-react";
import { type ComponentType, useEffect, useRef, useState } from "react";

import { api } from "../../api";
import type { Bar, PriceZone, Timeframe } from "../../types";
import { DrawingToolbar } from "./DrawingToolbar";
import { zonePresentation } from "./chartOptions";
import { type DrawingAnchor, type DrawingGeometry, type DrawingKind, buildManualZonePayload } from "./drawing";
import { StockChart, type StockChartProps } from "./StockChart";
import { TimeframeToolbar } from "./TimeframeToolbar";

export interface ChartClient {
  bars(symbol: string, timeframe: Timeframe, start: string, end: string): Promise<Bar[]>;
  zones(symbol: string, timeframe: Timeframe, asOf: string): Promise<PriceZone[]>;
  createManualZone(symbol: string, payload: object): Promise<PriceZone>;
  deleteZone(symbol: string, zoneId: string): Promise<void>;
}

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
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [bars, setBars] = useState<Bar[]>([]);
  const [zones, setZones] = useState<PriceZone[]>([]);
  const [kind, setKind] = useState<DrawingKind | null>(null);
  const [geometry, setGeometry] = useState<DrawingGeometry>("horizontal");
  const [anchors, setAnchors] = useState<DrawingAnchor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const deletingZoneIdsRef = useRef(new Set<string>());
  const [deletingZoneIds, setDeletingZoneIds] = useState(new Set<string>());

  useEffect(() => {
    let current = true;
    const [start, end] = range(timeframe);
    setLoading(true); setError("");
    Promise.all([client.bars(symbol, timeframe, start, end), client.zones(symbol, timeframe, end)])
      .then(([nextBars, nextZones]) => { if (current) { setBars(nextBars); setZones(nextZones); } })
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

  return (
    <main className="chart-page">
      <header className="chart-heading">
        <div><p className="eyebrow">PRICE STRUCTURE / DRAWING DESK</p><h1>K 线研究</h1></div>
        <form onSubmit={(event) => { event.preventDefault(); setSymbol(symbolInput.trim().toUpperCase()); }}>
          <Search size={15} /><input aria-label="证券代码" value={symbolInput} onChange={(event) => setSymbolInput(event.target.value)} /><button type="submit">打开</button>
        </form>
      </header>
      <section className="chart-desk">
        <div className="chart-topline"><div><strong>{symbol}</strong><span>{bars.length ? `${bars.at(-1)?.close.toFixed(2)} 元` : "—"}</span></div><TimeframeToolbar value={timeframe} onChange={(next) => { setTimeframe(next); setAnchors([]); }} /></div>
        <DrawingToolbar kind={kind} geometry={geometry} anchors={anchors.length} onKindChange={(next) => { setKind(next); setAnchors([]); }} onGeometryChange={(next) => { setGeometry(next); setAnchors([]); }} onCancel={() => { setKind(null); setAnchors([]); }} />
        {error && <div className="error-banner" role="alert">{error}</div>}
        <div className="chart-canvas-wrap">
          {loading ? (
            <div className="chart-loading">正在读取行情…</div>
          ) : !bars.length ? (
            <div className="chart-loading">该周期暂无本地 K 线数据</div>
          ) : (
            <Chart bars={bars} zones={zones} drawing={kind !== null} onAnchor={addAnchor} />
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
