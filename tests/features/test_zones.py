from datetime import date
from pathlib import Path

import pandas as pd

from astock.domain.market import Timeframe
from astock.features.zones import (
    ManualZoneInput,
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


def test_detects_rising_trend_support_from_multiple_pivot_anchors() -> None:
    frame = _frame(
        [11, 8.5, 11, 12, 9.5, 12, 13, 10.5, 13, 14],
        lows={1: 8.0, 4: 9.0, 7: 10.0},
        highs={},
    )

    zones = detect_zones(frame, as_of=date(2026, 1, 14), pivot_order=1)

    trend = next(
        zone for zone in zones if zone.zone_kind == "support" and zone.geometry == "trend"
    )
    assert trend.slope is not None and trend.slope > 0
    assert len(trend.anchors) >= 2


def test_daily_trend_selection_returns_support_and_resistance_when_strict_fit_misses_one() -> None:
    frame = _frame(
        [13, 9, 14, 10, 13, 11, 12.5, 12, 12, 13, 13.2, 13.8, 13.5, 13.2, 13.8, 13.1],
        lows={1: 8, 4: 9, 7: 10.5, 10: 12.5, 13: 12.8},
        highs={2: 16, 5: 15, 8: 13, 11: 15, 14: 14.2},
    )
    as_of = date(2026, 1, 22)

    strict = detect_zones(frame, as_of=as_of, pivot_order=1)
    daily = detect_zones(
        frame, as_of=as_of, timeframe=Timeframe.DAY, pivot_order=1
    )
    weekly = detect_zones(
        frame, as_of=as_of, timeframe=Timeframe.WEEK, pivot_order=1
    )

    strict_trends = [zone for zone in strict if zone.geometry == "trend"]
    daily_trends = [zone for zone in daily if zone.geometry == "trend"]
    assert {zone.zone_kind for zone in strict_trends} != {"support", "resistance"}
    assert {zone.zone_kind for zone in daily_trends} == {"support", "resistance"}
    assert next(
        zone.center_price for zone in daily_trends if zone.zone_kind == "support"
    ) < frame.iloc[-1]["close"]
    assert next(
        zone.center_price for zone in daily_trends if zone.zone_kind == "resistance"
    ) > frame.iloc[-1]["close"]
    assert weekly == strict


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
    rows = nearest_zones(database.connection, "600001.SH", Timeframe.DAY, as_of)

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
        "select count(*) from support_resistance_zones where zone_id = ?", [zone_id]
    ).fetchone() == (0,)
    assert database.connection.execute(
        """
        select symbol, timeframe, geometry, lower_price, center_price, upper_price
        from zone_deletion_markers
        """
    ).fetchone() == ("600001.SH", "1d", "horizontal", 9.8, 10.0, 10.2)


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
