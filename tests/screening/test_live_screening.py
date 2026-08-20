from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.data.providers.tencent import SnapshotBatchResult
from astock.domain.market import MarketSnapshot
from astock.features.store import MarketFeatureStore
from astock.screening.models import ConditionNode
from astock.screening.service import ScreeningService
from astock.storage.database import Database


class FakeSnapshots:
    def snapshot_many(self, symbols: list[str]) -> SnapshotBatchResult:
        return SnapshotBatchResult(
            snapshots=(
                MarketSnapshot(
                    symbol="600001.SH",
                    timestamp=datetime(
                        2026, 8, 20, 10, tzinfo=ZoneInfo("Asia/Shanghai")
                    ),
                    price=11,
                    previous_close=10,
                    volume_shares=200,
                    amount_cny=2_100,
                    source="tencent",
                ),
            ),
            requested=len(symbols),
            failed_batches=0,
        )


def test_live_screen_uses_snapshots_and_records_coverage_without_changing_close_features(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "live.duckdb")
    database.migrate()
    database.connection.executemany(
        "insert into symbols (symbol, name, exchange, is_listed) values (?, ?, 'SH', true)",
        [["600001.SH", "有行情"], ["600002.SH", "缺行情"]],
    )
    database.connection.executemany(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, return_1)
        values (?, '1d', '2026-08-19', 'v1', 10, 0)
        """,
        [["600001.SH"], ["600002.SH"]],
    )
    condition = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "return_1",
            "timeframe": "1d",
            "operator": "gt",
            "right": {"kind": "constant", "value": 5, "unit": "percent"},
        }
    )
    service = ScreeningService(
        database, MarketFeatureStore(database), snapshot_provider=FakeSnapshots()
    )

    result = service.run(condition, as_of=date(2026, 8, 20), mode="live")

    assert [match.symbol for match in result.matches] == ["600001.SH"]
    assert result.realtime_covered == 1
    assert database.connection.execute(
        "select realtime_covered, failed_batches from screen_runs where run_id = ?",
        [result.run_id],
    ).fetchone() == (1, 0)
    assert database.connection.execute(
        "select close, return_1 from market_features where symbol = '600001.SH'"
    ).fetchone() == (10.0, 0.0)
