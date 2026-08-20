from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from astock.live.evaluator import evaluate_price
from astock.live.models import MonitorTaskCreate, PriceComparator, SignalState

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 20, 10, tzinfo=TZ)


def test_monitor_task_requires_symbols_and_positive_threshold() -> None:
    with pytest.raises(ValidationError):
        MonitorTaskCreate(
            name="无效规则",
            symbols=[],
            comparator=PriceComparator.CROSS_ABOVE,
            threshold=0,
        )


def test_crossing_triggers_once_resets_and_honors_cooldown() -> None:
    task = MonitorTaskCreate(
        name="突破 100",
        symbols=["600519.SH"],
        comparator=PriceComparator.CROSS_ABOVE,
        threshold=100,
        cooldown_seconds=30,
    )
    state = SignalState(task_id="t1", symbol="600519.SH", last_value=99)

    first = evaluate_price(task, state, 101, NOW)
    held = evaluate_price(task, first.state, 102, NOW + timedelta(seconds=5))
    reset = evaluate_price(task, held.state, 99, NOW + timedelta(seconds=10))
    cooling = evaluate_price(task, reset.state, 101, NOW + timedelta(seconds=20))
    reset_again = evaluate_price(task, cooling.state, 99, NOW + timedelta(seconds=35))
    again = evaluate_price(task, reset_again.state, 101, NOW + timedelta(seconds=40))

    assert [first.triggered, held.triggered, reset.triggered, cooling.triggered, again.triggered] == [
        True,
        False,
        False,
        False,
        True,
    ]


def test_above_rule_can_alert_on_first_fresh_quote() -> None:
    task = MonitorTaskCreate(
        name="达到 100",
        symbols=["600519.SH"],
        comparator=PriceComparator.ABOVE,
        threshold=100,
    )

    result = evaluate_price(task, SignalState(task_id="t1", symbol="600519.SH"), 101, NOW)

    assert result.triggered is True
