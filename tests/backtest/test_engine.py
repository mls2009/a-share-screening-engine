from datetime import date, datetime
from zoneinfo import ZoneInfo

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
    assert result.trades[0].timestamp.minute == 40


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
