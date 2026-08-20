import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
    with urlopen(url, timeout=timeout) as response:
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
        try:
            price = float(fields[3])
            volume_shares = int(float(fields[36])) * 100
            amount_cny = float(Decimal(fields[37]) * 10_000)
            timestamp = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(
                tzinfo=SHANGHAI
            )
        except (InvalidOperation, TypeError, ValueError) as error:
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
