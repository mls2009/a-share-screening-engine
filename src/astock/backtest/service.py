from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from astock.backtest.engine import BacktestEngine
from astock.backtest.models import (
    BacktestRequest,
    BacktestResult,
    BacktestRun,
    ExecutionStatus,
)
from astock.data.service import MarketDataService
from astock.domain.market import Timeframe
from astock.storage.bars import BarStore
from astock.storage.database import Database


class BacktestDataError(RuntimeError):
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        super().__init__(f"missing local bars for: {', '.join(symbols)}")


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
        missing = []
        for symbol in request.symbols:
            bars = self.bar_store.read_range(
                symbol,
                base,
                request.adjustment,
                warmup_start,
                request.end,
            )
            if not bars:
                missing.append(symbol)
                continue
            market[symbol] = MarketDataService.derive(bars, request.timeframe)
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
        result = self.engine.run(request, market, statuses)
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
