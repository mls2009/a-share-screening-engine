from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock.data.providers.fallback import FallbackQuoteProvider, QuoteProviderError
from astock.domain.market import Quote

TZ = ZoneInfo("Asia/Shanghai")


def quote(symbol: str, source: str) -> Quote:
    return Quote(
        symbol=symbol,
        timestamp=datetime(2026, 8, 20, 10, 0, tzinfo=TZ),
        price=10,
        volume_shares=100,
        amount_cny=1_000,
        source=source,
    )


class StubProvider:
    def __init__(self, result: list[Quote] | Exception) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def quotes(self, symbols: list[str]) -> list[Quote]:
        self.calls.append(symbols)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_returns_first_complete_provider_without_building_fallback() -> None:
    primary = StubProvider([quote("600519.SH", "mootdx")])
    fallback_built = False

    def build_fallback() -> StubProvider:
        nonlocal fallback_built
        fallback_built = True
        return StubProvider([quote("600519.SH", "tencent")])

    provider = FallbackQuoteProvider([("mootdx", lambda: primary), ("tencent", build_fallback)])

    result = provider.quotes(["600519.SH"])

    assert result[0].source == "mootdx"
    assert fallback_built is False


@pytest.mark.parametrize(
    "primary_result",
    [ConnectionError("offline"), [], [quote("600519.SH", "mootdx")]],
)
def test_falls_back_on_error_empty_or_incomplete_batch(primary_result) -> None:
    symbols = ["600519.SH", "000001.SZ"]
    primary = StubProvider(primary_result)
    fallback = StubProvider([quote(symbol, "tencent") for symbol in symbols])
    provider = FallbackQuoteProvider(
        [("mootdx", lambda: primary), ("tencent", lambda: fallback)]
    )

    result = provider.quotes(symbols)

    assert [item.source for item in result] == ["tencent", "tencent"]
    assert fallback.calls == [symbols]


def test_falls_back_when_primary_factory_fails() -> None:
    def failing_factory():
        raise ConnectionError("cannot construct mootdx")

    fallback = StubProvider([quote("600519.SH", "tencent")])
    provider = FallbackQuoteProvider(
        [("mootdx", failing_factory), ("tencent", lambda: fallback)]
    )

    assert provider.quotes(["600519.SH"])[0].source == "tencent"


def test_raises_aggregate_error_after_all_providers_fail() -> None:
    provider = FallbackQuoteProvider(
        [
            ("mootdx", lambda: StubProvider(ConnectionError("offline"))),
            ("tencent", lambda: StubProvider(TimeoutError("timed out"))),
        ]
    )

    with pytest.raises(QuoteProviderError) as captured:
        provider.quotes(["600519.SH"])

    assert "mootdx: offline" in str(captured.value)
    assert "tencent: timed out" in str(captured.value)
    assert list(captured.value.failures) == ["mootdx", "tencent"]


def test_empty_request_does_not_build_providers() -> None:
    def forbidden_factory():
        raise AssertionError("provider must not be built")

    provider = FallbackQuoteProvider([("mootdx", forbidden_factory)])

    assert provider.quotes([]) == []
