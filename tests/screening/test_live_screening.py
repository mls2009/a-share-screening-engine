from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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


def test_live_weekly_condition_cannot_read_same_day_close(tmp_path: Path) -> None:
    database = Database(tmp_path / "weekly-live.duckdb")
    database.migrate()
    database.connection.execute(
        "insert into symbols (symbol, name, exchange, is_listed) "
        "values ('600001.SH', '股票一', 'SH', true)"
    )
    database.connection.execute(
        "insert into market_features (symbol, timeframe, feature_date, feature_version, close) "
        "values ('600001.SH', '1w', '2026-08-14', 'v1', 5), "
        "('600001.SH', '1w', '2026-08-21', 'v1', 50)"
    )
    condition = ConditionNode.model_validate({
        "metric": "close", "timeframe": "1w", "operator": "gt",
        "right": {"kind": "constant", "value": 10, "unit": "price"},
    })
    result = ScreeningService(database, MarketFeatureStore(database), FakeSnapshots()).run(
        condition, as_of=date(2026, 8, 21), mode="live",
    )
    assert result.match_count == 0


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


@pytest.mark.parametrize("as_of", [date(2026, 8, 19), date(2026, 8, 21)])
def test_live_screen_does_not_use_snapshot_from_another_date(tmp_path: Path, as_of) -> None:
    database = Database(tmp_path / "live-date.duckdb")
    database.migrate()
    database.connection.execute(
        "insert into symbols (symbol, name, exchange, is_listed) "
        "values ('600001.SH', '股票一', 'SH', true)"
    )
    condition = ConditionNode.model_validate({
        "metric": "close", "timeframe": "1d", "operator": "gt",
        "right": {"kind": "constant", "value": 0, "unit": "price"},
    })
    service = ScreeningService(database, MarketFeatureStore(database), FakeSnapshots())
    result = service.run(condition, as_of=as_of, mode="live")
    assert result.match_count == 0
    assert result.realtime_covered == 0


def test_live_screen_uses_prior_days_for_volume_average_even_after_close_sync(tmp_path: Path) -> None:
    database = Database(tmp_path / "live-volume.duckdb")
    database.migrate()
    database.connection.execute(
        "insert into symbols (symbol, name, exchange, is_listed) "
        "values ('600001.SH', '股票一', 'SH', true)"
    )
    database.connection.executemany(
        "insert into market_features "
        "(symbol, timeframe, feature_date, feature_version, volume) "
        "values ('600001.SH', '1d', ?, 'v1', ?)",
        [(date(2026, 8, day), 100 if day < 20 else 10000) for day in range(16, 21)],
    )
    condition = ConditionNode.model_validate({
        "metric": "volume_ma_5", "timeframe": "1d", "operator": "eq",
        "right": {"kind": "constant", "value": 120, "unit": "shares"},
    })
    service = ScreeningService(database, MarketFeatureStore(database), FakeSnapshots())
    result = service.run(condition, as_of=date(2026, 8, 20), mode="live")
    assert result.match_count == 1


@pytest.mark.parametrize('metric,unit,threshold', [('pe_ratio','ratio',20), ('pb_ratio','ratio',3), ('total_market_cap','amount',2000000000), ('float_market_cap','amount',1000000000)])
def test_current_valuations_filter_snapshot_and_missing_is_unknown(tmp_path, metric, unit, threshold):
    database = Database(tmp_path / 'valuations.duckdb')
    database.migrate()
    database.connection.executemany("insert into symbols(symbol,name,exchange,is_listed) values (?,?,'SH',true)", [['600001.SH','有估值'], ['600002.SH','无估值']])
    class Valuations:
        def snapshot_many(self, symbols):
            return SnapshotBatchResult(tuple(MarketSnapshot(symbol=symbol, timestamp='2026-08-20T15:00:00+08:00', price=12, volume_shares=100, amount_cny=1200, source='tencent', **({metric: threshold - 1} if symbol == '600001.SH' else {})) for symbol in symbols),len(symbols),0)
    service = ScreeningService(database, MarketFeatureStore(database), Valuations())
    tree = ConditionNode.model_validate({'metric':metric,'timeframe':'1d','operator':'lt','right':{'kind':'constant','value':threshold,'unit':unit}})
    result = service.run(tree, as_of=date(2026,8,20), mode='live')
    assert [match.symbol for match in result.matches] == ['600001.SH']
    assert result.diagnostics['conditions']['root']['unknown'] == 1
    from astock.screening.service import ScreenDefinitionError
    with pytest.raises(ScreenDefinitionError):
        service.run(tree, as_of=date(2026,8,20), mode='close')
