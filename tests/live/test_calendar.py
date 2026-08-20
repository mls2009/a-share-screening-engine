from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock.live.calendar import TradingCalendar

TZ = ZoneInfo("Asia/Shanghai")


def test_calendar_excludes_lunch_and_non_trading_dates() -> None:
    calendar = TradingCalendar({date(2026, 8, 20)})

    assert calendar.is_live(datetime(2026, 8, 20, 9, 30, tzinfo=TZ))
    assert calendar.is_live(datetime(2026, 8, 20, 11, 30, tzinfo=TZ))
    assert not calendar.is_live(datetime(2026, 8, 20, 11, 31, tzinfo=TZ))
    assert calendar.is_live(datetime(2026, 8, 20, 13, 0, tzinfo=TZ))
    assert not calendar.is_live(datetime(2026, 8, 22, 10, 0, tzinfo=TZ))
