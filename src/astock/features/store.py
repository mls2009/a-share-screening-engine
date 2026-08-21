import json
from datetime import date

import pandas as pd

from astock.domain.market import Timeframe
from astock.features.zones import nearest_zones
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
    "high_history",
    "low_20",
    "low_60",
    "low_250",
    "low_history",
    "max_drawdown_20",
    "max_drawdown_60",
    "max_drawdown_250",
    "up_streak",
    "down_streak",
    "volume_change_1",
    "volume_change_5",
    "volume_change_20",
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
            incoming = pd.DataFrame(rows, columns=columns)
            self.connection.register("_incoming_market_features", incoming)
            try:
                self.connection.execute(
                    f"""
                    insert or replace into market_features ({', '.join(columns)})
                    select {', '.join(columns)} from _incoming_market_features
                    """
                )
            finally:
                self.connection.unregister("_incoming_market_features")

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
        result = dict(zip([column[0] for column in cursor.description], row, strict=True))
        return self._enrich(symbol, timeframe, result)

    def read_history(
        self,
        symbol: str,
        timeframe: Timeframe,
        end: date,
        limit: int,
        feature_version: str = "v1",
        *,
        enrich: bool = True,
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
        rows = [self._decode(dict(zip(columns, row, strict=True))) for row in cursor.fetchall()]
        return [self._enrich(symbol, timeframe, row) for row in rows] if enrich else rows

    def read_histories(
        self,
        symbols: list[str],
        timeframe: Timeframe,
        end: date,
        limit: int,
        feature_version: str = "v1",
        *,
        enrich: bool = True,
    ) -> dict[str, list[dict]]:
        if not symbols:
            return {}
        cursor = self.connection.execute(
            """
            select * exclude (history_rank) from (
              select *, row_number() over (
                partition by symbol order by feature_date desc
              ) as history_rank
              from market_features
              where symbol in (select unnest(?))
                and timeframe = ? and feature_version = ? and feature_date <= ?
            ) where history_rank <= ?
            order by symbol, feature_date desc
            """,
            [symbols, timeframe.value, feature_version, end, limit],
        )
        columns = [column[0] for column in cursor.description]
        histories = {symbol: [] for symbol in symbols}
        for values in cursor.fetchall():
            row = self._decode(dict(zip(columns, values, strict=True)))
            if enrich:
                row = self._enrich(row["symbol"], timeframe, row)
            histories[row["symbol"]].append(row)
        return histories

    @staticmethod
    def _decode(row: dict) -> dict:
        decoded = dict(row)
        extra = decoded.pop("extra", None)
        if extra:
            decoded.update(json.loads(extra) if isinstance(extra, str) else extra)
        listing_days = decoded.get("listing_trade_days")
        if listing_days is not None:
            if listing_days <= 30:
                decoded["listing_stage"] = "new"
            elif listing_days <= 250:
                decoded["listing_stage"] = "secondary_new"
            else:
                decoded["listing_stage"] = "established"
        return decoded

    def _enrich(self, symbol: str, timeframe: Timeframe, row: dict) -> dict:
        enriched = self._decode(row)

        security = self.connection.execute(
            """
            select s.name, s.board, st.is_st, st.is_suspended, st.previous_close,
                   st.limit_up, st.limit_down
            from symbols s
            left join lateral (
              select is_st, is_suspended, previous_close, limit_up, limit_down
              from security_status
              where symbol = s.symbol and trade_date <= ?
              order by trade_date desc limit 1
            ) st on true
            where s.symbol = ?
            """,
            [enriched["feature_date"], symbol],
        ).fetchone()
        if security:
            for key, value in zip(
                (
                    "name",
                    "board",
                    "is_st",
                    "is_suspended",
                    "previous_close",
                    "limit_up",
                    "limit_down",
                ),
                security,
                strict=True,
            ):
                enriched[key] = value

        feature_date = enriched["feature_date"]
        patterns = self.connection.execute(
            """
            select pattern_type, strength from pattern_events
            where symbol = ? and timeframe = ? and event_date = ?
            order by strength desc, pattern_type
            """,
            [symbol, timeframe.value, feature_date],
        ).fetchall()
        if not patterns:
            enriched["pattern_type"] = None
            enriched["pattern_strength"] = None
        else:
            pattern_types = [pattern[0] for pattern in patterns]
            enriched["pattern_type"] = (
                pattern_types[0] if len(pattern_types) == 1 else pattern_types
            )
            enriched["pattern_strength"] = patterns[0][1]

        close = enriched.get("close")
        zones = nearest_zones(self.connection, symbol, timeframe, feature_date, limit_each=1)
        for kind in ("support", "resistance"):
            matching = next((zone for zone in zones if zone["zone_kind"] == kind), None)
            key = f"{kind}_distance"
            if close in {None, 0} or matching is None:
                enriched[key] = None
            elif kind == "support":
                enriched[key] = (close - matching["center_price"]) / close * 100
            else:
                enriched[key] = (matching["center_price"] - close) / close * 100
        return enriched
