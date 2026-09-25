from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features.builder import chart_base_timeframe
from astock.storage.bars import BarStore
from astock.storage.database import Database


class StockMarketData(Protocol):
    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> list[Bar]: ...


class IndexHistoryProvider(Protocol):
    def index_history(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> list[Bar]: ...


class BenchmarkDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    name: str


class ComparisonPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    stock_return_pct: float
    benchmark_return_pct: float
    relative_pct: float
    stock_period_pct: float | None = None
    benchmark_period_pct: float | None = None
    relative_period_pct: float | None = None


class BenchmarkComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: Timeframe = Timeframe.DAY
    stock_symbol: str
    stock_name: str
    benchmark_symbol: str
    benchmark_name: str
    points: list[ComparisonPoint]


class BenchmarkDataError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


BENCHMARKS = {
    "shanghai": BenchmarkDefinition(symbol="000001.SH", name="上证指数"),
    "shenzhen": BenchmarkDefinition(symbol="399001.SZ", name="深证成指"),
    "chinext": BenchmarkDefinition(symbol="399006.SZ", name="创业板指"),
    "star": BenchmarkDefinition(symbol="000688.SH", name="科创50"),
    "beijing": BenchmarkDefinition(symbol="899050.BJ", name="北证50"),
}


class BenchmarkService:
    def __init__(
        self,
        database: Database,
        bar_store: BarStore,
        stock_market_data: StockMarketData | None = None,
        index_provider: IndexHistoryProvider | None = None,
    ) -> None:
        self.database = database
        self.bar_store = bar_store
        self.stock_market_data = stock_market_data
        self.index_provider = index_provider

    def _security(self, symbol: str) -> tuple[str, str, str, str]:
        row = self.database.connection.execute(
            """
            select name, exchange, coalesce(board, 'main'), instrument_type
            from symbols where symbol = ? and is_listed
            """,
            [symbol],
        ).fetchone()
        if row is None:
            raise BenchmarkDataError("symbol_not_found", "未找到对应证券")
        return row

    def benchmark_for(self, symbol: str) -> BenchmarkDefinition:
        _, exchange, board, instrument_type = self._security(symbol)
        if instrument_type == "etf" or board == "main":
            key = "shanghai" if exchange == "SH" else "shenzhen"
        else:
            key = board
        benchmark = BENCHMARKS.get(key)
        if benchmark is None:
            raise BenchmarkDataError("benchmark_not_found", "无法匹配对应大盘指数")
        return benchmark

    @staticmethod
    def _in_window(
        bar: Bar,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> bool:
        if start_at is not None and bar.timestamp <= start_at:
            return False
        return end_at is None or bar.timestamp <= end_at

    def _read(
        self,
        symbol: str,
        timeframe: Timeframe,
        adjustment: Adjustment,
        start: date,
        end: date,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[Bar]:
        base = chart_base_timeframe(timeframe)
        source = self.bar_store.read_range(symbol, base, adjustment, start, end)
        bars = source if timeframe == base else MarketDataService.derive(source, timeframe)
        return [
            bar
            for bar in bars
            if bar.is_final and self._in_window(bar, start_at, end_at)
        ]

    def compare(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> BenchmarkComparison:
        stock_name, _, _, _ = self._security(symbol)
        benchmark = self.benchmark_for(symbol)
        stock = self._read(
            symbol, timeframe, Adjustment.QFQ, date.min, end, None, end_at
        )
        if not stock:
            raise BenchmarkDataError("stock_data_missing", "当前时段股票行情尚未同步")
        market = self._read(
            benchmark.symbol,
            timeframe,
            Adjustment.NONE,
            date.min,
            end,
            None,
            end_at,
        )
        if not market:
            raise BenchmarkDataError("benchmark_data_missing", "对应大盘数据尚未同步")

        stock_by_time = {bar.timestamp: bar for bar in stock}
        market_by_time = {bar.timestamp: bar for bar in market}
        timestamps = sorted(stamp for stamp in stock_by_time.keys() & market_by_time.keys()
                            if start <= stamp.date() <= end and self._in_window(stock_by_time[stamp], start_at, end_at))
        def period_changes(bars):
            return {current.timestamp: ((current.close / previous.close - 1) * 100, previous.timestamp)
                    for previous, current in zip(bars, bars[1:]) if previous.close > 0}
        stock_changes = period_changes(stock)
        market_changes = period_changes(market)
        if not timestamps:
            raise BenchmarkDataError(
                "no_aligned_data", "股票与大盘在该时段没有可对齐行情"
            )

        stock_base = stock_by_time[timestamps[0]].close
        market_base = market_by_time[timestamps[0]].close
        points = []
        for timestamp in timestamps:
            stock_return = (stock_by_time[timestamp].close / stock_base - 1) * 100
            market_return = (market_by_time[timestamp].close / market_base - 1) * 100
            points.append(
                ComparisonPoint(
                    timestamp=timestamp,
                    stock_return_pct=stock_return,
                    benchmark_return_pct=market_return,
                    relative_pct=stock_return - market_return,
                    stock_period_pct=stock_changes.get(timestamp, (None, None))[0],
                    benchmark_period_pct=market_changes.get(timestamp, (None, None))[0],
                    relative_period_pct=(stock_changes[timestamp][0] - market_changes[timestamp][0])
                    if timestamp in stock_changes and timestamp in market_changes
                    and stock_changes[timestamp][1] == market_changes[timestamp][1] else None,
                )
            )
        return BenchmarkComparison(
            timeframe=timeframe,
            stock_symbol=symbol,
            stock_name=stock_name,
            benchmark_symbol=benchmark.symbol,
            benchmark_name=benchmark.name,
            points=points,
        )

    def sync(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        include_benchmark: bool,
    ) -> dict[str, int]:
        self._security(symbol)
        if self.stock_market_data is None:
            raise BenchmarkDataError("sync_unavailable", "当前服务未配置行情同步")
        base = chart_base_timeframe(timeframe)
        stock = self.stock_market_data.history(
            symbol, base, start, end, Adjustment.QFQ
        )
        if not stock:
            raise BenchmarkDataError("stock_data_missing", "免费数据源无该时段股票行情")

        market: list[Bar] = []
        if include_benchmark:
            if self.index_provider is None:
                raise BenchmarkDataError("sync_unavailable", "当前服务未配置指数同步")
            benchmark = self.benchmark_for(symbol)
            market = self.index_provider.index_history(
                benchmark.symbol, base, start, end
            )
            if not market:
                if base == Timeframe.MIN_5:
                    raise BenchmarkDataError(
                        "minute_history_unavailable",
                        "该时段已超出免费数据源的分钟历史覆盖范围",
                    )
                raise BenchmarkDataError(
                    "benchmark_data_missing", "免费数据源无该时段大盘行情"
                )
            self.bar_store.upsert(market)
        return {"stock_bars": len(stock), "benchmark_bars": len(market)}
