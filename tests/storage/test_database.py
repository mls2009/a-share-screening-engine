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
