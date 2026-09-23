from dataclasses import dataclass
from datetime import timedelta
from math import isfinite, sqrt

import pandas as pd

from astock.backtest.broker import Broker
from astock.backtest.models import (
    BacktestDiagnostics,
    BacktestMetrics,
    BacktestRequest,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
    ExecutionStatus,
)
from astock.domain.market import Bar, Timeframe
from astock.features.technical import compute_technical_features
from astock.screening.evaluator import TruthValue, evaluate_tree
from astock.screening.service import _requirements


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


def _periods_per_year(timeframe: Timeframe) -> int:
    return {
        Timeframe.MIN_5: 252 * 48,
        Timeframe.MIN_15: 252 * 16,
        Timeframe.MIN_30: 252 * 8,
        Timeframe.MIN_60: 252 * 4,
        Timeframe.DAY: 252,
        Timeframe.WEEK: 52,
        Timeframe.MONTH: 12,
    }[timeframe]


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
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


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
    elapsed_seconds = (curve[-1].timestamp - curve[0].timestamp).total_seconds()
    elapsed_years = elapsed_seconds / (365.25 * 24 * 60 * 60)
    ratio = float(equity.iloc[-1] / request.initial_cash)
    try:
        annualized = (
            (ratio ** (1 / elapsed_years) - 1) * 100
            if elapsed_years > 0 and ratio > 0
            else 0
        )
    except OverflowError:
        annualized = None
    if annualized is not None and not isfinite(annualized):
        annualized = None
    returns = equity.pct_change().dropna()
    sharpe = (
        float(
            returns.mean()
            / returns.std(ddof=0)
            * sqrt(_periods_per_year(request.timeframe))
        )
        if len(returns) > 1 and returns.std(ddof=0)
        else 0
    )
    wins = [value for value in closed_pnls if value > 0]
    losses = [-value for value in closed_pnls if value < 0]
    return BacktestMetrics(
        total_return=float(total_return),
        annualized_return=annualized,
        max_drawdown=max((point.drawdown for point in curve), default=0),
        sharpe_ratio=sharpe,
        win_rate=len(wins) / len(closed_pnls) * 100 if closed_pnls else 0,
        profit_loss_ratio=(sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0,
        trade_count=len(closed_pnls),
        total_fees=sum(trade.commission + trade.tax + trade.transfer_fee for trade in trades),
    )


def _close_at(bar: Bar):
    if bar.timeframe in {Timeframe.DAY, Timeframe.WEEK, Timeframe.MONTH}:
        return bar.timestamp.replace(hour=15, minute=0, second=0, microsecond=0)
    return bar.timestamp


def _open_at(bar: Bar):
    if bar.timeframe == Timeframe.DAY:
        return bar.timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
    if bar.timeframe in {Timeframe.WEEK, Timeframe.MONTH}:
        raise ValueError("weekly/monthly signals require daily execution_market")
    return bar.timestamp - timedelta(minutes=int(bar.timeframe.value[:-1]))


class BacktestEngine:
    def run(
        self,
        request: BacktestRequest,
        market: dict[str, list[Bar]],
        statuses: dict[tuple[str, object], ExecutionStatus] | None = None,
        execution_market: dict[str, list[Bar]] | None = None,
        condition_history=None,
    ) -> BacktestResult:
        statuses = statuses or {}
        prepared: dict[str, tuple[list[Bar], list[dict]]] = {}
        for symbol in request.symbols:
            bars = sorted(
                [
                    bar
                    for bar in market.get(symbol, [])
                    if bar.timestamp.date() <= request.end and bar.is_final
                ],
                key=lambda bar: bar.timestamp,
            )
            if bars:
                prepared[symbol] = (bars, _records(bars))

        execution_market = execution_market if execution_market is not None else market
        execution_bars = {
            symbol: {_close_at(bar): bar for bar in execution_market.get(symbol, [])
                     if bar.is_final and request.start <= bar.timestamp.date() <= request.end}
            for symbol in request.symbols
        }
        timeline = sorted({timestamp for bars in execution_bars.values() for timestamp in bars})
        indices = {
            symbol: {_close_at(bar): index for index, bar in enumerate(bars)}
            for symbol, (bars, _) in prepared.items()
        }
        history_limit = max(_requirements(request.entry_tree)[1], _requirements(request.exit_tree)[1])
        required_metrics = _requirements(request.entry_tree)[2] | _requirements(request.exit_tree)[2]
        warmup_missing = []
        for symbol, (bars, records) in prepared.items():
            first = next((i for i, bar in enumerate(bars)
                          if bar.timestamp.date() >= request.start), None)
            if first is not None and (first + 1 < history_limit or any(
                records[i].get(metric) is None
                for i in range(max(0, first + 1 - history_limit), first + 1)
                for metric in required_metrics
            )):
                warmup_missing.append(symbol)
        unknown_evaluations = 0
        covered = 0
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
            available = [(symbol, bars[timestamp]) for symbol, bars in execution_bars.items()
                         if timestamp in bars]
            opening_prices = {symbol: bar.open for symbol, bar in available}
            opening_equity = cash + sum(
                position.quantity * opening_prices.get(
                    symbol, last_prices.get(symbol, position.average_cost)
                )
                for symbol, position in positions.items()
            )
            execution_order = sorted(
                available,
                key=lambda item: 0 if item[0] in pending and pending[item[0]].side == "sell" else 1,
            )
            for symbol, bar in execution_order:
                open_at = _open_at(bar)
                order = pending.pop(symbol, None)
                if order is None:
                    continue
                status = statuses.get((symbol, timestamp.date()), ExecutionStatus())
                if request.mode.value == "realistic":
                    reason = None
                    if bar.volume_shares == 0:
                        reason = "zero_volume"
                    elif status.is_suspended:
                        reason = "suspended"
                    elif (
                        order.side == "buy"
                        and status.limit_up is not None
                        and bar.open >= status.limit_up
                    ):
                        reason = "limit_up_no_liquidity"
                    elif (
                        order.side == "sell"
                        and status.limit_down is not None
                        and bar.open <= status.limit_down
                    ):
                        reason = "limit_down_no_liquidity"
                    slipped = bar.open * (1 + (1 if order.side == "buy" else -1)
                                          * request.fees.slippage_bps / 10_000)
                    if reason is None and (
                        (status.limit_up is not None and slipped > status.limit_up)
                        or (status.limit_down is not None and slipped < status.limit_down)
                    ):
                        reason = "slippage_outside_price_limits"
                    if reason is not None:
                        rejected.append(f"{timestamp.isoformat()} {symbol}: {reason}")
                        continue
                if order.side == "buy" and symbol not in positions:
                    target = opening_equity * request.position_size
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
                            timestamp=open_at,
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
                            timestamp=open_at,
                            quantity=execution.quantity,
                            price=execution.price,
                            gross=execution.gross,
                            commission=execution.commission,
                            tax=execution.tax,
                            transfer_fee=execution.transfer_fee,
                            reason=order.reason,
                        )
                    )

            for symbol, bar in available:
                last_prices[symbol] = bar.close
                covered += (symbol, timestamp.date()) in statuses
                index = indices.get(symbol, {}).get(timestamp)
                if index is None or symbol in pending:
                    continue
                records = prepared[symbol][1]
                history = {request.timeframe: list(reversed(
                    records[max(0, index + 1 - history_limit): index + 1]
                ))}
                if condition_history is not None:
                    history = condition_history(symbol, timestamp)
                tree = request.exit_tree if symbol in positions else request.entry_tree
                result = evaluate_tree(tree, history)
                unknown_evaluations += result.result == TruthValue.UNKNOWN
                if result.result == TruthValue.TRUE:
                    side = "sell" if symbol in positions else "buy"
                    pending[symbol] = PendingOrder(side, pd.Timestamp(timestamp),
                                                   f"{side} condition matched")

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

        count = sum(len(bars) for bars in execution_bars.values())
        warnings = []
        if request.mode.value == "realistic" and covered < count:
            warnings.append("部分执行K线缺少历史交易状态，停牌/涨跌停约束覆盖不完整。")
        if warmup_missing:
            warnings.append("区间开始时条件所需指标/观察窗口暖机不足：" + ", ".join(warmup_missing))
        if unknown_evaluations:
            warnings.append("存在指标暖机或数据缺失导致的未知条件，未据此产生信号。")
        if timeline and (timeline[-1] - timeline[0]).days < 365:
            warnings.append("样本不足一年，年化收益和夏普可能不稳定；极短样本年化不可表示时为空。")
        metrics_request = request.model_copy(update={"timeframe": Timeframe.DAY}) if (
            request.timeframe in {Timeframe.WEEK, Timeframe.MONTH}
        ) else request
        return BacktestResult(
            request=request,
            metrics=_metrics(metrics_request, curve, trades, closed_pnls),
            warnings=warnings,
            diagnostics=BacktestDiagnostics(
                effective_start=timeline[0] if timeline else None,
                effective_end=timeline[-1] if timeline else None,
                execution_bars=count,
                signal_bars=sum(request.start <= bar.timestamp.date() <= request.end
                                for bars, _ in prepared.values() for bar in bars),
                status_covered_bars=covered, status_coverage_pct=covered / count * 100 if count else 0,
                unknown_evaluations=unknown_evaluations,
                warmup_bars={symbol: sum(bar.timestamp.date() < request.start for bar in bars)
                             for symbol, (bars, _) in prepared.items()},
            ),
            trades=trades,
            equity_curve=curve,
            rejected_orders=rejected,
        )
