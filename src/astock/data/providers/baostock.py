from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import ModuleType
from zoneinfo import ZoneInfo

import baostock

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security

SHANGHAI = ZoneInfo("Asia/Shanghai")
ADJUST_FLAGS = {
    Adjustment.NONE: "3",
    Adjustment.QFQ: "2",
    Adjustment.HFQ: "1",
}
DAILY_FIELDS = "date,code,open,high,low,close,volume,amount,adjustflag"
MINUTE_FIELDS = "date,time,code,open,high,low,close,volume,amount,adjustflag"


class BaoStockError(RuntimeError):
    pass


class BaoStockProvider:
    def __init__(self, module: ModuleType = baostock) -> None:
        self.module = module

    @contextmanager
    def _session(self) -> Iterator[None]:
        login = self.module.login()
        self._ensure_success(login)
        try:
            yield
        finally:
            self.module.logout()

    @staticmethod
    def _ensure_success(response: object) -> None:
        if getattr(response, "error_code", None) != "0":
            message = getattr(response, "error_msg", "unknown BaoStock error")
            raise BaoStockError(str(message))

    @staticmethod
    def _provider_symbol(symbol: str) -> str:
        code, exchange = symbol.split(".")
        return f"{exchange.lower()}.{code}"

    @staticmethod
    def _symbol(provider_symbol: str) -> str:
        exchange, code = provider_symbol.split(".")
        return f"{code}.{exchange.upper()}"

    def _query_rows(self, method_name: str, **kwargs: str) -> list[dict[str, str]]:
        with self._session():
            result = getattr(self.module, method_name)(**kwargs)
            self._ensure_success(result)
            rows = []
            while result.next():
                rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
            return rows

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> list[Bar]:
        if timeframe == Timeframe.DAY:
            fields = DAILY_FIELDS
            frequency = "d"
        elif timeframe == Timeframe.MIN_5:
            fields = MINUTE_FIELDS
            frequency = "5"
        else:
            raise ValueError(f"unsupported BaoStock timeframe: {timeframe}")

        with self._session():
            result = self.module.query_history_k_data_plus(
                code=self._provider_symbol(symbol),
                fields=fields,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency=frequency,
                adjustflag=ADJUST_FLAGS[adjustment],
            )
            self._ensure_success(result)
            rows = []
            while result.next():
                rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))

        def timestamp(row: dict[str, str]) -> datetime:
            if timeframe == Timeframe.DAY:
                return datetime.combine(
                    date.fromisoformat(row["date"]), time(15), tzinfo=SHANGHAI
                )
            return datetime.strptime(row["time"][:14], "%Y%m%d%H%M%S").replace(
                tzinfo=SHANGHAI
            )

        return [
            Bar(
                symbol=self._symbol(row["code"]),
                timestamp=timestamp(row),
                timeframe=timeframe,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume_shares=int(float(row["volume"])),
                amount_cny=float(row["amount"]),
                adjustment=adjustment,
                source="baostock",
            )
            for row in rows
        ]

    def trading_dates(self, start: date, end: date) -> set[date]:
        rows = self._query_rows(
            "query_trade_dates", start_date=start.isoformat(), end_date=end.isoformat()
        )
        return {
            date.fromisoformat(row["calendar_date"])
            for row in rows
            if row["is_trading_day"] == "1"
        }

    def symbols_on(self, on_date: date) -> list[dict]:
        rows = self._query_rows("query_all_stock", day=on_date.isoformat())
        return [
            {
                "symbol": self._symbol(row["code"]),
                "name": row["code_name"],
                "trade_status": row["tradeStatus"],
                "source": "baostock",
            }
            for row in rows
        ]

    def securities_on(self, on_date: date) -> list[Security]:
        trade_rows = self._query_rows("query_all_stock", day=on_date.isoformat())
        basic_rows = self._query_rows("query_stock_basic")
        basics = {row["code"]: row for row in basic_rows if row.get("code")}
        securities = []
        for row in trade_rows:
            provider_symbol = row["code"]
            basic = basics.get(provider_symbol, {})
            if basic.get("type") not in {None, "", "1"}:
                continue
            symbol = self._symbol(provider_symbol)
            listed_on = (
                date.fromisoformat(basic["ipoDate"])
                if basic.get("ipoDate")
                else None
            )
            delisted_on = (
                date.fromisoformat(basic["outDate"])
                if basic.get("outDate")
                else None
            )
            is_listed = delisted_on is None or delisted_on > on_date
            securities.append(
                Security(
                    symbol=symbol,
                    name=row.get("code_name") or basic.get("code_name") or symbol,
                    exchange=symbol.split(".")[1],
                    board=self._board(symbol),
                    listed_on=listed_on,
                    delisted_on=delisted_on,
                    is_listed=is_listed,
                    is_suspended=row.get("tradeStatus") != "1",
                )
            )
        return securities

    def adjustment_factors(self, symbol: str, start: date, end: date) -> list[dict]:
        rows = self._query_rows(
            "query_adjust_factor",
            code=self._provider_symbol(symbol),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        return [
            {
                "symbol": self._symbol(row["code"]),
                "trade_date": date.fromisoformat(row["dividOperateDate"]),
                "forward_factor": float(row["foreAdjustFactor"]),
                "backward_factor": float(row["backAdjustFactor"]),
                "source": "baostock",
            }
            for row in rows
        ]

    def corporate_actions(self, symbol: str, start: date, end: date) -> list[dict]:
        actions = []
        for year in range(start.year, end.year + 1):
            rows = self._query_rows(
                "query_dividend_data",
                code=self._provider_symbol(symbol),
                year=str(year),
                yearType="operate",
            )
            for row in rows:
                raw_date = row["dividOperateDate"]
                if not raw_date:
                    continue
                ex_date = date.fromisoformat(raw_date)
                if not start <= ex_date <= end:
                    continue
                share_ratio = Decimal(row["dividStocksPs"] or "0") + Decimal(
                    row["dividReserveToStockPs"] or "0"
                )
                actions.append(
                    {
                        "symbol": self._symbol(row["code"]),
                        "ex_date": ex_date,
                        "cash_per_share": float(row["dividCashPsBeforeTax"] or 0),
                        "share_ratio": float(share_ratio),
                        "source": "baostock",
                    }
                )
        return actions

    @staticmethod
    def _board(symbol: str) -> str:
        code, exchange = symbol.split(".")
        if exchange == "BJ" or code.startswith(("4", "8", "9")):
            return "beijing"
        if code.startswith(("300", "301")):
            return "chinext"
        if code.startswith(("688", "689")):
            return "star"
        return "main"

    @staticmethod
    def _price_limit(previous_close: float, rate: Decimal) -> tuple[float, float]:
        price = Decimal(str(previous_close))
        quantizer = Decimal("0.01")
        upper = (price * (1 + rate)).quantize(quantizer, rounding=ROUND_HALF_UP)
        lower = (price * (1 - rate)).quantize(quantizer, rounding=ROUND_HALF_UP)
        return float(upper), float(lower)

    def _listing_date(self, symbol: str) -> date | None:
        rows = self._query_rows("query_stock_basic", code=self._provider_symbol(symbol))
        if not rows or not rows[0].get("ipoDate"):
            return None
        return date.fromisoformat(rows[0]["ipoDate"])

    def security_status(self, symbol: str, start: date, end: date) -> list[dict]:
        rows = self._query_rows(
            "query_history_k_data_plus",
            code=self._provider_symbol(symbol),
            fields="date,code,preclose,tradestatus,isST",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        listing_date = self._listing_date(symbol)
        board = self._board(symbol)
        unlimited_dates: set[date] = set()
        if listing_date is not None and start <= listing_date + timedelta(days=60):
            listing_trade_dates = sorted(self.trading_dates(listing_date, end))
            unlimited_count = 1 if board == "beijing" else 5
            unlimited_dates = set(listing_trade_dates[:unlimited_count])

        statuses = []
        for row in rows:
            is_st = row["isST"] == "1"
            rate = Decimal("0.05") if is_st else {
                "main": Decimal("0.10"),
                "chinext": Decimal("0.20"),
                "star": Decimal("0.20"),
                "beijing": Decimal("0.30"),
            }[board]
            trade_date = date.fromisoformat(row["date"])
            previous_close = float(row["preclose"]) if row["preclose"] else None
            if trade_date in unlimited_dates or previous_close is None:
                limit_up, limit_down = None, None
            else:
                limit_up, limit_down = self._price_limit(previous_close, rate)
            statuses.append(
                {
                    "symbol": self._symbol(row["code"]),
                    "trade_date": trade_date,
                    "board": board,
                    "is_st": is_st,
                    "is_suspended": row["tradestatus"] != "1",
                    "previous_close": previous_close,
                    "limit_up": limit_up,
                    "limit_down": limit_down,
                }
            )
        return statuses
