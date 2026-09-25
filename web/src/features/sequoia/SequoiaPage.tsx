import { useResultReviews } from "../reviews/useResultReviews";
import { FailureButton } from "../reviews/FailureButton";
import { DataDateInput } from "../../components/DataDateInput";
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { ConditionMark, WatchGroup } from '../watchlist/model';
import { parseConfig, sequoiaApi, type Config, type Match, type Run, type Strategy } from './api';
import { sequoiaChartMarks, STRATEGY_COLORS } from './chartMarks';
import './sequoia.css';

const ChartPage = lazy(() => import('../chart/ChartPage').then(m => ({ default: m.ChartPage })));
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const number = (value: unknown) => typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : String(value ?? '—');
const operators: Record<string, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤', in: '属于' };

export function SequoiaPage() {
  const [catalog, setCatalog] = useState<Strategy[]>([]);
  const [watchGroups, setWatchGroups] = useState<WatchGroup[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [config, setConfig] = useState<Config>({ as_of: '', period: 'latest', scope: 'market', group_id: null, strategies: ['turtle'], minimum_matches: 1, parameters: {} });
  const [run, setRun] = useState<Run>();
  const reviews = useResultReviews("sequoia", run?.run_id);
  const [failedOnly, setFailedOnly] = useState(false);
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [detail, setDetail] = useState<Match>();
  const [focus, setFocus] = useState<ConditionMark>();
  const [hiddenStrategies, setHiddenStrategies] = useState<string[]>([]);
  const [target, setTarget] = useState('strategy');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [sort, setSort] = useState('symbol');
  const [json, setJson] = useState('');
  const detailRef = useRef<HTMLElement>(null);
  const requestVersion = useRef(0);
  useEffect(() => {
    let alive = true;
    Promise.all([sequoiaApi.catalog(), sequoiaApi.groups(), sequoiaApi.history()]).then(([c, g, h]) => {
      if (!alive) return;
      setCatalog(c); setWatchGroups(g); setHistory(h);
      const active = h.find(r => r.status === 'running');
      if (active) setRun(active);
    }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (run?.status !== 'running') return;
    let alive = true;
    const timer = window.setTimeout(() => {
      sequoiaApi.run(run.run_id).then(async next => {
        if (!alive) return;
        if (next.status !== 'running') {
          try { const h = await sequoiaApi.history(); if (alive) setHistory(h); } catch { /* The finished snapshot remains available if history refresh fails. */ }
        }
        if (alive) setRun(next);
      }).catch(e => { if (alive) { setError(e.message); setRun(current => current ? { ...current } : current); } });
    }, 1500);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [run]);
  const running = run?.status === 'running';
  const terminal = run?.status === 'completed' || run?.status === 'partial';
  const visible = (run?.matches ?? []).filter(m => (!filter || m.groups.some(g => g.id === filter)) && (!failedOnly || reviews.symbols.includes(m.symbol))).sort((a, b) => sort === 'change' ? (b.change_percent ?? -Infinity) - (a.change_percent ?? -Infinity) : a.symbol.localeCompare(b.symbol));
  const detailIndex = visible.findIndex(m => m.symbol === detail?.symbol);
  const visibleSelected = selected.filter(s => visible.some(m => m.symbol === s));
  const chartMarks = detail ? sequoiaChartMarks(detail.groups, detail.source.marks).filter(mark => !hiddenStrategies.includes(mark.strategyId ?? '')) : [];
  function view(next: Run) { setFailedOnly(false); setRun(next); setSelected([]); setDetail(undefined); setFocus(undefined); setHiddenStrategies([]); setFilter(''); setNotice(''); }
  async function start() {
    setBusy(true); setError(''); setNotice(''); requestVersion.current++;
    try { view(await sequoiaApi.start({...config,as_of:config.as_of || today()})); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function load(id: string) {
    const version = ++requestVersion.current;
    setError('');
    try { const next = await sequoiaApi.run(id); if (version === requestVersion.current) view(next); }
    catch (e) { if (version === requestVersion.current) setError((e as Error).message); }
  }
  async function add(symbols: string[]) {
    if (!run) return;
    setBusy(true); setError(''); setNotice('');
    try { const result = await sequoiaApi.add(run.run_id, symbols, target); setNotice(`已添加 ${result.added} 只股票，分组依据和图上标注已保存。`); setWatchGroups(await sequoiaApi.groups()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function toggleStrategy(id: string) {
    setConfig(current => { const parameters = { ...current.parameters }; delete parameters[id]; const strategies = current.strategies.includes(id) ? current.strategies.filter(s => s !== id) : [...current.strategies, id]; return { ...current, parameters, strategies, minimum_matches: Math.min(current.minimum_matches ?? 1, Math.max(1, strategies.length)) }; });
  }
  function open(match: Match) { setDetail(match); setFocus(undefined); setHiddenStrategies([]); window.setTimeout(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0); }
  return <main className="sequoia-page">
    <header className="sq-heading"><div><p className="eyebrow">SEQUOIA / STRATEGY SCANNER</p><h1>Sequoia 选股</h1><p>按策略发现股票，沿入选依据回到 K 线。</p></div><a href="https://github.com/sngyai/Sequoia-X" target="_blank" rel="noreferrer">查看原仓库 ↗</a></header>
    {error && <p className="sq-error" role="alert">{error}</p>}{notice && <p className="sq-notice" role="status">{notice}</p>}
    <section className="sq-panel" aria-label="筛选配置"><div className="sq-section-title"><h2>策略分组</h2><span>每个策略独立判断；可设置同日最少命中数</span></div>
      <div className="sq-strategies">{catalog.map((strategy, index) => <article key={strategy.id} className={config.strategies.includes(strategy.id) ? 'sq-strategy chosen' : 'sq-strategy'}>
        <label className="sq-strategy-title"><input type="checkbox" aria-label={`选择策略 ${strategy.name}`} checked={config.strategies.includes(strategy.id)} onChange={() => toggleStrategy(strategy.id)} /><span className="sq-index">0{index + 1}</span><strong>{strategy.name}</strong></label><p>{strategy.description}</p>
        <details><summary>查看 / 调整参数</summary>{Object.entries(strategy.parameters).map(([key, spec]) => <label className="sq-param" key={key}>{spec.label}<input type="number" min={spec.min} max={spec.max} step={spec.integer ? 1 : 'any'} disabled={!config.strategies.includes(strategy.id)} value={config.parameters[strategy.id]?.[key] ?? spec.default} onChange={e => setConfig({ ...config, parameters: { ...config.parameters, [strategy.id]: { ...config.parameters[strategy.id], [key]: e.target.valueAsNumber } } })} /></label>)}</details>
      </article>)}</div>
      <div className="sq-controls"><label>同日最少命中策略数<select aria-label="同日最少命中策略数" value={Math.min(config.minimum_matches ?? 1, Math.max(1, config.strategies.length))} onChange={e => setConfig({ ...config, minimum_matches: Number(e.target.value) })}>{Array.from({length:Math.max(1,config.strategies.length)},(_,index)=><option key={index+1} value={index+1}>至少 {index+1} 个{index===0 ? '（原有方式）' : ''}</option>)}</select></label><DataDateInput label="截至日期" value={config.as_of} onChange={as_of=>setConfig({...config,as_of})} />
        <label>识别时间范围<select aria-label="识别时间范围" value={config.period ?? 'latest'} onChange={e => setConfig({...config,period:e.target.value as Config['period']})}><option value="latest">最新一天（截至所选日期）</option><option value="1y">近一年</option><option value="2y">近两年</option></select></label><label>股票范围<select value={config.scope} onChange={e => setConfig({ ...config, scope: e.target.value as Config['scope'], group_id: null })}><option value="market">全市场 A 股</option><option value="watchlist">我的自选股</option></select></label>
        {config.scope === 'watchlist' && <label>自选范围分组<select value={config.group_id ?? ''} onChange={e => setConfig({ ...config, group_id: e.target.value || null })}><option value="">全部自选</option>{watchGroups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>}
        <button className="sq-primary" disabled={busy || running || !catalog.length || !config.strategies.length || (config.period !== undefined && config.period !== 'latest' && config.strategies.includes('placement'))} onClick={() => void start()}>{running ? '正在分析…' : '开始分组选股'}</button>
      </div>
      <p className="sq-data">选择“至少 2 个”或更多时，必须在同一个交易日满足，不会把不同日期的信号拼在一起。</p>{config.period && config.period !== 'latest' && <p className="sq-data">逐个交易日判断；海龟按阶段计次：收盘跌破首次突破前高才结束，默认只标记首日；RPS 按各历史日的全市场排名计算。定增名单不支持历史范围，请取消该策略后运行。</p>}<details className="sq-json"><summary>JSON 配置导入 / 导出</summary><p>仅用于本板块策略配置。导入后核对策略和日期，再开始筛选。</p><textarea aria-label="Sequoia JSON 配置" value={json} onChange={e => setJson(e.target.value)} placeholder="点击导出当前配置查看格式" /><div className="sq-actions"><button onClick={() => setJson(JSON.stringify(config, null, 2))}>导出当前配置</button><button onClick={() => { try { setConfig(parseConfig(json, catalog)); setError(''); setNotice('配置已导入，尚未运行。'); } catch (e) { setError((e as Error).message); } }}>导入 JSON</button><label className="sq-file">选择 JSON 文件<input type="file" accept=".json,application/json" onChange={async e => { const file = e.target.files?.[0]; if (!file) return; try { const text = await file.text(); setConfig(parseConfig(text, catalog)); setJson(text); setError(''); setNotice('文件已导入，尚未运行。'); } catch (cause) { setError((cause as Error).message); } e.target.value = ''; }} /></label></div></details>
    </section>
    <section className="sq-panel" aria-label="分组筛选结果"><div className="sq-section-title"><h2>筛选结果</h2><label>历史记录 <select aria-label="Sequoia 历史记录" disabled={running || busy} value={history.some(h => h.run_id === run?.run_id) ? run?.run_id : ''} onChange={e => e.target.value && void load(e.target.value)}><option value="">选择运行记录</option>{history.map(h => <option key={h.run_id} value={h.run_id}>{h.config.as_of} · {h.config.period === '1y' ? '近一年' : h.config.period === '2y' ? '近两年' : '单日'} · {h.config.strategies.map(id => catalog.find(s => s.id === id)?.name ?? id).join('/')} · {h.match_count ?? '…'} 只 · {h.run_id.slice(0, 6)}</option>)}</select></label></div>
      {!run ? <p className="sq-empty">选择策略并运行后，在这里按分组查看命中股票和入选依据。</p> : <>
        {running && <div role="status"><progress max="100" value={run.progress} /><p>{run.message} · {run.progress}%</p></div>}
        {run.config.strategies.includes('turtle') && run.turtle_rule !== 'relative_volume_limit_close_fixed_level_v2' && <p className="sq-data">此记录使用旧版海龟规则，旧标记未改写。请复用配置并重新运行，得到相对放量或收盘涨停突破、阶段合并后的结果。</p>}
        {run.error && <p className="sq-error" role="alert">{run.error}</p>}
        <details className="sq-run-config"><summary>查看本次运行配置</summary><pre>{JSON.stringify(run.config, null, 2)}</pre><button disabled={running || busy} onClick={() => {setConfig({...run.config,parameters:Object.fromEntries(Object.entries(run.config.parameters).map(([id,params])=>[id,Object.fromEntries(Object.entries(params).filter(([key])=>catalog.find(s=>s.id===id)?.parameters[key]))]))});setNotice("已载入配置，已移除停用参数；重新运行使用当前规则和默认参数。");}}>复用本次配置</button></details>
        {run.data_date && <p className="sq-data">本次计算日线：<strong>{run.range_start ? `${run.range_start} ～ ` : ""}{run.data_date}</strong> · 同日最少命中 {run.config.minimum_matches ?? 1} 个策略 · 范围 {run.universe_size} 只 · 去重命中 {run.match_count ?? '…'} 只{run.config.strategies.includes('rps') && !run.range_start && ` · RPS 全市场有效母体 ${run.rps_universe_size} 只`}。这是截至 {run.config.as_of} 的运行时快照。</p>}
        {!!run.listing_date_unknown && <p className="sq-data">{run.listing_date_unknown} 只缺少上市日期，按当前在市记录兼容；该范围可能有幸存者偏差，不作为历史回测结果。</p>}
        <div className="sq-tabs"><button className={!filter ? 'active' : ''} onClick={() => {setFilter('');setSelected([]);setDetail(undefined);setFocus(undefined);}}>全部命中</button>{run.groups.map(g => <button key={g.id} className={filter === g.id ? 'active' : ''} onClick={() => { setFilter(g.id); setSelected([]);setDetail(undefined);setFocus(undefined); }}>{g.name} <b>{g.signal_count ?? g.matched}</b></button>)}</div>
        {run.range_start && <p className="sq-data">逐日诊断按“股票 × 交易日”计数；列表按股票去重。共检查 {run.observation_days} 个有数据的交易日，停更日期不沿用旧行情。收盘及涨跌幅取截至所选日期的最近记录。</p>}{(run.config.minimum_matches ?? 1) > 1 && <p className="sq-data">下方“成立”是各策略独立命中次数；只有同一天命中至少 {run.config.minimum_matches} 个策略的股票才进入上方结果。</p>}<div className="sq-diagnostics">{run.groups.filter(g => !filter || filter === g.id).map(g => <details key={g.id}><summary>{g.name}：成立 {g.matched} · 不成立 {g.rejected} · 数据不足 {g.unknown}</summary>{g.error && <p className="sq-error">{g.error}</p>}{g.examples.map(e => <p key={e.symbol}>{e.symbol}：{e.reason}</p>)}{!g.unknown && <p>本组没有数据不足的股票。</p>}</details>)}</div>
        {terminal && <><div className="sq-controls"><label><input type="checkbox" checked={failedOnly} disabled={reviews.busy} onChange={e=>{setFailedOnly(e.target.checked);setSelected([]);}} />仅看失败</label><span>本次已标失败 {reviews.symbols.length} 只</span>{reviews.error && <span role="alert">{reviews.error}</span>}<label>添加到<select aria-label="添加到自选分组" value={target} onChange={e => setTarget(e.target.value)}><option value="strategy">按命中策略自动分组</option><option value="">仅加入自选</option>{watchGroups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label><button disabled={busy || !visibleSelected.length} onClick={() => void add(visibleSelected)}>批量加入自选（{visibleSelected.length}）</button><label>排序<select value={sort} onChange={e => setSort(e.target.value)}><option value="symbol">股票代码</option><option value="change">当日涨跌幅降序</option></select></label></div>
          <p className="sq-data">按策略添加会创建或复用“Sequoia · 策略名”自选分组，多策略命中会加入多个分组；指定已有分组时，仍保留全部入选依据。</p>
          <div className="sq-table"><table><thead><tr><th><input aria-label="选择当前分组全部股票" type="checkbox" checked={visible.length > 0 && visibleSelected.length === visible.length} onChange={e => setSelected(e.target.checked ? visible.map(m => m.symbol) : [])} /></th><th>股票</th><th>收盘</th><th>最近记录涨跌幅</th><th>入选依据分组</th><th>复盘标记</th><th>操作</th></tr></thead><tbody>{visible.map(m => <tr key={m.symbol}><td><input aria-label={`选择 ${m.name}`} type="checkbox" checked={selected.includes(m.symbol)} onChange={e => setSelected(e.target.checked ? [...selected, m.symbol] : selected.filter(s => s !== m.symbol))} /></td><td><button className="sq-stock" aria-label={`查看 ${m.name} ${m.symbol}`} onClick={() => open(m)}><strong>{m.name}</strong><small>{m.symbol}</small></button></td><td>{number(m.close)}{m.quote_date && <small> · {m.quote_date}</small>}</td><td className={(m.change_percent ?? 0) > 0 ? 'sq-up' : (m.change_percent ?? 0) < 0 ? 'sq-down' : ''}>{m.change_percent == null ? '—' : `${m.change_percent > 0 ? '+' : ''}${m.change_percent.toFixed(2)}%`}</td><td><div className="sq-tags">{m.groups.map(g => <button key={g.id} onClick={() => {open(m); setFocus(g.checks.find(c => c.mark)?.mark);}}>{g.name}{g.occurrences && ` · ${g.occurrences.length} 次`}</button>)}</div>{m.last_match_date && <small>最近命中 {m.last_match_date}</small>}</td><td><FailureButton symbol={m.symbol} failed={reviews.symbols.includes(m.symbol)} disabled={reviews.busy} onClick={()=>void reviews.toggle(m.symbol)} /></td><td><button disabled={busy} onClick={() => void add([m.symbol])}>加入自选</button></td></tr>)}</tbody></table>{!visible.length && <p className="sq-empty">本组没有命中股票；数据不足请展开上方诊断查看。</p>}</div>
        </>}
      </>}
    </section>
    {detail && <section className="sq-panel sq-detail" ref={detailRef} aria-label="股票分组依据"><div className="sq-section-title"><h2>{detail.name} <small>{detail.symbol}</small></h2><div className="sq-detail-navigation" aria-label="股票详情切换"><button disabled={detailIndex <= 0} onClick={() => open(visible[detailIndex - 1])}>↑ 上一只</button><span>{detailIndex + 1} / {visible.length}</span><button disabled={detailIndex < 0 || detailIndex >= visible.length - 1} onClick={() => open(visible[detailIndex + 1])}>↓ 下一只</button><button onClick={() => setDetail(undefined)}>关闭详情</button></div></div><div className="sq-chart-legend" role="group" aria-label="策略图例"><span>图上策略</span>{detail.groups.map(group => <button key={group.id} type="button" aria-label={`图例 ${group.name}`} aria-pressed={!hiddenStrategies.includes(group.id)} className={hiddenStrategies.includes(group.id) ? 'sq-legend-off' : ''} onClick={() => { setFocus(undefined); setHiddenStrategies(current => current.includes(group.id) ? current.filter(id => id !== group.id) : [...current, group.id]); }}><i style={{ backgroundColor: STRATEGY_COLORS[group.id] ?? '#f3c969' }} />{group.name}</button>)}<small>点亮显示，点灭隐藏；悬停图上信号查看名称。详细条件在下方。</small></div><Suspense fallback={<p>加载 K 线详情…</p>}><ChartPage key={`${detail.symbol}:${run?.run_id}:${`${focus?.date ?? ''}:${focus?.label ?? 'all'}`}`} initialSymbol={detail.symbol} watchSource={{ ...detail.source, marks: focus ? [{ ...focus, strategyId: detail.groups.find(group => group.checks.some(check => check.mark === focus) || group.occurrences?.some(hit => hit.checks.some(check => check.mark === focus)))?.id }] : chartMarks }} focusMark={focus} /></Suspense><p>默认每个策略、每次命中只显示一个彩色信号；海龟按阶段仅标首日。展开下方条件可单独查看价格或成交量依据。</p>{detail.confluence_dates && <details className="sq-confluence"><summary>同日达到至少 {run?.config.minimum_matches ?? 1} 个策略：{detail.confluence_dates.length} 个交易日</summary><p>{detail.confluence_dates.join('、')}</p></details>}<div className="sq-evidence">{detail.groups.map(g => <article key={g.id}><h3>{g.name}{g.occurrences && ` · ${g.occurrences.length} 次命中`}</h3>{(g.occurrences ?? [{date: '', checks: g.checks}]).map(hit => <details key={hit.date || 'latest'} open={!hit.date}><summary>{hit.date || '本次命中依据'}{hit.end_date ? ` ～ ${hit.end_date} · 阶段内 ${hit.days} 根日线` : ''} · {hit.checks.length} 项首日条件满足</summary>{hit.breakout_level !== undefined && <p>固定突破前高：{number(hit.breakout_level)} · {hit.ended_on ? `${hit.ended_on} 收盘跌破，阶段结束` : '截至观察日尚未确认跌破'}</p>}{hit.checks.map((c, i) => <button key={i} className={focus === c.mark ? 'active' : ''} disabled={!c.mark} onClick={() => setFocus(c.mark)}><span>✓ {c.label}</span><small>实际 {number(c.actual)} {operators[c.operator] ?? c.operator} {number(c.expected)}</small><em>{c.mark ? `${c.mark.startDate ?? c.mark.date} → ${c.mark.date} · 查看标注` : '无图形标注'}</em></button>)}</details>)}</article>)}</div><button onClick={() => setFocus(undefined)}>显示全部分组标注</button></section>}
    <footer className="sq-foot">基础规则来源 Sequoia-X · 版本 444c0db；海龟采用相对放量或收盘涨停突破（含一字板）、固定前高划分阶段 · 使用本地日线统一口径计算。原仓库定时推送、行情采集与飞书通知未接入；定增依赖东方财富当日接口。</footer>
  </main>;
}
