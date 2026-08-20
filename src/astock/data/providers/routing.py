from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from astock.data.providers.akshare import AkShareProvider
from astock.data.providers.baostock import BaoStockProvider
from astock.data.providers.base import HistoryProvider, ReferenceDataProvider
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security


class RoutedHistoryProvider:
    def __init__(self, primary: HistoryProvider, bse: HistoryProvider) -> None:
        self.primary = primary
        self.bse = bse

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> list[Bar]:
        provider = self.bse if symbol.endswith(".BJ") else self.primary
        return provider.history(symbol, timeframe, start, end, adjustment)

    @contextmanager
    def bulk_session(self) -> Iterator[None]:
        session = getattr(self.primary, "bulk_session", None)
        if session is None:
            yield
            return
        with session():
            yield


class CombinedReferenceProvider:
    def __init__(
        self,
        primary: ReferenceDataProvider,
        bse: object,
    ) -> None:
        self.primary = primary
        self.bse = bse

    def securities_on(self, on_date: date) -> list[Security]:
        merged = {
            security.symbol: security
            for security in [
                *self.primary.securities_on(on_date),
                *self.bse.securities_on(on_date),
            ]
        }
        return sorted(merged.values(), key=lambda security: security.symbol)

    def symbols_on(self, on_date: date) -> list[dict]:
        return [
            {
                "symbol": security.symbol,
                "name": security.name,
                "trade_status": "0" if security.is_suspended else "1",
                "source": security.source,
            }
            for security in self.securities_on(on_date)
        ]

    def trading_dates(self, start: date, end: date) -> set[date]:
        return self.primary.trading_dates(start, end)

    def adjustment_factors(self, symbol: str, start: date, end: date) -> list[dict]:
        if symbol.endswith(".BJ"):
            return []
        return self.primary.adjustment_factors(symbol, start, end)

    def corporate_actions(self, symbol: str, start: date, end: date) -> list[dict]:
        if symbol.endswith(".BJ"):
            return []
        return self.primary.corporate_actions(symbol, start, end)

    def security_status(self, symbol: str, start: date, end: date) -> list[dict]:
        if symbol.endswith(".BJ"):
            return []
        return self.primary.security_status(symbol, start, end)


def build_default_market_providers() -> tuple[RoutedHistoryProvider, CombinedReferenceProvider]:
    primary = BaoStockProvider()
    bse = AkShareProvider()
    return RoutedHistoryProvider(primary, bse), CombinedReferenceProvider(primary, bse)
