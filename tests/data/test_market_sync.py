from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.data.market_sync import MarketSyncService
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security
from astock.storage.database import Database
from astock.storage.jobs import SyncJobRepository


class FakeReference:
    def trading_dates(self, start, end):
        return {date(2026, 8, 20)}

    def security_status(self, symbol, start, end):
        return []

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
    def ensure_daily_published(self, target):
        pass

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
        return [Bar(symbol=symbol, timeframe=Timeframe.DAY,
                    timestamp=datetime(2026, 8, 20, 15, tzinfo=ZoneInfo('Asia/Shanghai')),
                    open=10, high=11, low=9, close=10, volume_shares=100,
                    amount_cny=1000, adjustment=adjustment, source='fake')]


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


def test_empty_history_is_not_a_successful_update(tmp_path):
    service, market, _jobs = _service(tmp_path)
    market.history = lambda *args: []
    result = service.start(date(2026, 8, 20))
    assert result.status == 'completed_with_errors'
    assert result.succeeded == 0 and result.failed == 2
    assert service.latest_completed_end_date() is None


def test_stale_history_retries_when_provider_publishes_target_day(tmp_path):
    from datetime import timedelta
    service, market, _jobs = _service(tmp_path)
    market.fail_once.clear()
    original = market.history
    market.history = lambda *args: [b.model_copy(update={
        'timestamp': b.timestamp - timedelta(days=1)
    }) for b in original(*args)]
    first = service.start(date(2026, 8, 20))
    assert first.failed == 2
    market.history = original
    second = service.start(date(2026, 8, 20))
    assert second.job_id == first.job_id
    assert second.status == 'completed' and second.succeeded == 2


def test_only_exact_target_day_confirmed_suspension_can_complete_missing_bar(tmp_path):
    service, market, jobs = _service(tmp_path)
    market.history = lambda *args: []
    def statuses(symbol, start, end):
        return [{'symbol': symbol, 'trade_date': end if symbol == '600000.SH' else date(2026,8,19),
                 'board': 'main', 'is_st': False, 'is_suspended': True,
                 'previous_close': 10, 'limit_up': 11, 'limit_down': 9}]
    service.reference_provider.security_status = statuses
    result = service.start(date(2026,8,20))
    assert result.succeeded == 1 and result.failed == 1
    assert jobs.failed_symbols(result.job_id) == ['000001.SZ']


def test_closed_day_uses_last_confirmed_trading_date(tmp_path):
    service, market, _jobs = _service(tmp_path)
    market.fail_once.clear()
    result = service.start(date(2026,8,23))
    assert result.status == 'completed'


def test_delayed_data_can_be_downloaded_on_same_job_retry(tmp_path):
    from datetime import timedelta

    from astock.data.service import MarketDataService
    from astock.storage.bars import BarStore

    class Reference(FakeReference):
        def trading_dates(self, start, end):
            return {date(2026,8,19), date(2026,8,20)}

    class Provider(FakeMarketData):
        ready = False
        def history(self, *args):
            bars = super().history(*args)
            if not self.ready and args[0] != '000001.SH':
                return [b.model_copy(update={'timestamp': b.timestamp-timedelta(days=1)}) for b in bars]
            return bars

    db = Database(tmp_path/'delayed.duckdb')
    db.migrate()
    provider = Provider()
    provider.fail_once.clear()
    reference = Reference()
    data = MarketDataService(provider, BarStore(tmp_path/'bars'), db, reference_provider=reference)
    jobs = SyncJobRepository(db.connection)
    service = MarketSyncService(data, reference, jobs)
    first = service.start(date(2026,8,20))
    assert first.failed == 2 and service.latest_completed_end_date() is None
    provider.ready = True
    second = service.start(date(2026,8,20))
    assert second.job_id == first.job_id and second.status == 'completed'
    stock_calls = [call for call in provider.history_calls if call[0] != '000001.SH']
    assert len(stock_calls) == 4
    assert all(call[2] == date(2026,8,20) for call in stock_calls[2:])
    db.connection.close()
