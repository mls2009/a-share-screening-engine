# A 股策略与回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在统一行情服务之上实现可复现的配置式/Python 策略、简化/真实 A 股撮合、单股/组合回测及完整报告。

**Architecture:** 指标层只接收已完成 K 线；配置规则与 Python 策略统一输出 `SignalIntent`。事件驱动回测器在当前 K 线收盘生成意图，在下一根 K 线开盘撮合。撮合规则、账户记账和绩效统计均为纯领域逻辑，便于后续实时监控复用。

**Tech Stack:** Python 3.12、Pandas、NumPy、Pydantic 2、DuckDB、Parquet、pytest、Ruff

---

## Public Interfaces

```python
# src/astock/strategy/base.py
class Strategy(Protocol):
    def on_bar(self, context: StrategyContext) -> list[SignalIntent]: ...

# src/astock/backtest/engine.py
class BacktestEngine:
    def run(self, request: BacktestRequest) -> BacktestResult: ...

# src/astock/backtest/service.py
class BacktestService:
    def submit(self, request: BacktestRequest) -> str: ...
    def run_now(self, request: BacktestRequest) -> BacktestResult: ...
```

`Strategy` 是下一阶段实时监控唯一可调用的策略入口；监控模块不得调用回测器内部对象。

## File Map

```text
src/astock/domain/trading.py             信号、订单、成交、持仓与费用模型
src/astock/indicators/core.py             MA/MACD/KDJ/RSI/布林带
src/astock/strategy/base.py               共享策略协议与无未来数据上下文
src/astock/strategy/rules.py              配置条件与一层 AND/OR 组合
src/astock/strategy/configured.py         配置式策略
src/astock/strategy/python_loader.py       Python 策略加载与异常隔离
src/astock/backtest/models.py              回测请求、模式、结果模型
src/astock/backtest/broker.py              撮合、T+1、整手、涨跌停与费用
src/astock/backtest/corporate_actions.py   分红送转
src/astock/backtest/portfolio.py           账户、仓位与资金分配
src/astock/backtest/engine.py              时间线与事件循环
src/astock/backtest/metrics.py             收益、风险和交易指标
src/astock/backtest/report.py              Parquet 明细与 DuckDB 摘要
src/astock/backtest/service.py             数据准备与任务入口
tests/                                    对应测试与固定回归样本
```

### Task 1: Define immutable trading and backtest models

**Files:**
- Create: `src/astock/domain/trading.py`
- Create: `src/astock/backtest/models.py`
- Test: `tests/domain/test_trading.py`

- [ ] **Step 1: Write failing validation tests**

```python
from datetime import datetime
from pydantic import ValidationError
import pytest

from astock.domain.market import Timeframe
from astock.domain.trading import Side, SignalIntent


def test_signal_requires_positive_quantity_or_weight() -> None:
    with pytest.raises(ValidationError):
        SignalIntent(strategy_id="s1", symbol="600519.SH", timeframe=Timeframe.DAY,
                     signal_at=datetime(2026, 8, 20, 15), side=Side.BUY, reason="cross")


def test_signal_cannot_set_quantity_and_target_weight_together() -> None:
    with pytest.raises(ValidationError):
        SignalIntent(strategy_id="s1", symbol="600519.SH", timeframe=Timeframe.DAY,
                     signal_at=datetime(2026, 8, 20, 15), side=Side.BUY, reason="cross",
                     quantity=100, target_weight=0.2)
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `python -m pytest tests/domain/test_trading.py -v`
Expected: FAIL because `astock.domain.trading` does not exist.

- [ ] **Step 3: Implement the models**

```python
# src/astock/domain/trading.py
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, model_validator
from astock.domain.market import Timeframe


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class SignalIntent(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_id: str
    symbol: str
    timeframe: Timeframe
    signal_at: datetime
    side: Side
    reason: str
    quantity: int | None = None
    target_weight: float | None = None

    @model_validator(mode="after")
    def validate_size(self) -> "SignalIntent":
        supplied = [self.quantity is not None, self.target_weight is not None]
        if sum(supplied) != 1:
            raise ValueError("set exactly one of quantity or target_weight")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.target_weight is not None and not 0 <= self.target_weight <= 1:
            raise ValueError("target_weight must be between 0 and 1")
        return self


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"


class Order(BaseModel):
    order_id: str
    signal: SignalIntent
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: str | None = None


class Fill(BaseModel):
    order_id: str
    symbol: str
    side: Side
    filled_at: datetime
    quantity: int
    price: float
    commission: float
    tax: float
    transfer_fee: float
    slippage: float
```

```python
# src/astock/backtest/models.py
from datetime import date
from enum import StrEnum
from pydantic import BaseModel, Field
from astock.domain.market import Adjustment, Timeframe


class BacktestMode(StrEnum):
    SIMPLE = "simple"
    REALISTIC = "realistic"


class FeeSchedule(BaseModel):
    effective_from: date
    commission_rate: float = Field(ge=0)
    minimum_commission: float = Field(ge=0)
    sell_stamp_tax_rate: float = Field(ge=0)
    transfer_fee_rate: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)


class BacktestRequest(BaseModel):
    strategy_id: str
    symbols: list[str]
    timeframe: Timeframe
    start: date
    end: date
    initial_cash: float = Field(gt=0)
    mode: BacktestMode
    adjustment: Adjustment = Adjustment.QFQ
    fees: FeeSchedule
    benchmark: str = "000300.SH"
    max_positions: int = Field(default=10, gt=0)
    max_weight_per_symbol: float = Field(default=1.0, gt=0, le=1)
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/domain/test_trading.py -v`
Expected: PASS.

```bash
git add src/astock/domain/trading.py src/astock/backtest/models.py tests/domain/test_trading.py
git commit -m "feat: define trading and backtest models"
```

### Task 2: Implement deterministic indicators

**Files:**
- Create: `src/astock/indicators/__init__.py`
- Create: `src/astock/indicators/core.py`
- Test: `tests/indicators/test_core.py`

- [ ] **Step 1: Write golden-value tests**

```python
import pandas as pd
from astock.indicators.core import add_indicators


def test_indicators_have_expected_columns_and_warmup() -> None:
    frame = pd.DataFrame({"close": range(1, 61), "high": range(2, 62),
                          "low": range(0, 60), "volume_shares": [100] * 60})
    result = add_indicators(frame, ma_periods=(5, 20))
    assert result.loc[3, "ma_5"] != result.loc[3, "ma_5"]  # NaN warm-up
    assert result.loc[4, "ma_5"] == 3
    assert {"macd_diff", "macd_dea", "macd_hist", "kdj_k", "kdj_d", "kdj_j",
            "rsi_14", "boll_mid", "boll_upper", "boll_lower", "volume_ma_5"} <= set(result)
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/indicators/test_core.py -v`
Expected: FAIL because the indicator module is missing.

- [ ] **Step 3: Implement formulas with Pandas only**

```python
# src/astock/indicators/core.py
import pandas as pd


def add_indicators(frame: pd.DataFrame, ma_periods: tuple[int, ...] = (5, 10, 20, 60)) -> pd.DataFrame:
    out = frame.copy()
    for period in ma_periods:
        out[f"ma_{period}"] = out["close"].rolling(period, min_periods=period).mean()
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd_diff"] = ema12 - ema26
    out["macd_dea"] = out["macd_diff"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = 2 * (out["macd_diff"] - out["macd_dea"])
    low9 = out["low"].rolling(9, min_periods=9).min()
    high9 = out["high"].rolling(9, min_periods=9).max()
    rsv = (out["close"] - low9) / (high9 - low9).replace(0, pd.NA) * 100
    out["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    out["kdj_d"] = out["kdj_k"].ewm(alpha=1 / 3, adjust=False).mean()
    out["kdj_j"] = 3 * out["kdj_k"] - 2 * out["kdj_d"]
    delta = out["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, pd.NA))
    out["boll_mid"] = out["close"].rolling(20, min_periods=20).mean()
    std = out["close"].rolling(20, min_periods=20).std(ddof=0)
    out["boll_upper"] = out["boll_mid"] + 2 * std
    out["boll_lower"] = out["boll_mid"] - 2 * std
    out["volume_ma_5"] = out["volume_shares"].rolling(5, min_periods=5).mean()
    return out
```

- [ ] **Step 4: Compare a fixed CSV against independent expected values**

Add `tests/fixtures/indicator_expected.csv` containing 60 input rows and the last five expected indicator rows calculated independently. Assert absolute error `< 1e-8` for every non-null value.

Run: `python -m pytest tests/indicators/test_core.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/indicators tests/indicators tests/fixtures/indicator_expected.csv
git commit -m "feat: calculate supported technical indicators"
```

### Task 3: Build the strategy context and configured rule evaluator

**Files:**
- Create: `src/astock/strategy/__init__.py`
- Create: `src/astock/strategy/base.py`
- Create: `src/astock/strategy/rules.py`
- Create: `src/astock/strategy/configured.py`
- Test: `tests/strategy/test_rules.py`

- [ ] **Step 1: Test cross semantics and one-level groups**

```python
from astock.strategy.rules import Condition, ConditionGroup, Operator, evaluate_group


def test_and_group_can_contain_or_group_without_deeper_nesting() -> None:
    current = {"ma_5": 11, "ma_20": 10, "macd_diff": 0.2, "rsi_14": 50}
    previous = {"ma_5": 9, "ma_20": 10, "macd_diff": -0.1, "rsi_14": 35}
    rule = ConditionGroup(
        operator=Operator.AND,
        items=[
            Condition(left="ma_5", comparator="cross_above", right="ma_20"),
            ConditionGroup(operator=Operator.OR, items=[
                Condition(left="macd_diff", comparator="cross_above", right=0),
                Condition(left="rsi_14", comparator="lt", right=30),
            ]),
        ],
    )
    assert evaluate_group(rule, current, previous) is True
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/strategy/test_rules.py -v`
Expected: FAIL because the rules module is missing.

- [ ] **Step 3: Implement typed rules and bounded nesting**

```python
# src/astock/strategy/rules.py
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, model_validator


class Operator(StrEnum):
    AND = "and"
    OR = "or"


class Condition(BaseModel):
    left: str
    comparator: Literal["gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below"]
    right: str | float


class ConditionGroup(BaseModel):
    operator: Operator
    items: list[Condition | "ConditionGroup"]

    @model_validator(mode="after")
    def reject_deep_nesting(self) -> "ConditionGroup":
        for item in self.items:
            if isinstance(item, ConditionGroup) and any(isinstance(x, ConditionGroup) for x in item.items):
                raise ValueError("only one nested condition-group level is allowed")
        return self


def _value(spec: str | float, row: dict[str, float]) -> float:
    return float(row[spec]) if isinstance(spec, str) else float(spec)


def evaluate_condition(condition: Condition, current: dict, previous: dict) -> bool:
    left, right = _value(condition.left, current), _value(condition.right, current)
    if condition.comparator == "cross_above":
        return _value(condition.left, previous) <= _value(condition.right, previous) and left > right
    if condition.comparator == "cross_below":
        return _value(condition.left, previous) >= _value(condition.right, previous) and left < right
    return {"gt": left > right, "gte": left >= right, "lt": left < right,
            "lte": left <= right, "eq": left == right}[condition.comparator]


def evaluate_group(group: ConditionGroup, current: dict, previous: dict) -> bool:
    values = [evaluate_group(item, current, previous) if isinstance(item, ConditionGroup)
              else evaluate_condition(item, current, previous) for item in group.items]
    return all(values) if group.operator == Operator.AND else any(values)
```

- [ ] **Step 4: Add `StrategyContext` and `ConfiguredStrategy`**

```python
# src/astock/strategy/base.py
from dataclasses import dataclass
from typing import Protocol
import pandas as pd
from astock.domain.market import Bar
from astock.domain.trading import SignalIntent


@dataclass(frozen=True)
class StrategyContext:
    bar: Bar
    history: pd.DataFrame
    cash: float
    position_quantity: int


class Strategy(Protocol):
    def on_bar(self, context: StrategyContext) -> list[SignalIntent]: ...
```

`ConfiguredStrategy.on_bar()` adds indicators to `context.history`, returns no signal while required columns are null, evaluates separate buy/sell groups against only the last two completed rows, and emits an intent with configured quantity or target weight.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/strategy/test_rules.py -v`
Expected: PASS, including validation that a third group level raises an error.

```bash
git add src/astock/strategy tests/strategy
git commit -m "feat: evaluate configured trading strategies"
```

### Task 4: Load and isolate Python strategies

**Files:**
- Create: `src/astock/strategy/python_loader.py`
- Create: `examples/strategies/ma_cross.py`
- Test: `tests/strategy/test_python_loader.py`

- [ ] **Step 1: Write contract and error-isolation tests**

```python
from pathlib import Path
import pytest
from astock.strategy.python_loader import PythonStrategyError, load_strategy


def test_loader_requires_create_strategy(tmp_path: Path) -> None:
    path = tmp_path / "bad.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(PythonStrategyError, match="create_strategy"):
        load_strategy(path)
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/strategy/test_python_loader.py -v`
Expected: FAIL because the loader is missing.

- [ ] **Step 3: Implement explicit module loading and guarded calls**

```python
# src/astock/strategy/python_loader.py
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from astock.strategy.base import Strategy, StrategyContext


class PythonStrategyError(RuntimeError):
    pass


def load_strategy(path: Path) -> Strategy:
    spec = spec_from_file_location(f"astock_user_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise PythonStrategyError(f"cannot load {path}")
    module = module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        factory = getattr(module, "create_strategy")
        strategy = factory()
    except Exception as exc:
        raise PythonStrategyError(f"failed to create strategy: {exc}") from exc
    if not callable(getattr(strategy, "on_bar", None)):
        raise PythonStrategyError("strategy must define on_bar(context)")
    return strategy


def call_strategy(strategy: Strategy, context: StrategyContext):
    try:
        return strategy.on_bar(context)
    except Exception as exc:
        raise PythonStrategyError(f"strategy execution failed: {exc}") from exc
```

- [ ] **Step 4: Add a documented MA-cross example and tests**

The example must import only the public `StrategyContext`, `SignalIntent`, `Side`, and `Timeframe` APIs, inspect completed history, and export `create_strategy()`. Test a thrown user exception is converted to `PythonStrategyError` without terminating the test process.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/strategy/test_python_loader.py -v`
Expected: PASS.

```bash
git add src/astock/strategy/python_loader.py examples/strategies tests/strategy/test_python_loader.py
git commit -m "feat: support Python strategy modules"
```

### Task 5: Implement account allocation and simple-mode broker

**Files:**
- Create: `src/astock/backtest/portfolio.py`
- Create: `src/astock/backtest/broker.py`
- Test: `tests/backtest/test_simple_broker.py`

- [ ] **Step 1: Test next-open fill, target weight and fees**

```python
def test_simple_order_fills_at_next_open_with_slippage() -> None:
    broker = Broker(mode=BacktestMode.SIMPLE,
                    fees=FeeSchedule(commission_rate=0.001, minimum_commission=0,
                                     sell_stamp_tax_rate=0, transfer_fee_rate=0,
                                     slippage_bps=10))
    result = broker.execute(BUY_100, NEXT_BAR_OPEN_10, EMPTY_ACCOUNT)
    assert result.fill.price == 10.01
    assert result.fill.commission == 1.001
    assert result.account.position("600519.SH").quantity == 100
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/backtest/test_simple_broker.py -v`
Expected: FAIL because broker and portfolio modules are missing.

- [ ] **Step 3: Implement pure portfolio transitions**

`Portfolio.apply_fill(fill)` returns a new portfolio: buys reduce cash and increase weighted cost; sells increase cash, reduce quantity, and update realized P&L. `Allocator.quantity_for_target()` converts target weight to affordable shares, applies `max_positions` and per-symbol weight, but does not round to lots in simple mode.

- [ ] **Step 4: Implement the simple broker**

```python
def execution_price(side: Side, open_price: float, slippage_bps: float) -> float:
    direction = 1 if side == Side.BUY else -1
    return open_price * (1 + direction * slippage_bps / 10_000)


def calculate_fees(side: Side, value: float, schedule: FeeSchedule) -> tuple[float, float, float]:
    commission = max(value * schedule.commission_rate, schedule.minimum_commission)
    tax = value * schedule.sell_stamp_tax_rate if side == Side.SELL else 0.0
    transfer = value * schedule.transfer_fee_rate
    return commission, tax, transfer
```

`Broker.execute()` must reject insufficient cash or holdings, otherwise return an immutable execution result containing the fill and updated portfolio.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/backtest/test_simple_broker.py -v`
Expected: PASS.

```bash
git add src/astock/backtest/portfolio.py src/astock/backtest/broker.py tests/backtest/test_simple_broker.py
git commit -m "feat: add simple backtest broker and portfolio"
```

### Task 6: Add realistic A-share execution rules

**Files:**
- Modify: `src/astock/backtest/broker.py`
- Create: `src/astock/backtest/corporate_actions.py`
- Test: `tests/backtest/test_realistic_broker.py`
- Test: `tests/backtest/test_corporate_actions.py`

- [ ] **Step 1: Write failing T+1, lot, suspension and price-limit tests**

```python
def test_realistic_buy_rounds_down_to_board_lot() -> None:
    result = realistic_broker.execute(BUY_150, OPEN_BAR, EMPTY_ACCOUNT)
    assert result.fill.quantity == 100


def test_same_day_position_cannot_be_sold() -> None:
    account = account_with_position(quantity=100, acquired_on=TRADE_DATE)
    result = realistic_broker.execute(SELL_100, OPEN_BAR, account)
    assert result.order.reject_reason == "t_plus_one"


def test_suspended_bar_rejects_order() -> None:
    result = realistic_broker.execute(BUY_100, SUSPENDED_BAR, EMPTY_ACCOUNT)
    assert result.order.reject_reason == "suspended"
```

- [ ] **Step 2: Verify the new tests fail**

Run: `python -m pytest tests/backtest/test_realistic_broker.py -v`
Expected: FAIL on unimplemented realistic rules.

- [ ] **Step 3: Implement a composable rejection sequence**

Apply checks in this exact order: invalid/absent bar → suspension → T+1 sell availability → 100-share buy lot → daily limit tradability → holdings/cash. Daily limits come from point-in-time security metadata (board and ST status), not symbol-name guesses. A limit-up buy or limit-down sell is rejected only when the bar has no executable range away from the limit; record `limit_up_no_liquidity` or `limit_down_no_liquidity`.

- [ ] **Step 4: Implement corporate actions**

```python
@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    ex_date: date
    cash_per_share: float = 0.0
    share_ratio: float = 0.0


def apply_action(portfolio: Portfolio, action: CorporateAction) -> Portfolio:
    position = portfolio.position(action.symbol)
    cash_delta = position.quantity * action.cash_per_share
    new_quantity = int(position.quantity * (1 + action.share_ratio))
    return portfolio.replace_position(action.symbol, new_quantity, cash_delta)
```

Test cash dividend, bonus shares and unchanged total economic value within rounding tolerance.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/backtest/test_realistic_broker.py tests/backtest/test_corporate_actions.py -v`
Expected: PASS.

```bash
git add src/astock/backtest tests/backtest/test_realistic_broker.py tests/backtest/test_corporate_actions.py
git commit -m "feat: enforce realistic A-share execution rules"
```

### Task 7: Build the no-look-ahead event loop

**Files:**
- Create: `src/astock/backtest/engine.py`
- Test: `tests/backtest/test_engine.py`

- [ ] **Step 1: Write a regression test proving next-bar execution**

```python
def test_signal_on_close_fills_only_at_next_bar_open() -> None:
    bars = fixture_bars(closes=[9, 11, 12], opens=[8, 10, 20])
    result = engine_for(CrossStrategy()).run(request_for(bars))
    assert result.fills[0].signal_at == bars[1].timestamp
    assert result.fills[0].filled_at == bars[2].timestamp
    assert result.fills[0].price == 20
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/backtest/test_engine.py -v`
Expected: FAIL because the engine is missing.

- [ ] **Step 3: Implement the ordered event loop**

For each global timestamp: (1) apply corporate actions; (2) execute intentions queued by prior bars against current raw open prices; (3) update marked-to-market portfolio; (4) expose history ending at the current completed bar; (5) call the strategy; (6) queue returned intentions for the next bar of that symbol; (7) append equity and diagnostic records. Never expose a later row through `StrategyContext.history`.

- [ ] **Step 4: Cover disjoint symbol calendars and failures**

Add tests showing a suspended/missing symbol does not block other symbols, pending orders wait only for that symbol's next valid bar, and a Python strategy exception marks the task failed with symbol/timestamp/traceback.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/backtest/test_engine.py -v`
Expected: PASS.

```bash
git add src/astock/backtest/engine.py tests/backtest/test_engine.py
git commit -m "feat: run deterministic event-driven backtests"
```

### Task 8: Add point-in-time universes and portfolio allocation

**Files:**
- Create: `src/astock/backtest/universe.py`
- Modify: `src/astock/backtest/portfolio.py`
- Test: `tests/backtest/test_universe.py`
- Test: `tests/backtest/test_allocation.py`

- [ ] **Step 1: Test delisted/newly listed exclusion and allocation caps**

```python
def test_universe_uses_membership_on_backtest_date() -> None:
    assert universe.members(date(2020, 1, 2)) == {"000001.SZ", "600519.SH"}
    assert "301001.SZ" not in universe.members(date(2020, 1, 2))


def test_equal_weight_respects_max_positions() -> None:
    intents = allocator.equal_weight(["A", "B", "C"], equity=300_000,
                                     max_positions=2, max_weight=0.6)
    assert [x.symbol for x in intents] == ["A", "B"]
    assert all(x.target_weight == 0.5 for x in intents)
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/backtest/test_universe.py tests/backtest/test_allocation.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement membership intervals**

`UniverseRepository.members(on_date)` queries symbol listing/delisting and historical universe membership intervals. Add the required `universe_membership(symbol, universe, valid_from, valid_to)` table in `src/astock/storage/schema.sql`; never substitute the current symbol list for historical dates.

- [ ] **Step 4: Implement fixed cash, percentage and equal-weight allocation**

Sort same-timestamp candidates by `(priority, symbol)` for repeatability. Apply maximum positions, available cash and per-symbol cap before emitting quantities/weights. Add tests for insufficient cash and deterministic ordering.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/backtest/test_universe.py tests/backtest/test_allocation.py -v`
Expected: PASS.

```bash
git add src/astock/backtest src/astock/storage/schema.sql tests/backtest
git commit -m "feat: add point-in-time portfolio universes"
```

### Task 9: Calculate metrics and persist reproducible reports

**Files:**
- Create: `src/astock/backtest/metrics.py`
- Create: `src/astock/backtest/report.py`
- Modify: `src/astock/storage/schema.sql`
- Test: `tests/backtest/test_metrics.py`
- Test: `tests/backtest/test_report.py`

- [ ] **Step 1: Write metric and persistence tests**

```python
def test_metrics_from_fixed_equity_curve() -> None:
    metrics = calculate_metrics(EQUITY_CURVE, BENCHMARK_CURVE, TRADES)
    assert metrics.total_return == pytest.approx(0.10)
    assert metrics.max_drawdown == pytest.approx(-0.10)
    assert metrics.trade_count == 2


def test_report_round_trip_keeps_request_and_fee_schedule(tmp_path) -> None:
    report_id = ReportStore(tmp_path, database).save(FIXED_RESULT)
    loaded = ReportStore(tmp_path, database).load(report_id)
    assert loaded.request == FIXED_RESULT.request
    assert loaded.fills == FIXED_RESULT.fills
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/backtest/test_metrics.py tests/backtest/test_report.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement documented metric conventions**

Daily returns use the last portfolio value per trading day; annualization uses 252; risk-free rate defaults to zero and is stored in the result. Calculate total/annualized/benchmark/excess return, max drawdown, Sharpe, volatility, win rate, profit-loss ratio, trade count and turnover. Empty-trade results return null win/profit-loss ratios rather than divide by zero.

- [ ] **Step 4: Persist summaries and details**

Add `backtest_runs` to DuckDB with status, serialized request, strategy content hash, data coverage/hash, code version, timestamps, metrics and error. Store equity, drawdown, positions, orders and fills as Parquet under `data/backtests/<run_id>/`. Write to a temporary run directory and atomically rename only after all files succeed.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/backtest/test_metrics.py tests/backtest/test_report.py -v`
Expected: PASS.

```bash
git add src/astock/backtest src/astock/storage/schema.sql tests/backtest
git commit -m "feat: persist reproducible backtest reports"
```

### Task 10: Add the backtest service and fixed regression fixture

**Files:**
- Create: `src/astock/backtest/service.py`
- Modify: `src/astock/cli.py`
- Create: `tests/fixtures/backtest/golden_bars.csv`
- Create: `tests/fixtures/backtest/golden_result.json`
- Test: `tests/backtest/test_regression.py`

- [ ] **Step 1: Write the end-to-end regression test**

```python
def test_golden_backtest_is_repeatable(backtest_service, golden_request) -> None:
    first = backtest_service.run_now(golden_request)
    second = backtest_service.run_now(golden_request)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.summary.model_dump(mode="json") == load_golden_result()
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/backtest/test_regression.py -v`
Expected: FAIL because orchestration is missing.

- [ ] **Step 3: Implement orchestration**

`BacktestService.run_now()` validates dates/symbols and calls `MarketDataService.history()` for every symbol and benchmark. It always loads unadjusted bars for execution and, when the request uses QFQ/HFQ, separately loads that adjusted series for indicators; both series must align by symbol/timestamp. It also loads corporate actions and point-in-time security status for realistic mode, rejects any uncovered interval or quality issue, loads the strategy, runs the engine, and persists the report. `submit()` inserts a queued run and launches a separate `multiprocessing` worker by run ID so live monitoring cannot be blocked.

- [ ] **Step 4: Add CLI commands and golden files**

```text
astock backtest run --request examples/backtests/ma-cross.json
astock backtest show <run-id>
```

Create golden bars with a known cross, next-open fill, T+1 rejection, dividend and sell. Review `golden_result.json` manually once, then use it as the regression contract.

- [ ] **Step 5: Run full milestone verification**

Run:

```bash
python -m pytest tests/domain tests/indicators tests/strategy tests/backtest -v
ruff check .
astock backtest run --request examples/backtests/ma-cross.json
```

Expected: all tests PASS, lint is clean, and CLI prints a run ID plus report path.

- [ ] **Step 6: Commit**

```bash
git add src/astock/backtest src/astock/cli.py examples/backtests tests/fixtures/backtest tests/backtest
git commit -m "feat: expose reproducible backtest service"
```

## Milestone Verification

Run:

```bash
python -m pytest --cov=astock.strategy --cov=astock.backtest --cov-report=term-missing
ruff check .
astock backtest run --request examples/backtests/ma-cross.json
```

Expected:

- signals are calculated only from completed current/past bars and fill at the next valid open;
- simple and realistic modes produce their reviewed golden results;
- T+1, lots, suspension, price limits, fees and corporate actions have focused tests;
- single-symbol and portfolio runs are deterministic;
- full requests, strategy/data hashes, orders, fills, reasons and metrics are recoverable from the saved report.
