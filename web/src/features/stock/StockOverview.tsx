import { useEffect, useState } from "react";
import { api } from "../../api";

export interface StockOverviewData {
  symbol: string; name: string; exchange: string; board: string | null; listed_on: string | null;
  quote: { timestamp: string; source: string; price: number; previous_close?: number | null; open?: number | null; high?: number | null; low?: number | null; volume_shares: number; amount_cny: number; pe_ratio?: number | null; pb_ratio?: number | null; total_market_cap?: number | null; float_market_cap?: number | null; turnover_rate?: number | null; volume_ratio?: number | null } | null;
  message: string | null; valuation_note: string;
}
const number = (value: number | null | undefined, unit = "") => value == null || !Number.isFinite(value) ? "暂无" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}${unit}`;
const amount = (value: number | null | undefined) => value == null ? "暂无" : Math.abs(value) >= 1e8 ? number(value / 1e8, " 亿") : number(value / 1e4, " 万");

export function StockOverview({ symbol }: { symbol: string }) {
  const [data, setData] = useState<StockOverviewData>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setData(undefined); setError(""); setLoading(true);
    api.stockOverview(symbol).then(value => { if (active) setData(value); })
      .catch((cause: Error) => { if (active) setError(cause.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [symbol, revision]);
  const q = data?.quote;
  const change = q?.previous_close ? (q.price / q.previous_close - 1) * 100 : null;
  const fields = [
    ["市盈率（腾讯）", number(q?.pe_ratio, " 倍")], ["市净率", number(q?.pb_ratio, " 倍")],
    ["总市值", amount(q?.total_market_cap)], ["流通市值", amount(q?.float_market_cap)],
    ["换手率", number(q?.turnover_rate, "%")], ["量比", number(q?.volume_ratio, " 倍")],
    ["今开", number(q?.open)], ["昨收", number(q?.previous_close)], ["最高", number(q?.high)], ["最低", number(q?.low)],
    ["成交量（股）", q ? amount(q.volume_shares) : "暂无"], ["成交额（元）", amount(q?.amount_cny)],
  ];
  return <section className="stock-overview" aria-label="股票行情与估值">
    <header><div><h2>{data?.name ?? symbol} <small>{symbol}</small></h2><p>{data?.exchange ?? ""}{data?.listed_on ? ` · 上市日期 ${data.listed_on}` : ""}</p></div><button disabled={loading} onClick={() => setRevision(value => value + 1)}>{loading ? "读取中…" : "刷新行情"}</button></header>
    <div className={`stock-overview-price ${change == null || change === 0 ? "" : change > 0 ? "watch-up" : "watch-down"}`}><strong>{number(q?.price)}</strong><span>{number(change, "%")}</span></div>
    {(error || data?.message) && <p className="error-banner" role="alert">{error || data?.message}</p>}
    <div className="stock-metric-groups">{[
      { title: "估值指标", tone: "valuation", indices: [0, 1] },
      { title: "市值规模", tone: "capital", indices: [2, 3] },
      { title: "成交活跃度", tone: "activity", indices: [4, 5, 10, 11] },
      { title: "当日价格", tone: "prices", indices: [6, 7, 8, 9] },
    ].map(group => <section className={`stock-metric-group ${group.tone}`} key={group.tone} aria-label={group.title}>
      <h3>{group.title}</h3><dl>{group.indices.map(index => { const [label, value] = fields[index]; return <div key={label}><dt>{label}</dt><dd>{value}</dd></div>; })}</dl>
    </section>)}</div>
    <p className="stock-overview-note">{q ? `行情时间：${q.timestamp.replace("T", " ")} · 来源：${q.source === "tencent" ? "腾讯行情" : q.source} · 当前未复权报价` : "未获取到最新行情，不显示推算估值。"}</p>
    <small>{data?.valuation_note}</small>
  </section>;
}
