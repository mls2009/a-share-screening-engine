create table if not exists symbols (
  symbol varchar primary key,
  name varchar not null,
  exchange varchar not null,
  listed_on date,
  delisted_on date
);

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
