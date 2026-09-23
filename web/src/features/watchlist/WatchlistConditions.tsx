import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { MetricSpec, ScreenRunResult, UiNode } from "../../types";
import { ConditionTree } from "../screener/ConditionTree";
import { createCondition, createGroup, toApiNode } from "../screener/treeModel";
import { ConditionJsonImport } from "../backtest/ConditionJsonImport";

export function WatchlistConditions({ catalog, group, onResult }: { catalog: MetricSpec[]; group: string; onResult: (symbols: string[] | null) => void }) {
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const [tree, setTree] = useState<UiNode>(() => ({ ...createGroup(), children: [{ ...createCondition("pe_ratio"), operator: "lt" }] }));
  const [mode, setMode] = useState<"live" | "close">("live");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<ScreenRunResult>();
  const clear = () => { setResult(undefined); setMessage(""); onResult(null); };
  const run = async () => {
    setBusy(true); clear();
    try {
      const asOf = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());
      const value = await api.runScreen({ tree: toApiNode(tree, catalog), mode, as_of: asOf, scope: "watchlist", watch_group_id: ["all", "ungrouped"].includes(group) ? undefined : group, watch_ungrouped: group === "ungrouped", limit: 1000 });
      const symbols = value.matches.map(item => item.symbol);
      for (let offset = symbols.length; offset < value.match_count; offset += 1000) {
        const page = await api.screenResults(value.run_id, 1000, offset);
        symbols.push(...page.matches.map(item => item.symbol));
      }
      if (active.current) { setResult(value); onResult(symbols); }
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "筛选失败"); }
    finally { setBusy(false); }
  };
  return <details className="watch-condition-filter"><summary>按条件筛选当前自选分组</summary>
    <p>与条件选股使用相同规则。市盈率、市净率、市值等当前指标请选择“实时行情”；筛选只改变列表显示，不移除自选。</p>
    <fieldset disabled={busy}><label>数据模式<select aria-label="自选筛选数据模式" value={mode} onChange={event => { setMode(event.target.value as "live" | "close"); clear(); }}><option value="live">实时行情</option><option value="close">本地收盘数据</option></select></label>
      <ConditionJsonImport label="自选筛选" catalog={catalog} onImport={value => { setTree(value); clear(); }} />
      <ConditionTree tree={tree} catalog={catalog} onChange={value => { setTree(value); clear(); }} />
      <div className="watch-row-actions"><button className="run-button" disabled={!catalog.length} onClick={() => void run()}>{busy ? "筛选中…" : "筛选当前分组"}</button><button onClick={clear}>清除筛选</button></div>
    </fieldset>
    {message && <p className="error-banner" role="alert">{message}</p>}
    {result && <p role="status">符合条件 {result.match_count} 只 · {mode === "live" ? `取得行情 ${result.realtime_covered ?? 0} 只` : "使用本地收盘数据"} · 不符合或数据不足的股票仍保留在自选中。</p>}
    {result?.diagnostics?.warnings.map(warning => <p className="stale-banner" key={warning}>{warning}</p>)}
  </details>;
}
