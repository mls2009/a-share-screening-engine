from datetime import date

from astock.cli import main
from astock.domain.market import Adjustment, Timeframe


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
