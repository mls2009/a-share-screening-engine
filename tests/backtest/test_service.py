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


def test_service_reads_a_warmup_window_before_the_requested_start(tmp_path: Path) -> None:
    database = Database(tmp_path / "warmup.duckdb")
    database.migrate()

    class RecordingStore:
        call = None

        def read_range(self, symbol, timeframe, adjustment, start, end):
            self.call = (symbol, timeframe, adjustment, start, end)
            return _daily_bars()

    store = RecordingStore()
    BacktestService(database, store).run(_request())  # type: ignore[arg-type]

    assert store.call is not None
    assert store.call[3] < _request().start


def test_service_rejects_data_that_only_covers_warmup(tmp_path: Path) -> None:
    service, database, bars = _service(tmp_path)
    bars.upsert(_daily_bars())
    request = _request().model_copy(update={"start": date(2026, 8, 20),
                                           "end": date(2026, 8, 25)})
    with pytest.raises(BacktestDataError):
        service.run(request)
    assert database.connection.execute("select count(*) from backtest_runs").fetchone()[0] == 0


@pytest.mark.parametrize("raw_available", [True, False])
def test_realistic_adjusted_limits_require_matching_raw_open(tmp_path: Path, raw_available) -> None:
    service, database, store = _service(tmp_path)
    bars = _daily_bars()[:3]
    store.upsert(bars)
    if raw_available:
        store.upsert([bar.model_copy(update={"adjustment": Adjustment.NONE,
            "open": bar.open * 2, "high": bar.high * 2, "low": bar.low * 2,
            "close": bar.close * 2}) for bar in bars])
    database.connection.execute(
        "insert into security_status values (?, ?, 'main', false, false, 20, 22, 18)",
        ["600001.SH", date(2026, 8, 4)],
    )
    condition = {"kind": "condition", "metric": "close", "timeframe": "1d",
                 "operator": "gt", "right": {"kind": "constant", "value": 0, "unit": "price"}}
    request = BacktestRequest(symbols=["600001.SH"], timeframe="1d", start=date(2026, 8, 3),
        end=date(2026, 8, 5), entry_tree=condition, exit_tree=condition,
        initial_cash=100_000, mode="realistic", fees=FeeSchedule.zero())
    if not raw_available:
        with pytest.raises(BacktestDataError, match="未复权开盘价"):
            service.run(request)
        return
    result = service.run(request).result
    assert any("limit_up_no_liquidity" in item for item in result.rejected_orders)
    assert not any(trade.timestamp.date() == date(2026, 8, 4) for trade in result.trades)
    assert any("近似换算" in warning for warning in result.warnings)


@pytest.mark.parametrize("timeframe,signal_day,next_day", [
    (Timeframe.WEEK, date(2026, 4, 30), date(2026, 5, 6)),
    (Timeframe.MONTH, date(2026, 4, 30), date(2026, 5, 6)),
])
def test_period_signal_executes_after_holiday(tmp_path, timeframe, signal_day, next_day) -> None:
    service, database, store = _service(tmp_path)
    source = _daily_bars()[0]
    store.upsert([source.model_copy(update={"timestamp": datetime.combine(day, datetime.min.time(), TZ)})
                  for day in [signal_day, next_day]])
    database.connection.executemany("insert into trading_calendar values (?, ?)",
        [(signal_day + timedelta(days=i), i in [0, 6]) for i in range(7)])
    condition = {"kind": "condition", "metric": "close", "timeframe": timeframe,
                 "operator": "gt", "right": {"kind": "constant", "value": 0, "unit": "price"}}
    request = BacktestRequest(symbols=["600001.SH"], timeframe=timeframe, start=signal_day,
        end=next_day, entry_tree=condition, exit_tree=condition,
        initial_cash=100_000, fees=FeeSchedule.zero())
    result = service.run(request).result
    assert result.trades[0].signal_at.hour == 15
    assert result.trades[0].signal_at.date() == signal_day
    assert result.trades[0].timestamp == datetime(2026, 5, 6, 9, 30, tzinfo=TZ)
