import shutil

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from threading import Event
from typing import Protocol
from uuid import UUID

from astock.data.providers.base import ReferenceDataProvider
from astock.data.updates import MarketUpdates
from astock.domain.market import Adjustment, Timeframe
from astock.domain.security import Security
from astock.storage.jobs import SyncJobRepository


class MarketDataWriter(Protocol):
    def sync_universe(self, start: date, end: date) -> list[Security]: ...

    def ensure_daily_published(self, target: date) -> None: ...

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> list: ...


class SymbolFeatureBuilder(Protocol):
    def build_symbol(self, symbol: str, as_of: date) -> None: ...


@dataclass(frozen=True)
class SyncSummary:
    job_id: UUID
    total: int
    succeeded: int
    failed: int
    status: str


class MarketSyncService:
    def __init__(
        self,
        market_data: MarketDataWriter,
        reference_provider: ReferenceDataProvider,
        jobs: SyncJobRepository,
        feature_builder: SymbolFeatureBuilder | None = None,
    ) -> None:
        self.market_data = market_data
        self.reference_provider = reference_provider
        self.jobs = jobs
        self.feature_builder = feature_builder
        self.updates = MarketUpdates()
        self.stopping = Event()

    def _check_disk_space(self) -> None:
        if shutil.disk_usage(self.jobs.connection.path.parent).free < 3 * 1024**3:
            raise RuntimeError("可用空间不足 3 GiB，暂停行情更新以保护数据库")

    def stop(self) -> None:
        self.stopping.set()

    @staticmethod
    def _years_before(value: date, years: int) -> date:
        try:
            return value.replace(year=value.year - years)
        except ValueError:
            return value.replace(year=value.year - years, day=28)

    def start(self, end: date, years: int = 3) -> SyncSummary:
        if years <= 0:
            raise ValueError("years must be positive")
        self._check_disk_space()
        refresh = getattr(self.market_data, "sync_watchlist_status", None)
        if refresh is not None:
            refresh(end)
            self.updates.publish()
        pending = self.jobs.connection.execute(
            """select job_id from data_sync_jobs where end_date = ?
            and status in ('running', 'completed_with_errors')
            order by started_at desc limit 1""", [end],
        ).fetchone()
        if pending:
            return self.resume(pending[0])
        start = self._years_before(end, years)
        securities = self.market_data.sync_universe(start, end)
        symbols = [security.symbol for security in securities if security.is_listed]
        job_id = self.jobs.create(start, end, total=len(symbols))
        return self._run(job_id, symbols)

    def retry_failed(self, job_id: UUID) -> SyncSummary:
        self._check_disk_space()
        symbols = self.jobs.failed_symbols(job_id)
        self.jobs.reopen(job_id)
        return self._run(job_id, symbols)

    def resume(self, job_id: UUID) -> SyncSummary:
        self._check_disk_space()
        job = self.jobs.get(job_id)
        succeeded = self.jobs.succeeded_symbols(job_id)
        symbols = [
            security.symbol
            for security in self.reference_provider.securities_on(job.end_date)
            if security.is_listed and security.symbol not in succeeded
        ]
        self.jobs.reopen(job_id)
        return self._run(job_id, symbols)

    def status(self, job_id: UUID) -> SyncSummary:
        job = self.jobs.get(job_id)
        return SyncSummary(
            job_id=job.job_id,
            total=job.total,
            succeeded=job.succeeded,
            failed=job.failed,
            status=job.status,
        )

    def latest_completed_end_date(self) -> date | None:
        return self.jobs.latest_completed_end_date()

    def _run(self, job_id: UUID, symbols: list[str]) -> SyncSummary:
        job = self.jobs.get(job_id)
        open_dates = self.reference_provider.trading_dates(job.start_date, job.end_date)
        if not open_dates:
            raise RuntimeError("无法确认目标交易日，不能将行情更新标记为完成")
        target = max(open_dates)
        session = getattr(self.market_data, "bulk_session", nullcontext)
        with session():
            self.market_data.ensure_daily_published(target)
            for symbol in symbols:
                if self.stopping.is_set():
                    break
                self._check_disk_space()
                try:
                    bars = self.market_data.history(
                        symbol,
                        Timeframe.DAY,
                        job.start_date,
                        job.end_date,
                        Adjustment.QFQ,
                    )
                    current = any(bar.timestamp.date() == target and bar.is_final for bar in bars)
                    if not current:
                        statuses = self.reference_provider.security_status(symbol, target, target)
                        suspended = next((row for row in statuses
                            if row["symbol"] == symbol and row["trade_date"] == target
                            and row["is_suspended"]), None)
                        if suspended is None:
                            latest = max((bar.timestamp.date() for bar in bars), default=None)
                            raise RuntimeError(
                                f"目标交易日 {target} 日线尚未到齐（本地最新 {latest or '无'}），"
                                "且未确认当日停牌，等待重试"
                            )
                        self.jobs.connection.execute(
                            "insert or replace into security_status values (?, ?, ?, ?, ?, ?, ?, ?)",
                            [suspended[key] for key in ("symbol", "trade_date", "board", "is_st",
                                "is_suspended", "previous_close", "limit_up", "limit_down")],
                        )
                    if self.feature_builder is not None:
                        getattr(self.feature_builder, "build_incremental_symbol", self.feature_builder.build_symbol)(symbol, job.end_date)
                except Exception as error:  # noqa: BLE001 - one stock must not abort the batch
                    self.jobs.mark_failed(job_id, symbol, str(error))
                else:
                    self.jobs.mark_succeeded(job_id, symbol)
        if not self.stopping.is_set():
            self.jobs.complete(job_id)
        self.updates.publish()
        completed = self.jobs.get(job_id)
        return SyncSummary(
            job_id=job_id,
            total=completed.total,
            succeeded=completed.succeeded,
            failed=completed.failed,
            status=completed.status,
        )
