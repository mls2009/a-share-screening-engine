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
        self._next_attempt: datetime | None = None
        self.last_attempt: datetime | None = None
        self.last_error: str | None = None
        self.target_date: date | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def next_attempt(self) -> datetime | None:
        return self._next_attempt

    def run_due(self, now: datetime) -> bool:
        local_now = now.astimezone(SHANGHAI)
        today = local_now.date()
        latest = self.service.latest_completed_end_date()
        target = today
        if local_now.time() < self.run_at:
            target -= timedelta(days=1)
        while target.weekday() >= 5:
            target -= timedelta(days=1)
        # An empty installation waits for its first scheduled close; existing
        # installations catch up even when restarted before close or on weekends.
        if latest is None and target != today:
            return False
        if latest is not None and latest >= target:
            self._next_attempt = None
            return False
        if self._next_attempt is not None and local_now < self._next_attempt:
            return False

        self._next_attempt = local_now + timedelta(minutes=30)
        self.last_attempt = local_now
        self.target_date = target
        try:
            result = self.service.start(end=target, years=3)
        except Exception as error:
            self.last_error = str(error)
            raise
        self.last_error = (f"更新未全部完成：{getattr(result, 'failed', 0)} 只失败，请查看任务明细"
                           if getattr(result, "status", None) == "completed_with_errors" else None)
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
        cancel = getattr(self.service, "stop", None)
        if cancel is not None:
            cancel()
        if self._thread is not None:
            self._thread.join(timeout=25 if cancel is not None else 1)
        self._thread = None
