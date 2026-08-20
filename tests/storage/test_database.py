from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from astock.storage.database import Database


def test_database_migrates_required_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.duckdb")
    db.migrate()

    names = {row[0] for row in db.connection.execute("show tables").fetchall()}

    assert {
        "symbols",
        "trading_calendar",
        "security_status",
        "bar_coverage",
        "quality_issues",
        "adjustment_factors",
        "corporate_actions",
    } <= names


def test_database_uses_thread_local_connections_for_concurrent_transactions(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "concurrent.duckdb")
    db.migrate()
    db.connection.execute("create table concurrent_rows (value integer primary key)")

    def insert(value: int) -> None:
        connection = db.connection
        connection.execute("begin transaction")
        connection.execute("insert into concurrent_rows values (?)", [value])
        connection.execute("commit")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(insert, range(400)))

    assert db.connection.execute("select count(*) from concurrent_rows").fetchone()[0] == 400
