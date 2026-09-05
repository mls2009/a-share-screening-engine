from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from astock.data.service import MarketDataService
from astock.domain.market import Bar, Timeframe


def _bars(dates, timeframe=Timeframe.DAY):
    return [Bar(symbol="600001.SH", timestamp=datetime.fromisoformat(value).replace(
        tzinfo=ZoneInfo("Asia/Shanghai")), timeframe=timeframe,
        open=10, high=11, low=9, close=10, volume_shares=100, amount_cny=1000)
        for value in dates]


@pytest.mark.parametrize("timeframe,dates", [
    (Timeframe.WEEK, ["2026-08-17T15:00", "2026-08-20T15:00"]),
    (Timeframe.MONTH, ["2026-08-03T15:00", "2026-08-20T15:00"]),
])
def test_unfinished_calendar_period_is_not_final(timeframe, dates):
    assert not MarketDataService.derive(_bars(dates), timeframe)[-1].is_final


def test_calendar_recognizes_holiday_week_end():
    bars = _bars(["2026-09-28T15:00", "2026-09-29T15:00", "2026-09-30T15:00"])
    calendar = {date(2026, 9, 28) + timedelta(days=i): i < 3 for i in range(5)}
    assert MarketDataService.derive(bars, Timeframe.WEEK, calendar=calendar)[0].is_final


def test_nonfinal_component_cannot_make_final_week():
    bars = _bars(["2026-08-17T15:00", "2026-08-21T15:00"])
    bars[-1] = bars[-1].model_copy(update={"is_final": False})
    assert not MarketDataService.derive(bars, Timeframe.WEEK)[0].is_final


def test_incomplete_fifteen_minute_bucket_is_not_final():
    bars = _bars(["2026-08-20T09:35", "2026-08-20T09:40"], Timeframe.MIN_5)
    assert not MarketDataService.derive(bars, Timeframe.MIN_15)[0].is_final


def test_fifteen_minute_bucket_with_missing_middle_bar_is_not_final():
    bars = _bars(["2026-08-20T09:35", "2026-08-20T09:45"], Timeframe.MIN_5)
    assert not MarketDataService.derive(bars, Timeframe.MIN_15)[0].is_final


def test_complete_fifteen_minute_bucket_is_final():
    bars = _bars(["2026-08-20T09:35", "2026-08-20T09:40", "2026-08-20T09:45"], Timeframe.MIN_5)
    assert MarketDataService.derive(bars, Timeframe.MIN_15)[0].is_final
