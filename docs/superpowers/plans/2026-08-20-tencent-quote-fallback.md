# Tencent Quote Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure-Python Tencent A-share quote adapter and automatically fall back to it when mootdx cannot return a complete quote batch.

**Architecture:** Keep vendor parsing in focused `TencentQuoteProvider` and keep fallback policy in a vendor-neutral `FallbackQuoteProvider`. Construct quote providers lazily so mootdx connection failures are caught by the fallback chain, while the CLI depends only on the existing `QuoteProvider` protocol.

**Tech Stack:** Python 3.12 standard library (`urllib.request`, `datetime`, `zoneinfo`), Pydantic domain models, pytest, Ruff

---

## File Map

```text
src/astock/data/providers/tencent.py   Tencent symbol conversion, HTTP transport and response parser
src/astock/data/providers/fallback.py  Lazy provider orchestration and complete-batch fallback policy
src/astock/cli.py                      Provider selection and smoke-test output
tests/data/providers/test_tencent.py   Tencent parsing, unit conversion and error cases
tests/data/providers/test_fallback.py  Provider ordering, lazy construction and failure aggregation
tests/test_cli.py                      auto/mootdx/tencent CLI dispatch and actual-source output
```

### Task 1: Implement the Tencent quote adapter

**Files:**
- Create: `src/astock/data/providers/tencent.py`
- Create: `tests/data/providers/test_tencent.py`

- [ ] **Step 1: Write the failing symbol and quote parsing tests**

Create `tests/data/providers/test_tencent.py`:

```python
from urllib.parse import parse_qs, urlparse

import pytest

from astock.data.providers.tencent import (
    TencentQuoteError,
    TencentQuoteProvider,
    to_tencent_symbol,
)


def quote_row(
    key: str,
    code: str,
    *,
    price: str = "10.50",
    timestamp: str = "20260820100500",
    volume_lots: str = "123",
    amount_ten_thousand: str = "12.915",
) -> str:
    fields = [""] * 38
    fields[0] = "1"
    fields[1] = "测试股票"
    fields[2] = code
    fields[3] = price
    fields[30] = timestamp
    fields[36] = volume_lots
    fields[37] = amount_ten_thousand
    return f'v_{key}="{"~".join(fields)}";'


def test_converts_supported_a_share_symbols() -> None:
    assert to_tencent_symbol("600519.SH") == "sh600519"
    assert to_tencent_symbol("000001.SZ") == "sz000001"
    assert to_tencent_symbol("920001.BJ") == "bj920001"


def test_rejects_unsupported_symbol_suffix() -> None:
    with pytest.raises(ValueError, match="unsupported exchange"):
        to_tencent_symbol("00700.HK")


def test_parses_gbk_response_and_preserves_requested_order() -> None:
    calls: list[tuple[str, float]] = []
    body = "\n".join(
        [
            quote_row("sz000001", "000001", price="11.25"),
            quote_row("sh600519", "600519", price="10.50"),
        ]
    ).encode("gbk")

    def transport(url: str, timeout: float) -> bytes:
        calls.append((url, timeout))
        return body

    quotes = TencentQuoteProvider(transport=transport, timeout=2.5).quotes(
        ["600519.SH", "000001.SZ"]
    )

    assert [quote.symbol for quote in quotes] == ["600519.SH", "000001.SZ"]
    assert quotes[0].price == 10.5
    assert quotes[0].timestamp.isoformat() == "2026-08-20T10:05:00+08:00"
    assert quotes[0].volume_shares == 12_300
    assert quotes[0].amount_cny == 129_150
    assert quotes[0].source == "tencent"
    assert parse_qs(urlparse(calls[0][0]).query)["q"] == ["sh600519,sz000001"]
    assert calls[0][1] == 2.5
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```bash
.venv/bin/python -m pytest tests/data/providers/test_tencent.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'astock.data.providers.tencent'`.

- [ ] **Step 3: Implement the minimal Tencent provider**

Create `src/astock/data/providers/tencent.py`:

```python
import re
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from astock.domain.market import Quote

SHANGHAI = ZoneInfo("Asia/Shanghai")
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/"
Transport = Callable[[str, float], bytes]


class TencentQuoteError(RuntimeError):
    pass


def to_tencent_symbol(symbol: str) -> str:
    code, separator, exchange = symbol.partition(".")
    prefixes = {"SH": "sh", "SZ": "sz", "BJ": "bj"}
    if not separator or exchange not in prefixes or not code.isdigit():
        raise ValueError(f"unsupported exchange or symbol: {symbol}")
    return f"{prefixes[exchange]}{code}"


def _default_transport(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS host
        return response.read()


class TencentQuoteProvider:
    def __init__(
        self,
        transport: Transport = _default_transport,
        timeout: float = 3.0,
    ) -> None:
        self.transport = transport
        self.timeout = timeout

    @staticmethod
    def _parse_quote(symbol: str, fields: list[str]) -> Quote:
        if len(fields) < 38:
            raise TencentQuoteError(f"truncated quote for {symbol}")
        try:
            price = float(fields[3])
            volume_shares = int(float(fields[36])) * 100
            amount_cny = float(fields[37]) * 10_000
            timestamp = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(
                tzinfo=SHANGHAI
            )
        except (TypeError, ValueError) as error:
            raise TencentQuoteError(f"invalid quote for {symbol}") from error
        if price <= 0 or volume_shares < 0 or amount_cny < 0:
            raise TencentQuoteError(f"invalid market values for {symbol}")
        return Quote(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            volume_shares=volume_shares,
            amount_cny=amount_cny,
            source="tencent",
        )

    def quotes(self, symbols: list[str]) -> list[Quote]:
        if not symbols:
            return []
        keys = [to_tencent_symbol(symbol) for symbol in symbols]
        url = f"{TENCENT_QUOTE_URL}?{urlencode({'q': ','.join(keys)}, safe=',')}"
        try:
            text = self.transport(url, self.timeout).decode("gbk")
        except Exception as error:
            raise TencentQuoteError("Tencent quote request failed") from error

        requested = dict(zip(keys, symbols, strict=True))
        parsed: dict[str, Quote] = {}
        for key, raw_fields in re.findall(r'v_([^=]+)="([^"]*)";', text):
            if key not in requested:
                continue
            fields = raw_fields.split("~")
            if len(fields) < 38 or not fields[0]:
                continue
            parsed[key] = self._parse_quote(requested[key], fields)
        return [parsed[key] for key in keys if key in parsed]
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/data/providers/test_tencent.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Add explicit malformed-response and transport-error tests**

Append to `tests/data/providers/test_tencent.py`:

```python
def test_skips_unmatched_and_truncated_rows() -> None:
    body = 'v_pv_none_match="1";\nv_sh999999="1~short";'.encode("gbk")
    provider = TencentQuoteProvider(transport=lambda _url, _timeout: body)

    assert provider.quotes(["600519.SH"]) == []


def test_rejects_invalid_core_fields() -> None:
    body = quote_row("sh600519", "600519", timestamp="bad-time").encode("gbk")
    provider = TencentQuoteProvider(transport=lambda _url, _timeout: body)

    with pytest.raises(TencentQuoteError, match="invalid quote"):
        provider.quotes(["600519.SH"])


def test_wraps_transport_failure() -> None:
    def failing_transport(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("timed out")

    provider = TencentQuoteProvider(transport=failing_transport)

    with pytest.raises(TencentQuoteError, match="request failed") as captured:
        provider.quotes(["600519.SH"])
    assert isinstance(captured.value.__cause__, TimeoutError)


def test_empty_request_does_not_call_transport() -> None:
    def forbidden_transport(_url: str, _timeout: float) -> bytes:
        raise AssertionError("transport must not be called")

    assert TencentQuoteProvider(transport=forbidden_transport).quotes([]) == []
```

- [ ] **Step 6: Run all Tencent tests**

Run:

```bash
.venv/bin/python -m pytest tests/data/providers/test_tencent.py -v
```

Expected: `7 passed`.

- [ ] **Step 7: Commit the Tencent adapter**

```bash
git add src/astock/data/providers/tencent.py tests/data/providers/test_tencent.py
git commit -m "feat: add Tencent realtime quotes"
```

### Task 2: Implement complete-batch provider fallback

**Files:**
- Create: `src/astock/data/providers/fallback.py`
- Create: `tests/data/providers/test_fallback.py`

- [ ] **Step 1: Write failing fallback-policy tests**

Create `tests/data/providers/test_fallback.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify the missing-module failure**

Run:

```bash
.venv/bin/python -m pytest tests/data/providers/test_fallback.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'astock.data.providers.fallback'`.

- [ ] **Step 3: Implement minimal lazy fallback orchestration**

Create `src/astock/data/providers/fallback.py`:

```python
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
```

- [ ] **Step 4: Run focused fallback tests**

Run:

```bash
.venv/bin/python -m pytest tests/data/providers/test_fallback.py -v
```

Expected: `7 passed` because the parameterized test contributes three cases.

- [ ] **Step 5: Run provider regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/data/providers -v
```

Expected: all provider tests pass.

- [ ] **Step 6: Commit fallback orchestration**

```bash
git add src/astock/data/providers/fallback.py tests/data/providers/test_fallback.py
git commit -m "feat: fall back across realtime quote providers"
```

### Task 3: Wire auto fallback into the CLI

**Files:**
- Modify: `src/astock/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI provider-selection tests**

Change the imports at the top of `tests/test_cli.py` to:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock.cli import main
from astock.domain.market import Adjustment, Quote, Timeframe
```

Then append:

```python


class FakeQuoteProvider:
    def __init__(self, source: str = "tencent") -> None:
        self.source = source
        self.calls: list[list[str]] = []

    def quotes(self, symbols: list[str]) -> list[Quote]:
        self.calls.append(symbols)
        return [
            Quote(
                symbol=symbols[0],
                timestamp=datetime(2026, 8, 20, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
                price=10.5,
                volume_shares=12_300,
                amount_cny=129_150,
                source=self.source,
            )
        ]


def test_smoke_defaults_to_auto_and_prints_actual_source(capsys) -> None:
    selected: list[str] = []
    provider = FakeQuoteProvider()

    def factory(name: str):
        selected.append(name)
        return provider

    exit_code = main(["data", "smoke"], quote_provider_factory=factory)

    assert exit_code == 0
    assert selected == ["auto"]
    assert provider.calls == [["600519.SH"]]
    assert "tencent 正常" in capsys.readouterr().out


def test_smoke_dispatches_explicit_realtime_provider() -> None:
    selected: list[str] = []
    provider = FakeQuoteProvider(source="mootdx")

    main(
        ["data", "smoke", "--provider", "mootdx"],
        quote_provider_factory=lambda name: selected.append(name) or provider,
    )

    assert selected == ["mootdx"]
```

- [ ] **Step 2: Run the CLI tests and verify the signature/parser failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: new tests fail because `--provider` is required and the injected factory does not accept the current zero-argument call.

- [ ] **Step 3: Add provider construction and CLI routing**

In `src/astock/cli.py`, add imports:

```python
from astock.data.providers.base import QuoteProvider
from astock.data.providers.fallback import FallbackQuoteProvider
from astock.data.providers.tencent import TencentQuoteProvider
```

Change the mootdx import to expose its client factory:

```python
from astock.data.providers.mootdx import MootdxProvider, create_mootdx_client
```

Add the factory after `build_market_data_service`:

```python
def build_quote_provider(name: str) -> QuoteProvider:
    providers: dict[str, Callable[[], QuoteProvider]] = {
        "mootdx": MootdxProvider,
        "tencent": TencentQuoteProvider,
    }
    if name == "auto":
        return FallbackQuoteProvider(
            [
                (
                    "mootdx",
                    lambda: MootdxProvider(client=create_mootdx_client(servers=[])),
                ),
                ("tencent", providers["tencent"]),
            ]
        )
    return providers[name]()
```

Passing `servers=[]` keeps mootdx's single best-IP attempt but skips the exhaustive public-node
loop in `auto` mode. Explicit `--provider mootdx` still constructs `MootdxProvider()` and retains
the full diagnostic behavior.

Change the smoke argument:

```python
smoke.add_argument(
    "--provider",
    choices=["auto", "baostock", "mootdx", "tencent"],
    default="auto",
)
```

Change the `main` injection and realtime branch:

```python
def main(
    argv: Sequence[str] | None = None,
    service_factory: Callable[[], MarketDataService] = build_market_data_service,
    quote_provider_factory: Callable[[str], QuoteProvider] = build_quote_provider,
) -> int:
    # existing sync and baostock branches stay unchanged
    quotes = quote_provider_factory(args.provider).quotes(["600519.SH"])
    if not quotes:
        raise RuntimeError(f"{args.provider} 未返回实时报价")
    quote = quotes[0]
    print(f"{quote.source} 正常：价格 {quote.price}，时间 {quote.timestamp.isoformat()}")
    return 0
```

- [ ] **Step 4: Run CLI and provider tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/data/providers -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the CLI integration**

```bash
git add src/astock/cli.py tests/test_cli.py
git commit -m "feat: use automatic realtime quote fallback"
```

### Task 4: Verify offline and online behavior

**Files:**
- Modify only if verification exposes a covered defect; add a regression test before any fix.

- [ ] **Step 1: Run the complete offline verification suite**

Run:

```bash
.venv/bin/python -m pytest --cov=astock --cov-report=term-missing
.venv/bin/ruff check .
git diff --check
```

Expected: all tests pass, Ruff reports `All checks passed!`, and `git diff --check` exits 0.

- [ ] **Step 2: Run the standalone Tencent online smoke test**

Run:

```bash
.venv/bin/astock data smoke --provider tencent
```

Expected: output begins with `tencent 正常：价格` and contains an `Asia/Shanghai` timestamp.

- [ ] **Step 3: Run the automatic online fallback smoke test**

Run:

```bash
.venv/bin/astock data smoke
```

Expected: output begins with either `mootdx 正常` or `tencent 正常`; when the known mootdx public nodes remain unavailable, it begins with `tencent 正常`.

- [ ] **Step 4: Verify repository state**

Run:

```bash
git status --short
git log --oneline -6
```

Expected: no uncommitted implementation changes and the three feature commits appear after the design and plan commits.
