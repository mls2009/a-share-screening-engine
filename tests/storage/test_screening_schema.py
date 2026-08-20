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
        "data_sync_jobs",
        "sync_job_failures",
        "screen_definitions",
        "screen_runs",
        "screen_matches",
    } <= tables
    assert {"board", "is_listed"} <= symbol_columns


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
