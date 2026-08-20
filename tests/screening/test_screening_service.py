from datetime import date
from pathlib import Path

from astock.features.store import MarketFeatureStore
from astock.screening.models import ConditionNode
from astock.screening.service import RankSpec, ScreeningService
from astock.storage.database import Database


def test_close_screen_ranks_matches_and_persists_full_explanation(tmp_path: Path) -> None:
    database = Database(tmp_path / "screen.duckdb")
    database.migrate()
    database.connection.executemany(
        """
        insert into symbols (symbol, name, exchange, board, is_listed)
        values (?, ?, 'SH', 'main', true)
        """,
        [["600001.SH", "股票一"], ["600002.SH", "股票二"]],
    )
    database.connection.executemany(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, return_20)
        values (?, '1d', ?, 'v1', ?, ?)
        """,
        [
            ["600001.SH", date(2026, 8, 20), 12.0, 35.0],
            ["600002.SH", date(2026, 8, 20), 8.0, 10.0],
        ],
    )
    condition = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "return_20",
            "timeframe": "1d",
            "operator": "gte",
            "right": {"kind": "constant", "value": 30, "unit": "percent"},
        }
    )
    service = ScreeningService(database, MarketFeatureStore(database))

    result = service.run(
        condition,
        as_of=date(2026, 8, 20),
        rank=RankSpec(metric="return_20", direction="desc"),
    )

    assert [match.symbol for match in result.matches] == ["600001.SH"]
    assert result.matches[0].explanation.actual == 35.0
    assert database.connection.execute(
        "select status from screen_runs where run_id = ?", [result.run_id]
    ).fetchone()[0] == "completed"
    assert database.connection.execute(
        "select count(*) from screen_matches where run_id = ?", [result.run_id]
    ).fetchone()[0] == 1
    saved = service.results(result.run_id, limit=10, offset=0)
    assert saved[0]["symbol"] == "600001.SH"
    assert saved[0]["explanation"]["result"] == "true"
