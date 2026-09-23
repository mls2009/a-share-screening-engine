import { useEffect, useState } from "react";
import { api } from "../../api";
import type { SymbolSearchResult } from "../../types";
import type { WatchGroup, WatchItem } from "./model";

export function MarketSearch({ items, groups, onAdded, onOpen }: { items: WatchItem[]; groups: WatchGroup[]; onAdded: () => Promise<void>; onOpen: (stock: SymbolSearchResult, groupId?: string) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const [group, setGroup] = useState("");
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string>();
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    setResults([]); setMessage(""); setLoading(Boolean(query.trim()));
    const timer = setTimeout(() => {
      if (!query.trim()) return;
      api.searchSymbols(query.trim()).then(value => { if (active) setResults(value); })
        .catch((cause: Error) => { if (active) setMessage(cause.message); })
        .finally(() => { if (active) setLoading(false); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [query]);
  const add = async (symbol: string) => {
    setAdding(symbol); setMessage("");
    try { await api.addWatchlist(symbol, undefined, group || undefined); await onAdded(); setMessage("已加入自选" + (group ? "及所选分组" : "")); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : "添加失败"); }
    finally { setAdding(undefined); }
  };
  return <section className="watch-market-search" aria-label="全市场添加自选">
    <div className="watch-market-controls"><label>从全市场添加<input aria-label="全市场股票搜索" placeholder="输入股票代码或名称，例如 600519" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label>加入分组<select aria-label="搜索添加目标分组" value={group} onChange={event => setGroup(event.target.value)}><option value="">仅加入自选</option>{groups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>
    {loading && <p role="status">正在搜索全市场…</p>}
    {message && <p role="status">{message}</p>}
    {!loading && query.trim() && !results.length && !message && <p>未找到匹配的股票，请检查代码或名称。</p>}
    <div className="watch-market-results">{results.map(stock => {
      const existing = items.find(item => item.symbol === stock.symbol);
      const alreadyAdded = Boolean(existing && (!group || existing.groups?.some(item => item.id === group)));
      return <div key={stock.symbol}><button className="watch-stock-name" onClick={() => onOpen(stock, group || undefined)}><strong>{stock.name}</strong><span>{stock.symbol}</span></button><button disabled={Boolean(adding) || alreadyAdded} onClick={() => void add(stock.symbol)}>{adding === stock.symbol ? "添加中…" : alreadyAdded ? "已添加" : existing ? "加入此分组" : "加入自选"}</button></div>;
    })}</div>
  </section>;
}
