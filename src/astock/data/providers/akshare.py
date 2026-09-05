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

    def index_history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[Bar]:
        code, exchange = symbol.split(".")
        if timeframe == Timeframe.DAY:
            frame = self._module().stock_zh_index_daily_em(
                symbol=f"{exchange.lower()}{code}",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            rows = frame.rename(
                columns={
                    "date": "timestamp",
                    "volume": "volume_shares",
                    "amount": "amount_cny",
                }
            ).to_dict("records")
            timestamps = [
                datetime.combine(
                    pd.Timestamp(row["timestamp"]).date(), time(15), tzinfo=SHANGHAI
                )
                for row in rows
            ]
            volume_multiplier = 1
        elif timeframe == Timeframe.MIN_5:
            frame = self._module().index_zh_a_hist_min_em(
                symbol=code,
                period="5",
                start_date=f"{start.isoformat()} 00:00:00",
                end_date=f"{end.isoformat()} 23:59:59",
            )
            rows = frame.rename(
                columns={
                    "时间": "timestamp",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume_shares",
                    "成交额": "amount_cny",
                }
            ).to_dict("records")
            timestamps = [
                pd.Timestamp(row["timestamp"]).to_pydatetime().replace(tzinfo=SHANGHAI)
                for row in rows
            ]
            volume_multiplier = 100
        else:
            raise ValueError(f"unsupported index timeframe: {timeframe}")

        return [
            Bar(
                symbol=symbol,
                timestamp=timestamp,
                timeframe=timeframe,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume_shares=int(float(row["volume_shares"]) * volume_multiplier),
                amount_cny=float(row["amount_cny"]),
                adjustment=Adjustment.NONE,
                source="akshare-eastmoney-index",
            )
            for row, timestamp in zip(rows, timestamps, strict=True)
        ]
