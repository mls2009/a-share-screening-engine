from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from astock.domain.market import Bar


def limit_state(close: float, upper: float | None, lower: float | None) -> str | None:
    price = Decimal(str(close)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if upper is not None and price == Decimal(str(upper)):
        return 'up'
    if lower is not None and price == Decimal(str(lower)):
        return 'down'
    return None


def annotate_limits(bars: Iterable[Bar], raw_bars: Iterable[Bar], statuses: dict) -> list[dict]:
    raw = {bar.timestamp: bar for bar in raw_bars}
    result = []
    for bar in bars:
        row = bar.model_dump(mode='json')
        row['limit_state'] = None
        status = statuses.get(bar.timestamp.date())
        actual = raw.get(bar.timestamp)
        row['limit_data_pending'] = actual is None or status is None
        if actual and status and not status[0]:
            row['limit_state'] = limit_state(actual.close, status[1], status[2])
        result.append(row)
    return result
