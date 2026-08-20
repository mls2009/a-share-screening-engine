from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock.backtest.models import BacktestRequest, FeeSchedule
from astock.backtest.service import BacktestDataError, BacktestService
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.storage.bars import BarStore
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")
CONDITION = {
    "kind": "condition",
    "metric": "return_1",
    "timeframe": "1w",
    "operator": "gt",
    "right": {"kind": "constant", "value": -100, "unit": "percent"},
}


def _daily_bars() -> list[Bar]:
    start = datetime(2026, 8, 3, 15, tzinfo=TZ)
    return [
        Bar(
            symbol="600001.SH",
            timestamp=start + timedelta(days=index),
            timeframe=Timeframe.DAY,
            open=10 + index,
            high=10.5 + index,
            low=9.5 + index,
            close=10 + index,
            volume_shares=1_000_000,
            amount_cny=(10 + index) * 1_000_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for index in range(10)
    ]


def _request(symbol: str = "600001.SH") -> BacktestRequest:
    return BacktestRequest(
        symbols=[symbol],
        timeframe="1w",
        start=date(2026, 8, 3),
        end=date(2026, 8, 15),
        entry_tree=CONDITION,
        exit_tree=CONDITION,
        initial_cash=100_000,
        fees=FeeSchedule.zero(),
    )


def _service(tmp_path: Path) -> tuple[BacktestService, Database, BarStore]:
    database = Database(tmp_path / "backtest.duckdb")
    database.migrate()
    bars = BarStore(tmp_path / "bars")
    return BacktestService(database, bars), database, bars


def test_service_derives_timeframe_runs_and_persists_result(tmp_path: Path) -> None:
    service, database, bars = _service(tmp_path)
    bars.upsert(_daily_bars())

    run = service.run(_request())

    assert run.result.request.timeframe == Timeframe.WEEK
    stored = service.get(run.run_id)
    assert stored is not None
    assert stored.run_id == run.run_id
    assert database.connection.execute("select count(*) from backtest_runs").fetchone()[0] == 1


def test_service_names_every_symbol_with_missing_local_data(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    with pytest.raises(BacktestDataError) as error:
        service.run(_request("000001.SZ"))

    assert error.value.symbols == ["000001.SZ"]
