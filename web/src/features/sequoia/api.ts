import type { ConditionMark, WatchSource, WatchGroup } from '../watchlist/model';

export interface Strategy { id: string; name: string; description: string; parameters: Record<string, { label: string; default: number; min: number; max: number; integer: boolean }> }
export interface Config { period?: 'latest' | '1y' | '2y'; as_of: string; scope: 'market' | 'watchlist'; group_id: string | null; strategies: string[]; minimum_matches?: number; parameters: Record<string, Record<string, number>> }
export interface Check { label: string; actual: unknown; expected: unknown; operator: string; result: string; mark?: ConditionMark }
export interface EvidenceGroup { id: string; name: string; checks: Check[]; occurrences?: {date: string; end_date?: string; days?: number; breakout_level?: number; ended_on?: string; active?: boolean; checks: Check[]}[] }
export interface Match { quote_date?: string; hit_count?: number; last_match_date?: string; confluence_dates?: string[]; symbol: string; name: string; close: number; change_percent: number | null; groups: EvidenceGroup[]; source: WatchSource }
export interface Run { turtle_rule?: string; range_start?: string; statistics_unit?: string; observation_days?: number; run_id: string; status: string; progress: number; message: string; error?: string; config: Config; data_date?: string; universe_size: number; listing_date_unknown?: number; rps_universe_size?: number; match_count?: number; matches?: Match[]; groups: { id: string; name: string; matched: number; signal_count?: number; rejected: number; unknown: number; error?: string; examples: { symbol: string; reason: string }[] }[] }
async function request<T>(url: string, payload?: unknown): Promise<T> {
  const response = await fetch(url, payload === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : Array.isArray(value.detail) ? value.detail.map((x: {msg: string}) => x.msg).join('；') : '请求失败');
  return value as T;
}
export const sequoiaApi = {
  catalog: () => request<Strategy[]>('/api/sequoia/catalog'),
  groups: () => request<WatchGroup[]>('/api/watchlist/groups'),
  history: () => request<Run[]>('/api/sequoia/runs'),
  run: (id: string) => request<Run>(`/api/sequoia/runs/${encodeURIComponent(id)}`),
  start: (config: Config) => request<Run>('/api/sequoia/runs', config),
  add: (id: string, symbols: string[], target: string) => request<{added: number}>(`/api/sequoia/runs/${encodeURIComponent(id)}/watchlist`, { symbols, group_id: target && target !== 'strategy' ? target : null, by_strategy: target === 'strategy' }),
};
export function parseConfig(text: string, catalog: Strategy[]): Config {
  const value = JSON.parse(text) as Config;
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('JSON 必须是一个配置对象');
  if (Object.keys(value).some(key => !['as_of', 'period', 'scope', 'group_id', 'strategies', 'minimum_matches', 'parameters'].includes(key))) throw new Error('JSON 包含不支持的字段');
  if ((value.as_of !== '' && !/^\d{4}-\d{2}-\d{2}$/.test(value.as_of)) || !['market', 'watchlist'].includes(value.scope) || !Array.isArray(value.strategies) || !value.strategies.length || new Set(value.strategies).size !== value.strategies.length || value.strategies.some(id => !catalog.some(s => s.id === id))) throw new Error('日期、范围或策略不正确');
  if (value.group_id != null && (typeof value.group_id !== 'string' || value.scope !== 'watchlist')) throw new Error('自选分组配置不正确');
  if (value.period && !['latest','1y','2y'].includes(value.period)) throw new Error('识别时间范围不正确');
  if (value.minimum_matches !== undefined && (!Number.isInteger(value.minimum_matches) || value.minimum_matches < 1 || value.minimum_matches > value.strategies.length)) throw new Error('同日最少命中策略数不正确');
  if (value.period && value.period !== 'latest' && value.strategies.includes('placement')) throw new Error('定增名单不支持历史范围');
  const parameters = value.parameters ?? {};
  if (typeof parameters !== 'object' || Array.isArray(parameters) || parameters === null) throw new Error('parameters 必须是对象');
  for (const [id, params] of Object.entries(parameters)) {
    if (!value.strategies.includes(id) || !params || typeof params !== 'object' || Array.isArray(params)) throw new Error('策略参数格式不正确');
    for (const [key, number] of Object.entries(params)) {
      const spec = catalog.find(s => s.id === id)?.parameters[key];
      if (!spec || typeof number !== 'number' || !Number.isFinite(number) || number < spec.min || number > spec.max || (spec.integer && !Number.isInteger(number))) throw new Error(`${id}.${key} 参数无效`);
    }
  }
  return { ...value, group_id: value.group_id ?? null, parameters };
}
