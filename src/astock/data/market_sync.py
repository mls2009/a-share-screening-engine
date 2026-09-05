from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from astock.data.providers.base import ReferenceDataProvider
from astock.domain.market import Adjustment, Timeframe
from astock.domain.security import Security
from astock.storage.jobs import SyncJobRepository


class MarketDataWriter(Protocol):
    def sync_universe(self, start: date, end: date) -> list[Security]: ...

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

    @staticmethod
    def _years_before(value: date, years: int) -> date:
        try:
            return value.replace(year=value.year - years)
        except ValueError:
            return value.replace(year=value.year - years, day=28)

    def start(self, end: date, years: int = 3) -> SyncSummary:
        if years <= 0:
            raise ValueError("years must be positive")
        start = self._years_before(end, years)
        securities = self.market_data.sync_universe(start, end)
        symbols = [security.symbol for security in securities if security.is_listed]
        job_id = self.jobs.create(start, end, total=len(symbols))
        return self._run(job_id, symbols)

    def retry_failed(self, job_id: UUID) -> SyncSummary:
        symbols = self.jobs.failed_symbols(job_id)
        self.jobs.reopen(job_id)
        return self._run(job_id, symbols)

    def resume(self, job_id: UUID) -> SyncSummary:
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
        session = getattr(self.market_data, "bulk_session", nullcontext)
        with session():
            for symbol in symbols:
                try:
                    self.market_data.history(
                        symbol,
                        Timeframe.DAY,
                        job.start_date,
                        job.end_date,
                        Adjustment.QFQ,
                    )
                    if self.feature_builder is not None:
                        self.feature_builder.build_symbol(symbol, job.end_date)
                except Exception as error:  # noqa: BLE001 - one stock must not abort the batch
                    self.jobs.mark_failed(job_id, symbol, str(error))
                else:
                    self.jobs.mark_succeeded(job_id, symbol)
        self.jobs.complete(job_id)
        completed = self.jobs.get(job_id)
        return SyncSummary(
            job_id=job_id,
            total=completed.total,
            succeeded=completed.succeeded,
            failed=completed.failed,
            status=completed.status,
        )
