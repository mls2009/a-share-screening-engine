import logging
from datetime import datetime, timedelta
from threading import Event, Thread
from typing import ClassVar, Protocol
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger(__name__)


class ScheduledMonitoring(Protocol):
    def run_watchlist_once(self, now: datetime): ...

    def run_market_once(self, now: datetime): ...


class MonitoringScheduler:
    intervals: ClassVar[dict[str, timedelta]] = {
        "watchlist": timedelta(seconds=5),
        "market": timedelta(minutes=5),
    }

    def __init__(self, service: ScheduledMonitoring) -> None:
        self.service = service
        self._stop = Event()
        self._threads: list[Thread] = []

    @property
    def running(self) -> bool:
        return bool(self._threads) and not self._stop.is_set()

    def interval_for(self, name: str) -> timedelta:
        return self.intervals[name]

    def _loop(self, name: str) -> None:
        interval = self.intervals[name].total_seconds()
        callback = (
            self.service.run_watchlist_once
            if name == "watchlist"
            else self.service.run_market_once
        )
        while not self._stop.wait(interval):
            try:
                callback(datetime.now(SHANGHAI))
            except Exception:
                LOGGER.exception("monitoring scan failed", extra={"scope": name})

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._threads = [
            Thread(target=self._loop, args=(name,), daemon=True, name=f"astock-{name}")
            for name in self.intervals
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1)
        self._threads.clear()
