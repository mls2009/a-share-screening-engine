create table if not exists symbols (
  symbol varchar primary key,
  name varchar not null,
  exchange varchar not null,
  listed_on date,
  delisted_on date,
  board varchar,
  instrument_type varchar not null default 'stock',
  is_listed boolean not null default true
);

alter table symbols add column if not exists board varchar;
alter table symbols add column if not exists instrument_type varchar default 'stock';
alter table symbols add column if not exists is_listed boolean default true;

create table if not exists trading_calendar (
  trade_date date primary key,
  is_open boolean not null
);

create table if not exists security_status (
  symbol varchar not null,
  trade_date date not null,
  board varchar not null,
  is_st boolean not null,
  is_suspended boolean not null,
  previous_close double,
  limit_up double,
  limit_down double,
  primary key(symbol, trade_date)
);

create table if not exists bar_coverage (
  symbol varchar not null,
  timeframe varchar not null,
  adjustment varchar not null,
  start_at timestamp not null,
  end_at timestamp not null,
  primary key(symbol, timeframe, adjustment, start_at, end_at)
);

create table if not exists adjustment_factors (
  symbol varchar not null,
  trade_date date not null,
  forward_factor double not null,
  backward_factor double not null,
  source varchar not null,
  primary key(symbol, trade_date)
);

create table if not exists corporate_actions (
  symbol varchar not null,
  ex_date date not null,
  cash_per_share double not null default 0,
  share_ratio double not null default 0,
  source varchar not null,
  primary key(symbol, ex_date)
);

create table if not exists quality_issues (
  issue_id uuid default uuid(),
  symbol varchar not null,
  timestamp timestamp,
  code varchar not null,
  detail varchar not null,
  created_at timestamp default current_timestamp
);

create table if not exists watchlist (
  symbol varchar primary key,
  name varchar not null,
  sources json not null default '[]',
  added_at timestamp default current_timestamp
);

create table if not exists market_features (
  symbol varchar not null,
  timeframe varchar not null,
  feature_date date not null,
  feature_version varchar not null,
  open double,
  high double,
  low double,
  close double,
  volume double,
  amount double,
  return_1 double,
  return_3 double,
  return_5 double,
  return_10 double,
  return_20 double,
  return_60 double,
  return_120 double,
  return_250 double,
  volume_ma_5 double,
  volume_ma_20 double,
  volume_ma_60 double,
  volume_ratio_20 double,
  ma_5 double,
  ma_10 double,
  ma_20 double,
  ma_30 double,
  ma_60 double,
  ma_120 double,
  ma_250 double,
  macd double,
  macd_signal double,
  macd_hist double,
  kdj_k double,
  kdj_d double,
  kdj_j double,
  rsi_14 double,
  boll_upper double,
  boll_middle double,
  boll_lower double,
  atr_14 double,
  obv double,
  amplitude double,
  volatility_20 double,
  listing_trade_days integer,
  is_new boolean,
  is_secondary_new boolean,
  extra json,
  created_at timestamp not null default current_timestamp,
  primary key(symbol, timeframe, feature_date, feature_version)
);

create table if not exists pattern_events (
  symbol varchar not null,
  timeframe varchar not null,
  event_date date not null,
  pattern_type varchar not null,
  rule_version varchar not null,
  strength double not null,
  body_ratio double,
  upper_shadow_ratio double,
  lower_shadow_ratio double,
  amplitude_ratio double,
  parameters json,
  primary key(symbol, timeframe, event_date, pattern_type, rule_version)
);

create table if not exists support_resistance_zones (
  zone_id uuid primary key default uuid(),
  symbol varchar not null,
  timeframe varchar not null,
  as_of_date date not null,
  zone_kind varchar not null,
  geometry varchar not null,
  lower_price double not null,
  center_price double not null,
  upper_price double not null,
  slope double,
  intercept double,
  anchors json,
  strength double not null,
  touches integer not null,
  first_touched_on date,
  last_touched_on date,
  state varchar not null default 'active',
  source varchar not null default 'auto',
  rule_version varchar not null,
  created_at timestamp not null default current_timestamp
);

delete from support_resistance_zones
where source = 'auto' and geometry = 'trend';

create table if not exists zone_detection_batches (
  symbol varchar not null,
  timeframe varchar not null,
  as_of_date date not null,
  rule_version varchar not null,
  latest_bar_at timestamptz not null,
  source_revision varchar not null default 'legacy',
  created_at timestamp not null default current_timestamp,
  primary key(symbol, timeframe, as_of_date)
);

insert into zone_detection_batches
  (symbol, timeframe, as_of_date, rule_version, latest_bar_at,
   source_revision, created_at)
select symbol, timeframe, as_of_date, max(rule_version),
  cast(as_of_date as timestamptz), 'legacy', min(created_at)
from support_resistance_zones
where source = 'auto'
group by symbol, timeframe, as_of_date
on conflict do nothing;

create table if not exists zone_deletion_markers (
  marker_id uuid primary key,
  symbol varchar not null,
  timeframe varchar not null,
  geometry varchar not null,
  lower_price double not null,
  center_price double not null,
  upper_price double not null,
  deleted_at timestamp not null default current_timestamp
);

create table if not exists data_sync_jobs (
  job_id uuid primary key,
  start_date date not null,
  end_date date not null,
  status varchar not null,
  total integer not null,
  succeeded integer not null default 0,
  failed integer not null default 0,
  current_symbol varchar,
  created_at timestamp not null default current_timestamp,
  started_at timestamp not null default current_timestamp,
  finished_at timestamp
);

create table if not exists sync_job_symbols (
  job_id uuid not null,
  symbol varchar not null,
  status varchar not null,
  error varchar,
  updated_at timestamp not null default current_timestamp,
  primary key(job_id, symbol)
);

create table if not exists sync_job_failures (
  job_id uuid not null,
  symbol varchar not null,
  error varchar not null,
  created_at timestamp not null default current_timestamp,
  resolved_at timestamp,
  primary key(job_id, symbol)
);

create table if not exists screen_definitions (
  definition_id uuid primary key default uuid(),
  name varchar not null,
  version integer not null default 1,
  condition_tree json not null,
  created_at timestamp not null default current_timestamp,
  updated_at timestamp not null default current_timestamp
);

create table if not exists screen_runs (
  run_id uuid primary key default uuid(),
  definition_id uuid,
  mode varchar not null,
  as_of_date date,
  feature_version varchar not null,
  condition_tree json not null,
  universe_size integer not null default 0,
  realtime_covered integer not null default 0,
  failed_batches integer not null default 0,
  status varchar not null,
  snapshot json,
  created_at timestamp not null default current_timestamp,
  finished_at timestamp
);

alter table screen_runs add column if not exists diagnostics json default '{}';

create table if not exists screen_matches (
  run_id uuid not null,
  symbol varchar not null,
  match_rank integer not null,
  feature_snapshot json not null,
  explanation json not null,
  created_at timestamp not null default current_timestamp,
  primary key(run_id, symbol)
);

create table if not exists backtest_runs (
  run_id uuid primary key,
  status varchar not null,
  request json not null,
  metrics json not null,
  result json not null,
  created_at timestamp not null default current_timestamp,
  finished_at timestamp
);

create table if not exists backtest_trades (
  run_id uuid not null,
  sequence integer not null,
  symbol varchar not null,
  side varchar not null,
  signal_at timestamp not null,
  executed_at timestamp not null,
  quantity integer not null,
  price double not null,
  gross double not null,
  fees double not null,
  reason varchar not null,
  primary key(run_id, sequence)
);

create table if not exists backtest_equity (
  run_id uuid not null,
  timestamp timestamp not null,
  cash double not null,
  market_value double not null,
  equity double not null,
  drawdown double not null,
  primary key(run_id, timestamp)
);

create table if not exists monitor_tasks (
  task_id uuid primary key,
  name varchar not null,
  symbols json not null,
  comparator varchar not null,
  threshold double not null,
  cooldown_seconds integer not null,
  scope varchar not null,
  enabled boolean not null,
  created_at timestamp not null default current_timestamp,
  updated_at timestamp not null default current_timestamp
);

create table if not exists signal_states (
  task_id uuid not null,
  symbol varchar not null,
  active boolean not null,
  last_value double,
  last_triggered_at timestamp,
  primary key(task_id, symbol)
);

create table if not exists signals (
  signal_key varchar primary key,
  task_id uuid not null,
  symbol varchar not null,
  quote_timestamp timestamp not null,
  triggered_at timestamp not null,
  price double not null,
  threshold double not null,
  comparator varchar not null,
  payload json not null
);

create table if not exists notification_outbox (
  message_id uuid primary key,
  signal_key varchar unique,
  payload json not null,
  status varchar not null,
  attempts integer not null default 0,
  next_attempt_at timestamp not null,
  last_error varchar,
  updated_at timestamp not null default current_timestamp
);
