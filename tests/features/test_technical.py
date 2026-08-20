import math

import pandas as pd

from astock.features.technical import compute_technical_features


def _frame(rows: int = 30) -> pd.DataFrame:
    close = pd.Series(range(1, rows + 1), dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="B"),
            "open": close - 0.25,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume_shares": [100] * rows,
            "amount_cny": close * 100,
        }
    )


def test_computes_returns_averages_volume_and_obv() -> None:
    features = compute_technical_features(_frame())
    last = features.iloc[-1]

    assert last["return_20"] == 200.0
    assert last["ma_5"] == 28.0
    assert last["volume_ma_20"] == 100.0
    assert last["volume_ratio_20"] == 1.0
    assert last["obv"] == 2_900.0


def test_computes_bollinger_atr_rsi_and_streaks() -> None:
    features = compute_technical_features(_frame())
    last = features.iloc[-1]

    assert last["boll_middle"] == 20.5
    assert math.isclose(last["boll_upper"], 20.5 + 2 * math.sqrt(33.25))
    assert last["atr_14"] == 2.0
    assert last["rsi_14"] == 100.0
    assert last["up_streak"] == 29


def test_features_do_not_change_past_rows_when_future_bars_are_added() -> None:
    short = compute_technical_features(_frame(20))
    full = compute_technical_features(_frame(30)).iloc[:20]

    pd.testing.assert_frame_equal(short, full)
