from dataclasses import dataclass
from math import sqrt

import pandas as pd

from astock.backtest.broker import Broker
from astock.backtest.models import (
    BacktestMetrics,
    BacktestRequest,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
    ExecutionStatus,
)
from astock.domain.market import Bar
from astock.features.technical import compute_technical_features
from astock.screening.evaluator import TruthValue, evaluate_tree


@dataclass
class Position:
    quantity: int
    average_cost: float
    bought_at: pd.Timestamp


@dataclass(frozen=True)
class PendingOrder:
    side: str
    signal_at: pd.Timestamp
    reason: str


def _frame(bars: list[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume_shares": bar.volume_shares,
                "amount_cny": bar.amount_cny,
            }
            for bar in bars
        ]
    )


def _records(bars: list[Bar]) -> list[dict]:
    frame = compute_technical_features(_frame(bars))
    return frame.where(pd.notna(frame), None).to_dict("records")


def _metrics(
    request: BacktestRequest,
    curve: list[EquityPoint],
    trades: list[BacktestTrade],
    closed_pnls: list[float],
) -> BacktestMetrics:
    if not curve:
        return BacktestMetrics(
            total_return=0,
            annualized_return=0,
            max_drawdown=0,
            sharpe_ratio=0,
            win_rate=0,
            profit_loss_ratio=0,
            trade_count=0,
            total_fees=0,
        )
    equity = pd.Series([point.equity for point in curve], dtype=float)
    total_return = (equity.iloc[-1] / request.initial_cash - 1) * 100
    periods = max(len(equity) - 1, 1)
    annualized = ((equity.iloc[-1] / request.initial_cash) ** (252 / periods) - 1) * 100
    returns = equity.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std(ddof=0) * sqrt(252)) if len(returns) > 1 and returns.std(ddof=0) else 0
    wins = [value for value in closed_pnls if value > 0]
    losses = [-value for value in closed_pnls if value < 0]
    return BacktestMetrics(
        total_return=float(total_return),
        annualized_return=float(annualized),
        max_drawdown=max((point.drawdown for point in curve), default=0),
        sharpe_ratio=sharpe,
        win_rate=len(wins) / len(closed_pnls) * 100 if closed_pnls else 0,
        profit_loss_ratio=(sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0,
        trade_count=len(closed_pnls),
        total_fees=sum(trade.commission + trade.tax + trade.transfer_fee for trade in trades),
    )


class BacktestEngine:
    def run(
        self,
        request: BacktestRequest,
        market: dict[str, list[Bar]],
        statuses: dict[tuple[str, object], ExecutionStatus] | None = None,
    ) -> BacktestResult:
        statuses = statuses or {}
        prepared: dict[str, tuple[list[Bar], list[dict]]] = {}
        for symbol in request.symbols:
            bars = sorted(
                [
                    bar
                    for bar in market.get(symbol, [])
                    if request.start <= bar.timestamp.date() <= request.end and bar.is_final
                ],
                key=lambda bar: bar.timestamp,
            )
            if bars:
                prepared[symbol] = (bars, _records(bars))

        timeline = sorted(
            {bar.timestamp for bars, _ in prepared.values() for bar in bars}
        )
        indices = {
            symbol: {bar.timestamp: index for index, bar in enumerate(bars)}
            for symbol, (bars, _) in prepared.items()
        }
        broker = Broker(request.mode, request.fees)
        cash = request.initial_cash
        positions: dict[str, Position] = {}
        pending: dict[str, PendingOrder] = {}
        last_prices: dict[str, float] = {}
        trades: list[BacktestTrade] = []
        closed_pnls: list[float] = []
        rejected: list[str] = []
        curve: list[EquityPoint] = []
        peak = request.initial_cash

        for timestamp in timeline:
            available: list[tuple[str, Bar, int, list[dict]]] = []
            for symbol, (bars, records) in prepared.items():
                index = indices[symbol].get(timestamp)
                if index is not None:
                    available.append((symbol, bars[index], index, records))

            for symbol, bar, _, _ in available:
                order = pending.pop(symbol, None)
                if order is None:
                    continue
                status = statuses.get((symbol, timestamp.date()), ExecutionStatus())
                if request.mode.value == "realistic":
                    reason = None
                    if status.is_suspended:
                        reason = "suspended"
                    elif (
                        order.side == "buy"
                        and status.limit_up is not None
                        and bar.low >= status.limit_up
                    ):
                        reason = "limit_up_no_liquidity"
                    elif (
                        order.side == "sell"
                        and status.limit_down is not None
                        and bar.high <= status.limit_down
                    ):
                        reason = "limit_down_no_liquidity"
                    if reason is not None:
                        rejected.append(f"{timestamp.isoformat()} {symbol}: {reason}")
                        continue
                if order.side == "buy" and symbol not in positions:
                    marked_value = sum(
                        position.quantity * last_prices.get(item, position.average_cost)
                        for item, position in positions.items()
                    )
                    target = (cash + marked_value) * request.position_size
                    execution = broker.buy(cash, bar.open, target)
                    if execution.quantity == 0:
                        rejected.append(f"{timestamp.isoformat()} {symbol}: insufficient cash")
                        continue
                    cash -= execution.total_cost
                    positions[symbol] = Position(
                        execution.quantity, execution.total_cost / execution.quantity, pd.Timestamp(timestamp)
                    )
                    trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            side="buy",
                            signal_at=order.signal_at.to_pydatetime(),
                            timestamp=timestamp,
                            quantity=execution.quantity,
                            price=execution.price,
                            gross=execution.gross,
                            commission=execution.commission,
                            tax=execution.tax,
                            transfer_fee=execution.transfer_fee,
                            reason=order.reason,
                        )
                    )
                elif order.side == "sell" and symbol in positions:
                    position = positions[symbol]
                    if (
                        request.mode.value == "realistic"
                        and position.bought_at.date() >= pd.Timestamp(timestamp).date()
                    ):
                        pending[symbol] = order
                        continue
                    execution = broker.sell(position.quantity, bar.open)
                    cash += execution.net_cash
                    closed_pnls.append(execution.net_cash - position.average_cost * position.quantity)
                    del positions[symbol]
                    trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            side="sell",
                            signal_at=order.signal_at.to_pydatetime(),
                            timestamp=timestamp,
                            quantity=execution.quantity,
                            price=execution.price,
                            gross=execution.gross,
                            commission=execution.commission,
                            tax=execution.tax,
                            transfer_fee=execution.transfer_fee,
                            reason=order.reason,
                        )
                    )

            for symbol, bar, index, records in available:
                last_prices[symbol] = bar.close
                history = {request.timeframe: list(reversed(records[: index + 1]))}
                if symbol in positions:
                    result = evaluate_tree(request.exit_tree, history)
                    if result.result == TruthValue.TRUE:
                        pending[symbol] = PendingOrder(
                            "sell", pd.Timestamp(timestamp), "exit condition matched"
                        )
                elif symbol not in pending:
                    result = evaluate_tree(request.entry_tree, history)
                    if result.result == TruthValue.TRUE:
                        pending[symbol] = PendingOrder(
                            "buy", pd.Timestamp(timestamp), "entry condition matched"
                        )

            market_value = sum(
                position.quantity * last_prices.get(symbol, position.average_cost)
                for symbol, position in positions.items()
            )
            equity = cash + market_value
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak * 100 if peak else 0
            curve.append(
                EquityPoint(
                    timestamp=timestamp,
                    cash=cash,
                    market_value=market_value,
                    equity=equity,
                    drawdown=drawdown,
                )
            )

        return BacktestResult(
            request=request,
            metrics=_metrics(request, curve, trades, closed_pnls),
            trades=trades,
            equity_curve=curve,
            rejected_orders=rejected,
        )
