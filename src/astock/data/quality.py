from collections import Counter
from dataclasses import dataclass
from datetime import date, time
from itertools import pairwise


@dataclass(frozen=True)
class QualityIssue:
    code: str
    timestamp: object
    detail: str


@dataclass(frozen=True)
class QualityContext:
    valid_trading_dates: set[date]
    intraday: bool


def inspect_rows(rows: list[dict], context: QualityContext) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    timestamps = [row["timestamp"] for row in rows]

    if any(current < previous for previous, current in pairwise(timestamps)):
        issues.append(
            QualityIssue("non_monotonic_input", timestamps[0], "timestamps not ascending")
        )

    for timestamp, count in Counter(timestamps).items():
        if count > 1:
            issues.append(QualityIssue("duplicate_timestamp", timestamp, f"count={count}"))

    for row in rows:
        timestamp = row["timestamp"]
        if row["volume_shares"] < 0:
            issues.append(QualityIssue("negative_volume", timestamp, "volume < 0"))
        if row["amount_cny"] < 0:
            issues.append(QualityIssue("negative_amount", timestamp, "amount < 0"))
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(
            row["open"], row["close"]
        ):
            issues.append(QualityIssue("invalid_ohlc", timestamp, "OHLC bounds"))
        if timestamp.date() not in context.valid_trading_dates:
            issues.append(QualityIssue("invalid_trading_date", timestamp, "market closed"))
        if context.intraday and not (
            time(9, 30) < timestamp.time() <= time(11, 30)
            or time(13, 0) < timestamp.time() <= time(15, 0)
        ):
            issues.append(
                QualityIssue("invalid_session_time", timestamp, "outside A-share session")
            )

    return issues
