from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.storage.bars import BarStore


def test_upsert_bars_deduplicates_symbol_timestamp(tmp_path: Path) -> None:
    bar = Bar(
        symbol="600519.SH",
        timestamp=datetime(2026, 8, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        timeframe=Timeframe.DAY,
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume_shares=1_000,
        amount_cny=10_500,
        source="test",
    )
    store = BarStore(tmp_path)

    store.upsert([bar, bar])
    saved = store.read("600519.SH", Timeframe.DAY, Adjustment.NONE)

    assert saved == [bar]


def test_read_latest_scans_backwards_and_filters_adjustment_and_as_of(
    tmp_path: Path,
) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    store = BarStore(tmp_path)
    store.upsert(
        [
            Bar(
                symbol="600519.SH",
                timestamp=datetime(year, 8, day, 15, tzinfo=timezone),
                timeframe=Timeframe.DAY,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume_shares=1_000,
                amount_cny=10_500,
                adjustment=adjustment,
                source="test",
            )
            for year, day, close, adjustment in (
                (2024, 20, 10.0, Adjustment.QFQ),
                (2025, 19, 20.0, Adjustment.HFQ),
                (2025, 21, 30.0, Adjustment.QFQ),
                (2026, 20, 40.0, Adjustment.QFQ),
            )
        ]
    )

    qfq = store.read_latest(
        "600519.SH", Timeframe.DAY, Adjustment.QFQ, date(2025, 8, 20)
    )
    hfq = store.read_latest(
        "600519.SH", Timeframe.DAY, Adjustment.HFQ, date(2025, 8, 20)
    )

    assert qfq is not None and qfq.close == 10.0
    assert hfq is not None and hfq.close == 20.0
    assert (
        store.read_latest(
            "000001.SZ", Timeframe.DAY, Adjustment.QFQ, date(2025, 8, 20)
        )
        is None
    )


def test_read_latest_can_skip_non_final_rows(tmp_path: Path) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    store = BarStore(tmp_path)
    store.upsert(
        [
            Bar(
                symbol="600519.SH",
                timestamp=datetime(2026, 8, 20, 9, minute, tzinfo=timezone),
                timeframe=Timeframe.MIN_5,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume_shares=1_000,
                amount_cny=10_500,
                adjustment=Adjustment.QFQ,
                source="test",
                is_final=is_final,
            )
            for minute, close, is_final in (
                (35, 10.0, True),
                (40, 11.0, False),
            )
        ]
    )

    latest = store.read_latest(
        "600519.SH", Timeframe.MIN_5, Adjustment.QFQ, date(2026, 8, 20)
    )
    latest_final = store.read_latest(
        "600519.SH",
        Timeframe.MIN_5,
        Adjustment.QFQ,
        date(2026, 8, 20),
        final_only=True,
    )

    assert latest is not None and latest.close == 11.0
    assert latest_final is not None and latest_final.close == 10.0


def test_revision_changes_when_same_timestamp_bar_is_replaced(tmp_path: Path) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    store = BarStore(tmp_path)
    timestamp = datetime(2026, 8, 20, 9, 35, tzinfo=timezone)

    def write(close: float) -> None:
        store.upsert(
            [
                Bar(
                    symbol="600519.SH",
                    timestamp=timestamp,
                    timeframe=Timeframe.MIN_5,
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume_shares=1_000,
                    amount_cny=10_500,
                    adjustment=Adjustment.QFQ,
                    source="test",
                )
            ]
        )

    assert store.revision("600519.SH", Timeframe.MIN_5, timestamp.date()) is None
    write(10.0)
    first = store.revision("600519.SH", Timeframe.MIN_5, timestamp.date())
    write(11.0)
    second = store.revision("600519.SH", Timeframe.MIN_5, timestamp.date())

    assert first is not None
    assert second is not None
    assert second != first


def test_revision_changes_when_an_earlier_year_is_backfilled(tmp_path: Path) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    store = BarStore(tmp_path)

    def bar(year: int) -> Bar:
        return Bar(
            symbol="600519.SH",
            timestamp=datetime(year, 8, 20, 15, tzinfo=timezone),
            timeframe=Timeframe.DAY,
            open=10,
            high=11,
            low=9,
            close=10.5,
            volume_shares=1_000,
            amount_cny=10_500,
            adjustment=Adjustment.QFQ,
            source="test",
        )

    store.upsert([bar(2026)])
    first = store.revision("600519.SH", Timeframe.DAY, date(2026, 8, 20))
    store.upsert([bar(2025)])
    second = store.revision("600519.SH", Timeframe.DAY, date(2026, 8, 20))

    assert first is not None
    assert second is not None
    assert second != first


def test_revision_ignores_files_from_years_after_as_of(tmp_path: Path) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    store = BarStore(tmp_path)

    def bar(year: int) -> Bar:
        return Bar(
            symbol="600519.SH",
            timestamp=datetime(year, 8, 20, 15, tzinfo=timezone),
            timeframe=Timeframe.DAY,
            open=10,
            high=11,
            low=9,
            close=10.5,
            volume_shares=1_000,
            amount_cny=10_500,
            adjustment=Adjustment.QFQ,
            source="test",
        )

    store.upsert([bar(2026)])
    first = store.revision("600519.SH", Timeframe.DAY, date(2026, 8, 20))
    store.upsert([bar(2027)])

    assert store.revision(
        "600519.SH", Timeframe.DAY, date(2026, 8, 20)
    ) == first
