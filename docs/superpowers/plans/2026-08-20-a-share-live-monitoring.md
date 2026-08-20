# A 股实时监控与飞书通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现交易日/交易时段内的自选股 5 秒监控、全市场 5 分钟扫描、点位和指标信号、幂等模拟交易、飞书通知及重启恢复。

**Architecture:** 调度器只决定何时运行，扫描器只读取行情并调用上一阶段的共享 `Strategy`。信号状态、模拟成交和通知发件箱在一个 DuckDB 事务内记录；通知发送在事务外重试，确保飞书失败不会重复交易。实时报价驱动点位规则，已完成 K 线驱动指标规则。

**Tech Stack:** Python 3.12、APScheduler、mootdx、DuckDB、HTTPX、Pydantic 2、pytest、freezegun、Ruff

---

## Public Interfaces

```python
# src/astock/live/service.py
class MonitoringService:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def run_watchlist_once(self, now: datetime) -> ScanSummary: ...
    def run_market_once(self, now: datetime) -> ScanSummary: ...

# src/astock/notifications/feishu.py
class FeishuNotifier:
    def send(self, message: NotificationMessage) -> DeliveryResult: ...
```

## File Map

```text
src/astock/live/calendar.py             交易日与时段判断
src/astock/live/models.py               监控任务、点位规则、信号状态
src/astock/live/repository.py           DuckDB 任务/状态/信号/发件箱
src/astock/live/bar_builder.py          实时报价合成最终 5 分钟 K 线
src/astock/live/evaluator.py            点位与共享指标策略求值
src/astock/live/simulator.py            实时模拟账户和下一报价成交
src/astock/live/scanner.py              自选股和全市场批量扫描
src/astock/live/scheduler.py            5 秒/5 分钟及盘后任务
src/astock/live/recovery.py             数据补齐与任务恢复
src/astock/live/keep_awake.py           macOS caffeinate 生命周期
src/astock/live/service.py              监控门面
src/astock/notifications/models.py      通知消息和状态
src/astock/notifications/feishu.py      签名、格式化和发送
src/astock/notifications/outbox.py      退避重试工作器
tests/live/                              实时模块测试
tests/notifications/                     飞书测试
```

### Task 1: Define calendar and monitoring models

**Files:**
- Create: `src/astock/live/__init__.py`
- Create: `src/astock/live/calendar.py`
- Create: `src/astock/live/models.py`
- Test: `tests/live/test_calendar.py`
- Test: `tests/live/test_models.py`

- [ ] **Step 1: Write failing session-boundary tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from astock.live.calendar import TradingCalendar

TZ = ZoneInfo("Asia/Shanghai")


def test_calendar_excludes_lunch_and_includes_session_edges(fake_trade_dates) -> None:
    calendar = TradingCalendar(fake_trade_dates)
    assert calendar.is_live(datetime(2026, 8, 20, 9, 30, tzinfo=TZ))
    assert calendar.is_live(datetime(2026, 8, 20, 11, 30, tzinfo=TZ))
    assert not calendar.is_live(datetime(2026, 8, 20, 11, 31, tzinfo=TZ))
    assert calendar.is_live(datetime(2026, 8, 20, 13, 0, tzinfo=TZ))
    assert not calendar.is_live(datetime(2026, 8, 22, 10, 0, tzinfo=TZ))
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_calendar.py tests/live/test_models.py -v`
Expected: FAIL because live modules do not exist.

- [ ] **Step 3: Implement timezone-safe sessions and models**

```python
# src/astock/live/calendar.py
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0)))


class TradingCalendar:
    def __init__(self, trading_dates: set[date]) -> None:
        self.trading_dates = trading_dates

    def is_live(self, now: datetime) -> bool:
        local = now.astimezone(SHANGHAI)
        return local.date() in self.trading_dates and any(start <= local.time() <= end for start, end in SESSIONS)
```

```python
# src/astock/live/models.py
from datetime import datetime, timedelta
from enum import StrEnum
from pydantic import BaseModel, Field
from astock.domain.market import Timeframe
from astock.domain.trading import Side


class MonitorKind(StrEnum):
    PRICE = "price"
    STRATEGY = "strategy"


class PriceComparator(StrEnum):
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"


class MonitorTask(BaseModel):
    task_id: str
    name: str
    kind: MonitorKind
    symbols: list[str]
    timeframe: Timeframe | None = None
    strategy_id: str | None = None
    enabled: bool = True
    simulate: bool = False
    cooldown: timedelta = timedelta(0)


class PriceRule(BaseModel):
    rule_id: str
    task_id: str
    symbol: str
    comparator: PriceComparator
    threshold: float = Field(gt=0)
    action: Side | None = None


class SignalState(BaseModel):
    rule_id: str
    symbol: str
    active: bool = False
    last_value: float | None = None
    last_triggered_at: datetime | None = None
```

Add model validators: price tasks require rules but no strategy; strategy tasks require strategy/timeframe; `simulate=True` requires an action or strategy sizing configuration.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/live/test_calendar.py tests/live/test_models.py -v`
Expected: PASS.

```bash
git add src/astock/live tests/live/test_calendar.py tests/live/test_models.py
git commit -m "feat: define live monitoring sessions and tasks"
```

### Task 2: Persist tasks, signal state, simulated ledger and outbox

**Files:**
- Modify: `src/astock/storage/schema.sql`
- Create: `src/astock/live/repository.py`
- Test: `tests/live/test_repository.py`

- [ ] **Step 1: Write transaction and unique-key tests**

```python
def test_record_trigger_is_idempotent(repository, trigger) -> None:
    first = repository.record_trigger(trigger)
    second = repository.record_trigger(trigger)
    assert first.created is True
    assert second.created is False
    assert repository.count_signals() == 1
    assert repository.count_outbox() == 1
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_repository.py -v`
Expected: FAIL because schema and repository are missing.

- [ ] **Step 3: Add the persisted schema**

Add tables:

```sql
create table if not exists monitor_tasks (
  task_id varchar primary key, payload_json json not null, enabled boolean not null,
  updated_at timestamp not null default current_timestamp
);
create table if not exists signal_states (
  rule_id varchar not null, symbol varchar not null, active boolean not null,
  last_value double, last_triggered_at timestamp,
  primary key(rule_id, symbol)
);
create table if not exists signals (
  signal_key varchar primary key, task_id varchar not null, rule_id varchar not null,
  strategy_id varchar, symbol varchar not null, timeframe varchar,
  bar_timestamp timestamp, triggered_at timestamp not null, payload_json json not null
);
create table if not exists simulation_accounts (
  account_id varchar primary key, mode varchar not null, cash double not null,
  frozen_cash double not null default 0, updated_at timestamp not null
);
create table if not exists simulation_positions (
  account_id varchar not null, symbol varchar not null, quantity bigint not null,
  sellable_quantity bigint not null, average_cost double not null,
  realized_pnl double not null default 0,
  primary key(account_id, symbol)
);
create table if not exists simulation_orders (
  order_id varchar primary key, signal_key varchar unique not null,
  payload_json json not null, status varchar not null, created_at timestamp not null
);
create table if not exists simulation_fills (
  fill_id varchar primary key, order_id varchar unique not null,
  payload_json json not null, filled_at timestamp not null
);
create table if not exists notification_outbox (
  message_id varchar primary key, signal_key varchar unique,
  payload_json json not null, status varchar not null, attempts integer not null default 0,
  next_attempt_at timestamp not null, last_error varchar
);
```

- [ ] **Step 4: Implement atomic `record_trigger()`**

Build `signal_key` as SHA-256 of `task_id|rule_id|strategy_id|symbol|timeframe|bar_timestamp`. In one DuckDB transaction: insert signal with `on conflict do nothing`; only if inserted, update signal state, create at most one simulation order, and insert one outbox row. Roll back all writes on any failure.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/live/test_repository.py -v`
Expected: PASS, including an injected mid-transaction error that leaves every table unchanged.

```bash
git add src/astock/storage/schema.sql src/astock/live/repository.py tests/live/test_repository.py
git commit -m "feat: persist idempotent monitoring state"
```

### Task 3: Build completed 5-minute bars from quotes

**Files:**
- Create: `src/astock/live/bar_builder.py`
- Test: `tests/live/test_bar_builder.py`

- [ ] **Step 1: Test bar finalization and lunch separation**

```python
def test_builder_emits_bar_only_after_bucket_closes() -> None:
    builder = FiveMinuteBarBuilder()
    assert builder.add(quote_at("09:30:01", 10, 100)) == []
    assert builder.add(quote_at("09:34:59", 11, 300)) == []
    completed = builder.add(quote_at("09:35:00", 12, 500))
    assert len(completed) == 1
    assert completed[0].open == 10
    assert completed[0].close == 11
    assert completed[0].volume_shares == 200
    assert completed[0].is_final is True
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_bar_builder.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement cumulative-volume delta aggregation**

Keep one in-memory state per symbol containing bucket, OHLC, prior cumulative volume/amount and last timestamp. Convert cumulative quote totals to non-negative deltas; if the source counters reset or go backwards, mark the state invalid and wait for historical reconciliation. Bucket anchors are 09:30 and 13:00, never wall-clock floor across lunch. Emit the prior bucket when the first quote of a later valid bucket arrives.

- [ ] **Step 4: Add stale/out-of-order tests**

Reject a quote older than the last accepted timestamp; never finalize from a stale quote; flush 11:30 and 15:00 bars with an explicit scheduler callback. Persist only emitted final bars through `BarStore.upsert()`.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/live/test_bar_builder.py -v`
Expected: PASS.

```bash
git add src/astock/live/bar_builder.py tests/live/test_bar_builder.py
git commit -m "feat: build finalized realtime five-minute bars"
```

### Task 4: Evaluate price crossings and completed-bar strategies

**Files:**
- Create: `src/astock/live/evaluator.py`
- Test: `tests/live/test_evaluator.py`

- [ ] **Step 1: Test false-to-true transitions and cooldown**

```python
def test_price_rule_triggers_only_on_false_to_true_transition() -> None:
    state = SignalState(rule_id="r1", symbol="600519.SH", active=False, last_value=99)
    first = evaluator.price(rule_above_100, state, quote(price=101), NOW)
    held = evaluator.price(rule_above_100, first.state, quote(price=102), NOW_PLUS_5S)
    reset = evaluator.price(rule_above_100, held.state, quote(price=99), NOW_PLUS_10S)
    again = evaluator.price(rule_above_100, reset.state, quote(price=101), NOW_PLUS_20S)
    assert [first.triggered, held.triggered, reset.triggered, again.triggered] == [True, False, False, True]
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_evaluator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement point-price state transitions**

`cross_above` is true only when prior value `<= threshold` and current value `> threshold`; `cross_below` is symmetric. A persistent true state cannot trigger again. A false state resets immediately. After reset, suppress a new trigger until `last_triggered_at + cooldown`, while still updating the state/value.

- [ ] **Step 4: Reuse the strategy API for indicator rules**

`evaluate_strategy()` receives only a newly finalized bar plus history ending at that bar, constructs `StrategyContext`, and calls the same strategy used by backtests. It must reject `is_final=False`. Use the bar timestamp, not scan time, in the signal key.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/live/test_evaluator.py -v`
Expected: PASS.

```bash
git add src/astock/live/evaluator.py tests/live/test_evaluator.py
git commit -m "feat: evaluate realtime price and strategy signals"
```

### Task 5: Reuse trading rules in the simulated account

**Files:**
- Create: `src/astock/live/simulator.py`
- Test: `tests/live/test_simulator.py`

- [ ] **Step 1: Test signal-to-next-quote execution and idempotency**

```python
def test_strategy_signal_fills_on_next_fresh_quote_once(simulator) -> None:
    simulator.queue(SIGNAL_AT_10_00)
    assert simulator.on_quote(quote_at("10:00:00", 10)).fills == []
    first = simulator.on_quote(quote_at("10:00:05", 10.1))
    second = simulator.on_quote(quote_at("10:00:10", 10.2))
    assert len(first.fills) == 1
    assert second.fills == []
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_simulator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement persisted pending orders**

Price rules with simulation action may use the triggering fresh quote; completed-bar strategy signals wait for the first fresh quote strictly after `signal_at`. Load the account and pending order inside a transaction, delegate fee/T+1/lot/limit/suspension decisions to the backtest `Broker`, persist fill/account/position/order status, and use unique `signal_key`/`order_id` constraints.

- [ ] **Step 4: Implement daily T+1 rollover and equity snapshots**

At the first run on a new trading date, set `sellable_quantity = quantity` once and record the rollover date. At close, persist cash, positions, marked value, realized/unrealized P&L and total equity. Test restart before and after rollover.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/live/test_simulator.py -v`
Expected: PASS.

```bash
git add src/astock/live/simulator.py tests/live/test_simulator.py
git commit -m "feat: maintain idempotent simulated positions"
```

### Task 6: Implement signed Feishu messages and transactional outbox delivery

**Files:**
- Create: `src/astock/notifications/__init__.py`
- Create: `src/astock/notifications/models.py`
- Create: `src/astock/notifications/feishu.py`
- Create: `src/astock/notifications/outbox.py`
- Modify: `src/astock/config.py`
- Test: `tests/notifications/test_feishu.py`
- Test: `tests/notifications/test_outbox.py`

- [ ] **Step 1: Write signature, payload and retry tests**

```python
def test_feishu_signature_matches_known_vector() -> None:
    assert sign(timestamp="1599360473", secret="test-secret") == KNOWN_SIGNATURE


def test_failed_delivery_schedules_exponential_retry(outbox, failing_notifier) -> None:
    outbox.deliver_due(NOW, failing_notifier)
    row = outbox.get("m1")
    assert row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(seconds=5)
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/notifications -v`
Expected: FAIL.

- [ ] **Step 3: Implement Feishu webhook client**

Read `ASTOCK_FEISHU_WEBHOOK` and `ASTOCK_FEISHU_SECRET` from environment-only settings using secret types; never serialize or log them. Generate the documented timestamp/HMAC signature, send an interactive card via HTTPX, require HTTP 2xx and Feishu response code 0, and return a structured result.

Message card fields: stock name/code, trigger time, timeframe, price, strategy/rule and concrete condition values, simulated order/fill or rejection, holdings and P&L. Also support system status, source outage/recovery and close summary variants.

- [ ] **Step 4: Implement outbox retries**

Select only pending rows with `next_attempt_at <= now`; claim a row before network I/O; mark sent on success; on failure set pending and delay `min(5 * 2**attempts, 1800)` seconds plus deterministic test-injected jitter. After configured maximum attempts, mark failed and retain the error. Never call simulation code from the delivery worker.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/notifications -v`
Expected: PASS with mocked HTTP; no secret appears in captured logs.

```bash
git add src/astock/notifications src/astock/config.py tests/notifications
git commit -m "feat: deliver idempotent Feishu notifications"
```

### Task 7: Build watchlist and market scanners with freshness gates

**Files:**
- Create: `src/astock/live/scanner.py`
- Test: `tests/live/test_scanner.py`

- [ ] **Step 1: Test batching, isolation and stale-source behavior**

```python
def test_stale_quote_pauses_symbol_without_triggering(scanner) -> None:
    source.returns([quote(symbol="600519.SH", timestamp=NOW_MINUS_2M, price=101)])
    result = scanner.scan_watchlist(NOW)
    assert result.triggered == 0
    assert result.paused_symbols == {"600519.SH": "stale_quote"}
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_scanner.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement bounded batched scans**

Watchlist scans active symbols every invocation; market scans load the point-in-time active A-share universe and process configurable batches with a request timeout. Validate source timestamp age before any rule evaluation. A failed batch records source health and continues other batches; it never substitutes cached prices for signals.

- [ ] **Step 4: Wire quote and bar paths**

For every fresh quote: evaluate price rules, feed the 5-minute builder, execute pending simulated orders. For each emitted final 5-minute bar: persist it, derive any due 15/30/60 bars, evaluate matching strategies. At close, reconcile the unadjusted and configured adjusted daily bars with BaoStock, evaluate daily strategies, derive/evaluate weekly or monthly strategies when that trading date closes the period, and record every correction.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/live/test_scanner.py -v`
Expected: PASS.

```bash
git add src/astock/live/scanner.py tests/live/test_scanner.py
git commit -m "feat: scan watchlists and market safely"
```

### Task 8: Schedule scans, recovery and macOS keep-awake

**Files:**
- Create: `src/astock/live/scheduler.py`
- Create: `src/astock/live/recovery.py`
- Create: `src/astock/live/keep_awake.py`
- Test: `tests/live/test_scheduler.py`
- Test: `tests/live/test_recovery.py`
- Test: `tests/live/test_keep_awake.py`

- [ ] **Step 1: Write schedule and process-lifecycle tests**

```python
def test_scheduler_has_required_intervals(scheduler) -> None:
    scheduler.configure()
    assert scheduler.interval_for("watchlist") == timedelta(seconds=5)
    assert scheduler.interval_for("market") == timedelta(minutes=5)


def test_keep_awake_releases_child_process(fake_popen) -> None:
    with KeepAwake(enabled=True):
        assert fake_popen.started_with == ["caffeinate", "-dimsu"]
    assert fake_popen.process.terminated
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_scheduler.py tests/live/test_recovery.py tests/live/test_keep_awake.py -v`
Expected: FAIL.

- [ ] **Step 3: Configure guarded jobs**

Use APScheduler interval jobs at 5 seconds and 5 minutes, both wrapped by `TradingCalendar.is_live()`, with `max_instances=1`, `coalesce=True`, and misfire grace shorter than the next interval. Add explicit pre-open task/data-source status, session-close bar flush, close reconciliation/summary, and next-trading-day rollover jobs. Weekly/monthly strategies run only after the last trading session of the period closes. Source outage and recovery notifications fire only when persisted health state changes, not on every failed request.

- [ ] **Step 4: Implement startup recovery**

On startup: migrate DB → load calendar/tasks/account/state → detect unclean stop → reconcile pending/final bars and covered data → reset stuck outbox claims → resume only enabled tasks. If required data cannot be repaired, keep affected tasks paused with a visible reason while unrelated tasks start.

- [ ] **Step 5: Implement keep-awake ownership**

Start `caffeinate -dimsu` only when monitoring starts and the setting is enabled. Store the child handle, terminate and wait on normal stop, and register a process-exit cleanup. Never kill unrelated `caffeinate` processes.

- [ ] **Step 6: Run tests and commit**

Run: `python -m pytest tests/live/test_scheduler.py tests/live/test_recovery.py tests/live/test_keep_awake.py -v`
Expected: PASS.

```bash
git add src/astock/live tests/live/test_scheduler.py tests/live/test_recovery.py tests/live/test_keep_awake.py
git commit -m "feat: schedule and recover realtime monitoring"
```

### Task 9: Expose the monitoring service and end-to-end regression

**Files:**
- Create: `src/astock/live/service.py`
- Modify: `src/astock/cli.py`
- Test: `tests/live/test_monitoring_e2e.py`

- [ ] **Step 1: Write the recorded end-to-end test**

```python
def test_trigger_notification_fill_and_restart_are_idempotent(system) -> None:
    system.enable(TASK)
    system.feed([QUOTE_BELOW, QUOTE_ABOVE, NEXT_QUOTE])
    system.restart()
    system.feed([NEXT_QUOTE])
    assert system.signal_count == 1
    assert system.fill_count == 1
    assert system.outbox_count == 1
    assert system.account.position("600519.SH").quantity == 100
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/live/test_monitoring_e2e.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the service facade**

`MonitoringService.start()` performs recovery, starts keep-awake, configures the scheduler and starts outbox delivery. `stop()` prevents new scans, waits for active scans, flushes final state, stops workers and releases keep-awake. `run_watchlist_once()` and `run_market_once()` remain deterministic synchronous entry points for tests and manual diagnostics.

- [ ] **Step 4: Add CLI operations**

```text
astock monitor start
astock monitor stop
astock monitor status
astock monitor scan --scope watchlist
astock notify test
```

The long-running `start` command handles SIGINT/SIGTERM and exits only after `stop()` finishes.

- [ ] **Step 5: Run milestone verification and online smoke tests**

Run:

```bash
python -m pytest tests/live tests/notifications -v
ruff check .
astock monitor scan --scope watchlist
astock notify test
```

Expected: offline tests PASS; on a trading day the scan returns fresh quotes; configured Feishu receives exactly one test card.

- [ ] **Step 6: Commit**

```bash
git add src/astock/live/service.py src/astock/cli.py tests/live/test_monitoring_e2e.py
git commit -m "feat: expose resilient realtime monitoring service"
```

## Milestone Verification

Run:

```bash
python -m pytest --cov=astock.live --cov=astock.notifications --cov-report=term-missing
ruff check .
```

Expected:

- the watchlist path is callable every 5 seconds and market path every 5 minutes only during A-share sessions;
- price rules use fresh quotes; indicator rules use only finalized bars and the shared strategy API;
- false-to-true state, cooldown and unique signal keys prevent duplicate alerts;
- notification retries cannot repeat simulated orders or fills;
- task/state/account/outbox recovery survives a process restart;
- stale or missing data pauses only affected tasks and records a user-visible reason.
