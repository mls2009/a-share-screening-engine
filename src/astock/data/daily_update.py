import logging
from datetime import date, datetime, time, timedelta
from threading import Event, Thread
from typing import Protocol
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger(__name__)


class ScheduledMarketSync(Protocol):
    def latest_completed_end_date(self) -> date | None: ...

    def start(self, end: date, years: int = 3): ...


class DailyMarketUpdateScheduler:
    run_at = time(16, 10)
    poll_interval = timedelta(minutes=1)

    def __init__(self, service: ScheduledMarketSync) -> None:
        self.service = service
        self._stop = Event()
        self._thread: Thread | None = None
        self._last_attempted_date: date | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_due(self, now: datetime) -> bool:
        local_now = now.astimezone(SHANGHAI)
        today = local_now.date()
        if local_now.weekday() >= 5 or local_now.time() < self.run_at:
            return False
        if self._last_attempted_date == today:
            return False
        latest = self.service.latest_completed_end_date()
        if latest is not None and latest >= today:
            return False

        self._last_attempted_date = today
        self.service.start(end=today, years=3)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_due(datetime.now(SHANGHAI))
            except Exception:
                LOGGER.exception("daily market update failed")
            if self._stop.wait(self.poll_interval.total_seconds()):
                break

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._loop,
            daemon=True,
            name="astock-daily-market-update",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._thread = None
