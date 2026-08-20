from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from time import sleep
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features import builder as builder_module
from astock.features.builder import FeatureBuilder
from astock.features.store import MarketFeatureStore
from astock.features.zones import PriceZone
from astock.storage.bars import BarStore
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")


def test_builder_persists_idempotent_daily_weekly_monthly_features(tmp_path: Path) -> None:
    database = Database(tmp_path / "features.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "bars")
    dates = pd.date_range("2026-01-02", periods=40, freq="B")
    bars = [
        Bar(
            symbol="600000.SH",
            timestamp=datetime.combine(stamp.date(), datetime.min.time(), tzinfo=TZ),
            timeframe=Timeframe.DAY,
            open=index,
            high=index + 1,
            low=index - 1,
            close=index + 0.5,
            volume_shares=1_000 * index,
            amount_cny=10_000 * index,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for index, stamp in enumerate(dates, start=1)
    ]
    bar_store.upsert(bars)
    database.connection.execute(
        """
        insert into symbols
          (symbol, name, exchange, listed_on, board, is_listed)
        values ('600000.SH', '浦发银行', 'SH', ?, 'main', true)
        """,
        [dates[0].date()],
    )
    store = MarketFeatureStore(database)
    builder = FeatureBuilder(bar_store, store, database)

    builder.build_symbol("600000.SH", dates[-1].date())
    builder.build_symbol("600000.SH", dates[-1].date())

    counts = dict(
        database.connection.execute(
            "select timeframe, count(*) from market_features group by timeframe"
        ).fetchall()
    )
    latest = store.read_latest("600000.SH", Timeframe.DAY, dates[-1].date())
    assert counts["1d"] == 40
    assert counts["1w"] > 1
    assert counts["1mo"] == 2
    assert database.connection.execute(
        "select count(*) from pattern_events where symbol = '600000.SH'"
    ).fetchone()[0] > 0
    assert latest is not None
    assert latest["listing_trade_days"] == 40
    assert latest["is_new"] is False
    assert latest["is_secondary_new"] is True


def test_builder_persists_automatic_support_and_resistance_zones(tmp_path: Path) -> None:
    database = Database(tmp_path / "zones.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "bars")
    closes = [12] * 14
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    bars = []
    for index, (stamp, close) in enumerate(zip(dates, closes, strict=True)):
        low = {1: 8.0, 4: 9.0, 7: 10.0, 10: 11.0}.get(index, close - 0.4)
        high = {2: 16.0, 5: 15.0, 8: 14.0, 11: 13.0}.get(index, close + 0.4)
        bars.append(
            Bar(
                symbol="600000.SH",
                timestamp=datetime.combine(stamp.date(), datetime.min.time(), tzinfo=TZ),
                timeframe=Timeframe.DAY,
                open=close - 0.1,
                high=high,
                low=low,
                close=close,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        )
    bar_store.upsert(bars)
    database.connection.execute(
        """
        insert into symbols (symbol, name, exchange, listed_on, is_listed)
        values ('600000.SH', '浦发银行', 'SH', ?, true)
        """,
        [dates[0].date()],
    )

    FeatureBuilder(bar_store, MarketFeatureStore(database), database).build_symbol(
        "600000.SH", dates[-1].date()
    )

    kinds = {
        row[0]
        for row in database.connection.execute(
            """
            select distinct zone_kind from support_resistance_zones
            where timeframe = '1d' and geometry = 'trend'
            """
        ).fetchall()
    }
    assert kinds == {"uptrend", "downtrend"}


@pytest.mark.parametrize(
    "timeframe",
    [
        Timeframe.MIN_5,
        Timeframe.MIN_15,
        Timeframe.MIN_30,
        Timeframe.MIN_60,
    ],
)
def test_ensure_chart_zones_uses_only_final_five_minute_bars(
    tmp_path: Path, timeframe: Timeframe
) -> None:
    database = Database(tmp_path / f"{timeframe.value}-zones.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / f"{timeframe.value}-bars")
    timestamp = datetime(2026, 8, 20, 9, 35, tzinfo=TZ)
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=timestamp,
                timeframe=Timeframe.MIN_5,
                open=10,
                high=10.6,
                low=9.8,
                close=10.5,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            ),
            Bar(
                symbol="600000.SH",
                timestamp=timestamp + timedelta(minutes=5),
                timeframe=Timeframe.MIN_5,
                open=99,
                high=100.5,
                low=98.5,
                close=100,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
                is_final=False,
            ),
        ]
    )
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)

    assert (
        builder.ensure_chart_zones(
            "600000.SH", timeframe, as_of=date(2026, 8, 20)
        )
        == 10.5
    )


def test_ensure_chart_zones_returns_none_without_base_bars(tmp_path: Path) -> None:
    database = Database(tmp_path / "empty-zones.duckdb")
    database.migrate()
    builder = FeatureBuilder(
        BarStore(tmp_path / "empty-bars"), MarketFeatureStore(database), database
    )

    assert (
        builder.ensure_chart_zones(
            "600000.SH", Timeframe.MIN_15, as_of=date(2026, 8, 20)
        )
        is None
    )


def test_empty_chart_zone_detection_is_not_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "empty-detection.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "empty-detection-bars")
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=datetime(2026, 8, 20, 9, 35, tzinfo=TZ),
                timeframe=Timeframe.MIN_5,
                open=10,
                high=10.6,
                low=9.8,
                close=10.5,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        ]
    )
    detections = []

    def detect_empty(*_args, **_kwargs) -> list[PriceZone]:
        detections.append(True)
        return []

    monkeypatch.setattr(builder_module, "detect_zones", detect_empty)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)

    first = builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    second = builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )

    assert first == second == 10.5
    assert len(detections) == 1
    assert database.connection.execute(
        """
        select max(as_of_date) from zone_detection_batches
        where symbol = '600000.SH' and timeframe = '5m'
        """
    ).fetchone() == (date(2026, 8, 20),)


def test_concurrent_chart_zone_builds_persist_one_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "concurrent-zones.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "concurrent-bars")
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=datetime(2026, 8, 20, 9, 35, tzinfo=TZ),
                timeframe=Timeframe.MIN_5,
                open=10,
                high=10.6,
                low=9.8,
                close=10.5,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        ]
    )
    detected = []

    def slow_detect_zones(*_args, **_kwargs) -> list[PriceZone]:
        detected.append(True)
        sleep(0.05)
        return [
            PriceZone(
                as_of_date=date(2026, 8, 20),
                zone_kind="support",
                geometry="horizontal",
                lower_price=9.8,
                center_price=10,
                upper_price=10.2,
                slope=None,
                intercept=None,
                anchors=((date(2026, 8, 20), 10),),
                strength=0.8,
                touches=1,
            )
        ]

    monkeypatch.setattr(builder_module, "detect_zones", slow_detect_zones)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)
    start = Barrier(2)

    def ensure() -> float | None:
        start.wait(timeout=5)
        return builder.ensure_chart_zones(
            "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        closes = list(executor.map(lambda _index: ensure(), range(2)))

    assert closes == [10.5, 10.5]
    assert len(detected) == 1
    assert database.connection.execute(
        """
        select count(*) from support_resistance_zones
        where symbol = '600000.SH' and timeframe = '5m' and source = 'auto'
        """
    ).fetchone() == (1,)
