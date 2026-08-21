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
from astock.features.zones import (
    ZONE_RULE_VERSION,
    PriceZone,
    chart_zones,
    replace_auto_zones,
)
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
    assert latest["high_history"] == 41.0
    assert latest["low_history"] == 0.0


def test_builder_persists_automatic_support_and_resistance_zones(tmp_path: Path) -> None:
    database = Database(tmp_path / "zones.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "bars")
    closes = [12] * 15
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    bars = []
    for index, (stamp, close) in enumerate(zip(dates, closes, strict=True)):
        low = {2: 10.0, 6: 10.0, 10: 10.0}.get(index, close - 0.4)
        high = {4: 15.0, 8: 15.0, 12: 15.0}.get(index, close + 0.4)
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

    zones = {
        tuple(row)
        for row in database.connection.execute(
            """
            select distinct zone_kind, geometry from support_resistance_zones
            where timeframe = '1d' and source = 'auto'
            """
        ).fetchall()
    }
    assert zones == {
        ("support", "horizontal"),
        ("resistance", "horizontal"),
    }


def test_builder_records_the_latest_source_bar_as_zone_watermark(tmp_path: Path) -> None:
    database = Database(tmp_path / "daily-zone-watermark.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "daily-zone-watermark-bars")
    timestamp = datetime(2026, 8, 20, 15, 0, tzinfo=TZ)
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=timestamp,
                timeframe=Timeframe.DAY,
                open=10,
                high=11,
                low=9,
                close=10.5,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        ]
    )

    FeatureBuilder(bar_store, MarketFeatureStore(database), database).build_symbol(
        "600000.SH", timestamp.date()
    )

    assert database.connection.execute(
        """
        select distinct epoch(latest_bar_at), source_revision
        from zone_detection_batches
        """
    ).fetchall() == [
        (
            timestamp.timestamp(),
            bar_store.revision("600000.SH", Timeframe.DAY, timestamp.date()),
        )
    ]


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


def test_same_day_new_final_bar_refreshes_chart_zone_watermark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "same-day-refresh.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "same-day-bars")
    first_timestamp = datetime(2026, 8, 20, 9, 35, tzinfo=TZ)
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=first_timestamp,
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

    def detect_empty(*_args, **kwargs) -> list[PriceZone]:
        detections.append(kwargs.get("rule_version", "v1"))
        return []

    monkeypatch.setattr(builder_module, "detect_zones", detect_empty)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)

    first_close = builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    second_timestamp = first_timestamp + timedelta(minutes=5)
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=second_timestamp,
                timeframe=Timeframe.MIN_5,
                open=10.5,
                high=11.2,
                low=10.4,
                close=11,
                volume_shares=1_000,
                amount_cny=11_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        ]
    )
    second_close = builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    database.connection.execute(
        """
        update zone_detection_batches set latest_bar_at = ?
        where symbol = '600000.SH' and timeframe = '5m'
          and as_of_date = '2026-08-20'
        """,
        [second_timestamp + timedelta(minutes=5)],
    )
    third_close = builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )

    assert (first_close, second_close, third_close) == (10.5, 11.0, 11.0)
    assert detections == [ZONE_RULE_VERSION] * 3
    latest_bar_epoch = database.connection.execute(
        """
        select epoch(latest_bar_at) from zone_detection_batches
        where symbol = '600000.SH' and timeframe = '5m'
          and as_of_date = '2026-08-20'
        """
    ).fetchone()[0]
    assert latest_bar_epoch == second_timestamp.timestamp()


def test_same_timestamp_bar_revision_rebuilds_chart_zones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "same-timestamp-revision.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "same-timestamp-revision-bars")
    timestamp = datetime(2026, 8, 20, 9, 35, tzinfo=TZ)

    def write(close: float) -> None:
        bar_store.upsert(
            [
                Bar(
                    symbol="600000.SH",
                    timestamp=timestamp,
                    timeframe=Timeframe.MIN_5,
                    open=close,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                    volume_shares=1_000,
                    amount_cny=10_000,
                    adjustment=Adjustment.QFQ,
                    source="test",
                )
            ]
        )

    detections = []

    def detect_latest_close(frame, as_of: date, **kwargs) -> list[PriceZone]:
        center = float(frame.iloc[-1]["close"])
        detections.append(center)
        return [
            PriceZone(
                as_of_date=as_of,
                zone_kind="support",
                geometry="horizontal",
                lower_price=center - 0.1,
                center_price=center,
                upper_price=center + 0.1,
                slope=None,
                intercept=None,
                anchors=((as_of, center),),
                strength=0.8,
                touches=2,
                rule_version=kwargs["rule_version"],
            )
        ]

    monkeypatch.setattr(builder_module, "detect_zones", detect_latest_close)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)
    write(10.0)
    builder.ensure_chart_zones("600000.SH", Timeframe.MIN_5, timestamp.date())
    write(11.0)
    builder.ensure_chart_zones("600000.SH", Timeframe.MIN_5, timestamp.date())

    assert detections == [10.0, 11.0]
    assert [
        row["center_price"]
        for row in chart_zones(
            database.connection,
            "600000.SH",
            Timeframe.MIN_5,
            timestamp.date(),
            close_override=11.0,
        )
    ] == [11.0]


def test_backfilled_earlier_bar_rebuilds_chart_zones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "backfilled-revision.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "backfilled-revision-bars")

    def bar(year: int) -> Bar:
        return Bar(
            symbol="600000.SH",
            timestamp=datetime(year, 8, 20, 9, 35, tzinfo=TZ),
            timeframe=Timeframe.MIN_5,
            open=10,
            high=10.5,
            low=9.5,
            close=10,
            volume_shares=1_000,
            amount_cny=10_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )

    detections = []

    def detect_empty(*_args, **_kwargs) -> list[PriceZone]:
        detections.append(1)
        return []

    monkeypatch.setattr(builder_module, "detect_zones", detect_empty)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)
    bar_store.upsert([bar(2026)])
    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    bar_store.upsert([bar(2025)])
    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )

    assert len(detections) == 2


def test_future_year_bar_does_not_rebuild_historical_chart_zones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "future-revision.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "future-revision-bars")

    def bar(year: int) -> Bar:
        return Bar(
            symbol="600000.SH",
            timestamp=datetime(year, 8, 20, 9, 35, tzinfo=TZ),
            timeframe=Timeframe.MIN_5,
            open=10,
            high=10.5,
            low=9.5,
            close=10,
            volume_shares=1_000,
            amount_cny=10_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )

    detections = []

    def detect_empty(*_args, **_kwargs) -> list[PriceZone]:
        detections.append(1)
        return []

    monkeypatch.setattr(builder_module, "detect_zones", detect_empty)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)
    bar_store.upsert([bar(2026)])
    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    bar_store.upsert([bar(2027)])
    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )

    assert len(detections) == 1


def test_historical_chart_zone_request_builds_its_own_batch_after_future_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "historical-after-future.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "historical-after-future-bars")
    bar_store.upsert(
        [
            Bar(
                symbol="600000.SH",
                timestamp=datetime(2026, 8, day, 9, 35, tzinfo=TZ),
                timeframe=Timeframe.MIN_5,
                open=close,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
            for day, close in ((19, 10.0), (20, 11.0))
        ]
    )
    detections = []

    def detect_for_date(_frame, as_of: date, **kwargs) -> list[PriceZone]:
        detections.append(as_of)
        center = float(as_of.day)
        return [
            PriceZone(
                as_of_date=as_of,
                zone_kind="support",
                geometry="horizontal",
                lower_price=center - 0.1,
                center_price=center,
                upper_price=center + 0.1,
                slope=None,
                intercept=None,
                anchors=((as_of, center),),
                strength=0.8,
                touches=2,
                rule_version=kwargs.get("rule_version", "v1"),
            )
        ]

    monkeypatch.setattr(builder_module, "detect_zones", detect_for_date)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)

    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 19)
    )

    assert detections == [date(2026, 8, 20), date(2026, 8, 19)]
    assert database.connection.execute(
        """
        select as_of_date from zone_detection_batches
        where symbol = '600000.SH' and timeframe = '5m' order by as_of_date
        """
    ).fetchall() == [(date(2026, 8, 19),), (date(2026, 8, 20),)]
    historical = chart_zones(
        database.connection,
        "600000.SH",
        Timeframe.MIN_5,
        date(2026, 8, 19),
        close_override=19.0,
    )
    assert [(row["as_of_date"], row["center_price"]) for row in historical] == [
        (date(2026, 8, 19), 19.0)
    ]


def test_fresh_chart_zone_batch_does_not_read_full_bar_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "fresh-fast-path.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "fresh-fast-path-bars")
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
            )
        ]
    )
    replace_auto_zones(
        database.connection,
        "600000.SH",
        Timeframe.MIN_5,
        date(2026, 8, 20),
        [],
        rule_version=ZONE_RULE_VERSION,
        latest_bar_at=timestamp,
        source_revision=bar_store.revision(
            "600000.SH", Timeframe.MIN_5, timestamp.date()
        ),
    )

    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("fresh chart zones must not read full bar history")

    monkeypatch.setattr(bar_store, "read", unexpected_read)
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)

    assert (
        builder.ensure_chart_zones(
            "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
        )
        == 10.5
    )


def test_current_zone_rule_version_rebuilds_an_older_rule_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "rule-version-refresh.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "rule-version-refresh-bars")
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
    detected_versions = []

    def detect_versioned(_frame, as_of: date, **kwargs) -> list[PriceZone]:
        version = kwargs.get("rule_version", "v1")
        detected_versions.append(version)
        return [
            PriceZone(
                as_of_date=as_of,
                zone_kind="support",
                geometry="horizontal",
                lower_price=9.8,
                center_price=10,
                upper_price=10.2,
                slope=None,
                intercept=None,
                anchors=((as_of, 10),),
                strength=0.8,
                touches=1,
                rule_version=version,
            )
        ]

    monkeypatch.setattr(builder_module, "detect_zones", detect_versioned)
    monkeypatch.setattr(builder_module, "ZONE_RULE_VERSION", "v1")
    builder = FeatureBuilder(bar_store, MarketFeatureStore(database), database)
    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )
    monkeypatch.setattr(builder_module, "ZONE_RULE_VERSION", "v2", raising=False)

    builder.ensure_chart_zones(
        "600000.SH", Timeframe.MIN_5, as_of=date(2026, 8, 20)
    )

    assert detected_versions == ["v1", "v2"]
    assert database.connection.execute(
        """
        select rule_version from zone_detection_batches
        where symbol = '600000.SH' and timeframe = '5m'
          and as_of_date = '2026-08-20'
        """
    ).fetchall() == [("v2",)]
    assert database.connection.execute(
        """
        select distinct rule_version from support_resistance_zones
        where symbol = '600000.SH' and timeframe = '5m'
          and as_of_date = '2026-08-20' and source = 'auto'
        """
    ).fetchall() == [("v2",)]
