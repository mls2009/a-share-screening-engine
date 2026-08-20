import json
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from astock.domain.market import Timeframe


@dataclass(frozen=True)
class PatternEvent:
    event_date: date
    pattern_type: str
    strength: float
    body_ratio: float
    upper_shadow_ratio: float
    lower_shadow_ratio: float
    amplitude_ratio: float
    rule_version: str
    parameters: dict[str, float]


def detect_patterns(bars: pd.DataFrame, rule_version: str = "v1") -> list[PatternEvent]:
    data = bars.copy().sort_values("timestamp").reset_index(drop=True)
    events: list[PatternEvent] = []

    def add(index: int, pattern_type: str, strength: float, **parameters: float) -> None:
        row = data.iloc[index]
        candle_range = max(float(row["high"] - row["low"]), 1e-12)
        body = abs(float(row["close"] - row["open"]))
        upper = float(row["high"] - max(row["open"], row["close"]))
        lower = float(min(row["open"], row["close"]) - row["low"])
        previous_close = float(data.iloc[index - 1]["close"]) if index else float(row["close"])
        events.append(
            PatternEvent(
                event_date=pd.Timestamp(row["timestamp"]).date(),
                pattern_type=pattern_type,
                strength=round(min(max(strength, 0), 1), 6),
                body_ratio=body / candle_range,
                upper_shadow_ratio=upper / candle_range,
                lower_shadow_ratio=lower / candle_range,
                amplitude_ratio=candle_range / max(abs(previous_close), 1e-12),
                rule_version=rule_version,
                parameters=parameters,
            )
        )

    for index, row in data.iterrows():
        candle_range = max(float(row["high"] - row["low"]), 1e-12)
        body = abs(float(row["close"] - row["open"]))
        upper = float(row["high"] - max(row["open"], row["close"]))
        lower = float(min(row["open"], row["close"]) - row["low"])
        body_ratio = body / candle_range
        if body_ratio <= 0.1:
            add(index, "doji", 1 - body_ratio / 0.1, max_body_ratio=0.1)
        if upper >= 2 * max(body, 1e-12) and upper / candle_range >= 0.5:
            add(index, "long_upper_shadow", upper / candle_range, shadow_to_body=2)
        if lower >= 2 * max(body, 1e-12) and lower / candle_range >= 0.5:
            add(index, "long_lower_shadow", lower / candle_range, shadow_to_body=2)
        if lower >= 2 * max(body, 1e-12) and upper <= max(body, candle_range * 0.1):
            add(index, "hammer", lower / candle_range, shadow_to_body=2)

        if index >= 1:
            previous = data.iloc[index - 1]
            bullish = row["close"] > row["open"]
            bearish = row["close"] < row["open"]
            previous_bullish = previous["close"] > previous["open"]
            previous_bearish = previous["close"] < previous["open"]
            if (
                bullish
                and previous_bearish
                and row["open"] <= previous["close"]
                and row["close"] >= previous["open"]
            ):
                add(index, "bullish_engulfing", body_ratio)
            if (
                bearish
                and previous_bullish
                and row["open"] >= previous["close"]
                and row["close"] <= previous["open"]
            ):
                add(index, "bearish_engulfing", body_ratio)
            previous_midpoint = (previous["open"] + previous["close"]) / 2
            if bullish and previous_bearish and previous["close"] < row["close"] < previous["open"] and row["close"] > previous_midpoint:
                add(index, "piercing", body_ratio)
            if bearish and previous_bullish and previous["open"] < row["close"] < previous["close"] and row["close"] < previous_midpoint:
                add(index, "dark_cloud_cover", body_ratio)

        if index >= 2:
            three = data.iloc[index - 2 : index + 1]
            bullish_rows = three["close"] > three["open"]
            bearish_rows = three["close"] < three["open"]
            increasing = three["close"].is_monotonic_increasing
            decreasing = three["close"].is_monotonic_decreasing
            if bool(bullish_rows.all()) and increasing:
                add(index, "three_white_soldiers", 1.0)
            if bool(bearish_rows.all()) and decreasing:
                add(index, "three_black_crows", 1.0)
            first, middle, current = (three.iloc[position] for position in range(3))
            middle_body = abs(middle["close"] - middle["open"])
            middle_range = max(middle["high"] - middle["low"], 1e-12)
            if first["close"] < first["open"] and middle_body / middle_range <= 0.3 and current["close"] > current["open"] and current["close"] > (first["open"] + first["close"]) / 2:
                add(index, "morning_star", body_ratio)
            if first["close"] > first["open"] and middle_body / middle_range <= 0.3 and current["close"] < current["open"] and current["close"] < (first["open"] + first["close"]) / 2:
                add(index, "evening_star", body_ratio)

        if index >= 20:
            consolidation = data.iloc[index - 20 : index]
            range_ratio = (
                consolidation["high"].max() - consolidation["low"].min()
            ) / consolidation["close"].mean()
            if row["close"] > consolidation["high"].max() and range_ratio <= 0.15:
                add(index, "consolidation_breakout", 1 - range_ratio / 0.15)
    return events


def persist_pattern_events(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: Timeframe,
    events: list[PatternEvent],
) -> None:
    if not events:
        return
    columns = [
        "symbol",
        "timeframe",
        "event_date",
        "pattern_type",
        "rule_version",
        "strength",
        "body_ratio",
        "upper_shadow_ratio",
        "lower_shadow_ratio",
        "amplitude_ratio",
        "parameters",
    ]
    incoming = pd.DataFrame(
        [
            (
                symbol,
                timeframe.value,
                event.event_date,
                event.pattern_type,
                event.rule_version,
                event.strength,
                event.body_ratio,
                event.upper_shadow_ratio,
                event.lower_shadow_ratio,
                event.amplitude_ratio,
                json.dumps(event.parameters),
            )
            for event in events
        ],
        columns=columns,
    )
    connection.register("_incoming_pattern_events", incoming)
    try:
        connection.execute(
            f"""
            insert or replace into pattern_events ({', '.join(columns)})
            select {', '.join(columns)} from _incoming_pattern_events
            """
        )
    finally:
        connection.unregister("_incoming_pattern_events")
