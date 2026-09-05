from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from astock.backtest.engine import BacktestEngine, _periods_per_year
from astock.backtest.models import BacktestMode, BacktestRequest, ExecutionStatus, FeeSchedule
from astock.domain.market import Adjustment, Bar, Timeframe

TZ = ZoneInfo("Asia/Shanghai")


def _bars() -> list[Bar]:
    prices = [10, 11, 12, 11, 10, 9]
    return [
        Bar(
            symbol="600001.SH",
            timestamp=datetime(2026, 8, 10 + index, 15, tzinfo=TZ),
            timeframe=Timeframe.DAY,
            open=price,
            high=price + 0.2,
            low=price - 0.2,
            close=price,
            volume_shares=1_000_000,
            amount_cny=price * 1_000_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for index, price in enumerate(prices)
    ]


def _condition(operator: str, value: float) -> dict:
    return {
        "kind": "condition",
        "metric": "return_1",
        "timeframe": "1d",
        "operator": operator,
        "right": {"kind": "constant", "value": value, "unit": "percent"},
    }


def test_signals_at_close_fill_at_next_open_without_future_data() -> None:
    request = BacktestRequest(
        symbols=["600001.SH"],
        timeframe="1d",
        start=date(2026, 8, 10),
        end=date(2026, 8, 15),
        entry_tree=_condition("gt", 5),
        exit_tree=_condition("lt", -5),
        initial_cash=100_000,
        position_size=1,
        fees=FeeSchedule.zero(),
    )

    result = BacktestEngine().run(request, {"600001.SH": _bars()})

    assert [(trade.side, trade.timestamp.date(), trade.price) for trade in result.trades] == [
        ("buy", date(2026, 8, 12), 12),
        ("sell", date(2026, 8, 14), 10),
    ]
    assert result.metrics.trade_count == 1
    assert result.metrics.total_return < 0
    assert result.equity_curve[-1].equity == 83_334


def test_indicator_warmup_values_do_not_trigger_orders() -> None:
    condition = {
        "kind": "condition",
        "metric": "ma_20",
        "timeframe": "1d",
        "operator": "ne",
        "right": {"kind": "constant", "value": 0, "unit": "price"},
    }
    request = BacktestRequest(
        symbols=["600001.SH"],
        timeframe="1d",
        start=date(2026, 8, 10),
        end=date(2026, 8, 15),
        entry_tree=condition,
        exit_tree=condition,
        initial_cash=100_000,
        fees=FeeSchedule.zero(),
    )

    result = BacktestEngine().run(request, {"600001.SH": _bars()})

    assert result.trades == []


def test_pre_start_bars_warm_up_indicators_but_cannot_place_orders() -> None:
    bars = [
        Bar(
            symbol="600001.SH",
            timestamp=datetime(2026, 7, 1 + index, 15, tzinfo=TZ),
            timeframe=Timeframe.DAY,
            open=10 + index / 10,
            high=10.3 + index / 10,
            low=9.7 + index / 10,
            close=10 + index / 10,
            volume_shares=1_000_000,
            amount_cny=10_000_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for index in range(30)
    ]
    entry = {
        "kind": "condition",
        "metric": "ma_20",
        "timeframe": "1d",
        "operator": "gt",
        "right": {"kind": "constant", "value": 0, "unit": "price"},
    }
    exit_tree = {
        "kind": "condition",
        "metric": "close",
        "timeframe": "1d",
        "operator": "lt",
        "right": {"kind": "constant", "value": 0, "unit": "price"},
    }
    request = BacktestRequest(
        symbols=["600001.SH"],
        timeframe="1d",
        start=date(2026, 7, 25),
        end=date(2026, 7, 30),
        entry_tree=entry,
        exit_tree=exit_tree,
        initial_cash=100_000,
        fees=FeeSchedule.zero(),
    )

    result = BacktestEngine().run(request, {"600001.SH": bars})

    assert result.trades[0].signal_at.date() == date(2026, 7, 25)
    assert result.trades[0].timestamp.date() == date(2026, 7, 26)
    assert all(point.timestamp.date() >= request.start for point in result.equity_curve)


def test_risk_scaling_matches_each_supported_timeframe() -> None:
    assert _periods_per_year(Timeframe.MIN_5) == 252 * 48
    assert _periods_per_year(Timeframe.MIN_15) == 252 * 16
    assert _periods_per_year(Timeframe.MIN_30) == 252 * 8
    assert _periods_per_year(Timeframe.MIN_60) == 252 * 4
    assert _periods_per_year(Timeframe.DAY) == 252
    assert _periods_per_year(Timeframe.WEEK) == 52
    assert _periods_per_year(Timeframe.MONTH) == 12


def test_five_minute_conditions_produce_orders_on_five_minute_history() -> None:
    prices = [10, 11, 12, 11]
    bars = [
        Bar(
            symbol="600001.SH",
            timestamp=datetime(2026, 8, 20, 9, 30 + index * 5, tzinfo=TZ),
            timeframe=Timeframe.MIN_5,
            open=price,
            high=price + 0.2,
            low=price - 0.2,
            close=price,
            volume_shares=100_000,
            amount_cny=price * 100_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for index, price in enumerate(prices)
    ]
    entry = {**_condition("gt", 5), "timeframe": "5m"}
    exit_tree = {**_condition("lt", -5), "timeframe": "5m"}
    request = BacktestRequest(
        symbols=["600001.SH"],
        timeframe="5m",
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
        entry_tree=entry,
        exit_tree=exit_tree,
        initial_cash=100_000,
        fees=FeeSchedule.zero(),
    )

    result = BacktestEngine().run(request, {"600001.SH": bars})

    assert result.trades
    assert result.trades[0].timestamp.minute == 35


def test_realistic_mode_rejects_suspended_and_one_price_limit_bars() -> None:
    request = BacktestRequest(
        symbols=["600001.SH"],
        timeframe="1d",
        start=date(2026, 8, 10),
        end=date(2026, 8, 15),
        entry_tree=_condition("gt", 5),
        exit_tree=_condition("lt", -5),
        initial_cash=100_000,
        mode=BacktestMode.REALISTIC,
        fees=FeeSchedule.zero(),
    )
    suspended = {
        ("600001.SH", date(2026, 8, 12)): ExecutionStatus(is_suspended=True)
    }
    limit_up = {
        ("600001.SH", date(2026, 8, 12)): ExecutionStatus(limit_up=12, limit_down=8)
    }
    bars = _bars()
    bars[2] = bars[2].model_copy(update={"open": 12, "high": 12, "low": 12})

    suspended_result = BacktestEngine().run(request, {"600001.SH": _bars()}, suspended)
    limit_result = BacktestEngine().run(request, {"600001.SH": bars}, limit_up)

    assert all(trade.timestamp.date() != date(2026, 8, 12) for trade in suspended_result.trades)
    assert any("suspended" in reason for reason in suspended_result.rejected_orders)
    assert all(trade.timestamp.date() != date(2026, 8, 12) for trade in limit_result.trades)
    assert any("limit_up_no_liquidity" in reason for reason in limit_result.rejected_orders)


def test_simultaneous_buys_use_one_portfolio_value_at_current_open() -> None:
    symbols = ["600001.SH", "600002.SH"]
    market = {symbol: [bar.model_copy(update={"symbol": symbol}) for bar in _bars()]
              for symbol in symbols}
    request = BacktestRequest(
        symbols=symbols, timeframe="1d", start=date(2026, 8, 10), end=date(2026, 8, 15),
        entry_tree=_condition("gt", 5), exit_tree=_condition("lt", -100),
        initial_cash=100_000, position_size=0.5, fees=FeeSchedule.zero(),
    )
    result = BacktestEngine().run(request, market)
    assert [trade.quantity for trade in result.trades] == [4166, 4166]


def test_profitable_intraday_backtest_does_not_overflow_annualization() -> None:
    bars = [bar.model_copy(update={
        "timeframe": Timeframe.MIN_5,
        "timestamp": datetime(2026, 8, 20, 10, index * 5, tzinfo=TZ),
    }) for index, bar in enumerate(_bars()[:3])]
    request = BacktestRequest(
        symbols=["600001.SH"], timeframe="5m", start=date(2026, 8, 20), end=date(2026, 8, 20),
        entry_tree={**_condition("gt", -100), "timeframe": "5m", "metric": "close",
                    "right": {"kind": "constant", "value": 0, "unit": "price"}},
        exit_tree={**_condition("lt", -100), "timeframe": "5m"},
        initial_cash=100_000, position_size=1, fees=FeeSchedule.zero(),
    )
    result = BacktestEngine().run(request, {"600001.SH": bars})
    assert result.metrics.total_return == pytest.approx(9.09)
    assert result.metrics.annualized_return is None
    assert '"annualized_return":null' in result.model_dump_json()


@pytest.mark.parametrize("symbols", [["600002.SH", "600001.SH"], ["600001.SH", "600002.SH"]])
def test_rebalance_executes_sells_before_buys(symbols) -> None:
    market = {}
    for symbol, prices in [("600001.SH", [10, 12, 12]), ("600002.SH", [20, 10, 10])]:
        market[symbol] = [bar.model_copy(update={
            "symbol": symbol, "open": price, "high": price, "low": price, "close": price,
        }) for bar, price in zip(_bars(), prices)]
    request = BacktestRequest(
        symbols=symbols, timeframe="1d", start=date(2026, 8, 10), end=date(2026, 8, 12),
        entry_tree={**_condition("lt", 11), "metric": "close",
                    "right": {"kind": "constant", "value": 11, "unit": "price"}},
        exit_tree={**_condition("gt", 11), "metric": "close",
                   "right": {"kind": "constant", "value": 11, "unit": "price"}},
        initial_cash=100_000, position_size=1, fees=FeeSchedule.zero(),
    )
    result = BacktestEngine().run(request, market)
    assert [(trade.side, trade.symbol) for trade in result.trades] == [
        ("buy", "600001.SH"), ("sell", "600001.SH"), ("buy", "600002.SH"),
    ]
    assert result.rejected_orders == []


def test_week_signal_executes_next_daily_open() -> None:
    daily = [bar.model_copy(update={"timestamp": datetime(2026, 8, day, 15, tzinfo=TZ)})
             for bar, day in zip(_bars(), [7, 10, 11, 12, 13, 14])]
    weekly = [daily[0].model_copy(update={"timeframe": Timeframe.WEEK})]
    condition = {"kind": "condition", "metric": "close", "timeframe": "1w",
                 "operator": "gt", "right": {"kind": "constant", "value": 0, "unit": "price"}}
    request = BacktestRequest(symbols=["600001.SH"], timeframe="1w", start=date(2026, 8, 7),
        end=date(2026, 8, 14), entry_tree=condition, exit_tree=condition,
        initial_cash=100_000, fees=FeeSchedule.zero())
    result = BacktestEngine().run(request, {"600001.SH": weekly},
                                 execution_market={"600001.SH": daily})
    assert result.trades[0].timestamp == datetime(2026, 8, 10, 9, 30, tzinfo=TZ)
    assert result.trades[0].signal_at == datetime(2026, 8, 7, 15, tzinfo=TZ)
    assert result.trades[0].price == 11


def test_open_limit_cannot_use_later_intraday_low() -> None:
    request = BacktestRequest(symbols=["600001.SH"], timeframe="1d", start=date(2026, 8, 10),
        end=date(2026, 8, 15), entry_tree=_condition("gt", 5), exit_tree=_condition("lt", -5),
        initial_cash=100_000, mode="realistic", fees=FeeSchedule.zero())
    result = BacktestEngine().run(request, {"600001.SH": _bars()}, {
        ("600001.SH", date(2026, 8, 12)): ExecutionStatus(limit_up=12)})
    assert not any(trade.timestamp.date() == date(2026, 8, 12) for trade in result.trades)


def test_t1_retry_preserves_original_exit_signal() -> None:
    times = [datetime(2026, 8, 10, 9, minute, tzinfo=TZ) for minute in [35, 40, 45, 50]]
    times += [datetime(2026, 8, 11, 9, 35, tzinfo=TZ)]
    bars = [bar.model_copy(update={"timestamp": timestamp, "timeframe": Timeframe.MIN_5})
            for bar, timestamp in zip(_bars(), times)]
    condition = {"kind": "condition", "metric": "close", "timeframe": "5m",
                 "operator": "gt", "right": {"kind": "constant", "value": 0, "unit": "price"}}
    request = BacktestRequest(symbols=["600001.SH"], timeframe="5m", start=date(2026, 8, 10),
        end=date(2026, 8, 11), entry_tree=condition, exit_tree=condition,
        initial_cash=100_000, mode="realistic", fees=FeeSchedule.zero())
    result = BacktestEngine().run(request, {"600001.SH": bars})
    assert [trade.side for trade in result.trades] == ["buy", "sell"]
    assert result.trades[-1].timestamp == datetime(2026, 8, 11, 9, 30, tzinfo=TZ)
    assert result.trades[-1].signal_at == times[1]


@pytest.mark.parametrize("reason,volume,limit,slippage", [
    ("zero_volume", 0, 20, 0), ("slippage_outside_price_limits", 1000, 12.01, 100),
])
def test_realistic_zero_volume_and_slippage_limits(reason, volume, limit, slippage) -> None:
    bars = _bars()
    bars[2] = bars[2].model_copy(update={"volume_shares": volume})
    request = BacktestRequest(symbols=["600001.SH"], timeframe="1d", start=date(2026, 8, 10),
        end=date(2026, 8, 15), entry_tree=_condition("gt", 5), exit_tree=_condition("lt", -5),
        initial_cash=100_000, mode="realistic",
        fees=FeeSchedule.zero().model_copy(update={"slippage_bps": slippage}))
    result = BacktestEngine().run(request, {"600001.SH": bars}, {
        ("600001.SH", date(2026, 8, 12)): ExecutionStatus(limit_up=limit)})
    assert any(reason in message for message in result.rejected_orders)
    assert result.diagnostics.status_coverage_pct == pytest.approx(100 / 6)


def test_evaluator_history_is_bounded(monkeypatch) -> None:
    from astock.backtest import engine
    original = engine.evaluate_tree
    lengths = []

    def evaluate(tree, history):
        lengths.append(len(history[Timeframe.DAY]))
        return original(tree, history)

    monkeypatch.setattr(engine, "evaluate_tree", evaluate)
    request = BacktestRequest(symbols=["600001.SH"], timeframe="1d", start=date(2026, 8, 10),
        end=date(2026, 8, 15), entry_tree=_condition("gt", 5), exit_tree=_condition("lt", -5),
        initial_cash=100_000, fees=FeeSchedule.zero())
    BacktestEngine().run(request, {"600001.SH": _bars()})
    assert max(lengths) == 1
