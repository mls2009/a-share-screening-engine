from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from astock.screening.service import ScreeningService
from astock.storage.bars import BarStore
from astock.storage.database import Database


class MarketSyncReader(Protocol):
    def status(self, job_id: UUID) -> object: ...


@dataclass(frozen=True)
class ApiContext:
    database: Database
    bar_store: BarStore
    screening: ScreeningService
    market_sync: MarketSyncReader
