from collections.abc import Callable
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from mootdx.quotes import Quotes

from astock.domain.market import Quote

SHANGHAI = ZoneInfo("Asia/Shanghai")


def create_mootdx_client() -> Any:
    return Quotes.factory(
        market="std",
        multithread=True,
        heartbeat=True,
        bestip=True,
    )


class MootdxProvider:
    def __init__(
        self,
        client: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client if client is not None else create_mootdx_client()
        self.now = now if now is not None else lambda: datetime.now(SHANGHAI)

    def _timestamp(self, server_time: str) -> datetime:
        parsed_time = time.fromisoformat(server_time)
        local_date = self.now().astimezone(SHANGHAI).date()
        return datetime.combine(local_date, parsed_time, tzinfo=SHANGHAI)

    def quotes(self, symbols: list[str]) -> list[Quote]:
        by_code = {symbol.split(".")[0]: symbol for symbol in symbols}
        frame = self.client.quotes(symbol=list(by_code))
        if frame is None or frame.empty:
            return []

        quotes = []
        for row in frame.to_dict("records"):
            code = str(row["code"])
            if code not in by_code:
                continue
            volume_lots = row.get("vol", row.get("volume", 0))
            quotes.append(
                Quote(
                    symbol=by_code[code],
                    timestamp=self._timestamp(str(row["servertime"])),
                    price=float(row["price"]),
                    volume_shares=int(float(volume_lots)) * 100,
                    amount_cny=float(row["amount"]),
                    source="mootdx",
                )
            )
        return quotes
