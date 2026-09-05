from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astock.data.daily_update import DailyMarketUpdateScheduler

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeMarketSync:
    def __init__(self, latest: date | None = None) -> None:
        self.latest = latest
        self.calls: list[tuple[date, int]] = []

    def latest_completed_end_date(self) -> date | None:
        return self.latest

    def start(self, end: date, years: int = 3):
        self.calls.append((end, years))
        self.latest = end
        return SimpleNamespace(end=end)


def moment(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=SHANGHAI)


def test_daily_update_runs_once_after_market_close() -> None:
    service = FakeMarketSync()
    scheduler = DailyMarketUpdateScheduler(service)

    assert scheduler.run_due(moment(4, 16, 9)) is False
    assert scheduler.run_due(moment(4, 16, 10)) is True
    assert scheduler.run_due(moment(4, 18, 0)) is False
    assert service.calls == [(date(2026, 9, 4), 3)]


def test_daily_update_skips_weekends() -> None:
    service = FakeMarketSync()
    scheduler = DailyMarketUpdateScheduler(service)

    assert scheduler.run_due(moment(5, 18, 0)) is False
    assert scheduler.run_due(moment(6, 18, 0)) is False
    assert service.calls == []


def test_daily_update_uses_completed_job_to_avoid_repeat_after_restart() -> None:
    service = FakeMarketSync(latest=date(2026, 9, 4))
    scheduler = DailyMarketUpdateScheduler(service)

    assert scheduler.run_due(moment(4, 17, 0)) is False
    assert service.calls == []
