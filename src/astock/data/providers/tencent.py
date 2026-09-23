import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from astock.domain.market import MarketSnapshot, Quote

SHANGHAI = ZoneInfo("Asia/Shanghai")
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/"
Transport = Callable[[str, float], bytes]


class TencentQuoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotBatchResult:
    snapshots: tuple[MarketSnapshot, ...]
    requested: int
    failed_batches: int


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

    @staticmethod
    def _optional_float(fields: list[str], index: int, multiplier: float = 1) -> float | None:
        if index >= len(fields) or fields[index].strip() in {"", "-", "--", "N/A"}:
            return None
        try:
            value = float(fields[index]) * multiplier
            return value if math.isfinite(value) else None
        except ValueError as error:
            raise TencentQuoteError(f"invalid optional field at index {index}") from error

    @classmethod
    def _parse_snapshot(cls, symbol: str, fields: list[str]) -> MarketSnapshot:
        quote = cls._parse_quote(symbol, fields)
        return MarketSnapshot(
            symbol=symbol,
            timestamp=quote.timestamp,
            price=quote.price,
            previous_close=cls._optional_float(fields, 4),
            open=cls._optional_float(fields, 5),
            high=cls._optional_float(fields, 33),
            low=cls._optional_float(fields, 34),
            volume_shares=quote.volume_shares,
            amount_cny=quote.amount_cny,
            turnover_rate=cls._optional_float(fields, 38),
            pe_ratio=cls._optional_float(fields, 39),
            pb_ratio=cls._optional_float(fields, 46),
            float_market_cap=cls._optional_float(fields, 44, 100_000_000),
            total_market_cap=cls._optional_float(fields, 45, 100_000_000),
            volume_ratio=cls._optional_float(fields, 49),
            source="tencent",
        )

    def snapshots(self, symbols: list[str]) -> list[MarketSnapshot]:
        if not symbols:
            return []
        keys = [to_tencent_symbol(symbol) for symbol in symbols]
        url = f"{TENCENT_QUOTE_URL}?{urlencode({'q': ','.join(keys)}, safe=',')}"
        try:
            text = self.transport(url, self.timeout).decode("gbk")
        except Exception as error:
            raise TencentQuoteError("Tencent snapshot request failed") from error
        requested = dict(zip(keys, symbols, strict=True))
        parsed: dict[str, MarketSnapshot] = {}
        for key, raw_fields in re.findall(r'v_([^=]+)="([^"]*)";', text):
            if key not in requested:
                continue
            fields = raw_fields.split("~")
            if len(fields) < 38 or not fields[0]:
                continue
            parsed[key] = self._parse_snapshot(requested[key], fields)
        return [parsed[key] for key in keys if key in parsed]

    def snapshot_many(
        self, symbols: list[str], batch_size: int = 60
    ) -> SnapshotBatchResult:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        snapshots: list[MarketSnapshot] = []
        failed_batches = 0
        for offset in range(0, len(symbols), batch_size):
            try:
                snapshots.extend(self.snapshots(symbols[offset : offset + batch_size]))
            except TencentQuoteError:
                failed_batches += 1
        return SnapshotBatchResult(tuple(snapshots), len(symbols), failed_batches)
