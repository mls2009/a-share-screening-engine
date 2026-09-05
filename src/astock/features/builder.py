from bisect import bisect_right
from datetime import date
from threading import Lock

import pandas as pd

from astock.data.aggregate import aggregate_daily
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features.patterns import detect_patterns, persist_pattern_events
from astock.features.store import MarketFeatureStore
from astock.features.technical import compute_burst_features, compute_technical_features
from astock.features.zones import ZONE_RULE_VERSION, detect_zones, replace_auto_zones
from astock.storage.bars import BarStore
from astock.storage.database import Database

_CHART_ZONE_BUILD_LOCK = Lock()


def _bar_frame(bars: list[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume_shares": bar.volume_shares,
                "amount_cny": bar.amount_cny,
            }
            for bar in bars
        ]
    )


def chart_base_timeframe(timeframe: Timeframe) -> Timeframe:
    if timeframe in {
        Timeframe.MIN_5,
        Timeframe.MIN_15,
        Timeframe.MIN_30,
        Timeframe.MIN_60,
    }:
        return Timeframe.MIN_5
    return Timeframe.DAY


class FeatureBuilder:
    def __init__(
        self,
        bar_store: BarStore,
        feature_store: MarketFeatureStore,
        database: Database,
    ) -> None:
        self.bar_store = bar_store
        self.feature_store = feature_store
        self.connection = database.connection

    def ensure_chart_zones(
        self, symbol: str, timeframe: Timeframe, as_of: date
    ) -> float | None:
        base = chart_base_timeframe(timeframe)
        latest_base = self.bar_store.read_latest(
            symbol, base, Adjustment.QFQ, as_of, final_only=True
        )
        if latest_base is None:
            return None
        source_revision = self.bar_store.revision(symbol, base, as_of)
        if source_revision is None:
            return None

        zone_date = latest_base.timestamp.date()
        with _CHART_ZONE_BUILD_LOCK:
            fresh = self.connection.execute(
                """
                select latest_bar_at = ? and source_revision = ?
                from zone_detection_batches
                where symbol = ? and timeframe = ? and as_of_date = ?
                  and rule_version = ?
                """,
                [
                    latest_base.timestamp,
                    source_revision,
                    symbol,
                    timeframe.value,
                    zone_date,
                    ZONE_RULE_VERSION,
                ],
            ).fetchone()
            if fresh is not None and fresh[0]:
                return float(latest_base.close)

            source = [
                bar
                for bar in self.bar_store.read(symbol, base, Adjustment.QFQ)
                if bar.timestamp.date() <= as_of and bar.is_final
            ]
            bars = (
                source
                if timeframe == base
                else MarketDataService.derive(source, timeframe)
            )
            if not bars:
                return None
            frame = _bar_frame(bars)
            zones = detect_zones(
                frame,
                zone_date,
                timeframe=timeframe,
                rule_version=ZONE_RULE_VERSION,
            )
            replace_auto_zones(
                self.connection,
                symbol,
                timeframe,
                zone_date,
                zones,
                rule_version=ZONE_RULE_VERSION,
                latest_bar_at=latest_base.timestamp,
                source_revision=source_revision,
            )
        return float(latest_base.close)

    def build_symbol(self, symbol: str, as_of: date) -> None:
        bars = [
            bar
            for bar in self.bar_store.read(symbol, Timeframe.DAY, Adjustment.QFQ)
            if bar.timestamp.date() <= as_of and bar.is_final
        ]
        if not bars:
            return
        source_revision = self.bar_store.revision(
            symbol, Timeframe.DAY, bars[-1].timestamp.date()
        )
        if source_revision is None:
            return
        daily = _bar_frame(bars)
        date_index = [pd.Timestamp(value).date() for value in daily["timestamp"]]
        listed_row = self.connection.execute(
            "select listed_on, board, name from symbols where symbol = ?", [symbol]
        ).fetchone()
        listed_on = listed_row[0] if listed_row else None
        board = listed_row[1] if listed_row and listed_row[1] else self._board(symbol)
        name = listed_row[2] if listed_row else symbol
        statuses = {
            row[0]: row[1:]
            for row in self.connection.execute(
                """
                select trade_date, is_st, previous_close, limit_up
                from security_status where symbol = ? and trade_date <= ?
                """,
                [symbol, as_of],
            ).fetchall()
        }

        frames = {
            Timeframe.DAY: daily,
            Timeframe.WEEK: aggregate_daily(daily, "week"),
            Timeframe.MONTH: aggregate_daily(daily, "month"),
        }
        for timeframe, frame in frames.items():
            features = compute_technical_features(frame)
            listing_days = []
            for timestamp in features["timestamp"]:
                count = bisect_right(date_index, pd.Timestamp(timestamp).date())
                if listed_on is None or listed_on < date_index[0]:
                    count = max(251, count)
                listing_days.append(count)
            features["listing_trade_days"] = listing_days
            features["is_new"] = features["listing_trade_days"] <= 30
            features["is_secondary_new"] = features["listing_trade_days"].between(31, 250)
            if timeframe == Timeframe.DAY:
                thresholds = self._limit_up_thresholds(
                    features, board, name, statuses
                )
                features = compute_burst_features(features, thresholds)
            self.feature_store.upsert(symbol, timeframe, features)
            persist_pattern_events(
                self.connection,
                symbol,
                timeframe,
                detect_patterns(frame),
            )
            zone_date = pd.Timestamp(frame.iloc[-1]["timestamp"]).date()
            replace_auto_zones(
                self.connection,
                symbol,
                timeframe,
                zone_date,
                detect_zones(frame, zone_date, timeframe=timeframe),
                rule_version=ZONE_RULE_VERSION,
                latest_bar_at=bars[-1].timestamp,
                source_revision=source_revision,
            )

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
    def _limit_up_thresholds(
        features: pd.DataFrame,
        board: str,
        name: str,
        statuses: dict[date, tuple],
    ) -> pd.Series:
        normalized_name = name.upper().lstrip("*")
        fallback_rate = 5.0 if normalized_name.startswith("ST") else {
            "main": 10.0,
            "chinext": 20.0,
            "star": 20.0,
            "beijing": 30.0,
        }.get(board, 10.0)
        unlimited_days = 1 if board == "beijing" else 5
        values: list[float | None] = []
        for row in features.to_dict("records"):
            feature_date = pd.Timestamp(row["timestamp"]).date()
            status = statuses.get(feature_date)
            if status is not None:
                _, previous_close, limit_up = status
                values.append(
                    (limit_up / previous_close - 1) * 100
                    if limit_up is not None and previous_close not in {None, 0}
                    else None
                )
            elif row["listing_trade_days"] <= unlimited_days:
                values.append(None)
            else:
                values.append(fallback_rate)
        return pd.Series(values, index=features.index, dtype="float64")
