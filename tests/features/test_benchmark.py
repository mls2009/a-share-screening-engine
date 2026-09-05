from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features.benchmark import BenchmarkDataError, BenchmarkService
from astock.storage.bars import BarStore
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")
START = date(2026, 8, 19)
END = date(2026, 8, 20)


def make_bar(
    symbol: str,
    day: int,
    close: float,
    adjustment: Adjustment,
    timeframe: Timeframe = Timeframe.DAY,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 8, day, 15, tzinfo=TZ),
        timeframe=timeframe,
        open=close,
        high=close,
        low=close,
        close=close,
        volume_shares=1_000,
        amount_cny=close * 1_000,
        adjustment=adjustment,
        source="test",
    )


def make_service(tmp_path: Path) -> tuple[BenchmarkService, Database, BarStore]:
    database = Database(tmp_path / "benchmark.duckdb")
    database.migrate()
    database.connection.executemany(
        """
        insert into symbols
          (symbol, name, exchange, board, instrument_type, is_listed)
        values (?, ?, ?, ?, ?, true)
        """,
        [
            ["600001.SH", "沪市股票", "SH", "main", "stock"],
            ["000001.SZ", "深市股票", "SZ", "main", "stock"],
            ["300001.SZ", "创业板股票", "SZ", "chinext", "stock"],
            ["688001.SH", "科创板股票", "SH", "star", "stock"],
            ["920001.BJ", "北交所股票", "BJ", "beijing", "stock"],
            ["159558.SZ", "深市ETF", "SZ", "main", "etf"],
            ["510300.SH", "沪市ETF", "SH", "main", "etf"],
        ],
    )
    store = BarStore(tmp_path / "bars")
    return BenchmarkService(database, store), database, store


def test_benchmark_mapping_uses_board_and_etf_exchange(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)

    assert service.benchmark_for("600001.SH").symbol == "000001.SH"
    assert service.benchmark_for("000001.SZ").symbol == "399001.SZ"
    assert service.benchmark_for("300001.SZ").symbol == "399006.SZ"
    assert service.benchmark_for("688001.SH").symbol == "000688.SH"
    assert service.benchmark_for("920001.BJ").symbol == "899050.BJ"
    assert service.benchmark_for("159558.SZ").symbol == "399001.SZ"
    assert service.benchmark_for("510300.SH").symbol == "000001.SH"


def test_comparison_aligns_common_timestamps_and_normalizes_returns(
    tmp_path: Path,
) -> None:
    service, _, store = make_service(tmp_path)
    store.upsert([
        make_bar("600001.SH", 19, 10, Adjustment.QFQ),
        make_bar("600001.SH", 20, 11, Adjustment.QFQ),
        make_bar("000001.SH", 18, 2_900, Adjustment.NONE),
        make_bar("000001.SH", 19, 3_000, Adjustment.NONE),
        make_bar("000001.SH", 20, 3_150, Adjustment.NONE),
    ])

    result = service.compare("600001.SH", Timeframe.DAY, START, END)

    assert result.stock_name == "沪市股票"
    assert result.benchmark_name == "上证指数"
    assert [point.timestamp.day for point in result.points] == [19, 20]
    assert result.points[0].stock_return_pct == 0
    assert result.points[0].benchmark_return_pct == 0
    assert result.points[1].stock_return_pct == pytest.approx(10)
    assert result.points[1].benchmark_return_pct == pytest.approx(5)
    assert result.points[1].relative_pct == pytest.approx(5)


@pytest.mark.parametrize(
    ("stock", "benchmark", "code"),
    [
        ([], [make_bar("000001.SH", 19, 3_000, Adjustment.NONE)], "stock_data_missing"),
        ([make_bar("600001.SH", 19, 10, Adjustment.QFQ)], [], "benchmark_data_missing"),
        (
            [make_bar("600001.SH", 19, 10, Adjustment.QFQ)],
            [make_bar("000001.SH", 20, 3_000, Adjustment.NONE)],
            "no_aligned_data",
        ),
    ],
)
def test_comparison_reports_distinct_missing_data_errors(
    tmp_path: Path,
    stock: list[Bar],
    benchmark: list[Bar],
    code: str,
) -> None:
    service, _, store = make_service(tmp_path)
    store.upsert([*stock, *benchmark])

    with pytest.raises(BenchmarkDataError) as error:
        service.compare("600001.SH", Timeframe.DAY, START, END)

    assert error.value.code == code


class FakeStockMarketData:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.calls: list[tuple] = []

    def history(self, *args):
        self.calls.append(args)
        return self.bars


class FakeIndexProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.calls: list[tuple] = []

    def index_history(self, *args):
        self.calls.append(args)
        return self.bars


def test_sync_uses_base_timeframes_and_saves_index_bars(tmp_path: Path) -> None:
    _, database, store = make_service(tmp_path)
    stock_bar = make_bar(
        "600001.SH", 20, 10, Adjustment.QFQ, Timeframe.MIN_5
    )
    index_bar = make_bar(
        "000001.SH", 20, 3_000, Adjustment.NONE, Timeframe.MIN_5
    )
    stock_data = FakeStockMarketData([stock_bar])
    index_provider = FakeIndexProvider([index_bar])
    service = BenchmarkService(database, store, stock_data, index_provider)

    result = service.sync(
        "600001.SH", Timeframe.MIN_15, END, END, include_benchmark=True
    )

    assert stock_data.calls == [
        ("600001.SH", Timeframe.MIN_5, END, END, Adjustment.QFQ)
    ]
    assert index_provider.calls == [
        ("000001.SH", Timeframe.MIN_5, END, END)
    ]
    assert result == {"stock_bars": 1, "benchmark_bars": 1}
    assert store.read("000001.SH", Timeframe.MIN_5, Adjustment.NONE) == [index_bar]


def test_sync_reports_unavailable_historical_minute_index(tmp_path: Path) -> None:
    _, database, store = make_service(tmp_path)
    service = BenchmarkService(
        database,
        store,
        FakeStockMarketData([
            make_bar("600001.SH", 20, 10, Adjustment.QFQ, Timeframe.MIN_5)
        ]),
        FakeIndexProvider([]),
    )

    with pytest.raises(BenchmarkDataError) as error:
        service.sync("600001.SH", Timeframe.MIN_5, END, END, include_benchmark=True)

    assert error.value.code == "minute_history_unavailable"


def test_unknown_symbol_has_explicit_error(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)

    with pytest.raises(BenchmarkDataError) as error:
        service.benchmark_for("999999.SH")

    assert error.value.code == "symbol_not_found"
