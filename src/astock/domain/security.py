from datetime import date

from pydantic import BaseModel, ConfigDict


class Security(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    name: str
    exchange: str
    board: str
    listed_on: date | None = None
    delisted_on: date | None = None
    is_listed: bool = True
    is_suspended: bool = False
    source: str = "baostock"
