from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class Timeframe(StrEnum):
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"
    DAY = "1d"
    WEEK = "1w"
    MONTH = "1mo"


class Adjustment(StrEnum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timestamp: datetime
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    volume_shares: int
    amount_cny: float
    adjustment: Adjustment = Adjustment.NONE
    source: str = ""
    is_final: bool = True

    @model_validator(mode="after")
    def validate_market_values(self) -> "Bar":
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC values are inconsistent")
        if self.volume_shares < 0 or self.amount_cny < 0:
            raise ValueError("volume and amount must be non-negative")
        return self


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timestamp: datetime
    price: float
    volume_shares: int
    amount_cny: float
    source: str


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timestamp: datetime
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume_shares: int
    amount_cny: float
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    total_market_cap: float | None = None
    float_market_cap: float | None = None
    source: str
