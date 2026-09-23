from datetime import date
from pathlib import Path

from astock.data.market_sync import MarketSyncService
from astock.domain.market import Adjustment, Timeframe
from astock.domain.security import Security
from astock.storage.database import Database
from astock.storage.jobs import SyncJobRepository


class FakeReference:
    def securities_on(self, on_date: date) -> list[Security]:
        return [
            Security(
                symbol="600000.SH",
                name="浦发银行",
                exchange="SH",
                board="main",
                listed_on=date(1999, 11, 10),
            ),
            Security(
                symbol="000001.SZ",
                name="平安银行",
                exchange="SZ",
                board="main",
                listed_on=date(1991, 4, 3),
            ),
        ]


class FakeMarketData:
    def __init__(self) -> None:
        self.universe_calls: list[tuple] = []
        self.history_calls: list[tuple] = []
        self.fail_once = {"000001.SZ"}

    def sync_universe(self, start: date, end: date) -> list[Security]:
        self.universe_calls.append((start, end))
        return FakeReference().securities_on(end)

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> list:
        self.history_calls.append((symbol, timeframe, start, end, adjustment))
        if symbol in self.fail_once:
            self.fail_once.remove(symbol)
            raise RuntimeError("temporary provider error")
        return []


class FakeFeatureBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def build_symbol(self, symbol: str, as_of: date) -> None:
        self.calls.append((symbol, as_of))


def _service(tmp_path: Path) -> tuple[MarketSyncService, FakeMarketData, SyncJobRepository]:
    database = Database(tmp_path / "market.duckdb")
    database.migrate()
    jobs = SyncJobRepository(database.connection)
    market_data = FakeMarketData()
    return (
        MarketSyncService(market_data, FakeReference(), jobs),
        market_data,
        jobs,
    )


def test_full_market_sync_continues_after_one_symbol_fails(tmp_path: Path) -> None:
    service, market_data, jobs = _service(tmp_path)

    summary = service.start(end=date(2026, 8, 20), years=3)

    assert service.updates.revision == 1
    assert summary.total == 2
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.status == "completed_with_errors"
    assert market_data.universe_calls == [
        (date(2023, 8, 20), date(2026, 8, 20))
    ]
    assert jobs.failed_symbols(summary.job_id) == ["000001.SZ"]
    assert service.latest_completed_end_date() is None


def test_retry_failed_only_requests_previously_failed_symbols(tmp_path: Path) -> None:
    service, market_data, jobs = _service(tmp_path)
    first = service.start(end=date(2026, 8, 20), years=3)
    initial_calls = list(market_data.history_calls)

    retried = service.retry_failed(first.job_id)

    assert service.updates.revision == 2
    assert retried.status == "completed"
    assert retried.succeeded == 2
    assert retried.failed == 0
    assert market_data.history_calls == [
        *initial_calls,
        (
            "000001.SZ",
            Timeframe.DAY,
            date(2023, 8, 20),
            date(2026, 8, 20),
            Adjustment.QFQ,
        ),
    ]
    assert jobs.failed_symbols(first.job_id) == []


def test_successful_symbol_builds_screening_features_immediately(tmp_path: Path) -> None:
    database = Database(tmp_path / "pipeline.duckdb")
    database.migrate()
    market_data = FakeMarketData()
    builder = FakeFeatureBuilder()
    service = MarketSyncService(
        market_data,
        FakeReference(),
        SyncJobRepository(database.connection),
        feature_builder=builder,
    )

    service.start(end=date(2026, 8, 20), years=3)

    assert builder.calls == [("600000.SH", date(2026, 8, 20))]


def test_resume_requests_pending_symbols_but_not_already_succeeded_symbols(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "resume.duckdb")
    database.migrate()
    jobs = SyncJobRepository(database.connection)
    job_id = jobs.create(date(2023, 8, 20), date(2026, 8, 20), total=2)
    jobs.mark_succeeded(job_id, "600000.SH")
    market_data = FakeMarketData()
    market_data.fail_once.clear()
    service = MarketSyncService(market_data, FakeReference(), jobs)

    summary = service.resume(job_id)

    assert summary.status == "completed"
    assert [call[0] for call in market_data.history_calls] == ["000001.SZ"]


def test_scheduled_retry_resumes_same_job(tmp_path: Path) -> None:
    service, market_data, _jobs = _service(tmp_path)
    first = service.start(end=date(2026, 8, 20))
    count = len(market_data.history_calls)
    second = service.start(end=date(2026, 8, 20))
    assert second.job_id == first.job_id
    assert second.status == 'completed'
    assert [call[0] for call in market_data.history_calls[count:]] == ['000001.SZ']
    assert service.latest_completed_end_date() == date(2026, 8, 20)


def test_stop_preserves_unfinished_job_for_resume(tmp_path):
    service, market_data, jobs = _service(tmp_path)
    original = market_data.history
    def history(*args):
        service.stop()
        return original(*args)
    market_data.history = history
    summary = service.start(date(2026, 8, 20))
    assert len(market_data.history_calls) == 1
    assert summary.status == "running"
    assert jobs.get(summary.job_id).finished_at is None


def test_market_sync_uses_incremental_feature_builder(tmp_path):
    service, market_data, jobs = _service(tmp_path)
    market_data.fail_once.clear()
    class Builder:
        calls = []
        def build_symbol(self, *args):
            raise AssertionError('full rebuild must not be used')
        def build_incremental_symbol(self, symbol, as_of):
            self.calls.append((symbol, as_of))
    builder = Builder()
    service.feature_builder = builder
    summary = service.start(date(2026, 8, 20))
    assert summary.succeeded == 2
    assert len(builder.calls) == 2


def test_primary_sync_refuses_low_disk_before_any_provider_or_write(tmp_path, monkeypatch):
    import shutil
    import pytest
    from types import SimpleNamespace
    service, market, jobs = _service(tmp_path)
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=2*1024**3))
    with pytest.raises(RuntimeError, match='空间'):
        service.start(end=date(2026,8,20))
    assert market.universe_calls==[] and market.history_calls==[]
    assert jobs.connection.execute('select count(*) from data_sync_jobs').fetchone()[0]==0
