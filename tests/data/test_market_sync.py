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
        self.reference_calls: list[tuple] = []
        self.history_calls: list[tuple] = []
        self.fail_once = {"000001.SZ"}

    def sync_reference(self, symbols: list[str], start: date, end: date) -> None:
        self.reference_calls.append((symbols, start, end))

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

    assert summary.total == 2
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.status == "completed_with_errors"
    assert market_data.reference_calls == [
        (["600000.SH", "000001.SZ"], date(2023, 8, 20), date(2026, 8, 20))
    ]
    assert jobs.failed_symbols(summary.job_id) == ["000001.SZ"]


def test_retry_failed_only_requests_previously_failed_symbols(tmp_path: Path) -> None:
    service, market_data, jobs = _service(tmp_path)
    first = service.start(end=date(2026, 8, 20), years=3)
    initial_calls = list(market_data.history_calls)

    retried = service.retry_failed(first.job_id)

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
