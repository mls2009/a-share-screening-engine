from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PriceComparator(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"


class MonitorScope(StrEnum):
    WATCHLIST = "watchlist"
    MARKET = "market"


class MonitorTaskCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=80)
    symbols: list[str] = Field(max_length=1000)
    comparator: PriceComparator
    threshold: float = Field(gt=0)
    cooldown_seconds: int = Field(default=300, ge=0, le=86_400)
    scope: MonitorScope = MonitorScope.WATCHLIST
    enabled: bool = True

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if any(not value for value in normalized):
            raise ValueError("symbols must not contain blanks")
        if len(set(normalized)) != len(normalized):
            raise ValueError("symbols must be unique")
        return normalized

    @model_validator(mode="after")
    def require_watchlist_symbols(self) -> MonitorTaskCreate:
        if self.scope == MonitorScope.WATCHLIST and not self.symbols:
            raise ValueError("watchlist tasks require at least one symbol")
        return self


class MonitorTask(MonitorTaskCreate):
    task_id: UUID
    created_at: datetime
    updated_at: datetime


class SignalState(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    symbol: str
    active: bool = False
    last_value: float | None = None
    last_triggered_at: datetime | None = None


class PriceEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    triggered: bool
    state: SignalState


class ScanSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: MonitorScope
    tasks: int
    requested_symbols: int
    received_quotes: int
    triggered: int
    paused_symbols: dict[str, str] = Field(default_factory=dict)
    skipped_reason: str | None = None
