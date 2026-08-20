from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SESSIONS = ((time(9, 30), time(11, 30)), (time(13), time(15)))


class TradingCalendar:
    def __init__(self, trading_dates: set[date]) -> None:
        self.trading_dates = trading_dates

    def is_live(self, now: datetime) -> bool:
        local = now.astimezone(SHANGHAI)
        return local.date() in self.trading_dates and any(
            start <= local.time().replace(tzinfo=None) <= end
            for start, end in SESSIONS
        )
