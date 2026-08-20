from datetime import date, datetime, time
from importlib import import_module
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security

SHANGHAI = ZoneInfo("Asia/Shanghai")
ADJUSTMENTS = {
    Adjustment.NONE: "",
    Adjustment.QFQ: "qfq",
    Adjustment.HFQ: "hfq",
}


class AkShareProvider:
    def __init__(self, module: Any | None = None) -> None:
        self.module = module

    def _module(self) -> Any:
        if self.module is None:
            self.module = import_module("akshare")
        return self.module

    def securities_on(self, on_date: date) -> list[Security]:
        frame = self._module().stock_info_bj_name_code()
        securities = []
        for row in frame.to_dict("records"):
            raw_date = row.get("上市日期")
            listed_on = pd.Timestamp(raw_date).date() if pd.notna(raw_date) else None
            securities.append(
                Security(
                    symbol=f"{str(row['证券代码']).zfill(6)}.BJ",
                    name=str(row["证券简称"]),
                    exchange="BJ",
                    board="beijing",
                    listed_on=listed_on,
                    is_listed=listed_on is None or listed_on <= on_date,
                    source="akshare-bse",
                )
            )
        return [security for security in securities if security.is_listed]

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> list[Bar]:
        if not symbol.endswith(".BJ") or timeframe != Timeframe.DAY:
            raise ValueError("AkShare fallback supports Beijing daily bars only")
        code = symbol.split(".")[0]
        frame = self._module().stock_zh_a_daily(
            symbol=f"bj{code}",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=ADJUSTMENTS[adjustment],
        )
        return [
            Bar(
                symbol=symbol,
                timestamp=datetime.combine(
                    pd.Timestamp(row["date"]).date(), time(15), tzinfo=SHANGHAI
                ),
                timeframe=Timeframe.DAY,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume_shares=int(float(row["volume"])),
                amount_cny=float(row["amount"]),
                adjustment=adjustment,
                source="akshare-sina",
            )
            for row in frame.to_dict("records")
        ]
