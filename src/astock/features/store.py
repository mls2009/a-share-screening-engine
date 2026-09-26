import json
from datetime import date

import pandas as pd

from astock.data.periods import final_session, period_end
from astock.domain.market import Timeframe
from astock.features.chart_shapes import chart_shape_features
from astock.features.ma250_reclaim import MA250_RECLAIM_METRIC, MA250_RECLAIM_HITS, MA250_RECLAIM_EXTENDED_METRIC, MA250_RECLAIM_EXTENDED_HITS, reclaim_hits, shadow_support_hits
from astock.features.ma_support import MA_SUPPORT_METRIC, MA_SUPPORT_HITS, support_hits
from astock.features.ma_pierce import (
    MA_PIERCE_2Y_HITS, MA_PIERCE_10D_METRIC, MA_PIERCE_10D_HITS,
    MA_PIERCE_2Y_METRIC,
    ma_pierce_2y_hits,
    ma_pierce_features,
)
from astock.features.price_action import price_action_features, weekly_price_action_features
from astock.features.vacuum import vacuum_features
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
    "is_limit_up",
    "limit_up_count_5_max_60",
    "limit_up_burst_5_count_60",
    "return_10_max_60",
    "ma_10_slope_abs_5",
    "ma_20_slope_abs_5",
    "ma_10_range_5",
    "ma_20_range_5",
    "ma_10_20_distance",
]


def _value(value: object) -> object:
    return None if pd.isna(value) else value.item() if hasattr(value, "item") else value


class MarketFeatureStore:
    def __init__(self, database: Database) -> None:
        self.connection = database.connection

    def _period_filter(self, timeframe: Timeframe, end: date) -> tuple[str, list]:
        if timeframe not in {Timeframe.WEEK, Timeframe.MONTH}:
            return "", []
        dates = [row[0] for row in self.connection.execute(
            "select distinct feature_date from market_features "
            "where timeframe = ? and feature_date <= ?", [timeframe.value, end],
        ).fetchall()]
        calendar = dict(self.connection.execute(
            "select trade_date, is_open from trading_calendar where trade_date between ? and ?",
            [min(dates, default=end), period_end(end, timeframe)],
        ).fetchall())
        completed = [day for day in dates if day == final_session(day, timeframe, calendar)]
        return " and feature_date in (select unnest(?::date[]))", [completed]

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
        period_filter, period_args = self._period_filter(timeframe, as_of)
        cursor = self.connection.execute(
            f"""
            select * from market_features
            where symbol = ? and timeframe = ? and feature_version = ? and feature_date <= ?
              {period_filter}
            order by feature_date desc limit 1
            """,
            [symbol, timeframe.value, feature_version, as_of, *period_args],
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
        include_vacuum: bool = False,
        include_price_action: bool = False,
        include_shapes: bool = False,
        include_ma_pierce: bool = False,
        include_ma_support: bool = False,
        include_ma250_reclaim: bool = False,
    ) -> list[dict]:
        period_filter, period_args = self._period_filter(timeframe, end)
        cursor = self.connection.execute(
            f"""
            select * from market_features
            where symbol = ? and timeframe = ? and feature_version = ? and feature_date <= ?
              {period_filter}
            order by feature_date desc limit ?
            """,
            [symbol, timeframe.value, feature_version, end, *period_args, limit],
        )
        columns = [column[0] for column in cursor.description]
        rows = [self._decode(dict(zip(columns, row, strict=True))) for row in cursor.fetchall()]
        if include_vacuum and timeframe == Timeframe.DAY:
            self.attach_vacuum({symbol: rows}, end, feature_version)
        if include_shapes and timeframe == Timeframe.DAY:
            self.attach_shapes({symbol: rows}, end, feature_version)
        if include_ma250_reclaim and timeframe == Timeframe.DAY:
            self.attach_ma250_reclaim({symbol: rows}, end, feature_version)
        if include_ma_support and timeframe == Timeframe.DAY:
            self.attach_ma_support({symbol: rows}, end, feature_version)
        if include_ma_pierce and timeframe == Timeframe.DAY:
            self.attach_ma_pierce({symbol: rows}, end, feature_version)
        if include_price_action and timeframe in {Timeframe.DAY, Timeframe.WEEK}:
            self.attach_price_action({symbol: rows}, end, feature_version, timeframe)
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
        include_vacuum: bool = False,
        include_price_action: bool = False,
        include_shapes: bool = False,
        include_ma_pierce: bool = False,
        include_ma_support: bool = False,
        include_ma250_reclaim: bool = False,
        progress=None,
    ) -> dict[str, list[dict]]:
        if not symbols:
            return {}
        period_filter, period_args = self._period_filter(timeframe, end)
        cursor = self.connection.execute(
            f"""
            select * exclude (history_rank) from (
              select *, row_number() over (
                partition by symbol order by feature_date desc
              ) as history_rank
              from market_features
              where symbol in (select unnest(?))
                and timeframe = ? and feature_version = ? and feature_date <= ?
                {period_filter}
            ) where history_rank <= ?
            order by symbol, feature_date desc
            """,
            [symbols, timeframe.value, feature_version, end, *period_args, limit],
        )
        columns = [column[0] for column in cursor.description]
        histories = {symbol: [] for symbol in symbols}
        for values in cursor.fetchall():
            row = self._decode(dict(zip(columns, values, strict=True)))
            if enrich:
                row = self._enrich(row["symbol"], timeframe, row)
            histories[row["symbol"]].append(row)
        if include_vacuum and timeframe == Timeframe.DAY:
            self.attach_vacuum(histories, end, feature_version, progress=progress)
        if include_shapes and timeframe == Timeframe.DAY:
            self.attach_shapes(histories, end, feature_version, progress=progress)
        if include_ma250_reclaim and timeframe == Timeframe.DAY:
            self.attach_ma250_reclaim(histories, end, feature_version)
        if include_ma_support and timeframe == Timeframe.DAY:
            self.attach_ma_support(histories, end, feature_version)
        if include_ma_pierce and timeframe == Timeframe.DAY:
            self.attach_ma_pierce(histories, end, feature_version)
        if include_price_action and timeframe in {Timeframe.DAY, Timeframe.WEEK}:
            self.attach_price_action(histories, end, feature_version, timeframe, progress=progress)
        return histories

    def attach_ma250_reclaim(self, histories, end, feature_version="v1"):
        boundary = (pd.Timestamp(end) - pd.DateOffset(years=2)).date()
        recent_days = {str(row[0]) for row in self.connection.execute(
            """select distinct feature_date from market_features
               where timeframe = '1d' and feature_version = ? and feature_date <= ?
               order by feature_date desc limit 5""", [feature_version, end]).fetchall()}
        symbols = [symbol for symbol, rows in histories.items() if rows]
        for offset in range(0, len(symbols), 64):
            batch = symbols[offset:offset + 64]
            cursor = self.connection.execute(
                """with bars as (
                       select symbol, feature_date, open, low, close, ma_250,
                              lead(feature_date) over (partition by symbol order by feature_date) next_date
                       from market_features
                       where symbol in (select unnest(?)) and timeframe = '1d'
                         and feature_version = ? and feature_date <= ?
                   ) select symbol, feature_date, open, low, close, ma_250 from bars
                   where feature_date >= ? or next_date >= ?
                   order by symbol, feature_date""", [batch, feature_version, end, boundary, boundary])
            records = {symbol: [] for symbol in batch}
            for symbol, day, opening, low, closing, average in cursor.fetchall():
                records[symbol].append({'feature_date': day, 'open': opening, 'low': low, 'close': closing, 'ma_250': average})
            for symbol, rows in records.items():
                frame = pd.DataFrame(rows)
                original_hits = reclaim_hits(frame, boundary)
                extended_hits = sorted(reclaim_hits(frame, boundary, max_days=3) + shadow_support_hits(frame, boundary), key=lambda hit: hit["date"])
                extended_hits = [hit for hit in extended_hits if hit["date"] in recent_days]
                histories[symbol][0].update({MA250_RECLAIM_METRIC: bool(original_hits), MA250_RECLAIM_HITS: original_hits,
                                             MA250_RECLAIM_EXTENDED_METRIC: bool(extended_hits), MA250_RECLAIM_EXTENDED_HITS: extended_hits})

    def attach_ma_support(self, histories, end, feature_version="v1"):
        boundary = (pd.Timestamp(end) - pd.DateOffset(years=2)).date()
        start = boundary
        recent_days = {str(row[0]) for row in self.connection.execute(
            """select distinct feature_date from market_features
               where timeframe = '1d' and feature_version = ? and feature_date <= ?
               order by feature_date desc limit 5""", [feature_version, end]).fetchall()}
        symbols = [symbol for symbol, rows in histories.items() if rows]
        for offset in range(0, len(symbols), 64):
            batch = symbols[offset:offset + 64]
            cursor = self.connection.execute(
                """select symbol, feature_date, open, high, close, low, ma_120, ma_250
                   from market_features
                   where symbol in (select unnest(?)) and timeframe = '1d'
                     and feature_version = ? and feature_date between ? and ?
                   order by symbol, feature_date""", [batch, feature_version, start, end])
            columns = [column[0] for column in cursor.description]
            records = {symbol: [] for symbol in batch}
            for values in cursor.fetchall():
                row = dict(zip(columns, values, strict=True))
                records[row.pop("symbol")].append(row)
            for symbol, rows in records.items():
                hits = support_hits(pd.DataFrame(rows)) if rows else []
                hits = [hit for hit in hits if hit["date"] in recent_days]
                histories[symbol][0].update({MA_SUPPORT_METRIC: bool(hits), MA_SUPPORT_HITS: hits})

    def attach_ma_pierce(
        self, histories: dict[str, list[dict]], end: date, feature_version: str = "v1",
    ) -> None:
        """单K穿线逐行判定；近两年变体回读两年窗口扫描完整形态，标记在最新一行。"""
        for rows in histories.values():
            for row, derived in zip(rows, ma_pierce_features(rows), strict=True):
                row.update(derived)
        symbols = [symbol for symbol, rows in histories.items() if rows]
        if not symbols:
            return
        start = (pd.Timestamp(end) - pd.DateOffset(years=2) - pd.Timedelta(days=30)).date()
        for offset in range(0, len(symbols), 64):
            batch = symbols[offset:offset + 64]
            cursor = self.connection.execute(
                """
                select symbol, feature_date, open, close, volume, volume_ma_20,
                       ma_5, ma_10, ma_20, ma_30, ma_60, ma_120
                from market_features
                where symbol in (select unnest(?)) and timeframe = '1d' and feature_version = ?
                  and feature_date between ? and ?
                order by symbol, feature_date
                """,
                [batch, feature_version, start, end],
            )
            records: dict[str, list[dict]] = {symbol: [] for symbol in batch}
            for row_values in cursor.fetchall():
                (symbol, day, opening, closing, volume, average_volume,
                 ma5, ma10, ma20, ma30, ma60, ma120) = row_values
                records[symbol].append({
                    "feature_date": day, "open": opening, "close": closing, "volume": volume,
                    "volume_ma_20": average_volume, "ma_5": ma5, "ma_10": ma10, "ma_20": ma20,
                    "ma_30": ma30, "ma_60": ma60, "ma_120": ma120,
                })
            for symbol, rows in records.items():
                targets = histories.get(symbol) or []
                if not targets:
                    continue
                frame = pd.DataFrame(rows)
                if frame.empty:
                    continue
                hits = ma_pierce_2y_hits(frame)
                targets[0][MA_PIERCE_2Y_METRIC] = bool(hits)
                targets[0][MA_PIERCE_2Y_HITS] = hits
                new_hits = ma_pierce_2y_hits(frame, ten_day=True)
                boundary = str((pd.Timestamp(end) - pd.DateOffset(years=2)).date())
                new_hits = [hit for hit in new_hits if boundary <= hit["date"] <= str(end)]
                targets[0][MA_PIERCE_10D_METRIC] = bool(new_hits)
                targets[0][MA_PIERCE_10D_HITS] = new_hits

    def attach_vacuum(self, histories: dict[str, list[dict]], end: date, feature_version: str = "v1", progress=None) -> None:
        """Read narrow OHLC batches; derive on demand without rewriting stored features."""
        symbols = [symbol for symbol, rows in histories.items() if rows]
        for offset in range(0, len(symbols), 64):
            batch = symbols[offset:offset + 64]
            records = {symbol: [] for symbol in batch}
            cursor = self.connection.execute("""
                select symbol, feature_date, high, low, close, volume from market_features
                where symbol in (select unnest(?)) and timeframe = '1d'
                  and feature_version = ? and feature_date <= ?
                order by symbol, feature_date
            """, [batch, feature_version, end])
            for symbol, stamp, high, low, close, volume in cursor.fetchall():
                records[symbol].append(dict(feature_date=stamp, high=high, low=low, close=close, volume=volume))
            for symbol, rows in records.items():
                targets = {row["feature_date"]: row for row in histories[symbol]}
                for row, derived in zip(rows, vacuum_features(rows), strict=True):
                    if row["feature_date"] in targets:
                        targets[row["feature_date"]].update(derived)
            if progress:
                progress("计算真空区", min(offset+64, len(symbols)), len(symbols))

    def attach_price_action(self, histories: dict[str, list[dict]], end: date, feature_version: str = "v1", timeframe: Timeframe = Timeframe.DAY, progress=None) -> None:
        symbols = [symbol for symbol, rows in histories.items() if rows]
        for offset in range(0, len(symbols), 64):
            batch = symbols[offset:offset + 64]
            records = {symbol: [] for symbol in batch}
            cursor = self.connection.execute("""
                select symbol, feature_date, open, high, low, close from market_features
                where symbol in (select unnest(?)) and timeframe = '1d'
                  and feature_version = ? and feature_date <= ?
                order by symbol, feature_date
            """, [batch, feature_version, end])
            for symbol, stamp, opening, high, low, close in cursor.fetchall():
                records[symbol].append(dict(feature_date=stamp, open=opening, high=high, low=low, close=close))
            weekly_records = {}
            if timeframe == Timeframe.WEEK:
                weekly_records = self.read_histories(batch, timeframe, end, 10000, feature_version, enrich=False)
            for symbol, rows in records.items():
                targets = {row["feature_date"]: row for row in histories[symbol]}
                if timeframe == Timeframe.WEEK:
                    weekly = weekly_records[symbol]
                    weekly.reverse()
                    derived_rows = weekly_price_action_features(weekly, rows, set(targets))
                    rows = weekly
                else:
                    derived_rows = price_action_features(rows, set(targets), include_year=True)
                for row, derived in zip(rows, derived_rows, strict=True):
                    if row["feature_date"] in targets:
                        targets[row["feature_date"]].update(derived)
            if progress:
                progress("计算裸K及历史形态", min(offset+64, len(symbols)), len(symbols))

    def attach_shapes(self, histories, end, feature_version="v1", progress=None):
        symbols = [symbol for symbol, rows in histories.items() if rows]
        for offset in range(0, len(symbols), 64):
            batch = symbols[offset:offset+64]
            records = {symbol: [] for symbol in batch}
            earliest = min(row['feature_date'] for symbol in batch for row in histories[symbol])
            start = (pd.Timestamp(earliest)-pd.DateOffset(years=2)-pd.Timedelta(days=30)).date()
            for symbol, stamp, high, low in self.connection.execute(
                "select symbol,feature_date,high,low from market_features where symbol in (select unnest(?)) "
                "and timeframe='1d' and feature_version=? and feature_date between ? and ? order by symbol,feature_date",
                [batch,feature_version,start,end]).fetchall():
                records[symbol].append(dict(feature_date=stamp,high=high,low=low))
            for symbol, rows in records.items():
                targets = {r['feature_date']:r for r in histories[symbol]}
                for row, feature in zip(rows,chart_shape_features(rows),strict=True):
                    if row['feature_date'] in targets:
                        targets[row['feature_date']].update(feature)
            if progress:
                progress("计算三角形与震荡区间", min(offset+64, len(symbols)), len(symbols))

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
