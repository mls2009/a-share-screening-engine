from datetime import date

import pytest
from pydantic import ValidationError

from astock.backtest.models import BacktestRequest

CONDITION = {
    "kind": "condition",
    "metric": "return_1",
    "timeframe": "1d",
    "operator": "gt",
    "right": {"kind": "constant", "value": 5, "unit": "percent"},
}


def test_backtest_request_rejects_reverse_dates_and_empty_symbols() -> None:
    with pytest.raises(ValidationError):
        BacktestRequest(
            symbols=[],
            timeframe="1d",
            start=date(2026, 8, 20),
            end=date(2026, 1, 1),
            entry_tree=CONDITION,
            exit_tree=CONDITION,
            initial_cash=100_000,
        )


def test_backtest_request_rejects_condition_from_a_different_timeframe() -> None:
    with pytest.raises(ValidationError, match="condition timeframe must match backtest timeframe"):
        BacktestRequest(
            symbols=["600001.SH"],
            timeframe="5m",
            start=date(2026, 8, 19),
            end=date(2026, 8, 20),
            entry_tree=CONDITION,
            exit_tree=CONDITION,
            initial_cash=100_000,
        )


def test_backtest_request_rejects_unknown_metrics() -> None:
    unknown = {**CONDITION, "metric": "future_magic"}

    with pytest.raises(ValidationError, match="invalid backtest condition"):
        BacktestRequest(
            symbols=["600001.SH"],
            timeframe="1d",
            start=date(2026, 8, 19),
            end=date(2026, 8, 20),
            entry_tree=unknown,
            exit_tree=CONDITION,
            initial_cash=100_000,
        )


@pytest.mark.parametrize("operand", ["left", "right"])
def test_backtest_rejects_metrics_that_engine_does_not_compute(operand) -> None:
    tree = {
        **CONDITION, "metric": "pattern_strength",
        "right": {"kind": "constant", "value": 1, "unit": "score"},
    } if operand == "left" else {
        **CONDITION, "metric": "rsi_14",
        "right": {"kind": "metric", "metric": "pattern_strength", "timeframe": "1d"},
    }
    with pytest.raises(ValidationError, match="unsupported backtest metric"):
        BacktestRequest(
            symbols=["600001.SH"], timeframe="1d",
            start=date(2026, 8, 19), end=date(2026, 8, 20),
            entry_tree=tree, exit_tree=CONDITION, initial_cash=100_000,
        )
