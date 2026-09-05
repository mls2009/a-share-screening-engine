from datetime import UTC, date, datetime, timedelta
from math import isclose, isfinite
from uuid import UUID, uuid4

from astock.backtest.engine import BacktestEngine
from astock.backtest.models import (
    BacktestRequest,
    BacktestResult,
    BacktestRun,
    ExecutionStatus,
)
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Timeframe
from astock.storage.bars import BarStore
from astock.storage.database import Database


class BacktestDataError(RuntimeError):
    def __init__(self, symbols: list[str], message: str | None = None) -> None:
        self.symbols = symbols
        super().__init__(message or f"本地缺少区间内有效回测行情，请同步股票和周期：{', '.join(symbols)}")


class BacktestService:
    def __init__(
        self,
        database: Database,
        bar_store: BarStore,
        engine: BacktestEngine | None = None,
    ) -> None:
        self.database = database
        self.bar_store = bar_store
        self.engine = engine or BacktestEngine()

    @staticmethod
    def _base_timeframe(timeframe: Timeframe) -> Timeframe:
        if timeframe in {
            Timeframe.MIN_15,
            Timeframe.MIN_30,
            Timeframe.MIN_60,
        }:
            return Timeframe.MIN_5
        if timeframe in {Timeframe.WEEK, Timeframe.MONTH}:
            return Timeframe.DAY
        return timeframe

    @staticmethod
    def _warmup_start(start: date, timeframe: Timeframe) -> date:
        periods = 300
        if timeframe in {
            Timeframe.MIN_5,
            Timeframe.MIN_15,
            Timeframe.MIN_30,
            Timeframe.MIN_60,
        }:
            return start - timedelta(days=90)
        if timeframe == Timeframe.DAY:
            return start - timedelta(days=periods * 2)
        if timeframe == Timeframe.WEEK:
            return start - timedelta(days=periods * 7)
        return start - timedelta(days=periods * 31)

    def run(self, request: BacktestRequest) -> BacktestRun:
        base = self._base_timeframe(request.timeframe)
        warmup_start = self._warmup_start(request.start, request.timeframe)
        market = {}
        execution_market = {}
        source_bars = {}
        calendar = dict(self.database.connection.execute(
            "select trade_date, is_open from trading_calendar where trade_date between ? and ?",
            [warmup_start, request.end + timedelta(days=35)],
        ).fetchall())
        missing = []
        for symbol in request.symbols:
            bars = self.bar_store.read_range(
                symbol,
                base,
                request.adjustment,
                warmup_start,
                request.end,
            )
            bars = [bar for bar in bars if bar.is_final]
            if any(not isfinite(value) or value <= 0 for bar in bars
                   for value in (bar.open, bar.high, bar.low, bar.close)):
                raise BacktestDataError([symbol], f"{symbol}: 行情价格必须为有限正数")
            derived = MarketDataService.derive(bars, request.timeframe, calendar=calendar or None)
            if not any(
                bar.is_final and request.start <= bar.timestamp.date() <= request.end
                for bar in derived
            ):
                missing.append(symbol)
                continue
            market[symbol] = derived
            source_bars[symbol] = bars
            execution_market[symbol] = bars if request.timeframe in {
                Timeframe.WEEK, Timeframe.MONTH
            } else derived
        if missing:
            raise BacktestDataError(missing)

        rows = self.database.connection.execute(
            """
            select symbol, trade_date, is_suspended, limit_up, limit_down
            from security_status
            where symbol in (select unnest(?)) and trade_date between ? and ?
            """,
            [request.symbols, request.start, request.end],
        ).fetchall()
        statuses = {
            (row[0], row[1]): ExecutionStatus(
                is_suspended=row[2], limit_up=row[3], limit_down=row[4]
            )
            for row in rows
        }
        converted = False
        if request.mode.value == "realistic" and request.adjustment != Adjustment.NONE:
            for symbol in request.symbols:
                limit_dates = {day for (key, day), status in statuses.items()
                               if key == symbol and (status.limit_up is not None
                                                     or status.limit_down is not None)}
                if not limit_dates:
                    continue
                raw = {bar.timestamp: bar for bar in self.bar_store.read_range(
                    symbol, base, Adjustment.NONE, request.start, request.end
                ) if bar.is_final}
                factors = {}
                for bar in source_bars[symbol]:
                    day = bar.timestamp.date()
                    if day not in limit_dates:
                        continue
                    original = raw.get(bar.timestamp)
                    if original is None or not isfinite(original.open) or original.open <= 0:
                        raise BacktestDataError([symbol],
                            f"{symbol} {day}: 缺少可靠对应的未复权开盘价，无法换算涨跌停价格尺度")
                    factor = bar.open / original.open
                    if not isfinite(factor) or (day in factors and not isclose(
                        factors[day], factor, rel_tol=1e-6
                    )):
                        raise BacktestDataError([symbol],
                            f"{symbol} {day}: 日内复权比例不一致，无法可靠换算涨跌停价格尺度")
                    factors[day] = factor
                for day, factor in factors.items():
                    status = statuses[(symbol, day)]
                    statuses[(symbol, day)] = status.model_copy(update={
                        "limit_up": status.limit_up * factor if status.limit_up is not None else None,
                        "limit_down": status.limit_down * factor if status.limit_down is not None else None,
                    })
                    converted = True
        result = self.engine.run(request, market, statuses, execution_market=execution_market)
        warnings = list(result.warnings)
        if request.adjustment != Adjustment.NONE:
            warnings.append("使用复权价格进行研究性撮合，未逐笔模拟分红送转与真实现金流。")
        if converted:
            warnings.append("涨跌停价按当日对应复权/未复权开盘价比例近似换算；不等同真实成交复盘。")
        result = result.model_copy(update={"warnings": warnings})
        run = BacktestRun(run_id=uuid4(), result=result)
        self._persist(run)
        return run

    def _persist(self, run: BacktestRun) -> None:
        result = run.result
        connection = self.database.connection
        connection.execute("begin transaction")
        try:
            connection.execute(
                """
                insert into backtest_runs
                  (run_id, status, request, metrics, result, finished_at)
                values (?, 'completed', ?, ?, ?, ?)
                """,
                [
                    run.run_id,
                    result.request.model_dump_json(),
                    result.metrics.model_dump_json(),
                    result.model_dump_json(),
                    datetime.now(UTC),
                ],
            )
            if result.trades:
                connection.executemany(
                    """
                    insert into backtest_trades
                      (run_id, sequence, symbol, side, signal_at, executed_at,
                       quantity, price, gross, fees, reason)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        [
                            run.run_id,
                            sequence,
                            trade.symbol,
                            trade.side,
                            trade.signal_at,
                            trade.timestamp,
                            trade.quantity,
                            trade.price,
                            trade.gross,
                            trade.commission + trade.tax + trade.transfer_fee,
                            trade.reason,
                        ]
                        for sequence, trade in enumerate(result.trades)
                    ],
                )
            if result.equity_curve:
                connection.executemany(
                    """
                    insert into backtest_equity
                      (run_id, timestamp, cash, market_value, equity, drawdown)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        [
                            run.run_id,
                            point.timestamp,
                            point.cash,
                            point.market_value,
                            point.equity,
                            point.drawdown,
                        ]
                        for point in result.equity_curve
                    ],
                )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise

    def get(self, run_id: UUID) -> BacktestRun | None:
        row = self.database.connection.execute(
            "select result from backtest_runs where run_id = ?", [run_id]
        ).fetchone()
        if row is None:
            return None
        return BacktestRun(run_id=run_id, result=BacktestResult.model_validate_json(row[0]))
