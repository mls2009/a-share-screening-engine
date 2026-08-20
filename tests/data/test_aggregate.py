import pandas as pd

from astock.data.aggregate import aggregate_daily, aggregate_intraday


def test_fifteen_minute_bars_do_not_cross_lunch() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-08-20 11:25", "2026-08-20 11:30", "2026-08-20 13:05"]
            ),
            "open": [10, 11, 20],
            "high": [11, 12, 21],
            "low": [9, 10, 19],
            "close": [11, 12, 21],
            "volume_shares": [100, 200, 300],
            "amount_cny": [1_000, 2_200, 6_000],
        }
    )

    result = aggregate_intraday(frame, minutes=15)

    assert len(result) == 2
    assert result.iloc[0].timestamp == pd.Timestamp("2026-08-20 11:30")
    assert result.iloc[0].volume_shares == 300
    assert result.iloc[1].timestamp == pd.Timestamp("2026-08-20 13:15")
    assert result.iloc[1].open == 20


def test_daily_bars_aggregate_to_friday_ending_week() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-08-17", periods=5, freq="D"),
            "open": [10, 11, 12, 13, 14],
            "high": [11, 12, 13, 14, 15],
            "low": [9, 10, 11, 12, 13],
            "close": [10.5, 11.5, 12.5, 13.5, 14.5],
            "volume_shares": [100, 200, 300, 400, 500],
            "amount_cny": [1_000, 2_000, 3_000, 4_000, 5_000],
        }
    )

    result = aggregate_daily(frame, period="week")

    assert result.to_dict("records") == [
        {
            "timestamp": pd.Timestamp("2026-08-21"),
            "open": 10,
            "high": 15,
            "low": 9,
            "close": 14.5,
            "volume_shares": 1_500,
            "amount_cny": 15_000,
        }
    ]


def test_daily_bars_keep_calendar_months_separate() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-30", "2026-02-02"]),
            "open": [10, 20],
            "high": [11, 21],
            "low": [9, 19],
            "close": [10.5, 20.5],
            "volume_shares": [100, 200],
            "amount_cny": [1_000, 4_000],
        }
    )

    result = aggregate_daily(frame, period="month")

    assert list(result["timestamp"]) == [
        pd.Timestamp("2026-01-30"),
        pd.Timestamp("2026-02-02"),
    ]


def test_weekly_bar_uses_last_actual_trading_day() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-10-08", "2026-10-09"]),
            "open": [10, 11],
            "high": [11, 12],
            "low": [9, 10],
            "close": [10.5, 11.5],
            "volume_shares": [100, 200],
            "amount_cny": [1_000, 2_000],
        }
    )

    result = aggregate_daily(frame.iloc[:1], period="week")

    assert result.iloc[0].timestamp == pd.Timestamp("2026-10-08")
