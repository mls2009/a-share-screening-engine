import json
from datetime import date
from pathlib import Path

import pytest

from astock.domain.market import Timeframe
from astock.features.store import MarketFeatureStore
from astock.storage.database import Database


@pytest.mark.parametrize("method", ["read_latest", "read_history", "read_histories"])
def test_store_ignores_legacy_partial_week_before_applying_limit(tmp_path: Path, method) -> None:
    database = Database(tmp_path / "partial-week.duckdb")
    database.migrate()
    database.connection.executemany(
        "insert into market_features "
        "(symbol, timeframe, feature_date, feature_version, close) "
        "values ('600001.SH', '1w', ?, 'v1', ?)",
        [(date(2026, 8, 14), 10), (date(2026, 8, 18), 11), (date(2026, 8, 20), 12)],
    )
    store = MarketFeatureStore(database)
    if method == "read_latest":
        row = store.read_latest("600001.SH", Timeframe.WEEK, date(2026, 8, 20))
    elif method == "read_history":
        row = store.read_history("600001.SH", Timeframe.WEEK, date(2026, 8, 20), 1)[0]
    else:
        row = store.read_histories(["600001.SH"], Timeframe.WEEK, date(2026, 8, 20), 1)["600001.SH"][0]
    assert row is not None and row["feature_date"] == date(2026, 8, 14)


def test_store_recognizes_holiday_period_close(tmp_path: Path) -> None:
    database = Database(tmp_path / "holiday-week.duckdb")
    database.migrate()
    database.connection.execute(
        "insert into market_features "
        "(symbol, timeframe, feature_date, feature_version, close) "
        "values ('600001.SH', '1w', '2026-09-30', 'v1', 10)"
    )
    database.connection.execute(
        "insert into trading_calendar values "
        "('2026-09-30', true), ('2026-10-01', false), ('2026-10-02', false)"
    )
    rows = MarketFeatureStore(database).read_history(
        "600001.SH", Timeframe.WEEK, date(2026, 9, 30), 1,
    )
    assert len(rows) == 1


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


def test_batch_history_reads_all_symbols_without_optional_enrichment(tmp_path: Path) -> None:
    database = Database(tmp_path / "batch-features.duckdb")
    database.migrate()
    database.connection.executemany(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, return_20, extra)
        values (?, '1d', ?, 'v1', ?, ?, ?)
        """,
        [
            ["600001.SH", date(2026, 8, 19), 10, 20, json.dumps({"up_streak": 1})],
            ["600001.SH", date(2026, 8, 20), 11, 30, json.dumps({"up_streak": 2})],
            ["000001.SZ", date(2026, 8, 20), 12, 40, json.dumps({"up_streak": 3})],
        ],
    )
    store = MarketFeatureStore(database)

    histories = store.read_histories(
        ["600001.SH", "000001.SZ"],
        Timeframe.DAY,
        date(2026, 8, 20),
        1,
        enrich=False,
    )

    assert histories["600001.SH"][0]["feature_date"] == date(2026, 8, 20)
    assert histories["600001.SH"][0]["up_streak"] == 2
    assert histories["000001.SZ"][0]["return_20"] == 40
    assert "pattern_type" not in histories["600001.SH"][0]


def test_history_derives_listing_stage_from_trading_days(tmp_path: Path) -> None:
    database = Database(tmp_path / "listing-stage.duckdb")
    database.migrate()
    database.connection.executemany(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, listing_trade_days)
        values (?, '1d', '2026-08-20', 'v1', ?)
        """,
        [
            ["000001.SZ", 30],
            ["000002.SZ", 31],
            ["000003.SZ", 250],
            ["000004.SZ", 251],
        ],
    )
    store = MarketFeatureStore(database)

    stages = {
        symbol: store.read_history(
            symbol, Timeframe.DAY, date(2026, 8, 20), 1, enrich=False
        )[0]["listing_stage"]
        for symbol in ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")
    }

    assert stages == {
        "000001.SZ": "new",
        "000002.SZ": "secondary_new",
        "000003.SZ": "secondary_new",
        "000004.SZ": "established",
    }


def test_history_exposes_all_patterns_detected_on_the_same_day(tmp_path: Path) -> None:
    database = Database(tmp_path / "multiple-patterns.duckdb")
    database.migrate()
    database.connection.execute(
        """
        insert into symbols (symbol, name, exchange, board, is_listed)
        values ('600001.SH', '测试股份', 'SH', 'main', true)
        """
    )
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', '2026-08-20', 'v1', 12)
        """
    )
    database.connection.executemany(
        """
        insert into pattern_events
          (symbol, timeframe, event_date, pattern_type, rule_version, strength)
        values ('600001.SH', '1d', '2026-08-20', ?, 'v1', ?)
        """,
        [["doji", 0.7], ["hammer", 0.9]],
    )

    row = MarketFeatureStore(database).read_history(
        "600001.SH", Timeframe.DAY, date(2026, 8, 20), 1
    )[0]

    assert row["pattern_type"] == ["hammer", "doji"]
    assert row["pattern_strength"] == 0.9
