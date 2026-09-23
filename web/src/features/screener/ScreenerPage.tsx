import { DataDateInput } from "../../components/DataDateInput";
import { FileJson, FolderOpen, Play, Radio, Save, SlidersHorizontal, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../../api";
import type { MetricSpec, ScreenMatch, ScreenRunResult, ScreenTemplate, ScreenValidation, UiGroupNode, UiNode } from "../../types";
import { ConditionTree } from "./ConditionTree";
import { ResultsTable, type ScreenSortField, type SortDirection } from "./ResultsTable";
import { createGroup, fromApiNode, toApiNode } from "./treeModel";
import { conditionEntries, describe, metricLabel } from "./presentation";
import type { SourceNode, WatchSource } from "../watchlist/model";
import type { RunComparison, RunSummary } from "./workbenchTypes";
import { StockDetailPanel } from "./StockDetailPanel";

const storageKey = "astock.screener.workspace.v2";
function savedWorkspace() {
  try { return JSON.parse(localStorage.getItem(storageKey) ?? "null"); } catch { return null; }
}

export interface ScreenerClient {
  catalog(): Promise<MetricSpec[]>;
  validateScreen(tree: unknown): Promise<ScreenValidation>;
  listScreenTemplates(): Promise<ScreenTemplate[]>;
  saveScreenTemplate(name: string, tree: unknown): Promise<ScreenTemplate>;
  deleteScreenTemplate(templateId: string): Promise<void>;
  runScreen(payload: object, onProgress?: (value: {progress:number;message:string;processed:number;total:number}) => void): Promise<ScreenRunResult>;
  screenResults(runId: string, limit: number, offset: number, sortBy?: ScreenSortField, sortDirection?: SortDirection, newOnly?: boolean): Promise<ScreenRunResult>;
}

const today = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

export function ScreenerPage({
  client = api,
  onOpenChart,
  onBacktest,
  onMonitor,
}: {
  client?: ScreenerClient;
  onOpenChart: (symbol: string, source?: WatchSource) => void;
  onBacktest?: (symbol: string, tree: SourceNode) => void;
  onMonitor?: (symbol: string, price: number) => void;
}) {
  const [saved] = useState(() => client === api ? savedWorkspace() : null);
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [sectorStatus, setSectorStatus] = useState<Awaited<ReturnType<typeof api.sectorStatus>>>();
  useEffect(()=>{
    if(client!==api) return;
    let active=true;
    const refresh=()=>api.sectorStatus().then(status=>{if(active) setSectorStatus(status);}).catch(()=>{});
    void refresh();
    const timer=window.setInterval(refresh,5000);
    return ()=>{active=false;window.clearInterval(timer);};
  },[client]);
  useEffect(()=>{if(client===api && sectorStatus?.updated_at && !sectorStatus.running) void client.catalog().then(setCatalog).catch((cause:Error)=>setError(cause.message));},[client,sectorStatus?.updated_at,sectorStatus?.running]);
  const syncSectors=async()=>{try{await api.syncSectors();setSectorStatus(await api.sectorStatus());}catch(cause){setError(cause instanceof Error?cause.message:"板块更新失败");}};
  const [tree, setTree] = useState<UiGroupNode>(() => saved?.tree ?? createGroup());
  const [mode, setMode] = useState<"close" | "live">(saved?.mode ?? "close");
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState<ScreenRunResult | undefined>(saved?.result);
  const [selected, setSelected] = useState<ScreenMatch | undefined>(saved?.selected);
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  const [page, setPage] = useState(saved?.page ?? 1);
  const [pageSize, setPageSize] = useState(saved?.pageSize ?? 200);
  const [sortBy, setSortBy] = useState<ScreenSortField | undefined>(saved?.sortBy);
  const [sortDirection, setSortDirection] = useState<SortDirection | undefined>(saved?.sortDirection);
  const sortRef = useRef<{ by?: ScreenSortField; direction?: SortDirection }>({by:saved?.sortBy,direction:saved?.sortDirection});
  const [error, setError] = useState("");
  const openResultChart = async (symbol: string) => {
    if (client !== api || !result) { onOpenChart(symbol); return; }
    try {
      const detail = await api.screenDetail(result.run_id, symbol);
      onOpenChart(symbol, detail.source);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取K线入选依据失败");
    }
  };
  const [templates, setTemplates] = useState<ScreenTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [watchMessage, setWatchMessage] = useState("");
  const [scope, setScope] = useState(saved?.scope ?? "market");
  const [instrumentType, setInstrumentType] = useState(saved?.instrumentType ?? "all");
  const [boards, setBoards] = useState<string[]>(saved?.boards ?? []);
  const [sourceRunId, setSourceRunId] = useState(saved?.sourceRunId ?? "");
  const [runTree, setRunTree] = useState<SourceNode | undefined>(saved?.runTree);
  const [runSignature, setRunSignature] = useState(saved?.runSignature ?? "");
  const [watchGroups, setWatchGroups] = useState<import("../watchlist/model").WatchGroup[]>([]);
  const [targetWatchGroup, setTargetWatchGroup] = useState("");
  useEffect(() => {
    if (client !== api) return;
    const load = () => api.watchGroups().then(setWatchGroups).catch((cause: Error) => setError(cause.message));
    void load();
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, [client]);
  const [checked, setChecked] = useState<string[]>([]);
  const [allChecked, setAllChecked] = useState(false);
  const [hiddenColumns, setHiddenColumns] = useState<string[]>(saved?.hiddenColumns ?? []);
  const [extraColumns, setExtraColumns] = useState<string[]>(saved?.extraColumns ?? []);
  const [columnSearch, setColumnSearch] = useState("");
  const [columnTimeframe, setColumnTimeframe] = useState("1d");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [previousRunId, setPreviousRunId] = useState("");
  const [newOnly, setNewOnly] = useState(saved?.newOnly ?? false);
  const [comparison, setComparison] = useState<RunComparison>();
  const [batchBusy, setBatchBusy] = useState(false);
  const [detailOpen, setDetailOpen] = useState(saved?.detailOpen ?? false);
  const [unknownPath, setUnknownPath] = useState<string>();
  const [schedules, setSchedules] = useState<Awaited<ReturnType<typeof api.screenSchedules>>>([]);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleNotify, setScheduleNotify] = useState(false);
  useEffect(()=>{ if(client===api) api.screenSchedules().then(setSchedules).catch((cause:Error)=>setError(cause.message)); },[client]);
  useEffect(()=>{ const item=schedules.find(item=>item.template_id===selectedTemplateId); setScheduleEnabled(item?.enabled??false); setScheduleNotify(item?.notify??false); },[selectedTemplateId,schedules]);
  const saveSchedule = async () => {
    try { await api.saveScreenSchedule(selectedTemplateId,scheduleEnabled,scheduleNotify); setSchedules(await api.screenSchedules());setWatchMessage("模板收盘自动筛选设置已保存"); }
    catch(cause){setError(cause instanceof Error?cause.message:"保存失败");}
  };
  let currentTree: object | undefined;
  try { if (catalog.length) currentTree = toApiNode(tree,catalog); } catch { /* The editor shows the invalid draft until run/validate. */ }
  const signature = JSON.stringify({tree:currentTree,asOf,mode,scope,instrumentType,boards,sourceRunId});
  const stale = Boolean(result && currentTree && signature !== runSignature);
  const autoColumns = runTree ? conditionEntries(runTree).flatMap(({node}) => [ `${node.timeframe}:${node.metric}`, ...(node.right?.kind === "metric" ? [`${node.right.timeframe}:${node.right.metric}`] : []) ]) : [];
  const availableColumns = [...new Set(["close", "return_20", "volume_ratio_20", "1d:em_industry", "1d:em_concept", ...autoColumns, ...extraColumns])];
  const columns = availableColumns.filter((key) => !hiddenColumns.includes(key));

  useEffect(() => {
    if (client !== api) return;
    try { localStorage.setItem(storageKey,JSON.stringify({tree,mode,asOf,result,selected,page,pageSize,sortBy,sortDirection,scope,instrumentType,boards,sourceRunId,runTree,runSignature,hiddenColumns,extraColumns,detailOpen,newOnly})); }
    catch { setError("浏览器存储空间不足，当前筛选仍可使用；请保存模板以保留条件。"); }
  },[client,tree,mode,asOf,result,selected,page,pageSize,sortBy,sortDirection,scope,instrumentType,boards,sourceRunId,runTree,runSignature,hiddenColumns,extraColumns,detailOpen,newOnly]);
  useEffect(() => { if (client === api) api.screenRuns().then(setRuns).catch((cause:Error)=>setError(cause.message)); },[client,result?.run_id]);
  useEffect(() => {
    if (client !== api || !result || result.new_comparison !== undefined) return;
    let active = true;
    api.screenResults(result.run_id,pageSize,(page-1)*pageSize,sortBy,sortDirection,newOnly)
      .then(next=>{if(active)setResult(next);}).catch((cause:Error)=>{if(active)setError(cause.message);});
    return ()=>{active=false;};
  },[client,result?.run_id]);
  const stepStock = (delta:number) => {
    if (!result) return;
    const index = result.matches.findIndex((match)=>match.symbol===selected?.symbol);
    const next = result.matches[index+delta];
    if (next) setSelected(next);
    else if (delta>0 && page<totalPages) void loadPage(page+1);
    else if (delta<0 && page>1) void loadPage(page-1, pageSize, sortRef.current.by, sortRef.current.direction, true);
  };
  const batchAdd = async () => {
    if (!result) return;
    setBatchBusy(true);
    try { const next = await api.batchWatchlist(result.run_id,allChecked && newOnly ? result.new_comparison?.entered ?? [] : checked,allChecked && !newOnly,targetWatchGroup || undefined); setWatchMessage(`已将 ${next.added} 只股票加入${watchGroups.find(group => group.id === targetWatchGroup)?.name ?? "自选股"}并保存来源`); }
    catch(cause){setError(cause instanceof Error ? cause.message : "批量加入失败");}
    finally {setBatchBusy(false);}
  };
  const addWatchlist = async (symbol: string) => {
    if (!result) return;
    try {
      await api.batchWatchlist(result.run_id, [symbol], false, targetWatchGroup || undefined);
      setWatchMessage(`${symbol} 已加入${watchGroups.find(group => group.id === targetWatchGroup)?.name ?? "自选股"}，已保存本次筛选条件`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "加入自选失败"); }
  };

  useEffect(() => {
    client.catalog().then((metrics) => {
      setCatalog(metrics);
    }).catch((cause: Error) => setError(cause.message));
  }, [client]);

  useEffect(() => {
    client.listScreenTemplates().then((items) => {
      setTemplates(items);
    }).catch((cause: Error) => setError(cause.message));
  }, [client]);

  const setImportedTree = (value: unknown) => {
    const imported = fromApiNode(value, catalog);
    setTree(imported.kind === "group"
      ? imported
      : { ...createGroup(), children: [imported] });
  };

  const applyJson = async () => {
    setError("");
    try {
      const parsed = JSON.parse(importText) as unknown;
      const validation = await client.validateScreen(parsed);
      if (!validation.valid) throw new Error(validation.errors[0]?.message ?? "条件 JSON 校验失败");
      setImportedTree(parsed);
      setImportOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "条件 JSON 导入失败");
    }
  };

  const saveTemplate = async () => {
    const name = templateName.trim();
    if (!name) { setError("请填写模板名称"); return; }
    setError("");
    try {
      const saved = await client.saveScreenTemplate(name, toApiNode(tree, catalog));
      setTemplates((items) => [saved, ...items.filter((item) => item.template_id !== saved.template_id)]);
      setSelectedTemplateId(saved.template_id);
      setTemplateName(saved.name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存模板失败");
    }
  };

  const loadTemplate = (templateId = selectedTemplateId) => {
    const selectedTemplate = templates.find((item) => item.template_id === templateId);
    if (!selectedTemplate) { setError("请先选择模板"); return; }
    try {
      setImportedTree(selectedTemplate.tree);
      setSelectedTemplateId(templateId);
      setResult(undefined); setSelected(undefined); setRunTree(undefined); setRunSignature("");
      setChecked([]); setPage(1); setWatchMessage("");
      setTemplateName(selectedTemplate.name);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载模板失败");
    }
  };

  const deleteTemplate = async () => {
    if (!selectedTemplateId) { setError("请先选择模板"); return; }
    try {
      await client.deleteScreenTemplate(selectedTemplateId);
      const remaining = templates.filter((item) => item.template_id !== selectedTemplateId);
      setTemplates(remaining);
      setSelectedTemplateId("");
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除模板失败");
    }
  };

  const [screenProgress, setScreenProgress] = useState<{progress:number;message:string;processed:number;total:number}>();
  const run = async () => {
    if (!tree.children.length) { setError("至少需要一个筛选条件"); return; }
    setLoading(true); setError(""); setScreenProgress({progress:0,message:"正在提交筛选任务",processed:0,total:0});
    try {
      const submittedTree = toApiNode(tree, catalog);
      const next = await client.runScreen({ tree: submittedTree, mode, as_of: asOf || today(), limit: pageSize, offset: 0,
        scope, instrument_type:instrumentType, boards, source_run_id:scope === "run" ? sourceRunId : undefined,
        extra_columns:extraColumns }, setScreenProgress);
      setRunTree(submittedTree as SourceNode); setRunSignature(signature); setChecked([]); setAllChecked(false); setComparison(undefined); setNewOnly(false);
      setResult(next);
      setSelected(next.matches[0]);
      setPage(1);
      sortRef.current = {};
      setSortBy(undefined);
      setSortDirection(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "筛选失败");
    } finally {
      setLoading(false);
    }
  };

  const loadPage = async (
    nextPage: number,
    nextPageSize = pageSize,
    nextSortBy = sortRef.current.by,
    nextSortDirection = sortRef.current.direction,
    selectLast = false,
    onlyNew = newOnly,
  ) => {
    if (!result) return;
    setPaging(true); setError("");
    try {
      const next = await client.screenResults(
        result.run_id,
        nextPageSize,
        (nextPage - 1) * nextPageSize,
        nextSortBy,
        nextSortDirection,
        onlyNew,
      );
      setResult(next); setNewOnly(onlyNew);
      setSelected(selectLast ? next.matches.at(-1) : next.matches[0]);
      setPage(nextPage);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取筛选结果失败");
    } finally {
      setPaging(false);
    }
  };

  const changeSort = (field: ScreenSortField) => {
    const { by, direction } = sortRef.current;
    const nextDirection = by !== field ? "desc" : direction === "desc" ? "asc" : undefined;
    const nextSortBy = nextDirection ? field : undefined;
    sortRef.current = { by: nextSortBy, direction: nextDirection };
    setSortBy(nextSortBy);
    setSortDirection(nextDirection);
    void loadPage(1, pageSize, nextSortBy, nextDirection);
  };

  const totalPages = result ? Math.max(1, Math.ceil((newOnly ? result.filtered_count ?? 0 : result.match_count) / pageSize)) : 1;

  return (
    <main className={`screener-page ${detailOpen ? "has-stock-detail" : ""}`}>
      <header className="compact-heading">
        <div><p className="eyebrow">FULL MARKET / RULE COMPOSER</p><h1>选股工作台</h1></div>
        <div className="screen-controls">
          <DataDateInput label="数据日期" value={asOf} onChange={setAsOf} />
          <label><span>运行方式</span><select aria-label="筛选模式" value={mode} onChange={(event) => setMode(event.target.value as "close" | "live")}><option value="close">收盘数据</option><option value="live">实时行情</option></select></label>
          <button type="button" className="run-button" aria-label="运行全市场筛选" disabled={loading || !catalog.length} onClick={run}>{mode === "live" ? <Radio size={16} /> : <Play size={16} />}{loading ? "计算中…" : "运行筛选"}</button>
        </div>
      </header>
      {mode === "live" && <p role="note">盘中仅更新行情、涨跌幅、均线和成交量相关指标；RSI、MACD、形态等动态指标暂不支持实时计算，缺失值不会命中。周/月条件使用最近完整周期。</p>}
      {error && <div className="error-banner" role="alert">{error}</div>}
      {watchMessage && <p role="status">{watchMessage}</p>}
      {loading && screenProgress && <section className="screen-progress" role="status" aria-label="条件选股进度"><div><strong>{screenProgress.message}</strong><span>{screenProgress.progress}%{screenProgress.total > 0 ? ` · 本阶段已处理 ${screenProgress.processed} / ${screenProgress.total} 只` : ''}</span></div><progress max="100" value={screenProgress.progress} aria-label="筛选进度" /><small>百分比按执行阶段估算；股票数量按实际处理进度更新。</small></section>}
      {client===api && <section className="sector-status" aria-label="东方财富板块数据"><div><strong>东方财富行业 / 概念</strong><span>{sectorStatus?.updated_at ? `快照 ${sectorStatus.updated_at} · ${sectorStatus.industries} 个行业 · ${sectorStatus.concepts} 个概念` : "尚无完整板块快照"}</span><small>按东方财富原始成分名单，不自行分类；历史选股采用当前名单，不代表历史归属。</small></div><button disabled={sectorStatus?.running} onClick={()=>void syncSectors()}>{sectorStatus?.running ? `同步 ${sectorStatus.done}/${sectorStatus.total} · ${sectorStatus.current}` : "更新板块数据"}</button>{sectorStatus?.error && <p role="alert">{sectorStatus.error}</p>}</section>}
      <section className="scope-toolbar" aria-label="筛选范围">
        <label>筛选范围 <select aria-label="筛选范围" value={scope} onChange={event=>setScope(event.target.value)}><option value="market">全市场</option><option value="board">指定板块</option><option value="watchlist">自选股</option><option value="run">某次筛选结果</option></select></label>
        <label>证券类型 <select aria-label="证券类型" value={instrumentType} onChange={event=>setInstrumentType(event.target.value)}><option value="all">股票与ETF</option><option value="stock">仅股票</option><option value="etf">仅ETF</option></select></label>
        {scope === "board" && catalog.find(item=>item.key==="board")?.choices?.map(choice=><label key={choice.value}><input type="checkbox" checked={boards.includes(choice.value)} onChange={()=>setBoards(values=>values.includes(choice.value)?values.filter(value=>value!==choice.value):[...values,choice.value])}/>{choice.label}</label>)}
        {scope === "run" && <select aria-label="来源筛选" value={sourceRunId} onChange={event=>setSourceRunId(event.target.value)}><option value="">选择来源结果</option>{runs.map(run=><option key={run.run_id} value={run.run_id}>{run.as_of} · {run.match_count}只 · {run.run_id.slice(0,8)}</option>)}</select>}
      </section>
      <section className="composer-section">
        <div className="section-title"><div><SlidersHorizontal size={17} /><span>条件编排</span></div><button type="button" className="ghost-button" aria-label="导入 JSON" onClick={() => setImportOpen((open) => !open)}><FileJson size={14} />导入 JSON</button></div>
        <div className="template-toolbar">
          <label><span>模板名称</span><input aria-label="模板名称" value={templateName} maxLength={80} placeholder="例如：月线强势股" onChange={(event) => setTemplateName(event.target.value)} /></label>
          <button type="button" aria-label="保存模板" onClick={() => void saveTemplate()}><Save size={14} />保存模板</button>
          <label><span>已保存模板</span><select aria-label="已保存模板" value={selectedTemplateId} disabled={loading || paging || !catalog.length} onChange={(event) => { const id = event.target.value; if (id) loadTemplate(id); else setSelectedTemplateId(""); }}><option value="">请选择</option>{templates.map((item) => <option key={item.template_id} value={item.template_id}>{item.name} · v{item.version}</option>)}</select></label>
          <button type="button" aria-label="加载模板" disabled={!selectedTemplateId || loading || paging} onClick={() => loadTemplate()}><FolderOpen size={14} />加载</button>
          <button type="button" className="danger-action" aria-label="删除模板" disabled={!selectedTemplateId} onClick={() => void deleteTemplate()}><Trash2 size={14} />删除</button>
        </div>
        {selectedTemplateId && <details><summary>模板收盘自动筛选与飞书通知</summary><p>对已保存模板使用全市场范围、收盘模式；每日16:10后等待当天行情同步完成，再执行一次。模板修改后按新版本建立对比基线。</p><label><input type="checkbox" checked={scheduleEnabled} onChange={event=>setScheduleEnabled(event.target.checked)}/>启用自动筛选</label> <label><input type="checkbox" checked={scheduleNotify} onChange={event=>setScheduleNotify(event.target.checked)}/>向已配置的飞书机器人发送结果变化</label> <button onClick={()=>void saveSchedule()}>保存自动筛选设置</button>{schedules.filter(item=>item.template_id===selectedTemplateId).map(item=><p key={item.template_id}>上次执行：{item.last_date??"尚未执行"} {item.last_error?`执行失败：${item.last_error}`:""}</p>)}</details>}
        {importOpen && <div className="json-import-panel" role="dialog" aria-label="JSON 条件导入">
          <div><strong>导入条件 JSON</strong><span>支持粘贴内容或读取 .json 文件；通过校验后才会替换当前条件。</span></div>
          <textarea aria-label="条件 JSON" value={importText} placeholder={'{"kind":"group","logic":"and","children":[…]}'} onChange={(event) => setImportText(event.target.value)} />
          <div className="json-import-actions">
            <label className="file-button"><Upload size={14} />选择文件<input aria-label="选择 JSON 文件" type="file" accept="application/json,.json" onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void file.text().then(setImportText).catch(() => setError("读取 JSON 文件失败"));
            }} /></label>
            <button type="button" className="ghost-button" onClick={() => setImportOpen(false)}>取消</button>
            <button type="button" className="run-button" aria-label="应用 JSON" disabled={!importText.trim()} onClick={() => void applyJson()}>应用 JSON</button>
          </div>
        </div>}
        {catalog.length ? <ConditionTree tree={tree} catalog={catalog} onChange={(next: UiNode) => setTree(next as UiGroupNode)} /> : <div className="loading-strip">正在读取指标目录…</div>}
        <section className="condition-preview" aria-label="中文条件预览"><strong>你正在表达：</strong><p>{describe(tree,catalog)}</p><small>“计算周期”是指标使用的K线根数；“周期”决定每根K线代表日、周或分钟；“回看周期”决定检查多少次。可将条件拖到目标分组标题上。</small></section>
      </section>
      <section className="screen-results">
        <div className="section-title">
          <div><span>命中结果</span>{result && <em>共命中 {result.match_count.toLocaleString("zh-CN")} 只</em>}</div>
          {result && <div className="run-stats"><span>全市场 <b>{result.universe_size.toLocaleString("zh-CN")}</b></span><span>实时覆盖 <b>{result.realtime_covered.toLocaleString("zh-CN")}</b></span></div>}
        </div>
        {!result ? <div className="result-empty">组合条件后运行，命中股票将在这里显示。</div> : <>
          {stale && <p className="stale-banner" role="status">条件、日期或范围已修改，当前仍为上次筛选结果。重新运行后更新。</p>}
          <details className="column-editor"><summary>显示列设置（自动关联筛选指标）</summary><div className="scope-toolbar">{availableColumns.map(key=><label key={key}><input type="checkbox" checked={!hiddenColumns.includes(key)} onChange={()=>setHiddenColumns(values=>values.includes(key)?values.filter(value=>value!==key):[...values,key])}/>{metricLabel(key,catalog)}</label>)}</div>
            <input aria-label="搜索结果列" placeholder="搜索要添加的指标" value={columnSearch} onChange={event=>setColumnSearch(event.target.value)}/><select aria-label="新增列周期" value={columnTimeframe} onChange={event=>setColumnTimeframe(event.target.value)}>{["1d","1w","1mo","5m","15m","30m","60m"].map(value=><option key={value}>{value}</option>)}</select>
            <select aria-label="添加结果列" value="" onChange={event=>setExtraColumns(values=>[...new Set([...values,`${columnTimeframe}:${event.target.value}`])])}><option value="">选择添加列</option>{catalog.filter(item=>item.visible!==false && `${item.label} ${item.key}`.includes(columnSearch)).map(item=><option key={item.key} value={item.key}>{metricLabel(item.key,catalog)}</option>)}</select><p>新加入周期的数据在下次运行时保存；未提供的数据会显示“数据不足”。</p>
          </details>
          <div className="scope-toolbar"><button onClick={()=>{setChecked(result.matches.map(match=>match.symbol));setAllChecked(false);}}>选择当前页</button><button onClick={()=>{setAllChecked(true);setChecked(result.matches.map(match=>match.symbol));}}>选择全部 {newOnly ? result.new_comparison?.count ?? 0 : result.match_count} 只</button><button onClick={()=>{setChecked([]);setAllChecked(false);}}>取消勾选</button><span>已选 {allChecked?(newOnly ? result.new_comparison?.count ?? 0 : result.match_count):checked.length} 只{allChecked?(newOnly?"（全部新增）":"（全部命中）"):""}</span><label>加入到分组 <select aria-label="目标自选分组" disabled={batchBusy} value={targetWatchGroup} onChange={event=>setTargetWatchGroup(event.target.value)}><option value="">仅加入自选（保留已有分组）</option>{watchGroups.map(group=><option key={group.id} value={group.id}>{group.name}</option>)}</select></label><button disabled={batchBusy || (!allChecked && !checked.length)} onClick={()=>void batchAdd()}>{batchBusy?"加入中…":"批量加入自选"}</button>
            <a download href={`/api/workbench/runs/${result.run_id}/export?${new URLSearchParams({columns:columns.join(","),...(sortBy?{sort_by:sortBy,sort_direction:sortDirection??"asc"}:{})})}`}>导出全部结果CSV</a><button onClick={()=>{setScope("run");setSourceRunId(result.run_id);}}>在本次结果中继续筛选</button>
          </div>
          <details className="run-comparison"><summary>历史记录与两次筛选对比</summary><select aria-label="对比筛选记录" value={previousRunId} onChange={event=>setPreviousRunId(event.target.value)}><option value="">选择另一条记录</option>{runs.filter(run=>run.run_id!==result.run_id).map(run=><option key={run.run_id} value={run.run_id}>{run.as_of} · {run.match_count}只 · {run.run_id.slice(0,8)}</option>)}</select><button disabled={!previousRunId} onClick={()=>void api.compareRuns(result.run_id,previousRunId).then(setComparison).catch((cause:Error)=>setError(cause.message))}>对比结果</button>
            {comparison && <div><p>{comparison.previous_date} → {comparison.current_date}</p>{(!comparison.same_definition || !comparison.same_scope || !comparison.same_mode) && <p className="stale-banner">两次筛选的条件、范围或运行模式不同，结果变化不完全由行情引起。</p>}{(["entered","stayed","exited"] as const).map((key,index)=><details key={key}><summary>{["新入选","仍符合","已退出"][index]} {comparison[key].length}只</summary>{comparison[key].map(item=><button key={item.symbol} onClick={()=>onOpenChart(item.symbol)}>{item.name} · {item.symbol}</button>)}</details>)}</div>}
          </details>
          {result.diagnostics && <details open className="screen-diagnostics">
            <summary>数据与条件诊断</summary>
            {result.diagnostics.warnings.map((warning) => <p key={warning}>{warning}</p>)}
            {Object.entries(result.diagnostics.data_dates).map(([timeframe, dates]) => <p key={timeframe}>数据时间（{timeframe}）：{dates.oldest ?? "无数据"} 至 {dates.latest ?? "无数据"}，为各股票最近可用记录的时间范围。</p>)}
            {Object.entries(result.diagnostics.conditions).map(([path, counts], index) => <div key={path}>
              <p>{runTree ? describe(conditionEntries(runTree).find(entry=>entry.path===path)?.node ?? {kind:"condition"},catalog) : `条件 ${index+1}`}：成立 {counts.true} · 不成立 {counts.false} · <button onClick={()=>setUnknownPath(unknownPath===path?undefined:path)}>数据不足 {counts.unknown}</button></p>
              {unknownPath===path && <div>{(counts as typeof counts & {unknown_symbols?:Array<{symbol:string;name:string;reason:string}>}).unknown_symbols?.map(item=><p key={item.symbol}><button onClick={()=>onOpenChart(item.symbol)}>{item.name} {item.symbol}</button>：{item.reason}</p>) ?? <p>旧记录未保存具体名单，请重新运行。</p>}</div>}
              {Object.entries(counts.reasons).map(([reason, count]) => <p key={reason}>{reason}：{count} 只</p>)}
            </div>)}
          </details>}
          <div className="scope-toolbar">
            {result.new_comparison ? <><span>对比上次相同条件：{result.new_comparison.finished_at.replace('T',' ').slice(0,19)}（运行时间） · 数据日期 {result.new_comparison.as_of} · 新增 {result.new_comparison.count} 只</span>
              <label><input type="checkbox" aria-label="仅看新增" checked={newOnly} disabled={paging || loading} onChange={event=>{setChecked([]);setAllChecked(false);void loadPage(1,pageSize,sortRef.current.by,sortRef.current.direction,false,event.target.checked);}}/>仅看新增</label></> : <span>暂无上一次相同条件、范围和模式的已完成筛选记录，无法判断新增。</span>}
          </div>
          <ResultsTable newSymbols={result.new_comparison?.entered} matches={result.matches} selected={selected?.symbol} onSelect={match=>{setSelected(match);setDetailOpen(true);}} onOpenChart={(symbol) => void openResultChart(symbol)} onAddWatchlist={addWatchlist} sortBy={sortBy} sortDirection={sortDirection} onSort={changeSort} columns={client===api?columns:undefined} catalog={catalog} checked={checked} onCheck={symbol=>{setAllChecked(false);setChecked(values=>values.includes(symbol)?values.filter(value=>value!==symbol):[...values,symbol]);}} hideExplanation={client===api}/>
          <div className="results-pagination">
            <label>每页<select aria-label="每页数量" value={pageSize} disabled={paging} onChange={(event) => {
              const nextSize = Number(event.target.value);
              setPageSize(nextSize);
              void loadPage(1, nextSize);
            }}>{[50, 100, 200].map((size) => <option key={size} value={size}>{size} 只</option>)}</select></label>
            <button type="button" aria-label="上一页" disabled={page <= 1 || paging} onClick={() => void loadPage(page - 1)}>上一页</button>
            <span>第 {page} / {totalPages} 页</span>
            <button type="button" aria-label="下一页" disabled={page >= totalPages || paging} onClick={() => void loadPage(page + 1)}>下一页</button>
          </div>
        </>}
      </section>
      {client===api && detailOpen && selected && result && <StockDetailPanel key={`${result.run_id}:${selected.symbol}`} runId={result.run_id} match={selected} catalog={catalog} onClose={()=>setDetailOpen(false)} onStep={stepStock} onOpenChart={(symbol) => void openResultChart(symbol)} onAddWatchlist={addWatchlist} onBacktest={onBacktest} onMonitor={onMonitor}/>}
    </main>
  );
}
