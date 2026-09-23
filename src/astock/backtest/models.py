from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from astock.domain.market import Adjustment, Timeframe
from astock.screening.catalog import DEFAULT_CATALOG, MetricCatalog
from astock.screening.models import ConditionNode, GroupNode, MetricOperand, Node
from astock.screening.validation import validate_tree

BACKTEST_CATALOG = MetricCatalog([
    metric for metric in DEFAULT_CATALOG.all() if "backtest" in metric.supported_modes
])


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
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    commission_rate: float = Field(default=0.0003, ge=0)
    minimum_commission: float = Field(default=5, ge=0)
    sell_stamp_tax_rate: float = Field(default=0.0005, ge=0)
    transfer_fee_rate: float = Field(default=0.00001, ge=0)
    slippage_bps: float = Field(default=2, ge=0, lt=10_000)

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
        issues = validate_tree(self.entry_tree) + validate_tree(self.exit_tree)
        if issues:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            raise ValueError(f"invalid backtest condition: {details}")
        unsupported = validate_tree(self.entry_tree, catalog=BACKTEST_CATALOG) + validate_tree(
            self.exit_tree, catalog=BACKTEST_CATALOG
        )
        if unsupported:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in unsupported)
            raise ValueError(f"unsupported backtest metric: {details}")
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
    annualized_return: float | None
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_loss_ratio: float
    trade_count: int
    total_fees: float


class BacktestDiagnostics(BaseModel):
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    execution_bars: int = 0
    signal_bars: int = 0
    status_covered_bars: int = 0
    status_coverage_pct: float = 0
    unknown_evaluations: int = 0
    warmup_bars: dict[str, int] = Field(default_factory=dict)


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: BacktestRequest
    metrics: BacktestMetrics
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
    rejected_orders: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diagnostics: BacktestDiagnostics = Field(default_factory=BacktestDiagnostics)


class BacktestRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    result: BacktestResult
