from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import pytest

from astock.domain.market import Timeframe
from astock.features import zones as zones_module
from astock.features.zones import (
    ManualZoneInput,
    PriceZone,
    create_manual_zone,
    delete_zone,
    detect_zones,
    nearest_zones,
    replace_auto_zones,
)
from astock.storage.database import Database


def _frame(closes: list[float], lows: dict[int, float], highs: dict[int, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "open": close - 0.1,
                "high": highs.get(index, close + 0.4),
                "low": lows.get(index, close - 0.4),
                "close": close,
                "volume_shares": 100,
                "amount_cny": 1_000,
            }
            for index, (timestamp, close) in enumerate(
                zip(pd.date_range("2026-01-01", periods=len(closes), freq="B"), closes, strict=True)
            )
        ]
    )


def test_detects_horizontal_support_and_resistance_as_price_zones() -> None:
    frame = _frame(
        [12, 10.5, 12.5, 14.5, 13, 10.4, 12.5, 14.6, 13, 10.3, 12.5, 14.5, 12],
        lows={1: 10.0, 5: 10.1, 9: 9.95},
        highs={3: 15.0, 7: 15.1, 11: 14.95},
    )

    zones = detect_zones(frame, as_of=date(2026, 1, 19), pivot_order=1)

    support = next(
        zone for zone in zones if zone.zone_kind == "support" and zone.geometry == "horizontal"
    )
    resistance = next(
        zone for zone in zones if zone.zone_kind == "resistance" and zone.geometry == "horizontal"
    )
    assert support.lower_price < 10.1 < support.upper_price
    assert resistance.lower_price < 15.0 < resistance.upper_price
    assert support.touches >= 3
    assert support.source == "auto"


@pytest.mark.parametrize("timeframe", [Timeframe.DAY, Timeframe.WEEK, Timeframe.MONTH])
def test_detects_at_most_one_trend_line_per_direction_for_every_timeframe(
    timeframe: Timeframe,
) -> None:
    frame = _frame(
        [12] * 14,
        lows={
            0: 10,
            1: 8,
            2: 11,
            3: 10.5,
            4: 9,
            5: 11.5,
            6: 11,
            7: 10,
            8: 12,
            9: 11.5,
            10: 11,
            11: 12.5,
            12: 13,
            13: 12.5,
        },
        highs={
            0: 13,
            1: 13.5,
            2: 16,
            3: 13,
            4: 13.5,
            5: 15,
            6: 12.5,
            7: 13,
            8: 14,
            9: 12,
            10: 12.5,
            11: 13,
            12: 11.5,
            13: 12,
        },
    )

    zones = detect_zones(
        frame,
        as_of=date(2026, 1, 20),
        timeframe=timeframe,
        pivot_order=1,
    )
    trends = [zone for zone in zones if zone.geometry == "trend"]
    uptrends = [zone for zone in trends if zone.zone_kind == "uptrend"]
    downtrends = [zone for zone in trends if zone.zone_kind == "downtrend"]

    assert len(uptrends) == 1
    assert uptrends[0].slope is not None and uptrends[0].slope > 0
    assert len(downtrends) == 1
    assert downtrends[0].slope is not None and downtrends[0].slope < 0
    assert len(trends) == 2


def test_directional_trends_prefer_recent_valid_windows_over_older_touch_count() -> None:
    frame = _frame(
        [100 + index * 0.01 for index in range(40)],
        lows={1: 95, 4: 96, 7: 97, 10: 98, 13: 99, 28: 94, 34: 98},
        highs={
            2: 105.2,
            5: 104.2,
            8: 103.2,
            11: 102.2,
            14: 101.2,
            29: 106,
            35: 102,
        },
    )

    zones = detect_zones(
        frame,
        as_of=pd.Timestamp(frame.iloc[-1]["timestamp"]).date(),
        timeframe=Timeframe.DAY,
        pivot_order=1,
    )
    trends = [zone for zone in zones if zone.geometry == "trend"]
    uptrends = [zone for zone in trends if zone.zone_kind == "uptrend"]
    downtrends = [zone for zone in trends if zone.zone_kind == "downtrend"]

    assert len(uptrends) == 1
    assert uptrends[0].anchors[-1][0] == pd.Timestamp(frame.iloc[34]["timestamp"]).date()
    assert uptrends[0].touches == 2
    assert len(downtrends) == 1
    assert downtrends[0].anchors[-1][0] == pd.Timestamp(frame.iloc[35]["timestamp"]).date()
    assert downtrends[0].touches == 2
    assert len(trends) == 2


def test_nearly_horizontal_pivots_do_not_create_a_trend_line() -> None:
    frame = _frame(
        [11] * 10,
        lows={
            0: 11,
            1: 10.0,
            2: 11,
            3: 10.8,
            4: 10.1,
            5: 11.1,
            6: 10.9,
            7: 10.2,
            8: 11.2,
            9: 11,
        },
        highs={index: 12 + index * 0.1 for index in range(10)},
    )

    zones = detect_zones(
        frame,
        as_of=date(2026, 1, 14),
        timeframe=Timeframe.MONTH,
        pivot_order=1,
    )

    assert not [zone for zone in zones if zone.geometry == "trend"]


def test_zone_calculation_respects_explicit_as_of_without_future_leakage() -> None:
    frame = _frame(
        [12, 10.5, 12, 14.5, 12, 10.4, 12, 14.6, 12, 30],
        lows={1: 10.0, 5: 10.1},
        highs={3: 15.0, 7: 15.1, 9: 31.0},
    )
    cutoff = date(2026, 1, 12)

    original = detect_zones(frame.iloc[:8], as_of=cutoff, pivot_order=1)
    with_future = detect_zones(frame, as_of=cutoff, pivot_order=1)

    assert original == with_future


def test_persists_auto_zones_and_returns_nearest_support_and_resistance(tmp_path: Path) -> None:
    database = Database(tmp_path / "zones.duckdb")
    database.migrate()
    frame = _frame(
        [12, 10.5, 12.5, 14.5, 13, 10.4, 12.5, 14.6, 13, 10.3, 12.5, 14.5, 12],
        lows={1: 10.0, 5: 10.1, 9: 9.95},
        highs={3: 15.0, 7: 15.1, 11: 14.95},
    )
    as_of = date(2026, 1, 19)
    zones = detect_zones(frame, as_of=as_of, pivot_order=1)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600000.SH', '1d', ?, 'v1', 12)
        """,
        [as_of],
    )

    replace_auto_zones(database.connection, "600000.SH", Timeframe.DAY, as_of, zones)
    nearest = nearest_zones(
        database.connection, "600000.SH", Timeframe.DAY, as_of, limit_each=1
    )

    assert {row["zone_kind"] for row in nearest} == {"support", "resistance"}
    assert all(row["source"] == "auto" for row in nearest)


def test_empty_auto_batch_hides_previous_automatic_zones(tmp_path: Path) -> None:
    database = Database(tmp_path / "empty-auto-batch.duckdb")
    database.migrate()
    previous = date(2026, 8, 19)
    latest = date(2026, 8, 20)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', ?, 'v1', 12)
        """,
        [latest],
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        previous,
        [
            PriceZone(
                as_of_date=previous,
                zone_kind="support",
                geometry="horizontal",
                lower_price=9.8,
                center_price=10,
                upper_price=10.2,
                slope=None,
                intercept=None,
                anchors=((previous, 10),),
                strength=0.8,
                touches=1,
            )
        ],
    )

    replace_auto_zones(
        database.connection, "600001.SH", Timeframe.DAY, latest, []
    )

    assert zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.DAY, latest
    ) == []
    assert database.connection.execute(
        """
        select max(as_of_date) from zone_detection_batches
        where symbol = '600001.SH' and timeframe = '1d'
        """
    ).fetchone() == (latest,)


def test_auto_zone_replacement_rolls_back_rows_and_batch_on_insert_failure(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "auto-zone-rollback.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    original = PriceZone(
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
    )
    replacement = PriceZone(
        as_of_date=as_of,
        zone_kind="resistance",
        geometry="horizontal",
        lower_price=12.8,
        center_price=13,
        upper_price=13.2,
        slope=None,
        intercept=None,
        anchors=((as_of, 13),),
        strength=0.9,
        touches=1,
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        as_of,
        [original],
    )
    tables = {row[0] for row in database.connection.execute("show tables").fetchall()}
    assert "zone_detection_batches" in tables
    batch_before = database.connection.execute(
        """
        select rule_version, created_at from zone_detection_batches
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
        """,
        [as_of],
    ).fetchone()

    class FailingConnection:
        def execute(self, *args, **kwargs):
            return database.connection.execute(*args, **kwargs)

        def executemany(self, *_args, **_kwargs):
            raise RuntimeError("injected zone insert failure")

    with pytest.raises(RuntimeError, match="injected zone insert failure"):
        replace_auto_zones(
            FailingConnection(),  # type: ignore[arg-type]
            "600001.SH",
            Timeframe.DAY,
            as_of,
            [replacement],
        )

    assert database.connection.execute(
        """
        select zone_kind, center_price from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
        """,
        [as_of],
    ).fetchall() == [("support", 10.0)]
    assert database.connection.execute(
        """
        select rule_version, created_at from zone_detection_batches
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
        """,
        [as_of],
    ).fetchone() == batch_before


@pytest.mark.parametrize("invalid_kind", ["as_of", "mixed_version"])
def test_auto_zone_replacement_validates_batch_before_deleting_old_rows(
    tmp_path: Path, invalid_kind: str
) -> None:
    database = Database(tmp_path / f"invalid-{invalid_kind}.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    original = PriceZone(
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
        rule_version="v1",
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        as_of,
        [original],
        rule_version="v1",
    )
    invalid = (
        [replace(original, as_of_date=date(2026, 8, 19))]
        if invalid_kind == "as_of"
        else [original, replace(original, rule_version="v2")]
    )

    with pytest.raises(ValueError):
        replace_auto_zones(
            database.connection,
            "600001.SH",
            Timeframe.DAY,
            as_of,
            invalid,
            rule_version="v1",
        )

    assert database.connection.execute(
        """
        select zone_kind, center_price, rule_version
        from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
        """,
        [as_of],
    ).fetchall() == [("support", 10.0, "v1")]
    assert database.connection.execute(
        """
        select rule_version from zone_detection_batches
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
        """,
        [as_of],
    ).fetchall() == [("v1",)]


def test_auto_zone_replacement_keeps_one_rule_version_per_date(tmp_path: Path) -> None:
    database = Database(tmp_path / "zone-rule-replacement.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    v1 = PriceZone(
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
        rule_version="v1",
    )
    v2 = replace(
        v1,
        lower_price=10.8,
        center_price=11,
        upper_price=11.2,
        rule_version="v2",
    )

    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        as_of,
        [v1],
        rule_version="v1",
        latest_bar_at=datetime(
            2026, 8, 20, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        as_of,
        [v2],
        rule_version="v2",
        latest_bar_at=datetime(
            2026, 8, 20, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
    )

    assert database.connection.execute(
        """
        select rule_version from zone_detection_batches
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
        """,
        [as_of],
    ).fetchall() == [("v2",)]
    assert database.connection.execute(
        """
        select center_price, rule_version from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '1d' and as_of_date = ?
          and source = 'auto'
        """,
        [as_of],
    ).fetchall() == [(11.0, "v2")]


def test_chart_zones_uses_rule_version_recorded_by_latest_batch(tmp_path: Path) -> None:
    database = Database(tmp_path / "latest-batch-rule.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, slope, intercept, strength,
           touches, last_touched_on, source, rule_version)
        values (?, '600001.SH', '5m', ?, ?, 'trend', ?, ?, ?, ?, ?, 0.8, 2,
                ?, 'auto', ?)
        """,
        [
            [
                "00000000-0000-0000-0000-000000000401",
                as_of,
                "downtrend",
                9.8,
                10.0,
                10.2,
                -0.1,
                11.0,
                as_of,
                "v1",
            ],
            [
                "00000000-0000-0000-0000-000000000402",
                as_of,
                "uptrend",
                10.8,
                11.0,
                11.2,
                0.1,
                10.0,
                as_of,
                "v2",
            ],
        ],
    )
    database.connection.execute(
        """
        insert into zone_detection_batches
          (symbol, timeframe, as_of_date, rule_version, latest_bar_at)
        values ('600001.SH', '5m', ?, 'v2', '2026-08-20 01:35:00+00')
        """,
        [as_of],
    )

    rows = zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.MIN_5, as_of
    )

    assert [(row["zone_kind"], row["rule_version"]) for row in rows] == [
        ("uptrend", "v2")
    ]


def test_distance_and_chart_zone_selectors_keep_trends_separate(tmp_path: Path) -> None:
    database = Database(tmp_path / "zone-selectors.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', ?, 'v1', 10)
        """,
        [as_of],
    )
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, slope, intercept, strength,
           touches, last_touched_on, state, source, rule_version)
        values (?, '600001.SH', '1d', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1')
        """,
        [
            ["00000000-0000-0000-0000-000000000101", as_of, "resistance", "horizontal", 9.4, 9.5, 9.6, None, None, 0.8, 3, date(2026, 8, 18), "active", "auto"],
            ["00000000-0000-0000-0000-000000000102", as_of, "support", "horizontal", 8.4, 8.5, 8.6, None, None, 0.9, 5, date(2026, 8, 19), "active", "auto"],
            ["00000000-0000-0000-0000-000000000103", as_of, "support", "horizontal", 10.2, 10.3, 10.4, None, None, 0.7, 2, date(2026, 8, 17), "active", "auto"],
            ["00000000-0000-0000-0000-000000000104", as_of, "resistance", "horizontal", 11.9, 12.0, 12.1, None, None, 0.9, 5, date(2026, 8, 19), "active", "auto"],
            ["00000000-0000-0000-0000-000000000105", as_of, "uptrend", "trend", 10.9, 11.0, 11.1, 0.1, 8.0, 0.3, 2, date(2026, 8, 19), "active", "auto"],
            ["00000000-0000-0000-0000-000000000106", as_of, "uptrend", "trend", 8.9, 9.0, 9.1, 0.1, 7.0, 1.0, 9, date(2026, 8, 18), "active", "auto"],
            ["00000000-0000-0000-0000-000000000107", as_of, "downtrend", "trend", 8.8, 8.9, 9.0, -0.1, 12.0, 0.9, 4, date(2026, 8, 19), "active", "auto"],
            ["00000000-0000-0000-0000-000000000108", as_of, "downtrend", "trend", 8.7, 8.8, 8.9, -0.1, 12.0, 1.0, 3, date(2026, 8, 19), "active", "auto"],
            ["00000000-0000-0000-0000-000000000112", as_of, "downtrend", "trend", 8.6, 8.7, 8.8, -0.1, 12.0, 0.95, 4, date(2026, 8, 19), "active", "auto"],
            ["00000000-0000-0000-0000-000000000109", as_of, "support", "horizontal", 9.8, 9.9, 10.0, None, None, 1.0, 1, date(2026, 8, 20), "active", "manual"],
            ["00000000-0000-0000-0000-000000000110", as_of, "support", "trend", 9.85, 9.95, 10.05, 0.05, 9.0, 1.0, 2, date(2026, 8, 20), "active", "manual"],
            ["00000000-0000-0000-0000-000000000111", as_of, "resistance", "trend", 10.4, 10.5, 10.6, -0.05, 11.0, 1.0, 2, date(2026, 8, 20), "deleted", "manual"],
        ],
    )
    database.connection.executemany(
        """
        insert into zone_deletion_markers
          (marker_id, symbol, timeframe, geometry, lower_price, center_price, upper_price)
        values (?, '600001.SH', '1d', ?, ?, ?, ?)
        """,
        [
            ["00000000-0000-0000-0000-000000000121", "horizontal", 10.2, 10.3, 10.4],
            ["00000000-0000-0000-0000-000000000122", "trend", 9.85, 9.95, 10.05],
        ],
    )

    nearest = nearest_zones(
        database.connection, "600001.SH", Timeframe.DAY, as_of, limit_each=1
    )
    chart = zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.DAY, as_of, limit_each=1
    )

    assert {str(row["zone_id"]) for row in nearest} == {
        "00000000-0000-0000-0000-000000000103",
        "00000000-0000-0000-0000-000000000109",
    }
    assert all(row["geometry"] == "horizontal" for row in nearest)
    assert next(
        row for row in nearest if str(row["zone_id"]).endswith("103")
    )["reappeared"] is True
    assert {str(row["zone_id"]) for row in chart} == {
        "00000000-0000-0000-0000-000000000101",
        "00000000-0000-0000-0000-000000000103",
        "00000000-0000-0000-0000-000000000105",
        "00000000-0000-0000-0000-000000000112",
        "00000000-0000-0000-0000-000000000109",
        "00000000-0000-0000-0000-000000000110",
    }
    chart_by_id = {str(row["zone_id"]): row for row in chart}
    assert chart_by_id["00000000-0000-0000-0000-000000000101"]["zone_kind"] == "support"
    assert chart_by_id["00000000-0000-0000-0000-000000000103"]["zone_kind"] == "resistance"
    assert chart_by_id["00000000-0000-0000-0000-000000000105"]["zone_kind"] == "uptrend"
    assert chart_by_id["00000000-0000-0000-0000-000000000112"]["zone_kind"] == "downtrend"
    assert chart_by_id["00000000-0000-0000-0000-000000000103"]["reappeared"] is True
    assert chart_by_id["00000000-0000-0000-0000-000000000110"]["reappeared"] is True


@pytest.mark.parametrize("close_state", ["missing", "null"])
def test_chart_zones_returns_trends_without_a_non_null_close(
    tmp_path: Path, close_state: str
) -> None:
    database = Database(tmp_path / f"zones-with-{close_state}-close.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    if close_state == "null":
        database.connection.execute(
            """
            insert into market_features
              (symbol, timeframe, feature_date, feature_version, close)
            values ('600001.SH', '1d', ?, 'v1', null)
            """,
            [as_of],
        )
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, slope, intercept, strength,
           touches, last_touched_on, source, rule_version)
        values (?, '600001.SH', '1d', ?, ?, 'trend', ?, ?, ?, ?, ?, 0.8, 3,
                ?, ?, 'v1')
        """,
        [
            ["00000000-0000-0000-0000-000000000131", as_of, "support", 9.8, 10.0, 10.2, 0.1, 8.0, as_of, "manual"],
            ["00000000-0000-0000-0000-000000000132", as_of, "uptrend", 10.8, 11.0, 11.2, 0.1, 9.0, as_of, "auto"],
        ],
    )

    chart = zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.DAY, as_of, limit_each=1
    )

    assert {str(row["zone_id"]) for row in chart} == {
        "00000000-0000-0000-0000-000000000131",
        "00000000-0000-0000-0000-000000000132",
    }
    assert nearest_zones(
        database.connection, "600001.SH", Timeframe.DAY, as_of, limit_each=1
    ) == []


def test_chart_zones_breaks_fully_tied_auto_trends_by_zone_id(tmp_path: Path) -> None:
    database = Database(tmp_path / "tied-chart-trends.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', ?, 'v1', 10)
        """,
        [as_of],
    )
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, slope, intercept, strength,
           touches, last_touched_on, source, rule_version)
        values (?, '600001.SH', '1d', ?, 'uptrend', 'trend', 10.8, 11, 11.2,
                0.1, 9, 0.8, 3, ?, 'auto', 'v1')
        """,
        [
            ["00000000-0000-0000-0000-000000000141", as_of, as_of],
            ["00000000-0000-0000-0000-000000000142", as_of, as_of],
        ],
    )

    chart = zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.DAY, as_of
    )

    assert [str(row["zone_id"]) for row in chart] == [
        "00000000-0000-0000-0000-000000000142"
    ]


def test_manual_zone_survives_auto_replacement_and_can_be_deleted(tmp_path: Path) -> None:
    database = Database(tmp_path / "manual-zones.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', ?, 'v1', 12)
        """,
        [as_of],
    )
    zone_id = create_manual_zone(
        database.connection,
        "600001.SH",
        ManualZoneInput(
            timeframe=Timeframe.DAY,
            as_of_date=as_of,
            zone_kind="support",
            geometry="trend",
            lower_price=10.0,
            center_price=10.1,
            upper_price=10.2,
            slope=0.05,
            intercept=9.5,
            anchors=((date(2026, 8, 1), 9.8), (date(2026, 8, 20), 10.1)),
        ),
    )

    replace_auto_zones(database.connection, "600001.SH", Timeframe.DAY, as_of, [])
    rows = zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.DAY, as_of
    )

    assert len(rows) == 1
    assert rows[0]["zone_id"] == zone_id
    assert rows[0]["source"] == "manual"
    assert delete_zone(database.connection, "600001.SH", zone_id) is True
    assert delete_zone(database.connection, "600001.SH", zone_id) is False


def test_delete_zone_persists_marker_for_automatic_line_and_checks_owner(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "deleted-zones.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    zone_id = "00000000-0000-0000-0000-000000000011"
    database.connection.execute(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, strength, touches, source,
           rule_version)
        values (?, '600001.SH', '1d', ?, 'support', 'horizontal',
                9.8, 10, 10.2, 0.8, 3, 'auto', 'v1')
        """,
        [zone_id, as_of],
    )

    assert delete_zone(database.connection, "000001.SZ", zone_id) is False
    assert database.connection.execute(
        "select count(*) from zone_deletion_markers"
    ).fetchone() == (0,)

    assert delete_zone(database.connection, "600001.SH", zone_id) is True
    assert database.connection.execute(
        """
        select count(*) from support_resistance_zones
        where zone_id = ? and state = 'active'
        """,
        [zone_id],
    ).fetchone() == (0,)
    assert database.connection.execute(
        "select state from support_resistance_zones where zone_id = ?", [zone_id]
    ).fetchone() == ("deleted",)
    assert database.connection.execute(
        """
        select symbol, timeframe, geometry, lower_price, center_price, upper_price
        from zone_deletion_markers
        """
    ).fetchone() == ("600001.SH", "1d", "horizontal", 9.8, 10.0, 10.2)


def test_concurrent_delete_claims_zone_once_and_persists_one_marker(
    tmp_path: Path,
) -> None:
    path = tmp_path / "concurrent-delete.duckdb"
    database = Database(path)
    database.migrate()
    zone_id = "00000000-0000-0000-0000-000000000012"
    database.connection.execute(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, strength, touches, source,
           rule_version)
        values (?, '600001.SH', '1d', '2026-08-20', 'support', 'horizontal',
                9.8, 10, 10.2, 0.8, 3, 'auto', 'v1')
        """,
        [zone_id],
    )
    database.connection.close()

    start = Barrier(2)

    def remove(connection: duckdb.DuckDBPyConnection) -> bool:
        start.wait(timeout=5)
        return delete_zone(connection, "600001.SH", zone_id)

    connections = [duckdb.connect(str(path)), duckdb.connect(str(path))]
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(remove, connections))
        assert sorted(results) == [False, True]
        assert connections[0].execute(
            "select count(*) from zone_deletion_markers"
        ).fetchone() == (1,)
    finally:
        for connection in connections:
            connection.close()


def test_deleting_only_latest_automatic_zone_does_not_reveal_previous_batch(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "zone-batches.duckdb")
    database.migrate()
    latest = date(2026, 8, 20)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', ?, 'v1', 12)
        """,
        [latest],
    )
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, strength, touches, source,
           rule_version)
        values (?, '600001.SH', '1d', ?, 'support', 'horizontal',
                9.8, 10, 10.2, 0.8, 3, 'auto', 'v1')
        """,
        [
            ["00000000-0000-0000-0000-000000000031", date(2026, 8, 19)],
            ["00000000-0000-0000-0000-000000000032", latest],
        ],
    )

    assert delete_zone(
        database.connection,
        "600001.SH",
        "00000000-0000-0000-0000-000000000032",
    ) is True

    assert nearest_zones(
        database.connection, "600001.SH", Timeframe.DAY, latest, limit_each=20
    ) == []
    assert zones_module.chart_zones(
        database.connection, "600001.SH", Timeframe.DAY, latest, limit_each=20
    ) == []


def test_nearest_zones_converts_automatic_roles_but_preserves_manual_choice(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "role-conversion.duckdb")
    database.migrate()
    as_of = date(2026, 8, 20)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1w', ?, 'v1', 10)
        """,
        [as_of],
    )
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, strength, touches, source,
           rule_version)
        values (?, '600001.SH', '1w', ?, ?, 'horizontal', ?, ?, ?, 0.8, 3, ?, 'v1')
        """,
        [
            ["00000000-0000-0000-0000-000000000001", as_of, "support", 11.9, 12, 12.1, "auto"],
            ["00000000-0000-0000-0000-000000000002", as_of, "resistance", 7.9, 8, 8.1, "auto"],
            ["00000000-0000-0000-0000-000000000003", as_of, "support", 10.9, 11, 11.1, "manual"],
        ],
    )
    database.connection.executemany(
        """
        insert into zone_deletion_markers
          (marker_id, symbol, timeframe, geometry, lower_price, center_price, upper_price)
        values (?, '600001.SH', '1w', ?, ?, ?, ?)
        """,
        [
            ["00000000-0000-0000-0000-000000000021", "horizontal", 11.9, 12, 12.1],
            ["00000000-0000-0000-0000-000000000022", "trend", 10.9, 11, 11.1],
        ],
    )

    rows = nearest_zones(
        database.connection, "600001.SH", Timeframe.WEEK, as_of, limit_each=10
    )
    roles = {str(row["zone_id"]): row["zone_kind"] for row in rows}
    reappeared = {str(row["zone_id"]): row["reappeared"] for row in rows}

    assert roles["00000000-0000-0000-0000-000000000001"] == "resistance"
    assert roles["00000000-0000-0000-0000-000000000002"] == "support"
    assert roles["00000000-0000-0000-0000-000000000003"] == "support"
    assert reappeared["00000000-0000-0000-0000-000000000001"] is True
    assert reappeared["00000000-0000-0000-0000-000000000002"] is False
    assert reappeared["00000000-0000-0000-0000-000000000003"] is False
