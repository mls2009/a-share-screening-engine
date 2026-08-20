from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock.data.quality import QualityContext, inspect_rows

TZ = ZoneInfo("Asia/Shanghai")


def _row(timestamp: datetime, **overrides: object) -> dict:
    row = {
        "timestamp": timestamp,
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10,
        "volume_shares": 1,
        "amount_cny": 10,
    }
    row.update(overrides)
    return row


def test_quality_reports_duplicate_and_negative_volume() -> None:
    timestamp = datetime(2026, 8, 20, tzinfo=TZ)
    rows = [_row(timestamp, volume_shares=-1), _row(timestamp)]
    context = QualityContext(valid_trading_dates={date(2026, 8, 20)}, intraday=False)

    assert {issue.code for issue in inspect_rows(rows, context)} == {
        "duplicate_timestamp",
        "negative_volume",
    }


def test_quality_reports_non_monotonic_input_without_blocking_values() -> None:
    rows = [
        _row(datetime(2026, 8, 21, tzinfo=TZ)),
        _row(datetime(2026, 8, 20, tzinfo=TZ)),
    ]
    context = QualityContext(
        valid_trading_dates={date(2026, 8, 20), date(2026, 8, 21)}, intraday=False
    )

    assert [issue.code for issue in inspect_rows(rows, context)] == ["non_monotonic_input"]


def test_quality_reports_market_date_session_amount_and_ohlc_errors() -> None:
    rows = [
        _row(
            datetime(2026, 8, 22, 12, tzinfo=TZ),
            open=10,
            high=9,
            low=11,
            close=10,
            amount_cny=-1,
        )
    ]
    context = QualityContext(valid_trading_dates={date(2026, 8, 20)}, intraday=True)

    assert {issue.code for issue in inspect_rows(rows, context)} == {
        "negative_amount",
        "invalid_ohlc",
        "invalid_trading_date",
        "invalid_session_time",
    }


def test_zero_volume_suspension_bar_is_valid() -> None:
    rows = [_row(datetime(2026, 8, 20, tzinfo=TZ), volume_shares=0, amount_cny=0)]
    context = QualityContext(valid_trading_dates={date(2026, 8, 20)}, intraday=False)

    assert inspect_rows(rows, context) == []
