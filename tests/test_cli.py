import json
from datetime import date, datetime
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from astock.cli import build_quote_provider, main
from astock.domain.market import Adjustment, Quote, Timeframe
from astock.screening.evaluator import TruthValue


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


class FakeMarketSync:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, end: date, years: int):
        self.calls.append((end, years))
        return SimpleNamespace(
            job_id=UUID("00000000-0000-0000-0000-000000000001"),
            total=2,
            succeeded=2,
            failed=0,
            status="completed",
        )


def test_data_sync_market_dispatches_full_market_job(capsys) -> None:
    service = FakeMarketSync()

    exit_code = main(
        ["data", "sync-market", "--years", "3", "--end", "2026-08-20"],
        market_sync_factory=lambda: service,
    )

    assert exit_code == 0
    assert service.calls == [(date(2026, 8, 20), 3)]
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["succeeded"] == 2


class FakeScreening:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def validate(self, tree):
        return []

    def run(self, tree, *, as_of: date, mode: str, limit: int, offset: int):
        self.calls.append((tree.metric, as_of, mode, limit, offset))
        explanation = SimpleNamespace(result=TruthValue.TRUE, actual=35)
        return SimpleNamespace(
            run_id=UUID("00000000-0000-0000-0000-000000000002"),
            universe_size=5000,
            realtime_covered=4990,
            failed_batches=1,
            status="completed",
            matches=[SimpleNamespace(symbol="600001.SH", rank=1, explanation=explanation)],
        )


def test_screen_run_reads_safe_condition_json_and_dispatches_live_mode(
    tmp_path, capsys
) -> None:
    definition = tmp_path / "screen.json"
    definition.write_text(
        json.dumps(
            {
                "kind": "condition",
                "metric": "return_20",
                "timeframe": "1d",
                "operator": "gte",
                "right": {"kind": "constant", "value": 30, "unit": "percent"},
            }
        ),
        encoding="utf-8",
    )
    service = FakeScreening()

    exit_code = main(
        [
            "screen",
            "run",
            str(definition),
            "--mode",
            "live",
            "--as-of",
            "2026-08-20",
        ],
        screening_service_factory=lambda: service,
    )

    assert exit_code == 0
    assert service.calls == [("return_20", date(2026, 8, 20), "live", 100, 0)]
    assert json.loads(capsys.readouterr().out)["matches"][0]["symbol"] == "600001.SH"
