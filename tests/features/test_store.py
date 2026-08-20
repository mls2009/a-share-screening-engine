import json
from datetime import date
from pathlib import Path

from astock.domain.market import Timeframe
from astock.features.store import MarketFeatureStore
from astock.storage.database import Database


def test_history_expands_extra_and_adds_pattern_and_zone_context(tmp_path: Path) -> None:
    database = Database(tmp_path / "features.duckdb")
    database.migrate()
    database.connection.execute(
        """
        insert into symbols (symbol, name, exchange, listed_on, board, is_listed)
        values ('600001.SH', '测试股份', 'SH', '2020-01-01', 'main', true)
        """
    )
    database.connection.execute(
        """
        insert into security_status
          (symbol, trade_date, board, is_st, is_suspended, previous_close)
        values ('600001.SH', '2026-08-20', 'main', true, false, 11.5)
        """
    )
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, extra)
        values ('600001.SH', '1d', '2026-08-20', 'v1', 12, ?)
        """,
        [json.dumps({"high_20": 13.5, "max_drawdown_20": -8.2, "up_streak": 3})],
    )
    database.connection.execute(
        """
        insert into pattern_events
          (symbol, timeframe, event_date, pattern_type, rule_version, strength)
        values ('600001.SH', '1d', '2026-08-20', 'hammer', 'v1', 0.86)
        """
    )
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (symbol, timeframe, as_of_date, zone_kind, geometry, lower_price,
           center_price, upper_price, strength, touches, source, rule_version)
        values ('600001.SH', '1d', '2026-08-20', ?, 'horizontal', ?, ?, ?, 0.8, 3,
                'auto', 'v1')
        """,
        [
            ["support", 9.8, 10.0, 10.2],
            ["resistance", 14.8, 15.0, 15.2],
        ],
    )

    row = MarketFeatureStore(database).read_history(
        "600001.SH", Timeframe.DAY, date(2026, 8, 20), 1
    )[0]

    assert row["high_20"] == 13.5
    assert row["max_drawdown_20"] == -8.2
    assert row["up_streak"] == 3
    assert row["pattern_type"] == "hammer"
    assert row["pattern_strength"] == 0.86
    assert row["name"] == "测试股份"
    assert row["board"] == "main"
    assert row["is_st"] is True
    assert row["is_suspended"] is False
    assert row["support_distance"] == 16.666666666666664
    assert row["resistance_distance"] == 25.0
