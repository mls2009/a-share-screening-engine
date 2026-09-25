import type { BacktestRun, Bar, BenchmarkComparison, ChartDataSyncRequest, ChartDataSyncResult, ChartIndicatorPoint, MetricSpec, MonitorSignal, MonitorStatus, MonitorTask, PriceZone, ScreenRunResult, ScreenTemplate, ScreenValidation, SymbolSearchResult, Timeframe } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.message ?? detail?.errors?.[0]?.message ?? (typeof detail?.detail === "string" ? detail.detail : `HTTP ${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  resultReviews: (source: string, runId: string) => request<string[]>(`/api/result-reviews/${source}/${encodeURIComponent(runId)}`),
  saveResultReview: (source: string, runId: string, symbol: string, failed: boolean) => request<{failed:boolean}>(`/api/result-reviews/${source}/${encodeURIComponent(runId)}/${encodeURIComponent(symbol)}`, {method:"PUT",body:JSON.stringify({failed})}),
  stockOverview: (symbol: string) => request<import("./features/stock/StockOverview").StockOverviewData>(`/api/symbols/${encodeURIComponent(symbol)}/overview`),
  historyWaves: (symbol: string, payload: object) => request<import("./features/watchlist/HistoryWaves").WaveResult>(`/api/watchlist/${encodeURIComponent(symbol)}/waves`, { method: "POST", body: JSON.stringify(payload) }),
  sectorStatus: () => request<{source:string;updated_at:string|null;running:boolean;done:number;total:number;current:string;error:string;industries:number;concepts:number}>("/api/sectors/status"),
  syncSectors: () => request<object>("/api/sectors/sync",{method:"POST"}),
  screenSchedules: () => request<Array<{template_id:string;enabled:boolean;notify:boolean;last_date:string|null;last_error:string|null;last_run_id:string|null}>>("/api/workbench/schedules"),
  saveScreenSchedule: (templateId:string,enabled:boolean,notify:boolean) => request<object>(`/api/workbench/schedules/${encodeURIComponent(templateId)}`,{method:"PUT",body:JSON.stringify({enabled,notify})}),
  screenRuns: () => request<import("./features/screener/workbenchTypes").RunSummary[]>("/api/workbench/runs"),
  screenDetail: (runId: string, symbol: string, latest = false) => request<import("./features/screener/workbenchTypes").StockDetail>(`/api/workbench/runs/${encodeURIComponent(runId)}/detail/${encodeURIComponent(symbol)}?latest=${latest}`),
  compareRuns: (runId: string, previousId: string) => request<import("./features/screener/workbenchTypes").RunComparison>(`/api/workbench/runs/${encodeURIComponent(runId)}/compare/${encodeURIComponent(previousId)}`),
  batchWatchlist: (runId: string, symbols: string[], allMatches: boolean, groupId?: string) => request<{added:number}>(`/api/workbench/runs/${encodeURIComponent(runId)}/watchlist`, {method:"POST", body:JSON.stringify({symbols, all_matches:allMatches, group_id:groupId})}),
  watchlist: () => request<import("./features/watchlist/model").WatchItem[]>("/api/watchlist"),
  watchGroups: () => request<import("./features/watchlist/model").WatchGroup[]>("/api/watchlist/groups"),
  createWatchGroup: (name: string) => request<import("./features/watchlist/model").WatchGroup>("/api/watchlist/groups", { method: "POST", body: JSON.stringify({ name }) }),
  renameWatchGroup: (id: string, name: string) => request<import("./features/watchlist/model").WatchGroup>(`/api/watchlist/groups/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ name }) }),
  deleteWatchGroup: (id: string) => request<void>(`/api/watchlist/groups/${encodeURIComponent(id)}`, { method: "DELETE" }),
  setWatchGroups: (symbol: string, groupIds: string[]) => request<object>(`/api/watchlist/${encodeURIComponent(symbol)}/groups`, { method: "PUT", body: JSON.stringify({ group_ids: groupIds }) }),
  addWatchlist: (symbol: string, runId?: string, groupId?: string) => request<import("./features/watchlist/model").WatchItem>("/api/watchlist", {
    method: "POST", body: JSON.stringify({ symbol, run_id: runId, group_id: groupId }),
  }),
  removeWatchlist: (symbol: string) => request<void>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  catalog: () => request<MetricSpec[]>("/api/catalog"),
  validateScreen: (tree: unknown) => request<ScreenValidation>("/api/screens/validate", {
    method: "POST",
    body: JSON.stringify(tree),
  }),
  listScreenTemplates: () => request<ScreenTemplate[]>("/api/screens/templates"),
  saveScreenTemplate: (name: string, tree: unknown) =>
    request<ScreenTemplate>("/api/screens/templates", {
      method: "POST",
      body: JSON.stringify({ name, tree }),
    }),
  deleteScreenTemplate: (templateId: string) =>
    request<void>(`/api/screens/templates/${encodeURIComponent(templateId)}`, {
      method: "DELETE",
    }),
  runScreen: async (payload: object, onProgress?: (value: {progress:number;message:string;processed:number;total:number}) => void): Promise<ScreenRunResult> => {
    type Job = {job_id:string;status:string;progress:number;message:string;processed:number;total:number;result?:ScreenRunResult;error?:string};
    let job = await request<Job>("/api/screens/tasks", {method:"POST",body:JSON.stringify(payload)});
    while (true) {
      onProgress?.(job);
      if (job.status === "completed" && job.result) return job.result;
      if (job.status === "failed") throw new Error(job.error || "筛选失败");
      await new Promise(resolve => window.setTimeout(resolve, 1000));
      job = await request<Job>(`/api/screens/tasks/${encodeURIComponent(job.job_id)}`);
    }
  },
  screenResults: (runId: string, limit: number, offset: number, sortBy?: string, sortDirection?: "asc" | "desc", newOnly = false, failedOnly = false) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (failedOnly) params.set("failed_only", "true");
    if (newOnly) params.set("new_only", "true");
    if (sortBy && sortDirection) {
      params.set("sort_by", sortBy);
      params.set("sort_direction", sortDirection);
    }
    return request<ScreenRunResult>(`/api/screens/runs/${encodeURIComponent(runId)}?${params}`);
  },
  searchSymbols: (query: string) =>
    request<SymbolSearchResult[]>(
      `/api/symbols/search?${new URLSearchParams({ q: query })}`,
    ),
  bars: (symbol: string, timeframe: Timeframe, start: string, end: string) =>
    request<Bar[]>(
      `/api/symbols/${encodeURIComponent(symbol)}/bars?${new URLSearchParams({ timeframe, start, end })}`,
    ),
  indicators: (symbol: string, timeframe: Timeframe, start: string, end: string) =>
    request<ChartIndicatorPoint[]>(
      `/api/symbols/${encodeURIComponent(symbol)}/indicators?${new URLSearchParams({ timeframe, start, end })}`,
    ),
  benchmarkComparison: (
    symbol: string,
    timeframe: Timeframe,
    start: string,
    end: string,
    startAt?: string,
    endAt?: string,
  ) => {
    const params = new URLSearchParams({ timeframe, start, end });
    if (startAt) params.set("start_at", startAt);
    if (endAt) params.set("end_at", endAt);
    return request<BenchmarkComparison>(
      `/api/symbols/${encodeURIComponent(symbol)}/benchmark-comparison?${params}`,
    );
  },
  syncChartData: (symbol: string, payload: ChartDataSyncRequest) =>
    request<ChartDataSyncResult>(
      `/api/symbols/${encodeURIComponent(symbol)}/chart-data/sync`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  chartShapes: (symbol: string, asOf: string, signal?: AbortSignal) =>
    request<{marks: import("./features/watchlist/model").ConditionMark[];data_date:string|null}>(`/api/symbols/${encodeURIComponent(symbol)}/chart-shapes?${new URLSearchParams({as_of:asOf})}`, {signal}),
  zones: (symbol: string, timeframe: Timeframe, asOf: string) =>
    request<PriceZone[]>(
      `/api/symbols/${encodeURIComponent(symbol)}/zones?${new URLSearchParams({ timeframe, as_of: asOf, limit_each: "3" })}`,
    ),
  createManualZone: (symbol: string, payload: object) =>
    request<PriceZone>(`/api/symbols/${encodeURIComponent(symbol)}/zones/manual`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteZone: (symbol: string, zoneId: string) =>
    request<void>(`/api/symbols/${encodeURIComponent(symbol)}/zones/${zoneId}`, {
      method: "DELETE",
    }),
  runBacktest: (payload: object) =>
    request<BacktestRun>("/api/backtests/run", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  monitorTasks: () => request<MonitorTask[]>("/api/monitor/tasks"),
  monitorStatus: () => request<MonitorStatus>("/api/monitor/status"),
  monitorSignals: () => request<MonitorSignal[]>("/api/monitor/signals"),
  createMonitorTask: (payload: object) => request<MonitorTask>("/api/monitor/tasks", {
    method: "POST", body: JSON.stringify(payload),
  }),
  toggleMonitorTask: (taskId: string, enabled: boolean) => request<MonitorTask>(`/api/monitor/tasks/${taskId}`, {
    method: "PATCH", body: JSON.stringify({ enabled }),
  }),
  deleteMonitorTask: (taskId: string) => request<void>(`/api/monitor/tasks/${taskId}`, { method: "DELETE" }),
  startMonitor: () => request<{ running: boolean }>("/api/monitor/start", { method: "POST" }),
  stopMonitor: () => request<{ running: boolean }>("/api/monitor/stop", { method: "POST" }),
  scanMonitor: () => request<{ triggered: number }>("/api/monitor/scan?scope=watchlist", { method: "POST" }),
  testFeishu: () => request<{ success: boolean }>("/api/notifications/feishu/test", { method: "POST" }),
};
