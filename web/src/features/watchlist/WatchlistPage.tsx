import { useEffect, useState } from "react";
import { api } from "../../api";
import { MarketSearch } from "./MarketSearch";
import { WatchlistConditions } from "./WatchlistConditions";
import { StockOverview } from "../stock/StockOverview";
import { ChartPage } from "../chart/ChartPage";
import { HistoryWaves } from "./HistoryWaves";
import { sourceMarks, type WatchItem, type SourceNode, type WatchGroup } from "./model";
import { describe } from "../screener/presentation";
import type { Evaluation, MetricSpec } from "../../types";

function SourceExplanation({ node, result, catalog }: { node: SourceNode; result: Evaluation; catalog: MetricSpec[] }) {
  if (node.children) return <div style={{ paddingLeft: 16, borderLeft: "2px solid #394247" }}>
    <p>{node.label && <strong>{node.label} · </strong>}{node.logic === "and" ? "全部满足（AND）" : node.logic === "or" ? "任一满足（OR）" : node.logic === "at_least" ? `同日最少满足 ${node.minimumMatches ?? 1} 个策略` : "不满足（NOT）"}</p>
    {node.children.map((child, index) => <SourceExplanation key={index} node={child} result={result.children[index]} catalog={catalog} />)}
  </div>;
  const spec = catalog.find((item) => item.key === node.metric);
  const operators: Record<string, string> = { gt: "大于", gte: "至少", lt: "小于", lte: "至多", eq: "等于", ne: "不等于", in: "属于", not_in: "不属于", continuous: "连续成立", at_least: "最近 N 次至少成立", crosses_above: "上穿", crosses_below: "下穿", between: "介于", not_between: "不介于" };
  const display = (value: unknown): string => Array.isArray(value) ? value.map(display).join("、") : typeof value === "number" ? value.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) : spec?.choices?.find((choice) => choice.value === String(value))?.label ?? String(value ?? "数据不足");
  const rightSpec = catalog.find((item) => item.key === node.right?.metric);
  const comparison = rightSpec ? `${rightSpec.label}${rightSpec.period ? ` ${rightSpec.period}周期` : ""}（${display(result.expected)}）` : display(result.expected);
  const timeframes: Record<string, string> = { "1d": "日线", "1w": "周线", "1mo": "月线", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟", "60m": "60分钟" };
  return <p>{result.result === "true" ? "✓" : result.result === "false" ? "✕" : "?"} {spec?.label ?? node.metric}{spec?.period ? ` · ${spec.period}周期` : ""}（{timeframes[node.timeframe ?? ""] ?? node.timeframe}） {node.lookback ? `最近 ${node.lookback} 周期，` : ""}{operators[node.operator ?? ""] ?? node.operator} {comparison}{spec?.unit === "percent" ? "%" : ""}；实际 {display(result.actual)}{spec?.unit === "percent" ? "%" : ""}</p>;
}

export function WatchlistPage() {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [previewGroup, setPreviewGroup] = useState("");
  const [preview, setPreview] = useState<WatchItem>();
  const [matchedSymbols, setMatchedSymbols] = useState<string[] | null>(null);
  const [filterRevision, setFilterRevision] = useState(0);
  const [selected, setSelected] = useState<string>();
  const [sourceIndex, setSourceIndex] = useState(0);
  const [error, setError] = useState("");
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [groups, setGroups] = useState<WatchGroup[]>([]);
  const [groupFilter, setGroupFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [groupName, setGroupName] = useState("");
  const [editingGroup, setEditingGroup] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState("");
  const refresh = async () => {
    setMatchedSymbols(null); setFilterRevision(value => value + 1);
    const [nextItems, nextGroups] = await Promise.all([api.watchlist(), api.watchGroups()]);
    setItems(nextItems); setGroups(nextGroups);
  };
  useEffect(() => {
    let active = true, pending = false, queued = false;
    const poll = async () => {
      if (pending) { queued = true; return; }
      pending = true;
      try {
        const [nextItems, nextGroups] = await Promise.all([api.watchlist(), api.watchGroups()]);
        if (active) {
          setItems(nextItems); setGroups(nextGroups); setError("");
          setRefreshedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
        }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "更新失败，保留上次数据"); }
      finally { pending = false; if (active) { setLoading(false); if (queued) { queued = false; void poll(); } } }
    };
    const events = new EventSource("/api/market-updates");
    const refreshOnUpdate = () => { void poll(); };
    events.addEventListener("ready", refreshOnUpdate);
    events.addEventListener("market-updated", refreshOnUpdate);
    events.onerror = () => { if (active) { setLoading(false); setError("行情更新通知连接中断，正在自动重连"); } };
    return () => { active = false; events.close(); };

  }, []);
  useEffect(() => { api.catalog().then(setCatalog).catch((cause: Error) => setError(cause.message)); }, []);
  const mutate = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setBusy(false); }
  };
  const visible = items.filter((entry) => (matchedSymbols === null || matchedSymbols.includes(entry.symbol)) && (groupFilter === "all" || (groupFilter === "ungrouped" ? !entry.groups?.length : entry.groups?.some((group) => group.id === groupFilter))) && `${entry.name} ${entry.symbol}`.toLowerCase().includes(search.trim().toLowerCase()));
  const open = (entry: WatchItem) => {
    setSelected(entry.symbol);
    setSourceIndex(entry.sources.reduce((best, source, index) => source.as_of >= entry.sources[best].as_of ? index : best, 0));
  };
  const item = items.find((entry) => entry.symbol === selected) ?? (preview?.symbol === selected ? preview : undefined);
  const source = item?.sources[sourceIndex];
  const remove = async (symbol: string) => {
    try {
      await api.removeWatchlist(symbol);
      setItems((previous) => previous.filter((entry) => entry.symbol !== symbol));
      if (selected === symbol) setSelected(undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "移除失败"); }
  };
  return <div className="watchlist-page" style={{ minWidth: 0, flex: 1 }}>
    <section style={{ padding: "24px 32px" }}>
      <div className="watch-heading">
        <div><p className="watch-eyebrow">我的观察列表</p><h1>{item ? item.name : "自选股"} <small>{item ? item.symbol : `${items.length} 只`}</small></h1></div>
        {item && <button className="ghost-button" onClick={() => setSelected(undefined)}>返回自选股</button>}
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {!item && <>
        <MarketSearch items={items} groups={groups} onAdded={refresh} onOpen={(stock, groupId) => { setPreviewGroup(groupId ?? ""); setPreview({ ...stock, sources: [], groups: [] }); setSelected(stock.symbol); setSourceIndex(0); }} />
        <p className="watch-update">最新价与涨跌幅采用腾讯报价及昨收价 · 行情不可用时标明本地历史数据 · 进入页面及行情更新完成后刷新{refreshedAt && ` · 页面更新于 ${refreshedAt}`}</p>
        <div className="watch-toolbar">
          <nav aria-label="自选股分组">
            <button className={groupFilter === "all" ? "watch-tab active" : "watch-tab"} onClick={() => { setGroupFilter("all"); setMatchedSymbols(null); }}>全部 {items.length}</button>
            <button className={groupFilter === "ungrouped" ? "watch-tab active" : "watch-tab"} onClick={() => { setGroupFilter("ungrouped"); setMatchedSymbols(null); }}>未分组</button>
            {groups.map((group) => <button key={group.id} className={groupFilter === group.id ? "watch-tab active" : "watch-tab"} onClick={() => { setGroupFilter(group.id); setMatchedSymbols(null); }}>{group.name} {items.filter((entry) => entry.groups?.some((value) => value.id === group.id)).length}</button>)}
          </nav>
          <input aria-label="搜索自选股" placeholder="在当前自选中查找" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
        <WatchlistConditions key={`${groupFilter}:${filterRevision}`} catalog={catalog} group={groupFilter} onResult={setMatchedSymbols} />
        <details className="watch-group-manager"><summary>管理我的分组</summary>
          <form onSubmit={(event) => { event.preventDefault(); void mutate(async () => { if (editingGroup) await api.renameWatchGroup(editingGroup, groupName); else await api.createWatchGroup(groupName); setGroupName(""); setEditingGroup(undefined); }); }}>
            <input aria-label="分组名称" maxLength={40} placeholder="例如：芯片观察" value={groupName} onChange={(event) => setGroupName(event.target.value)} />
            <button disabled={busy || !groupName.trim()}>{editingGroup ? "保存名称" : "创建分组"}</button>
            {editingGroup && <button type="button" onClick={() => { setEditingGroup(undefined); setGroupName(""); }}>取消改名</button>}
          </form>
          <p>一只股票可以加入多个分组。删除分组只解除归属，股票仍保留在自选股中。</p>
          {groups.map((group) => <div className="watch-group-edit" key={group.id}><span>{group.name}</span><button disabled={busy} onClick={() => { setEditingGroup(group.id); setGroupName(group.name); }}>改名</button><button disabled={busy} onClick={() => void mutate(async () => { await api.deleteWatchGroup(group.id); if (groupFilter === group.id) { setGroupFilter("all"); setMatchedSymbols(null); }; if (editingGroup === group.id) { setEditingGroup(undefined); setGroupName(""); } })}>删除分组</button></div>)}
        </details>
        {loading ? <p role="status">正在加载自选股…</p> : !items.length ? <p>在条件选股结果中点击“+ 自选”，即可保留股票及入选条件。</p> : !visible.length && <p>当前分组或搜索条件下没有股票。</p>}
        <div className="results-table-wrap"><table className="results-table watch-table">
          <thead><tr><th>股票</th><th>最新价</th><th>涨跌幅</th><th>入选依据（加入时）</th><th>我的分组</th><th>操作</th></tr></thead>
          <tbody>{visible.map((entry) => {
            const latest = [...entry.sources].sort((a, b) => b.as_of.localeCompare(a.as_of))[0];
            const quote = entry.current_quote ?? entry.quote;
            const suspended = entry.trading_status?.is_suspended && (!quote || entry.trading_status.date >= quote.date);
            const change = suspended ? null : quote?.change_percent;
            return <tr key={entry.symbol}>
              <td><button className="watch-stock-name" onClick={() => open(entry)}><strong>{entry.name}</strong><span>{entry.symbol}</span></button></td>
              <td className="watch-number">{quote?.close?.toFixed(2) ?? "—"}<small>{entry.current_quote ? `行情 ${entry.current_quote.timestamp.slice(0, 19).replace("T", " ")}` : entry.quote ? `最近成交 ${entry.quote.date}` : "暂无行情"}</small></td>
              <td className={`watch-number ${change == null || change === 0 ? "" : change > 0 ? "watch-up" : "watch-down"}`}>{suspended ? "停牌" : change == null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(2)}%`}{!suspended && <small>{entry.current_quote ? `相对昨收 · ${entry.current_quote.date}` : "历史涨跌幅 · 非实时"}</small>}{entry.trading_status && <small>状态截至 {entry.trading_status.date}</small>}</td>
              <td className="watch-reason">{latest ? <><p>{describe(latest.tree, catalog)}</p><small>{latest.as_of} · {entry.sources.length} 次入选记录</small></> : <span>手动加入</span>}</td>
              <td><div className="watch-tags">{entry.groups?.length ? entry.groups.map((group) => <span key={group.id}>{group.name}</span>) : <span>未分组</span>}</div>
                <details className="watch-membership"><summary>设置分组</summary>{groups.length ? groups.map((group) => <label key={group.id}><input type="checkbox" disabled={busy} checked={entry.groups?.some((value) => value.id === group.id) ?? false} onChange={(event) => {
                  const ids = entry.groups?.map((value) => value.id) ?? [];
                  void mutate(() => api.setWatchGroups(entry.symbol, event.target.checked ? [...ids, group.id] : ids.filter((id) => id !== group.id)));
                }} />{group.name}</label>) : <p>请先在“管理我的分组”中创建分组。</p>}</details>
              </td>
              <td><div className="watch-row-actions"><button onClick={() => open(entry)}>查看详情</button><button disabled={busy} onClick={() => void remove(entry.symbol)}>移除自选</button></div></td>
            </tr>;
          })}</tbody>
        </table></div>
      </>}
      {item && <ChartPage showOverview={false} key={`${item.symbol}:${sourceIndex}`} initialSymbol={item.symbol} watchSource={source ? { ...source, marks: sourceMarks(source).map((mark) => {
      const spec = catalog.find((entry) => entry.key === mark.metric);
      const metricLabel = `${spec?.label ?? mark.metric}${spec?.period ? ` ${spec.period}周期` : ""}`;
      return { ...mark, metricLabel, label: `${metricLabel} · ${mark.label}` };
    }) } : undefined} />}
      {item && <div>
        <StockOverview key={item.symbol} symbol={item.symbol} />
        {!items.some(entry => entry.symbol === item.symbol) && <div className="watch-row-actions"><select aria-label="详情添加目标分组" value={previewGroup} onChange={event => setPreviewGroup(event.target.value)}><option value="">仅加入自选</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select><button className="ghost-button" disabled={busy} onClick={() => void mutate(() => api.addWatchlist(item.symbol, undefined, previewGroup || undefined))}>加入自选</button></div>}
        {item.sources.length > 0 && <label>入选记录 <select aria-label="入选记录" value={sourceIndex} onChange={(event) => setSourceIndex(Number(event.target.value))}>
          {item.sources.map((entry, index) => <option key={entry.run_id} value={index}>{entry.as_of} · {entry.mode === "live" ? "盘中" : "收盘"} · 第 {index + 1} 次</option>)}
        </select></label>}
        {source && <p>金色框与圆点表示这次入选的条件依据；切换对应周期可查看标注。盘中入选记录可能与最终收盘图形不同。</p>}
        {source && <details open><summary>入选条件与成立结果</summary>{source.confluence_dates && source.confluence_dates.length > 0 && <p>同日最少满足 {source.minimum_matches ?? 1} 个策略：{source.confluence_dates.join('、')}</p>}<SourceExplanation node={source.tree} result={source.explanation} catalog={catalog} /></details>}
      </div>}
    </section>
    {item && items.some(entry => entry.symbol === item.symbol) && <HistoryWaves key={item.symbol} symbol={item.symbol} catalog={catalog} />}

  </div>;
}
