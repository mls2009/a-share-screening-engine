from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.storage.bars import BarStore
from astock.storage.coverage import CoverageRepository
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")


def test_missing_ranges_merge_overlapping_coverage(tmp_path: Path) -> None:
    database = Database(tmp_path / "coverage.duckdb")
    database.migrate()
    repository = CoverageRepository(database)
    repository.record(
        "600519.SH",
        Timeframe.DAY,
        Adjustment.NONE,
        date(2026, 1, 1),
        date(2026, 1, 10),
    )
    repository.record(
        "600519.SH",
        Timeframe.DAY,
        Adjustment.NONE,
        date(2026, 1, 8),
        date(2026, 1, 20),
    )

    assert repository.missing_ranges(
        "600519.SH",
        Timeframe.DAY,
        Adjustment.NONE,
        date(2026, 1, 1),
        date(2026, 1, 31),
    ) == [(date(2026, 1, 21), date(2026, 1, 31))]


def test_bar_store_reads_inclusive_range_and_adjustment(tmp_path: Path) -> None:
    store = BarStore(tmp_path / "bars")
    bars = [
        Bar(
            symbol="600519.SH",
            timestamp=datetime(2026, 8, day, 15, tzinfo=TZ),
            timeframe=Timeframe.DAY,
            open=10,
            high=11,
            low=9,
            close=10,
            volume_shares=100,
            amount_cny=1_000,
            adjustment=adjustment,
            source="test",
        )
        for day, adjustment in [
            (19, Adjustment.NONE),
            (20, Adjustment.NONE),
            (21, Adjustment.NONE),
            (20, Adjustment.QFQ),
        ]
    ]
    store.upsert(bars)

    result = store.read_range(
        "600519.SH",
        Timeframe.DAY,
        Adjustment.NONE,
        date(2026, 8, 20),
        date(2026, 8, 21),
    )

    assert [bar.timestamp.date() for bar in result] == [date(2026, 8, 20), date(2026, 8, 21)]
