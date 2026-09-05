import { FileJson, FolderOpen, Play, Radio, Save, SlidersHorizontal, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../../api";
import type { MetricSpec, ScreenMatch, ScreenRunResult, ScreenTemplate, ScreenValidation, UiGroupNode, UiNode } from "../../types";
import { ConditionTree } from "./ConditionTree";
import { ResultsTable, type ScreenSortField, type SortDirection } from "./ResultsTable";
import { createGroup, fromApiNode, toApiNode } from "./treeModel";

export interface ScreenerClient {
  catalog(): Promise<MetricSpec[]>;
  validateScreen(tree: unknown): Promise<ScreenValidation>;
  listScreenTemplates(): Promise<ScreenTemplate[]>;
  saveScreenTemplate(name: string, tree: unknown): Promise<ScreenTemplate>;
  deleteScreenTemplate(templateId: string): Promise<void>;
  runScreen(payload: object): Promise<ScreenRunResult>;
  screenResults(runId: string, limit: number, offset: number, sortBy?: ScreenSortField, sortDirection?: SortDirection): Promise<ScreenRunResult>;
}

const today = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

export function ScreenerPage({
  client = api,
  onOpenChart,
}: {
  client?: ScreenerClient;
  onOpenChart: (symbol: string) => void;
}) {
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [tree, setTree] = useState<UiGroupNode>(() => createGroup());
  const [mode, setMode] = useState<"close" | "live">("close");
  const [asOf, setAsOf] = useState(today);
  const [result, setResult] = useState<ScreenRunResult>();
  const [selected, setSelected] = useState<ScreenMatch>();
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(200);
  const [sortBy, setSortBy] = useState<ScreenSortField>();
  const [sortDirection, setSortDirection] = useState<SortDirection>();
  const sortRef = useRef<{ by?: ScreenSortField; direction?: SortDirection }>({});
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<ScreenTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [watchMessage, setWatchMessage] = useState("");
  const addWatchlist = async (symbol: string) => {
    if (!result) return;
    try {
      await api.addWatchlist(symbol, result.run_id);
      setWatchMessage(`${symbol} 已加入自选，已保存本次筛选条件`);
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
      setSelectedTemplateId((current) => current || items[0]?.template_id || "");
    }).catch((cause: Error) => setError(cause.message));
  }, [client]);

  const setImportedTree = (value: unknown) => {
    const imported = fromApiNode(value, catalog);
    setTree(imported.kind === "group"
      ? imported
      : { ...createGroup(), children: [imported] });
    setResult(undefined);
    setSelected(undefined);
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

  const loadTemplate = () => {
    const selectedTemplate = templates.find((item) => item.template_id === selectedTemplateId);
    if (!selectedTemplate) { setError("请先选择模板"); return; }
    try {
      setImportedTree(selectedTemplate.tree);
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
      setSelectedTemplateId(remaining[0]?.template_id ?? "");
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除模板失败");
    }
  };

  const run = async () => {
    if (!tree.children.length) { setError("至少需要一个筛选条件"); return; }
    setLoading(true); setError("");
    try {
      const next = await client.runScreen({ tree: toApiNode(tree, catalog), mode, as_of: asOf, limit: pageSize, offset: 0 });
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
      );
      setResult(next);
      setSelected(next.matches[0]);
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

  const totalPages = result ? Math.max(1, Math.ceil(result.match_count / pageSize)) : 1;

  return (
    <main className="screener-page">
      <header className="compact-heading">
        <div><p className="eyebrow">FULL MARKET / RULE COMPOSER</p><h1>选股工作台</h1></div>
        <div className="screen-controls">
          <label><span>数据日期</span><input aria-label="数据日期" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
          <label><span>运行方式</span><select aria-label="筛选模式" value={mode} onChange={(event) => setMode(event.target.value as "close" | "live")}><option value="close">收盘数据</option><option value="live">实时行情</option></select></label>
          <button type="button" className="run-button" aria-label="运行全市场筛选" disabled={loading || !catalog.length} onClick={run}>{mode === "live" ? <Radio size={16} /> : <Play size={16} />}{loading ? "计算中…" : "运行筛选"}</button>
        </div>
      </header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <section className="composer-section">
        <div className="section-title"><div><SlidersHorizontal size={17} /><span>条件编排</span></div><button type="button" className="ghost-button" aria-label="导入 JSON" onClick={() => setImportOpen((open) => !open)}><FileJson size={14} />导入 JSON</button></div>
        <div className="template-toolbar">
          <label><span>模板名称</span><input aria-label="模板名称" value={templateName} maxLength={80} placeholder="例如：月线强势股" onChange={(event) => setTemplateName(event.target.value)} /></label>
          <button type="button" aria-label="保存模板" onClick={() => void saveTemplate()}><Save size={14} />保存模板</button>
          <label><span>已保存模板</span><select aria-label="已保存模板" value={selectedTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)}><option value="">请选择</option>{templates.map((item) => <option key={item.template_id} value={item.template_id}>{item.name} · v{item.version}</option>)}</select></label>
          <button type="button" aria-label="加载模板" disabled={!selectedTemplateId} onClick={loadTemplate}><FolderOpen size={14} />加载</button>
          <button type="button" className="danger-action" aria-label="删除模板" disabled={!selectedTemplateId} onClick={() => void deleteTemplate()}><Trash2 size={14} />删除</button>
        </div>
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
      </section>
      <section className="screen-results">
        <div className="section-title">
          <div><span>命中结果</span>{result && <em>共命中 {result.match_count.toLocaleString("zh-CN")} 只</em>}</div>
          {result && <div className="run-stats"><span>全市场 <b>{result.universe_size.toLocaleString("zh-CN")}</b></span><span>实时覆盖 <b>{result.realtime_covered.toLocaleString("zh-CN")}</b></span></div>}
        </div>
        {!result ? <div className="result-empty">组合条件后运行，命中股票将在这里显示。</div> : <>
          {watchMessage && <p role="status">{watchMessage}</p>}
          <ResultsTable matches={result.matches} selected={selected?.symbol} onSelect={setSelected} onOpenChart={onOpenChart} onAddWatchlist={addWatchlist} sortBy={sortBy} sortDirection={sortDirection} onSort={changeSort} />
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
    </main>
  );
}
