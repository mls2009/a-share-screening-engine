from collections.abc import Callable, Sequence
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from mootdx.consts import HQ_HOSTS
from mootdx.quotes import Quotes

from astock.domain.market import Quote

SHANGHAI = ZoneInfo("Asia/Shanghai")


class MootdxConnectionError(ConnectionError):
    pass


def _client_has_quotes(client: Any) -> bool:
    try:
        frame = client.quotes(symbol=["000001"])
        return frame is not None and not frame.empty
    except Exception:  # noqa: BLE001 - an invalid public server must be skipped
        return False


def _close_client(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()


def create_mootdx_client(
    factory: Callable[..., Any] = Quotes.factory,
    servers: Sequence[tuple[str, int]] | None = None,
) -> Any:
    candidates = (
        list(servers)
        if servers is not None
        else [(str(host[1]), int(host[2])) for host in HQ_HOSTS]
    )
    errors: list[Exception] = []
    try:
        candidate = factory(
            market="std",
            multithread=True,
            heartbeat=True,
            bestip=True,
            timeout=3,
        )
        if _client_has_quotes(candidate):
            return candidate
        _close_client(candidate)
        errors.append(MootdxConnectionError("selected server returned empty quotes"))
    except Exception as error:  # noqa: BLE001 - provider failures vary by selected server
        errors.append(error)

    for server in candidates:
        try:
            candidate = factory(
                market="std",
                multithread=True,
                heartbeat=True,
                bestip=False,
                server=server,
                timeout=3,
            )
            if _client_has_quotes(candidate):
                return candidate
            _close_client(candidate)
            errors.append(MootdxConnectionError(f"server {server[0]} returned empty quotes"))
        except Exception as error:  # noqa: BLE001 - continue to the next public server
            errors.append(error)

    raise MootdxConnectionError(f"all {len(candidates) + 1} mootdx servers failed") from errors[-1]


class MootdxProvider:
    def __init__(
        self,
        client: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client if client is not None else create_mootdx_client()
        self.now = now if now is not None else lambda: datetime.now(SHANGHAI)

    def _timestamp(self, server_time: str) -> datetime:
        hour, remainder = server_time.split(":", maxsplit=1)
        parsed_time = time.fromisoformat(f"{int(hour):02d}:{remainder}")
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
