from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from astock.domain.market import Adjustment, Timeframe
from astock.screening.models import ConditionNode, GroupNode, MetricOperand, Node
from astock.screening.validation import validate_tree


def _tree_timeframes(tree: Node) -> set[Timeframe]:
    result: set[Timeframe] = set()

    def visit(node: ConditionNode | GroupNode) -> None:
        if isinstance(node, GroupNode):
            for child in node.children:
                visit(child)
            return
        result.add(node.timeframe)
        if isinstance(node.right, MetricOperand):
            result.add(node.right.timeframe)

    visit(tree)
    return result


class BacktestMode(StrEnum):
    SIMPLE = "simple"
    REALISTIC = "realistic"


class FeeSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    commission_rate: float = Field(default=0.0003, ge=0)
    minimum_commission: float = Field(default=5, ge=0)
    sell_stamp_tax_rate: float = Field(default=0.0005, ge=0)
    transfer_fee_rate: float = Field(default=0.00001, ge=0)
    slippage_bps: float = Field(default=2, ge=0)

    @classmethod
    def zero(cls) -> FeeSchedule:
        return cls(
            commission_rate=0,
            minimum_commission=0,
            sell_stamp_tax_rate=0,
            transfer_fee_rate=0,
            slippage_bps=0,
        )


class ExecutionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_suspended: bool = False
    limit_up: float | None = None
    limit_down: float | None = None


class BacktestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbols: list[str] = Field(min_length=1)
    timeframe: Timeframe
    start: date
    end: date
    entry_tree: Node
    exit_tree: Node
    initial_cash: float = Field(gt=0)
    position_size: float = Field(default=0.2, gt=0, le=1)
    mode: BacktestMode = BacktestMode.SIMPLE
    adjustment: Adjustment = Adjustment.QFQ
    fees: FeeSchedule = Field(default_factory=FeeSchedule)

    @model_validator(mode="after")
    def validate_range(self) -> BacktestRequest:
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be unique")
        tree_timeframes = _tree_timeframes(self.entry_tree) | _tree_timeframes(self.exit_tree)
        if tree_timeframes != {self.timeframe}:
            raise ValueError("condition timeframe must match backtest timeframe")
        issues = validate_tree(self.entry_tree) + validate_tree(self.exit_tree)
        if issues:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            raise ValueError(f"invalid backtest condition: {details}")
        return self


class BacktestTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: str
    signal_at: datetime
    timestamp: datetime
    quantity: int
    price: float
    gross: float
    commission: float
    tax: float
    transfer_fee: float
    reason: str


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    cash: float
    market_value: float
    equity: float
    drawdown: float


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_loss_ratio: float
    trade_count: int
    total_fees: float


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: BacktestRequest
    metrics: BacktestMetrics
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
    rejected_orders: list[str] = Field(default_factory=list)


class BacktestRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    result: BacktestResult
