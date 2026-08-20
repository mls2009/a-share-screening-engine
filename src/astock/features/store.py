import json
from datetime import date

import pandas as pd

from astock.domain.market import Timeframe
from astock.storage.database import Database

FEATURE_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "return_20",
    "return_60",
    "return_120",
    "return_250",
    "volume_ma_5",
    "volume_ma_20",
    "volume_ma_60",
    "volume_ratio_20",
    "ma_5",
    "ma_10",
    "ma_20",
    "ma_30",
    "ma_60",
    "ma_120",
    "ma_250",
    "macd",
    "macd_signal",
    "macd_hist",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "rsi_14",
    "boll_upper",
    "boll_middle",
    "boll_lower",
    "atr_14",
    "obv",
    "amplitude",
    "volatility_20",
    "listing_trade_days",
    "is_new",
    "is_secondary_new",
]
EXTRA_COLUMNS = [
    "high_20",
    "high_60",
    "high_250",
    "low_20",
    "low_60",
    "low_250",
    "max_drawdown_20",
    "max_drawdown_60",
    "max_drawdown_250",
    "up_streak",
    "down_streak",
]


def _value(value: object) -> object:
    return None if pd.isna(value) else value.item() if hasattr(value, "item") else value


class MarketFeatureStore:
    def __init__(self, database: Database) -> None:
        self.connection = database.connection

    def upsert(
        self,
        symbol: str,
        timeframe: Timeframe,
        features: pd.DataFrame,
        feature_version: str = "v1",
    ) -> None:
        columns = ["symbol", "timeframe", "feature_date", "feature_version", *FEATURE_COLUMNS, "extra"]
        placeholders = ", ".join("?" for _ in columns)
        rows = []
        for record in features.to_dict("records"):
            extra = {key: _value(record.get(key)) for key in EXTRA_COLUMNS}
            rows.append(
                [
                    symbol,
                    timeframe.value,
                    pd.Timestamp(record["timestamp"]).date(),
                    feature_version,
                    *[_value(record.get(key)) for key in FEATURE_COLUMNS],
                    json.dumps(extra, ensure_ascii=False),
                ]
            )
        if rows:
            self.connection.executemany(
                f"insert or replace into market_features ({', '.join(columns)}) values ({placeholders})",
                rows,
            )

    def read_latest(
        self,
        symbol: str,
        timeframe: Timeframe,
        as_of: date,
        feature_version: str = "v1",
    ) -> dict | None:
        cursor = self.connection.execute(
            """
            select * from market_features
            where symbol = ? and timeframe = ? and feature_version = ? and feature_date <= ?
            order by feature_date desc limit 1
            """,
            [symbol, timeframe.value, feature_version, as_of],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([column[0] for column in cursor.description], row, strict=True))

    def read_history(
        self,
        symbol: str,
        timeframe: Timeframe,
        end: date,
        limit: int,
        feature_version: str = "v1",
    ) -> list[dict]:
        cursor = self.connection.execute(
            """
            select * from market_features
            where symbol = ? and timeframe = ? and feature_version = ? and feature_date <= ?
            order by feature_date desc limit ?
            """,
            [symbol, timeframe.value, feature_version, end, limit],
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
