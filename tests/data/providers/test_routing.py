from datetime import date

from astock.data.providers.routing import (
    CombinedReferenceProvider,
    RoutedHistoryProvider,
    build_default_market_providers,
)
from astock.domain.market import Adjustment, Timeframe
from astock.domain.security import Security


class FakeProvider:
    def __init__(self, securities: list[Security], label: str) -> None:
        self._securities = securities
        self.label = label
        self.history_calls: list[str] = []

    def securities_on(self, on_date: date) -> list[Security]:
        return self._securities

    def history(self, symbol, timeframe, start, end, adjustment):
        self.history_calls.append(symbol)
        return [self.label]

    def trading_dates(self, start, end):
        return {end}

    def adjustment_factors(self, symbol, start, end):
        return [self.label]

    def corporate_actions(self, symbol, start, end):
        return [self.label]

    def security_status(self, symbol, start, end):
        return [self.label]


def test_combined_reference_adds_bse_and_routes_history_by_exchange() -> None:
    sh = Security(symbol="600001.SH", name="沪股", exchange="SH", board="main")
    bj = Security(symbol="920001.BJ", name="京股", exchange="BJ", board="beijing")
    primary = FakeProvider([sh], "primary")
    bse = FakeProvider([bj], "bse")
    reference = CombinedReferenceProvider(primary, bse)
    history = RoutedHistoryProvider(primary, bse)

    assert {item.symbol for item in reference.securities_on(date(2026, 8, 20))} == {
        "600001.SH",
        "920001.BJ",
    }
    assert history.history(
        "600001.SH", Timeframe.DAY, date(2026, 8, 1), date(2026, 8, 20), Adjustment.QFQ
    ) == ["primary"]
    assert history.history(
        "920001.BJ", Timeframe.DAY, date(2026, 8, 1), date(2026, 8, 20), Adjustment.QFQ
    ) == ["bse"]
    assert reference.adjustment_factors(
        "920001.BJ", date(2026, 8, 1), date(2026, 8, 20)
    ) == []


def test_default_market_providers_include_exchange_router() -> None:
    history, reference = build_default_market_providers()

    assert isinstance(history, RoutedHistoryProvider)
    assert isinstance(reference, CombinedReferenceProvider)
