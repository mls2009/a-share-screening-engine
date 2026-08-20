from collections.abc import Callable, Sequence

from astock.data.providers.base import QuoteProvider
from astock.domain.market import Quote

ProviderFactory = Callable[[], QuoteProvider]


class IncompleteQuoteBatchError(RuntimeError):
    pass


class QuoteProviderError(RuntimeError):
    def __init__(self, failures: dict[str, Exception]) -> None:
        self.failures = failures
        detail = "; ".join(f"{name}: {error}" for name, error in failures.items())
        super().__init__(f"all quote providers failed: {detail}")


class FallbackQuoteProvider:
    def __init__(self, providers: Sequence[tuple[str, ProviderFactory]]) -> None:
        if not providers:
            raise ValueError("at least one quote provider is required")
        self.providers = providers

    def quotes(self, symbols: list[str]) -> list[Quote]:
        if not symbols:
            return []
        requested = set(symbols)
        failures: dict[str, Exception] = {}
        for name, factory in self.providers:
            try:
                quotes = factory().quotes(symbols)
                missing = requested - {quote.symbol for quote in quotes}
                if missing:
                    raise IncompleteQuoteBatchError(
                        f"missing symbols: {', '.join(sorted(missing))}"
                    )
                return quotes
            except Exception as error:  # noqa: BLE001 - provider boundary
                failures[name] = error
        raise QuoteProviderError(failures)
