from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.domain.market import Quote
from astock.live.models import MonitorTaskCreate
from astock.live.repository import MonitoringRepository
from astock.live.service import MonitoringService
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 20, 10, tzinfo=TZ)


class FakeQuotes:
    def __init__(self) -> None:
        self.price = 99
        self.timestamp = NOW

    def quotes(self, symbols: list[str]) -> list[Quote]:
        return [
            Quote(
                symbol=symbol,
                timestamp=self.timestamp,
                price=self.price,
                volume_shares=1000,
                amount_cny=self.price * 1000,
                source="fake",
            )
            for symbol in symbols
        ]


def _service(tmp_path: Path) -> tuple[MonitoringService, MonitoringRepository, FakeQuotes]:
    database = Database(tmp_path / "live.duckdb")
    database.migrate()
    database.connection.execute(
        "insert into trading_calendar values (?, true)", [date(2026, 8, 20)]
    )
    source = FakeQuotes()
    repository = MonitoringRepository(database)
    service = MonitoringService(database, repository, source)
    return service, repository, source


def test_watchlist_scan_triggers_only_on_fresh_crossing(tmp_path: Path) -> None:
    service, repository, source = _service(tmp_path)
    repository.create_task(
        MonitorTaskCreate(
            name="突破 100",
            symbols=["600519.SH"],
            comparator="cross_above",
            threshold=100,
        )
    )

    seeded = service.run_watchlist_once(NOW)
    source.price = 101
    source.timestamp = NOW + timedelta(seconds=5)
    crossed = service.run_watchlist_once(NOW + timedelta(seconds=5))
    held = service.run_watchlist_once(NOW + timedelta(seconds=10))

    assert seeded.triggered == 0
    assert crossed.triggered == 1
    assert held.triggered == 0
    assert repository.database.connection.execute("select count(*) from signals").fetchone()[0] == 1


def test_stale_quotes_are_paused_without_changing_state(tmp_path: Path) -> None:
    service, repository, source = _service(tmp_path)
    task = repository.create_task(
        MonitorTaskCreate(
            name="达到 100",
            symbols=["600519.SH"],
            comparator="above",
            threshold=100,
        )
    )
    source.price = 101
    source.timestamp = NOW - timedelta(minutes=3)

    result = service.run_watchlist_once(NOW)

    assert result.paused_symbols == {"600519.SH": "stale_quote"}
    assert repository.get_state(task.task_id, "600519.SH").last_value is None


def test_market_scope_without_symbols_loads_full_listed_universe(tmp_path: Path) -> None:
    service, repository, source = _service(tmp_path)
    repository.database.connection.executemany(
        """
        insert into symbols (symbol, name, exchange, is_listed)
        values (?, ?, ?, true)
        """,
        [
            ["600001.SH", "股票一", "SH"],
            ["000001.SZ", "股票二", "SZ"],
        ],
    )
    repository.create_task(
        MonitorTaskCreate(
            name="全市场百元股",
            symbols=[],
            comparator="above",
            threshold=100,
            scope="market",
        )
    )
    source.price = 101

    result = service.run_market_once(NOW)

    assert result.requested_symbols == 2
    assert result.received_quotes == 2
    assert result.triggered == 2
