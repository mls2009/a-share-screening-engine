from datetime import date
from pathlib import Path

import pandas as pd

from astock.domain.market import Timeframe
from astock.features.zones import detect_zones, nearest_zones, replace_auto_zones
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
