from datetime import date
from typing import Protocol

from astock.domain.market import Adjustment, Bar, Quote, Timeframe
from astock.domain.security import Security


class HistoryProvider(Protocol):
    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> list[Bar]: ...


class QuoteProvider(Protocol):
    def quotes(self, symbols: list[str]) -> list[Quote]: ...


class ReferenceDataProvider(Protocol):
    def trading_dates(self, start: date, end: date) -> set[date]: ...

    def symbols_on(self, on_date: date) -> list[dict]: ...

    def securities_on(self, on_date: date) -> list[Security]: ...

    def adjustment_factors(self, symbol: str, start: date, end: date) -> list[dict]: ...

    def corporate_actions(self, symbol: str, start: date, end: date) -> list[dict]: ...

    def security_status(self, symbol: str, start: date, end: date) -> list[dict]: ...
