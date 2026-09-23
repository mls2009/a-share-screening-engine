import { useState } from "react";
import { api } from "../../api";
import type { MetricSpec, UiNode } from "../../types";
import { ConditionTree } from "../screener/ConditionTree";
import { createGroup, fromApiNode, toApiNode } from "../screener/treeModel";
import { ChartPage } from "../chart/ChartPage";

interface Wave { start: string; end: string; days: number; start_price: number | null; end_price: number | null; gain: number | null }
export interface WaveResult { matches: Wave[]; total: number; matched_days: number; bars: number; unknown: number; start: string | null; end: string | null }
export function HistoryWaves({ symbol, catalog }: { symbol: string; catalog: MetricSpec[] }) {
  const storageKey = `astock-history-conditions:v2:${symbol}`;
  const [tree, setTree] = useState<UiNode>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) ?? "null") ?? createGroup(); }
    catch { return createGroup(); }
  });
  const [result, setResult] = useState<WaveResult>();
  const [selected, setSelected] = useState<Wave>();
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [importing, setImporting] = useState(false);
  const metrics = catalog.filter((metric) => (["price", "activity", "technical", "trend"].includes(metric.group ?? "") || metric.key.startsWith("pa_")) && metric.supported_modes?.includes("backtest") && !["support_distance", "resistance_distance"].includes(metric.key) && metric.timeframes.includes("1d")).map((metric) => ({ ...metric, timeframes: ["1d" as const] }));
  const applyJson = async () => {
    setImportError(""); setImporting(true);
    try {
      const parsed: unknown = JSON.parse(importText);
      const validation = await api.validateScreen(parsed);
      if (!validation.valid) throw new Error(validation.errors[0]?.message ?? "条件 JSON 校验失败");
      const imported = fromApiNode(parsed, catalog);
      const check = (node: UiNode): void => {
        if (node.kind === "group") { node.children.forEach(check); return; }
        const operands = [node, ...(node.right.kind === "metric" ? [node.right] : [])];
        for (const operand of operands) {
          if (operand.timeframe !== "1d") throw new Error("历史条件扫描仅支持日线，请修改条件周期后导入");
          if (!metrics.some((metric) => metric.key === operand.metric)) throw new Error(`历史条件扫描不支持指标：${catalog.find((metric) => metric.key === operand.metric)?.label ?? operand.metric}`);
        }
      };
      check(imported);
      setTree(imported.kind === "group" ? imported : { ...createGroup(), children: [imported] });
      setResult(undefined); setSelected(undefined); setPage(0); setMessage(""); setImportOpen(false);
    } catch (error) { setImportError(error instanceof Error ? error.message : "条件 JSON 导入失败"); }
    finally { setImporting(false); }
  };
  const exportJson = () => {
    try {
      const blob = new Blob([JSON.stringify(toApiNode(tree, metrics), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `${symbol}-conditions.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setMessage(error instanceof Error ? error.message : "导出失败"); }
  };
  const run = async () => {
    setBusy(true); setMessage(""); setResult(undefined); setSelected(undefined); setPage(0);
    try { setResult(await api.historyWaves(symbol, { tree: toApiNode(tree, metrics) })); }
    catch (error) { setMessage(error instanceof Error ? error.message : "扫描失败"); }
    finally { setBusy(false); }
  };
  return <section className="history-waves">
    <h2>历史波段筛选</h2>
    <p>像条件选股一样组合指标，逐日检查本股历史；连续满足条件的交易日合并成区间，单日命中也保留。不满足或数据不足会断开区间。</p>
    <p>支持日线价格、成交活跃度和技术指标。使用本地前复权行情，每天只读取当日及之前的数据。</p>
    <div className="wave-controls">
      <button type="button" className="ghost-button" disabled={busy || importing || !metrics.length} onClick={() => { setImportOpen((open) => !open); setImportError(""); }}>导入 JSON</button>
      <button type="button" className="ghost-button" disabled={busy || importing || !metrics.length} onClick={exportJson}>导出 JSON</button>
    </div>
    {importOpen && <div className="json-import-panel" role="dialog" aria-label="JSON 条件导入">
      <div><strong>导入条件 JSON</strong><span>支持条件选股的 JSON 格式；校验通过后替换当前条件。</span></div>
      <textarea aria-label="条件 JSON" disabled={importing} value={importText} onChange={(event) => setImportText(event.target.value)} />
      <div className="json-import-actions">
        <label className="file-button">选择文件<input aria-label="选择 JSON 文件" type="file" accept="application/json,.json" disabled={importing} onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void file.text().then(setImportText).catch(() => setImportError("读取 JSON 文件失败"));
          event.target.value = "";
        }} /></label>
        <button type="button" disabled={importing} onClick={() => setImportOpen(false)}>取消</button>
        <button type="button" className="run-button" disabled={importing || !importText.trim()} onClick={() => void applyJson()}>{importing ? "校验中…" : "应用 JSON"}</button>
      </div>
      {importError && <p role="alert" className="error-banner">{importError}</p>}
    </div>}
    <fieldset disabled={busy || importing} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
      <ConditionTree tree={tree} catalog={metrics} onChange={(next) => { setTree(next); setResult(undefined); setSelected(undefined); setPage(0); setMessage(""); }} />
    </fieldset>
    <div className="wave-controls">
      <button className="run-button" disabled={busy || importing || !metrics.length} onClick={() => void run()}>{busy ? "正在扫描历史…" : "扫描历史条件"}</button>
      <button onClick={() => { try { localStorage.setItem(storageKey, JSON.stringify(tree)); setMessage("规则已保存到当前浏览器的这只自选股"); } catch { setMessage("保存失败：浏览器存储不可用"); } }}>保存本股规则</button>
    </div>
    {message && <p role="status">{message}</p>}
    {result && <>
      <p>命中 {result.matched_days} 天 · {result.total} 个连续区间 · 扫描 {result.bars} 根日线 · {result.start ?? "暂无数据"} ～ {result.end ?? "暂无数据"}{result.unknown > 0 ? ` · ${result.unknown} 天数据不足，未计入命中` : ""}</p>
      {result.total === 0 && <p>这段历史中没有符合条件的日期，可调整条件后重新扫描。</p>}
      <div className="results-table-wrap"><table className="results-table"><thead><tr><th>起点</th><th>终点</th><th>命中天数（含首尾）</th><th>起点收盘</th><th>终点收盘</th><th>区间涨跌幅</th><th>操作</th></tr></thead>
        <tbody>{result.matches.slice(page * 50, (page + 1) * 50).map((wave) => <tr key={`${wave.start}:${wave.end}`}><td>{wave.start}</td><td>{wave.end}</td><td>{wave.days}</td><td>{wave.start_price?.toFixed(2) ?? "—"}</td><td>{wave.end_price?.toFixed(2) ?? "—"}</td><td>{wave.gain === null ? "—" : `${wave.gain.toFixed(2)}%`}</td><td><button onClick={() => setSelected(wave)}>定位 K 线</button></td></tr>)}</tbody>
      </table></div>
      <div className="wave-controls"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.max(1, Math.ceil(result.total / 50))}</span><button disabled={(page + 1) * 50 >= result.total} onClick={() => setPage(page + 1)}>下一页</button></div>
    </>}
    {selected && <ChartPage key={`${symbol}:${selected.start}:${selected.end}`} initialSymbol={symbol} focusMark={{ metric: "close", timeframe: "1d", date: selected.end, startDate: selected.start, periods: selected.days, label: "命中波段" }} historyWave={{ ...selected, days: selected.days - 1 }} />}
  </section>;
}
