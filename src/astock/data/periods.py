from datetime import date, timedelta

import pandas as pd

from astock.domain.market import Timeframe


def period_end(day: date, timeframe: Timeframe) -> date:
    rule = "W-FRI" if timeframe == Timeframe.WEEK else "M"
    return pd.Period(day, freq=rule).end_time.date()


def final_session(
    day: date, timeframe: Timeframe, calendar: dict[date, bool] | None = None,
) -> date:
    """Use known closures; absent calendar entries fall back to weekdays."""
    calendar = calendar or {}
    last = period_end(day, timeframe)
    while not calendar.get(last, last.weekday() < 5):
        last -= timedelta(days=1)
    return last
