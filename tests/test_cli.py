from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock.cli import build_quote_provider, main
from astock.domain.market import Adjustment, Quote, Timeframe


class FakeService:
    def __init__(self) -> None:
        self.reference_call: tuple | None = None
        self.history_call: tuple | None = None

    def sync_reference(self, symbols: list[str], start: date, end: date) -> None:
        self.reference_call = (symbols, start, end)

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> list:
        self.history_call = (symbol, timeframe, start, end, adjustment)
        return []


def test_data_sync_dispatches_normalized_request(capsys) -> None:
    service = FakeService()

    exit_code = main(
        [
            "data",
            "sync",
            "--symbol",
            "600519.SH",
            "--timeframe",
            "15m",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-20",
            "--adjustment",
            "qfq",
        ],
        service_factory=lambda: service,
    )

    assert exit_code == 0
    assert service.reference_call == (
        ["600519.SH"],
        date(2026, 8, 1),
        date(2026, 8, 20),
    )
    assert service.history_call == (
        "600519.SH",
        Timeframe.MIN_15,
        date(2026, 8, 1),
        date(2026, 8, 20),
        Adjustment.QFQ,
    )
    assert "同步完成" in capsys.readouterr().out


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


def test_auto_provider_limits_mootdx_to_best_server_attempt(monkeypatch) -> None:
    server_arguments: list[list] = []
    selected_client = object()

    def fake_create_mootdx_client(*, servers):
        server_arguments.append(servers)
        return selected_client

    class FakeMootdxProvider(FakeQuoteProvider):
        def __init__(self, client=None) -> None:
            super().__init__(source="mootdx")
            self.client = client

    monkeypatch.setattr("astock.cli.create_mootdx_client", fake_create_mootdx_client)
    monkeypatch.setattr("astock.cli.MootdxProvider", FakeMootdxProvider)

    quotes = build_quote_provider("auto").quotes(["600519.SH"])

    assert quotes[0].source == "mootdx"
    assert server_arguments == [[]]
