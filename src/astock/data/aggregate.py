from typing import Literal

import pandas as pd


def aggregate_intraday(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    data = frame.copy().sort_values("timestamp")
    timestamps = pd.to_datetime(data["timestamp"])
    session_minutes = timestamps.dt.hour.map(lambda hour: 9 * 60 + 30 if hour < 12 else 13 * 60)
    session_start = timestamps.dt.normalize() + pd.to_timedelta(session_minutes, unit="m")
    elapsed_seconds = (timestamps - session_start).dt.total_seconds().astype(int)
    bucket_number = ((elapsed_seconds - 1).clip(lower=0) // (minutes * 60)) + 1
    data["session"] = session_start
    data["bucket"] = session_start + pd.to_timedelta(bucket_number * minutes, unit="m")

    return (
        data.groupby(["session", "bucket"], as_index=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume_shares=("volume_shares", "sum"),
            amount_cny=("amount_cny", "sum"),
        )
        .rename(columns={"bucket": "timestamp"})
        .drop(columns=["session"])
    )


def aggregate_daily(
    frame: pd.DataFrame, period: Literal["week", "month"]
) -> pd.DataFrame:
    data = frame.copy().sort_values("timestamp").set_index("timestamp")
    rule = {"week": "W-FRI", "month": "ME"}[period]
    return (
        data.resample(rule)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume_shares=("volume_shares", "sum"),
            amount_cny=("amount_cny", "sum"),
        )
        .dropna(subset=["open"])
        .reset_index()
    )
