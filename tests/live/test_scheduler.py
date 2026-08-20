from datetime import timedelta

from astock.live.scheduler import MonitoringScheduler


class FakeService:
    def run_watchlist_once(self, now):
        return None

    def run_market_once(self, now):
        return None


def test_scheduler_exposes_required_intervals_and_lifecycle() -> None:
    scheduler = MonitoringScheduler(FakeService())

    assert scheduler.interval_for("watchlist") == timedelta(seconds=5)
    assert scheduler.interval_for("market") == timedelta(minutes=5)
    assert scheduler.running is False
    scheduler.start()
    assert scheduler.running is True
    scheduler.stop()
    assert scheduler.running is False
