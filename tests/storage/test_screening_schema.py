from datetime import date
from pathlib import Path

from astock.storage.database import Database


def test_screening_schema_contains_required_tables_and_symbol_columns(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.duckdb")
    db.migrate()

    tables = {row[0] for row in db.connection.execute("show tables").fetchall()}
    symbol_columns = {
        row[1]
        for row in db.connection.execute("pragma table_info('symbols')").fetchall()
    }

    assert {
        "market_features",
        "pattern_events",
        "support_resistance_zones",
        "zone_detection_batches",
        "zone_deletion_markers",
        "data_sync_jobs",
        "sync_job_failures",
        "screen_definitions",
        "screen_runs",
        "screen_matches",
    } <= tables
    assert {"board", "is_listed"} <= symbol_columns


def test_migration_backfills_existing_automatic_zone_batches(tmp_path: Path) -> None:
    db = Database(tmp_path / "legacy-zones.duckdb")
    db.migrate()
    db.connection.execute("drop table if exists zone_detection_batches")
    db.connection.execute(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, strength, touches, source,
           rule_version)
        values
          ('00000000-0000-0000-0000-000000000301', '600001.SH', '1d',
           '2026-08-19', 'support', 'horizontal', 9.8, 10, 10.2, 0.8, 3,
           'auto', 'v1'),
          ('00000000-0000-0000-0000-000000000302', '600001.SH', '1d',
           '2026-08-19', 'support', 'horizontal', 8.8, 9, 9.2, 0.7, 2,
           'auto', 'v1'),
          ('00000000-0000-0000-0000-000000000303', '600001.SH', '1d',
           '2026-08-20', 'resistance', 'horizontal', 12.8, 13, 13.2, 0.9, 4,
           'auto', 'v2'),
          ('00000000-0000-0000-0000-000000000304', '600001.SH', '1d',
           '2026-08-20', 'support', 'horizontal', 10.8, 11, 11.2, 1, 1,
           'manual', 'manual-v1')
        """
    )

    db.migrate()

    assert "zone_detection_batches" in {
        row[0] for row in db.connection.execute("show tables").fetchall()
    }
    assert db.connection.execute(
        """
        select symbol, timeframe, as_of_date, rule_version
        from zone_detection_batches order by as_of_date
        """
    ).fetchall() == [
        ("600001.SH", "1d", date(2026, 8, 19), "v1"),
        ("600001.SH", "1d", date(2026, 8, 20), "v2"),
    ]


def test_migration_upgrades_an_existing_symbols_table(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.duckdb")
    db.connection.execute(
        "create table symbols (symbol varchar primary key, name varchar not null, "
        "exchange varchar not null, listed_on date, delisted_on date)"
    )

    db.migrate()

    columns = {
        row[1]
        for row in db.connection.execute("pragma table_info('symbols')").fetchall()
    }
    assert {"board", "is_listed"} <= columns
