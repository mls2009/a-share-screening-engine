from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from astock.data.providers.mootdx import MootdxProvider

TZ = ZoneInfo("Asia/Shanghai")


class FakeMootdxClient:
    def __init__(self) -> None:
        self.requested_symbols: list[str] = []

    def quotes(self, symbol: list[str]) -> pd.DataFrame:
        self.requested_symbols = symbol
        return pd.DataFrame(
            [
                {
                    "code": "600519",
                    "price": 10.5,
                    "vol": 123,
                    "amount": 129_150,
                    "servertime": "10:05:00.000",
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
