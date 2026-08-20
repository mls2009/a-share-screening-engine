from datetime import datetime, timedelta

from astock.live.models import (
    MonitorTaskCreate,
    PriceComparator,
    PriceEvaluation,
    SignalState,
)


def evaluate_price(
    task: MonitorTaskCreate,
    state: SignalState,
    price: float,
    now: datetime,
) -> PriceEvaluation:
    above = task.comparator in {PriceComparator.ABOVE, PriceComparator.CROSS_ABOVE}
    active = price > task.threshold if above else price < task.threshold
    crossed = False
    if task.comparator in {PriceComparator.ABOVE, PriceComparator.BELOW}:
        crossed = active and not state.active
    elif state.last_value is not None:
        if task.comparator == PriceComparator.CROSS_ABOVE:
            crossed = state.last_value <= task.threshold < price
        else:
            crossed = state.last_value >= task.threshold > price

    cooled_down = (
        state.last_triggered_at is None
        or now >= state.last_triggered_at + timedelta(seconds=task.cooldown_seconds)
    )
    triggered = crossed and cooled_down
    next_state = state.model_copy(
        update={
            "active": active,
            "last_value": price,
            "last_triggered_at": now if triggered else state.last_triggered_at,
        }
    )
    return PriceEvaluation(triggered=triggered, state=next_state)
