from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from astock.data.providers.mootdx import MootdxProvider, create_mootdx_client

TZ = ZoneInfo("Asia/Shanghai")


class FakeMootdxClient:
    def __init__(self, server_time: str = "10:05:00.000") -> None:
        self.requested_symbols: list[str] = []
        self.server_time = server_time

    def quotes(self, symbol: list[str]) -> pd.DataFrame:
        self.requested_symbols = symbol
        return pd.DataFrame(
            [
                {
                    "code": "600519",
                    "price": 10.5,
                    "vol": 123,
                    "amount": 129_150,
                    "servertime": self.server_time,
                }
            ]
        )


def test_mootdx_converts_a_share_lots_and_server_time() -> None:
    client = FakeMootdxClient()
    now = lambda: datetime(2026, 8, 20, 10, 5, 1, tzinfo=TZ)

    quote = MootdxProvider(client, now=now).quotes(["600519.SH"])[0]

    assert quote.volume_shares == 12_300
    assert quote.price == 10.5
    assert quote.timestamp.isoformat() == "2026-08-20T10:05:00+08:00"
    assert quote.symbol == "600519.SH"
    assert client.requested_symbols == ["600519"]


def test_mootdx_accepts_single_digit_server_hour() -> None:
    client = FakeMootdxClient(server_time="9:53:29.767")
    now = lambda: datetime(2026, 8, 20, 9, 54, tzinfo=TZ)

    quote = MootdxProvider(client, now=now).quotes(["600519.SH"])[0]

    assert quote.timestamp.isoformat() == "2026-08-20T09:53:29.767000+08:00"


def test_client_creation_falls_back_to_another_server() -> None:
    attempts: list[tuple[str, int] | None] = []

    class WorkingClient:
        def quotes(self, symbol: list[str]) -> pd.DataFrame:
            return pd.DataFrame([{"code": symbol[0]}])

    expected_client = WorkingClient()

    def factory(**kwargs):
        attempts.append(kwargs.get("server"))
        if kwargs.get("server") == ("2.2.2.2", 7709):
            return expected_client
        raise ConnectionError("unavailable")

    client = create_mootdx_client(
        factory=factory,
        servers=[("1.1.1.1", 7709), ("2.2.2.2", 7709)],
    )

    assert client is expected_client
    assert attempts == [None, ("1.1.1.1", 7709), ("2.2.2.2", 7709)]


def test_client_creation_rejects_connected_server_with_empty_quotes() -> None:
    attempts: list[tuple[str, int] | None] = []

    class EmptyClient:
        def quotes(self, symbol: list[str]) -> pd.DataFrame:
            return pd.DataFrame()

    class WorkingClient:
        def quotes(self, symbol: list[str]) -> pd.DataFrame:
            return pd.DataFrame([{"code": symbol[0]}])

    empty_client = EmptyClient()
    working_client = WorkingClient()

    def factory(**kwargs):
        attempts.append(kwargs.get("server"))
        return empty_client if kwargs.get("server") is None else working_client

    client = create_mootdx_client(factory=factory, servers=[("1.1.1.1", 7709)])

    assert client is working_client
    assert attempts == [None, ("1.1.1.1", 7709)]
