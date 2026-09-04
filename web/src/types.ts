export type Timeframe = "5m" | "15m" | "30m" | "60m" | "1d" | "1w" | "1mo";
export type Unit = "price" | "percent" | "ratio" | "shares" | "amount" | "days" | "boolean" | "category" | "score";

export interface MetricChoice {
  value: string;
  label: string;
}

export interface MetricSpec {
  key: string;
  label: string;
  unit: Unit;
  timeframes: Timeframe[];
  operators: string[];
  group?: string;
  family?: string;
  period?: number | "history" | null;
  directions?: MetricChoice[];
  choices?: MetricChoice[];
  multiple?: boolean;
  visible?: boolean;
}

export interface UiConstantOperand {
  kind: "constant";
  value: string;
}

export interface UiMetricOperand {
  kind: "metric";
  metric: string;
  timeframe: Timeframe;
  multiplier: number;
}

export type UiOperand = UiConstantOperand | UiMetricOperand;

export interface UiConditionNode {
  id: string;
  kind: "condition";
  metric: string;
  timeframe: Timeframe;
  operator: string;
  right: UiOperand;
  direction?: "rise" | "fall" | "increase" | "decrease";
  selectedValues?: string[];
  lookback?: number;
  occurrences?: number;
}

export interface UiGroupNode {
  id: string;
  kind: "group";
  logic: "and" | "or" | "not";
  children: UiNode[];
}

export type UiNode = UiConditionNode | UiGroupNode;

export interface ScreenMatch {
  symbol: string;
  rank: number;
  features: Record<string, unknown>;
  explanation: Evaluation;
}

export interface Evaluation {
  path: string;
  result: "true" | "false" | "unknown";
  actual?: unknown;
  expected?: unknown;
  unit?: string;
  children: Evaluation[];
}

export interface ScreenRunResult {
  run_id: string;
  status: string;
  universe_size: number;
  match_count: number;
  realtime_covered: number;
  failed_batches: number;
  matches: ScreenMatch[];
}

export interface ScreenValidation {
  valid: boolean;
  errors: Array<{ code: string; message: string; path: string }>;
}

export interface ScreenTemplate {
  template_id: string;
  name: string;
  version: number;
  tree: unknown;
  updated_at: string;
}

export interface Bar {
  symbol: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume_shares: number;
  amount_cny: number;
}

export type ChartIndicator = "ma" | "boll" | "macd" | "kdj" | "rsi" | "volume_ma" | "obv" | "atr";

export interface ChartIndicatorPoint {
  timestamp: string;
  ma_5: number | null;
  ma_10: number | null;
  ma_20: number | null;
  ma_30: number | null;
  boll_upper: number | null;
  boll_middle: number | null;
  boll_lower: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  kdj_k: number | null;
  kdj_d: number | null;
  kdj_j: number | null;
  rsi_14: number | null;
  volume_ma_5: number | null;
  volume_ma_20: number | null;
  obv: number | null;
  atr_14: number | null;
}

export interface SymbolSearchResult {
  symbol: string;
  name: string;
  exchange: "SH" | "SZ" | "BJ";
  instrument_type: "stock" | "etf";
}

export interface PriceZoneBase {
  zone_id: string;
  timeframe: Timeframe;
  as_of_date: string;
  lower_price: number;
  center_price: number;
  upper_price: number;
  anchors: string | Array<[string, number]>;
  strength: number;
  touches: number;
  reappeared: boolean;
}

export type PriceZone = PriceZoneBase & (
  | { source: "auto"; geometry: "horizontal"; zone_kind: "support" | "resistance"; slope: null; intercept: null }
  | { source: "auto"; geometry: "trend"; zone_kind: "uptrend" | "downtrend"; slope: number; intercept: number }
  | { source: "manual"; geometry: "horizontal"; zone_kind: "support" | "resistance"; slope: null; intercept: null }
  | { source: "manual"; geometry: "trend"; zone_kind: "support" | "resistance"; slope: number; intercept: number }
);

export interface BacktestMetrics {
  total_return: number;
  annualized_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  win_rate: number;
  profit_loss_ratio: number;
  trade_count: number;
  total_fees: number;
}

export interface BacktestTrade {
  symbol: string;
  side: "buy" | "sell";
  signal_at: string;
  timestamp: string;
  quantity: number;
  price: number;
  gross: number;
  commission: number;
  tax: number;
  transfer_fee: number;
  reason: string;
}

export interface EquityPoint {
  timestamp: string;
  cash: number;
  market_value: number;
  equity: number;
  drawdown: number;
}

export interface BacktestRun {
  run_id: string;
  result: {
    request: { symbols: string[]; [key: string]: unknown };
    metrics: BacktestMetrics;
    trades: BacktestTrade[];
    equity_curve: EquityPoint[];
    rejected_orders: string[];
  };
}

export type PriceComparator = "above" | "below" | "cross_above" | "cross_below";

export interface MonitorTask {
  task_id: string;
  name: string;
  symbols: string[];
  comparator: PriceComparator;
  threshold: number;
  cooldown_seconds: number;
  scope: "watchlist" | "market";
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MonitorStatus {
  running: boolean;
  tasks: number;
  enabled_tasks: number;
  pending_notifications: number;
  feishu_configured: boolean;
  watchlist_interval_seconds: number;
  market_interval_seconds: number;
}

export interface MonitorSignal {
  signal_key: string;
  symbol: string;
  price: number;
  threshold: number;
  comparator: PriceComparator;
  triggered_at: string;
}
