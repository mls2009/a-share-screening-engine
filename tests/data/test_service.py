from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock.data.service import DataQualityError, MarketDataService
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security
from astock.storage.bars import BarStore
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")
START = date(2026, 8, 20)
END = date(2026, 8, 20)


class FakeCalendar:
    def open_dates(self, start: date, end: date) -> set[date]:
        return {START}


class FakeHistory:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.calls: list[tuple] = []

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> list[Bar]:
        self.calls.append((symbol, timeframe, start, end, adjustment))
        return self.bars


class FakeReference:
    detail_calls = 0
    def trading_dates(self, start: date, end: date) -> set[date]:
        return {START}

    def symbols_on(self, on_date: date) -> list[dict]:
        return [
            {
                "symbol": "600519.SH",
                "name": "贵州茅台",
                "trade_status": "1",
                "source": "baostock",
            }
        ]

    def securities_on(self, on_date: date) -> list[Security]:
        return [
            Security(
                symbol="600519.SH",
                name="贵州茅台",
                exchange="SH",
                board="main",
                listed_on=date(2001, 8, 27),
                is_listed=True,
                is_suspended=False,
            )
        ]

    def adjustment_factors(self, symbol: str, start: date, end: date) -> list[dict]:
        self.detail_calls += 1
        return [
            {
                "symbol": symbol,
                "trade_date": START,
                "forward_factor": 0.5,
                "backward_factor": 2.0,
                "source": "baostock",
            }
        ]

    def corporate_actions(self, symbol: str, start: date, end: date) -> list[dict]:
        self.detail_calls += 1
        return [
            {
                "symbol": symbol,
                "ex_date": START,
                "cash_per_share": 1.0,
                "share_ratio": 0.1,
                "source": "baostock",
            }
        ]

    def security_status(self, symbol: str, start: date, end: date) -> list[dict]:
        self.detail_calls += 1
        return [
            {
                "symbol": symbol,
                "trade_date": START,
                "board": "main",
                "is_st": False,
                "is_suspended": False,
                "previous_close": 10.0,
                "limit_up": 11.0,
                "limit_down": 9.0,
            }
        ]


def _bar(minute: int) -> Bar:
    return Bar(
        symbol="600519.SH",
        timestamp=datetime(2026, 8, 20, 9, minute, tzinfo=TZ),
        timeframe=Timeframe.MIN_5,
        open=10,
        high=11,
        low=9,
        close=10,
        volume_shares=100,
        amount_cny=1_000,
        source="fake",
    )


def _service(tmp_path: Path, history: FakeHistory) -> MarketDataService:
    database = Database(tmp_path / "service.duckdb")
    database.migrate()
    return MarketDataService(
        history_provider=history,
        bar_store=BarStore(tmp_path / "bars"),
        database=database,
        calendar=FakeCalendar(),
    )


def test_history_downloads_once_and_derives_fifteen_minutes(tmp_path: Path) -> None:
    provider = FakeHistory([_bar(35), _bar(40), _bar(45)])
    service = _service(tmp_path, provider)

    first = service.history("600519.SH", Timeframe.MIN_15, START, END)
    second = service.history("600519.SH", Timeframe.MIN_15, START, END)

    assert first == second
    assert len(first) == 1
    assert first[0].timestamp == datetime(2026, 8, 20, 9, 45, tzinfo=TZ)
    assert first[0].volume_shares == 300
    assert provider.calls == [
        ("600519.SH", Timeframe.MIN_5, START, END, Adjustment.NONE)
    ]


def test_history_rejects_bar_outside_trading_session(tmp_path: Path) -> None:
    invalid = _bar(35).model_copy(update={"timestamp": datetime(2026, 8, 20, 12, tzinfo=TZ)})
    service = _service(tmp_path, FakeHistory([invalid]))

    with pytest.raises(DataQualityError) as error:
        service.history("600519.SH", Timeframe.MIN_5, START, END)

    assert [issue.code for issue in error.value.issues] == ["invalid_session_time"]


def test_sync_reference_persists_realistic_backtest_inputs(tmp_path: Path) -> None:
    database = Database(tmp_path / "reference.duckdb")
    database.migrate()
    service = MarketDataService(
        history_provider=FakeHistory([]),
        bar_store=BarStore(tmp_path / "bars"),
        database=database,
        calendar=FakeCalendar(),
        reference_provider=FakeReference(),
    )

    service.sync_reference(["600519.SH"], START, END)

    assert database.connection.execute("select count(*) from trading_calendar").fetchone()[0] == 1
    assert database.connection.execute("select count(*) from symbols").fetchone()[0] == 1
    assert database.connection.execute("select count(*) from adjustment_factors").fetchone()[0] == 1
    assert database.connection.execute("select count(*) from corporate_actions").fetchone()[0] == 1
    assert database.connection.execute("select count(*) from security_status").fetchone()[0] == 1
    assert database.connection.execute(
        "select board, listed_on, is_listed from symbols where symbol = '600519.SH'"
    ).fetchone() == ("main", date(2001, 8, 27), True)


def test_sync_universe_is_lightweight_and_skips_per_symbol_reference_calls(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "universe.duckdb")
    database.migrate()
    reference = FakeReference()
    reference.detail_calls = 0
    service = MarketDataService(
        history_provider=FakeHistory([]),
        bar_store=BarStore(tmp_path / "bars"),
        database=database,
        reference_provider=reference,
    )

    securities = service.sync_universe(START, END)

    assert [security.symbol for security in securities] == ["600519.SH"]
    assert reference.detail_calls == 0
    assert database.connection.execute("select count(*) from symbols").fetchone()[0] == 1
    assert database.connection.execute("select count(*) from trading_calendar").fetchone()[0] == 1
