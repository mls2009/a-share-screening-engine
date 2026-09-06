import type { Evaluation } from "../../types";
import type { WatchSource, SourceNode } from "../watchlist/model";
export interface RunSummary { run_id: string; as_of: string; mode: string; tree: SourceNode; finished_at: string; match_count: number }
export interface StockDetail { symbol: string; features: Record<string, unknown>; source: WatchSource; recent: Array<{ date: string; evaluation: Evaluation }>; checked_at: string; latest: boolean }
export interface RunComparison { same_definition: boolean; same_scope: boolean; same_mode: boolean; current_date: string; previous_date: string; entered: Array<{symbol: string; name: string}>; stayed: Array<{symbol: string; name: string}>; exited: Array<{symbol: string; name: string}> }
