from datetime import date
from pathlib import Path

from astock.features.store import MarketFeatureStore
from astock.screening.models import ConditionNode
from astock.screening.service import RankSpec, ScreeningService, _live_history_limit
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

    assert service.results(result.run_id, sort_by="close")[0]["symbol"] == "600001.SH"


def test_plain_technical_screen_uses_one_unenriched_batch_read(tmp_path: Path) -> None:
    database = Database(tmp_path / "batch-screen.duckdb")
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
        values (?, '1d', '2026-08-20', 'v1', 10, ?)
        """,
        [["600001.SH", 35], ["600002.SH", 10]],
    )
    store = MarketFeatureStore(database)
    calls: list[tuple] = []
    original = store.read_histories

    def recording_read(*args, **kwargs):
        calls.append((*args[1:], kwargs.get("enrich")))
        return original(*args, **kwargs)

    store.read_histories = recording_read  # type: ignore[method-assign]
    condition = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "return_20",
            "timeframe": "1d",
            "operator": "gte",
            "right": {"kind": "constant", "value": 30, "unit": "percent"},
        }
    )

    result = ScreeningService(database, store).run(condition, date(2026, 8, 20))

    assert [match.symbol for match in result.matches] == ["600001.SH"]
    assert result.matches[0].features["name"] == "股票一"
    assert len(calls) == 1
    assert calls[0][-2:] == (1, False)


def test_live_screen_only_loads_the_longest_window_used_by_the_tree() -> None:
    assert _live_history_limit({"close"}) == 1
    assert _live_history_limit({"return_20", "ma_10"}) == 20
    assert _live_history_limit({"ma_250"}) == 250


def test_historical_universe_and_unknown_diagnostics(tmp_path: Path) -> None:
    import json

    database = Database(tmp_path / "historical.duckdb")
    database.migrate()
    database.connection.executemany(
        """insert into symbols (symbol,name,exchange,board,is_listed,listed_on,delisted_on)
        values (?, ?, 'SH', 'main', ?, ?, ?)""",
        [["600001.SH", "历史退市", False, "2020-01-01", "2026-09-01"],
         ["600002.SH", "未来上市", True, "2026-09-01", None],
         ["600003.SH", "边界退市", False, "2020-01-01", "2026-08-20"],
         ["600004.SH", "旧数据", True, None, None]],
    )
    database.connection.execute("""insert into market_features
        (symbol,timeframe,feature_date,feature_version,close)
        values ('600001.SH','1d','2026-08-20','v1',12)""")
    node = ConditionNode.model_validate({"metric": "close", "timeframe": "1d",
        "operator": "gt", "right": {"kind": "constant", "value": 10, "unit": "price"}})
    result = ScreeningService(database, MarketFeatureStore(database)).run(node, date(2026, 8, 20))
    assert result.universe_size == 2
    assert [m.symbol for m in result.matches] == ["600001.SH"]
    assert result.matches[0].features["name"] == "历史退市"
    assert result.diagnostics["conditions"]["root"]["unknown"] == 1
    assert result.diagnostics["conditions"]["root"]["true"] == 1
    assert result.diagnostics["warnings"]
    saved = database.connection.execute("select diagnostics from screen_runs where run_id=?",
                                        [result.run_id]).fetchone()[0]
    assert json.loads(saved) == result.diagnostics


def test_cross_timeframe_loads_right_history_covering_left_window(tmp_path: Path) -> None:
    database = Database(tmp_path / "cross.duckdb")
    database.migrate()
    database.connection.execute("""insert into symbols (symbol,name,exchange,board,is_listed)
        values ('600001.SH','股票','SH','main',true)""")
    database.connection.executemany("""insert into market_features
        (symbol,timeframe,feature_date,feature_version,close,ma_20)
        values ('600001.SH', ?, ?, 'v1', ?, ?)""",
        [["1mo", "2026-07-31", 11, None], ["1mo", "2026-06-30", 9, None],
         ["1d", "2026-07-31", None, 10], ["1d", "2026-07-30", None, 5],
         ["1d", "2026-06-30", None, 10]])
    node = ConditionNode.model_validate({"metric":"close", "timeframe":"1mo",
        "operator":"crosses_above", "right":{"kind":"metric","metric":"ma_20","timeframe":"1d"}})
    result = ScreeningService(database, MarketFeatureStore(database)).run(node,date(2026,7,31))
    assert result.match_count == 1
